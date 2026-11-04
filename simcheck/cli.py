"""Command line interface. Default output is compact text for agents; --json prints the same
content as JSON. Every handle printed (eNNN, a cursor) can be passed straight back in."""
import argparse
import errno
import heapq
import json
import os
import sqlite3
import sys
import threading
import time

from . import __version__, render
from .integrity import fingerprint
from .server import make_server, serve
from .store import (API, collect, connect, details, digest, events, evidence, evidence_id, heartbeat,
                    manifest, scan, record_error, measurement_page, open_readonly, retire, show, snapshot, status,
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


def collector_loop(db_path, configs, interval, stop, port=None, final=False, manifest_path=None):
    """Schedule each run independently. Only this loop owns the writer and active caches."""
    started = time.time()
    interval = max(0.2, interval)
    runs = {cfg['id']: cfg for cfg in configs}
    # IDs sort deterministically when deadlines coincide.
    due = [(0.0, rid) for rid in runs]
    heapq.heapify(due)
    cache, root_cache, sidecars, errors = {}, {}, {}, {}
    next_discovery = time.monotonic() + 30
    next_heartbeat = 0
    with connect(db_path) as db:
        try:
            while not stop.is_set():
                now = time.monotonic()
                if manifest_path and now >= next_discovery:
                    try:
                        fresh = {c['id']: c for c in manifest(manifest_path, root_cache)['runs']}
                        for rid in runs.keys() - fresh.keys():
                            record_error(db, runs[rid], ValueError('run no longer listed by discovery'))
                            cache.pop(rid, None)
                            sidecars.pop(rid, None)
                            errors.pop(rid, None)
                        due = [(t, r) for t, r in due if r in fresh and runs[r] == fresh[r]]
                        for rid, cfg in fresh.items():
                            if cfg != runs.get(rid):
                                due.append((now, rid))
                                cache.pop(rid, None)
                                sidecars.pop(rid, None)
                        heapq.heapify(due)
                        runs = fresh
                        errors.pop(None, None)
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        db.rollback()
                        errors[None] = 'discovery: ' + str(exc)
                    next_discovery = now + 30
                if now >= next_heartbeat:
                    try:
                        heartbeat(db, started, interval, port, '; '.join(errors.values())[:500] or None)
                    except sqlite3.Error as exc:
                        db.rollback()
                        print('Collector heartbeat: ' + str(exc), file=sys.stderr, flush=True)
                    next_heartbeat = now + interval
                wake = min(next_heartbeat, next_discovery if manifest_path else float('inf'))
                if not due or due[0][0] > now:
                    stop.wait(max(0, min(wake, due[0][0] if due else wake) - now))
                    continue
                _, rid = heapq.heappop(due)
                cfg = runs[rid]
                delay = interval
                try:
                    stamp = tuple(fingerprint(cfg[k]) for k in ('log', 'state', 'log_status', 'raw') if cfg.get(k))
                    prior = cache.get(rid)
                    if prior and stamp == prior[0] and now < prior[1]:
                        delay = min(60, prior[2] * 2) if prior[3] else interval
                        cache[rid] = (*prior[:2], delay, prior[3])
                    else:
                        if prior and now >= prior[1]:
                            sidecars.pop(rid, None)
                        result = scan(db, cfg, final, sidecars.setdefault(rid, {}))
                        errors.pop(rid, None)
                        if result['backlog']:
                            delay = 0
                            cache.pop(rid, None)
                        elif result.get('error') or result['retry_nul']:
                            cache.pop(rid, None)
                        else:
                            state = result['integrity']['status']
                            quiet = time.time() - result.get('source_mtime_epoch', time.time())
                            backoff = state in ('complete', 'failed', 'incomplete') or quiet > cfg.get('quiet_after_s', 1800) > 0
                            cache[rid] = (stamp, now + 300, delay, backoff)
                except Exception as exc:
                    db.rollback()
                    cache.pop(rid, None)
                    try:
                        errors[rid] = record_error(db, cfg, exc)
                    except sqlite3.Error as write_error:
                        db.rollback()
                        errors[rid] = str(write_error)[:500]
                        print(f'Collector error for {rid}: {write_error}', file=sys.stderr, flush=True)
                heapq.heappush(due, (time.monotonic() + delay, rid))
        finally:
            retire(db)


def cmd_run(args):
    data = manifest(args.manifest)
    configs = data['runs']
    try:
        server = make_server(args.db, args.port)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, 'winerror', None) in (10048, 10013):
            raise OSError(f'Port {args.port} is already in use. Choose a free port with --port 0 '
                          'or check the viewer version and PID at /api/health.') from None
        raise
    try:
        with connect(args.db):
            pass  # schema check before the collector thread starts
        stop = threading.Event()
        worker = threading.Thread(target=collector_loop, daemon=True,
                                  args=(args.db, configs, args.interval, stop, server.server_port),
                                  kwargs={'manifest_path': args.manifest if data.get('roots') else None})
        worker.start()
        try:
            serve(server, args.open)
        finally:
            stop.set()
            worker.join(timeout=10)
    finally:
        server.server_close()


def cmd_watch(args):
    data = manifest(args.manifest)
    configs = data['runs']
    stop = threading.Event()
    try:
        collector_loop(args.db, configs, args.interval, stop, final=args.final,
                       manifest_path=args.manifest if data.get('roots') else None)
    except KeyboardInterrupt:
        stop.set()


def cmd_serve(args):
    open_readonly(args.db).close()
    serve(make_server(args.db, args.port))


def cmd_scan(args):
    configs = manifest(args.manifest)['runs']
    with connect(args.db) as db:
        while configs:
            results = collect(db, configs, args.final)
            configs = [c for c in configs if results[c['id']].get('backlog')]
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
