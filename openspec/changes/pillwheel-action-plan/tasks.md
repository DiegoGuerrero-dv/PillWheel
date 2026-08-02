# Tasks: PillWheel — Backend seguro y arquitectura HAL

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 700–850 (total) / ~350–450 por PR |
| Review budget (D2) | 800 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 (stacked-to-main) |
| Delivery strategy | ask-on-risk (usuario eligió chained) |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium

### Dependency Diagram

    main ← PR 1 (Fases 1–2, base main) ← PR 2 (Fases 3–4, base main)

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Seguridad F1 + storage + validaciones | PR 1 | Fases 1–2; base main; verificación: smoke tests auth/storage |
| 2 | HAL + scheduler + UI + docs | PR 2 | Fases 3–4; base main (stacked-to-main); depende de PR 1 |

## Phase 1: Foundation — Config y Auth F1 (PR 1)

- [x] 1.1 `Dev_server.py` Config: agregar `ADMIN_USER` y `RETENTION_DAYS` a load_env_file/defaults; actualizar `.env.example`
- [x] 1.2 `Dev_server.py` AuthService: `login(user, password)` → token de sesión (secrets, en memoria), `require_session()`, `logout()`
- [x] 1.3 `Dev_server.py` rutas: `/api/login` usa AuthService; endpoints protegidos exigen sesión (ya no DEV_TOKEN)

## Phase 2: Storage y Seguridad (PR 1)

- [x] 2.1 `taken_log.json`: migrar dict → records `{key, taken, ts}` con migración del formato viejo
- [x] 2.2 `Dev_server.py` purga: entradas > `RETENTION_DAYS` (182) al arranque y en cada write (spec data-retention)
- [x] 2.3 `Dev_server.py` validación de slots: rechazar hora vacía (V4), hora sin name (V5), upsert con id inexistente → 4xx, insert válido (V8)
- [x] 2.4 `Dev_server.py` estáticos: `/schedule.json`, `/taken_log.json`, `/Dev_server.py` → 401 sin sesión (V1/V2)

## Phase 3: HAL + Scheduler (PR 2)

- [ ] 3.1 `Dev_server.py` DriverPort (Protocol) + DevDriver mock que simula GPIO y auto-confirma toma (H5/H6)
- [ ] 3.2 `Dev_server.py` scheduler thread: dispara `dispense`/`ring` según schedule (timer en backend)
- [ ] 3.3 `Dev_server.py` `/api/taken` POST: solo vía adapter con device token F2, valida origen (V9)
- [ ] 3.4 `Dev_server.py` WS hub RFC 6455 mínimo en stdlib (~100 líneas) + push de `on_pill_taken`
- [ ] 3.5 `Dev_server.py` `/api/status` (sesión) → `driver.status()`

## Phase 4: Frontend y Documentación (PR 2)

- [ ] 4.1 `script.js` renderDashboard: escapar datos, sin onclick con JSON ni innerHTML crudo (V3)
- [ ] 4.2 `script.js`/`index.html`: login con usuario+contraseña, botón logout, token de sesión
- [ ] 4.3 `script.js` cliente WS `/ws`: actualiza UI al recibir `on_pill_taken`; reconnect/fallback
- [ ] 4.4 `docs/architecture.md` + `docs/action-plan.md`: checklist V1–V10 cerrado + contrato H4
- [ ] 4.5 Smoke tests `docs/run-and-test.md` (login/logout, 401s, validación, purga, WS)
