# data-retention Specification

## Purpose

Retención del historial de tomas: 6 meses con purga automática, cuidando además la vida útil de la flash del ESP32 en el target real.

## Requirements

### Requirement: Retención de 6 meses

The system MUST conservar las entradas del log de tomas durante al menos 6 meses.

#### Scenario: Entrada dentro del período

- GIVEN una toma registrada hace menos de 6 meses
- WHEN se consulta el log de tomas
- THEN la entrada está disponible

### Requirement: Purga automática

The system MUST purgar las entradas con más de 6 meses automáticamente (al arrancar y periódicamente). La purga MUST NOT afectar los datos del schedule.

#### Scenario: Entrada vencida

- GIVEN una toma registrada hace más de 6 meses
- WHEN la purga se ejecuta (arranque o período)
- THEN la entrada se elimina del log de tomas

#### Scenario: La purga no toca el schedule

- GIVEN un schedule activo
- WHEN la purga se ejecuta
- THEN el schedule permanece intacto
