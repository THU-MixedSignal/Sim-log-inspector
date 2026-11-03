"""Command line interface. Default output is compact text for agents; --json prints the same
content as JSON. Every handle printed (eNNN, a cursor) can be passed straight back in."""
import argparse
import errno
import json
import os
import sqlite3
import sys
import threading
import time

from . import __version__, render
from .server import make_server, serve
from .store import (API, collect, connect, details, digest, events, evidence, evidence_id, heartbeat,
                    manifest, measurement_page, open_readonly, retire, show, snapshot, status,
                    wait_for_change)

DEFAULT_DB = '.runtime/simcheck.sqlite'
GUIDE = '''agent loop:
  simcheck status              runs needing attention first; prints a cursor
  simcheck wait --cursor C     blocks until something new needs attention; prints the next cursor
  simcheck show RUN            problem groups of one run with evidence IDs (eNNN)
  simcheck evidence eNNN       the raw log lines and path:line
--json prints the same content as JSON. Set SIMCHECK_DB instead of repeating --db.'''


def emit(args, data, text):
    if args.json:
        print(json.dumps(data, ensure_ascii=False, separators=(',', ':')), flush=True)
    else:
        print(text(data), flush=True)


def collector_loop(db_path, configs, interval, stop, port=None, final=False):
    """Collect until stopped. Writes a heartbeat so readers can tell when data goes stale."""
    started = time.time()
    with connect(db_path) as db:
        try:
            while not stop.is_set():
                try:
                    results = collect(db, configs, final)
                    errors = '; '.join(f"{rid}: {r['collector_error']}"
                                       for rid, r in results.items() if r.get('collector_error'))
                    heartbeat(db, started, interval, port, errors[:500] or None)
                    if any(r.get('backlog') for r in results.values()):
                        continue  # keep indexing; bounded ticks, no idle wait while behind
                except sqlite3.Error as exc:
                    db.rollback()
                    print('Collector error: ' + str(exc), file=sys.stderr, flush=True)
                stop.wait(max(0.2, interval))
        finally:
            retire(db)


def cmd_run(args):
    configs = manifest(args.manifest)['runs']
    try:
        server = make_server(args.db, args.port)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, 'winerror', None) in (10048, 10013):
            raise OSError(f'端口 {args.port} 已被占用（可能已有查看器在运行）。'
                          '用 --port 0 自动选择空闲端口，或用 /api/health 查看占用者的版本和 PID。') from None
        raise
    try:
        with connect(args.db):
            pass  # schema check before the collector thread starts
        stop = threading.Event()
        worker = threading.Thread(target=collector_loop, daemon=True,
                                  args=(args.db, configs, args.interval, stop, server.server_port))
        worker.start()
        try:
            serve(server, args.open)
        finally:
            stop.set()
            worker.join(timeout=10)
    finally:
        server.server_close()


def cmd_watch(args):
    configs = manifest(args.manifest)['runs']
    stop = threading.Event()
    try:
        collector_loop(args.db, configs, args.interval, stop, final=args.final)
    except KeyboardInterrupt:
        stop.set()


def cmd_serve(args):
    open_readonly(args.db).close()
    serve(make_server(args.db, args.port))


def cmd_scan(args):
    configs = manifest(args.manifest)['runs']
    with connect(args.db) as db:
        while any(r.get('backlog') for r in collect(db, configs, args.final).values()):
            pass
        emit(args, digest(snapshot(db)), render.status)


def cmd_status(args):
    with open_readonly(args.db) as db:
        emit(args, status(db, args.runs), render.status)


def cmd_wait(args):
    result, code = wait_for_change(args.db, args.cursor, args.runs, args.timeout, args.interval,
                                   args.notices, args.repeats)
    emit(args, result, render.wait)
    return code


def cmd_show(args):
    with open_readonly(args.db) as db:
        data = show(db, args.run, full=args.all, limit=args.limit)
    if data is None:
        raise LookupError(f'unknown run: {args.run}')
    emit(args, data, render.show)


def cmd_evidence(args):
    with open_readonly(args.db) as db:
        data = evidence(db, args.id)
    if data is None:
        raise LookupError(f'evidence e{args.id} not found')
    emit(args, data, render.evidence)


def cmd_measurements(args):
    with open_readonly(args.db) as db:
        data = measurement_page(db, args.run, args.after or 0, args.limit, args.before, args.tail)
    if data is None:
        raise LookupError(f'unknown run: {args.run}')
    emit(args, data, render.measurements)


