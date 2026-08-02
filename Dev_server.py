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
  interno llama al driver (DevDriver) directamente; el driver NO
  auto-confirma la toma: la dosis se marca tomada solo con la secuencia
  de sensor slot_open → slot_closed (o su simulación /api/driver/sim).

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
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
    except PermissionError:
        # Windows/OneDrive: el archivo puede estar siendo reemplazado por
        # un writer concurrente (W1); reintento corto antes de rendirse.
        time.sleep(0.05)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = f.read().strip()
        except PermissionError:
            # Lectura fallida de forma persistente: levantar en vez de
            # devolver default, para que un RMW no sobrescriba todo el
            # archivo con un solo elemento en silencio.
            raise
    if not raw:
        # Archivo vacío (0 bytes) — pasa esto en vez de tronar, y lo
        # deja con datos válidos para la próxima vez. El write queda
        # bajo IO_LOCK para no pisar un save concurrente.
        with IO_LOCK:
            write_json(path, default)
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # JSON corrupto — mismo tratamiento: no tronar el servidor,
        # solo reiniciar ese archivo a su valor por defecto.
        with IO_LOCK:
            write_json(path, default)
        return default


def write_json(path, data):
    # Escritura atómica (W1): volcar a un temporal y reemplazar con
    # os.replace. El scheduler lee schedule.json cada 20 s y hay writes
    # concurrentes de taken_log bajo ThreadingHTTPServer; sin esto, un
    # lector en la ventana truncar->dump veía JSON corrupto y podía
    # resetear el archivo a [] en silencio.
    #
    # Windows/NTFS + OneDrive: os.replace y open() pueden fallar con
    # PermissionError si otro hilo tiene el archivo abierto (Python no
    # pide FILE_SHARE_DELETE), por eso hay reintentos cortos. El tmp es
    # único por proceso/hilo para que dos escritores concurrentes no
    # compartan el mismo archivo temporal.
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        last_err = None
        for attempt in range(4):
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.05 * (attempt + 1))
        # Agotó reintentos: fallar con la señal original (PermissionError),
        # no con un RuntimeError sin excepción activa.
        raise last_err
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# Serializa el read-modify-write de taken_log.json/schedule.json entre
# hilos (on_pill_taken, POST /api/taken, POST /api/schedule y writes de
# recuperación bajo ThreadingHTTPServer): evita lost updates (W1).
# RLock permite reentrada cuando read_json/load_taken_log escriben
# (recuperación/migración) mientras el caller ya tiene el lock.
IO_LOCK = threading.RLock()


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
        # Migración serializada (W1): no pisar un RMW concurrente.
        with IO_LOCK:
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
    enabled = slot.get('enabled')
    if enabled is not None:
        if not isinstance(enabled, dict):
            return False, 'slot inválido: enabled debe ser un objeto'
        for day, val in enabled.items():
            if day not in DAY_KEYS:
                return False, 'slot inválido: día desconocido en enabled ({})'.format(day)
            if not isinstance(val, bool):
                return False, 'slot inválido: enabled[{}] debe ser booleano'.format(day)
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
        """Activa la alerta/sonido del dispositivo (buzzer)."""
        ...

    def status(self) -> dict:
        """Estado del dispositivo: conectado, último evento, errores."""
        ...

    def on_pill_taken(self, slot_id, time) -> None:
        """Evento de vuelta: el dispositivo reporta que la dosis fue tomada."""
        ...

    def init(self) -> None:
        """Inicializa el driver al arrancar el sistema."""
        ...

    def oled_show(self, slot_id, name, time) -> None:
        """Muestra en la pantalla OLED la pastilla y hora del slot indicado."""
        ...

    def led_on(self, slot_id) -> None:
        """Enciende el LED del slot indicado (toca tomar la dosis)."""
        ...

    def led_off(self, slot_id) -> None:
        """Apaga el LED del slot indicado (toma confirmada)."""
        ...

    def slot_open(self, slot_id) -> None:
        """Evento del sensor: el usuario abrió el compartimiento del slot."""
        ...

    def slot_closed(self, slot_id) -> bool:
        """Evento del sensor: el usuario cerró el compartimiento del slot.
        True si el cierre confirmó una o más dosis pendientes del slot."""
        ...


