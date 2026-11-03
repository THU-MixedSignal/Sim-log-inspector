"""New native Spectre runs, not hand-authored error logs.

Golden codes/states below were checked against native excerpts and managed
receipts. These tests only replay small sanitized evidence; no simulator starts.
"""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from simcheck.store import connect, evidence, measurement_page, problem_groups, scan, status

FIX = Path(__file__).parent / 'fixtures' / 'live_20261103'
GOLD = {
    'rc-normal': ('complete', None),
    'model-missing': ('failed', 'SFE-23'),
    'param-missing': ('failed', 'SFE-1997'),
    'include-missing': ('failed', 'SFE-868'),
    'ahdl-compile': ('failed', 'VACOMP-2212'),
    'topology': ('failed', None),
    'dc-nonconv': ('failed', 'SPECTRE-16080'),
    'tran-minstep': ('failed', 'SPECTRE-16927'),
    'tb-records': ('complete', None),
    'output-limit': ('failed', 'SPECTRE-27'),
    # This attempt reached the output cap first; it is NOT a wall-limit proof.
    'wall-limit': ('failed', 'SPECTRE-27'),
    'soa': ('complete', 'CMI-2751'),
    'adc-a-tt': ('complete', None),
    'adc-b-tt': ('complete', 'CMI-2751'),
}


def config(name):
    analysis = 'tran_perf' if name.startswith('adc-') else 'tran_live'
    c = dict(id=name, log=str(FIX / (name + '.log')), state=str(FIX / (name + '.state.json')),
             analysis=analysis, expected_stop_s=359e-9 if name.startswith('adc-') else 20e-9)
    if (FIX / (name + '.logStatus')).exists():
        c['log_status'] = str(FIX / (name + '.logStatus'))
    if name == 'rc-normal':
        c['raw'] = str(FIX / 'rc-normal.tran')
    return c


class NativeCampaign(unittest.TestCase):
    def test_provenance(self):
        provenance = json.loads((FIX / 'provenance.json').read_text(encoding='utf-8'))
        self.assertEqual(set(provenance), set(GOLD))
        for name, meta in provenance.items():
            for ext, key in (('.log', 'log_sha256'), ('.state.json', 'state_sha256'),
                             ('.logStatus', 'log_status_sha256')):
                if key in meta:
                    data = (FIX / (name + ext)).read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), meta[key], name + ext)
            self.assertIsNone(re.search(rb'\d+@[A-Za-z]', (FIX / (name + '.log')).read_bytes()))
        self.assertEqual(hashlib.sha256((FIX / 'rc-normal.tran').read_bytes()).hexdigest(),
                         provenance['rc-normal']['raw_sha256'])

    def test_native_error_and_completion_matrix(self):
        for name, (expected, code) in GOLD.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with connect(Path(tmp) / 'index.sqlite') as db:
                    observed = scan(db, config(name))
                    self.assertEqual(observed['integrity']['status'], expected)
                    groups = problem_groups(db, name, limit=500)
                    if code:
                        group = next(g for g in groups if g['code'] == code)
                        item = evidence(db, group['first_evidence_id'])
                        source_lines = (FIX / (name + '.log')).read_text(encoding='utf-8').splitlines()
                        self.assertEqual(item['raw'], source_lines[item['line'] - 1])
                    if name == 'topology':
                        self.assertTrue(any(g['severity'] == 'FATAL' for g in groups))
                    if name in ('output-limit', 'wall-limit'):
                        self.assertEqual(observed['integrity']['execution_status'], 'limit_exceeded')
                        source_state = json.loads((FIX / (name + '.state.json')).read_text(encoding='utf-8'))
                        self.assertEqual(source_state['exit_code'], 0)
                        self.assertEqual(source_state['reason'], 'output_size_limit')
                    if name == 'tran-minstep':
                        run = status(db)['runs'][0]
                        self.assertAlmostEqual(run['t'], 5.00081e-9)
                        self.assertAlmostEqual(run['pct'], 25.00405, delta=.0001)

    def test_native_tb_prefixes_and_adc_frames(self):
        for name in ('tb-records', 'adc-a-tt', 'adc-b-tt'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with connect(Path(tmp) / 'index.sqlite') as db:
                    scan(db, config(name))
                    page = measurement_page(db, name, tail=20)
                    if name == 'tb-records':
                        self.assertEqual(page['total'], 6)
                        keys = {g['problem_key'] for g in problem_groups(db, name)}
                        self.assertTrue({'TB:reported_valid=0', 'TB:unparsed_record', 'TB:reported_FAIL'} <= keys)
                    else:
                        self.assertEqual([r['code'] for r in page['rows']], [231, 44, 183])
                        self.assertEqual([r['valid'] for r in page['rows']], [1, 1, 1])
                        self.assertEqual(len(page['rows']), 3)
                        cmi = [g for g in problem_groups(db, name) if (g['code'] or '').startswith('CMI-')]
                        self.assertEqual(sum(g['printed_count'] for g in cmi), 25 if name == 'adc-b-tt' else 0)

    def test_soa_signed_values_suppression_and_first_unknown_time(self):
        from simcheck.parser import initial, parse
        state = initial()
        out = [e for n, line in enumerate((FIX / 'soa.log').read_text(encoding='utf-8').splitlines(), 1)
               for e in parse(line, state, n)]
        first = next(e for e in out if e.get('code') == 'CMI-2754')
        self.assertEqual(first['measured']['value_si'], -1.2)
        self.assertEqual(first['limit']['value_si'], .99)
        self.assertIsNone(first['sim_time_s'])  # IC header did not report a time.
        with tempfile.TemporaryDirectory() as tmp:
            with connect(Path(tmp) / 'index.sqlite') as db:
                c = config('soa')
                c['watch'] = [{'name': 'SOA', 'code': 'CMI-*'}]
                scan(db, c)
                groups = [g for g in problem_groups(db, 'soa') if (g['code'] or '').startswith('CMI-')]
                self.assertEqual(len(groups), 5)
                self.assertTrue(all(g['printed_count'] == 5 and g['suppressed_after'] for g in groups))
                hit = status(db)['runs'][0]['rules'][0]
                self.assertEqual(hit['e'], min(g['first_evidence_id'] for g in groups))
                self.assertNotIn('t', hit)  # Later timed groups cannot hide the earlier untimed hit.

    def test_real_raw_truncated_copy_and_wrong_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            with connect(Path(tmp) / 'index.sqlite') as db:
                c = config('rc-normal')
                self.assertEqual(scan(db, c)['integrity']['status'], 'complete')
                corrupted = Path(tmp) / 'truncated.tran'
                data = (FIX / 'rc-normal.tran').read_bytes()
                self.assertTrue(data.rstrip().endswith(b'END'))
                corrupted.write_bytes(data[:data.rfind(b'END')])
                c['raw'] = str(corrupted)
                self.assertEqual(scan(db, c)['integrity']['status'], 'incomplete')
                c['raw'] = str(FIX / 'rc-normal.tran')
                c['analysis'] = 'not_the_real_analysis'
                self.assertEqual(scan(db, c)['integrity']['status'], 'incomplete')
