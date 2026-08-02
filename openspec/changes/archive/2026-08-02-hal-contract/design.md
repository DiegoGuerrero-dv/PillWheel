# Design: hal-contract

## Objetivo

Completar la capa HAL según la especificación del sistema embebido: `DriverPort` ampliado (OLED, LEDs por slot, sensor de apertura/cierre, init), log estructurado `[hal]` de toda invocación, scheduler que dispara el combo completo (dispense + ring + oled_show + led_on), confirmación de toma **solo** por sensor (`slot_open` + `slot_closed`, sin auto-confirmación), simulación local (botón UI + `POST /api/driver/sim`), y contrato `docs/esp32-contract.md`.

## Arquitectura (sin cambios estructurales)

Se mantiene la estructura actual (`DriverPort` + `DevDriver` + `Scheduler` dentro de `Dev_server.py`, deuda H2 intacta). Cambios aditivos:

- El **driver solo ejecuta y reporta**; el timer/scheduler vive en el backend (regla H4 existente).
- El estado de "qué dosis está esperando confirmación" lo guarda el `DevDriver` (simula el dispositivo: LED encendido + pendiente), porque es estado del hardware simulado.
- El **marcado de toma** sigue pasando por la función global `on_pill_taken` (escribe `taken_log.json` + WS push); el driver la emite cuando confirma por sensor.

## Diseño de `DevDriver`

### Estado interno

```python
self._on_pill_taken   # callback global (existe)
self._events = []     # [{action, ts, kw}, ...] (cambia de tuples a dicts con ts)
self._leds = {}       # slot_id -> bool  (LEDs por slot)
self._pending = {}    # (slot_id, time) -> True  (dosis esperando confirmación del sensor)
self._opened = set()  # slots con apertura reportada (secuencia open → close)
self._oled = None     # último texto mostrado en OLED
self._lock = threading.Lock()  # estado compartido entre scheduler y handler (W1)
```

### Log estructurado

```python
def _log(self, action, result=None, **kw):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    args = ', '.join(f'{k}={v}' for k, v in kw.items())
    print(f'[hal] {ts} {action}({args}) -> {result}')
    self._events.append({'action': action, 'ts': ts, 'kw': kw})
```

Formato de consola: `[hal] 2026-08-02 08:00:00 dispense(slot_id=1, time=08:00) -> True`.

### Métodos

| Método | Comportamiento |
|--------|----------------|
| `init()` | `_log('init')` — arranque del driver |
| `dispense(slot_id, time)` | `_log` + `self._pending[(slot_id, time)] = True` (LED queda esperando; **NO** llama `on_pill_taken`; clave con hora para no pisar dosis múltiples del mismo slot, W2) |
| `ring()` | `_log('ring')` — buzzer |
| `oled_show(slot_id, name, time)` | `_log` + guarda `self._oled` |
| `led_on(slot_id)` | `_log` + `self._leds[slot_id] = True` |
| `led_off(slot_id)` | `_log` + `self._leds[slot_id] = False` |
| `slot_open(slot_id)` | agrega a `_opened` + `_log('slot_open')` — sensor reporta apertura |
| `slot_closed(slot_id)` | `_log`; **solo** si `slot_id in _opened` y hay pendientes → `led_off` + `_on_pill_taken` por cada dosis pendiente del slot + limpia; devuelve `bool` (`confirmed`). Cierre sin apertura previa NO confirma (C1) |
| `pending_slots()` | `list({s for (s, t) in self._pending})` (con lock) |
| `status()` | `{driver, ok, leds, pending: {slot_id: [times]}, oled, last_events}` — `last_events = self._events[-5:][::-1]` (más reciente primero, spec) |

Regla de negocio: `slot_closed` sin apertura previa o sin pendientes solo loguea y devuelve `False`; con secuencia open → close confirma **todas** las dosis pendientes del slot (el compartimiento se resuelve en una apertura) y devuelve `True`.

## Diseño de `DriverPort` (Protocol)

Firmas nuevas (además de `dispense`, `ring`, `status`, `on_pill_taken`):

