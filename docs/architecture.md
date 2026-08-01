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
   ▼
Dev_server.py (SimpleHTTPRequestHandler)
   ├── POST /api/login          → valida password → entrega token
   ├── GET  /api/schedule       → devuelve slots (auth)
   ├── POST /api/schedule       → reemplaza slot por id (auth)
   ├── GET  /api/taken          → devuelve log de dosis (auth)
   ├── POST /api/taken          → upsert de clave en el log (auth)
   └── static: /, /index.html, /style.css, /script.js
   │
   ▼
schedule.json  ·  taken_log.json
```

## Contrato de API

Base: `http://localhost:8000`. Autenticación: header `Authorization: Bearer dev-local-token` (token estático).

| Método | Ruta | Body | Respuesta | Auth |
| --- | --- | --- | --- | --- |
| POST | `/api/login` | `{"password": "..."}` | 200 `{"ok": true, "token": "dev-local-token"}` / 401 | No |
| GET | `/api/schedule` | — | 200 array de slots / 401 | Sí |
| POST | `/api/schedule` | objeto slot completo | 200 `{"ok": true}` | Sí |
| GET | `/api/taken` | — | 200 objeto log / 401 | Sí |
| POST | `/api/taken` | `{"key": "YYYY-MM-DD_1_08:00", "value": true}` | 200 `{"ok": true}` | Sí |
| GET | `/`, `/index.html`, `/style.css`, `/script.js` | — | 200 archivo estático | No |

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

Objeto clave → booleano:

```json
{
  "2026-07-25_1_08:00": true
}
```

La clave es `YYYY-MM-DD_slotId_HH:MM`. La fecha la calcula el cliente (`dateKey(new Date())`), no el servidor.

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

## Problemas conocidos

1. **Bypass de autenticación por rutas estáticas.** `SimpleHTTPRequestHandler` sirve cualquier archivo del directorio sin auth: `GET /schedule.json`, `GET /taken_log.json` y `GET /Dev_server.py` (fuente con la password) responden 200 sin token. Verificado con el server corriendo. El fix es una whitelist de estáticos en `do_GET` (solo `/`, `/index.html`, `/style.css`, `/script.js`; todo lo demás 404).
2. **Dosis fantasma.** El slot 3 tiene horario 07:30 todos los días pero `name` vacío; `getTodayDoses()` saltea slots sin nombre, así que esas dosis existen en el JSON pero no se ven en el panel.
3. **Datos corruptos persistidos.** Horas vacías guardadas: slot 1 `"Sab": [""]` y clave `2026-07-25_1_` en el log. El editor no valida horas vacías al guardar.
4. **XSS parcial.** En `renderDashboard()` el `onclick` inyecta `JSON.stringify(dose)` sin escapar; un nombre con comillas puede inyectar código. El resto del template usa `escapeHtml`.
5. **Auth simbólico.** Password `admin1234` y token `dev-local-token` hardcodeados en el fuente. Aceptable en LAN de casa; no sirve para redes compartidas.
6. **Server en `0.0.0.0`.** Visible en la LAN; combinado con el problema 1 expone los datos a cualquier dispositivo de la red.
7. **Código muerto.** `emptySchedule()` en `script.js` no se usa.

El plan de cierre de estas vulnerabilidades está en [action-plan.md](action-plan.md).

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
| 1 | Browser ↔ Backend | Token de usuario (`dev-local-token`) | Existe (con vulnerabilidades) |
| 2 | Backend ↔ Dispositivo | Token de dispositivo (distinto) | A diseñar (Fase 2) |

### Qué previene el patrón

- **Whitelist de acciones:** el backend solo puede pedir `dispense`/`ring` al dispositivo; nunca "servir archivos arbitrarios".
- **Separación de credenciales:** la fuga de una no compromete la otra.
- **Testabilidad:** el adaptador simulado permite probar todo el flujo sin hardware.

### Estado de la implementación

| Componente | Estado |
| --- | --- |
| Frontend (rutas `/api/*` estables) | ✅ Funciona (sin cambios) |
| Núcleo: scheduler + validación | 🔲 Por implementar (Fase 2) |
| Puerto `DriverPort` | 🔲 Borrador arriba |
| Adaptador `DevServerDriver` (simulación) | 🔲 Por implementar (Fase 2) |
| Adaptador `Esp32Driver` | 🔲 Contrato por definir (Fase 2) |
| Vulnerabilidades | 🔲 Plan en [action-plan.md](action-plan.md) |
