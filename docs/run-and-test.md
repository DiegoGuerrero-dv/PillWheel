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

Credenciales de acceso (hardcodeadas en `Dev_server.py`):

- Password: `admin1234`
- Token (para llamadas por API): `dev-local-token`

## Probar manualmente (UI)

1. Entrar con `admin1234`.
2. Pestaña **Hoy**: debe mostrarse la próxima dosis del día (hero) y la lista de dosis. Tocar el botón ✓ de una dosis la marca como tomada (persiste en `taken_log.json`).
3. Pestaña **Casillas**: grid de 8 celdas. Tocar una celda abre el editor: nombre, color, días y horarios. Guardar persiste en `schedule.json`. "Vaciar casilla" limpia nombre y horarios.
4. Cerrar sesión con el botón ⏻ del topbar.

## Probar la API (smoke test)

En PowerShell, con el server corriendo:

```powershell
$base = "http://localhost:8000"

# Login correcto (esperado 200 + token)
curl.exe -s -X POST "$base/api/login" -H "Content-Type: application/json" -d '{"password":"admin1234"}'

# Login incorrecto (esperado 401)
curl.exe -s -X POST "$base/api/login" -H "Content-Type: application/json" -d '{"password":"mala"}'

# Schedule sin token (esperado 401)
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/schedule"

# Schedule con token (esperado 200)
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/schedule" -H "Authorization: Bearer dev-local-token"

# Estáticos (esperado 200)
curl.exe -s -o NUL -w "%{http_code}`n" "$base/"
curl.exe -s -o NUL -w "%{http_code}`n" "$base/index.html"
```

## Bypass conocido (problema de seguridad)

Sin autenticación, las siguientes rutas responden 200 y NO deberían:

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" "$base/schedule.json"   # 200 → fuga de datos
curl.exe -s -o NUL -w "%{http_code}`n" "$base/taken_log.json"  # 200 → fuga de datos
curl.exe -s -o NUL -w "%{http_code}`n" "$base/Dev_server.py"   # 200 → fuga de fuente
```

Hasta aplicar el fix de whitelist, cualquiera en la red puede leer los datos y el código fuente. Ver [architecture.md](architecture.md#problemas-conocidos).

## Solución de problemas

- **`Address already in use`:** otro proceso ocupa el puerto 8000. Encontrarlo con `Get-NetTCPConnection -LocalPort 8000 -State Listen` y cerrarlo, o cambiar `PORT = 8000` en `Dev_server.py`.
- **No carga desde otro dispositivo:** el servidor escucha en `0.0.0.0`, así que en la LAN se accede con la IP local (`ipconfig` → IPv4). Si no responde, Windows Firewall puede estar bloqueando python (aceptar el popup o agregar regla).
- **La página carga pero pide contraseña:** es el diseño; la contraseña es `admin1234`.
- **JSON corrupto:** `read_json` reinicia el archivo a su valor por defecto automáticamente, sin tumbar el server.

## Restablecer datos de prueba

Detener el server y borrar/regenerar los JSON (el server los recrea si faltan):

```powershell
Remove-Item schedule.json, taken_log.json -ErrorAction SilentlyContinue
python dev_server.py
```
