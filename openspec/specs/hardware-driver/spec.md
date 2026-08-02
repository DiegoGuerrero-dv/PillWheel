# hardware-driver Specification

## Purpose

Arquitectura hexagonal (Ports & Adapters / HAL, H1–H6): DriverPort con contrato H4 documentado y adaptadores Dev/mock en Python. Prepara el backend para correr en el ESP32 sin acoplarse al hardware.

## Requirements

### Requirement: DriverPort (contrato H4)

The system MUST exponer el puerto de driver con: `dispense(slot_id, time) -> bool`, `ring()`, `status() -> dict` y `on_pill_taken(slot_id, time)`. El timer y el scheduler MUST vivir en el backend, no en el driver.

#### Scenario: Dispensa programada

- GIVEN una dosis programada y el scheduler activo
- WHEN llega la hora de la dosis
- THEN el backend llama `dispense(slot_id, time)` y registra el resultado

#### Scenario: Sin timer en el driver

- WHEN se diseña o implementa un adaptador
- THEN el driver solo ejecuta comandos; el temporizado lo maneja el backend

### Requirement: Confirmación por sensor

The system MUST aceptar las confirmaciones de toma generadas por el adapter del dispositivo vía `on_pill_taken`. The storage layer MUST registrarlas en el log.

#### Scenario: Sensor confirma toma

- GIVEN el adapter del dispositivo detecta la toma
- WHEN se emite `on_pill_taken(slot_id, time)`
- THEN el sistema registra la toma en el log con origen verificado

### Requirement: Adaptador Dev (mock H5/H6)

The system MUST proveer un adaptador `DevDriver` que simule el GPIO (motor, buzzer, sensor) sin hardware, utilizado por `Dev_server.py`.

#### Scenario: Mock sin hardware

- GIVEN el backend corriendo en desarrollo
- WHEN el scheduler dispara `dispense`/`ring`
- THEN el adaptador Dev simula la acción y reporta `status()`

#### Scenario: Contrato estable entre adaptadores

- WHEN un adaptador reemplaza a otro (Dev → firmware ESP32)
- THEN la API y el scheduler no cambian