def cmd_details(args):
    with open_readonly(args.db) as db:
        data = details(db, args.run)
    if data is None:
        raise LookupError(f'unknown run: {args.run}')
    emit(args, data, render.details)


def cmd_events(args):
    with open_readonly(args.db) as db:
        rows = events(db, args.run, args.after, args.limit, args.category, args.severity, args.generation)
    print(json.dumps({'v': API, 'events': rows}, ensure_ascii=False), flush=True)


def build_parser():
    # Subcommands accept --db/--json too; SUPPRESS keeps them from overwriting a value given earlier.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--db', default=argparse.SUPPRESS, help='database file')
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help='print JSON instead of text')
    p = argparse.ArgumentParser(prog='simcheck', description='Read-only Spectre evidence monitor.',
                                epilog=GUIDE, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--db', default=os.environ.get('SIMCHECK_DB') or DEFAULT_DB,
                   help='database file (default: $SIMCHECK_DB or .runtime/simcheck.sqlite)')
    p.add_argument('--json', action='store_true', help='print JSON instead of text')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True, metavar='COMMAND')

    def command(name, text):
        return sub.add_parser(name, help=text, description=text, parents=[common])

    a = command('status', 'all runs, attention first: state, progress, first errors, rule hits, cursor')
    a.add_argument('--run', action='append', dest='runs', metavar='RUN', help='only this run (repeatable)')
    a = command('wait', 'block until something needs attention; exit 0 change, 3 timeout, 4 no collector')
    a.add_argument('--cursor', help='cursor from the previous status or wait')
    a.add_argument('--run', action='append', dest='runs', metavar='RUN', help='only this run (repeatable)')
    a.add_argument('--timeout', type=float, default=3600)
    a.add_argument('--interval', type=float, default=2)
    a.add_argument('--notices', action='store_true', help='also wake on new NOTICE groups')
    a.add_argument('--repeats', action='store_true', help='also wake on more occurrences of known groups')
    a = command('show', 'problem groups of one run with evidence IDs')
    a.add_argument('run')
    a.add_argument('--all', action='store_true', help='include NOTICE groups and lift the line limit')
    a.add_argument('--limit', type=int, default=30)
    a = command('evidence', 'raw log lines of one evidence ID with path:line')
    a.add_argument('id', type=evidence_id, metavar='eID')
    a = command('measurements', 'testbench records of one run, newest by default')
    a.add_argument('run')
    a.add_argument('--tail', type=int, help='newest N records')
    a.add_argument('--before', type=evidence_id, metavar='eID')
    a.add_argument('--after', type=evidence_id, metavar='eID')
    a.add_argument('--limit', type=int, default=20)
    a = command('details', 'completion checks and requested vs effective settings of one run')
    a.add_argument('run')
    for name, text in (('scan', 'index until caught up once, then print status'),
                       ('watch', 'collector loop without a dashboard')):
        a = command(name, text)
        a.add_argument('manifest')
        a.add_argument('--interval', type=float, default=2)
        a.add_argument('--final', action='store_true', help='parse a last unterminated line; closed files only')
    a = command('run', 'collector and local dashboard in one foreground process')
    a.add_argument('manifest')
    a.add_argument('--port', type=int, default=8765, help='0 picks a free port')
    a.add_argument('--open', action='store_true', help='open the dashboard in the default browser')
    a.add_argument('--interval', type=float, default=2)
    a = command('serve', 'dashboard only; needs a separate watch collector')
    a.add_argument('--port', type=int, default=8765)
    a = command('events', 'raw stored events as JSON (debug/export)')
    a.add_argument('--run')
    a.add_argument('--after', type=int, default=0)
    a.add_argument('--limit', type=int, default=100)
    a.add_argument('--category')
    a.add_argument('--severity')
    a.add_argument('--generation', type=int)
    return p


COMMANDS = {'status': cmd_status, 'wait': cmd_wait, 'show': cmd_show, 'evidence': cmd_evidence,
            'measurements': cmd_measurements, 'details': cmd_details, 'scan': cmd_scan,
            'watch': cmd_watch, 'run': cmd_run, 'serve': cmd_serve, 'events': cmd_events}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')  # never the console code page
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args) or 0
    except KeyboardInterrupt:
        return 130
    except (LookupError, ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        if args.json:
            print(json.dumps({'v': API, 'error': {'type': type(exc).__name__, 'message': str(exc)}},
                             ensure_ascii=False, separators=(',', ':')), flush=True)
        else:
            print(f'error: {type(exc).__name__}: {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
