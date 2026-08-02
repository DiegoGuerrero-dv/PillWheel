# Design: Day Toggle — días de la semana activables/desactivables por casilla

## Technical Approach

Cambio aditivo sobre el modelo actual de `schedule.json`: cada slot puede llevar un campo `enabled` (mapa `{Dom..Sab: bool}`) que indica qué días están activos. Ausente = todos activos, para no romper los datos existentes. El backend valida y persiste el campo sin cambios de ruta de API; el scheduler filtra días desactivados antes de dispensar; el frontend hace toggle en el chip del día y filtra el dashboard. Sin dependencias externas.

## Architecture Decisions

| Decisión | Opciones | Tradeoff | Decisión |
|---|---|---|---|
| Representación de días inactivos | `enabled` map completo vs lista `disabled` vs borrar horas | Borrar horas viola el requisito (conservar); `disabled` con default invertido es propenso a errores | `enabled: {día: bool}` dentro del slot; clave ausente o campo ausente = activo |
| Default para datos viejos | Todos activos vs todos inactivos | Inactivos rompería horarios existentes | Todos activos (compatibilidad total) |
| Dónde persiste `enabled` | En el slot de `schedule.json` vs archivo separado | Archivo separado duplica estado y sincronización | Dentro del slot: misma lectura/escritura/validación |
| Interacción del click | Toggle directo en el chip vs menú contextual | Menú = más pasos; el usuario pidió toggle simple | Click en día seleccionado → deselecciona y apaga; click en día apagado → reactiva |
| Día tras deseleccionar | `editingDay = null` (panel "sin día") vs saltar al primer activo | Saltar a otro día oculta el estado desactivado recién creado | `editingDay = null`: el panel muestra mensaje neutro, ningún chip activo |
| Dashboard | Filtrar en `getTodayDoses` vs marcar como no pendiente | Marcar no pendiente conserva ruido visual | Filtrar: el slot no produce dosis ese día |

## Data Flow

    Editor: click chip día
      ├─ d === editingDay  → enabled[d] = false (conserva schedule[d]); editingDay = null
      ├─ d desactivado     → enabled[d] = true; editingDay = d (copia horas si estaba vacío)
      └─ d día común       → editingDay = d (copia horas si estaba vacío, comportamiento actual)
    Guardar: saveSlot envía slot completo (con enabled) → POST /api/schedule → validate_slot → save_schedule
    Scheduler (20 s): slot → enabled.get(day, True) === false ? skip : dispense si hhmm in schedule[day]

## File Changes

| File | Action | Description |
|---|---|---|
| `Dev_server.py` | Modify | `validate_slot` acepta y valida `enabled`; `Scheduler.run` salta días con `enabled.get(day, True) is False` |
| `script.js` | Modify | `openEditor` inicializa `enabled`; `selectDay` con toggle; `renderDayStrip` marca chips `off`; `getTodayDoses` filtra; `clearSlot` resetea `enabled` |
| `style.css` | Modify | Clase `.day-chip.off` (visual de día apagado) |
| `schedule.json` | Modify | Los slots editados guardan `enabled` (aditivo) |
| `docs/architecture.md` | Modify | Modelo de datos con `enabled` + regla day-toggle |
| `openspec/specs/schedule-days` | New | Spec del comportamiento (fase spec ya escrita) |
| `openspec/specs/hardware-driver` | Modify | Delta scheduler respeta días inactivos (ya escrita) |

## Interfaces / Contracts

Forma del slot (aditivo):

```json
{
  "id": 1,
  "name": "Losartán",
  "color": "#4fd1ae",
  "schedule": { "Dom": ["08:00", "16:00"], "Lun": ["08:00"], "Mar": [], "Mie": [], "Jue": [], "Vie": [], "Sab": [] },
  "enabled": { "Dom": true, "Lun": true, "Mar": true, "Mie": true, "Jue": true, "Vie": true, "Sab": true }
}
```

- `enabled` es opcional; una clave ausente o el campo ausente equivalen a activo.
- `validate_slot`: si `enabled` viene, debe ser dict; cada clave debe pertenecer a `DAY_KEYS` y su valor se normaliza con `bool()`.
- Scheduler: `if slot.get('enabled', {}).get(day, True) is False: continue` — no se toca el mapeo `DAY_KEYS[(weekday()+1)%7]`.
- Frontend: `editingSlot.enabled` inicializado a todos `true` si no viene; al deseleccionar se conserva `schedule[d]` intacto.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Smoke manual | Toggle en editor, persistencia en `schedule.json`, dashboard filtra, reactivación, vaciar resetea | Checklist en `docs/run-and-test.md` (servidor dev + navegador) |
| Scheduler | Skip de días desactivados / dispensa en días activos | Inspección del filtro + opcional script `unittest` de `validate_slot`/filtro si se agrega |

## Migration / Rollout

- Aditivo y sin migración: los slots sin `enabled` se tratan con todos los días activos.
- Sin feature flags. Si algo falla, revert git (el campo es opcional, el comportamiento previo queda intacto con solo quitar los commits).

## Open Questions

- None blocking. El filtrado del scheduler se valida por inspección/smoke: disparar una dosis real requiere esperar la hora o reducir el intervalo en desarrollo.
