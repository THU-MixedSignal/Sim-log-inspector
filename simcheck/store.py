"""Incremental reader and SQLite evidence store (schema 4).

The database is a derived index of the source logs. The collector is its only
writer and works in bounded transactional ticks; every reader opens it
read-only. The output builders (status, show, evidence, wait, ...) return
compact dicts for agents: an absent key means false, none or zero, and
evidence IDs are the handles for drilling down. Nothing here judges circuits.
"""
import fnmatch
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path

from . import __version__, parser
from .integrity import fingerprint, inspect

SCHEMA = 4
API = 4
MAX_LINE = 65536
TICK_BYTES = 2 * 1024 * 1024
QUIET_AFTER_S = 1800
MAX_CHANGES = 20
ENDED = {'complete', 'failed', 'incomplete'}
RULE_FIELDS = {'name', 'code', 'key', 'severity', 'text', 'min_count'}
SEVERITY_SQL = ("CASE severity WHEN 'FATAL' THEN 0 WHEN 'ERROR' THEN 1 "
                "WHEN 'WARNING' THEN 2 WHEN 'NOTICE' THEN 3 ELSE 4 END")
SEV_LETTER = {'FATAL': 'E', 'ERROR': 'E', 'WARNING': 'W', 'NOTICE': 'N'}  # testbench groups: 'T'
SEV_ORDER = {'FATAL': 0, 'ERROR': 0, 'WARNING': 1, 'INFO': 2, 'NOTICE': 3}
CHECK_FIELDS = ('check', 'status', 'reported_status', 'exit_code', 'reason', 'analysis', 'last_status',
                'end_marker', 'last_saved_time_s', 'expected_stop_reached', 'size_bytes', 'detail', 'format')
DDL = (
    'CREATE TABLE runs(id TEXT PRIMARY KEY, config TEXT NOT NULL, cursor TEXT NOT NULL,'
    ' summary TEXT NOT NULL, updated REAL NOT NULL, rev INTEGER NOT NULL DEFAULT 0, input_stamp TEXT)',
    'CREATE TABLE events(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, generation INTEGER NOT NULL,'
    ' line INTEGER, byte_offset INTEGER, observed REAL NOT NULL, category TEXT, severity TEXT,'
    ' kind TEXT, code TEXT, stream TEXT NOT NULL, problem_key TEXT, sim_time REAL, payload TEXT NOT NULL)',
    'CREATE INDEX events_run ON events(run_id, generation, id)',
    "CREATE INDEX events_tb ON events(run_id, generation, id) WHERE category='testbench'",
    'CREATE TABLE groups(run_id TEXT, generation INTEGER, problem_key TEXT, severity TEXT,'
    ' printed_count INTEGER, first_evidence_id INTEGER, last_evidence_id INTEGER,'
    ' first_observed_epoch REAL, last_observed_epoch REAL,'
    ' PRIMARY KEY(run_id,generation,problem_key,severity)) WITHOUT ROWID',
    'CREATE TABLE sources(run_id TEXT,generation INTEGER,path TEXT,PRIMARY KEY(run_id,generation)) WITHOUT ROWID',
    'CREATE TABLE suppressed(run_id TEXT,generation INTEGER,problem_key TEXT,'
    ' PRIMARY KEY(run_id,generation,problem_key)) WITHOUT ROWID',
    'CREATE TABLE revision(seq INTEGER NOT NULL)',
    'INSERT INTO revision VALUES(0)',
    'CREATE TABLE collectors(pid INTEGER PRIMARY KEY, started REAL, heartbeat REAL, version TEXT,'
    ' interval REAL, port INTEGER, last_error TEXT)',
)


class SchemaError(RuntimeError):
    """The database file belongs to another schema version."""


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


# ---------------------------------------------------------------- manifest

def validate_rules(rules):
    if not isinstance(rules, list):
        raise ValueError('watch must be a list of rules')
    for rule in rules:
        if (not isinstance(rule, dict) or not rule.get('name') or set(rule) - RULE_FIELDS
                or not set(rule) & {'code', 'key', 'severity', 'text'}):
            raise ValueError('watch rule needs a name and at least one of code/key/severity/text: '
                             + json.dumps(rule, ensure_ascii=False))


def discover(root, base, cache):
    """One directory level. Periodically relist even if attributes look unchanged."""
    path = (base / root['root']).resolve()
    alias = root['alias']
    if not isinstance(alias, str) or not alias or '/' in alias or chr(92) in alias:
        raise ValueError('root alias must be a single nonempty name')
    templates = {k: root[k] for k in ('log', 'state', 'log_status', 'raw') if k in root}
    if 'log' not in templates or not all(isinstance(v, str) and v and not Path(v).anchor
                                          and '..' not in Path(v).parts for v in templates.values()):
        raise ValueError('root needs relative file paths within each run directory')
    stamp = path.stat().st_mtime_ns
    previous = cache.get(alias)
    now = time.monotonic()
    if previous and previous[:2] == (path, stamp) and now - previous[2] < 300:
        names = previous[3]
    else:
        with os.scandir(path) as entries:
            names = sorted(e.name for e in entries if e.is_dir(follow_symlinks=False))
        cache[alias] = (path, stamp, now, names)
    for name in names:
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in root.get('exclude', [])):
            continue
        config = {k: v for k, v in root.items() if k not in ('root', 'alias', 'exclude')}
        config.update({k: str(path / name / v) for k, v in templates.items()})
        yield dict(config, id=alias + '/' + name)


