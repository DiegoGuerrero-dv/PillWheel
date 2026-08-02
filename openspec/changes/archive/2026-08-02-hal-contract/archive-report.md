# Archive Report — hal-contract

## Change Archived

**Change**: hal-contract
**Archived to**: `openspec/changes/archive/2026-08-02-hal-contract/`
**Fecha**: 2026-08-02
**Modo**: hybrid (openspec + engram)

## Estado final

- **Verdict verify**: PASS (20/20 tests, smoke E2E verificado por el usuario, auditoría fresca R3 sin CRITICAL ni WARNING pendientes).
- **Tasks**: 38/38 completas (0 sin marcar).
- **Dispatcher nativo**: verify=all_done, archive=ready, blockedReasons=[].
- **Soporte**: sub-agente `sdd-archive` devolvió resultado vacío (falla de herramienta documentada en esta sesión, misma que `sdd-verify`); el orquestador ejecutó el archive manualmente según el skill `sdd-archive`.

## Specs Synced

| Domain | Action | Details |
|--------|--------|---------|
| hal | Created | `openspec/specs/hal/spec.md` — spec completa (driver HAL, logging, modal, sim, re-alarma, contrato firmware) |
| hardware | Created | `openspec/specs/hardware/spec.md` — spec completa (sistema embebido: buzzer, OLED, LED, sensor, re-alarma) |

Nota: el delta `hardware` se archivó como spec de dominio propia (`openspec/specs/hardware/spec.md`); no se mergeó en `hardware-driver` porque los requirements del delta no modifican ni eliminan ninguno de los 3 requirements existentes (DriverPort H4, Confirmación por sensor, Adaptador Dev) — son dominios complementarios (arquitectura hexagonal vs. comportamiento del sistema embebido).

## Archive Contents

- proposal.md ✅
- specs/ ✅ (hal, hardware)
- design.md ✅
- tasks.md ✅ (38/38)
- verify-report.md ✅ (PASS)
- archive-report.md ✅ (este archivo)

## Deuda post-cierre (no bloqueante)

- **W2**: estado pendiente solo en memoria (`_pending` en DevDriver) — decisión de diseño explícita; requiere nota en docs.
- **W3**: contrato UI del modal sin cobertura automatizada (solo checklist manual).
- **S1**: un open→close confirma TODAS las dosis pendientes del slot.
- **S4**: tests de scheduler con reloj real; faltan tests de `init()`, dedupe de re-disparo, open sin pendientes, body vacío.

## Resueltos durante verify

- **W1**: persistencia JSON no atómica + RMW destructivo → fix v3 (write atómico + retry + IO_LOCK RLock + read que propaga errores), 7 StorageTests nuevos.
- **S2**: `DriverPort.slot_closed` anotado `-> bool` (antes `-> None`).
- **S3**: docstring de cabecera corregido (ya no dice "auto-confirma").

## Source of Truth Updated

Las siguientes specs ahora reflejan el comportamiento nuevo:
- `openspec/specs/hal/spec.md`
- `openspec/specs/hardware/spec.md`

## SDD Cycle Complete

El cambio ha sido planeado, implementado, verificado y archivado. Listo para el próximo cambio.