```python
def init(self) -> None: ...
def oled_show(self, slot_id, name, time) -> None: ...
def led_on(self, slot_id) -> None: ...
def led_off(self, slot_id) -> None: ...
def slot_open(self, slot_id) -> None: ...
def slot_closed(self, slot_id) -> None: ...
```

## Diseño del `Scheduler`

### Combo al disparar una dosis

Al disparar una dosis (después del filtro `enabled` y del dedupe existente):

```python
self.driver.dispense(slot['id'], hhmm)
self.driver.ring()                                   # alarma buzzer
self.driver.oled_show(slot['id'], slot.get('name', ''), hhmm)
self.driver.led_on(slot['id'])                       # LED del slot enciende
```

Orden especificado: dispense → ring → oled_show → led_on. No se toca el mapeo de días ni el filtro `enabled`.

### Re-alarma mientras haya pendientes

Al final del ciclo (después del loop de slots), si `DevDriver` tiene dosis pendientes (`pending_slots()`), el scheduler re-emite `ring()`:

```python
if self.driver.pending_slots():
    self.driver.ring()   # sigue pitando hasta que se confirme la toma
```

El LED ya quedó encendido por `led_on` y permanece hasta `slot_closed`. `DevDriver` agrega:

```python
def pending_slots(self):
    return list(self._pending.keys())
```

## Diseño del endpoint de simulación

En `do_POST` (después de `/api/taken`):

```python
if path == '/api/driver/sim':
    if not self._require_session():
        return
    if not isinstance(body, dict):
        return self._send_json(400, {'error': 'json inválido'})   # W5
    action = body.get('action')
    slot_id = body.get('slot_id')
    if action not in ('open', 'close'):
        return self._send_json(400, {'error': 'acción inválida (open|close)'})
    if not isinstance(slot_id, int) or isinstance(slot_id, bool) or not 1 <= slot_id <= 8:
        return self._send_json(400, {'error': 'slot_id inválido'})  # S1: bool no es slot
    if action == 'open':
        DRIVER.slot_open(slot_id)
        return self._send_json(200, {'ok': True, 'confirmed': False})
    confirmed = DRIVER.slot_closed(slot_id)
    return self._send_json(200, {'ok': True, 'confirmed': confirmed})  # W3
```

- Requiere sesión F1 (es una herramienta de desarrollo del simulador).
- El firmware real NO usa este endpoint: reporta `slot_open`/`slot_closed` vía eventos F2; `POST /api/taken` (V9) sigue intacto.
- Respuesta `200 {"ok": true, "confirmed": bool}`: `confirmed` es `False` para `open` (abrir no confirma) y para un `close` sin apertura previa o sin pendientes (W3: la UI no tosteea éxito falso).

## Diseño de la UI (`script.js`)

- `api.simDriver(slotId, action)`: `POST /api/driver/sim` con `{slot_id, action}` + `authHeaders()`.
- **Modal de dosis pendiente** (overlay tipo bottom-sheet, similar a `#editOverlay`):
  - Detección: al renderizar el dashboard y con un timer (`setInterval` cada ~15 s) se busca la próxima dosis pendiente: `getTodayDoses().find(d => !isTaken(d) && d.time <= now && pendingSlots.includes(d.slotId))` — `pendingSlots` viene de `GET /api/status` (W3: solo aparecen dosis que el scheduler realmente dispensó).
  - Contenido: "Casilla N", hora (`d.time`), nombre de la pastilla, y botón **"Abrir y tomar"**.
  - Acción del botón (delegación de eventos, sin `onclick` con string — respeta V3/XSS):
    1. `simDriver(slotId, 'open')` + `simDriver(slotId, 'close')` (secuencia del sensor).
    2. Toast de éxito **solo si** la respuesta del close trae `confirmed: true`; si no, "No había dosis pendiente en esta casilla" (W3).
    3. Al recibir `on_pill_taken` por WS (o tras el fetch), cerrar el modal y refrescar.
  - **Persistencia ante recarga**: como la confirmación vive en `taken_log.json`, al recargar la página la dosis sigue sin `taken: true` → el modal vuelve a desplegarse (mientras `status().pending` la tenga). No hay estado extra que guardar.
  - Si hay varias dosis pendientes, el modal muestra la más próxima (una a la vez).
  - Las dosis tomadas nunca abren el modal.
  - Logout cierra el modal (`hideDoseModal()` en `handleLogout`, W4).