class DevDriver:
    """Adaptador mock (H5/H6): simula GPIO del ESP32 (motor, buzzer, sensor,
    LED por slot, OLED) sin hardware. NO auto-confirma la toma: la confirmación
    ocurre solo cuando el sensor reporta apertura + cierre (slot_open/slot_closed)
    o su simulación local (/api/driver/sim)."""

    def __init__(self, on_pill_taken):
        self._on_pill_taken = on_pill_taken
        self._events = []
        self._leds = {}      # slot_id -> bool
        self._pending = {}   # (slot_id, time) -> True (dosis esperando confirmación)
        self._opened = set() # slots con apertura reportada (secuencia open → close)
        self._oled = None    # último texto mostrado
        self._lock = threading.Lock()  # estado compartido entre scheduler y handler

    def _log(self, action, result=None, **kw):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        args = ', '.join(f'{k}={v}' for k, v in kw.items())
        print(f'[hal] {ts} {action}({args}) -> {result}')
        with self._lock:
            self._events.append({'action': action, 'ts': ts, 'kw': kw})

    def init(self) -> None:
        self._log('init')

    def dispense(self, slot_id, time) -> bool:
        self._log('dispense', True, slot_id=slot_id, time=time)
        # La dosis queda pendiente: el LED enciende y se espera el sensor.
        # Clave (slot_id, time): un slot con varias dosis al día no se pisa.
        with self._lock:
            self._pending[(slot_id, time)] = True
        return True

    def ring(self) -> None:
        self._log('ring')

    def oled_show(self, slot_id, name, time) -> None:
        self._log('oled_show', None, slot_id=slot_id, name=name, time=time)
        with self._lock:
            self._oled = f'{name} {time}'

    def led_on(self, slot_id) -> None:
        self._log('led_on', None, slot_id=slot_id)
        with self._lock:
            self._leds[slot_id] = True

    def led_off(self, slot_id) -> None:
        self._log('led_off', None, slot_id=slot_id)
        with self._lock:
            self._leds[slot_id] = False

    def slot_open(self, slot_id) -> None:
        with self._lock:
            self._opened.add(slot_id)
        self._log('slot_open', None, slot_id=slot_id)

    def slot_closed(self, slot_id) -> bool:
        confirmed = False
        times = []
        with self._lock:
            # Solo confirma si hubo apertura previa (secuencia open → close).
            # Un cierre sin apertura (glitch, rebote, replay) NO confirma.
            if slot_id in self._opened:
                times = [t for (s, t) in self._pending if s == slot_id]
                for t in times:
                    del self._pending[(slot_id, t)]
                self._opened.discard(slot_id)
                if times:
                    self._leds[slot_id] = False
                    confirmed = True
        self._log('slot_closed', confirmed, slot_id=slot_id)
        # on_pill_taken fuera del lock (escribe log + pushea WS).
        for t in times:
            self._on_pill_taken(slot_id, t)
        return confirmed

    def pending_slots(self):
        with self._lock:
            return list({s for (s, t) in self._pending})

    def status(self) -> dict:
        with self._lock:
            pending = {}
            for (s, t) in self._pending:
                pending.setdefault(str(s), []).append(t)
            return {
                'driver': 'DevDriver (mock GPIO)',
                'ok': True,
                'leds': dict(self._leds),
                'pending': {k: sorted(v) for k, v in pending.items()},
                'oled': self._oled,
                'last_events': self._events[-5:][::-1],  # más reciente primero
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
    record = {
        'key': key,
        'taken': True,
        'ts': datetime.now().isoformat(timespec='seconds'),
    }
    with IO_LOCK:
        entries = load_taken_log()
        entries = [e for e in entries if e.get('key') != key]
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
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            # Poda: el dedupe solo importa para hoy; descartar días viejos.
            self._last_fired = {k for k in self._last_fired if k.startswith(today)}
            day = DAY_KEYS[(now.weekday() + 1) % 7]
            hhmm = now.strftime('%H:%M')
            try:
                slots = load_schedule()
            except OSError:
                # Lectura fallida (p.ej. PermissionError por OneDrive):
                # no matar el thread; se reintenta el próximo ciclo.
                slots = []
            for slot in slots:
                if not slot.get('name'):
                    continue
                if slot.get('enabled', {}).get(day, True) is False:
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
                print(f'[scheduler] dosis {slot["id"]} {hhmm}')
                # Combo HAL: dispensar, alarma (buzzer), OLED y LED del slot.
                self.driver.dispense(slot['id'], hhmm)
                self.driver.ring()
                self.driver.oled_show(slot['id'], slot.get('name', ''), hhmm)
                self.driver.led_on(slot['id'])
            # Re-alarma: mientras haya dosis pendientes, el buzzer sigue sonando.
            if self.driver.pending_slots():
                self.driver.ring()
            self._stop.wait(self.interval)


SCHED = Scheduler(DRIVER)


# ---- HTTP Handler ----

class Handler(SimpleHTTPRequestHandler):

    def end_headers(self):
        # Dev: sin caché para que los cambios de CSS/JS se vean al instante.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

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
            # RMW serializado: dos saves concurrentes de schedule.json no
            # se pisan entre sí (W1).
            with IO_LOCK:
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
            with IO_LOCK:
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

        if path == '/api/driver/sim':
            # Simulación local del sensor (solo DevDriver): el firmware real
            # reporta slot_open/slot_closed como eventos F2, no por aquí.
            if not self._require_session():
                return
            if not isinstance(body, dict):
                return self._send_json(400, {'error': 'json inválido'})
            action = body.get('action')
            slot_id = body.get('slot_id')
            if action not in ('open', 'close'):
                return self._send_json(400, {'error': 'acción inválida (open|close)'})
            if not isinstance(slot_id, int) or isinstance(slot_id, bool) or not 1 <= slot_id <= 8:
                return self._send_json(400, {'error': 'slot_id inválido'})
            if action == 'open':
                DRIVER.slot_open(slot_id)
                # Abrir no confirma; el cierre es el que confirma.
                return self._send_json(200, {'ok': True, 'confirmed': False})
            confirmed = DRIVER.slot_closed(slot_id)
            return self._send_json(200, {'ok': True, 'confirmed': confirmed})

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
    # HAL H4/H6: el driver registra su arranque y el scheduler corre en segundo
    # plano; cuando hay una dosis pendiente dispara dispense/ring/oled/led y la
    # toma se confirma solo con el sensor (o su simulación).
    DRIVER.init()
    SCHED.start()
    ThreadingHTTPServer((_host, PORT), Handler).serve_forever()
