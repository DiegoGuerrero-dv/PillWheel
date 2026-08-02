# hardware-driver Specification — delta day-toggle

## Requirements

### Requirement: Scheduler respeta días desactivados

The system MUST NOT llamar `dispense`/`ring` en un día con `enabled[<día actual>] === false`, aunque haya horas configuradas en `schedule[<día actual>]`.

#### Scenario: Dosis programada en día desactivado

- GIVEN un slot con horas en `schedule['Lun']` y `enabled['Lun'] = false`
- WHEN el scheduler evalúa un lunes a la hora programada
- THEN no se llama a `driver.dispense` para ese slot

#### Scenario: Día activo sigue dispensando

- GIVEN un slot con horas en `schedule['Lun']` y `enabled['Lun'] = true`
- WHEN el scheduler evalúa un lunes a la hora programada
- THEN se llama a `driver.dispense` para ese slot normalmente
