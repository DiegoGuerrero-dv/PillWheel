# Spec: HAL — funciones, logging y contrato firmware

## Descripción

El puerto `DriverPort` define las acciones del hardware. Con la especificación del sistema embebido, el puerto crece con funciones nuevas (OLED, LED por slot, sensores de apertura/cierre). Toda invocación al driver se registra en un **log estructurado** con timestamp en la consola del backend, y `status()` expone los últimos eventos. El documento `docs/esp32-contract.md` fija el contrato de red con el firmware real.

## Funciones del `DriverPort`

| Función | Firma | Hardware | Descripción |
|---------|-------|----------|-------------|
| `dispense` | `dispense(slot_id, time) -> bool` | Motor | Dispensa la casilla (existente) |
| `ring` | `ring() -> None` | Buzzer | Alarma sonora (existente, ahora invocada) |
| `status` | `status() -> dict` | — | Estado del dispositivo (existente, con timestamp) |
| `on_pill_taken` | `on_pill_taken(slot_id, time) -> None` | Sensor | Evento de vuelta: dosis tomada (existente) |
| `oled_show` | `oled_show(slot_id, name, time) -> None` | Pantalla OLED | Muestra pastilla + hora según slot (nueva) |
| `led_on` | `led_on(slot_id) -> None` | LED slot | Enciende LED del slot (nueva) |
| `led_off` | `led_off(slot_id) -> None` | LED slot | Apaga LED del slot (nueva) |
| `slot_open` | `slot_open(slot_id) -> None` | Sensor movimiento | El usuario abrió el compartimiento (nueva) |
| `slot_closed` | `slot_closed(slot_id) -> None` | Sensor movimiento | El usuario cerró el compartimiento (nueva) |
| `init` | `init() -> None` | — | Registra el arranque del driver (nueva) |

### Requirement: Log estructurado de invocaciones HAL

The system MUST registrar cada invocación a una función del driver con un log en la consola del backend con formato `[hal] <timestamp> <función>(<k=v,...>) → <resultado>`.

#### Scenario: dispense logueado

- GIVEN el scheduler dispara una dosis para el slot 1 a las 08:00
- WHEN se invoca `DRIVER.dispense(1, "08:00")`
- THEN la consola muestra `[hal] 2026-08-02 08:00:00 dispense(slot_id=1, time=08:00) → True`

#### Scenario: status con timestamp

- GIVEN el driver registró eventos
- WHEN se consulta `DRIVER.status()` (y `/api/status`)
- THEN devuelve `last_events` con entries `{action, ts, kw}` ordenadas de más reciente a más antigua

### Requirement: Scheduler dispara el conjunto de acciones HAL

The system MUST invocar, al disparar una dosis activa: `dispense`, `ring`, `oled_show(slot_id, name, time)` y `led_on(slot_id)`.

#### Scenario: Dosis completa con hardware

- GIVEN una dosis activa disparada por el scheduler (slot 3, "Pastilla Sida", 08:00)
- WHEN el scheduler procesa la dosis
- THEN se invoca `dispense(3, "08:00")`, `ring()`, `oled_show(3, "Pastilla Sida", "08:00")` y `led_on(3)` en ese orden

### Requirement: Secuencia sensor → toma confirmada

The system MUST marcar la toma (`on_pill_taken`) **solo** cuando el sensor reporta `slot_open` seguido de `slot_closed` del mismo slot, y apagar el LED correspondiente. El driver MUST NOT auto-confirmar la toma al dispensar.

#### Scenario: Toma confirmada por sensor

- GIVEN `led_on(3)` activo y el scheduler esperando la toma del slot 3
- WHEN llega `slot_open(3)` y luego `slot_closed(3)`
- THEN `on_pill_taken(3, <hora>)` registra la dosis en `taken_log.json`, `led_off(3)` apaga el LED y se pushea `on_pill_taken` por WS

#### Scenario: Sin sensor la dosis queda pendiente

- GIVEN una dosis disparada
- WHEN el sensor no reporta `slot_open` ni `slot_closed`
- THEN la dosis permanece pendiente (no se marca tomada); el LED sigue encendido

### Requirement: Modal de dosis pendiente (UI)

The system MUST mostrar un **modal** cuando hay una dosis pendiente (disparada y no confirmada) cuya hora ya llegó. El modal muestra el slot, la hora de la dosis y un botón para "abrir y tomar". El modal persiste ante recarga de la página mientras la dosis siga pendiente.

#### Scenario: Llega la hora → se despliega el modal

