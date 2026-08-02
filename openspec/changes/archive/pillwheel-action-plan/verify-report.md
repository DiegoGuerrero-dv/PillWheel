# Verify Report — PillWheel: pillwheel-action-plan

**Fecha:** 2026-08-01
**Cambio:** `pillwheel-action-plan` (PR 1 `9abf2e7` + PR 2 `01b75be`, ambos en `origin/main`)
**Método:** smoke tests manuales (PowerShell + curl + `ClientWebSocket`) + mapeo spec → código (Dev_server.py, script.js, index.html)
**Test runner:** no hay (strict_tdd: false) → modo Standard, verificación manual documentada en `docs/run-and-test.md`

## Resumen ejecutivo

**Estado: PASS CON ADVERTENCIAS.** Las 4 specs (user-auth, api-security, data-retention, hardware-driver) están implementadas y verificadas por smoke test. No hay requisitos MUST incumplidos. Las advertencias son riesgos menores documentados (color sin escapar en inline style, semántica update-vs-insert, hub WS mínimo) y deuda pendiente ya planificada (contrato esp32 H4, refactor H2).

## Mapeo de requisitos

### Spec: user-auth

| Requisito | Implementación | Estado |
|-----------|---------------|--------|
| Login admin único con credenciales de config (env/.env), 401 sin revelar campo | `Dev_server.py` L81-85 (env) + `AuthService.login` L127-136 (None idéntico para user o password mal) | ✅ |
| Escenario login exitoso → 200 + token | Smoke: `POST /api/login {"user":"admin","password":"admin1234"}` → 200 `{"ok":true,"token":"4130..."}` | ✅ |
| Escenario login fallido → 401 sin indicar campo | Smoke: password mala → 401 | ✅ |
| Token de sesión obligatorio en endpoints protegidos | `_require_session` L393-397; `secrets.token_hex(16)` L134 | ✅ |
| Token invalidado en logout o reinicio | `AuthService.logout` L141-142; `_sessions` en memoria → reinicio limpia | ✅ |
| Escenario token ausente/desconocido → 401 | Smoke: `/api/schedule` sin token → 401; tras logout → 401 | ✅ |
| Logout invalida el token | Smoke: logout 200 → mismo token da 401 | ✅ |

### Spec: api-security

| Requisito | Implementación | Estado |
|-----------|---------------|--------|
| Auth obligatoria en `/schedule.json`, `/taken_log.json`, `/Dev_server.py` y `/api/*` | `do_GET` L405-440 (whitelist estáticos + `_require_session`) | ✅ |
| Escenario acceso anónimo → 401 sin exponer datos | Smoke: 401 en schedule.json / taken_log.json / Dev_server.py / /api/schedule / /api/taken / /api/status | ✅ |
| Escenario acceso autenticado → datos | Smoke: 200 con sesión en /api/schedule, /api/taken, /api/status | ✅ |
| Escapar datos dinámicos en el DOM; sin onclick con JSON sin escapar ni innerHTML crudo | `escapeHtml` aplicado a `dose.name`/`slot.name`; `onclick='toggleTaken(JSON...)'` eliminado → span read-only | ✅ |
| Escenario render seguro | Nombres con caracteres especiales pasan por `escapeHtml` | ✅ |
| Rechazar hora vacía y hora sin nombre | `validate_slot` L226-232 (V4/V5) | ✅ |
| Escenarios slot inválido → rechazo | Smoke PR 1: hora vacía → 400; horario sin nombre → 400 | ✅ |
| Upsert: id inválido rechazado; insert válido almacenado | `validate_slot` L217 (rango 1..8); `do_POST /api/schedule` (append si no existe) | ✅ (ver W2) |
| Escenario update id inexistente → 4xx | Smoke PR 1: id 99 → 400 | ✅ |
| `/api/taken` solo desde adapter verificado; claves arbitrarias rechazadas | `do_POST /api/taken`: exige `DEV_TOKEN` (F2) + regex `YYYY-MM-DD_\d+_HH:MM` + value booleano (V9) | ✅ |
| Escenario reporte desde adapter | Smoke: POST con `dev-local-token` + clave válida → 200; `on_pill_taken` interno L329-342 | ✅ |
| Escenario escritura arbitraria rechazada | Smoke: POST con token de sesión → 403; clave malformada → 400; value no booleano → 400 | ✅ |

### Spec: data-retention

| Requisito | Implementación | Estado |
|-----------|---------------|--------|
| Conservar entradas ≥ 6 meses | `purge_taken_log` L183-198 con `RETENTION_DAYS=182`; cutoff por `ts` | ✅ |
| Purga automática al arranque y periódicamente | `save_taken_log` purga en cada write L201-203; `__main__` llama `save_taken_log(load_taken_log())` al arranque | ✅ |
| Purga no toca el schedule | `purge_taken_log` solo opera sobre el log; nunca lee/escribe schedule | ✅ |
| Escenario entrada vencida eliminada | Smoke PR 1: entrada sintética 2020 purgada | ✅ |
| Entrada sin fecha legible | Se conserva (no borrar lo que no se puede fechar) — decisión documentada L184-185 | ✅ |

### Spec: hardware-driver

