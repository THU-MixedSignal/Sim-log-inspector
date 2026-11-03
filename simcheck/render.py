"""Text output for agents: one fact per line, evidence IDs (eNNN) as handles, no filler.

Times use Spectre's own unit spelling (ns, us, ...) so they can be matched against the log.
"""
import json

UNITS = ((1.0, 's'), (1e-3, 'ms'), (1e-6, 'us'), (1e-9, 'ns'), (1e-12, 'ps'), (1e-15, 'fs'))
LETTER = {'FATAL': 'E', 'ERROR': 'E', 'WARNING': 'W', 'NOTICE': 'N', 'INFO': 'T'}
COUNT_ORDER = ('E', 'W', 'T', 'N')
CHECK_NAMES = {'state': 'state file', 'log_status': 'logStatus', 'raw': 'raw waveform'}
CLIP = 400


def sim(seconds):
    if seconds is None:
        return '-'
    if seconds == 0:
        return '0s'
    for scale, unit in UNITS:
        if abs(seconds) >= scale * 0.9999995 or unit == 'fs':
            return f'{seconds / scale:.6g}{unit}'


def pct(p):
    if p >= 10:
        return f'{p:.1f}%'
    if p >= 1:
        return f'{p:.2f}%'
    if p >= 0.001:
        return f'{p:.3f}%'
    return '<0.001%'


def at(item):
    """'@60.096ns (0.058%)' for an item with a simulation time, else ''."""
    if item.get('t') is None:
        return ''
    return f"@{sim(item['t'])}" + (f" ({pct(item['pct'])})" if item.get('pct') is not None else '')


def age(seconds):
    if seconds is None:
        return '?'
    s = max(0, seconds)
    if s < 90:
        return f'{s:.0f}s'
    if s < 5400:
        return f'{s / 60:.0f}m'
    if s < 172800:
        return f'{s / 3600:.1f}h'
    return f'{s / 86400:.0f}d'


def kib(n):
    if n is None:
        return '?'
    return f'{n / 1024:.1f}KiB' if n < 1048576 else f'{n / 1048576:.1f}MiB'


def clip(text, limit=CLIP):
    return text if len(text) <= limit else f'{text[:limit]}…[+{len(text) - limit} chars]'


def join(*parts):
    return ' '.join(p for p in parts if p)


def plain_key(key):
    """Native codes and tool keys as they are; uncoded messages as their number-masked text."""
    head, sep, rest = key.partition(':')
    return f'"{rest}"' if sep and head in LETTER else key


def label(item):
    """Code or tool key; empty for uncoded messages, whose text follows anyway."""
    key, sev = item.get('key') or '', item.get('sev') or ''
    return '' if sev and key.startswith(sev + ':') else key


def suppressed(item):
    return ' then suppressed' if item.get('sup') else ''


def counts(n):
    return ' '.join(f'{k}{n[k]}' for k in COUNT_ORDER if n.get(k)) or 'no problems'


def state_text(r):
    words = [r['state']]
    flags = r.get('flags', [])
    if 'rule' in flags:
        words.append('rule hit')
    if 'quiet' in flags:
        words.append(f"log quiet {age(r.get('log_age'))}")
    if 'collector_error' in flags:
        words.append('collector error')
    if 'source_error' in flags:
        words.append('log unreadable')
    if r.get('gen'):
        words.append(f"restart {r['gen']}")
    return ', '.join(words)


def progress_text(r):
    if not r.get('analysis'):
        return ''
    if r.get('t') is None:
        return r['analysis']
    stop = f"/{sim(r['stop'])}" if r.get('stop') else ''
    share = f" ({pct(r['pct'])})" if r.get('pct') is not None else ''
    return f"{r['analysis']} t>={sim(r['t'])}{stop}{share}"


def group_line(g, baseline=None):
    """E e3759 SPECTRE-16927 x1 @1.14929ns (0.140%): message"""
    parts = [LETTER.get(g['sev'], 'T'), f"e{g['e']}", label(g), f"x{g['n']}{suppressed(g)}", at(g) or g.get('phase', '')]
    if g.get('rules'):
        parts.append('rule=' + ','.join(g['rules']))
    if g.get('base_new') and baseline:
        parts.append(f'not-in-{baseline}')
    if g.get('last'):
        parts.append(f"last e{g['last']}")
    return join(*parts) + ': ' + g.get('msg', '')