def manifest(path, cache=None):
    p = Path(path).resolve()
    data = json.loads(p.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or not ('runs' in data or 'roots' in data):
        raise ValueError('manifest needs runs or roots')
    explicit, roots = data.get('runs', []), data.get('roots', [])
    if not isinstance(explicit, list) or not isinstance(roots, list):
        raise ValueError('runs and roots must be lists')
    if cache is None:
        cache = {}
    runs_in = list(explicit)
    aliases = set()
    for root in roots:
        if not isinstance(root, dict) or not all(root.get(k) for k in ('alias', 'root', 'log')):
            raise ValueError('each root needs alias, root and log')
        if not all(isinstance(root[k], str) for k in ('alias', 'root', 'log')):
            raise ValueError('alias, root and log must be strings')
        if root['alias'] in aliases:
            raise ValueError('duplicate root alias')
        if not isinstance(root.get('exclude', []), list) or not all(isinstance(v, str) for v in root.get('exclude', [])):
            raise ValueError('exclude must be a list of name patterns')
        aliases.add(root['alias'])
        runs_in.extend(discover(root, p.parent, cache))
    for key in set(cache) - aliases:
        del cache[key]
    shared_rules = data.get('watch', [])
    validate_rules(shared_rules)
    ids = set()
    runs = []
    for index, run in enumerate(runs_in):
        if not isinstance(run, dict) or not isinstance(run.get('id'), str) or not run['id'] or run['id'] in ids:
            raise ValueError('Run IDs must be nonempty unique strings')
        ids.add(run['id'])
        config = dict(run)
        for key in ('log', 'state', 'log_status', 'raw'):
            if config.get(key):
                config[key] = (str((p.parent / config[key]).resolve()) if index < len(explicit)
                               else config[key])
        if not config.get('log'):
            raise ValueError('log path is required: ' + run['id'])
        validate_rules(run.get('watch', []))
        config['watch'] = list(shared_rules) + list(run.get('watch', []))
        config.setdefault('baseline', data.get('baseline'))
        config.setdefault('quiet_after_s', data.get('quiet_after_s', QUIET_AFTER_S))
        runs.append(config)
    for config in runs:
        if config['baseline'] == config['id']:
            config['baseline'] = None  # the reference run is not compared with itself
        elif config['baseline'] and config['baseline'] not in ids:
            raise ValueError('baseline is not a run in this manifest: ' + config['baseline'])
    data['runs'] = runs
    return data


# ---------------------------------------------------------------- database

def _schema(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    tables = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    return version, tables


def _schema_error(path, version):
    return SchemaError(f'{path} 由其他版本创建（schema {version or "1/2"}，当前需要 {SCHEMA}）。'
                       '数据库只是源日志的派生索引：请换一个新的 --db 路径重新采集，旧库保持不动。')


def network_fs(path):
    """Recognize Windows remote drives and known Linux network mount types."""
    if os.name == 'nt':
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4
    try:
        lines = Path('/proc/self/mountinfo').read_text(errors='replace').splitlines()
    except OSError:
        return False
    longest = -1
    kind = None
    for line in lines:
        left, _, right = line.partition(' - ')
        mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), left.split()[4])
        if len(mount) >= longest and path.is_relative_to(mount):
            longest, kind = len(mount), right.split()[0]
    return kind in {'nfs', 'nfs4', 'cifs', 'smb3', 'gpfs', 'lustre', 'ceph', 'fuse.sshfs'}


def connect(path):
    """Writer connection for collectors; creates schema 4 in a new database."""
    if network_fs(Path(path).resolve().parent):
        raise ValueError('SQLite WAL requires a database on a local filesystem: ' + str(path))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, factory=Connection)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    version, tables = _schema(db)
    if version == 0 and tables == 0:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('BEGIN IMMEDIATE')
        if _schema(db) == (0, 0):
            for statement in DDL:
                db.execute(statement)
            db.execute(f'PRAGMA user_version={SCHEMA}')
        db.commit()
        version, tables = _schema(db)
    if version != SCHEMA:
        db.close()
        raise _schema_error(path, version)
    return db


