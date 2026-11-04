"""CLI and HTTP contracts: compact UTF-8 text/JSON, errors in the same form, read-only access,
loopback-only hosts."""
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


def cli(*args, env=None, timeout=60):
    clean = {k: v for k, v in os.environ.items() if k not in ('PYTHONIOENCODING', 'PYTHONUTF8', 'SIMCHECK_DB')}
    done = subprocess.run([sys.executable, '-m', 'simcheck', *args], cwd=ROOT, env=dict(clean, **(env or {})),
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

    def test_text_by_default_json_on_request_utf8_either_way(self):
        code, out = cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        self.assertEqual(code, 0)
        self.assertIn('cursor ', out.splitlines()[0])
        self.assertIn('\nt: complete | tran | W1 | frames 3', out)
        code, out = cli('--db', self.db, 'show', 't', '--json')
        group = json.loads(out)['groups'][0]
        self.assertIn('µV', group['msg'])
        code, out = cli('--db', self.db, 'evidence', f"e{group['e']}")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertTrue(lines[1].endswith('spectre.out:2'))
        self.assertIn('at time = 2 ns', lines[2])
        self.assertIn('✓', lines[3])
        code, out = cli('--json', '--db', self.db, 'evidence', str(group['e']))  # global flags, bare ID
        self.assertIn('✓', json.loads(out)['raw'])
        code, out = cli('--db', self.db, 'measurements', 't', '--tail', '2', '--json')
        rows = json.loads(out)['rows']
        self.assertEqual([m['frame'] for m in rows], [1, 2])
        code, out = cli('--db', self.db, 'measurements', 't', '--tail', '2')
        self.assertEqual(out.splitlines()[1:3], ['frame code valid evidence', f"1 24 1 e{rows[0]['e']}"])
        code, out = cli('status', env={'SIMCHECK_DB': self.db})
        self.assertEqual(code, 0)
        self.assertIn('t: complete', out)

    def test_errors_and_reads_never_create_a_database(self):
        missing = str(self.p / 'missing.sqlite')
        code, out = cli('--db', missing, 'status', '--json')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'FileNotFoundError'))
        code, out = cli('--db', missing, 'status')
        self.assertTrue(out.startswith('error: FileNotFoundError:'))
        self.assertFalse(Path(missing).exists())
        cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        code, out = cli('--db', self.db, 'evidence', 'e999999', '--json')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'LookupError'))
        self.assertEqual(cli('--db', self.db, 'evidence', 'x1')[0], 2)  # argparse rejects a malformed handle
        old = self.p / 'old.sqlite'
        with sqlite3.connect(old) as raw:
            raw.execute('CREATE TABLE runs(id TEXT)')
        raw.close()
        code, out = cli('--db', str(old), 'status', '--json')
        self.assertEqual((code, json.loads(out)['error']['type']), (1, 'SchemaError'))

    def test_wait_without_a_live_collector(self):
        cli('--db', self.db, 'scan', str(self.p / 'm.json'))
        code, out = cli('--db', self.db, 'wait', '--timeout', '1', '--json')
        self.assertEqual((code, json.loads(out)['reason']), (4, 'collector_offline'))
        code, out = cli('--db', self.db, 'wait', '--timeout', '1')
        self.assertEqual(code, 4)
        self.assertIn('no collector running', out)

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
        self.assertIn('already in use', out)
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
        # Loopback tests must reach our server even when the environment defines
        # HTTP proxies; a deliberately foreign Host can otherwise reach a proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def json(self, path, host=None):
        status, _, body = self.get(path, host)
        return status, json.loads(body)

    def test_api_and_assets(self):
        status, runs = self.json('/api/status')
        self.assertEqual((status, runs['v']), (200, 4))
        self.assertEqual(runs['runs'][0]['state'], 'complete')
        group = self.json('/api/show?run=t')[1]['groups'][0]
        item = self.json(f"/api/evidence?id=e{group['e']}")[1]
        self.assertIn('<script>', item['raw'])
        self.assertEqual(len(self.json('/api/measurements?run=t&tail=2')[1]['rows']), 2)
        self.assertEqual(self.json('/api/details?run=t')[1]['run'], 't')
        health = self.json('/api/health')[1]
        self.assertEqual((health['status'], health['pid']), ('ok', os.getpid()))
        self.assertFalse(health['collector']['live'])
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
        for path, expected in (('/api/evidence?id=abc', 400), ('/api/evidence?id=e999999', 404),
                               ('/api/show', 400), ('/api/details?run=none', 404),
                               ('/api/status?run=none', 404), ('/nope', 404),
                               ('/api/export', 400), ('/api/export?run=none', 404),
                               ('/api/export?run=t&format=exe', 400)):
            status, body = self.json(path)
            self.assertEqual((status, body['error']['status']), (expected, expected), path)
        # Only the unsupported method matters here. An empty POST avoids a
        # Windows connection reset when the server closes with unread body data.
        self.assertEqual(self.get('/api/status', data=b'')[0], 501)

    def test_saved_html_and_json_are_downloads_with_original_evidence(self):
        code, headers, body = self.get('/api/export?run=t&format=json')
        saved = json.loads(body)
        self.assertEqual((code, headers['Content-Length']), (200, str(len(body))))
        self.assertIn('attachment; filename="t-g1-', headers['Content-Disposition'])
        self.assertEqual(saved['summary']['state'], 'complete')
        self.assertEqual(saved['scope']['events'], len(saved['events']))
        self.assertTrue(saved['export_complete'])
        warning = next(e for e in saved['events'] if e.get('code') == 'X-1')
        self.assertIn('<script>alert(1)</script>', warning['raw'])
        self.assertEqual((warning['severity'], warning['line']), ('WARNING', 2))
        code, headers, body = self.get('/api/export?run=t&format=html')
        html = body.decode('utf-8')
        self.assertEqual(code, 200)
        self.assertIn('.html"', headers['Content-Disposition'])
        self.assertIn('<html lang="en">', html)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('µV', html)
        self.assertIn('Snapshot export complete.', html)
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.get('/api/export?run=t', host=f'attacker.example:{self.port}')[0], 403)
        self.assertEqual(self.get('/api/export?run=t', data=b'')[0], 501)

    def test_foreign_host_is_rejected(self):
        status, body = self.json('/api/status', host=f'attacker.example:{self.port}')
        self.assertEqual((status, body['error']['status']), (403, 403))
        self.assertEqual(self.json('/api/status', host=f'localhost:{self.port}')[0], 200)

    def test_old_database_is_reported_not_served(self):
        self.stop()
        old = self.p / 'old.sqlite'
        with sqlite3.connect(old) as raw:
            raw.execute('CREATE TABLE runs(id TEXT)')
        raw.close()
        self.start(old)
        status, body = self.json('/api/status')
        self.assertEqual(status, 503)
        self.assertIn('schema', body['error']['message'])
        self.assertEqual(self.json('/api/health')[1]['status'], 'degraded')


if __name__ == '__main__':
    unittest.main()
