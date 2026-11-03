"""Localhost-only, read-only HTTP interface. No filesystem, process or write endpoints.

The JSON is the same compact contract as `simcheck --json`: /api/status, /api/show,
/api/evidence, /api/measurements, /api/details, /api/health. /api/export downloads a saved snapshot.
"""
import json
import os
import shutil
import socket
import sqlite3
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .export import REPORT_CSP, export_file
from .store import (API, SchemaError, collector_brief, collector_status, details, evidence, evidence_id,
                    measurement_page, open_readonly, show, status)

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


def _int(q, key, default=None, parse=int):
    if q.get(key) in (None, ''):
        return default
    try:
        return parse(q[key])
    except ValueError:
        raise ApiError(400, f'{key} must be an integer' + (' or e123' if parse is evidence_id else '')) from None


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
                elif url.path == '/api/export':
                    format = q.get('format', 'json')
                    if format not in ('html', 'json'):
                        raise ApiError(400, 'format must be html or json')
                    with open_readonly(database) as db:
                        file, name, kind = export_file(db, _run(q), format)
                    with file:
                        size = file.seek(0, 2)
                        file.seek(0)
                        self._headers(200, size, kind, name, REPORT_CSP if format == 'html' else CSP)
                        shutil.copyfileobj(file, self.wfile, 65536)
                else:
                    body = json.dumps(self._api(url.path, q), ensure_ascii=False, separators=(',', ':'))
                    self._send(200, body.encode('utf-8'), 'application/json; charset=utf-8')
            except ApiError as e:
                self._error(e.status, str(e))
            except LookupError as e:
                self._error(404, str(e))
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
                info = {'v': API, 'status': 'ok', 'version': __version__, 'pid': os.getpid(),
                        'started': round(started), 'db': database}
                try:
                    with open_readonly(database) as db:
                        info['collector'] = collector_brief(collector_status(db))
                except (SchemaError, FileNotFoundError, sqlite3.Error) as e:
                    info.update(status='degraded', error=str(e))
                return info
            if path not in ('/api/status', '/api/show', '/api/evidence', '/api/measurements', '/api/details'):
                raise ApiError(404, 'not found')
            with open_readonly(database) as db:
                if path == '/api/status':
                    return status(db, [q['run']] if q.get('run') else None)
                if path == '/api/show':
                    result = show(db, _run(q), full=q.get('full') in ('1', 'true'), limit=_int(q, 'limit', 30))
                elif path == '/api/evidence':
                    result = evidence(db, _int(q, 'id', -1, evidence_id))
                elif path == '/api/measurements':
                    result = measurement_page(db, _run(q), _int(q, 'after', 0, evidence_id), _int(q, 'limit', 20),
                                              _int(q, 'before', None, evidence_id), _int(q, 'tail'))
                else:
                    result = details(db, _run(q))
                if result is None:
                    raise ApiError(404, 'not found')
                return result

        def _headers(self, status_code, size, kind, filename=None, csp=CSP):
            self.send_response(status_code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(size))
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', csp)
            self.end_headers()

        def _send(self, status_code, body, kind):
            self._headers(status_code, len(body), kind)
            self.wfile.write(body)

        def _error(self, status_code, message):
            body = json.dumps({'v': API, 'error': {'status': status_code, 'message': message}},
                              ensure_ascii=False).encode('utf-8')
            self._send(status_code, body, 'application/json; charset=utf-8')

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
