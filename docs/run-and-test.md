# Cómo correr y probar PillWheel

## Requisitos

- Python 3 (probado con 3.14; solo usa la librería estándar)
- Navegador (Chrome/Firefox/Edge)

## Correr el servidor

```powershell
cd C:\Users\blade\OneDrive\Documentos\acts\PillWheel
python dev_server.py
```

Luego abrir **http://localhost:8000** en el navegador.

Credenciales de acceso (desde tu `.env`, ver `.env.example`):

- Usuario: `ADMIN_USER` (default dev: `admin`)
- Password: `ADMIN_PASSWORD` (default dev: `admin1234`)
- Token de dispositivo (F2, para reportar tomas por API): `DEV_TOKEN` (default dev: `dev-local-token`)

Si no existe `.env`, se usan los defaults de desarrollo con un aviso en consola. Cada persona del repo puede poner sus propias credenciales en su `.env` (no se commitea).

El servidor escucha en `127.0.0.1` por defecto. Para exponerlo en la LAN: `python dev_server.py --host 0.0.0.0`.

## Probar manualmente (UI)

1. Entrar con `admin` / `admin1234`.
2. Pestaña **Hoy**: hero con la próxima dosis y lista de dosis de hoy. El ✓ de una dosis se marca cuando el driver confirma la toma por sensor (`slot_open` + `slot_closed`, o su simulación con el modal / `POST /api/driver/sim`); el navegador ya no escribe en el log (ver seguridad V9).
3. Pestaña **Casillas**: grid de 8 celdas. Tocar una celda abre el editor: nombre, color, días y horarios. Guardar persiste en `schedule.json`. "Vaciar casilla" limpia nombre y horarios.
4. Cerrar sesión con el botón ⏻ del topbar (invalida el token en el servidor).

## Probar la API (smoke test)

En PowerShell, con el server corriendo:

```powershell
$base = "http://localhost:8000"
$session = ""

# Login correcto con usuario (esperado 200 + token; guardarlo en $session)
$login = curl.exe -s -X POST "$base/api/login" -H "Content-Type: application/json" -d '{"user":"admin","password":"admin1234"}'
$login
$session = ($login | ConvertFrom-Json).token

# Login incorrecto (esperado 401)
curl.exe -s -X POST "$base/api/login" -H "Content-Type: application/json" -d '{"user":"admin","password":"mala"}'

# Sin token -> 401
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/schedule"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/schedule.json"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/taken_log.json"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/Dev_server.py"

# Con sesión -> 200
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/schedule" -H "Authorization: Bearer $session"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/taken" -H "Authorization: Bearer $session"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/status" -H "Authorization: Bearer $session"

# Estáticos (esperado 200 sin auth)
curl.exe -s -o NUL -w "%{http_code}`n" "$base/"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/index.html"

# POST /api/taken (V9): solo device token F2
# Con token de sesión -> 403
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "$base/api/taken" -H "Authorization: Bearer $session" -H "Content-Type: application/json" -d '{"key":"2026-08-01_1_08:00","value":true}'
# Con device token + clave válida -> 200
curl.exe -s -X POST "$base/api/taken" -H "Authorization: Bearer dev-local-token" -H "Content-Type: application/json" -d '{"key":"2026-08-01_1_08:00","value":true}'
# Con device token + clave malformada -> 400
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "$base/api/taken" -H "Authorization: Bearer dev-local-token" -H "Content-Type: application/json" -d '{"key":"clave-rara","value":true}'

