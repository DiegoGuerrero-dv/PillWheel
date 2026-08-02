# Spec: Sistema embebido (hardware)

## Descripción del sistema embebido

El sistema embebido (firmware, p. ej. ESP32) es el dispositivo físico que interactúa con el usuario y ejecuta las acciones del hardware:

- **8 slots** donde se guardan las dosis de pastillas.
- Cada slot cuenta con:
  - un **LED** (indicador visual de que toca tomar la dosis de ese slot);
  - un **sensor de movimiento** que detecta cuándo el usuario **abre** y **cierra** el compartimiento del slot.
- El sistema cuenta con un **buzzer** (alarma sonora).
- El sistema cuenta con una **pantalla OLED pequeña** (información de la dosis).

## Interacciones hardware ↔ software

1. Cuando llega el horario del día de tomar una pastilla para la rutina, **debe sonar una alarma con el buzzer**.
2. Además, se debe enviar a la **pantalla OLED** la información de la pastilla que toca y a qué hora se debe tomar, según el slot al que se le marcó la dosis.
3. El slot correspondiente debe **encender su LED** cuando llegue la hora de tomar la dosis de ese slot.
4. El **sensor de movimiento** del slot mide cuándo el usuario **abre** y **cierra** el compartimiento, para marcar cuándo una píldora fue tomada.

### Requirement: Alarma por buzzer al llegar la hora

The system MUST activar el buzzer (función HAL `ring`) cuando el scheduler detecta que llegó el horario de una dosis activa de hoy.

#### Scenario: Llega la hora de una dosis activa

- GIVEN un slot con horas configuradas para hoy y `enabled[hoy]` activo
- AND la hora actual coincide con una hora del slot
- WHEN el scheduler procesa el tick
- THEN se invoca la función HAL `ring()` (alarma del buzzer)

### Requirement: Información en pantalla OLED

The system MUST enviar a la pantalla OLED (función HAL `oled_show`) el nombre de la pastilla y la hora de la dosis cuando el scheduler la dispara, indicando el slot correspondiente.

#### Scenario: Dosis disparada → OLED

- GIVEN una dosis disparada por el scheduler para el slot 3 a las 08:00
- WHEN el scheduler procesa la dosis
- THEN se invoca `oled_show(slot_id=3, name=<nombre>, time="08:00")`

### Requirement: LED del slot al llegar la hora

The system MUST encender el LED del slot (función HAL `led_on`) cuando llega la hora de una dosis de ese slot, y apagarlo (función HAL `led_off`) cuando el usuario cierra el compartimiento (toma confirmada).

#### Scenario: LED enciende con la dosis

- GIVEN una dosis disparada por el scheduler para el slot 3
- WHEN el scheduler procesa la dosis
- THEN se invoca `led_on(slot_id=3)`

#### Scenario: LED se apaga al cerrar el slot

- GIVEN el LED del slot 3 encendido (dosis disparada)
- WHEN el usuario abre y cierra el compartimiento del slot 3
- THEN se invoca `led_off(slot_id=3)` al confirmarse la toma

### Requirement: Re-alarma mientras la dosis no se toma

The system MUST repetir la alarma del buzzer (`ring`) periódicamente mientras exista una dosis pendiente (disparada y no confirmada por el sensor). El LED del slot correspondiente permanece encendido mientras la dosis esté pendiente.

#### Scenario: Dosis pendiente → buzzer repite

- GIVEN una dosis disparada para el slot 3 (pendiente, LED encendido)
- WHEN el scheduler ejecuta ticks posteriores sin que el sensor confirme
- THEN el buzzer vuelve a sonar (`ring`) en cada ciclo hasta que la toma se confirme

#### Scenario: Toma confirmada → buzzer deja de sonar y LED se apaga

- GIVEN una dosis pendiente con re-alarma activa
- WHEN el sensor reporta `slot_open` + `slot_closed`
- THEN la toma se confirma, `led_off` apaga el LED y la re-alarma cesa

### Requirement: Sensor de movimiento → marcado de toma

The system MUST usar los eventos del sensor de movimiento (función HAL `slot_open` / `slot_closed`) para marcar cuándo una píldora fue tomada: una apertura seguida de un cierre del compartimiento del slot, dentro de la ventana de una dosis, confirma la toma (función `on_pill_taken`).

#### Scenario: Abrir y cerrar confirma la toma

- GIVEN una dosis disparada para el slot 3 (LED encendido, esperando toma)
- WHEN el usuario abre el compartimiento (`slot_open(slot_id=3)`)
- AND cierra el compartimiento (`slot_closed(slot_id=3)`)
- THEN el sistema marca la dosis como tomada (`on_pill_taken(slot_id=3, time=<hora>)`), apaga el LED y pushea por WS

#### Scenario: Sin sensor no hay toma confirmada

- GIVEN una dosis disparada para el slot 3
- WHEN el sensor no reporta apertura/cierre
- THEN la dosis permanece **pendiente** (no se marca tomada) y el LED permanece encendido; el sistema no auto-confirma la toma en ningún caso

#### Scenario: Modal de dosis pendiente en la UI

- GIVEN la app corriendo localmente con `DevDriver` (sin hardware) y una dosis pendiente
- WHEN el usuario ve el modal de dosis pendiente
- THEN el modal muestra el slot, la hora y un botón para "abrir y tomar"; al tocarlo el driver reporta `slot_open(slot_id)` y `slot_closed(slot_id)` y la dosis se marca tomada

#### Scenario: Modal persistente ante recarga

- GIVEN una dosis pendiente (no confirmada)
- WHEN el usuario recarga la página (o cierra y vuelve a abrir la app el mismo día)
- THEN el modal sigue desplegado mostrando la misma dosis pendiente, porque no hay confirmación en `taken_log.json`

## Compatibilidad

- Los datos existentes (`schedule.json`, `taken_log.json`) no cambian de formato por esta spec.
- El marcado de toma pasa a depender del sensor: `DevDriver` **deja de auto-confirmar** al dispensar; la confirmación ocurre solo con `slot_open` → `slot_closed` (o su simulación).
- La simulación local se expone por UI (botón en la dosis pendiente) y por `POST /api/driver/sim` (endpoint de prueba).
