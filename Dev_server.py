"""
Pastillero - servidor local de desarrollo
------------------------------------------------------------------------
Sirve index.html/style.css/script.js y expone /api/login, /api/schedule
y /api/taken leyendo y escribiendo schedule.json / taken_log.json en este
mismo folder. Es una copia funcional de lo que hará el ESP32 en LittleFS,
así que la página no necesita ningún cambio cuando pases del uno al otro.

Uso:
    python3 dev_server.py
    -> abre http://localhost:8000

No requiere librerías externas (solo la librería estándar de Python).
------------------------------------------------------------------------
"""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_PATH = os.path.join(DIR, 'schedule.json')
LOG_PATH = os.path.join(DIR, 'taken_log.json')

ADMIN_PASSWORD = 'admin1234'   # debe coincidir con ADMIN_PASSWORD en el .ino
DEV_TOKEN = 'dev-local-token'
PORT = 8000


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


class Handler(SimpleHTTPRequestHandler):

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return self.headers.get('Authorization', '') == f'Bearer {DEV_TOKEN}'

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        raw = self.rfile.read(length) if length else b''
        return json.loads(raw) if raw else {}

    # ---- GET ----
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/api/schedule':
            if not self._authorized():
                return self._send_json(401, {'error': 'no autorizado'})
            return self._send_json(200, read_json(SCHEDULE_PATH, []))

        if path == '/api/taken':
            if not self._authorized():
                return self._send_json(401, {'error': 'no autorizado'})
            return self._send_json(200, read_json(LOG_PATH, {}))

        super().do_GET()  # sirve index.html, style.css, script.js normalmente

    # ---- POST ----
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_body()
        except json.JSONDecodeError:
            return self._send_json(400, {'error': 'json inválido'})

        if path == '/api/login':
            if body.get('password') == ADMIN_PASSWORD:
                return self._send_json(200, {'ok': True, 'token': DEV_TOKEN})
            return self._send_json(401, {'ok': False, 'error': 'Contraseña incorrecta'})

        if path == '/api/schedule':
            if not self._authorized():
                return self._send_json(401, {'error': 'no autorizado'})
            slots = read_json(SCHEDULE_PATH, [])
            for i, slot in enumerate(slots):
                if slot.get('id') == body.get('id'):
                    slots[i] = body
                    break
            write_json(SCHEDULE_PATH, slots)
            return self._send_json(200, {'ok': True})

        if path == '/api/taken':
            if not self._authorized():
                return self._send_json(401, {'error': 'no autorizado'})
            log = read_json(LOG_PATH, {})
            log[body.get('key')] = body.get('value', False)
            write_json(LOG_PATH, log)
            return self._send_json(200, {'ok': True})

        self._send_json(404, {'error': 'no encontrado'})

    def log_message(self, fmt, *args):
        print('[dev_server]', *args)


if __name__ == '__main__':
    os.chdir(DIR)
    if not os.path.exists(SCHEDULE_PATH):
        write_json(SCHEDULE_PATH, [])
    if not os.path.exists(LOG_PATH):
        write_json(LOG_PATH, {})

    print(f'Pastillero (modo desarrollo) -> http://localhost:{PORT}')
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()