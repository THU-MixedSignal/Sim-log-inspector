"""Compare query latency and storage on ten synthetic warning streams, using a local temporary DB."""
import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

args = argparse.ArgumentParser(description=__doc__)
args.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1],
                  help='checkout containing the simcheck version to measure')
args.add_argument('--runs', type=int, default=10)
args.add_argument('--per-run', type=int, nargs='+', default=[20000, 100000])
opts = args.parse_args()
if opts.runs < 1 or opts.per_run != sorted(set(opts.per_run)) or min(opts.per_run) < 1:
    args.error('positive run count and increasing positive checkpoints required')
sys.path.insert(0, str(opts.source.resolve()))
from simcheck import store


def median_ms(fn):
    samples = []
    for _ in range(3):
        start = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return round(statistics.median(samples), 3)

line = b'    WARNING (SPECTRE-16780): LTE tolerance was temporarily relaxed.\n'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    configs = [dict(id=f'run-{i}', log=str(root / f'run-{i}.log')) for i in range(opts.runs)]
    with store.connect(root / 'events.db') as db:
        previous = 0
        for count in opts.per_run:
            start = time.perf_counter()
            for cfg in configs:
                with Path(cfg['log']).open('ab') as out:
                    full, remainder = divmod(count - previous, 1000)
                    for _ in range(full):
                        out.write(line * 1000)
                    out.write(line * remainder)
                while store.scan(db, cfg)['backlog']:
                    pass
            seconds = time.perf_counter() - start
            actual = db.execute('SELECT count(*) FROM events').fetchone()[0]
            assert actual == count * opts.runs
            store.heartbeat(db, time.time(), 120)
            base = store.snapshot(db)
            def idle_poll():
                assert not store.detect_changes(db, base, base['last_event_id'])[1]
            result = dict(python=platform.python_version(), schema=store.SCHEMA, runs=opts.runs, events=actual,
                          ingest_events_s =round((count - previous) * opts.runs / seconds),
                          status_ms=median_ms(lambda: store.status(db)), wait_poll_ms=median_ms(idle_poll),
                          logs_MB=len(line) * actual / 1e6)
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            result['db_MB'] = (root / 'events.db').stat().st_size / 1e6
            print(json.dumps(result), flush=True)
            previous = count
