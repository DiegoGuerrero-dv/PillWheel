# Propuesta: Day Toggle — días de la semana activables/desactivables por casilla

## Intent

Agregar estado activo/inactivo por día de la semana en cada casilla del pastillero. Al hacer click en un día que ya está seleccionado, el día se deselecciona y su horario deja de ejecutarse; las horas configuradas se conservan y pueden reactivarse con un click. Este es el comportamiento ideal del editor de horarios: configurar las horas una sola vez por casilla y activar/desactivar días sin borrar nada.

## Scope

### In Scope
- Modelo de datos: campo `enabled: {Dom: bool, ...}` en cada slot de `schedule.json`. Ausente = todos los días activos (compatibilidad con datos existentes, sin migración forzosa).
- Backend: `validate_slot` acepta `enabled` opcional y válido; el scheduler NO dispara dosis en días con `enabled[día] === false`; la persistencia guarda el campo tal cual.
- Frontend (editor): los chips de día muestran el estado activo/inactivo; click en día seleccionado → deseleccionar (desactiva, conservando horas); click en día desactivado → reactivar; click en día vacío sigue copiando horas del día visible (comportamiento ya aprobado).
- Dashboard: las dosis de un día desactivado no aparecen como pendientes.
- "Vaciar casilla" resetea nombre, horarios y estado de días (todo vuelve a activo).
- Specs OpenSpec nuevas/actualizadas y `docs/architecture.md`.

### Out of Scope
- Firmware del ESP32 y contrato H4 (deuda documentada del proyecto).
- Rediseño de UI o cambio de rutas de API (el cambio de forma del slot es aditivo).
- Cambio en el modelo del log de tomas (`taken_log.json`).

## Capabilities

### New Capabilities
- `schedule-days`: modelo de días activos/inactivos por casilla, reglas de activación/desactivación, conservación de horarios, filtrado del dashboard y comportamiento del editor.

### Modified Capabilities
- `hardware-driver`: el scheduler del backend debe respetar el estado `enabled` por día antes de disparar `dispense`.

## Approach

Cambio aditivo y compatible hacia atrás:

1. `schedule.json`: cada slot puede llevar `enabled` (mapa de 7 claves `Dom..Sab` con valores booleanos). Los slots existentes sin el campo se tratan como todos activos.
2. `Dev_server.py`: `validate_slot` valida `enabled` si viene (claves conocidas, valores booleanos); el scheduler consulta `slot.get('enabled', {}).get(day, True)` antes de dispensar.
3. `script.js`: `renderDayStrip` pinta el estado (clase CSS `off`); `selectDay` hace toggle: día seleccionado → deselecciona (marca `enabled[day]=false`, conserva `schedule[day]`); día desactivado → reactiva; `getTodayDoses` filtra por `enabled[today]`.
4. `style.css`: clase `.day-chip.off` (apagado visual).
5. Specs y docs: nueva capability `schedule-days` + actualización de `hardware-driver` y `docs/architecture.md`.

## Affected Areas

| Area | Impact | Descripción |
|------|--------|-------------|
| `Dev_server.py` | Modificado | Validación `enabled`, scheduler respeta días inactivos |
| `script.js` | Modificado | Toggle en `selectDay`, render del chip, filtro del dashboard |
| `style.css` | Modificado | Clase `.day-chip.off` |
| `schedule.json` | Modificado | Slots guardan `enabled` |
| `docs/architecture.md` | Modificado | Modelo de datos y regla de días activos |
| `openspec/specs/schedule-days` | Nuevo | Spec del comportamiento ideal |
| `openspec/specs/hardware-driver` | Modificado | Scheduler respeta días inactivos |

## Risks

| Risk | Likelihood | Mitigación |
|------|------------|------------|
| Datos existentes sin `enabled` | Alta | Default `true` por ausencia; sin migración forzosa |
| Interacción con la copia automática de horas | Media | Copiar solo cuando el día está vacío; desactivar nunca borra horas |
| Romper el mapeo de días del scheduler | Baja | No tocar `DAY_KEYS[(weekday()+1)%7]`; solo filtrar antes de dispensar |
| Sin test runner (smoke manual) | Media | Checklist manual en `docs/run-and-test.md` |

## Rollback Plan

Revert del/los commit(s) del cambio en git. El campo `enabled` es aditivo: un revert deja los slots sin el campo y el scheduler con el comportamiento original.

## Dependencies

- Ninguna externa. Python 3 stdlib.

## Success Criteria

- [ ] Click en un día seleccionado lo deselecciona y el scheduler no dispensa en ese día
- [ ] Las horas del día desactivado se conservan en `schedule.json` y en el editor
- [ ] Click en un día desactivado lo reactiva mostrando sus horas guardadas
- [ ] Un día vacío sigue copiando las horas del día visible al seleccionarlo
- [ ] El dashboard no muestra dosis pendientes de días desactivados
- [ ] Los slots existentes sin `enabled` siguen funcionando (todos activos)
- [ ] "Vaciar casilla" resetea nombre, horarios y estado de días
- [ ] Spec `schedule-days` documenta el comportamiento ideal y `hardware-driver` refleja el filtro
