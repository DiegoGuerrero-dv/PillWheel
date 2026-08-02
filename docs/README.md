# PillWheel

Pastillero inteligente: un panel web para programar y controlar un blister de **8 casillas** con horarios de medicación por día de la semana. Al llegar la dosis, suena la alarma, se muestra la pastilla en la pantalla OLED y el LED de la casilla se enciende; al abrir y cerrar el compartimiento, la toma queda confirmada.

- **Backend**: Python 3 (solo stdlib) con API REST + WebSocket.
- **Frontend**: HTML + CSS + JS vanilla, sin dependencias ni build.
- **Persistencia**: JSON en disco (`schedule.json`, `taken_log.json`).
- **Dispositivo**: pensado para correr sobre un sistema embebido (ESP32) acoplado por contrato HAL.

## Cambios arquitectónicos (vs. la primera versión)

La primera versión era un backend simple: el scheduler y la lógica de dispensado estaban acoplados, no existía una capa de hardware y la confirmación de toma la hacía el navegador. Con el plan de acción (ver `docs/action-plan.md`) el proyecto evolucionó a **Arquitectura Hexagonal (Ports & Adapters / HAL)**:

- **Puerto `DriverPort`**: contrato abstracto del hardware (10 funciones: `dispense`, `ring`, `oled_show`, `led_on/off`, `slot_open/closed`, `status`, `init`, `on_pill_taken`). El backend depende de la interfaz, no de la implementación.
- **Adaptador `DevDriver`**: simula el hardware en PC (motor, buzzer, sensor, LED, OLED). Permite probar todo el flujo sin dispositivo físico.
- **El scheduler vive en el backend**, nunca en el driver: cada 20 s revisa dosis, dispara el combo `dispense → ring → oled_show → led_on` y re-alarma mientras haya dosis pendientes.
- **Confirmación por sensor**: una dosis se marca tomada solo con la secuencia `slot_open → slot_closed` (sin auto-confirmación al dispensar). La simulación local se expone con `POST /api/driver/sim`.
- **Contrato de firmware documentado** (`docs/esp32-contract.md`): define cómo un ESP32 real implementa el puerto.
- **Seguridad cerrada**: autenticación por fronteras (sesión del navegador F1 / device token F2), rutas protegidas, validación de entrada y vulnerabilidades V1–V10 resueltas.

El frontend no cambió de contrato: sigue hablando por las mismas rutas `/api/*`. El detalle completo está en `docs/architecture.md`.

## Preparar el ESP32 y acoplarlo

El ESP32 **no reimplementa el servidor web**: el backend sigue siendo el punto de entrada del navegador, y el firmware pasa a ser un **adaptador del puerto de hardware**. El timer y el estado viven en el backend; el firmware solo ejecuta comandos y reporta eventos.

Pasos de acople:

1. **Leer el contrato** (`docs/esp32-contract.md`): mapeo de cada función del `DriverPort` a su comando de red, payload y autenticación.
2. **Implementar los comandos** en el firmware: `POST /init`, `/dispense`, `/ring`, `/oled`, `/led` y `GET /status`, todos autenticados con `Authorization: Bearer <DEV_TOKEN>` (Frontera 2).
3. **Reportar eventos de sensor** por `POST /events` (`slot_open` / `slot_closed`); el backend confirma la toma con la secuencia apertura → cierre y registra el log vía `on_pill_taken`.
4. **Reportar tomas** al backend por `POST /api/taken` con el device token (el firmware no conoce el resto de las rutas `/api/*`).
5. **Probar con `DevDriver` antes de conectar el hardware**: el adaptador simulado ejercita el mismo flujo y deja el contrato estable para el swap Dev → ESP32 sin tocar la API ni el scheduler.

## Carpeta `docs/`

Documentación del proyecto. Contenido:

| Archivo | Contenido |
| --- | --- |
| [`architecture.md`](architecture.md) | Arquitectura actual y objetivo: stack, contrato de API, modelo de datos, flujo HAL, decisiones de diseño, seguridad y estado de implementación. |
| [`esp32-contract.md`](esp32-contract.md) | Contrato de integración con el firmware ESP32 (HAL): comandos, payloads, autenticación y reglas. |
| [`run-and-test.md`](run-and-test.md) | Cómo correr el proyecto y cómo probarlo (UI, API, WebSocket, scheduler/HAL y troubleshooting). |
| [`action-plan.md`](action-plan.md) | Plan de acción que guio la evolución: cierre de vulnerabilidades (V1–V10) e implementación del HAL hexagonal (H1–H6). |

Los artefactos del flujo SDD (specs, diseños, tareas y cambios archivados) viven en `openspec/` en la raíz, no en `docs/`.

## Convenciones

- El idioma de los artefactos técnicos es español neutro, consistente con la UI y los comentarios del proyecto.
- La documentación se actualiza junto con el código: si un artefacto cambia, su doc asociada cambia en el mismo commit.
- Los problemas conocidos se registran en `architecture.md` hasta que se corrijan; al corregirlos se mueven a decisiones (o se eliminan).
