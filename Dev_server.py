"""
Pastillero - servidor local de desarrollo
------------------------------------------------------------------------
Sirve index.html/style.css/script.js y expone /api/login, /api/logout,
/api/schedule y /api/taken leyendo y escribiendo schedule.json /
taken_log.json en este mismo folder. Es una copia funcional de lo que
hará el ESP32 en LittleFS, así que la página no necesita ningún cambio
cuando pases del uno al otro.

Fronteras:
- F1 (browser <-> backend): token de sesión (en memoria). Login admin
  único con usuario + contraseña. Logout o reinicio invalidan el token.
- F2 (backend <-> dispositivo): device token reservado para el adapter
  del hardware (contrato H4). En esta fase no se usa aún en el handler.

Seguridad:
- /schedule.json, /taken_log.json y /Dev_server.py no se sirven sin
  sesión (V1/V2).
- Los slots se validan al guardar: sin horas vacías (V4), sin horas sin
  nombre (V5), ids numéricos y válidos en el upsert (V8).
- El log de tomas usa records {key, taken, ts} con retención de
  RETENTION_DAYS (6 meses por defecto) y purga automática.

Uso:
    python3 dev_server.py
    -> abre http://localhost:8000

No requiere librerías externas (solo la librería estándar de Python).
------------------------------------------------------------------------
"""

import json
import os
import secrets
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_PATH = os.path.join(DIR, 'schedule.json')
LOG_PATH = os.path.join(DIR, 'taken_log.json')

ENV_PATH = os.path.join(DIR, '.env')


def load_env_file(path=ENV_PATH):
    """Carga KEY=VALUE del archivo .env si existe. Solo stdlib.

    No pisa variables ya definidas en el entorno del proceso:
    prioridad = entorno del proceso > .env > defaults de desarrollo.
    """
    if not os.path.exists(path):
        return
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


load_env_file()

# Credenciales por configuración, no hardcodeadas en el fuente.
# Creá un .env a partir de .env.example para poner las tuyas.
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin1234')  # debe coincidir con ADMIN_PASSWORD en el .ino
DEV_TOKEN = os.environ.get('DEV_TOKEN', 'dev-local-token')  # F2: reservado para el adapter del dispositivo
PORT = int(os.environ.get('PORT', '8000'))
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '182'))


def read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read().strip()
    if not raw:
        # Archivo vacío (0 bytes) — pasa esto en vez de tronar, y lo
        # deja con datos válidos para la próxima vez.
        write_json(path, default)
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # JSON corrupto — mismo tratamiento: no tronar el servidor,
        # solo reiniciar ese archivo a su valor por defecto.
        write_json(path, default)
        return default


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- Auth F1 (sesión en memoria) ----

class AuthService:
    """Admin único. Tokens aleatorios en memoria: el reinicio invalida
    todas las sesiones (requisito de la spec user-auth)."""

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self._sessions = {}  # token -> timestamp

    def login(self, password, username=None):
        # Compatibilidad: si el cliente no manda usuario (UI vieja),
        # se asume el admin único. El happy path manda ambos.
        if username not in (None, '') and username != self.username:
            return None
        if password != self.password:
            return None
        token = secrets.token_hex(16)
        self._sessions[token] = time.time()
        return token

    def valid(self, token):
        return bool(token) and token in self._sessions

    def logout(self, token):
        self._sessions.pop(token, None)


AUTH = AuthService(ADMIN_USER, ADMIN_PASSWORD)


# ---- Storage ----

def load_schedule():
    return read_json(SCHEDULE_PATH, [])


def save_schedule(slots):
    write_json(SCHEDULE_PATH, slots)


def _ts_from_key(key):
    """Claves viejas tipo '2026-07-25_3_07:30' — la fecha va al inicio."""
    if isinstance(key, str) and len(key) >= 10:
        try:
            return datetime.strptime(key[:10], '%Y-%m-%d').isoformat()
        except ValueError:
            pass
    return datetime.now().isoformat(timespec='seconds')


def load_taken_log():
    """Devuelve records {key, taken, ts}. Migra el formato viejo
    (dict {key: bool}) a lista de records sin perder datos."""
    data = read_json(LOG_PATH, [])
    if isinstance(data, dict):
        data = [
            {'key': str(k), 'taken': v, 'ts': _ts_from_key(str(k))}
            for k, v in data.items()
        ]
        write_json(LOG_PATH, data)
    if not isinstance(data, list):
        data = []
    return data


def purge_taken_log(entries):
    """Purga entradas más viejas que RETENTION_DAYS. Sin fecha legible:
    se conserva (no borrar lo que no se puede fechar)."""
    if RETENTION_DAYS <= 0:
        return entries
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    kept = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry.get('ts', ''))
        except (ValueError, AttributeError):
            kept.append(entry)
            continue
        if ts >= cutoff:
            kept.append(entry)
    return kept


