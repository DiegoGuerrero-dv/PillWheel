# Proposal: hal-contract

## Resumen

Completar la capa HAL del sistema según la **especificación del sistema embebido** provista por el usuario: log estructurado de todas las invocaciones al driver en la consola del backend, conexión de eventos del sistema → hardware (scheduler → buzzer/OLED/LED, sensor → marcado de toma, arranque → init), simulador `DevDriver` completo para ejecución local, y el documento `docs/esp32-contract.md` con las firmas/comandos de la HAL para el firmware real (H4 del action-plan, pendiente).

## Sistema embebido (especificación del hardware)

- 8 slots donde se guardan las dosis.
- Cada slot tiene: un **LED** y un **sensor de movimiento** que detecta cuándo el usuario **abre y cierra** el compartimiento del slot.
- El sistema cuenta con un **buzzer** y una **pantalla OLED pequeña**.

### Interacciones hardware ↔ software

1. Cuando llega el horario del día de tomar una pastilla para la rutina: **suena una alarma con el buzzer**.
2. Además, se envía a la **pantalla OLED** la información de la pastilla que toca y a qué hora debe tomarse (según el slot al que se le marcó la dosis).
3. El slot correspondiente **enciende su LED** cuando llega la hora de tomar la dosis de ese slot.
4. El **sensor de movimiento** mide cuándo el usuario **abre** y **cierra** el compartimiento del slot, para marcar cuándo una píldora fue tomada.

## Motivación

- El HAL existe (`DriverPort` + `DevDriver`) pero el log es un `print` suelto (`[scheduler] dispense ...`) y `status()` solo guarda los últimos 5 eventos en memoria.
- `ring()` está definido en el contrato pero **nunca se invoca** desde ningún evento del sistema.
- La especificación del hardware agrega acciones nuevas: OLED, LED por slot y sensor de apertura/cierre.
- El contrato `docs/esp32-contract.md` quedó pendiente del action-plan (H4) y es necesario para integrar el firmware real.
- El simulador debe ser lo suficientemente completo para que la app sea ejecutable localmente sin hardware.

## Alcance

### In scope

1. **Logging HAL completo**: toda invocación a `DRIVER.*` emite un log con timestamp en la consola del server: `[hal] HH:MM:SS dispense(slot=1, time=08:00) → True`. `status()` expone más eventos (con timestamp) y `/api/status` los muestra.
2. **Eventos del sistema → HAL**:
   - Scheduler llega la hora de una dosis → `DRIVER.dispense(...)`, `DRIVER.ring()` (alarma buzzer) y `DRIVER.oled_show(...)` (info pastilla+hora) y `DRIVER.led_on(slot_id)`.
   - Sensor de movimiento del slot (abre/cierra) → eventos que marcan la toma de la píldora.
   - Arranque del server → log de inicialización del driver (`[hal] init DevDriver (mock GPIO)`).
3. **Funciones HAL nuevas** (deducidas de la especificación del hardware):
   - `oled_show(slot_id, name, time)` — muestra en la OLED la pastilla y hora (según slot).
   - `led_on(slot_id)` — enciende el LED del slot que tiene la dosis en ese momento.
   - `slot_open(slot_id)` — evento: el sensor detectó apertura del compartimiento.
   - `slot_closed(slot_id)` — evento: el sensor detectó cierre del compartimiento (marca la toma).
4. **`DevDriver` simulador local completo**: motor (dispense), buzzer (ring), OLED (oled_show), LEDs por slot (led_on), sensores de apertura/cierre (slot_open/slot_closed), estado; **NO auto-confirma** la toma — la confirmación ocurre solo cuando el sensor (o su simulación) reporta apertura+cierre. Simulación expuesta por el botón "Abrir y tomar" del modal y por `POST /api/driver/sim`.
5. **Modal de dosis pendiente (UI)**: cuando llega la hora de una dosis y no está tomada, se despliega un modal con el slot, la hora y un botón "Abrir y tomar". El modal **persiste ante recarga de la página** mientras la dosis siga pendiente (la confirmación vive en `taken_log.json`).
6. **Re-alarma en hardware**: mientras haya dosis pendientes, el scheduler re-emite `ring()` (el buzzer sigue pitando) y el LED del slot permanece encendido hasta confirmar la toma.
5. **`docs/esp32-contract.md`**: firma de cada método del `DriverPort`, su comando/payload de red equivalente (`POST /dispense`, `POST /ring`, `POST /oled`, `POST /led`, `POST /events`), auth de dispositivo (Frontera 2, `DEV_TOKEN`), y formato de eventos de vuelta (incluye `on_pill_taken` vía `POST /api/taken`).
6. Actualizar `docs/architecture.md` y `docs/run-and-test.md`.

### Out of scope

- Refactor a módulos `core/`/`ports/`/`adapters/` (deuda conocida H2; no cambia en este cambio).
- Integración con firmware real (sin acceso al hardware).
- `Esp32Driver` como adapter alternativo (H5 real) — solo se documenta el contrato.
- Detección fina de "qué píldora salió" vía sensor (el sensor solo mide apertura/cierre; no distingue cantidad).

## Enfoque

