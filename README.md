# PillWheel

Pastillero inteligente: un panel web para programar y controlar un blister de **8 casillas** con horarios de medicación por día de la semana. Al llegar la dosis, suena la alarma, se muestra la pastilla en la pantalla OLED y el LED de la casilla se enciende; al abrir y cerrar el compartimiento, la toma queda confirmada.

## Stack

| Capa | Tecnología |
| --- | --- |
| Frontend | HTML + CSS + JS vanilla, sin dependencias ni build |
| Backend dev | Python 3 (solo stdlib: `http.server`) |
| Persistencia | JSON en disco (`schedule.json`, `taken_log.json`) |
| Dispositivo | ESP32 + firmware (Arduino/C++) acoplado por contrato HAL |

## Estructura del proyecto

```
PillWheel/
├── Dev_server.py          # Backend dev (Python stdlib)
├── index.html             # Frontend
├── script.js              # Lógica del frontend
├── style.css              # Estilos
├── schedule.json          # Persistencia de horarios
├── taken_log.json         # Log de tomas
├── .env                   # Credenciales (no commitear)
├── adapters/              # Adaptadores del puerto DriverPort
│   └── esp32_driver.py    # Adaptador HTTP → ESP32 (pendiente)
├── firmware/              # Código del ESP32 (Arduino/C++)
│   └── pillwheel/         # Firmware del dispositivo
├── docs/                  # Documentación técnica
│   ├── architecture.md    # Arquitectura hexagonal y decisiones
│   ├── esp32-contract.md  # Contrato de integración firmware ↔ backend
│   ├── run-and-test.md    # Cómo correr y probar
│   └── action-plan.md     # Plan de acción y cierre de vulnerabilidades
└── openspec/              # Artefactos del flujo SDD
    ├── config.yaml
    ├── specs/
    └── changes/
```

## Arquitectura

El proyecto usa **Arquitectura Hexagonal** (Ports & Adapters / HAL):

```
Browser ──/api/*──► Backend (núcleo) ──DriverPort──► Adapter Dev (PC) / Adapter ESP32
                        ▲  scheduler                    │
                        └────── eventos (log) ◄─────────┘
```

- **Puerto `DriverPort`**: contrato abstracto del hardware (10 funciones). El backend depende de la interfaz, no de la implementación.
- **Adaptador `DevDriver`**: simula GPIO en PC para desarrollo sin hardware.
- **Adaptador `Esp32Driver`** (`adapters/esp32_driver.py`): habla por HTTP con el ESP32 usando el contrato de `esp32-contract.md`.
- **Firmware** (`firmware/pillwheel/`): código que corre en el ESP32, implementa los endpoints que el `Esp32Driver` llama.

## Trabajar con SDD (Spec-Driven Development)

Este proyecto usa SDD para planificar e implementar cambios. El flujo es:

### Comandos disponibles

| Comando | Qué hace |
| --- | --- |
| `/sdd-new <cambio>` | Explorar + proposal para un cambio nuevo |
| `/sdd-ff <nombre>` | Fast-forward: proposal → specs → design → tasks |
| `/sdd-continue [cambio]` | Ejecutar la siguiente fase pendiente |
| `/sdd-status [cambio]` | Ver estado del cambio activo |
| `/sdd-apply [cambio]` | Implementar tareas del cambio |
| `/sdd-verify [cambio]` | Validar implementación contra specs |
| `/sdd-archive [cambio]` | Cerrar cambio y persistir estado |

### Flujo típico

1. **`/sdd-new integrar-esp32`** → SDD explora el codebase, genera proposal
2. **`/sdd-ff integrar-esp32`** → avanza automáticamente por specs → design → tasks
3. Revisar los artefactos generados en `openspec/`
4. **`/sdd-apply integrar-esp32`** → implementa las tareas
5. **`/sdd-verify integrar-esp32`** → valida contra specs
6. **`/sdd-archive integrar-esp32`** → cierra el cambio

### Artefactos SDD

Viven en `openspec/`:

- `openspec/specs/` — especificaciones de cada cambio
- `openspec/changes/` — proposal, design, tasks de cambios activos
- `openspec/config.yaml` — configuración del proyecto

## Integrar el ESP32

El ESP32 **no reimplementa el servidor web**: el backend sigue siendo el punto de entrada del navegador. El firmware es un **adaptador del puerto de hardware**.

### Pasos de acople

1. **Leer el contrato** (`docs/esp32-contract.md`): mapeo de `DriverPort` → comandos de red.
2. **Implementar `Esp32Driver`** en `adapters/esp32_driver.py`: clase que cumple `DriverPort` y habla por HTTP al ESP32.
3. **Implementar el firmware** en `firmware/pillwheel/`: recibir comandos (`/dispense`, `/ring`, `/led`, `/oled`, `/init`, `/status`) y reportar eventos (`/events`).
4. **Configurar `DEV_TOKEN`** en `.env` del backend y en el firmware (Frontera 2).
5. **Probar con `DevDriver`** antes de conectar hardware: el adaptador simulado deja el contrato estable para el swap.

### Contrato rápido

| DriverPort | Comando firmware | Payload |
| --- | --- | --- |
| `dispense(slot_id, time)` | `POST /dispense` | `{"slot_id": 1, "time": "08:00"}` |
| `ring()` | `POST /ring` | `{}` |
| `oled_show(slot_id, name, time)` | `POST /oled` | `{"slot_id": 3, "name": "Paracetamol", "time": "08:00"}` |
| `led_on(slot_id)` | `POST /led` | `{"slot_id": 3, "on": true}` |
| `led_off(slot_id)` | `POST /led` | `{"slot_id": 3, "on": false}` |
| `status()` | `GET /status` | — |
| `slot_open(slot_id)` | `POST /events` | `{"type": "slot_open", "slot_id": 3}` |
| `slot_closed(slot_id)` | `POST /events` | `{"type": "slot_closed", "slot_id": 3}` |

Ver `docs/esp32-contract.md` para el detalle completo de autenticación y reglas.

## Cómo correr

```bash
# Modo desarrollo (simula hardware)
python3 Dev_server.py
# → http://localhost:8000

# Con bind en LAN
python3 Dev_server.py --host 0.0.0.0
```

Credenciales por defecto: `admin` / `admin1234`. Crear `.env` a partir de `.env.example` para personalizar.

## Convenciones

- Artefactos técnicos en español neutro.
- La documentación se actualiza junto con el código.
- Los artefactos SDD viven en `openspec/`, la documentación técnica en `docs/`.
