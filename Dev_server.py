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
- F2 (backend <-> dispositivo): device token (DEV_TOKEN) para el adapter
  del hardware (contrato H4/H6). /api/taken solo acepta reportes con ese
  token; el navegador ya no escribe claves arbitrarias (V9). El scheduler
  interno llama al driver (DevDriver) directamente y el driver
  auto-confirma la toma.

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

import base64
import hashlib
import json
import os
import re
import secrets
import struct
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol
from urllib.parse import parse_qs, urlparse

# Claves de días alineadas con Date.getDay() de JS y tm_wday de C (0 = Domingo).
# Python weekday(): Lun=0..Dom=6, por eso el scheduler usa (weekday() + 1) % 7.
DAY_KEYS = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']

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


# ---- HAL: DriverPort + DevDriver (H1–H6) ----

class DriverPort(Protocol):
    """Contrato H4: acciones que un dispositivo físico debe poder ejecutar.
    El timer vive en el backend (scheduler); el driver solo ejecuta y reporta."""

    def dispense(self, slot_id, time) -> bool:
        """Dispensa la casilla. True si el dispositivo aceptó la acción."""
        ...

    def ring(self) -> None:
        """Activa la alerta/sonido del dispositivo."""
        ...

    def status(self) -> dict:
        """Estado del dispositivo: conectado, último evento, errores."""
        ...

    def on_pill_taken(self, slot_id, time) -> None:
        """Evento de vuelta: el dispositivo reporta que la dosis fue tomada."""
        ...


class DevDriver:
    """Adaptador mock (H5/H6): simula GPIO del ESP32 (motor, buzzer, sensor)
    sin hardware. Al dispensar, auto-confirma la toma vía on_pill_taken."""

    def __init__(self, on_pill_taken):
        self._on_pill_taken = on_pill_taken
        self._events = []

    def dispense(self, slot_id, time) -> bool:
        self._events.append(('dispense', slot_id, time))
        # Simula el sensor: la pastilla salió y el dispositivo confirma la toma.
        self._on_pill_taken(slot_id, time)
        return True

    def ring(self) -> None:
        self._events.append(('ring', None, None))

    def status(self) -> dict:
        return {
            'driver': 'DevDriver (mock GPIO)',
            'ok': True,
            'last_events': self._events[-5:],
        }


# ---- WS hub mínimo RFC 6455 (stdlib) ----

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def _ws_frame_text(payload: bytes) -> bytes:
    """Frame de texto servidor→cliente (sin máscara): FIN=1, opcode 0x1."""
    n = len(payload)
    if n < 126:
        header = bytes([0x81, n])
    elif n < 65536:
        header = bytes([0x81, 126]) + struct.pack('>H', n)
    else:
        header = bytes([0x81, 127]) + struct.pack('>Q', n)
    return header + payload


