# api-security Specification

## Purpose

Hardening de la API y la UI: cerrar V2 (fuga de datos), V3 (XSS), V4 (horas vacías), V5 (dosis fantasma), V8 (upsert sin validar) y V9 (claves arbitrarias).

## Requirements

### Requirement: Protección de estáticos y datos

The system MUST require autenticación para servir `/schedule.json`, `/taken_log.json`, `/Dev_server.py` y todo endpoint `/api/*`. The system MUST NOT devolver datos de horarios ni de tomas a peticiones anónimas.

#### Scenario: Acceso anónimo a datos

- GIVEN un cliente sin token
- WHEN solicita `/schedule.json`, `/taken_log.json`, `/Dev_server.py` o un endpoint `/api/*`
- THEN el sistema responde 401 y no expone datos

#### Scenario: Acceso autenticado a datos

- GIVEN un token válido
- WHEN solicita `/schedule.json`
- THEN el sistema responde con los datos

### Requirement: Saneamiento de salida

The UI MUST escapar todos los datos dinámicos antes de inyectarlos en el DOM. The system MUST NOT renderizar valores controlables por el usuario en sinks HTML crudos (onclick con JSON sin escapar, innerHTML sin sanitizar).

#### Scenario: Render seguro del dashboard

- GIVEN horarios o dosis con caracteres especiales (comillas, `<`, `>`)
- WHEN se renderiza el dashboard
- THEN los valores se muestran escapados y no se ejecuta código

#### Scenario: Sin sinks crudos

- WHEN la UI construye filas y acciones del dashboard
- THEN no usa `onclick` con JSON sin escapar ni `innerHTML` sin sanitización

### Requirement: Validación de horarios y dosis

The system MUST rechazar slots con hora vacía (`""`) y slots con hora definida pero sin nombre. Invalid slots MUST NOT almacenarse ni programarse.

#### Scenario: Slot con hora vacía

- GIVEN un slot con hora vacía
- WHEN se guarda el horario
- THEN el sistema rechaza o ignora el slot vacío

#### Scenario: Slot con hora pero sin nombre

- GIVEN un slot con hora definida y `name` vacío
- WHEN se guarda el horario
- THEN el sistema rechaza el slot (dosis fantasma)

### Requirement: Validación de upsert de slots

The system MUST validar los ids de slot en el upsert: actualizaciones de ids inexistentes MUST ser rechazadas e ids inválidos en inserción MUST ser rechazados.

#### Scenario: Update de id inexistente

- GIVEN un id que no existe en el schedule
- WHEN se actualiza ese slot
- THEN el sistema responde 4xx y no modifica nada

#### Scenario: Insert válido

- GIVEN un id válido y no existente
- WHEN se crea el slot
- THEN el sistema lo almacena

### Requirement: Origen verificado en /api/taken

The system MUST aceptar reportes de toma solo desde el adapter del dispositivo (`on_pill_taken`) por la vía verificada. Claves arbitrarias o escrituras externas directas MUST ser rechazadas.

#### Scenario: Reporte desde el adapter

- GIVEN el adapter del dispositivo confirma una toma
- WHEN se registra en el log
- THEN el sistema registra la toma con origen verificado

#### Scenario: Escritura arbitraria

- GIVEN una petición externa con una clave arbitraria
- WHEN intenta escribir una toma
- THEN el sistema rechaza la petición
