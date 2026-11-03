"""Spectre log line parser.

Every value is copied from the log or computed from logged values. Nothing here
diagnoses a circuit or decides whether a result is acceptable.
"""
import math
import re

SCHEMA_VERSION = 3
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
SCALE = {'': 1, 'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6,
         'µ': 1e-6, 'm': 1e-3, 'k': 1e3, 'M': 1e6, 'G': 1e9}

# "Warning from spectre at time = 60.0961 ns during transient analysis `tran'."
# The header owns the block of indented lines that follows it.
HEADER = re.compile(r'^(Warning|Notice|Error|Fatal error) (?:from|found by) spectre\b')
HEADER_SEVERITY = {'Warning': 'WARNING', 'Notice': 'NOTICE', 'Error': 'ERROR', 'Fatal error': 'FATAL'}
AT_TIME = re.compile(r'\bat time = (' + NUMBER + r')\s*([fpnuµmkMG]?s)\b')
ANY_TIME = re.compile(r'\btime\s*=\s*(' + NUMBER + r')\s*([fpnuµmkMG]?s)\b')
# One banner starts each analysis: "Transient Analysis `tran': time = (0 s -> 20 ns)",
# "DC Analysis `dc1': vcm = (1e-03 -> 809e-03)", "AC Analysis `ac1': freq = (1 MHz -> 2 MHz)",
# "Monte Carlo Analysis `mc1': iteration = (1 -> 4)", "DC Analysis `op'".
BANNER = re.compile(r"^([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)?) Analysis [`']([^'`]+)['`]")
# Headers name the innermost analysis first:
# "during AC analysis `ac1', during Monte Carlo analysis `mc1'", "during IC analysis, during transient analysis `tran'".
DURING = re.compile(r"\bduring (?:[A-Za-z]+ ){0,2}analysis [`']([^'`]+)['`]")
TRAN_START = re.compile(r"^Transient Analysis [`']([^'`]+)['`]: time = \((.+?) -> (.+?)\)")
# Spectre's progress meter: 70 cells, a digit after every six dots. Each line it prints
# repeats the whole meter so far from column 0, often with testbench output after it.
METER = '......9......8......7......6......5......4......3......2......1......0'
TAG = re.compile(r'^\s*(WARNING|ERROR|FATAL|NOTICE)(?:\s*\(([^)]+)\))?\s*:\s*(.*)$')
SUPPRESSED_TOTAL = re.compile(r'^\s*(\d+)\s+(warning|notice|error)s?\s+suppressed\b', re.I)
FOOTER = re.compile(r'spectre completes with (\d+) errors?, (\d+) warnings?, and (\d+) notices?')
SETTING = re.compile(r'\s*(method|reltol|maxstep|step|abstol\(V\)|abstol\(I\)|errpreset|relref|'
                     r'noisefmax|noisefmin|noiseseed|noisescale|temp)\s*=\s*(.+)')
SOA = re.compile(r'(\S+):\s+(V\w+)\(=\s*([^)]*)\).*?exceeded\s+(\w+)\(=\s*([^)]*)\)')
R4MEAS = re.compile(r'^[.\d\s]*R4MEAS,')
RAW_RECORD = re.compile(r'^[.\d\s]*(?P<name>STATIC\w*|ASSERT\w*|PASS|FAIL)(?=[,:\s])')
RESOURCE_CODES = ('SPECTRE-555', 'SPECTRE-27', 'SPECTRE-7082')


def quantity(text):
    m = re.fullmatch(r'\s*(' + NUMBER + r')\s*([fpnuµmkMG]?)([sVAHz]*)\s*', text)
    if not m:
        return None
    value = float(m[1]) * SCALE[m[2]]
    if not math.isfinite(value):
        return None
    return {'value_si': value, 'unit': m[3], 'raw': text}


def seconds(text):
    q = quantity(text)
    return q['value_si'] if q else None


def problem_key(severity, code, message):
    """Group key: the native code, else the message with numbers masked."""
    if code:
        return code
    text = ' '.join(re.sub(NUMBER, '#', message or '').split())[:80]
    return severity + ':' + text if text else severity


