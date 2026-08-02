# schedule-days Specification

## Purpose

Estado activo/inactivo por día de la semana en cada casilla del pastillero. Un día deseleccionado conserva sus horas pero el sistema no ejecuta dosis en ese día. Este es el comportamiento ideal del editor de horarios: configurar las horas una sola vez y activar/desactivar días sin borrar nada.

## Requirements

### Requirement: Estado por día (`enabled`)

The system MUST soportar un campo `enabled` por slot: un objeto con claves `Dom..Sab` y valores booleanos. Un slot sin el campo, o con `enabled[día]` ausente, MUST tratarse con todos los días activos (compatibilidad con datos existentes). Un slot con `enabled[día] === false` MUST conservar sus horas en `schedule[día]`.

#### Scenario: Slot existente sin enabled

- GIVEN un slot sin el campo `enabled` (datos previos al cambio)
- WHEN se carga el horario
- THEN todos sus días se tratan como activos

#### Scenario: Desactivar conserva horas

- GIVEN un slot con horas en `schedule['Lun']`
- WHEN se desactiva el día `Lun` (`enabled['Lun'] = false`)
- THEN las horas de `Lun` se conservan en `schedule.json`

### Requirement: Toggle en el editor

The system MUST permitir deseleccionar un día activo con un click sobre el chip del día en el editor, y reactivarlo con otro click. El chip desactivado MUST mostrarse visualmente inactivo.

#### Scenario: Click en día seleccionado

- GIVEN el editor abierto con el día `Lun` seleccionado y activo
- WHEN el usuario hace click en el chip de `Lun`
- THEN el día se deselecciona, `enabled['Lun']` pasa a `false` y el chip se muestra inactivo, conservando las horas de `Lun`

#### Scenario: Click en día desactivado

- GIVEN el día `Lun` desactivado con horas guardadas
- WHEN el usuario hace click en el chip de `Lun`
- THEN el día se reactiva (`enabled['Lun'] = true`) y se muestran sus horas guardadas

#### Scenario: Seleccionar día vacío copia horas

- GIVEN un día sin horas en el editor
- WHEN el usuario lo selecciona
- THEN se copian las horas del día visible (o del último día con horas), manteniendo el comportamiento existente

### Requirement: Dashboard filtra días desactivados

The system MUST NOT mostrar como pendientes las dosis de un día desactivado en el panel "Hoy".

#### Scenario: Hoy desactivado

- GIVEN un slot con `enabled[<hoy>] = false` y horas configuradas en `schedule[<hoy>]`
- WHEN se renderiza el panel "Hoy"
- THEN las dosis de ese slot no aparecen como pendientes

### Requirement: Vaciar casilla resetea días

The system MUST resetear el estado de los días al vaciar una casilla: nombre vacío, `schedule` sin horas y `enabled` restablecido con todos los días activos.

#### Scenario: Vaciar casilla

- GIVEN una casilla con días desactivados y horarios configurados
- WHEN el usuario toca "Vaciar casilla"
- THEN el nombre se limpia, los horarios se borran y todos los días vuelven a activos