class WSHub:
    """Hub simple: sockets conectados + broadcast de frames de texto."""

    def __init__(self):
        self._clients = set()
        self._lock = threading.Lock()

    def add(self, sock):
        with self._lock:
            self._clients.add(sock)

    def remove(self, sock):
        with self._lock:
            self._clients.discard(sock)

    def broadcast(self, payload: dict):
        frame = _ws_frame_text(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        with self._lock:
            socks = list(self._clients)
        for sock in socks:
            try:
                sock.sendall(frame)
            except OSError:
                self.remove(sock)


WS_HUB = WSHub()


def on_pill_taken(slot_id, time):
    """El adapter confirmó una toma: la registra en el log y la pushea por WS."""
    today = datetime.now().strftime('%Y-%m-%d')
    key = f'{today}_{slot_id}_{time}'
    entries = load_taken_log()
    entries = [e for e in entries if e.get('key') != key]
    record = {
        'key': key,
        'taken': True,
        'ts': datetime.now().isoformat(timespec='seconds'),
    }
    entries.append(record)
    save_taken_log(entries)
    WS_HUB.broadcast({'type': 'on_pill_taken', 'key': key, 'taken': True, 'ts': record['ts']})


DRIVER = DevDriver(on_pill_taken)


class Scheduler(threading.Thread):
    """Timer en el backend (spec hardware-driver): revisa el schedule y
    dispara dispense/ring cuando llega la hora de una dosis."""

    def __init__(self, driver, interval=20):
        super().__init__(daemon=True, name='scheduler')
        self.driver = driver
        self.interval = interval
        self._last_fired = set()

    def run(self):
        while True:
            now = datetime.now()
            day = DAY_KEYS[(now.weekday() + 1) % 7]
            hhmm = now.strftime('%H:%M')
            for slot in load_schedule():
                if not slot.get('name'):
                    continue
                times = slot.get('schedule', {}).get(day, [])
                if hhmm not in times:
                    continue
                # Dedupe por dosis (fecha + día + hora + casilla): dos slots
                # pueden tener la misma hora y ambos deben disparar.
                fired_key = f'{now.strftime("%Y-%m-%d")}_{day}_{hhmm}_{slot["id"]}'
                if fired_key in self._last_fired:
                    continue
                self._last_fired.add(fired_key)
                print(f'[scheduler] dispense slot {slot["id"]} {hhmm}')
                self.driver.dispense(slot['id'], hhmm)
            time.sleep(self.interval)


SCHED = Scheduler(DRIVER)


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

        if path == '/api/status':
            if not self._require_session():
                return
            return self._send_json(200, DRIVER.status())

        if path == '/ws':
            # WebSocket (RFC 6455 mínimo). El token de sesión va en la
            # query string: los navegadores no pueden fijar headers en WS.
            return self._handle_ws()

        if path in ('/schedule.json', '/taken_log.json', '/Dev_server.py'):
            # V1/V2: datos y fuente no se sirven sin sesión.
            if not self._require_session():
                return
            return super().do_GET()

        super().do_GET()  # index.html, style.css, script.js: públicos

    # ---- WebSocket (RFC 6455 mínimo, stdlib) ----

    def _handle_ws(self):
        params = parse_qs(urlparse(self.path).query)
        token = params.get('token', [''])[0]
        if not AUTH.valid(token):
            return self._send_json(401, {'error': 'no autorizado'})
        key = self.headers.get('Sec-WebSocket-Key', '')
        if not key:
            return self._send_json(400, {'error': 'falta Sec-WebSocket-Key'})
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.wfile.flush()
        self._ws_loop(self.connection)
        return

    def _ws_loop(self, sock):
        """Atiende pings/close de una conexión y la mantiene en el hub.
        El push de eventos lo hace WS_HUB.broadcast desde otros hilos."""
        WS_HUB.add(sock)
        try:
            while True:
                header = sock.recv(2)
                if len(header) < 2:
                    break
                opcode = header[0] & 0x0F
                masked = header[1] & 0x80
                length = header[1] & 0x7F
                if length == 126:
                    ext = sock.recv(2)
                    if len(ext) < 2:
                        break
                    length = struct.unpack('>H', ext)[0]
                elif length == 127:
                    ext = sock.recv(8)
                    if len(ext) < 8:
                        break
                    length = struct.unpack('>Q', ext)[0]
                if masked:
                    mask = sock.recv(4)
                    if len(mask) < 4:
                        break
                payload = sock.recv(length) if length else b''
                if opcode == 0x8:  # close
                    break
                if opcode == 0x9:  # ping -> pong
                    sock.sendall(bytes([0x8A, length]) + payload)
        except OSError:
            pass
        finally:
            WS_HUB.remove(sock)
            try:
                sock.close()
            except OSError:
                pass

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
            # V9: solo el adapter con device token F2 (config) reporta tomas.
            # El navegador ya no escribe claves arbitrarias en el log.
            if self._session_token() != DEV_TOKEN:
                return self._send_json(403, {'error': 'origen no verificado (F2)'})
            key = str(body.get('key', ''))
            value = body.get('value')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d+_\d{2}:\d{2}', key):
                return self._send_json(400, {'error': 'clave inválida'})
            if not isinstance(value, bool):
                return self._send_json(400, {'error': 'value debe ser booleano'})
            entries = load_taken_log()
            entries = [e for e in entries if e.get('key') != key]
            entries.append({
                'key': key,
                'taken': value,
                'ts': datetime.now().isoformat(timespec='seconds'),
            })
            save_taken_log(entries)
            WS_HUB.broadcast({'type': 'on_pill_taken', 'key': key, 'taken': value})
            return self._send_json(200, {'ok': True})

        self._send_json(404, {'error': 'no encontrado'})

    def log_message(self, fmt, *args):
        print('[dev_server]', *args)


if __name__ == '__main__':
    # V7: por defecto solo loopback; --host 0.0.0.0 expone en la LAN.
    _host = '127.0.0.1'
    if '--host' in sys.argv:
        _idx = sys.argv.index('--host')
        _host = sys.argv[_idx + 1] if _idx + 1 < len(sys.argv) else '0.0.0.0'

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

    print(f'Pastillero (modo desarrollo) -> http://localhost:{PORT}  (bind: {_host})')
    # HAL H4/H6: el scheduler corre en segundo plano y dispara DRIVER.dispense
    # cuando hay una dosis pendiente; DevDriver auto-confirma la toma.
    SCHED.start()
    ThreadingHTTPServer((_host, PORT), Handler).serve_forever()