- `Dev_server.py`:
  - Función `_hal_log(action, **kw)` que imprime `[hal] {ts} {action}({k=v,...}) → {result}` y agrega un evento con timestamp a `DRIVER._events`.
  - `DriverPort` crece con las funciones deducidas del hardware: `oled_show(slot_id, name, time)`, `led_on(slot_id)`, `led_off(slot_id)` (apagar al cerrar/tomar), `slot_open(slot_id)`, `slot_closed(slot_id)`.
  - `DevDriver` pasa por `_hal_log` en `dispense`, `ring`, `oled_show`, `led_on`/`led_off`, `slot_open`/`slot_closed` y un método `init()` (registra el arranque). `status()` devuelve los últimos N eventos con timestamp. **`dispense` ya no auto-confirma**: la toma se confirma solo con `slot_open` + `slot_closed` (o su simulación). Expone `pending_slots()` para la re-alarma.
  - Endpoint de simulación `POST /api/driver/sim` (solo en modo simulación): `{"slot_id": N, "action": "open"|"close"}` → llama `DRIVER.slot_open/closed(N)`; acción inválida → 400.
  - `Scheduler.run`: al disparar una dosis, llama `DRIVER.dispense(...)`, `DRIVER.ring()`, `DRIVER.oled_show(slot_id, name, time)` y `DRIVER.led_on(slot_id)`; al final del ciclo, si hay pendientes, re-emite `DRIVER.ring()` (re-alarma).
  - `main`: al arrancar, `DRIVER.init()`.
- `index.html`: overlay del modal de dosis pendiente.
- `script.js`: detección de dosis pendiente (timer ~15 s + al renderizar), modal con slot/hora/nombre y botón "Abrir y tomar" (delegación de eventos, sin XSS); persistencia natural ante recarga (la confirmación vive en `taken_log.json`).
- `docs/esp32-contract.md` (nuevo): contrato H4 con firma + comando de red + payload + auth para cada función del `DriverPort`.
- `docs/architecture.md`: diagrama de flujo HAL + tabla de estado actualizada (H4 pasa a "documentado") + descripción del sistema embebido.
- `docs/run-and-test.md`: checklist smoke del logging HAL y de la secuencia sensor→toma + modal.

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `Dev_server.py` | Modificado: `_hal_log`, `DriverPort` + OLED/LED/sensor, `DevDriver` simula hardware (sin auto-confirmación, `pending_slots`), `POST /api/driver/sim`, scheduler combo + re-alarma, `status()` con timestamp |
| `index.html` | Modificado: overlay del modal de dosis pendiente |
| `script.js` | Modificado: detección de pendientes + modal "Abrir y tomar" |
| `style.css` | Modificado: estilos del modal |
| `docs/esp32-contract.md` | Nuevo: contrato HAL/firmware (H4) |
| `docs/architecture.md` | Modificado: flujo HAL + estado H4 + sistema embebido |
| `docs/run-and-test.md` | Modificado: checklist smoke HAL |

## Riesgos

| Riesgo | Severidad | Mitigación |
|--------|-----------|------------|
| Cambiar la confirmación de toma (antes auto-confirmación en dispense; ahora solo con sensor open/close o su simulación) | Media | La UI muestra el botón "Simular abrir/cerrar" en cada dosis pendiente; se prueba el flujo completo en smoke |
| El ring/OLED/LED en cada dosis se siente ruidoso | Media | Es el comportamiento esperado (alarma + display + LED); se verifica en smoke y se ajusta si el usuario lo ve excesivo |
| Log muy verboso cada 20 s | Baja | Solo se loguean eventos reales (dispense/ring/oled/led/sensor/init), no ticks vacíos |
| Cambiar `status()` rompe la UI | Baja | `/api/status` es informativo; formato de eventos es aditivo (timestamp) |

## Rollout / Rollback

- Commit único con trabajo por unidades (work-unit commits): logging → funciones HAL nuevas + scheduler → secuencia sensor → contrato → docs.
- Rollback: revert del commit. El contrato es documental; el logging es aditivo; la secuencia sensor→toma tiene fallback a auto-confirmación.

## Criterios de aceptación

- [ ] Cada `dispense`, `ring`, `oled_show`, `led_on/off`, `slot_open/closed` e `init` aparece como `[hal] ...` con timestamp en la consola del server.
- [ ] Al arrancar el server, aparece `[hal] init ...`.
- [ ] `/api/status` muestra los últimos eventos del driver con timestamp.
- [ ] El scheduler dispara dispense + ring + oled_show + led_on del slot correcto cuando llega la hora (sin hardware).
- [ ] Mientras una dosis esté pendiente, el scheduler re-emite `ring()` en cada ciclo (buzzer sigue pitando) y el LED sigue encendido.
- [ ] Aparece el modal de dosis pendiente (slot, hora, botón "Abrir y tomar") y persiste ante recarga si no se toma.
- [ ] La secuencia sensor: `slot_open(slot)` seguido de `slot_closed(slot)` marca la dosis como tomada (`taken_log.json` + WS push) y cierra el modal.
- [ ] `docs/esp32-contract.md` cubre firma, payload de red y auth de cada método del `DriverPort`.
- [ ] Smoke: flujo completo sin hardware (dosis → alarma + OLED + LED → abrir/cerrar slot → toma marcada).