def _attention_lines(r):
    out = []
    errors = r.get('errors', [])
    for g in errors:
        out.append(join(f"e{g['e']}", g['sev'], label(g), f"x{g['n']}{suppressed(g)}", at(g)) + f": {g['msg']}")
    more = r.get('n', {}).get('E', 0) - len(errors)
    if more > 0:
        out.append(f"+{more} more error groups: simcheck show {r['run']}")
    for rule in r.get('rules', []):
        keys = ' '.join(plain_key(k) for k in rule['keys'])
        if rule.get('n'):
            keys += f" +{rule['n'] - len(rule['keys'])}"
        out.append(join(f"rule {rule['rule']}: {keys}; first e{rule['e']}", at(rule)))
    b = r.get('base')
    if b:
        extra = f" +{b['n'] - len(b['new'])}" if b.get('n') else ''
        out.append(f"not in baseline {b['ref']}: {' '.join(b['new'])}{extra}")
    if r.get('error'):
        out.append(f"error: {r['error']}")
    return out


def status(d):
    c = d['collector']
    runs = d['runs']
    if c['live']:
        head = f"collector live (heartbeat {age(c.get('hb'))})"
    elif c.get('hb') is not None:
        head = f"collector OFFLINE for {age(c['hb'])}: data is not updating"
    else:
        head = 'no collector running: data is not updating'
    attention = sum(1 for r in runs if r.get('flags'))
    lines = [f"{head}; {len(runs)} runs, {attention} need attention; cursor {d['cursor']}"]
    if c.get('version') and c['version'] != d['version']:
        lines.append(f"warning: collector {c['version']} and reader {d['version']} differ")
    for r in runs:
        parts = [f"{r['run']}: {state_text(r)}", progress_text(r), counts(r.get('n', {}))]
        f = r.get('frames')
        if f:
            latest = f" last {f['frame']} code {f.get('code', '-')}" if 'frame' in f and not r.get('ended') else ''
            parts.append(f"frames {f['n']}{latest}")
        if r.get('log_age') is not None and 'quiet' not in r.get('flags', []):
            parts.append(f"log {age(r['log_age'])} ago")
        lines.append(' | '.join(p for p in parts if p))
        if r.get('flags'):
            lines += ['  ' + line for line in _attention_lines(r)]
    return '\n'.join(lines)


def show(d):
    head = [f"{d['run']}: {state_text(d)}", progress_text(d), f"log {d['log']}" if d.get('log') else '']
    lines = [' | '.join(p for p in head if p)]
    lines += [group_line(g, d.get('baseline')) for g in d['groups']]
    if d.get('more'):
        lines.append(f"+{d['more']} more groups: simcheck show {d['run']} --all")
    if d.get('hidden_notices'):
        lines.append(f"{d['hidden_notices']} NOTICE groups hidden: simcheck show {d['run']} --all")
    if not d['groups'] and not d.get('hidden_notices'):
        lines.append('no problems in the indexed log')
    return '\n'.join(lines)


def evidence(d):
    head = [f"e{d['e']}", d['run'], d.get('sev', ''), label(d), at(d)]
    if 'frame' in d:
        head.append(f"frame {d['frame']} code {d.get('code', '-')} valid {d.get('valid', '-')}")
    if d.get('issue'):
        head.append(f"issue {d['issue']}")
    g = d.get('group')
    if g and (g['n'] > 1 or g.get('sup')):
        head.append(f"| group x{g['n']}{suppressed(g)}, first e{g['first']}, last e{g['last']}")
    lines = [join(*head), f"{d['path']}:{d['line']}"]
    if d.get('header'):
        lines.append(f"  {d['header']['line']} {clip(d['header']['raw'])}")
    lines.append(f"> {d['line']} {clip(d['raw'])}")
    lines += [f"  {c['line']} {clip(c['raw'])}" for c in d.get('cont', [])]
    if d.get('cont_more'):
        lines.append('  ... more continuation lines in the log')
    if d.get('suppression'):
        lines.append(f"  {d['suppression']['line']} {clip(d['suppression']['raw'])}")
    if d.get('limitation'):
        lines.append(f"limitation: {d['limitation']}")
    return '\n'.join(lines)


def change_line(c):
    run, kind = c.get('run', ''), c['type']
    if kind == 'status':
        return f"{run}: status {c['from']} -> {c['to']}"
    if kind == 'restart':
        return f"{run}: log restarted (generation {c['gen']})"
    if kind == 'new':
        rules = f" rule={','.join(c['rules'])}" if c.get('rules') else ''
        return (f"{run}: new " + join(c['sev'], f"e{c['e']}", label(c), f"x{c['n']}{suppressed(c)}", at(c))
                + rules + f": {c.get('msg', '')}")
    if kind == 'rule':
        return f"{run}: rule {c['rule']} hit " + join(plain_key(c['key']), f"e{c['e']}", at(c))
    if kind == 'more':
        return f"{run}: " + join(plain_key(c['key']), f"x{c['n']} more", f"last e{c['last']}")
    if kind == 'quiet':
        return f"{run}: log quiet for {age(c['log_age'])}, run not ended"
    if kind == 'collector_error':
        return f"{run}: collector error: {c['error']}"
    if kind == 'source_error':
        return f"{run}: log unreadable: {c['error']}"
    if kind == 'run_added':
        return f"{run}: new run"
    if kind == 'collector_offline':
        return f"collector offline (heartbeat {age(c.get('hb'))} ago)"
    if kind == 'state_changed':
        return 'state changed since the cursor: run `simcheck status`'
    return json.dumps(c, ensure_ascii=False)