## Diseño de `docs/esp32-contract.md` (nuevo)

Contrato H4: por cada función del `DriverPort`, tabla con firma Python, comando de red del firmware, payload de ejemplo y auth:

| DriverPort | Comando firmware | Payload |
|------------|------------------|---------|
| `init()` | `POST /init` | `{}` |
| `dispense(slot_id, time)` | `POST /dispense` | `{"slot_id": 1, "time": "08:00"}` |
| `ring()` | `POST /ring` | `{}` |
| `oled_show(slot_id, name, time)` | `POST /oled` | `{"slot_id": 3, "name": "...", "time": "08:00"}` |
| `led_on(slot_id)` | `POST /led` | `{"slot_id": 3, "on": true}` |
| `led_off(slot_id)` | `POST /led` | `{"slot_id": 3, "on": false}` |
| `status()` | `GET /status` | — |
| `slot_open(slot_id)` | `POST /events` | `{"type": "slot_open", "slot_id": 3}` |
| `slot_closed(slot_id)` | `POST /events` | `{"type": "slot_closed", "slot_id": 3}` |
| `on_pill_taken(slot_id, time)` | `POST /api/taken` (backend) | `{"key": "...", "value": true}` |

- Auth de dispositivo: `Authorization: Bearer <DEV_TOKEN>` (Frontera 2).
- El firmware no conoce `/api/*` del backend más que el reporte de tomas; el backend llama al firmware por los comandos de arriba.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `Dev_server.py` | `DriverPort` +6 firmas; `DevDriver` con `_log`/`_leds`/`_pending`/`_oled`, `init`, `pending_slots`, sin auto-confirmación; `status()` con ts; scheduler combo + re-alarma; `POST /api/driver/sim`; `DRIVER.init()` en `main` |
| `index.html` | overlay del modal de dosis pendiente |
| `script.js` | `api.simDriver`, lógica del modal (detección + timer + botón con delegación) |
| `style.css` | estilos del modal y botón "Abrir y tomar" |
| `docs/esp32-contract.md` | nuevo |
| `docs/architecture.md` | sistema embebido + flujo HAL + estado H4 |
| `docs/run-and-test.md` | checklist smoke HAL |

## Flujo de referencia (éxito)

```
08:00 scheduler ──► DRIVER.dispense(1,"08:00") ──► pendiente {1:"08:00"}
                    DRIVER.ring()               [hal] logs
                    DRIVER.oled_show(1,"X","08:00")
                    DRIVER.led_on(1)  → led 1 encendido
UI: aparece el MODAL "Casilla 1 · 08:00 · Abrir y tomar"
mientras no se tome: cada tick del scheduler → DRIVER.ring() de nuevo (sigue pitando)
click "Abrir y tomar" ──► POST /api/driver/sim open  → DRIVER.slot_open(1)   [hal] log
                       ──► POST /api/driver/sim close → DRIVER.slot_closed(1)
                            ├─ led_off(1)            [hal] log
                            └─ on_pill_taken(1,"08:00") → taken_log.json + WS push → modal se cierra
si el usuario recarga sin tomar: la dosis sigue pendiente → modal vuelve a aparecer
```

## Estimación de esfuerzo

- `Dev_server.py`: ~120 líneas nuevas/modificadas (incluye re-alarma y `pending_slots`).
- `script.js` + `index.html` (overlay del modal): ~70 líneas.
- `style.css`: ~20 líneas (modal + botón).
- Docs (esp32-contract, architecture, run-and-test): ~180 líneas.
- Total: ~390 líneas cambiadas. Forecast: **~350–400 líneas, riesgo bajo-medio**. Presupuesto D2 (800) OK; 1 PR único.

## Rollback

Revert del commit. Cambios aditivos sobre el HAL; si se revierte, el `DevDriver` vuelve a la auto-confirmación original (sin necesidad de migración de datos).
