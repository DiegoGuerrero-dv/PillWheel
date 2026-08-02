# Propuesta: PillWheel — Backend seguro y arquitectura HAL

## Intent

Cerrar las vulnerabilidades V1–V10 del backend y adoptar arquitectura hexagonal (Ports & Adapters / HAL) para el control del dispensador. El target real del backend es correr en el ESP32; `Dev_server.py` queda como adaptador de desarrollo/mock con el mismo contrato.

## Scope

### In Scope
- Fase 1: cerrar V1–V10 (auth F1, XSS, validación de slots/dosis, origen de `/api/taken`, retención 6 meses con purga, restricción de exposición).
- Fase 2: `DriverPort` con `dispense/ring/status/on_pill_taken`, contrato H4 documentado, adaptadores Dev (mock) H5/H6.
- Transporte F1: HTTP REST + WebSockets. F2: HAL interna directa (sin red — backend y dispositivo corren juntos en el target ESP32).

### Out of Scope
- Firmware del ESP32 (Opción A: solo contrato H4 + mock en Python).
- Rediseño de UI/maquetado.
- MQTT (extensión futura con broker/notificaciones remotas).

## Capabilities

### New Capabilities
- `user-auth`: autenticación F1 — admin único, token de sesión, logout/reinicio invalida.
- `api-security`: hardening — estáticos y datos protegidos (V2), saneamiento XSS (V3), validación slots/dosis (V4/V5), validación de upsert (V8), origen verificado en `/api/taken` (V9).
- `data-retention`: log de tomas con retención 6 meses y purga automática.
- `hardware-driver`: DriverPort HAL + adaptadores Dev y simulado (H1–H6).

### Modified Capabilities
None (no hay specs previas en `openspec/specs/`).

## Approach

Refactor de `Dev_server.py` en capas: config (env), auth F1, API (REST+WS), storage (JSON con retención) y núcleo HAL detrás de `DriverPort`. La confirmación de toma la genera el ESP32 con sensor (`on_pill_taken`); `/api/taken` valida origen. Smoke tests de `docs/run-and-test.md`.

## Affected Areas

| Area | Impact | Descripción |
|------|--------|-------------|
| `Dev_server.py` | Modificado | Refactor: auth, API, storage, HAL |
| `script.js` | Modificado | Escapado en renderDashboard, WebSockets |
| `index.html` | Modificado | Logout, sin sinks XSS |
| `schedule.json` / `taken_log.json` | Modificado | Retención 6 meses |
| `docs/architecture.md` / `docs/action-plan.md` | Modificado | Estado final |
| `.env` / `.env.example` | Hecho | Config por entorno |

## Risks

| Risk | Likelihood | Mitigación |
|------|------------|------------|
| Sin hardware: contrato H4 sin validación real | Alta | Mock H5/H6 + contrato documentado |
| Refactor toca todos los endpoints | Media | Smoke tests por fase |
| WebSockets agrega estado a la UI | Media | Reconnect + fallback a polling |

## Rollback Plan

Revert del/los commit(s) del cambio en git. La configuración vuelve a defaults de `.env.example` (sin secretos commiteados). El contrato HAL es aditivo: el backend actual funciona sin él.

## Dependencies

- Ninguna externa. Python 3 stdlib.

## Success Criteria

- [ ] Checklist V1–V10 cerrado en `docs/action-plan.md` con verificación
- [ ] Smoke tests de `docs/run-and-test.md` pasan
- [ ] Contrato H4 documentado y adaptadores Dev/mock funcionando
