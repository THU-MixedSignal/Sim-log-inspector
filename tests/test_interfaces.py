"""CLI and HTTP contracts: UTF-8 JSON, JSON errors, read-only access, loopback-only hosts."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from simcheck.server import CSP, make_server
from simcheck.store import connect, scan

ROOT = Path(__file__).resolve().parents[1]
FOOT = 'spectre completes with 0 errors, 1 warnings, and 0 notices.\n'
LOG = ("Warning from spectre at time = 2 ns during transient analysis `tran'.\n"
       '    WARNING (X-1): R1: <script>alert(1)</script> Vds(=1 µV) ✓\n'
       'R4MEAS,0,23,8,8,8,16,23,1\nR4MEAS,1,24,8,8,8,16,24,1\nR4MEAS,2,25,8,8,8,16,25,1\n')


def cli(*args, timeout=60):
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8')}
    done = subprocess.run([sys.executable, '-m', 'simcheck', *args], cwd=ROOT, env=env,
                          capture_output=True, timeout=timeout)
    return done.returncode, done.stdout.decode('utf-8')  # strict: must be UTF-8


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        (self.p / 'spectre.out').write_text(LOG + FOOT, encoding='utf-8')
        (self.p / 'm.json').write_text('{"runs":[{"id":"t","log":"spectre.out"}]}', encoding='utf-8')
        self.db = str(self.p / 'db.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def test_utf8_json_even_for_text_outside_the_console_code_page(self):
        code, out = cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['runs'][0]['state']['status'], 'complete')
        code, out = cli('--db', self.db, 'problems', '--run', 't')
        group = json.loads(out)['problems'][0]
        self.assertIn('µV', group['message'])
        code, out = cli('--db', self.db, 'evidence', str(group['first_evidence_id']))
        self.assertEqual(code, 0)
        item = json.loads(out)['evidence']
        self.assertIn('✓', item['raw'])
        self.assertIn('at time = 2 ns', item['header']['raw'])
        code, out = cli('--db', self.db, 'measurements', '--run', 't', '--tail', '2')
        self.assertEqual([m['frame'] for m in json.loads(out)['measurements']], [1, 2])
        code, out = cli('--db', self.db, 'report')
        self.assertEqual(code, 0)
        self.assertIn('# Spectre 证据报告', out)

    def test_errors_are_json_and_reads_never_create_a_database(self):
        missing = str(self.p / 'missing.sqlite')
        code, out = cli('--db', missing, 'status')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'FileNotFoundError'))
        self.assertFalse(Path(missing).exists())
        cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        code, out = cli('--db', self.db, 'evidence', '999999')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'LookupError'))
        old = self.p / 'old.sqlite'
        with sqlite3.connect(old) as raw:
            raw.execute('CREATE TABLE runs(id TEXT)')
        raw.close()
        code, out = cli('--db', str(old), 'status')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'SchemaError'))

    def test_wait_without_a_live_collector(self):
        cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        code, out = cli('--db', self.db, 'wait', '--timeout', '1')
        self.assertEqual((code, json.loads(out)['reason']), (4, 'collector_offline'))

    def test_run_fails_fast_on_a_busy_port_without_touching_the_database(self):
        blocker = socket.socket()
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        blocker.bind(('127.0.0.1', 0))
        blocker.listen(1)
        try:
            port = str(blocker.getsockname()[1])
            code, out = cli('--db', self.db, 'run', str(self.p / 'm.json'), '--port', port)
        finally:
            blocker.close()
        self.assertEqual(code, 1)
        self.assertIn('已被占用', json.loads(out)['error']['message'])
        self.assertFalse(Path(self.db).exists())


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        log = self.p / 'spectre.out'
        log.write_text(LOG + FOOT, encoding='utf-8')
        self.path = self.p / 'db.sqlite'
        with connect(self.path) as db:  # closed before serving: readers work without a writer
            scan(db, {'id': 't', 'log': str(log)})
        self.start(self.path)

    def start(self, path):
        self.server = make_server(path, 0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def get(self, path, host=None, data=None):
        headers = {'Host': host} if host else {}
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers=headers, data=data)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def json(self, path, host=None):
        status, _, body = self.get(path, host)
        return status, json.loads(body)

    def test_api_and_assets(self):
        status, runs = self.json('/api/runs')
        self.assertEqual((status, runs['schema_version']), (200, 3))
        self.assertEqual(runs['runs'][0]['state']['status'], 'complete')
        group = self.json('/api/problems?run=t')[1]['problems'][0]
        item = self.json(f"/api/evidence?id={group['first_evidence_id']}")[1]['evidence']
        self.assertIn('<script>', item['raw'])
        self.assertEqual(len(self.json('/api/measurements?run=t&tail=2')[1]['measurements']), 2)
        self.assertEqual(self.json('/api/run-details?run=t')[1]['details']['run_id'], 't')
        health = self.json('/api/health')[1]
        self.assertEqual((health['status'], health['pid']), ('ok', os.getpid()))
        self.assertFalse(health['collector']['alive'])
        self.assertNotIn('unsafe-inline', CSP)
        for path in ('/', '/app.js', '/style.css'):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers['Content-Security-Policy'], CSP)
        script = self.get('/app.js')[2].decode('utf-8')
        self.assertIn('textContent', script)
        self.assertNotIn('innerHTML', script)
        page = self.get('/')[2].decode('utf-8')
        self.assertIn('app.js', page)
        self.assertNotIn('<script>', page.split('</head>')[1])  # no inline script in the body

    def test_errors_are_json(self):
        for path, expected in (('/api/evidence?id=abc', 400), ('/api/evidence?id=999999', 404),
                               ('/api/problems', 400), ('/api/run-details?run=none', 404), ('/nope', 404)):
            status, body = self.json(path)
            self.assertEqual((status, body['error']['status']), (expected, expected), path)
        self.assertEqual(self.get('/api/runs', data=b'{}')[0], 501)

    def test_foreign_host_is_rejected(self):
        status, body = self.json('/api/runs', host=f'attacker.example:{self.port}')
        self.assertEqual((status, body['error']['status']), (403, 403))
        self.assertEqual(self.json('/api/runs', host=f'localhost:{self.port}')[0], 200)

    def test_old_database_is_reported_not_served(self):
        self.stop()
        old = self.p / 'old.sqlite'
        with sqlite3.connect(old) as raw:
            raw.execute('CREATE TABLE runs(id TEXT)')
        raw.close()
        self.start(old)
        status, body = self.json('/api/runs')
        self.assertEqual(status, 503)
        self.assertIn('schema', body['error']['message'])
        self.assertEqual(self.json('/api/health')[1]['status'], 'degraded')


if __name__ == '__main__':
    unittest.main()