def wait(d):
    if d['changed']:
        lines = [f"{len(d['changes'])} change(s); cursor {d['cursor']}"]
        lines += [change_line(c) for c in d['changes']]
        if d.get('more'):
            lines.append(f"+{d['more']} more changes: simcheck status")
    elif d['reason'] == 'timeout':
        lines = [f"no change before timeout; cursor {d['cursor']}"]
    else:
        hb = d.get('collector', {}).get('hb')
        last = f" (last heartbeat {age(hb)} ago)" if hb is not None else ''
        return f"no collector running{last}: start `simcheck run MANIFEST` or `simcheck watch MANIFEST`"
    lines.append(f"next: simcheck wait --cursor {d['cursor']}")
    return '\n'.join(lines)


def measurements(d):
    rows = d['rows']
    head = f"{d['run']}: {d['total']} testbench records"
    if not rows:
        return head
    lines = [f"{head}; e{rows[0]['e']}..e{rows[-1]['e']}", 'frame code valid evidence']
    for r in rows:
        if 'frame' in r:
            lines.append(f"{r['frame']} {r.get('code', '-')} {r.get('valid', '-')} e{r['e']}")
        else:
            lines.append(f"- - - e{r['e']} {r.get('issue', 'raw')}: {r.get('raw', '')}")
    if d.get('older'):
        lines.append(f"older: simcheck measurements {d['run']} --before e{rows[0]['e']}")
    if d.get('newer'):
        lines.append(f"newer: simcheck measurements {d['run']} --after e{rows[-1]['e']}")
    return '\n'.join(lines)


def check_line(c):
    name, state = CHECK_NAMES.get(c['check'], c['check']), c['status']
    if state == 'not_checked':
        return f'{name}: not configured'
    if state != 'observed':
        why = c.get('detail') or c.get('format')
        return f'{name}: {state}' + (f' ({why})' if why else '')
    if c['check'] == 'state':
        reason = f", reason {c['reason']}" if c.get('reason') else ''
        return f"{name}: {c.get('reported_status')}, exit {c.get('exit_code', '-')}{reason}"
    if c['check'] == 'log_status':
        return f"{name}: {c.get('analysis') or '?'} {c.get('last_status') or 'missing'}"
    reached = {True: ', stop reached', False: ', stop NOT reached'}.get(c.get('expected_stop_reached'), '')
    return (f"{name}: END {'yes' if c.get('end_marker') else 'no'}, last saved {sim(c.get('last_saved_time_s'))}"
            f"{reached}, {kib(c.get('size_bytes'))} (head/tail only)")


def details(d):
    stops = ', '.join(f'{name} stop {sim(t)}' for name, t in d.get('stops', {}).items())
    indexed = f"indexed {kib(d.get('indexed'))} of {kib(d.get('size'))}" if 'size' in d else ''
    head = [f"{d['run']}: {d.get('status', 'unknown')}", f"Spectre {d['spectre']}" if d.get('spectre') else '',
            stops, f"log {d['log']}" if d.get('log') else '', indexed]
    lines = [' | '.join(p for p in head if p)]
    f = d.get('footer')
    lines.append(f"footer: {f['errors']} errors, {f['warnings']} warnings, {f['notices']} notices" if f
                 else 'footer: not written yet')
    lines += [check_line(c) for c in d.get('checks', [])]
    if d.get('suppressed'):
        lines.append('native suppressed totals: ' + ', '.join(f'{k} {v}' for k, v in d['suppressed'].items()))
    if d.get('coverage'):
        lines.append(f"coverage limited: {d['coverage']}")
    if d.get('pending_line'):
        lines.append('last log line is still incomplete')
    if d.get('settings'):
        lines.append('settings requested -> effective:')
        lines += [f"  {s['name']} {s.get('req', '-')} -> {s.get('eff', '-')}" + (' DIFF' if s.get('diff') else '')
                  for s in d['settings']]
    return '\n'.join(lines)