- GIVEN una dosis del slot 3 a las 08:00 pendiente y la hora actual ≥ 08:00
- WHEN el dashboard se renderiza (o un timer de la UI detecta la hora)
- THEN aparece el modal con "Casilla 3", "08:00" y el botón "Abrir y tomar"

#### Scenario: No se toma → modal persiste ante recarga

- GIVEN el modal desplegado por una dosis pendiente
- WHEN el usuario recarga la página sin confirmar la toma
- THEN el modal vuelve a desplegarse (la dosis sigue pendiente en `taken_log.json`)

#### Scenario: Tomar → el modal se cierra

- GIVEN el modal de la dosis pendiente del slot 3
- WHEN el usuario toca "Abrir y tomar"
- THEN se ejecuta la simulación `slot_open(3)` + `slot_closed(3)`, la dosis se marca tomada, el LED se apaga y el modal se cierra

### Requirement: Simulación local del sensor (DevDriver)

The system MUST exponer, cuando el driver es el `DevDriver` (modo simulación, sin hardware), una vía para simular la apertura y el cierre de un slot: el botón "Abrir y tomar" del modal de dosis pendiente y un endpoint de prueba `POST /api/driver/sim`.

#### Scenario: Botón del modal simula abrir y cerrar

- GIVEN una dosis pendiente del slot 3 visible en el modal
- WHEN el usuario toca "Abrir y tomar"
- THEN el backend recibe `slot_open(3)` y `slot_closed(3)` y la dosis se marca tomada (`on_pill_taken`)

#### Scenario: Endpoint de prueba

- GIVEN la app local con `DevDriver`
- WHEN se hace `POST /api/driver/sim` con `{"slot_id": 3, "action": "open"}` y luego `{"slot_id": 3, "action": "close"}`
- THEN cada llamada se loguea `[hal] ... slot_open(slot_id=3) ...` / `[hal] ... slot_closed(slot_id=3) ...` y al cerrar la dosis queda tomada

#### Scenario: Endpoint rechaza acciones inválidas

- GIVEN el endpoint `/api/driver/sim`
- WHEN se envía una acción distinta de `open`/`close` o falta `slot_id`
- THEN responde 400 y no invoca al driver

### Requirement: Re-alarma y estado del LED mientras hay pendientes

The system MUST re-emitir `ring()` periódicamente (en cada ciclo del scheduler) mientras `DevDriver` tenga dosis pendientes, y mantener `led_on` de esos slots hasta que la toma se confirme.

#### Scenario: Buzzer repite hasta confirmar

- GIVEN el scheduler corriendo con una dosis pendiente en el slot 3
- WHEN pasan ciclos del scheduler sin confirmación
- THEN cada ciclo invoca `ring()` de nuevo y el LED del slot 3 permanece encendido

#### Scenario: Confirmada → cesa la re-alarma

- GIVEN la re-alarma activa por la dosis pendiente del slot 3
- WHEN `slot_closed(3)` confirma la toma
- THEN `led_off(3)` apaga el LED y los siguientes ciclos ya no invocan `ring()` por esa dosis

### Requirement: Contrato firmware (docs/esp32-contract.md)

The system MUST documentar en `docs/esp32-contract.md` la firma de cada función del `DriverPort`, su comando/payload de red equivalente, la autenticación de dispositivo (Frontera 2, `DEV_TOKEN`) y el formato de los eventos de vuelta (incluye `on_pill_taken`).

#### Scenario: Contrato completo

- GIVEN el documento `docs/esp32-contract.md` existe
- THEN cubre las funciones del `DriverPort` con: firma Python, comando HTTP/WS del firmware, payload de ejemplo y auth (`Authorization: Bearer <DEV_TOKEN>`)

### Requirement: Arranque del driver

The system MUST registrar `init()` al arrancar el servidor, logueado como `[hal] ... init(...) → None`.

#### Scenario: Server inicia

- GIVEN el servidor arranca
- THEN la consola muestra el log `[hal] ... init()` y `status()` incluye el evento de arranque

## Compatibilidad

- `POST /api/taken` (V9) se conserva: el firmware real reporta tomas con `DEV_TOKEN`; en el mock, `slot_open`/`slot_closed` (o su simulación por `POST /api/driver/sim`) derivan en `on_pill_taken` internamente.
- El formato de `/api/status` es aditivo: agrega `ts` a los eventos; los campos existentes (`driver`, `ok`, `last_events`) se mantienen.
- No se elimina `ring` ni `on_pill_taken` (ya existentes).
- `POST /api/driver/sim` solo existe en modo simulación (`DevDriver`); con un adapter real no aplica.