| Requisito | Implementación | Estado |
|-----------|---------------|--------|
| DriverPort con `dispense(slot_id, time)->bool`, `ring()`, `status()->dict`, `on_pill_taken(slot_id, time)` | `DriverPort(Protocol)` L236-255 | ✅ |
| Timer/scheduler viven en el backend, no en el driver | `Scheduler(threading.Thread)` L349-374; `DevDriver` solo ejecuta comandos | ✅ |
| Escenario dispensa programada → `dispense` registrado | Smoke: 2 slots a la misma hora → 2 records; `GET /api/status` muestra `last_events: [["dispense",1,"17:42"]]` | ✅ |
| Confirmación por sensor vía `on_pill_taken` → storage | `on_pill_taken` L329-342: upsert en log + broadcast WS | ✅ |
| Escenario sensor confirma toma → registrado con origen verificado | Smoke: record `{"key":"2026-08-01_1_17:42","taken":true,"ts":...}` escrito | ✅ |
| Adaptador `DevDriver` mock que simula GPIO sin hardware | `DevDriver` L258-280, `DRIVER` L346 | ✅ |
| Contrato estable entre adaptadores (Dev → ESP32) | Rutas `/api/*` y `DriverPort` no cambian al cambiar adaptador; scheduler recibe driver por inyección | ✅ |
| WS push de `on_pill_taken` (H6) | `WSHub` L300-326, `_handle_ws`/`_ws_loop` L452-508; smoke: push recibido `{"type":"on_pill_taken","key":...,"taken":true}` | ✅ |

## Hallazgos

### CRITICAL
- Ninguno.

### WARNING
- **W1 — Color sin escapar en inline style.** `renderDashboard`/`renderManage` usan `style="background:${dose.color}"` sin `escapeHtml`. Riesgo bajo: el color solo lo setea el admin autenticado vía `<input type="color">`; se vuelve XSS persistente solo si el admin ya está comprometido. SUGERENCIA: validar `color` contra regex `^#[0-9a-fA-F]{6}$` al guardar (server-side).
- **W2 — Semántica update-vs-insert.** La spec api-security tiene dos escenarios: "update de id inexistente → 4xx" e "insert válido (id válido no existente) → se almacena". La implementación resuelve: id fuera de rango 1..8 → 400; id en rango no existente → insert. Como `schedule.json` siempre tiene la grilla fija de 8 slots, el caso "id 1-8 inexistente" no ocurre en la práctica.
- **W3 — WS token en query string.** `/ws?token=...` (los navegadores no pueden fijar headers en WebSocket). El token puede quedar en logs de acceso del servidor. Aceptable en LAN de desarrollo; para producción usar cookie HttpOnly + CSRF-safe o subprotocol. Documentado en `docs/architecture.md`.

### SUGGESTION
- **S1 — `_ws_loop` no desenmascara payloads entrantes.** El frame entrante (close/ping) se lee pero el payload no se desenmascara antes del pong. En la práctica los navegadores envían ping/close sin payload; el hub es push-only. Si en el futuro se reciben mensajes cliente→servidor, hay que aplicar la máscara.
- **S2 — Contrato esp32 (H4/H5) pendiente.** `docs/esp32-contract.md` aún no existe; necesita decisión de hardware (fuera de alcance).
- **S3 — Refactor H2 pendiente.** El puerto, adaptador y scheduler viven en `Dev_server.py` (monolito); la separación a `core/`/`ports/`/`adapters/` es deuda documentada en `docs/architecture.md`.
- **S4 — Sin test runner automatizado.** strict_tdd: false; la suite es manual (`docs/run-and-test.md`). Si el proyecto crece, conviene pytest/unittest para `validate_slot`, purga y scheduler.

## Evidencia de smoke tests

Todos corridos con el servidor en `127.0.0.1:8000` (datos restaurados después; sin procesos python vivos; puerto libre).

```powershell
# Login OK → 200 + token de sesión
curl -s -X POST http://localhost:8000/api/login -H "Content-Type: application/json" -d '{"user":"admin","password":"admin1234"}'
# → {"ok": true, "token": "413017e18acfc66291b1853af285c523"}

# Login malo → 401
# Sin token → 401 en: /api/schedule, /api/taken, /api/status, /schedule.json, /taken_log.json, /Dev_server.py
# Con sesión → 200 en: /api/schedule, /api/taken, /api/status
# Estáticos públicos → 200 en: /, /index.html

# V9: POST /api/taken
#   con token de sesión → 403 (origen no verificado)
#   con DEV_TOKEN + clave válida → 200
#   con DEV_TOKEN + clave malformada → 400
#   con DEV_TOKEN + value no booleano → 400

# Logout → 200; token posterior → 401

# WebSocket (ClientWebSocket .NET): connect /ws?token=<sesión> → Open
#   POST /api/taken con DEV_TOKEN → push recibido:
#   {"type": "on_pill_taken", "key": "2026-08-01_1_10:30", "taken": true}
#   /ws sin token → 401

# Scheduler (H3/H6): slot 1 y slot 2 con la hora actual en Sab
#   → 2 records tras ≤20 s: {"key":"2026-08-01_1_17:44","taken":true}, {"key":"2026-08-01_2_17:44","taken":true}
#   /api/status → {"driver":"DevDriver (mock GPIO)","ok":true,"last_events":[["dispense",1,"17:44"],["dispense",2,"17:44"]]}
```

Limpieza post-smoke: `schedule.json`/`taken_log.json` restaurados a backups; datos legados V4/V5 limpiados en el commit PR 2 (slot 1 `Sab: [""]` → `[]`, slot 3 fantasma → vacío, claves malformadas del log eliminadas).
