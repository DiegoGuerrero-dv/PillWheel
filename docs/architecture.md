# Arquitectura de PillWheel

## Visión general

Pastillero inteligente: un panel web de administración para programar y controlar un blister de 8 casillas con horarios de medicación por día de la semana.

El proyecto está diseñado para un backend **intercambiable**:

- **Ahora (desarrollo):** servidor Python puro (`Dev_server.py`) que lee y escribe JSON en disco.
- **Objetivo (dispositivo):** firmware ESP32 que sirve la misma página desde LittleFS y expone las mismas rutas.

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

## Camino hacia el ESP32

Para que el dispositivo reemplace a `Dev_server.py`, el firmware debe:

1. Servir `index.html`, `style.css` y `script.js` desde LittleFS.
2. Implementar las 5 rutas del contrato con la misma semántica (login con la misma password, Bearer token, upsert por id/clave).
3. **No** servir `schedule.json`/`taken_log.json` como estáticos (registrar rutas explícitas, no `serveStatic` del directorio completo).
4. Mantener el mismo formato de claves del log (`YYYY-MM-DD_slotId_HH:MM`), que el cliente ya genera.
