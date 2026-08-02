# Design: PillWheel — Backend seguro y arquitectura HAL

## Technical Approach

Refactor de `Dev_server.py` en capas dentro de un solo archivo (convención actual y espejo del target ESP32): Config → Auth (F1) → API (REST + WS) → Storage → Scheduler → DriverPort + DevDriver. Sin librerías externas (stdlib puro).

## Architecture Decisions

| Decisión | Opciones | Tradeoff | Decisión |
|---|---|---|---|
| Fronteras F1/F2 | Token único vs separados | Hoy login devuelve `DEV_TOKEN` (no distingue quién reporta) | Sesión F1 (random, en memoria) + device token F2 (config). Login ya NO devuelve `DEV_TOKEN` |
| Sesión | Memoria vs persistida | Persistida sobrevive reinicios (viola spec) | En memoria: el reinicio invalida los tokens |
| WebSockets stdlib | Librería vs hand-rolled vs SSE | Sin dependencias externas | WS RFC 6455 mínimo en stdlib (~100 líneas), hub simple; paridad con el ESP32 |
| Schema taken_log | `dict{key:bool}` vs records con `ts` | Sin `ts` no hay purga por fecha | Lista de records `{key, taken, ts}` con migración del formato viejo |
| Timer | En driver vs backend | Spec: timer en backend | Scheduler thread en backend |

## Data Flow

    Browser ──POST /api/login──→ Auth ──session token──→ Browser
    Browser ──GET/POST /api/* (Bearer sesión)──→ API ──→ Storage
    Scheduler ──dispense/ring──→ DriverPort ──→ DevDriver (mock GPIO)
    DevDriver ──on_pill_taken──→ Storage ──WS push──→ Browser
    POST /api/taken (Bearer device F2) ──→ solo desde adapter, valida origen

F2 es interna: scheduler llama al DriverPort directo (mismo proceso); la frontera de red queda solo en F1.

## File Changes

| File | Action | Description |
|---|---|---|
| `Dev_server.py` | Modify | Refactor en capas + WS hub + scheduler + DriverPort/DevDriver + retención |
| `script.js` | Modify | Escapado en renderDashboard, login/logout con sesión, cliente WS |
| `index.html` | Modify | Login con usuario+contraseña, botón logout |
| `taken_log.json` | Modify | Migrar a records `{key, taken, ts}` |
| `.env.example` | Modify | `ADMIN_USER`, `RETENTION_DAYS` |
| `docs/architecture.md` / `docs/action-plan.md` | Modify | Estado final HAL + checklist V1–V10 |

## Interfaces / Contracts

```python
class DriverPort(Protocol):
    def dispense(self, slot_id: str, time: str) -> bool: ...
    def ring(self) -> None: ...
    def status(self) -> dict: ...
    def on_pill_taken(self, slot_id: str, time: str) -> None: ...

class DevDriver:  # adaptador mock H5/H6: simula GPIO y auto-confirma la toma
    ...
```

API: `POST /api/login {user, password} → {token}` · `POST /api/logout` · `GET/POST /api/schedule` (sesión; valida V4/V5/V8) · `GET /api/taken` (sesión) · `POST /api/taken` (device F2, vía adapter) · `GET /api/status` (sesión) · `WS /ws` (sesión, push de `on_pill_taken`). Estáticos: `index.html`/`style.css`/`script.js` públicos; `/schedule.json`, `/taken_log.json`, `/Dev_server.py` → 401 sin sesión (V1/V2).

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Smoke | login/logout, 401s, upsert validado, purga, WS | scripts de `docs/run-and-test.md` |
| Unit (si se agregan) | validación de slots, retención, auth | `unittest` stdlib |

## Migration / Rollout

- `taken_log.json` migra a records con `ts` al primer arranque (dict viejo → lista).
- Sin feature flags. Refactor aditivo: si algo falla, revert git.

## Open Questions

- None blocking. El schema de `taken_log` queda fijo para que el firmware del ESP32 (ciclo futuro) lo replique tal cual.
