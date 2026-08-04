# adapters/

Adaptadores del puerto `DriverPort`. Cada adaptador implementa el contrato del hardware para un dispositivo específico.

## Adaptadores

| Archivo | Dispositivo | Estado |
| --- | --- | --- |
| `esp32_driver.py` | ESP32 físico (HTTP) | 🔲 Pendiente |

## Convención

Cada adaptador es una clase que cumple `DriverPort` (definido en `Dev_server.py`). El adaptador se instancia al arrancar el backend y el scheduler lo usa a través del puerto.

```python
# Ejemplo de uso (en Dev_server.py):
from adapters.esp32_driver import Esp32Driver

DRIVER = Esp32Driver(on_pill_taken, esp32_ip="192.168.1.100")
```

Ver `docs/esp32-contract.md` para el contrato de integración.