# Logout (invalida el token; el mismo token debe dar 401 después)
curl.exe -s -X POST "$base/api/logout" -H "Authorization: Bearer $session"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/schedule" -H "Authorization: Bearer $session"
```

## WebSocket (push de tomas)

Con el server corriendo y una sesión válida, abrir DevTools del navegador o un cliente WS:

```
ws://localhost:8000/ws?token=<token de sesión>
```

Cuando el scheduler dispara una dosis (o se reporta `POST /api/taken` con el device token), el servidor pushea:

```json
{"type": "on_pill_taken", "key": "2026-08-01_1_08:00", "taken": true}
```

El dashboard se actualiza solo.

## Scheduler / HAL (mock)

- El scheduler revisa `schedule.json` cada 20 s. Cuando llega la hora de una dosis dispara el **combo HAL**: `dispense` → `ring` (buzzer) → `oled_show` (OLED) → `led_on` (LED del slot).
- La dosis queda **pendiente** (Decisión B: el DevDriver NO auto-confirma). Mientras haya pendientes, el scheduler re-envía `ring()` cada ciclo (**re-alarma**) y el LED sigue encendido.
- La toma se confirma con la secuencia del sensor: `slot_open` + `slot_closed` (en el cierre: `led_off` + `on_pill_taken` → escribe `taken_log.json` y pushea por WS). Sin hardware, se simula con el botón del modal o `POST /api/driver/sim`.
- Para probar el flujo sin esperar la hora real, agregar al slot 1 el horario del minuto actual en el día de hoy y esperar ≤20 s.
- `GET /api/status` (con sesión) muestra el estado del driver: LEDs, pendientes, OLED y últimos eventos `[hal]` con timestamp.

### Modal de dosis pendiente

- Cuando la hora de una dosis ya llegó y no está tomada, la UI muestra el modal (casilla, hora, nombre, botón **"Abrir y tomar"**).
- Persiste ante recarga: si la dosis sigue sin confirmar (no está en `taken_log.json`), el modal vuelve a aparecer.
- "Abrir y tomar" simula el sensor: `open` + `close` → confirma la dosis, cierra el modal y tacha la dosis en el dashboard (via WS).

### Smoke test HAL (checklist)

- [ ] Al arrancar el server aparece en consola `[hal] {ts} init() -> None`.
- [ ] Al dispararse una dosis (horario del minuto actual), la consola muestra `dispense`, `ring`, `oled_show` y `led_on` en ese orden, con timestamp.
- [ ] `GET /api/status` (con sesión) refleja `leds`, `pending` y `oled`.
- [ ] Mientras la dosis no se confirma, `ring` se repite en los ciclos siguientes (re-alarma).
- [ ] `POST /api/driver/sim` con `{"action":"open","slot_id":N}` y luego `{"action":"close","slot_id":N}` (con sesión) → `200` con `"confirmed": true`, consola muestra `slot_open` y `slot_closed` + `led_off`, y la dosis queda marcada tomada (el `on_pill_taken` no imprime en consola: escribe `taken_log.json` y pushea por WS).
- [ ] `POST /api/driver/sim` con `{"action":"explode","slot_id":1}` → `400`; con `{"action":"open","slot_id":9}` → `400`; sin sesión → `401`.
- [ ] La dosis confirmada deja de re-alarmar (no aparece más `ring` en el ciclo siguiente).
- [ ] Modal: aparece al llegar la hora; persiste al recargar si no se tomó; "Abrir y tomar" lo cierra y tacha la dosis.

## Day toggle (días activos/desactivados)

Checklist manual (editor → pestaña Casillas → tocar una casilla):

- [ ] Tocar un día **seleccionado** lo deselecciona: el chip se ve apagado, el panel muestra "Seleccioná un día" y las horas de ese día **no se borran**.
- [ ] `schedule.json` conserva las horas del día desactivado y agrega `"enabled": {..., "día": false}` al slot.
- [ ] Tocar un día **desactivado** lo reactiva y muestra sus horas guardadas.
- [ ] Tocar un día **sin horas** copia las horas del día visible (comportamiento existente).
- [ ] En el dashboard "Hoy", si el día actual está desactivado, las dosis de ese slot no aparecen como pendientes.
- [ ] "Vaciar casilla" limpia nombre, horarios y deja todos los días activos (`enabled` completo en `true`).
- [ ] Los slots viejos **sin** `enabled` siguen funcionando (todos los días activos).

## Solución de problemas

- **`Address already in use`:** otro proceso ocupa el puerto 8000. Encontrarlo con `Get-NetTCPConnection -LocalPort 8000 -State Listen` y cerrarlo, o cambiar `PORT` en `.env`.
- **No carga desde otro dispositivo:** si arrancaste con `--host 0.0.0.0`, en la LAN se accede con la IP local (`ipconfig` → IPv4). Si no responde, Windows Firewall puede estar bloqueando python (aceptar el popup o agregar regla).
- **La página carga pero pide credenciales:** es el diseño; usuario `admin` y password del `.env` (default dev `admin1234`).
- **JSON corrupto:** `read_json` reinicia el archivo a su valor por defecto automáticamente, sin tumbar el server.
- **401 al reportar tomas desde la app:** `POST /api/taken` requiere el `DEV_TOKEN` (F2), no el token de sesión del navegador. Es el comportamiento esperado (V9).

## Restablecer datos de prueba

Detener el server y borrar/regenerar los JSON (el server los recrea si faltan):

```powershell
Remove-Item schedule.json, taken_log.json -ErrorAction SilentlyContinue
python dev_server.py
```
