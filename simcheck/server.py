"""Localhost-only, read-only HTTP interface. No filesystem, process or write endpoints."""
import json
import os
import socket
import sqlite3
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .store import (SCHEMA, SchemaError, collector_status, evidence, measurements, open_readonly,
                    problem_groups, run_details, summaries)

WEB = Path(__file__).parent / 'web'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # Windows otherwise lets two reuse-address listeners share one port, so a
        # browser can silently reach a stale viewer process.
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _int(q, key, default=None):
    if q.get(key) in (None, ''):
        return default
    try:
        return int(q[key])
    except ValueError:
        raise ApiError(400, key + ' must be an integer') from None


def _run(q):
    if not q.get('run'):
        raise ApiError(400, 'run is required')
    return q['run']


def handler(database, started=None):
    database = str(Path(database).resolve())
    started = time.time() if started is None else started

    class Handler(BaseHTTPRequestHandler):
        server_version = 'simcheck/' + __version__

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                self._check_host()
                if url.path in ASSETS:
                    name, kind = ASSETS[url.path]
                    self._send(200, (WEB / name).read_bytes(), kind)
                else:
                    body = json.dumps(self._api(url.path, q), ensure_ascii=False).encode('utf-8')
                    self._send(200, body, 'application/json; charset=utf-8')
            except ApiError as e:
                self._error(e.status, str(e))
            except (SchemaError, FileNotFoundError) as e:
                self._error(503, str(e))
            except sqlite3.Error as e:
                self._error(503, 'database unavailable: ' + str(e))

        def _check_host(self):
            # Reject DNS-rebinding pages: only loopback names for this port are served.
            port = self.server.server_port
            host = (self.headers.get('Host') or '').lower()
            if host not in {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}:
                raise ApiError(403, 'unexpected Host header')

        def _api(self, path, q):
            if path == '/api/health':
                info = {'schema_version': SCHEMA, 'status': 'ok', 'mode': 'read_only',
                        'version': __version__, 'pid': os.getpid(), 'started_epoch': started,
                        'database': database}
                try:
                    with open_readonly(database) as db:
                        info['collector'] = collector_status(db)
                except (SchemaError, FileNotFoundError, sqlite3.Error) as e:
                    info.update(status='degraded', database_error=str(e))
                return info
            if path not in ('/api/runs', '/api/problems', '/api/measurements', '/api/evidence',
                            '/api/run-details'):
                raise ApiError(404, 'not found')
            with open_readonly(database) as db:
                if path == '/api/runs':
                    return summaries(db)
                if path == '/api/problems':
                    run = _run(q)
                    return {'schema_version': SCHEMA, 'run_id': run,
                            'problems': problem_groups(db, run, _int(q, 'generation'),
                                                       _int(q, 'after', 0), _int(q, 'limit', 50))}
                if path == '/api/measurements':
                    run = _run(q)
                    return {'schema_version': SCHEMA, 'run_id': run,
                            'measurements': measurements(db, run, _int(q, 'after', 0), _int(q, 'limit', 50),
                                                         _int(q, 'generation'), _int(q, 'before'),
                                                         _int(q, 'tail'))}
                if path == '/api/evidence':
                    result = evidence(db, _int(q, 'id', -1))
                    if result is None:
                        raise ApiError(404, 'evidence not found')
                    return {'schema_version': SCHEMA, 'evidence': result}
                result = run_details(db, _run(q))
                if result is None:
                    raise ApiError(404, 'run not found')
                return {'schema_version': SCHEMA, 'details': result}

        def _send(self, status, body, kind):
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', CSP)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            body = json.dumps({'schema_version': SCHEMA, 'error': {'status': status, 'message': message}},
                              ensure_ascii=False).encode('utf-8')
            self._send(status, body, 'application/json; charset=utf-8')

        def log_message(self, *args):
            pass

    return Handler


def make_server(database, port=8765):
    """Bind before any collection work so a busy port fails fast."""
    return LocalServer(('127.0.0.1', port), handler(database))


def serve(server, open_browser=False):
    url = f'http://127.0.0.1:{server.server_port}'
    print('Viewer: ' + url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