def open_readonly(path):
    """Reader connection; never creates or upgrades a database."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f'数据库不存在：{p}（先运行 run/watch/scan 采集）')
    db = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=5, factory=Connection)
    db.row_factory = sqlite3.Row
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version != SCHEMA:
        db.close()
        raise _schema_error(p, version)
    return db


# ---------------------------------------------------------------- collection

def stream_of(event):
    kind = event['kind']
    if kind == 'message_continuation':
        return 'continuation'
    if kind == 'suppression':
        return 'suppression'
    if event.get('problem_key'):
        return 'problem'
    if event['category'] == 'testbench':
        return 'measurement'
    return 'state'


def _empty_cursor(path):
    # file_generation: the generation that began reading the current file content;
    # later generations of the same file are attempts appended to it.
    return {'path': str(path), 'inode': None, 'generation': 0, 'file_generation': 0, 'offset': 0, 'line': 0,
            'prefix_len': 0, 'prefix_hash': '', 'anchor_hash': '', 'parser': parser.initial(),
            'dropping': False, 'limited': False}


def _replaced(cur, source, st, f):
    if (not cur or cur.get('path') != str(source) or cur.get('inode') != st.st_ino
            or st.st_size < cur['offset']):
        return True
    f.seek(0)
    if hashlib.sha256(f.read(cur['prefix_len'])).hexdigest() != cur['prefix_hash']:
        return True
    if cur['offset']:
        f.seek(max(0, cur['offset'] - 128))
        return hashlib.sha256(f.read(min(128, cur['offset']))).hexdigest() != cur['anchor_hash']
    return False


def _new_generation(cur, source, st):
    fresh = _empty_cursor(source)
    generation = cur['generation'] + 1 if cur else 1
    fresh.update(inode=st.st_ino, generation=generation, file_generation=generation,
                 prefix_hash=hashlib.sha256(b'').hexdigest(),
                 anchor_hash=hashlib.sha256(b'').hexdigest())
    return fresh


def _write_batch(db, batch, config, now):
    """Assign IDs under the writer lock and merge repeated groups once per batch."""
    first = db.execute('SELECT coalesce(max(id),0)+1 FROM events').fetchone()[0]
    groups = {}
    suppressed = set()
    sources = set()
    def rows():
        for eid, (gen, line, offset, event) in enumerate(batch, first):
            stream = stream_of(event)
            key = event.pop('problem_key', None)
            severity = event.pop('severity')
            kind = event.pop('kind')
            code = event.pop('code', None)
            event.pop('schema_version', None)
            body = event.get('message')
            if body and event['raw'].endswith(body):
                event['body_at'] = len(event['raw']) - len(event.pop('message'))
            group = (config['id'], gen, key, severity)
            if stream == 'problem':
                stats = groups.setdefault(group, [0, eid, eid])
                stats[0] += 1
                stats[2] = eid
            elif stream == 'suppression' and key:
                suppressed.add(group[:3])
            sources.add((config['id'], gen, config['log']))
            yield (eid, config['id'], gen, line, offset, now, event.pop('category'), severity, kind, code,
                   stream, key, event.pop('sim_time_s'), json.dumps(event, ensure_ascii=False, separators=(',', ':')))
    db.executemany('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows())
    db.executemany('INSERT OR IGNORE INTO sources VALUES(?,?,?)', sources)
    db.executemany('INSERT OR IGNORE INTO suppressed VALUES(?,?,?)', suppressed)
    db.executemany('INSERT INTO groups VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET '
                   'printed_count=printed_count+excluded.printed_count,last_evidence_id=excluded.last_evidence_id,'
                   'first_observed_epoch=min(first_observed_epoch,excluded.first_observed_epoch),'
                   'last_observed_epoch=max(last_observed_epoch,excluded.last_observed_epoch)',
                   ((*key, *stats, now, now) for key, stats in groups.items()))


EVENT_SELECT = ('SELECT e.*, s.path AS source_path FROM events e JOIN sources s USING(run_id,generation)')


def unpack(row):
    event = json.loads(row['payload'])
    if 'body_at' in event:
        event['message'] = event['raw'][event.pop('body_at'):]
    for key in ('source_path', 'run_id', 'generation', 'line', 'byte_offset', 'category', 'severity', 'kind'):
        event[key] = row[key]
    for key in ('problem_key', 'code'):
        if (row[key] is not None or (key, row['kind']) in
                {('code', 'native_message'), ('problem_key', 'suppression')}):
            event[key] = row[key]
    event.update(schema_version=parser.SCHEMA_VERSION, sim_time_s=row['sim_time'])
    return event


def _read(batch, f, cur, final):
    """Index complete lines from the cursor; True when a partial last line waits."""
    f.seek(cur['offset'])
    used = 0
    cur['retry_nul'] = False
    while used < TICK_BYTES and len(batch) < 2048:
        start = f.tell()
        chunk = f.readline(MAX_LINE + 1)
        if not chunk:
            return False
        if b'\0' in chunk:
            cur['retry_nul'] = True
            return True
        if cur['dropping']:
            used += len(chunk)
            cur['offset'] = f.tell()
            cur['dropping'] = not chunk.endswith(b'\n')
            continue
        oversized = len(chunk) > MAX_LINE
        if not chunk.endswith(b'\n') and not oversized and not final:
            parser.read_meter(chunk[:len(parser.METER)].decode('ascii', 'replace'), cur['parser'])
            return True
        used += len(chunk)
        cur['offset'] = f.tell()
        cur['line'] += 1
        if oversized:
            cur['limited'] = True
            cur['dropping'] = not chunk.endswith(b'\n')
            records = [dict(schema_version=parser.SCHEMA_VERSION, category='data_resources',
                            severity='WARNING', kind='line_size_limit',
                            analysis=cur['parser']['analysis'], sim_time_s=None,
                            raw=chunk[:512].decode('utf-8', 'replace'), problem_key='line_size_limit',
                            limitation='line exceeds 64KiB; remainder skipped')]
        else:
            if b'Spectre (R) Circuit Simulator' in chunk and cur['parser']['banner_seen']:
                cur['generation'] += 1
                cur['parser'] = parser.initial()
                cur['records'] = 0
                cur['limited'] = False
            records = parser.parse(chunk.decode('utf-8', 'replace'), cur['parser'], cur['line'])
        for event in records:
            if event['category'] == 'testbench':
                cur['records'] = cur.get('records', 0) + 1
            batch.append((cur['generation'], cur['line'], start, event))
    return False


def scan(db, config, final=False, sidecars=None):
    try:
        return _scan(db, config, final, sidecars)
    except Exception:
        db.rollback()
        raise


def _scan(db, config, final, sidecars):
    """One bounded, transactional indexing step for one run."""
    now = time.time()
    batch = []
    row = db.execute('SELECT * FROM runs WHERE id=?', (config['id'],)).fetchone()
    encoded_config = json.dumps(config, ensure_ascii=False)
    stamp = None
    # Watch has already gated due work in memory. A standalone scan can use the
    # last committed fingerprint too, including when it runs in a new process.
    if sidecars is None:
        stamp = json.dumps([final] + [fingerprint(config[k]) for k in ('log', 'state', 'log_status', 'raw')
                                     if config.get(k)])
        if (row and row['input_stamp'] == stamp and row['config'] == encoded_config
                and 0 <= now - row['updated'] < 300):
            cur = json.loads(row['cursor'])
            return dict(json.loads(row['summary']), run_id=config['id'], generation=cur['generation'],
                        parser=cur['parser'], retry_nul=False)
    cur = json.loads(row['cursor']) if row else None
    source = Path(config['log'])
    try:
        with source.open('rb') as f:
            st = os.fstat(f.fileno())
            if _replaced(cur, source, st, f):
                cur = _new_generation(cur, source, st)
            pending = _read(batch, f, cur, final)
            st = os.fstat(f.fileno())
            if st.st_size < cur['offset']:
                raise OSError('source truncated during read; retrying')
            # Pending bytes may change in place before the writer finishes the line.
            prefix_len = min(cur['offset'], 4096)
            if prefix_len > cur['prefix_len']:
                f.seek(0)
                cur['prefix_hash'] = hashlib.sha256(f.read(prefix_len)).hexdigest()
                cur['prefix_len'] = prefix_len
            f.seek(max(0, cur['offset'] - 128))
            cur['anchor_hash'] = hashlib.sha256(f.read(min(128, cur['offset']))).hexdigest()
        integrity = inspect(config, cur['parser'], pending or cur['dropping'], sidecars)
        if cur.get('limited') or cur['parser'].get('context_limited'):
            integrity['coverage_limited'] = ('oversized_line_skipped' if cur.get('limited')
                                             else 'parser_context_limit')
            if integrity['status'] == 'complete':
                integrity['status'] = 'incomplete'
        backlog = cur['offset'] < st.st_size and not pending
        if backlog and integrity['status'] == 'complete':
            integrity['status'] = 'indexing'
        summary = {'source_path': str(source), 'source_bytes': st.st_size,
                   'source_mtime_epoch': st.st_mtime, 'indexed_bytes': cur['offset'],
                   'backlog': backlog, 'integrity': integrity, 'observed_epoch': now, 'error': None}
    except OSError as e:
        batch.clear()
        cur = json.loads(row['cursor']) if row else None
        cur = cur or _empty_cursor(source)
        # Managed queued/rejected jobs may never create a Spectre log. The
        # explicitly bound state remains evidence even when that file is absent.
        integrity = inspect(config, cur['parser'], False, sidecars)
        if integrity['status'] == 'complete':
            integrity['status'] = 'incomplete'
        not_started = (isinstance(e, FileNotFoundError) and cur['offset'] == 0
                       and integrity['native_status'] == 'unknown'
                       and integrity['execution_status'] in ('queued', 'submitted', 'waiting', 'starting'))
        summary = {'source_path': str(source), 'integrity': integrity,
                   'backlog': False, 'observed_epoch': now, 'error': None if not_started else str(e)}
    db.execute('BEGIN IMMEDIATE')
    prior = db.execute('SELECT rev FROM runs WHERE id=?', (config['id'],)).fetchone()
    if (prior[0] if prior else None) != (row['rev'] if row else None):
        db.rollback()
        raise RuntimeError('concurrent scan: cursor advanced during read')
    if batch:
        _write_batch(db, batch, config, now)
    db.execute('UPDATE revision SET seq=seq+1')
    if (summary.get('error') or summary['backlog'] or cur.get('retry_nul')
            or any(c['status'] == 'unavailable' for c in integrity['checks'])):
        stamp = None
    db.execute('INSERT OR REPLACE INTO runs(id,config,cursor,summary,updated,input_stamp,rev) '
               'VALUES(?,?,?,?,?,?,(SELECT seq FROM revision))',
               (config['id'], encoded_config, json.dumps(cur, ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False), now, stamp))
    db.commit()
    return dict(summary, run_id=config['id'], generation=cur['generation'], parser=cur['parser'],
                retry_nul=cur.get('retry_nul', False))


def record_error(db, config, exc):
    """Keep a failing run visible instead of silently freezing its data."""
    now = time.time()
    message = f'{type(exc).__name__}: {exc}'[:500]
    db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT summary FROM runs WHERE id=?', (config['id'],)).fetchone()
    if row:
        summary = json.loads(row['summary'])
        summary.update(collector_error=message, collector_error_epoch=now)
        db.execute('UPDATE runs SET summary=?, updated=?, input_stamp=NULL WHERE id=?',
                   (json.dumps(summary, ensure_ascii=False), now, config['id']))
    else:
        summary = {'source_path': config['log'], 'integrity': {'status': 'unknown', 'checks': []},
                   'backlog': False, 'observed_epoch': None, 'error': None,
                   'collector_error': message, 'collector_error_epoch': now}
        db.execute('INSERT INTO runs(id,config,cursor,summary,updated) VALUES(?,?,?,?,?)',
                   (config['id'], json.dumps(config, ensure_ascii=False),
                    json.dumps(_empty_cursor(config['log'])), json.dumps(summary, ensure_ascii=False), now))
    db.execute('UPDATE revision SET seq=seq+1')
    db.execute('UPDATE runs SET rev=(SELECT seq FROM revision) WHERE id=?', (config['id'],))
    db.commit()
    return message


def collect(db, configs, final=False):
    """One collector tick over all runs; one failing run never blocks the others."""
    results = {}
    for config in configs:
        try:
            results[config['id']] = scan(db, config, final)
        except Exception as exc:  # isolate any per-run failure and record it
            db.rollback()
            results[config['id']] = {'collector_error': record_error(db, config, exc), 'backlog': False}
    return results


def heartbeat(db, started, interval, port=None, error=None):
    db.execute('INSERT INTO collectors(pid,started,heartbeat,version,interval,port,last_error)'
               ' VALUES(?,?,?,?,?,?,?) ON CONFLICT(pid) DO UPDATE SET started=excluded.started,'
               ' heartbeat=excluded.heartbeat, version=excluded.version, interval=excluded.interval,'
               ' port=excluded.port, last_error=excluded.last_error',
               (os.getpid(), started, time.time(), __version__, interval, port, error))
    db.commit()


def retire(db):
    db.execute('DELETE FROM collectors WHERE pid=?', (os.getpid(),))
    db.commit()


# ---------------------------------------------------------------- reading

def current_generation(db, run):
    row = db.execute('SELECT cursor FROM runs WHERE id=?', (run,)).fetchone()
    return json.loads(row[0])['generation'] if row else 0


def _row(db, run):
    return db.execute('SELECT id, config, cursor, summary FROM runs WHERE id=?', (run,)).fetchone()


def collector_status(db, now=None):
    now = time.time() if now is None else now
    row = db.execute('SELECT * FROM collectors ORDER BY heartbeat DESC LIMIT 1').fetchone()
    if not row:
        return {'alive': False, 'heartbeat_age_s': None, 'pid': None, 'version': None,
                'interval_s': None, 'port': None, 'started_epoch': None, 'last_error': None}
    age = max(0.0, now - row['heartbeat'])
    return {'alive': age <= max(10.0, 3 * (row['interval'] or 2) + 5),
            'heartbeat_age_s': round(age, 1), 'pid': row['pid'], 'version': row['version'],
            'interval_s': row['interval'], 'port': row['port'], 'started_epoch': row['started'],
            'last_error': row['last_error']}


def short(text, limit=200):
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    cut = text.rfind(' ', 0, limit)
    return text[:cut if cut > limit // 2 else limit] + '…'


def _summary_text(event):
    if event['kind'] in ('record', 'raw_record'):
        if event.get('parse_issue'):
            return f"{event['parse_issue']}: {short(event['raw'], 160)}"
        if event.get('reported_valid') == 0:
            return f"frame {event.get('frame')}, code {event.get('code_value')}: reported_valid=0"
        return short(event['raw'])
    return short(event.get('message') or event['raw'])


def problem_groups(db, run, generation=None, after=0, limit=50, new_only=False):
    """Printed messages grouped by key and native severity; never estimates of suppressed counts."""
    generation = current_generation(db, run) if generation is None else int(generation)
    args = (run, generation, int(after), min(max(int(limit), 1), 500))
    if after and not new_only:
        rows = db.execute(
            'SELECT problem_key, severity, count(*) AS printed_count, min(id) AS first_evidence_id,'
            ' max(id) AS last_evidence_id, min(observed) AS first_observed_epoch,'
            ' max(observed) AS last_observed_epoch FROM events INDEXED BY events_run'
            " WHERE run_id=? AND generation=? AND stream='problem' AND id>?"
            f' GROUP BY problem_key, severity ORDER BY {SEVERITY_SQL}, first_evidence_id LIMIT ?',
            args).fetchall()
    else:
        rows = db.execute('SELECT problem_key,severity,printed_count,first_evidence_id,last_evidence_id,'
                          'first_observed_epoch,last_observed_epoch FROM groups WHERE run_id=? AND generation=?'
                          f' AND first_evidence_id>? ORDER BY {SEVERITY_SQL},first_evidence_id LIMIT ?', args)
    suppressed = {r[0] for r in db.execute(
        'SELECT problem_key FROM suppressed WHERE run_id=? AND generation=?', (run, generation))}
    groups = []
    for row in rows:
        event = unpack(db.execute(EVENT_SELECT + ' WHERE id=?', (row['first_evidence_id'],)).fetchone())
        first_time = event.get('sim_time_s')
        stop = event.get('analysis_stop_s')
        groups.append(dict(row) | {
            'code': event.get('code'), 'category': event['category'],
            'phase': event.get('analysis') or 'setup', 'first_sim_time_s': first_time,
            'analysis_stop_s': stop,
            'first_fraction': first_time / stop if first_time is not None and stop else None,
            'suppressed_after': row['problem_key'] in suppressed,
            'severity_source': event.get('severity_source'),
            'summary': _summary_text(event), 'message': short(event.get('message') or event['raw'], 400)})
    return groups


def _rule_matches(rule, group):
    if 'code' in rule and not fnmatch.fnmatchcase(group.get('code') or '', rule['code']):
        return False
    if 'key' in rule and not fnmatch.fnmatchcase(group['problem_key'], rule['key']):
        return False
    if 'severity' in rule:
        allowed = rule['severity'] if isinstance(rule['severity'], list) else [rule['severity']]
        if group['severity'] not in allowed:
            return False
    if 'text' in rule and rule['text'].casefold() not in (group.get('message') or '').casefold():
        return False
    return group['printed_count'] >= int(rule.get('min_count', 1))


def rule_hits(rules, groups):
    """User-defined watch rules matched against printed groups. The rule is the user's policy."""
    return [{'rule': rule['name'], 'problem_key': g['problem_key'], 'severity': g['severity'],
             'printed_count': g['printed_count'], 'first_evidence_id': g['first_evidence_id'],
             'first_sim_time_s': g['first_sim_time_s'], 'first_fraction': g['first_fraction']}
            for rule in rules for g in groups if _rule_matches(rule, g)]


