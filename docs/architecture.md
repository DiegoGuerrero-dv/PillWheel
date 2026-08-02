# Arquitectura de PillWheel

## Visión general

Pastillero inteligente: un panel web de administración para programar y controlar un blister de 8 casillas con horarios de medicación por día de la semana.

El proyecto está diseñado para un backend **intercambiable**:

- **Ahora (desarrollo):** servidor Python puro (`Dev_server.py`) que lee y escribe JSON en disco.
- **Objetivo (dispositivo):** el backend coordina las dosis y ejecuta acciones sobre el ESP32 a través de un puerto de hardware (HAL); el firmware implementa ese contrato. Ver [Arquitectura objetivo](#arquitectura-objetivo-hexagonal-ports--adapters--hal).

El frontend no conoce ni le importa quién responde: usa solo `fetch('/api/...')`. El contrato de API es el punto de intercambio.

## Stack

| Capa | Tecnología |
| --- | --- |
| Frontend | HTML + CSS + JS vanilla, sin dependencias ni build |
| Backend dev | Python 3 (solo stdlib: `http.server`) |
| Persistencia | JSON en disco (`schedule.json`, `taken_log.json`) |
| Backend objetivo | ESP32 + LittleFS (firmware no incluido en este repo) |

## Diagrama de flujo

```
Navegador
   │  fetch('/api/...')  (JSON, Authorization: Bearer <token>)
   │  WebSocket /ws?token=<sesión>  (push de tomas)
   ▼
Dev_server.py (ThreadingHTTPServer + SimpleHTTPRequestHandler)
   ├── POST /api/login          → valida user+password → token de sesión (F1)
   ├── POST /api/logout         → invalida el token
   ├── GET  /api/schedule       → devuelve slots (sesión)
   ├── POST /api/schedule       → reemplaza slot por id (sesión)
   ├── GET  /api/taken          → devuelve log de dosis (sesión)
   ├── POST /api/taken          → reporte del adapter, solo device token F2 (V9)
   ├── GET  /api/status         → estado del driver (sesión)
   ├── GET  /ws                 → WebSocket de push (sesión vía query)
   ├── scheduler (thread)       → cada 20 s llama DRIVER.dispense (H3/H4)
   │        └── DevDriver ──on_pill_taken──► log + WS push (H6)
   └── static: /, /index.html, /style.css, /script.js
   │
   ▼
schedule.json  ·  taken_log.json
```

## Contrato de API

Base: `http://localhost:8000`. Autenticación: header `Authorization: Bearer <token>`.

Frontera F1 (navegador): token de sesión en memoria, emitido por `/api/login`, invalidado por `/api/logout` o reinicio.
Frontera F2 (dispositivo): device token `DEV_TOKEN` (config), usado por el adapter en `POST /api/taken` (V9: el navegador no escribe claves arbitrarias).

| Método | Ruta | Auth | Body | Respuesta |
| --- | --- | --- | --- | --- |
| POST | `/api/login` | No | `{"user": "admin", "password": "..."}` | 200 `{"ok": true, "token": "<sesión>"}` / 401 |
| POST | `/api/logout` | F1 | — | 200 `{"ok": true}` / 401 |
| GET | `/api/schedule` | F1 | — | 200 array de slots / 401 |
| POST | `/api/schedule` | F1 | objeto slot completo | 200 `{"ok": true}` / 400 |
| GET | `/api/taken` | F1 | — | 200 lista de records / 401 |
| POST | `/api/taken` | F2 (device token) | `{"key": "YYYY-MM-DD_1_08:00", "value": true}` | 200 `{"ok": true}` / 400 / 403 |
| GET | `/api/status` | F1 | — | 200 estado del driver / 401 |
| GET | `/ws?token=<sesión>` | F1 (query) | — | 101 Switching Protocols / 401 |
| GET | `/`, `/index.html`, `/style.css`, `/script.js` | No | — | 200 archivo estático |

WebSocket: tras el handshake RFC 6455, el backend pushea `{"type": "on_pill_taken", "key": "...", "taken": true}` cuando el adapter confirma una toma.

## Modelo de datos

### schedule.json

Array de 8 slots con id fijo 1–8:

```json
[
  {
    "id": 1,
    "name": "Pastilla Sida",
    "color": "#4fd1ae",
    "schedule": {
      "Dom": ["13:00"],
      "Lun": [],
      "Mar": [],
      "Mie": [],
      "Jue": [],
      "Vie": [],
      "Sab": []
    }
  }
]
```

- `schedule` usa las claves `Dom, Lun, Mar, Mie, Jue, Vie, Sab`, alineadas índice a índice con `Date.getDay()` de JS (0 = Domingo) y con `tm_wday` de C.
- Los horarios son strings `"HH:MM"` de 24 h.
- `name` vacío = casilla sin medicamento (se ignora en el dashboard de hoy).

### taken_log.json

Lista de records:

```json
[
  {
    "key": "2026-08-01_1_08:00",
    "taken": true,
    "ts": "2026-08-01T08:00:02"
  }
]
```

- La clave es `YYYY-MM-DD_slotId_HH:MM`. La fecha la calcula el backend (scheduler/adapter, `datetime.now()`), no el cliente.
- La clave de una misma dosis se reemplaza (upsert por `key`), no se acumula.
- Retención: `RETENTION_DAYS` (182 por defecto); al arrancar y en cada guardado se purgan los records más viejos. La purga no toca `schedule.json`.

## Estructura del frontend

- **index.html** — tres vistas: login (`#view-login`), panel (`#view-app` con pestañas `Hoy` y `Casillas`) y editor tipo bottom-sheet (`#editOverlay`).
- **script.js** — capa de datos (`api` con fetch + token), autenticación/navegación, render del dashboard (próxima dosis, lista chequeable), grid del blister, editor (tira de días, lista de horarios, color) y utilidades (`escapeHtml`, toast).
- **style.css** — tema oscuro con variables CSS (`:root`), móvil-first (máx. 640 px), sin framework.

## Decisiones de diseño

1. **Contrato de API estable** para que el swap Python → ESP32 no toque el frontend.
2. **Cero dependencias y cero build** en el frontend: los tres archivos se sirven tal cual.
3. **`read_json` tolerante a fallos:** archivo vacío o JSON corrupto se reinicia al valor por defecto sin tumbar el servidor.
4. **UI en español** (es-MX para fechas), pensada para pantalla de teléfono.
5. **Horarios clave-céntricos:** la clave del log distingue día, casilla y hora, permitiendo la misma dosis en días distintos sin colisión.

## Estado de seguridad y vulnerabilidades (cerrado)

Los problemas conocidos fueron cerrados en dos PRs de revisión acotada (ver [action-plan.md](action-plan.md)):

1. ✅ **Bypass de auth por estáticos** (V1/V2) — whitelist en `do_GET`: solo `/`, `/index.html`, `/style.css`, `/script.js`; `schedule.json`, `taken_log.json` y `Dev_server.py` responden 401 sin sesión. Los datos solo se leen vía `/api/*`.
2. ✅ **XSS en `toggleTaken`** (V3) — se eliminó el `onclick` con `JSON.stringify`; la confirmación de toma ya no la hace el navegador (ver V9), y los nombres siempre pasan por `escapeHtml`.
3. ✅ **Horas vacías / dosis fantasma** (V4/V5) — `validate_slot` rechaza horas malformadas y horarios sin nombre; se limpiaron los datos corruptos.
4. ✅ **Credenciales hardcodeadas** (V6) — `ADMIN_USER`/`ADMIN_PASSWORD`/`DEV_TOKEN` por `.env` (con defaults de dev y aviso en consola).
5. ✅ **Bind en `0.0.0.0`** (V7) — por defecto `127.0.0.1`; solo `--host 0.0.0.0` expone en LAN.
6. ✅ **Upsert de slots** (V8) — `id` validado en 1..8; id desconocido o forma inválida → 400.
7. ✅ **Claves arbitrarias en el log** (V9) — `POST /api/taken` exige el device token F2 y valida formato de `key`/`value`; el navegador ya no escribe.
8. ✅ **Código muerto** (V10) — se eliminó `emptySchedule()`.

Limitación documentada (fuera de alcance): el backend dev no hace HTTPS/TLS.

## Camino hacia el ESP32

Con la arquitectura hexagonal, el firmware **ya no reimplementa el servidor web**: el backend sigue siendo el punto de entrada del navegador, y el ESP32 pasa a ser un **adaptador del puerto de hardware**. Para que el dispositivo se integre:

1. El firmware implementa el contrato `DriverPort` (comandos `dispense`/`ring` y reporte de eventos), no las rutas `/api/*`.
2. El backend expone hacia el dispositivo una API de integración con auth propia (Frontera 2), distinta del token del navegador.
3. **No** exponer `schedule.json`/`taken_log.json` como estáticos (registrar rutas explícitas, no `serveStatic` del directorio completo).
4. Mantener el mismo formato de claves del log (`YYYY-MM-DD_slotId_HH:MM`), que el cliente ya genera.
5. El contrato de integración se especifica en `docs/esp32-contract.md` (pendiente de escribir en la Fase 2 del plan).

## Arquitectura objetivo: Hexagonal (Ports & Adapters / HAL)

**Decisión (2026-08):** el proyecto adopta Arquitectura Hexagonal (Ports & Adapters) para separar el núcleo de negocio de los dispositivos físicos. El frontend no cambia: sigue hablando con el backend por las mismas rutas `/api/*`.

### El patrón

> Dependé de la interfaz, no de la implementación.

- **Núcleo (core):** scheduler de dosis, validación, persistencia de horarios y logs. No conoce ni al navegador ni al ESP32.
- **Puerto (driver):** interfaz de las acciones del dispositivo (`DriverPort`). Define QUÉ puede hacer el hardware, no cómo.
- **Adaptadores:** una implementación por dispositivo. `DevServerDriver` simula en PC (es el que corre hoy); `Esp32Driver` hablará con el firmware real. Cambiar de adaptador no toca el núcleo.

```
Browser ──/api/*──► Backend (núcleo) ──DriverPort──► Adapter Dev (PC) / Adapter ESP32
                        ▲  scheduler                    │
                        └────── eventos (log) ◄─────────┘
```

### Contrato del puerto (borrador)

```python
from typing import Protocol

class DriverPort(Protocol):
    """Acciones que un dispositivo físico debe poder ejecutar."""

    def dispense(self, slot_id: int, time: str) -> bool:
        """Dispensa la casilla. Devuelve True si el dispositivo aceptó la acción."""
        ...

    def ring(self) -> bool:
        """Activa la alerta/sonido del dispositivo."""
        ...

    def status(self) -> dict:
        """Estado del dispositivo: conectado, batería, errores."""
        ...

    def on_pill_taken(self, slot_id: int, time: str) -> None:
        """Evento de vuelta: el dispositivo reporta que la dosis fue tomada."""
        ...
```

El borrador se afina en la Fase 2 del plan de acción; es un contrato de ejemplo, no la implementación final.

### Flujo del timer (ejemplo del usuario)

1. Front + back generan el horario (ya existe: `schedule.json`).
2. El **scheduler del backend** corre cada minuto y calcula si toca alguna dosis.
3. Si toca → el núcleo llama `driver.dispense(slot_id, hora)`.
4. El adaptador dev actual loguea local; el adaptador ESP32 hará la llamada real al firmware.
5. El evento de vuelta (`on_pill_taken`) es lo que escribe el log en el backend.

El **timer vive en el backend, no en el driver**. El driver solo ejecuta. Así, si el dispositivo está dormido o apagado, el backend registra igual "no dispensado".

### Fronteras de autenticación

| Frontera | Entre | Credencial | Estado |
| --- | --- | --- | --- |
| 1 | Browser ↔ Backend | Token de sesión (memoria) | ✅ Login/logout reales, invalida al reiniciar |
| 2 | Backend ↔ Dispositivo | `DEV_TOKEN` (config) | ✅ Usado en `POST /api/taken` (V9); contrato ESP32 pendiente |

### Qué previene el patrón

- **Whitelist de acciones:** el backend solo puede pedir `dispense`/`ring` al dispositivo; nunca "servir archivos arbitrarios".
- **Separación de credenciales:** la fuga de una no compromete la otra.
- **Testabilidad:** el adaptador simulado permite probar todo el flujo sin hardware.

### Estado de la implementación

| Componente | Estado |
| --- | --- |
| Frontend (rutas `/api/*` estables + WS) | ✅ Login con usuario, logout, push por WebSocket |
| Vulnerabilidades V1–V10 | ✅ Cerradas (2 PRs, ver action-plan.md) |
| Núcleo: scheduler de dosis | ✅ Thread cada 20 s → `DRIVER.dispense` (H3) |
| Puerto `DriverPort` | ✅ `typing.Protocol` en `Dev_server.py` (H1) |
| Adaptador `DevDriver` (mock GPIO) | ✅ Simula motor/buzzer/sensor; auto-confirma toma (H5/H6) |
| Integración ESP32 real | 🔲 Pendiente (necesita hardware; ver [action-plan.md](action-plan.md) H4/H5) |

> **Nota sobre H2:** el refactor a módulos separados (`core/`, `ports/`, `adapters/`) sigue siendo deuda técnica; hoy el puerto, el adaptador mock y el scheduler viven en `Dev_server.py` para mantener el servidor en un solo archivo mientras el firmware no exista. El contrato (rutas + `DriverPort`) ya está definido y no debería cambiar cuando se separe.
