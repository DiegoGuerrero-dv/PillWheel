# firmware/

Código del ESP32 para el pastillero PillWheel. Implementa los endpoints que el `Esp32Driver` llama por HTTP.

## Estructura

```
firmware/
└── pillwheel/              # Proyecto Arduino/PlatformIO
    ├── pillwheel.ino       # Sketch principal
    ├── config.h            # Configuración (WiFi, DEV_TOKEN, IP del backend)
    ├── hal.h               # Funciones de hardware (GPIO, motor, buzzer, LED, OLED)
    └── network.h           # HTTP client para reportar eventos al backend
```

## Contrato

El firmware recibe comandos del backend y reporta eventos:

### Endpoints que implementa (recibe del backend)

| Ruta | Método | Payload | Descripción |
| --- | --- | --- | --- |
| `/init` | POST | `{}` | Inicializar hardware |
| `/dispense` | POST | `{"slot_id": 1, "time": "08:00"}` | Activar motor del slot |
| `/ring` | POST | `{}` | Sonar buzzer |
| `/oled` | POST | `{"slot_id": 3, "name": "...", "time": "08:00"}` | Mostrar en OLED |
| `/led` | POST | `{"slot_id": 3, "on": true}` | Encender/apagar LED |
| `/status` | GET | — | Estado del dispositivo |

### Endpoints que reporta (hacia el backend)

| Ruta | Método | Payload | Descripción |
| --- | --- | --- |--- |
| `/events` | POST | `{"type": "slot_open", "slot_id": 3}` | Sensor detectó apertura |
| `/events` | POST | `{"type": "slot_closed", "slot_id": 3}` | Sensor detectó cierre |
| `/api/taken` | POST | `{"key": "YYYY-MM-DD_3_08:00", "value": true}` | Confirmar toma |

## Autenticación

Todos los comandos del backend llevan `Authorization: Bearer <DEV_TOKEN>`. El firmware valida este token antes de ejecutar cualquier acción.

## Hardware

- 8 slots con LED propio y sensor de movimiento (apertura/cierre)
- Buzzer para alarma
- Pantalla OLED para mostrar pastilla y hora
- Motor por slot para dispensar

Ver `docs/esp32-contract.md` para el contrato completo.