def save_taken_log(entries):
    # Cada write purga (spec data-retention).
    write_json(LOG_PATH, purge_taken_log(entries))


# ---- Validación de slots (V4/V5/V8) ----

def validate_slot(slot):
    """Devuelve (ok, error). Un slot sin horarios en ningún día es
    inerte y se permite aunque no tenga nombre (placeholder)."""
    if not isinstance(slot, dict):
        return False, 'slot inválido: debe ser un objeto'
    try:
        slot_id = int(slot.get('id'))
    except (TypeError, ValueError):
        return False, 'slot inválido: id requerido y numérico'
    if slot_id < 1 or slot_id > 8:
        return False, 'slot inválido: id debe estar entre 1 y 8 (V8)'
    schedule = slot.get('schedule')
    if not isinstance(schedule, dict):
        return False, 'slot inválido: schedule requerido'
    has_time = False
    for day, times in schedule.items():
        if not isinstance(times, list):
            return False, 'slot inválido: horarios de {} deben ser una lista'.format(day)
        for t in times:
            if not isinstance(t, str) or not t.strip():
                return False, 'slot inválido: hora vacía en {} (V4)'.format(day)
            has_time = True
    name = str(slot.get('name') or '').strip()
    if has_time and not name:
        return False, 'slot inválido: hora sin nombre (V5)'
    return True, None


# ---- HTTP Handler ----

class Handler(SimpleHTTPRequestHandler):

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session_token(self):
        header = self.headers.get('Authorization', '')
        if header.startswith('Bearer '):
            return header[7:].strip()
        return ''

    def _require_session(self):
        if not AUTH.valid(self._session_token()):
            self._send_json(401, {'error': 'no autorizado'})
            return False
        return True

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(length) if length else b''
        return json.loads(raw) if raw else {}

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/api/schedule':
            if not self._require_session():
                return
            return self._send_json(200, load_schedule())

        if path == '/api/taken':
            if not self._require_session():
                return
            return self._send_json(200, load_taken_log())

        if path in ('/schedule.json', '/taken_log.json', '/Dev_server.py'):
            # V1/V2: datos y fuente no se sirven sin sesión.
            if not self._require_session():
                return
            return super().do_GET()

        super().do_GET()  # index.html, style.css, script.js: públicos

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_body()
        except json.JSONDecodeError:
            return self._send_json(400, {'error': 'json inválido'})

        if path == '/api/login':
            token = AUTH.login(body.get('password'), username=body.get('user'))
            if token is None:
                return self._send_json(401, {'ok': False, 'error': 'Credenciales incorrectas'})
            return self._send_json(200, {'ok': True, 'token': token})

        if path == '/api/logout':
            if not self._require_session():
                return
            AUTH.logout(self._session_token())
            return self._send_json(200, {'ok': True})

        if path == '/api/schedule':
            if not self._require_session():
                return
            ok, error = validate_slot(body)
            if not ok:
                return self._send_json(400, {'error': error})
            slots = load_schedule()
            slot_id = str(int(body.get('id')))
            idx = next((i for i, s in enumerate(slots) if str(s.get('id')) == slot_id), None)
            if idx is None:
                slots.append(body)  # insert válido (V8)
            else:
                slots[idx] = body   # update
            save_schedule(slots)
            return self._send_json(200, {'ok': True})

        if path == '/api/taken':
            # PR 1: requiere sesión. El origen del adapter (F2, V9) llega
            # en PR 2 con el contrato del driver.
            if not self._require_session():
                return
            entries = load_taken_log()
            entries.append({
                'key': str(body.get('key', '')),
                'taken': body.get('value', False),
                'ts': datetime.now().isoformat(timespec='seconds'),
            })
            save_taken_log(entries)
            return self._send_json(200, {'ok': True})

        self._send_json(404, {'error': 'no encontrado'})

    def log_message(self, fmt, *args):
        print('[dev_server]', *args)


if __name__ == '__main__':
    os.chdir(DIR)
    if not os.path.exists(SCHEDULE_PATH):
        write_json(SCHEDULE_PATH, [])
    if not os.path.exists(LOG_PATH):
        write_json(LOG_PATH, [])
    else:
        # Migración + purga al arranque (tasks 2.1/2.2).
        save_taken_log(load_taken_log())

    if ADMIN_PASSWORD == 'admin1234' and DEV_TOKEN == 'dev-local-token':
        print('[dev_server] AVISO: credenciales activas = defaults de desarrollo (admin/admin1234 / dev-local-token).')
        print('[dev_server] Para credenciales propias, creá un .env a partir de .env.example.')

    print(f'Pastillero (modo desarrollo) -> http://localhost:{PORT}')
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