def category_for(severity, code):
    if code in RESOURCE_CODES:
        return 'data_resources'
    if severity == 'FATAL' or code == 'SPECTRE-209':
        return 'execution'
    return 'diagnostics'


def initial():
    return {'analysis': None, 'analyses': {}, 'last_time_s': None, 'scope': 'requested',
            'native_errors': 0, 'fatal_seen': False, 'footer': None,
            'suppression_seen': False, 'suppressed_totals': {},
            'settings': {}, 'version': None, 'frames': 0, 'last_frame': None, 'last_code': None,
            'meter': None, 'banner_seen': False, 'block': None, 'message': None}


def stop_time(state):
    info = state['analyses'].get(state['analysis']) or {}
    return info.get('stop_time_s')


def meter_cells(text):
    """Length of the progress meter at the start of a line; 0 when the line has none."""
    n = 0
    for got, want in zip(text, METER):
        if got != want:
            break
        n += 1
    return n


def read_meter(text, state):
    """Keep the furthest meter of the current analysis. Also used on a last line that
    Spectre has not finished: the meter grows there for hours, and nothing is indexed."""
    if state['meter'] is not None and text[:1] == '.':
        state['meter'] = max(state['meter'], meter_cells(text))


def parse(line, state, line_no):
    """Mutate the persisted context and return zero or more structured events."""
    text = line.rstrip('\r\n')
    events = []

    def emit(category, kind, severity='INFO', sim_time_s=None, **fields):
        events.append(dict(schema_version=SCHEMA_VERSION, category=category, kind=kind,
                           severity=severity, analysis=state['analysis'],
                           sim_time_s=sim_time_s, raw=text, **fields))

    def message(severity, code, body, severity_source):
        block = state['block']
        sim_time = block['sim_time_s'] if block else None
        key = problem_key(severity, code, body)
        fields = {'code': code, 'message': body, 'problem_key': key,
                  'severity_source': severity_source}
        if block:
            fields.update(header_line=block['line'], header_raw=block['raw'])
        if sim_time is not None:
            fields['analysis_stop_s'] = stop_time(state)
        soa = SOA.search(body)
        if soa:
            fields.update(instance=soa[1], terminal=soa[2], measured=quantity(soa[3]),
                          limit_name=soa[4], limit=quantity(soa[5]))
        if severity in ('ERROR', 'FATAL'):
            state['native_errors'] += 1
            state['fatal_seen'] |= severity == 'FATAL'
        emit(category_for(severity, code), 'native_message', severity, sim_time, **fields)
        state['message'] = {'line': line_no, 'key': key}

    if 'Spectre (R) Circuit Simulator' in text:
        state['banner_seen'] = True
    version = re.search(r'Version\s+([\w.\-]+)', text)
    if version and ('spectre' in text.lower() or 'isr' in version[1]):
        state['version'] = version[1]
        emit('execution', 'version', version=version[1])
    banner = BANNER.match(text)
    during = None if banner else DURING.search(text)
    if banner or during:
        state['analysis'] = banner[2] if banner else during[1]
    logged = ANY_TIME.search(text)
    kind = (state['analyses'].get(state['analysis']) or {}).get('kind')
    # "Accumulated DC solution time = 0 s" in a DC or AC analysis is not simulation time.
    if logged and kind in (None, 'Transient'):
        observed_time = seconds(logged[1] + logged[2])
        if observed_time is not None:
            # Diagnostic summaries can say "accumulated from time = 0 s"
            # after a transient failure. Keep the furthest logged progress.
            previous = state['last_time_s']
            state['last_time_s'] = observed_time if previous is None else max(previous, observed_time)
    if banner:
        start = TRAN_START.match(text)
        stop = seconds(start[3]) if start else None
        state['analyses'][banner[2]] = {'kind': banner[1], 'stop_time_s': stop, 'line': line_no}
        state['scope'] = 'effective'
        state['last_time_s'] = None
        state['meter'] = 0
        emit('settings_progress', 'analysis_start', stop_time_s=stop, analysis_type=banner[1])
    read_meter(text, state)
    if 'Important parameter values:' in text:
        state['scope'] = 'effective'
    setting = SETTING.match(text)
    if setting:
        key, raw = setting.groups()
        value, sep, default = raw.partition(', default ')
        item = {'name': key, 'scope': state['scope'], 'value': value.strip(),
                'normalized': quantity(value), 'default_text': default if sep else None}
        state['settings'][str(state['analysis']) + ':' + state['scope'] + ':' + key] = item
        emit('settings_progress', 'setting', **item)

    indented = text[:1] in (' ', '\t') and bool(text.strip())
    header = HEADER.match(text)
    tag = TAG.match(text)
    total = SUPPRESSED_TOTAL.match(text)
    if header:
        at = AT_TIME.search(text)
        # Time belongs to this block only; a header without one leaves it unknown.
        state['block'] = {'line': line_no, 'raw': text, 'severity': HEADER_SEVERITY[header[1]],
                          'sim_time_s': seconds(at[1] + at[2]) if at else None}
        state['message'] = None
    elif total:
        kind = total[2].lower()
        state['suppression_seen'] = True
        state['suppressed_totals'][kind] = int(total[1])
        emit('data_resources', 'suppression_total', 'NOTICE', count=int(total[1]),
             suppressed_type=kind, count_scope='native_summary_not_per_code')
    elif 'Further occurrences of this' in text and 'suppressed' in text:
        state['suppression_seen'] = True
        last = state['message']
        emit('data_resources', 'suppression', 'NOTICE',
             related_message_line=last['line'] if last else None,
             problem_key=last['key'] if last else None)
    elif tag and (tag[2] or (indented and state['block'] is not None)):
        # Spectre's own: coded anywhere, uncoded only indented under its header line.
        severity, code, body = tag.groups()
        message(severity, code, body, 'tag')
    elif tag and not (indented and state['message'] is not None):
        # "ERROR: ..." outside any Spectre block was printed by something else, such as a
        # testbench. It stays evidence under its own word but is not a Spectre error.
        state['block'] = None
        state['message'] = None
        emit('testbench', 'raw_record', problem_key='TB:reported_' + tag[1],
             limitation='uncoded tag outside a Spectre message block; not counted as a Spectre message')
    elif indented and state['message'] is not None and not setting:
        emit('diagnostics', 'message_continuation', related_message_line=state['message']['line'])
    elif indented and state['block'] is not None and not setting:
        # Spectre notices have no tag: the header states the native severity.
        message(state['block']['severity'], None, text.strip(), 'header')
    else:
        state['block'] = None
        state['message'] = None

    footer = FOOTER.search(text)
    if footer:
        state['footer'] = {'errors': int(footer[1]), 'warnings': int(footer[2]),
                           'notices': int(footer[3])}
        emit('execution', 'native_footer', **state['footer'])
    if 'terminated prematurely' in text:
        state['fatal_seen'] = True
        emit('execution', 'premature_termination', 'ERROR', problem_key='premature_termination')
    if R4MEAS.match(text):
        values = text.split('R4MEAS,', 1)[1].strip().split(',')
        fields = {'record_type': 'R4MEAS',
                  'interpretation': 'reported_testbench_values_not_code_oracle'}
        if len(values) >= 8:
            try:
                fields.update(frame=int(values[0]), code_value=int(values[1]),
                              reported_valid=int(values[7]))
                state['last_frame'] = fields['frame']
                state['last_code'] = fields['code_value']
                state['frames'] += 1
            except ValueError:
                fields['parse_issue'] = 'non_integer_frame_or_code_or_valid'
        else:
            fields['parse_issue'] = 'short_record'
        if fields.get('parse_issue'):
            fields['problem_key'] = 'TB:unparsed_record'
        elif fields['reported_valid'] == 0:
            fields['problem_key'] = 'TB:reported_valid=0'
        emit('testbench', 'record', **fields)
    elif RAW_RECORD.match(text):
        fields = {'problem_key': 'TB:reported_FAIL'} if RAW_RECORD.match(text)['name'] == 'FAIL' else {}
        emit('testbench', 'raw_record', **fields)
    return events
