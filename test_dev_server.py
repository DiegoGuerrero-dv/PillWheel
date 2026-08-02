"""Tests de contrato para Dev_server.py — HAL (hal-contract).

Solo stdlib (unittest + http.client), sin dependencias externas, acorde al
proyecto. Cubren el contrato visible del cambio:
  - /api/driver/sim: auth (401), validación (400), secuencia open → close
  - DevDriver: close sin open NO confirma (C1), multi-dosis por slot (W2)
  - Scheduler: combo dispense → ring → oled_show → led_on + re-alarma

Correr con:
    python -m unittest test_dev_server -v
"""

import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock

import Dev_server as dev


class _Server(dev.ThreadingHTTPServer):
    daemon_threads = True


class HttpSimTests(unittest.TestCase):
    """Contrato HTTP de /api/driver/sim sobre el handler real."""

    @classmethod
    def setUpClass(cls):
        cls.server = _Server(('127.0.0.1', 0), dev.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        # Aisla el driver global: sin writes a taken_log.json y estado limpio.
        self._orig_on_pill_taken = dev.DRIVER._on_pill_taken
        self.confirmed = []
        dev.DRIVER._on_pill_taken = lambda slot_id, t: self.confirmed.append((slot_id, t))
        with dev.DRIVER._lock:
            dev.DRIVER._pending.clear()
            dev.DRIVER._opened.clear()
            dev.DRIVER._leds.clear()
            dev.DRIVER._events.clear()

    def tearDown(self):
        dev.DRIVER._on_pill_taken = self._orig_on_pill_taken

    # -- helpers ------------------------------------------------------------

    def _request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, payload, headers)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        parsed = json.loads(data) if data else {}
        return res.status, parsed

    def _login(self):
        status, data = self._request('POST', '/api/login',
                                     {'user': 'admin', 'password': 'admin1234'})
        self.assertEqual(status, 200)
        return data['token']

    # -- tests --------------------------------------------------------------

    def test_sim_requires_session(self):
        status, _ = self._request('POST', '/api/driver/sim', {'action': 'open', 'slot_id': 1})
        self.assertEqual(status, 401)

    def test_sim_invalid_action(self):
        token = self._login()
        status, data = self._request('POST', '/api/driver/sim',
                                     {'action': 'explode', 'slot_id': 1}, token)
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_sim_invalid_slot_id(self):
        token = self._login()
        for bad in (0, 9, '1', 1.5, True, None):
            status, data = self._request('POST', '/api/driver/sim',
                                         {'action': 'open', 'slot_id': bad}, token)
            self.assertEqual(status, 400, f'slot_id={bad!r} debía dar 400')

    def test_sim_non_dict_body(self):
        token = self._login()
        for bad_body in (None, [], 'x', 5):
            status, _ = self._request('POST', '/api/driver/sim', bad_body, token)
            self.assertEqual(status, 400, f'body={bad_body!r} debía dar 400')

    def test_open_does_not_confirm(self):
        token = self._login()
        with dev.DRIVER._lock:
            dev.DRIVER._pending[(1, '08:00')] = True
        status, data = self._request('POST', '/api/driver/sim',
                                     {'action': 'open', 'slot_id': 1}, token)
        self.assertEqual(status, 200)
        self.assertFalse(data['confirmed'])
        self.assertEqual(self.confirmed, [])

    def test_close_without_open_does_not_confirm(self):
        token = self._login()
        with dev.DRIVER._lock:
            dev.DRIVER._pending[(1, '08:00')] = True
        status, data = self._request('POST', '/api/driver/sim',
                                     {'action': 'close', 'slot_id': 1}, token)
        self.assertEqual(status, 200)
        self.assertFalse(data['confirmed'])
        self.assertEqual(self.confirmed, [])

    def test_open_close_sequence_confirms(self):
        token = self._login()
        with dev.DRIVER._lock:
            dev.DRIVER._pending[(1, '08:00')] = True
        self._request('POST', '/api/driver/sim', {'action': 'open', 'slot_id': 1}, token)
        status, data = self._request('POST', '/api/driver/sim', {'action': 'close', 'slot_id': 1}, token)
        self.assertEqual(status, 200)
        self.assertTrue(data['confirmed'])
        self.assertEqual(self.confirmed, [(1, '08:00')])
        with dev.DRIVER._lock:
            self.assertNotIn((1, '08:00'), dev.DRIVER._pending)
            self.assertFalse(dev.DRIVER._leds[1])

    def test_double_close_is_noop(self):
        token = self._login()
        with dev.DRIVER._lock:
            dev.DRIVER._pending[(1, '08:00')] = True
        self._request('POST', '/api/driver/sim', {'action': 'open', 'slot_id': 1}, token)
        _, first = self._request('POST', '/api/driver/sim', {'action': 'close', 'slot_id': 1}, token)
        _, second = self._request('POST', '/api/driver/sim', {'action': 'close', 'slot_id': 1}, token)
        self.assertTrue(first['confirmed'])
        self.assertFalse(second['confirmed'])
        self.assertEqual(self.confirmed, [(1, '08:00')])


