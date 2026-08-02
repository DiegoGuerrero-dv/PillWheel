# Tasks: hal-contract

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350–400 |
| Review budget (D2) | 800 |
| 400-line budget risk | Low-Medium |
| Chained PRs recommended | No |
| Suggested split | 1 PR (cambio cohesivo del HAL) |
| Delivery strategy | 1 PR único (decisión del usuario por tamaño) |
| Chain strategy | n/a |

Decision needed before apply: No
Chained PRs recommended: No
400-line budget risk: Low-Medium

### Dependency Diagram

    main ← PR único (hal-contract)

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Backend HAL (log, DriverPort+, DevDriver, scheduler, sim) | PR único | Verificable con smoke por API + test scheduler |
| 2 | UI modal + CSS | PR único | Misma PR; depende del backend (endpoint sim) |
| 3 | Docs (esp32-contract, architecture, run-and-test) | PR único | Depende de las firmas finales |

## Phase 1: Backend — log estructurado y DriverPort ampliado

- [x] 1.1 `Dev_server.py`: función `_hal_log(action, result, **kw)` — imprime `[hal] {ts} {action}({k=v,...}) -> {result}` y agrega evento `{action, ts, kw}` a la lista de eventos del driver
- [x] 1.2 `Dev_server.py` `DriverPort`: agregar firmas `init()`, `oled_show(slot_id, name, time)`, `led_on(slot_id)`, `led_off(slot_id)`, `slot_open(slot_id)`, `slot_closed(slot_id)`
- [x] 1.3 `Dev_server.py` `DevDriver.__init__`: estado `_leds = {}`, `_pending = {}`, `_oled = None`; `dispense` deja de llamar `on_pill_taken` y pasa a `self._pending[slot_id] = time`
- [x] 1.4 `Dev_server.py` `DevDriver`: `init()`, `oled_show`, `led_on`, `led_off`, `slot_open` (todos con `_log`)
- [x] 1.5 `Dev_server.py` `DevDriver.slot_closed`: si `slot_id in _pending` → `led_off` + `on_pill_taken(slot_id, time)` + limpiar pendiente; si no, solo loguea
- [x] 1.6 `Dev_server.py` `DevDriver.pending_slots()`: devuelve `list(self._pending.keys())`
- [x] 1.7 `Dev_server.py` `DevDriver.status()`: `{driver, ok, leds, pending, oled, last_events}` con `ts` en cada evento

## Phase 2: Backend — scheduler combo + re-alarma + init

- [x] 2.1 `Dev_server.py` `Scheduler.run`: al disparar dosis → `dispense` + `ring` + `oled_show(slot_id, name, hhmm)` + `led_on(slot_id)` (orden especificado)
- [x] 2.2 `Dev_server.py` `Scheduler.run`: al final del ciclo, `if self.driver.pending_slots(): self.driver.ring()` (re-alarma)
- [x] 2.3 `Dev_server.py` `main`: `DRIVER.init()` antes de `SCHED.start()`

## Phase 3: Backend — endpoint de simulación

- [x] 3.1 `Dev_server.py` `do_POST` `/api/driver/sim`: requiere sesión F1; valida `action` en (`open`, `close`) y `slot_id` int 1..8 → 400 si inválido; llama `DRIVER.slot_open/closed`; 200 `{"ok": true}`

## Phase 4: UI — modal de dosis pendiente

- [x] 4.1 `index.html`: overlay `#doseModal` (casilla, hora, nombre, botón "Abrir y tomar")
- [x] 4.2 `script.js` `api.simDriver(slotId, action)`: POST `/api/driver/sim` con `authHeaders`
- [x] 4.3 `script.js`: detección de pendiente — al renderizar + `setInterval` ~15 s: `getTodayDoses().find(d => !isTaken(d) && d.time <= now)` → muestra modal
- [x] 4.4 `script.js`: botón "Abrir y tomar" por delegación de eventos (sin `onclick` string, respeta V3) → `simDriver(slot, 'open')` + `simDriver(slot, 'close')` → cierra modal al confirmar (WS o refresh)
- [x] 4.5 `script.js`: al recargar, si la dosis sigue pendiente (no en `taken_log`) → modal vuelve a aparecer (persistencia natural)
- [x] 4.6 `style.css`: estilos del modal `#doseModal` y botón (tema oscuro, consistente)

## Phase 5: Documentación

- [x] 5.1 `docs/esp32-contract.md` (nuevo): contrato H4 — tabla DriverPort → comando firmware + payload + auth `DEV_TOKEN` (init/dispense/ring/oled/led/status/events)
- [x] 5.2 `docs/architecture.md`: descripción del sistema embebido + flujo HAL (modal + re-alarma) + estado H4 a "documentado"
- [x] 5.3 `docs/run-and-test.md`: checklist smoke — logs `[hal]`, modal (aparece/persiste/tomar), re-alarma, `/api/driver/sim` (válido/400), secuencia sensor→toma

## Phase 6: Verificación

- [x] 6.1 Sintaxis: `node --check script.js` + `python -m py_compile Dev_server.py`
- [x] 6.2 Smoke API: `POST /api/driver/sim` open/close → logs `[hal]` + dosis marcada tomada; acción inválida → 400
- [x] 6.3 Test scheduler: dosis disparada → combo dispense+ring+oled+led; pendiente → re-alarma en ciclo siguiente; confirmada → cesa
- [x] 6.4 Smoke UI: modal aparece al llegar la hora, persiste ante recarga, "Abrir y tomar" cierra modal y tacha dosis
- [x] 6.5 Auditoría fresh del diff (subagente reviewer; fallback manual si devuelve vacío)

## Correcciones por revisión (reviewer, 2026-08-02)

Veredicto: APPROVE WITH FIXES. Defectos corregidos antes de cerrar:

- [x] **C1** `slot_closed` confirmaba sin `slot_open` previo → `_opened` set; el cierre sin apertura NO confirma (test: `test_close_without_open_does_not_confirm`).
- [x] **C2** cero tests automatizados → `test_dev_server.py` (stdlib unittest, 13 tests): auth 401, validación 400, secuencia open→close, doble close no-op, multi-dosis por slot, combo y re-alarma del scheduler.
- [x] **W1** `_pending`/`_leds`/`_events` compartidos entre scheduler y handler sin lock → `threading.Lock` en `DevDriver`.
- [x] **W2** `_pending` por `slot_id` pisaba la primera dosis de un slot con 2 horarios → clave `(slot_id, time)`; el cierre confirma todas las pendientes del slot.
- [x] **W3** modal mostraba dosis nunca dispensadas con falso éxito → endpoint devuelve `confirmed`; la UI solo tosteea éxito si `confirmed`; detección filtra por `status().pending` real.
- [x] **W4** logout dejaba el modal abierto → `hideDoseModal()` en `handleLogout`.
- [x] **W5** body JSON válido no-dict (`null`/`[]`/`"x"`) daba 500 → guard `isinstance(body, dict)` → 400.
- [x] **S1** `slot_id: true` (bool) aceptado como 1 → `isinstance(slot_id, bool)` excluido → 400.
- [x] **S3** `last_events` en orden cronológico vs spec "más reciente primero" → `[::-1]`.
- [x] **S4/S5** docs referenciaban `_hal_log`/`on_pill_taken` en consola → corregido a `_log`/sin claim de consola.
- [x] **S6** contrato listaba `/events` como backend→firmware → corregido (firmware→backend).
- [x] **S8** `_last_fired` sin poda → poda por fecha de hoy en cada ciclo.
- [x] Scheduler stoppable (`stop()`/`_stop`) para tests (sin cambio de comportamiento en producción).

