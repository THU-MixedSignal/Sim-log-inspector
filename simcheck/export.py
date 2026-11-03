"""Offline snapshots of collected evidence; never read or modify simulation inputs."""
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from html import escape

from . import __version__, render
from .store import API, details, digest, evidence, show, snapshot

REPORT_CSP = ("default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
              "form-action 'none'; frame-ancestors 'none'")
REPORT_STYLE = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:24px auto;padding:0 24px;
max-width:1400px;color:#17212b;background:white;font:14px/1.5 'Segoe UI',Arial,sans-serif}
h1{font-size:24px;margin:0}h2{font-size:18px;margin:24px 0 8px}p{margin:6px 0}
small,.muted{font-size:12px;color:#636f7a}.state{font-size:14px;font-weight:600}
.failed,.fatal,.error{color:#b3123a}.unknown,.incomplete,.warning{color:#805300}
.tag{display:inline-block;padding:0 5px;border:1px solid;border-radius:3px;font-size:12px}
.rule{color:#b3123a}.baseline{color:#805300}details.problem{border-bottom:1px solid #dde2e6}
summary{cursor:pointer;padding:7px 0}.message{font-size:15px}.meta{color:#636f7a;font-size:12px}
.problem pre{margin:6px 0 10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:10px;
background:#f6f8f9;border:1px solid #dde2e6;border-radius:4px;font:12.5px/1.6 Consolas,monospace}
code{overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:5px 8px;border-bottom:1px solid #dde2e6}
th{font-size:12px;font-weight:400;color:#636f7a}td{overflow-wrap:anywhere}.raw{white-space:pre-wrap;
font-family:Consolas,monospace}footer{margin-top:24px;border-top:1px solid #dde2e6;padding-top:8px}
"""


def _text(value):
    return escape(str(value), quote=True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _events(db, run, generation):
    rows = db.execute('SELECT id, observed, payload FROM events WHERE run_id=? AND generation=? ORDER BY id',
                      (run, generation))
    for row in rows:
        yield dict(json.loads(row['payload']), event_id=row['id'], observed_epoch=row['observed'])


def _json_chunks(db, data):
    yield _json(data)[:-1] + ',"events":['
    for index, event in enumerate(_events(db, data['run'], data['scope']['generation'])):
        yield (',' if index else '') + _json(event)
    yield '],"export_complete":true}\n'


def _raw_evidence(db, event_id, label):
    item = evidence(db, event_id)
    if item is None:
        return '<p class="warning">Evidence unavailable.</p>'
    lines = []
    if item.get('header'):
        lines.append(item['header'])
    lines.append({'line': item['line'], 'raw': item['raw']})
    lines.extend(item.get('cont', []))
    if item.get('cont_more'):
        lines.append({'line': '…', 'raw': 'More continuation lines in Stored evidence below.'})
    if item.get('suppression'):
        lines.append(item['suppression'])
    text = '\n'.join(f"{line['line']:>5}  {line['raw']}" for line in lines)
    return (f'<small>{label} · e{event_id} · <code>{_text(item["path"])}:{item["line"]}</code></small>'
            f'<pre>{_text(text)}</pre>')


def _html_chunks(db, data):
    run = data['run']
    summary = data['summary']
    state = summary['state']
    checks = data['details']
    meta_csp = REPORT_CSP.removesuffix("; frame-ancestors 'none'")
    yield ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<meta http-equiv="Content-Security-Policy" content="{_text(meta_csp)}">'
           f'<title>{_text(run)} · Spectre Log Inspector</title><style>{REPORT_STYLE}</style></head><body>'
           f'<header><h1>{_text(run)}</h1><p class="state {_text(state)}">{_text(state)}</p>'
           f'<small>Saved {_text(data["saved_at"])} · Generation {data["scope"]["generation"]}</small>'
           f'<p class="muted"><code>{_text(checks.get("log", ""))}</code></p></header>')
    if summary.get('analysis'):
        yield f'<p>{_text(render.progress_text(summary))}</p>'
    if summary.get('error'):
        yield f'<p class="error">{_text(summary["error"])}</p>'
    yield '<h2>Problems</h2>'
    for group in data['problems']['groups']:
        tags = ''
        if group.get('rules'):
            tags += f' <span class="tag rule" title="{_text(", ".join(group["rules"]))}">Rule</span>'
        if group.get('base_new'):
            tags += (f' <span class="tag baseline" title="{_text(data["problems"].get("baseline", ""))}">'
                     'Not in baseline</span>')
        count = f'×{group["n"]}{"+" if group.get("sup") else ""}'
        title = 'Further occurrences suppressed; total unknown' if group.get('sup') else 'Printed occurrences'
        yield (f'<details class="problem"><summary><strong class="{_text(group["sev"].lower())}">'
               f'{_text(group["sev"])} {_text(render.label(group))}</strong> '
               f'<span class="meta" title="{title}">{count} {_text(render.at(group))}</span>{tags} '
               f'<span class="message">{_text(group["msg"])}</span></summary>')
        yield _raw_evidence(db, group['e'], 'First')
        if group.get('last'):
            yield _raw_evidence(db, group['last'], 'Last')
        yield '</details>'
    if not data['problems']['groups']:
        yield '<p class="muted">No problem records.</p>'
    if data['scope']['problem_groups'] > len(data['problems']['groups']):
        yield '<p class="warning">Problem summaries are limited to 500 groups; all stored events are included below.</p>'
    yield '<h2>Integrity and settings</h2>'
    yield f'<pre>{_text(render.details(checks))}</pre>'
    if data['coverage']['limitations']:
        yield '<p class="warning">Coverage: ' + _text('; '.join(data['coverage']['limitations'])) + '</p>'
    yield (f'<h2>Stored evidence ({data["scope"]["events"]})</h2>'
           '<p class="muted">All collected events for this generation, including testbench records.</p>'
           '<table><thead><tr><th>Evidence</th><th>Type</th><th>Source and original text</th></tr></thead><tbody>')
    for event in _events(db, run, data['scope']['generation']):
        kind = ' '.join(str(event[k]) for k in ('severity', 'kind') if event.get(k))
        yield (f'<tr id="e{event["event_id"]}"><td>e{event["event_id"]}</td><td>{_text(kind)}</td>'
               f'<td><small><code>{_text(event["source_path"])}:{event["line"]}</code></small>'
               f'<div class="raw">{_text(event["raw"])}</div></td></tr>')
    yield ('</tbody></table><footer><small>Snapshot export complete. Collected evidence only; '
           'source logs and waveform files are not embedded. This report does not update.</small></footer></body></html>')


def export_file(db, run, format='json'):
    """Return a seekable temporary download; serialize in chunks within one read transaction.

    All current-generation stored events are included. Summary/API limits remain
    explicit, and original input files are never opened. The spool moves to disk
    above 1 MiB so large event histories do not require a second in-memory copy.
    """
    if format not in ('html', 'json'):
        raise ValueError('format must be html or json')
    if not db.in_transaction:
        db.execute('BEGIN')
    now = time.time()
    snap = snapshot(db, now)
    current = next((r for r in snap['runs'] if r['run_id'] == run), None)
    if current is None:
        raise LookupError('unknown run: ' + run)
    generation = current['generation']
    count = db.execute('SELECT count(*) FROM events WHERE run_id=? AND generation=?', (run, generation)).fetchone()[0]
    stamp = datetime.fromtimestamp(now, timezone.utc)
    data = {'export_version': 1, 'v': API, 'version': __version__, 'run': run,
            'saved_at': stamp.isoformat(timespec='seconds'),
            'scope': {'generation': generation, 'events': count,
                      'problem_groups': current['problems']['group_count'], 'source_files_embedded': False},
            'summary': digest(snap, [run])['runs'][0], 'problems': show(db, run, full=True, now=now),
            'details': details(db, run), 'coverage': current['coverage']}
    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', run).strip('._-')[:64] or 'run'
    name = f'{safe_name}-g{generation}-{stamp:%Y%m%dT%H%M%SZ}.{format}'
    file = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
    try:
        for chunk in (_html_chunks if format == 'html' else _json_chunks)(db, data):
            file.write(chunk.encode('utf-8'))
        file.seek(0)
    except Exception:
        file.close()
        raise
    kind = 'text/html' if format == 'html' else 'application/json'
    return file, name, kind + '; charset=utf-8'
