# Plan de acción — Vulnerabilidades + HAL

**Objetivo:** cerrar todas las vulnerabilidades conocidas y reestructurar el backend hacia Arquitectura Hexagonal (Ports & Adapters / HAL), sin romper el contrato del frontend (`/api/*`).

**Documento relacionado:** [architecture.md](architecture.md) — arquitectura actual y objetivo.

**Ejecución:** el plan se ejecutó por el flujo SDD (propuesta → specs → diseño → tareas → apply → verify), en **2 PRs encadenados** (stacked-to-main):

- **PR 1 — Fases 1 y 2 (parte 1):** V1–V10 + scheduler + `DriverPort` + `DevDriver` + WS + `DEV_TOKEN`. Commits por unidad de trabajo, smoke test manual al cierre.
- **PR 2 — Fases 2 (parte 2) y 3:** endpoints de la frontera F2 (`/api/status`, WS `/ws`, `POST /api/taken` con device token), frontend (login con usuario, logout, push WS, V3/V9/V10) y docs.

> Estado 2026-08-01: **PR 1 verificado** (smoke test OK). **PR 2 implementado y verificado** (smoke test: login/logout, 401s, V9, WS push, scheduler→driver→log; datos legados V4/V5 limpiados). Pendiente solo el contrato `esp32-contract.md` (H4/H5), que necesita decisión de hardware.

---

## Priorización

| Severidad | Ítems |
| --- | --- |
| Alta | V1, V2, V3, V6, V7 |
| Media | V4, V5 |
| Baja / higiene | V8, V9, V10 |

Fase 1 primero (riesgo inmediato de fuga de datos), luego Fase 2 (HAL). Cada ítem con commit propio y verificación explícita.

---

## Fase 1 — Cerrar vulnerabilidades

| ID | Vulnerabilidad | Riesgo | Solución | Verificación |
| --- | --- | --- | --- | --- |
| V1 | **Bypass de auth por estáticos** | ALTA | Whitelist en `do_GET` de `Dev_server.py`: servir solo `/`, `/index.html`, `/style.css`, `/script.js`; todo lo demás 404. Los JSON se leen solo vía `/api/*`. | `curl /schedule.json` → 404; `curl /Dev_server.py` → 404; `curl /` → 200. |
| V2 | **Fuga de datos** (`schedule.json`, `taken_log.json`, fuente) | ALTA | Resuelto por V1. Confirmar que `GET /api/schedule` y `GET /api/taken` siguen 401 sin token y 200 con token. | Smoke test de API completo. |
| V3 | **XSS en `toggleTaken`** | ALTA | Reemplazar `onclick='toggleTaken(${JSON.stringify(dose)})'` por delegación de eventos con `data-*` attributes en `script.js`. | Nombre `');alert(1);//` se renderiza literal, sin ejecutarse. |
| V4 | **Horas vacías persistidas** | MEDIA | Validar formato `HH:MM` (`^([01]\d|2[0-3]):[0-5]\d$`) al guardar slot; rechazar vacíos. Limpiar datos existentes: slot 1 `"Sab": [""]` y clave `2026-07-25_1_` en el log. | Guardar hora vacía → 400 con error; JSON sin `""`. |
| V5 | **Dosis fantasma (slot 3)** | MEDIA | Al guardar, si la casilla tiene horarios, `name` es obligatorio. Limpiar/decidir el slot 3 actual. | Guardar horarios sin nombre → 400 con error. |
| V6 | **Credenciales hardcodeadas** | ALTA | Mover `ADMIN_PASSWORD` y `DEV_TOKEN` a variables de entorno, con defaults de dev y warning en consola. | Server arranca sin env usando default dev y avisa; con env usa los valores configurados. |
| V7 | **Bind en `0.0.0.0`** | MEDIA | Por defecto `127.0.0.1`; flag `--host 0.0.0.0` solo si se quiere exponer en LAN. | Por defecto no escucha en la interfaz de red; `netstat` lo confirma. |
| V8 | **Upsert silencioso de slots** | BAJA | Validar `id` en 1..8 y forma del slot; id desconocido o forma inválida → 400. | `POST /api/schedule` con id 99 → 400. |
| V9 | **`/api/taken` acepta claves arbitrarias** | BAJA | Validar formato de `key` (`YYYY-MM-DD_\d+_HH:MM`) y `value` booleano. | Clave malformada → 400. |
| V10 | **Código muerto** | BAJA | Eliminar `emptySchedule()` de `script.js`. | Sin referencias en el bundle. |

---

## Fase 2 — Implementar HAL (Hexagonal)

| ID | Entregable | Detalle | Verificación |
| --- | --- | --- | --- |
| H1 | **Puerto `DriverPort`** | Módulo `driver/port.py` con `Protocol`: `dispense(slot_id, time)`, `ring()`, `status()`, `on_pill_taken(slot_id, time)`. | Type check; tests de contrato con adapter falso. |
| H2 | **Refactor a módulos** | Separar `Dev_server.py` en `core/` (scheduler, lógica, validación), `ports/`, `adapters/` (http_server, json_store, dev_driver). Rutas `/api/*` idénticas. | Smoke test de API: mismos códigos y bodies que antes del refactor. |
| H3 | **Scheduler de dosis** | Hilo que cada minuto calcula las dosis vencidas de hoy (de `schedule.json`) y llama `driver.dispense(...)`; registra el intento en el log. | Con el adapter simulado, al llegar la hora se registra el evento. |
| H4 | **Contrato firmware ESP32** | Documento `docs/esp32-contract.md`: comandos que el dispositivo expone al backend (`POST /dispense`, `POST /ring`, `POST /events`), auth de dispositivo (Frontera 2), formato de payloads. | Revisión del contrato; payloads consistentes con `DriverPort`. |
| H5 | **Adapter mock ESP32** | `Esp32Driver` simulado (sin hardware) que implementa el contrato y permite E2E. | Tests end-to-end: scheduler → mock → log. |
| H6 | **Evento `pill_taken` real** | Endpoint en el backend donde el dispositivo reporta tomas reales → `taken_log.json` (prepara la integración sin acceso al hardware). | POST simulado desde el mock → se escribe en el log con la clave correcta. |

---

## Fuera de alcance

- Rediseño visual del frontend (UI).
- Firmware real del ESP32 (sin acceso al dispositivo; se deja el contrato en H4/H5).
- HTTPS / TLS en el backend dev (se documenta como limitación, no se implementa).

## Criterio de finalización

- Fase 1: todos los ítems V1–V10 verificados con el smoke test de API y pruebas manuales de regresión.
- Fase 2: el backend corre con `DevServerDriver`, el scheduler dispara y loguea, y el contrato ESP32 está especificado y probado contra el mock.
