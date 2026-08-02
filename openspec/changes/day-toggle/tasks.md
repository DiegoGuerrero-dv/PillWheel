# Tasks: Day Toggle — días de la semana activables/desactivables por casilla

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 80–130 |
| Review budget (D2) | 800 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | 1 PR (cambio atómico) |
| Delivery strategy | force-chained (preflight C3) → sin slices necesarios |
| Chain strategy | n/a (no aplica encadenado) |

Decision needed before apply: No
Chained PRs recommended: No
400-line budget risk: Low

### Dependency Diagram

    main ← PR único (day-toggle)

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Backend + editor + dashboard + CSS + docs | PR único | Cambio cohesivo <130 líneas; verificación: smoke manual |

## Phase 1: Backend — validación y scheduler (PR único)

- [x] 1.1 `Dev_server.py` `validate_slot`: aceptar y validar `enabled` (dict con claves en `DAY_KEYS`, valores normalizados con `bool()`; campo opcional)
- [x] 1.2 `Dev_server.py` `Scheduler.run`: saltar slots/días con `slot.get('enabled', {}).get(day, True) is False` antes de dispensar (sin tocar el mapeo de días)

## Phase 2: Editor — toggle de días

- [x] 2.1 `script.js` `openEditor`: inicializar `editingSlot.enabled` (todos `true` si el slot no trae el campo)
- [x] 2.2 `script.js` `selectDay`: toggle — click en día seleccionado → `enabled[d]=false` conservando `schedule[d]` y `editingDay=null`; click en día desactivado → `enabled[d]=true` + copiar horas si estaba vacío; click en día común → comportamiento actual
- [x] 2.3 `script.js` `renderDayStrip`: marcar chips con `enabled[d]===false` con clase `off`; ningún chip `active` cuando `editingDay` es null
- [x] 2.4 `script.js` `renderTimesPanel`: mostrar mensaje "Seleccioná un día" cuando `editingDay` es null
- [x] 2.5 `script.js` `clearSlot`: resetear `enabled` (todos `true`) junto con nombre y horarios

## Phase 3: Dashboard

- [x] 3.1 `script.js` `getTodayDoses`: filtrar slots con `enabled[today] === false` (no aparecen como pendientes)

## Phase 4: CSS

- [x] 4.1 `style.css`: clase `.day-chip.off` (día desactivado visualmente apagado, dot atenuado)

## Phase 5: Documentación y verificación

- [x] 5.1 `docs/architecture.md`: modelo de datos con `enabled` + regla day-toggle
- [x] 5.2 `docs/run-and-test.md`: checklist smoke del toggle (deseleccionar/reactivar, persistencia, dashboard, vaciar)
- [x] 5.3 Smoke test manual: toggle en editor, `schedule.json` conserva horas + `enabled`, dashboard filtra, vaciar resetea, slots viejos sin `enabled` siguen activos