def _digest(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _keys(groups):
    return {(g['problem_key'], g['severity']) for g in groups}


def _run_state(db, row, now):
    """Everything known about one run; the compact outputs below are derived from it."""
    config = json.loads(row['config'])
    cur = json.loads(row['cursor'])
    stored = json.loads(row['summary'])
    p = cur['parser']
    gen = cur['generation']
    integrity = stored.get('integrity') or {'status': 'unknown'}
    status = integrity.get('status', 'unknown')
    groups = problem_groups(db, row['id'], gen, limit=500)
    by_severity = {}
    group_count = printed = last_problem = 0
    for r in db.execute("SELECT severity, sum(printed_count) AS n, count(*) AS g, max(last_evidence_id) AS last"
                        " FROM groups WHERE run_id=? AND generation=?"
                        ' GROUP BY severity', (row['id'], gen)):
        by_severity[r['severity']] = r['n']
        printed += r['n']
        group_count += r['g']
        last_problem = max(last_problem, r['last'])
    records = cur.get('records', 0)
    last_event = db.execute('SELECT max(id) FROM events WHERE run_id=? AND generation=?',
                            (row['id'], gen)).fetchone()[0] or 0
    ended = status in ENDED or integrity.get('native_status', 'unknown') != 'unknown'
    mtime = stored.get('source_mtime_epoch')
    quiet_for = None if mtime is None else round(max(0.0, now - mtime), 1)
    quiet_after = config.get('quiet_after_s', QUIET_AFTER_S)
    hits = rule_hits(config.get('watch', []), groups)
    attention = []
    if status == 'failed':
        attention.append('failed')
    if hits:
        attention.append('rule')
    if not ended and quiet_for is not None and quiet_after and quiet_for > quiet_after:
        attention.append('quiet')
    if stored.get('collector_error'):
        attention.append('collector_error')
    if stored.get('error'):
        attention.append('source_error')
    analysis = p.get('analysis')
    stop = (p.get('analyses', {}).get(analysis) or {}).get('stop_time_s')
    last_time = p.get('last_time_s')
    limitations = [c['check'] + ':' + c['status'] for c in integrity.get('checks', [])
                   if c['status'] in ('not_checked', 'unavailable', 'unsupported', 'unknown')]
    if integrity.get('coverage_limited'):
        limitations.append(integrity['coverage_limited'])
    if integrity.get('pending_partial_line'):
        limitations.append('pending_partial_line')
    run = {
        'run_id': row['id'], 'generation': gen, 'log': config['log'], 'baseline_ref': config.get('baseline'),
        'state': {'status': status, 'ended': ended, 'analysis': analysis,
                  'last_logged_time_s': last_time, 'stop_time_s': stop,
                  'progress_at_least': last_time / stop if last_time is not None and stop else None,
                  'meter_cells': p.get('meter'),
                  'observed_epoch': stored.get('observed_epoch'), 'source_mtime_epoch': mtime,
                  'quiet_for_s': quiet_for, 'quiet_after_s': quiet_after,
                  'backlog': bool(stored.get('backlog')),
                  'index_complete': not stored.get('backlog') and not integrity.get('pending_partial_line')
                  and not stored.get('error'),
                  'error': stored.get('error'), 'collector_error': stored.get('collector_error'),
                  'collector_error_epoch': stored.get('collector_error_epoch')},
        'attention': attention,
        'problems': {'printed_count': printed, 'group_count': group_count, 'by_severity': by_severity,
                     'last_problem_id': last_problem},
        'groups': groups,
        'rule_hits': hits,
        'baseline': None,
        # records: every testbench line; frames: R4MEAS records the parser could read.
        'measurements': {'records': records, 'frames': p.get('frames', 0), 'last_frame': p.get('last_frame'),
                         'last_code': p.get('last_code')},
        'coverage': {'suppression_seen': p.get('suppression_seen', False),
                     'suppressed_totals': p.get('suppressed_totals', {}), 'limitations': limitations},
        'last_event_id': last_event}
    run['token'] = _digest(gen, status, ended, attention, sorted((h['rule'], h['problem_key']) for h in hits))
    return run


def snapshot(db, now=None, previous=None):
    """Internal view of every run, with baseline differences; status and wait derive from it."""
    owned = not db.in_transaction
    if owned:
        db.execute('BEGIN')
    try:
        return _snapshot(db, time.time() if now is None else now, previous)
    finally:
        if owned:
            db.rollback()


def _snapshot(db, now, previous):
    seq = db.execute('SELECT seq FROM revision').fetchone()[0]
    collector = collector_status(db, now)
    if previous and previous['seq'] == seq and now < previous['quiet_deadline']:
        if previous['collector']['alive'] == collector['alive']:
            return dict(previous, generated_epoch=now, collector=collector)
    cached = {r['run_id']: r for r in previous['runs']} if previous else {}
    runs = []
    deadlines = []
    for ident, revision in db.execute('SELECT id,rev FROM runs ORDER BY id'):
        old = cached.get(ident)
        if old and old['rev'] == revision and now < old['quiet_deadline']:
            run = dict(old)
        else:
            run = _run_state(db, _row(db, ident), now)
            run['rev'] = revision
        state = run['state']
        deadline = math.inf
        if (not state['ended'] and state['source_mtime_epoch'] is not None
                and state['quiet_after_s'] and 'quiet' not in run['attention']):
            deadline = state['source_mtime_epoch'] + state['quiet_after_s']
        run['quiet_deadline'] = deadline
        deadlines.append(deadline)
        runs.append(run)
    by_id = {r['run_id']: r for r in runs}
    for run in runs:
        ref = by_id.get(run['baseline_ref'])
        if ref:
            missing = _keys(run['groups']) - _keys(ref['groups'])
            run['baseline'] = {'run_id': ref['run_id'], 'status': ref['state']['status'],
                               'keys_not_in_baseline': [{'problem_key': k, 'severity': s}
                                                        for k, s in sorted(missing)]}
    last_event = db.execute('SELECT max(id) FROM events').fetchone()[0] or 0
    return {'seq': seq, 'quiet_deadline': min(deadlines, default=math.inf), 'version': __version__, 'generated_epoch': now, 'collector': collector,
            'last_event_id': last_event, 'token': _digest([r['token'] for r in runs], collector['alive']),
            'runs': runs}


# ---------------------------------------------------------------- compact output (API 4)

def _compact(d):
    return {k: v for k, v in d.items()
            if not (v is None or v is False or (isinstance(v, (str, list, dict)) and not v))}


def pct(fraction):
    return None if fraction is None else round(100 * fraction, 4)


def sig(seconds):
    """Times to the six significant digits Spectre prints, without float noise."""
    return None if seconds is None else float(f'{seconds:.6g}')


def cursor_of(snap):
    return f"{snap['last_event_id']}.{snap['token']}"


def parse_cursor(text):
    head, _, token = (text or '').partition('.')
    if not head.isdigit():
        raise ValueError(f'cursor must look like 3762.2330795c9a33 (from status or wait): {text}')
    return int(head), token or None


def evidence_id(text):
    """Evidence handles are written e123; a bare 123 is accepted too."""
    value = str(text).strip()
    digits = value[1:] if value[:1] in ('e', 'E') else value
    if not digits.isdigit():
        raise ValueError(f'evidence id must look like e123: {text}')
    return int(digits)


def brief(group, width=160):
    return _compact({'e': group['first_evidence_id'], 'sev': group['severity'], 'key': group['problem_key'],
                     'n': group['printed_count'], 'sup': group['suppressed_after'],
                     't': sig(group['first_sim_time_s']), 'pct': pct(group['first_fraction']),
                     'msg': short(group['summary'], width)})


def collector_brief(c):
    return {'live': c['alive'], **_compact({'hb': c['heartbeat_age_s'], 'pid': c['pid'],
                                            'version': c['version'], 'error': c['last_error']})}


def _progress(state):
    # How far the simulation got matters until it finished normally; then the footer says enough.
    if state['status'] == 'complete':
        return {}
    share = pct(state['progress_at_least'])
    cells = state['meter_cells']
    meter = round(100 * cells / len(parser.METER), 1) if cells else None
    out = {'t': sig(state['last_logged_time_s']), 'pct': share}
    # Between messages Spectre's meter runs ahead of the last logged time; give it when it says more.
    if meter is not None and (share is None or meter > share):
        out['meter'] = meter
    return out


def _rules(hits):
    """One entry per rule: first five keys and the earliest hit."""
    out = {}
    for h in hits:
        r = out.setdefault(h['rule'], {'rule': h['rule'], 'keys': [], 'n': 0, 'e': h['first_evidence_id'],
                                       't': h['first_sim_time_s'], 'pct': pct(h['first_fraction'])})
        r['n'] += 1
        if len(r['keys']) < 5:
            r['keys'].append(h['problem_key'])
        if h['first_evidence_id'] < r['e']:
            r.update(e=h['first_evidence_id'], t=h['first_sim_time_s'], pct=pct(h['first_fraction']))
    for r in out.values():
        r['t'] = sig(r['t'])
    for r in out.values():
        if r['n'] == len(r['keys']):
            r['n'] = None
    return [_compact(r) for r in out.values()]


def _counts(groups):
    counts = {}
    for g in groups:
        letter = SEV_LETTER.get(g['severity'], 'T')
        counts[letter] = counts.get(letter, 0) + 1
    return counts


def _digest_run(run):
    st = run['state']
    errors = sorted((g for g in run['groups'] if g['severity'] in ('FATAL', 'ERROR')),
                    key=lambda g: g['first_evidence_id'])
    m = run['measurements']
    frames = None
    if m['records']:
        frames = _compact({'n': m['frames'], 'other': max(0, m['records'] - m['frames']) or None,
                           'frame': m['last_frame'], 'code': m['last_code']})
    base = None
    if run['baseline']:
        new = [k['problem_key'] for k in run['baseline']['keys_not_in_baseline'] if k['severity'] != 'NOTICE']
        if new:
            base = _compact({'ref': run['baseline']['run_id'], 'new': new[:5],
                             'n': len(new) if len(new) > 5 else None})
    return _compact({
        'run': run['run_id'], 'state': st['status'], 'ended': st['ended'], 'flags': run['attention'],
        'analysis': st['analysis'], 'stop': sig(st['stop_time_s']), **_progress(st),
        'n': _counts(run['groups']), 'errors': [brief(g, 120) for g in errors[:2]],
        'rules': _rules(run['rule_hits']), 'base': base, 'frames': frames,
        'log_age': None if st['ended'] or st['quiet_for_s'] is None else round(st['quiet_for_s']),
        'error': st['collector_error'] or st['error'],
        'gen': run['generation'] if run['generation'] > 1 else None,
        'last_problem': run['problems']['last_problem_id'] or None})


def _urgency(run):
    flags = run['attention']
    rank = 0 if 'failed' in flags or 'rule' in flags else 1 if flags else 2
    # Running runs before ended ones: stopping those is what saves simulation time.
    return rank, run['state']['ended'], 'failed' not in flags, run['run_id']


def digest(snap, run_ids=None):
    runs = sorted((r for r in snap['runs'] if not run_ids or r['run_id'] in run_ids), key=_urgency)
    return {'v': API, 'version': snap['version'], 'cursor': cursor_of(snap),
            'collector': collector_brief(snap['collector']), 'runs': [_digest_run(r) for r in runs]}


def status(db, run_ids=None):
    snap = snapshot(db)
    unknown = set(run_ids or ()) - {r['run_id'] for r in snap['runs']}
    if unknown:
        raise LookupError('unknown run: ' + ', '.join(sorted(unknown)))
    return digest(snap, run_ids)


def _key_set(db, run):
    gen = current_generation(db, run)
    return {(r[0], r[1]) for r in db.execute(
        "SELECT problem_key, severity FROM groups WHERE run_id=? AND generation=?",
        (run, gen))}


def show(db, run, full=False, limit=30, now=None):
    """One run's problem groups, most severe first. NOTICE groups appear when a rule names them
    or with full; full also lifts the line limit."""
    row = _row(db, run)
    if row is None:
        return None
    r = _run_state(db, row, time.time() if now is None else now)
    ref = r['baseline_ref']
    ref_keys = _key_set(db, ref) if ref and _row(db, ref) else None
    rules = {}
    for h in r['rule_hits']:
        rules.setdefault((h['problem_key'], h['severity']), []).append(h['rule'])
    ordered = sorted(r['groups'], key=lambda g: (SEV_ORDER.get(g['severity'], 2), g['phase'] == 'setup',
                                                 g['first_evidence_id']))
    groups, hidden = [], 0
    for g in ordered:
        key = (g['problem_key'], g['severity'])
        if not full and g['severity'] == 'NOTICE' and key not in rules:
            hidden += 1
            continue
        groups.append({**brief(g, 160), **_compact({
            'last': g['last_evidence_id'] if g['last_evidence_id'] != g['first_evidence_id'] else None,
            'phase': g['phase'], 'rules': rules.get(key),
            'base_new': ref_keys is not None and g['severity'] != 'NOTICE' and key not in ref_keys})})
    st = r['state']
    more = 0 if full else max(0, len(groups) - int(limit))
    out = _compact({'v': API, 'run': run, 'state': st['status'], 'ended': st['ended'], 'flags': r['attention'],
                    'analysis': st['analysis'], 'stop': sig(st['stop_time_s']), **_progress(st),
                    'log_age': None if st['ended'] or st['quiet_for_s'] is None else round(st['quiet_for_s']),
                    'log': r['log'], 'baseline': ref if ref_keys is not None else None,
                    'hidden_notices': hidden or None, 'more': more or None})
    out['groups'] = groups if full else groups[:int(limit)]
    return out


def measurements(db, run, after=0, limit=50, generation=None, before=None, tail=None):
    """Testbench records in log order; tail/before page backwards from the newest."""
    generation = current_generation(db, run) if generation is None else int(generation)
    limit = min(max(int(tail or limit), 1), 500)
    base = ("SELECT id, payload FROM events WHERE run_id=? AND generation=?"
            " AND category='testbench'")
    if tail:
        rows = db.execute(base + ' ORDER BY id DESC LIMIT ?', (run, generation, limit)).fetchall()[::-1]
    elif before is not None:
        rows = db.execute(base + ' AND id<? ORDER BY id DESC LIMIT ?',
                          (run, generation, int(before), limit)).fetchall()[::-1]
    else:
        rows = db.execute(base + ' AND id>? ORDER BY id LIMIT ?',
                          (run, generation, int(after), limit)).fetchall()
    out = []
    for row in rows:
        event = json.loads(row['payload'])
        out.append(_compact({'e': row['id'], 'frame': event.get('frame'), 'code': event.get('code_value'),
                             'valid': event.get('reported_valid'), 'issue': event.get('parse_issue'),
                             'raw': None if 'frame' in event else short(event['raw'], 120)}))
    return out


def measurement_page(db, run, after=0, limit=20, before=None, tail=None):
    """Newest records by default; older/newer say whether paging further finds more."""
    if _row(db, run) is None:
        return None
    gen = current_generation(db, run)
    if before is None and not after and not tail:
        tail = limit
    rows = measurements(db, run, after or 0, limit, gen, before, tail)
    probe = "SELECT 1 FROM events WHERE run_id=? AND generation=? AND category='testbench' AND id{}? LIMIT 1"
    older = bool(rows) and db.execute(probe.format('<'), (run, gen, rows[0]['e'])).fetchone() is not None
    newer = bool(rows) and db.execute(probe.format('>'), (run, gen, rows[-1]['e'])).fetchone() is not None
    total = json.loads(_row(db, run)['cursor']).get('records', 0)
    out = _compact({'v': API, 'run': run, 'total': total, 'older': older, 'newer': newer})
    out['rows'] = rows
    return out


def evidence(db, event_id):
    """One evidence record with its header, continuation and suppression lines and its group."""
    row = db.execute(EVENT_SELECT + ' WHERE id=?',
                     (int(event_id),)).fetchone()
    if not row:
        return None
    event = unpack(row)
    run, gen = event['run_id'], event['generation']
    current = db.execute('SELECT cursor FROM runs WHERE id=?', (run,)).fetchone()
    current = json.loads(current[0]) if current else {}
    latest = current.get('generation', gen)
    # A later generation either appended an attempt to the same file (path:line still holds)
    # or replaced the file, so path:line now points into other content. Cursors written
    # before file_generation existed cannot tell the two apart: treat them as replaced.
    replaced = gen < latest and gen < current.get('file_generation', latest)
    # Continuation and suppression lines directly follow their message in the same block.
    scope = (run, gen, row['id'], row['id'] + 200)
    related = ("SELECT line, payload FROM events WHERE run_id=? AND generation=? AND id>? AND id<=?"
               " AND stream=? AND json_extract(payload, '$.related_message_line')=? ORDER BY id LIMIT ?")
    cont = [{'line': r['line'], 'raw': json.loads(r['payload'])['raw']}
            for r in db.execute(related, scope + ('continuation', event['line'], 21))]
    suppression = db.execute(related, scope + ('suppression', event['line'], 1)).fetchone()
    group = None
    if row['stream'] == 'problem':
        g = db.execute("SELECT printed_count AS n, first_evidence_id AS first, last_evidence_id AS last FROM groups WHERE run_id=?"
                       " AND generation=? AND problem_key=? AND severity=?",
                       (run, gen, row['problem_key'], row['severity'])).fetchone()
        later = db.execute("SELECT 1 FROM suppressed WHERE run_id=? AND generation=?"
                           ' AND problem_key=? LIMIT 1', (run, gen, row['problem_key'])).fetchone()
        group = _compact({'n': g['n'], 'sup': later is not None, 'first': g['first'], 'last': g['last']})
    t, stop = event.get('sim_time_s'), event.get('analysis_stop_s')
    out = _compact({
        'v': API, 'e': row['id'], 'run': run, 'gen': gen if gen > 1 or gen < latest else None,
        'latest_gen': latest if gen < latest else None, 'replaced': replaced,
        'path': event['source_path'], 'line': event['line'], 'off': event['byte_offset'],
        'sev': row['severity'] if row['stream'] == 'problem' else None, 'key': row['problem_key'],
        't': sig(t), 'pct': pct(t / stop) if t is not None and stop else None,
        'frame': event.get('frame'), 'code': event.get('code_value'), 'valid': event.get('reported_valid'),
        'issue': event.get('parse_issue'), 'limitation': event.get('limitation'), 'group': group,
        'seen': round(row['observed'], 1),
        'header': {'line': event['header_line'], 'raw': event['header_raw']} if event.get('header_line') else None})
    out['raw'] = event['raw']
    out.update(_compact({'cont': cont[:20], 'cont_more': len(cont) > 20,
                         'suppression': {'line': suppression['line'],
                                         'raw': json.loads(suppression['payload'])['raw']} if suppression else None}))
    return out


def _number(text):
    q = parser.quantity(text)
    if q:
        return q['value_si']
    m = re.match(r'\s*(' + parser.NUMBER + r')', text)
    return float(m[1]) if m else None


def same_value(a, b):
    x, y = _number(a), _number(b)
    if x is not None and y is not None:
        return math.isclose(x, y, rel_tol=1e-9, abs_tol=0.0)
    return a.strip().casefold() == b.strip().casefold()


def settings_table(settings):
    """Requested (user options) and effective (analysis report) values side by side."""
    rows = {}
    for item_key, item in settings.items():
        analysis, scope, name = item_key.rsplit(':', 2)
        row = rows.setdefault(name, {'name': name, 'requested': None, 'requested_default': None,
                                     'effective': []})
        if scope == 'requested':
            row['requested'] = item['value']
            row['requested_default'] = item.get('default_text')
        else:
            row['effective'].append({'analysis': None if analysis == 'None' else analysis,
                                     'value': item['value'], 'default': item.get('default_text')})
    for row in rows.values():
        row['differs'] = row['requested'] is not None and any(
            not same_value(row['requested'], e['value']) for e in row['effective'])
    return list(rows.values())


def _settings(settings):
    out = []
    for row in settings_table(settings):
        effective = row['effective']
        eff = '; '.join(f"{e['analysis']}={e['value']}" if len(effective) > 1 and e['analysis'] else e['value']
                        for e in effective)
        defaults = [d for d in [row['requested_default']] + [e['default'] for e in effective] if d]
        out.append(_compact({'name': row['name'], 'req': row['requested'], 'eff': eff,
                             'def': defaults[0] if defaults else None, 'diff': row['differs']}))
    return out


def details(db, run):
    """Completion checks and requested vs effective settings of one run."""
    row = db.execute('SELECT cursor, summary FROM runs WHERE id=?', (run,)).fetchone()
    if not row:
        return None
    stored = json.loads(row['summary'])
    p = json.loads(row['cursor'])['parser']
    integrity = stored.get('integrity') or {}
    checks = [{k: c[k] for k in CHECK_FIELDS if c.get(k) is not None} for c in integrity.get('checks', [])]
    return _compact({
        'v': API, 'run': run, 'status': integrity.get('status'), 'log': stored.get('source_path'),
        'indexed': stored.get('indexed_bytes'), 'size': stored.get('source_bytes'),
        'spectre': p.get('version'),
        'stops': {name: sig(a['stop_time_s']) for name, a in p.get('analyses', {}).items()
                  if a.get('stop_time_s') is not None},
        'footer': p.get('footer'), 'suppressed': p.get('suppressed_totals'),
        'coverage': integrity.get('coverage_limited'), 'pending_line': integrity.get('pending_partial_line'),
        'checks': checks, 'settings': _settings(p.get('settings', {}))})


def events(db, run=None, after=0, limit=100, category=None, severity=None, generation=None):
    """Raw stored events for debugging and export."""
    clauses, args = ['id>?'], [int(after)]
    for key, value in (('run_id', run), ('category', category), ('severity', severity),
                       ('generation', generation)):
        if value is not None:
            clauses.append(key + '=?')
            args.append(value)
    args.append(min(max(int(limit), 1), 500))
    rows = db.execute(EVENT_SELECT + ' WHERE ' + ' AND '.join(clauses)
                      + ' ORDER BY id LIMIT ?', args)
    return [dict(unpack(r), event_id=r['id'], observed_epoch=r['observed']) for r in rows]


# ---------------------------------------------------------------- waiting

def detect_changes(db, base, after, run_ids=None, notices=False, repeats=False):
    owned = not db.in_transaction
    if owned:
        db.execute('BEGIN')
    try:
        return _changes(db, base, after, run_ids, notices, repeats)
    finally:
        if owned:
            db.rollback()


def _changes(db, base, after, run_ids, notices, repeats):
    """Typed differences between an earlier snapshot and now, plus problems after an evidence ID."""
    current = snapshot(db, previous=base)
    if (current['seq'] == base['seq'] and after >= current['last_event_id']
            and current['token'] == base['token']):
        return current, []
    old_runs = {r['run_id']: r for r in base['runs']}
    changes = []
    for run in current['runs']:
        rid = run['run_id']
        if run_ids and rid not in run_ids:
            continue
        old = old_runs.get(rid)
        if (old and old['rev'] == run['rev'] and old['token'] == run['token']
                and run['problems']['last_problem_id'] <= after):
            continue
        if old is None:
            changes.append({'type': 'run_added', 'run': rid})
        else:
            if old['generation'] != run['generation']:
                changes.append({'type': 'restart', 'run': rid, 'gen': run['generation']})
            if old['state']['status'] != run['state']['status']:
                changes.append({'type': 'status', 'run': rid, 'from': old['state']['status'],
                                'to': run['state']['status']})
            if 'quiet' in run['attention'] and 'quiet' not in old['attention']:
                changes.append({'type': 'quiet', 'run': rid, 'log_age': round(run['state']['quiet_for_s'] or 0)})
            for flag, field in (('collector_error', 'collector_error'), ('source_error', 'error')):
                if flag in run['attention'] and flag not in old['attention']:
                    changes.append({'type': flag, 'run': rid, 'error': run['state'][field]})
        seen = {r[0] for r in db.execute(
            "SELECT DISTINCT problem_key FROM groups WHERE run_id=? AND generation=?"
            ' AND first_evidence_id<=?', (rid, run['generation'], int(after)))}
        ruled = {h['problem_key'] for h in run['rule_hits']}
        new = {}
        for group in (problem_groups(db, rid, run['generation'], after=after, limit=500, new_only=not repeats)
                      if run['problems']['last_problem_id'] > after else ()):
            if group['problem_key'] not in seen:
                if notices or group['severity'] != 'NOTICE' or group['problem_key'] in ruled:
                    new[group['problem_key']] = {'type': 'new', 'run': rid, **brief(group)}
            elif repeats:
                changes.append({'type': 'more', 'run': rid, 'key': group['problem_key'],
                                'sev': group['severity'], 'n': group['printed_count'],
                                'last': group['last_evidence_id']})
        if old is not None:
            known = {(h['rule'], h['problem_key']) for h in old['rule_hits']}
            for h in run['rule_hits']:
                if (h['rule'], h['problem_key']) in known:
                    continue
                if h['problem_key'] in new:  # a new group that hits a rule: one line, not two
                    new[h['problem_key']].setdefault('rules', []).append(h['rule'])
                else:
                    changes.append(_compact({'type': 'rule', 'run': rid, 'rule': h['rule'],
                                             'key': h['problem_key'], 'e': h['first_evidence_id'],
                                             't': sig(h['first_sim_time_s']), 'pct': pct(h['first_fraction'])}))
        changes.extend(new.values())
    if base['collector']['alive'] and not current['collector']['alive']:
        changes.append(_compact({'type': 'collector_offline', 'hb': current['collector']['heartbeat_age_s']}))
    return current, changes


def wait_for_change(path, cursor=None, run_ids=None, timeout=3600.0, interval=2.0,
                    notices=False, repeats=False, clock=time.monotonic, sleep=time.sleep):
    """Block until something needs attention. Returns (result, exit_code): 0 change, 3 timeout,
    4 no live collector. Pass the returned cursor to the next call so nothing is missed between calls."""
    deadline = clock() + max(0.0, timeout)
    after, token = parse_cursor(cursor) if cursor else (None, None)
    with open_readonly(path) as db:
        base = snapshot(db)
    if after is None:
        after = base['last_event_id']
    if not base['collector']['alive']:
        return ({'v': API, 'changed': False, 'reason': 'collector_offline',
                 'collector': collector_brief(base['collector']), 'cursor': cursor_of(base)}, 4)
    first = True
    while True:
        with open_readonly(path) as db:
            current, changes = detect_changes(db, base, after, run_ids, notices, repeats)
        if first and token and token != base['token']:
            # Status-level state moved between the caller's cursor and this call.
            changes.insert(0, {'type': 'state_changed'})
        first = False
        if changes:
            out = {'v': API, 'changed': True, 'changes': changes[:MAX_CHANGES], 'cursor': cursor_of(current)}
            if len(changes) > MAX_CHANGES:
                out['more'] = len(changes) - MAX_CHANGES
            return out, 0
        if clock() >= deadline:
            return {'v': API, 'changed': False, 'reason': 'timeout', 'cursor': cursor_of(current)}, 3
        base, after = current, current['last_event_id']
        sleep(interval)
