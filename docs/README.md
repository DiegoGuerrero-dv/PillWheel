# PillWheel — Documentación

Sede de la documentación del proyecto. Aquí viven la arquitectura, las guías de ejecución y prueba, y los artefactos de SDD generados durante el desarrollo.

## Índice

| Archivo | Contenido |
| --- | --- |
| [architecture.md](architecture.md) | Arquitectura actual: stack, contrato de API, modelo de datos, decisiones de diseño y problemas conocidos. |
| [run-and-test.md](run-and-test.md) | Cómo correr el proyecto y cómo probarlo (manual y por API). |
| `sdd/` (futuro) | Artefactos SDD por cambio: exploración, propuesta, spec, diseño y tareas. |

## Convenciones

- El idioma de los artefactos técnicos es español neutro, consistente con la UI y los comentarios del proyecto.
- La documentación se actualiza junto con el código: si un artefacto cambia, su doc asociada cambia en el mismo commit.
- Los problemas conocidos se registran en [architecture.md](architecture.md#problemas-conocidos) hasta que se corrijan; al corregirlos se mueven a decisiones (o se eliminan).

## Cómo se integra con SDD

El flujo SDD puede escribir sus artefactos dentro del repo (modo `openspec`/híbrido) para que queden trazables en revisión:

- Los artefactos de un cambio viven en `docs/sdd/<nombre-del-cambio>/` o en `openspec/` en la raíz según el backend activo.
- La arquitectura documentada aquí es la línea base que los specs de SDD deben respetar o actualizar explícitamente.
