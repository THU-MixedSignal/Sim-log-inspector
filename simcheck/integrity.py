"""Bounded sidecar inspection. Does not validate full waveforms."""
import json
import math
import os
import re
from pathlib import Path

LIMIT = 1024 * 1024
FAILED_STATES = {'failed', 'limit_exceeded', 'rejected', 'cancelled', 'killed'}
ACTIVE_STATES = {'running', 'starting', 'submitted', 'queued', 'waiting'}


def small(path):
    p = Path(path)
    with p.open('rb') as f:
        data = f.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('sidecar exceeds 1 MiB bound')
    return data.decode('utf-8', errors='replace')


def check_state(path):
    data = json.loads(small(path))
    if not isinstance(data, dict):
        raise ValueError('state JSON is not an object')
    check = {'check': 'state', 'status': 'observed', 'reported_status': data.get('status', 'unknown'),
             'exit_code': data.get('exit_code'), 'reason': data.get('reason'),
             'identity': 'user_bound_manifest_path'}
    return check


def check_log_status(path, target):
    statuses = {}
    for line in small(path).splitlines():
        cols = line.split('\t')
        if len(cols) >= 3:
            # A START/PASS/FAIL transition log: the latest line per analysis wins.
            statuses[cols[-2]] = cols[-1].strip()
    observed = statuses.get(target) if target else None
    return {'check': 'log_status', 'status': 'observed' if observed else 'unknown',
            'analysis': target, 'last_status': observed, 'all_analyses': statuses}


def check_raw(path, expected):
    p = Path(path)
    with p.open('rb') as f:
        size = os.fstat(f.fileno()).st_size
        head = f.read(4096)
        f.seek(max(0, size - 65536))
        tail = f.read(65536)
    if not head.startswith(b'HEADER'):
        return {'check': 'raw', 'status': 'unsupported', 'format': 'not_PSF_ASCII'}
    times = re.findall(rb'"time"\s+([+\-0-9.eE]+)', tail)
    last = float(times[-1]) if times else None
    ended = tail.rstrip().replace(b'\r\n', b'\n').endswith(b'\nEND')
    reached = None
    if expected is not None and last is not None:
        reached = math.isfinite(last) and last >= expected - max(1e-15, abs(expected) * 1e-9)
    return {'check': 'raw', 'status': 'observed', 'end_marker': ended, 'last_saved_time_s': last,
            'expected_stop_reached': reached, 'size_bytes': size,
            'coverage': 'header_and_64KiB_tail_only_not_full_waveform'}


def fingerprint(path):
    try:
        st = os.stat(path)
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    except OSError as exc:
        return ('unavailable', exc.errno)


def inspect(config, parser, pending=False, cache=None):
    checks = []
    native = 'unknown'
    if parser['fatal_seen'] or parser['native_errors'] or (parser['footer'] or {}).get('errors', 0):
        native = 'failed'
    elif parser['footer'] is not None:
        native = 'complete'
    execution = 'unknown'
    for key in ('state', 'log_status', 'raw'):
        if not config.get(key):
            checks.append({'check': key, 'status': 'not_checked'})
            continue
        try:
            stamp = (config[key], config.get('analysis'), config.get('expected_stop_s'),
                     fingerprint(config[key])) if cache is not None else None
            if cache is not None and key in cache and cache[key][0] == stamp:
                check = cache[key][1]
            elif key == 'state':
                check = check_state(config[key])
            elif key == 'log_status':
                check = check_log_status(config[key], config.get('analysis'))
            else:
                check = check_raw(config[key], config.get('expected_stop_s'))
            if cache is not None:
                cache[key] = (stamp, check)
            if key == 'state':
                execution = check['reported_status'] if check['exit_code'] in (None, 0) else 'failed'
        except (OSError, ValueError, TypeError) as e:
            check = {'check': key, 'status': 'unavailable', 'detail': str(e)}
        checks.append(check)
    state = 'failed' if execution in FAILED_STATES or native == 'failed' else 'unknown'
    if state != 'failed':
        bad_status = any(c.get('last_status') in ('FAIL', 'FAILED', 'ERROR') for c in checks)
        incomplete = any(c.get('end_marker') is False or c.get('expected_stop_reached') is False
                         or c['status'] in ('unavailable', 'unsupported') for c in checks)
        required_unknown = any(c['check'] == 'log_status' and c['status'] != 'not_checked'
                               and c.get('last_status') != 'PASS' for c in checks)
        incomplete |= any(c['check'] == 'raw' and config.get('raw') and config.get('expected_stop_s') is not None
                          and c.get('expected_stop_reached') is None for c in checks)
        if bad_status:
            state = 'failed'
        elif execution in ACTIVE_STATES:
            state = execution
        elif native == 'complete':
            state = 'incomplete' if incomplete or pending or required_unknown else 'complete'
        elif execution == 'complete':
            state = 'incomplete'
    return {'status': state, 'native_status': native, 'execution_status': execution,
            'checks': checks, 'electrical_verdict': 'not_inferred',
            'code_verdict': 'not_inferred', 'pending_partial_line': pending,
            'limitation': 'Completion of observed sources only; no circuit qualification.'}