class DevDriverTests(unittest.TestCase):
    """Máquina de estados del DevDriver (sin HTTP)."""

    def setUp(self):
        self.confirmed = []
        self.driver = dev.DevDriver(lambda slot_id, t: self.confirmed.append((slot_id, t)))

    def test_dispense_then_close_without_open_keeps_pending(self):
        self.driver.dispense(1, '08:00')
        self.assertFalse(self.driver.slot_closed(1))
        self.assertEqual(self.driver.pending_slots(), [1])
        self.assertEqual(self.confirmed, [])

    def test_multi_dose_per_slot_confirms_all_on_close(self):
        # W2: un slot con 2 horarios no pierde la primera dosis.
        self.driver.dispense(1, '08:00')
        self.driver.dispense(1, '16:00')
        self.driver.slot_open(1)
        self.assertTrue(self.driver.slot_closed(1))
        self.assertEqual(self.confirmed, [(1, '08:00'), (1, '16:00')])
        self.assertEqual(self.driver.pending_slots(), [])
        self.assertEqual(self.driver.status()['pending'], {})

    def test_status_exposes_state(self):
        self.driver.dispense(1, '08:00')
        st = self.driver.status()
        self.assertEqual(st['pending'], {'1': ['08:00']})
        self.assertEqual(st['leds'], {})
        # last_events: más reciente primero (spec) y con ts.
        self.assertEqual(st['last_events'][0]['action'], 'dispense')
        self.assertIn('ts', st['last_events'][0])


class SchedulerTests(unittest.TestCase):
    """Scheduler: combo HAL, re-alarma y cese al confirmar."""

    def setUp(self):
        self.confirmed = []
        self.driver = dev.DevDriver(lambda slot_id, t: self.confirmed.append((slot_id, t)))
        now = datetime.now()
        self.day = dev.DAY_KEYS[(now.weekday() + 1) % 7]
        self.hhmm = now.strftime('%H:%M')
        self.slot = {
            'id': 1, 'name': 'Test', 'color': '#ffffff',
            'enabled': {d: True for d in dev.DAY_KEYS},
            'schedule': {d: [] for d in dev.DAY_KEYS},
        }
        self.slot['schedule'][self.day] = [self.hhmm]
        self._orig_load = dev.load_schedule
        dev.load_schedule = lambda: [self.slot]

    def tearDown(self):
        dev.load_schedule = self._orig_load

    def _actions_since(self, start_index):
        with self.driver._lock:
            return [e['action'] for e in self.driver._events[start_index:]]

    def test_combo_order_and_realarm(self):
        sched = dev.Scheduler(self.driver, interval=0.15)
        sched.start()
        try:
            deadline = time.time() + 4
            while time.time() < deadline:
                with self.driver._lock:
                    if any(e['action'] == 'dispense' for e in self.driver._events):
                        break
                time.sleep(0.05)
            else:
                self.fail('el scheduler no disparó la dosis')
            with self.driver._lock:
                first = [e['action'] for e in self.driver._events[:5]]
            # combo en orden + re-alarma del mismo ciclo por pendiente.
            self.assertEqual(first, ['dispense', 'ring', 'oled_show', 'led_on', 'ring'])
            self.assertIn(1, self.driver.pending_slots())
        finally:
            sched.stop()

    def test_realarm_stops_after_confirm(self):
        sched = dev.Scheduler(self.driver, interval=0.15)
        sched.start()
        try:
            deadline = time.time() + 4
            rings_before = 0
            while time.time() < deadline:
                with self.driver._lock:
                    rings_before = sum(1 for e in self.driver._events if e['action'] == 'ring')
                if rings_before >= 2:
                    break
                time.sleep(0.05)
            # confirmar por sensor
            self.driver.slot_open(1)
            self.assertTrue(self.driver.slot_closed(1))
            self.assertEqual(self.confirmed, [(1, self.hhmm)])
            # esperar 2 ciclos sin pendientes: no deben aparecer más rings.
            rings_after = rings_before
            for _ in range(20):
                time.sleep(0.15)
                with self.driver._lock:
                    rings_after = sum(1 for e in self.driver._events if e['action'] == 'ring')
            self.assertEqual(rings_after, rings_before)
        finally:
            sched.stop()


