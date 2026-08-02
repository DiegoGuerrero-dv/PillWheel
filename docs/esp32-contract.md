# Contrato ESP32 — HAL (H4)

Documento de integración entre el backend (núcleo) y el firmware del dispositivo físico. Define, por cada función del puerto `DriverPort`, su comando de red equivalente, payload y autenticación.

## Sistema embebido

- **8 casillas (slots)**, cada una con **LED** propio y **sensor de movimiento** que detecta apertura/cierre del compartimiento.
- **Buzzer**: alarma cuando toca una dosis.
- **Pantalla OLED pequeña**: muestra la pastilla y la hora de la dosis del slot activo.
- El **timer vive en el backend** (scheduler); el firmware solo ejecuta y reporta.

## Autenticación (Frontera 2)

Todo comando del backend → firmware lleva:

```
Authorization: Bearer <DEV_TOKEN>
```

`DEV_TOKEN` es el device token de configuración (`.env`, Frontera 2). El token de sesión del navegador (F1) **no** se usa hacia el firmware.

## Mapeo DriverPort → firmware

| `DriverPort` (Python) | Comando firmware | Payload |
| --- | --- | --- |
| `init()` | `POST /init` | `{}` |
| `dispense(slot_id, time)` | `POST /dispense` | `{"slot_id": 1, "time": "08:00"}` |
| `ring()` | `POST /ring` | `{}` |
| `oled_show(slot_id, name, time)` | `POST /oled` | `{"slot_id": 3, "name": "Paracetamol", "time": "08:00"}` |
| `led_on(slot_id)` | `POST /led` | `{"slot_id": 3, "on": true}` |
| `led_off(slot_id)` | `POST /led` | `{"slot_id": 3, "on": false}` |
| `status()` | `GET /status` | — |
| `slot_open(slot_id)` | `POST /events` | `{"type": "slot_open", "slot_id": 3}` |
| `slot_closed(slot_id)` | `POST /events` | `{"type": "slot_closed", "slot_id": 3}` |
| `on_pill_taken(slot_id, time)` | `POST /api/taken` (backend) | `{"key": "YYYY-MM-DD_3_08:00", "value": true}` |

## Reglas del contrato

1. El firmware **no** conoce las rutas `/api/*` del backend salvo el reporte de tomas (`POST /api/taken`, que usa `DEV_TOKEN` y valida formato de `key`/`value`; V9).
2. El backend llama al firmware por los comandos de la tabla (`/init`, `/dispense`, `/ring`, `/oled`, `/led`, `GET /status`); el firmware **reporta** eventos de sensor por `POST /events` (nunca al revés).
3. `slot_open` y `slot_closed` se reportan como eventos (`POST /events`). La toma se confirma solo con la **secuencia apertura → cierre**: un cierre sin apertura previa se ignora (solo se loguea) para evitar dobles confirmaciones por rebote o replay. El cierre confirma **todas** las dosis pendientes del slot (el compartimiento se resuelve en una sola apertura).
4. Respuestas esperadas: `200 {"ok": true}` en comandos aceptados; `400` payload inválido; `401/403` sin `DEV_TOKEN` correcto.
5. El LED del slot queda encendido hasta que la dosis se confirma (`led_off`); mientras haya dosis pendientes el backend re-envía `ring()` en cada ciclo del scheduler (re-alarma).
6. En desarrollo (sin hardware), `DevDriver` simula todos estos efectos en consola con log `[hal] {ts} {action}({k=v,...}) -> {result}`, y la simulación del sensor se hace con `POST /api/driver/sim` (solo sesión F1, nunca hacia el firmware real).
