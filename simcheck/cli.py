"""Command line interface. Machine output is UTF-8 JSON on stdout."""
import argparse
import errno
import json
import sqlite3
import sys
import threading
import time

from . import __version__
from .server import make_server, serve
from .store import (SCHEMA, collect, connect, evidence, events, heartbeat, manifest, measurements,
                    open_readonly, problem_groups, retire, run_details, summaries, wait_for_change)

DEFAULT_DB = '.runtime/simcheck.sqlite'
PREFIXES = ((1, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n'), (1e-12, 'p'), (1e-15, 'f'))


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def fmt_time(seconds):
    if seconds is None:
        return '—'
    for scale, prefix in PREFIXES:
        if abs(seconds) >= scale or scale == 1e-15:
            return f'{seconds / scale:.4g} {prefix}s'
    return f'{seconds:g} s'


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
        emit(summaries(db))


def cmd_status(args):
    with open_readonly(args.db) as db:
        emit(summaries(db))


def cmd_wait(args):
    result, code = wait_for_change(args.db, args.after, args.since, args.runs, args.timeout,
                                   args.interval, args.notices, args.repeats)
    emit(result)
    return code


def cmd_problems(args):
    with open_readonly(args.db) as db:
        emit({'schema_version': SCHEMA, 'run_id': args.run,
              'problems': problem_groups(db, args.run, args.generation, args.after, args.limit)})


def cmd_measurements(args):
    with open_readonly(args.db) as db:
        emit({'schema_version': SCHEMA, 'run_id': args.run,
              'measurements': measurements(db, args.run, args.after, args.limit, args.generation,
                                           args.before, args.tail)})


def cmd_evidence(args):
    with open_readonly(args.db) as db:
        result = evidence(db, args.id)
    if result is None:
        raise LookupError(f'evidence {args.id} not found')
    emit({'schema_version': SCHEMA, 'evidence': result})


def cmd_details(args):
    with open_readonly(args.db) as db:
        result = run_details(db, args.run)
    if result is None:
        raise LookupError(f'run {args.run} not found')
    emit({'schema_version': SCHEMA, 'details': result})


def cmd_events(args):
    with open_readonly(args.db) as db:
        emit({'schema_version': SCHEMA, 'events': events(db, args.run, args.after, args.limit,
                                                         args.category, args.severity, args.generation)})


def cmd_report(args):
    with open_readonly(args.db) as db:
        data = summaries(db)
        groups = {r['run_id']: problem_groups(db, r['run_id'], r['generation'], limit=500)
                  for r in data['runs']}
    print('# Spectre 证据报告\n\n不推断电路或码字是否合格；时间为日志中该消息头行给出的仿真时间。\n')
    for run in data['runs']:
        state = run['state']
        print(f"## {run['run_id']} — {state['status']}\n")
        if run['attention']:
            print('关注：' + '、'.join(run['attention']) + '\n')
        for hit in run['rule_hits']:
            print(f"- 规则「{hit['rule']}」命中 {hit['problem_key']} ×{hit['printed_count']}，"
                  f"首次 {fmt_time(hit['first_sim_time_s'])} [证据 {hit['first_evidence_id']}]")
        if run['baseline'] and run['baseline']['keys_not_in_baseline']:
            keys = ', '.join(k['problem_key'] for k in run['baseline']['keys_not_in_baseline'])
            print(f"- 参考 run {run['baseline']['run_id']} 中没有：{keys}")
        print('\n| 级别 | 键 | 已打印 | 阶段 | 首次仿真时间 | 之后被抑制 | 证据 |\n|---|---|---|---|---|---|---|')
        for g in groups[run['run_id']]:
            key = g['problem_key'].replace('|', '\\|')
            print(f"| {g['severity']} | {key} | {g['printed_count']} | {g['phase']} | "
                  f"{fmt_time(g['first_sim_time_s'])} | {'是' if g['suppressed_after'] else ''} | "
                  f"{g['first_evidence_id']} |")
        print('\n覆盖：' + ('、'.join(run['coverage']['limitations']) or '全部已配置检查已观察') + '\n')


def build_parser():
    p = argparse.ArgumentParser(prog='simcheck', description='Read-only Spectre evidence monitor')
    p.add_argument('--db', default=DEFAULT_DB)
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True)
    for name, text in (('scan', 'index until caught up, then print the summary'),
                       ('watch', 'collector loop without a web viewer')):
        a = sub.add_parser(name, help=text)
        a.add_argument('manifest')
        a.add_argument('--interval', type=float, default=2)
        a.add_argument('--final', action='store_true',
                       help='parse a last unterminated line; use only for closed files')
    a = sub.add_parser('run', help='collector and local dashboard in one foreground process')
    a.add_argument('manifest')
    a.add_argument('--port', type=int, default=8765, help='0 picks a free port')
    a.add_argument('--open', action='store_true', help='open the viewer in the default browser')
    a.add_argument('--interval', type=float, default=2)
    a = sub.add_parser('serve', help='dashboard only; needs a separate watch collector')
    a.add_argument('--port', type=int, default=8765)
    sub.add_parser('status', help='summary of every run')
    a = sub.add_parser('wait', help='block until something needs attention (exit 0), 3 timeout, 4 no collector')
    a.add_argument('--after', type=int, help='last_event_id from the previous answer')
    a.add_argument('--since', help='token from the previous answer')
    a.add_argument('--run', action='append', dest='runs', help='limit to a run (repeatable)')
    a.add_argument('--timeout', type=float, default=3600)
    a.add_argument('--interval', type=float, default=2)
    a.add_argument('--notices', action='store_true', help='also wake on new NOTICE groups')
    a.add_argument('--repeats', action='store_true', help='also wake on more occurrences of known groups')
    a = sub.add_parser('problems')
    a.add_argument('--run', required=True)
    a.add_argument('--after', type=int, default=0)
    a.add_argument('--limit', type=int, default=50)
    a.add_argument('--generation', type=int)
    a = sub.add_parser('measurements')
    a.add_argument('--run', required=True)
    a.add_argument('--after', type=int, default=0)
    a.add_argument('--before', type=int)
    a.add_argument('--tail', type=int, help='newest N records')
    a.add_argument('--limit', type=int, default=50)
    a.add_argument('--generation', type=int)
    a = sub.add_parser('evidence')
    a.add_argument('id', type=int)
    a = sub.add_parser('details')
    a.add_argument('--run', required=True)
    sub.add_parser('report', help='Markdown report')
    a = sub.add_parser('events', help='raw stored events (debug/export)')
    a.add_argument('--run')
    a.add_argument('--after', type=int, default=0)
    a.add_argument('--limit', type=int, default=100)
    a.add_argument('--category')
    a.add_argument('--severity')
    a.add_argument('--generation', type=int)
    return p


COMMANDS = {'run': cmd_run, 'watch': cmd_watch, 'serve': cmd_serve, 'scan': cmd_scan,
            'status': cmd_status, 'wait': cmd_wait, 'problems': cmd_problems,
            'measurements': cmd_measurements, 'evidence': cmd_evidence, 'details': cmd_details,
            'events': cmd_events, 'report': cmd_report}


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
        emit({'schema_version': SCHEMA, 'error': {'type': type(exc).__name__, 'message': str(exc)}})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