class StorageTests(unittest.TestCase):
    """Contrato de persistencia JSON (W1): escritura atómica, recuperación
    y el camino on_pill_taken que usa IO_LOCK. Usa archivos temporales,
    nunca toca schedule.json / taken_log.json del proyecto."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(self.path)

    def _tmp_leftovers(self):
        d = os.path.dirname(self.path)
        base = os.path.basename(self.path)
        return [p for p in os.listdir(d) if p.startswith(base + '.') and p.endswith('.tmp')]

    def test_write_read_roundtrip(self):
        data = [{'id': 1, 'name': 'A'}]
        dev.write_json(self.path, data)
        self.assertEqual(dev.read_json(self.path, []), data)

    def test_no_tmp_left_after_write(self):
        dev.write_json(self.path, [1, 2, 3])
        self.assertEqual(self._tmp_leftovers(), [])

    def test_corrupt_json_resets_to_default(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{corrupto')
        self.assertEqual(dev.read_json(self.path, []), [])

    def test_on_pill_taken_persists_under_io_lock(self):
        orig = dev.LOG_PATH
        dev.LOG_PATH = self.path
        self.addCleanup(lambda: setattr(dev, 'LOG_PATH', orig))
        dev.on_pill_taken(1, '08:00')
        entries = dev.load_taken_log()
        self.assertTrue(
            any(e.get('key', '').endswith('_1_08:00') and e.get('taken') for e in entries)
        )
        self.assertEqual(self._tmp_leftovers(), [])

    def test_write_json_retries_then_succeeds(self):
        real_replace = os.replace
        calls = {'n': 0}

        def flaky(src, dst):
            calls['n'] += 1
            if calls['n'] == 1:
                raise PermissionError(13, 'simulado')
            return real_replace(src, dst)

        with mock.patch.object(dev.os, 'replace', side_effect=flaky):
            dev.write_json(self.path, [1])
        self.assertEqual(dev.read_json(self.path, []), [1])
        self.assertEqual(self._tmp_leftovers(), [])

    def test_write_json_raises_permission_error_after_retries(self):
        def always_fail(src, dst):
            raise PermissionError(13, 'simulado')

        with mock.patch.object(dev.os, 'replace', side_effect=always_fail):
            with self.assertRaises(PermissionError):
                dev.write_json(self.path, [1])
        self.assertEqual(self._tmp_leftovers(), [])

    def test_read_json_raises_on_persistent_permission_error(self):
        dev.write_json(self.path, [42])  # el archivo debe existir para llegar al open
        real_open = open

        def fake_open(path, *args, **kwargs):
            if str(path) == self.path:
                raise PermissionError(13, 'simulado')
            return real_open(path, *args, **kwargs)

        with mock.patch('builtins.open', side_effect=fake_open):
            # Un RMW no debe recibir default [] cuando la lectura falla:
            # eso lo convertiría en un sobrescritura destructiva.
            with self.assertRaises(PermissionError):
                dev.read_json(self.path, [])


if __name__ == '__main__':
    unittest.main()
