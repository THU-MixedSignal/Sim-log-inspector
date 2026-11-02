"""Synthetic scaling measurement; no user logs or simulations modified."""
import json
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simcheck.store import connect,scan

rows=[]
for count in (5000,40000):
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);log=p/'spectre.out'
        line=b'    WARNING (SPECTRE-16780): LTE tolerance was temporarily relaxed.\n'
        with log.open('wb') as f:
            for _ in range(count):f.write(line)
        tracemalloc.start();start=time.perf_counter()
        with connect(p/'events.db') as db:
            config={'id':'bench','log':str(log)}
            while scan(db,config).get('backlog'):pass
            actual=db.execute('SELECT count(*) FROM events').fetchone()[0]
            assert actual==count
            before=time.perf_counter();scan(db,config);idle=time.perf_counter()-before
        elapsed=time.perf_counter()-start;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        rows.append(dict(bytes=log.stat().st_size,events=actual,seconds=elapsed,
                         python_heap_peak_bytes=peak,idle_poll_seconds=idle))
print(json.dumps({'scope':'synthetic local SQLite; tracemalloc Python heap, not OS RSS',
                  'measurements':rows},indent=2))
