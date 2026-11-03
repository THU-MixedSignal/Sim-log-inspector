"""Hand-authored demo facts and counterexamples, independent of private logs."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from simcheck.store import (collect, connect, details, evidence, manifest,
                            measurement_page, show, status)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests' / 'fixtures' / 'synthetic'


def fixture_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(FIX.iterdir()) if p.is_file() and p.name != 'provenance.json'}


class SyntheticExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = connect(Path(cls.tmp.name) / 'examples.sqlite')
        cls.configs = manifest(ROOT / 'examples' / 'synthetic-cases.json')['runs']
        collect(cls.db, cls.configs)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_provenance_covers_every_synthetic_input(self):
        meta = json.loads((FIX / 'provenance.json').read_text(encoding='utf-8'))
        self.assertIn('synthetic', meta['source_kind'])
        self.assertEqual(fixture_hashes(), meta['files'])
        for c in self.configs:
            for field in ('log', 'state', 'log_status', 'raw'):
                if field in c:
                    self.assertEqual(Path(c[field]).parent, FIX)
                    self.assertIn(Path(c[field]).name, meta['files'])

    def test_completion_and_counterexamples(self):
        # Expected facts were written with the fixtures, not inferred from output.
        expected = {'demo-complete': 'complete', 'demo-warning': 'running',
                    'demo-fatal-exit0': 'failed', 'demo-no-footer': 'unknown',
                    'demo-raw-incomplete': 'incomplete', 'demo-analysis-mismatch': 'incomplete'}
        self.assertEqual({r['run']: r['state'] for r in status(self.db)['runs']}, expected)
        wrapper = next(c for c in details(self.db, 'demo-fatal-exit0')['checks']
                       if c['check'] == 'state')
        self.assertEqual((wrapper['reported_status'], wrapper['exit_code']), ('complete', 0))
        group = show(self.db, 'demo-fatal-exit0')['groups'][0]
        self.assertEqual((group['key'], group['sev']), ('DEMO-1', 'FATAL'))

    def test_warning_counts_time_suppression_and_source_location(self):
        groups = {g['key']: g for g in show(self.db, 'demo-warning')['groups']}
        g = groups['CMI-2753']
        self.assertEqual((g['sev'], g['n'], g['sup'], g['pct']), ('WARNING', 2, True, 20.0))
        self.assertAlmostEqual(g['t'], 20e-9)
        first = evidence(self.db, g['e'])
        last = evidence(self.db, g['last'])
        lines = (FIX / 'warning.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(Path(first['path']), FIX / 'warning.log')
        self.assertEqual((first['line'], first['header']['line']), (4, 3))
        self.assertEqual(first['raw'], lines[3])
        self.assertEqual(first['header']['raw'], lines[2])
        self.assertEqual(first['off'], len(('\n'.join(lines[:3]) + '\n').encode('utf-8')))
        self.assertNotIn('suppression', first)
        self.assertIn('Further occurrences', last['suppression']['raw'])
        # A native global total must not be assigned to the CMI group's count.
        self.assertEqual(details(self.db, 'demo-warning')['suppressed'], {'warning': 123})

    def test_untimed_unknown_code_and_notice_keep_their_evidence(self):
        view = show(self.db, 'demo-warning', full=True)
        groups = {g['key']: g for g in view['groups']}
        untimed = groups['DEMO-99']
        self.assertEqual(untimed['sev'], 'WARNING')
        self.assertNotIn('t', untimed)
        self.assertNotIn('t', evidence(self.db, untimed['e']))
        notice = next(g for g in groups.values() if g['key'].startswith('NOTICE:Newton'))
        self.assertEqual(notice['sev'], 'NOTICE')
        self.assertAlmostEqual(notice['t'], 26e-9)
        self.assertEqual(notice['rules'], ['Demo Newton notice'])
        self.assertTrue(groups['CMI-2753']['base_new'])
        self.assertEqual(groups['CMI-2753']['rules'], ['Demo SOA'])

    def test_measurements_preserve_invalid_and_unparsed_records(self):
        page = measurement_page(self.db, 'demo-warning')
        self.assertEqual(page['total'], 3)
        rows = page['rows']
        self.assertEqual([(r['frame'], r['code'], r['valid']) for r in rows[:2]],
                         [(0, 23, 1), (1, 24, 0)])
        self.assertEqual(rows[2]['issue'], 'short_record')
        self.assertEqual(rows[2]['raw'], 'R4MEAS,2,short')
        groups = {g['key']: g for g in show(self.db, 'demo-warning')['groups']}
        self.assertEqual(groups['TB:reported_valid=0']['sev'], 'INFO')
        self.assertEqual(groups['TB:unparsed_record']['sev'], 'INFO')
        self.assertEqual(groups['TB:reported_valid=0']['rules'], ['Demo TB valid=0'])

    def test_free_text_and_full_progress_do_not_prove_completion(self):
        view = show(self.db, 'demo-no-footer', full=True)
        self.assertEqual(view['state'], 'unknown')
        self.assertEqual(view['pct'], 100.0)
        self.assertEqual(view['groups'], [])
        self.assertNotIn('footer', details(self.db, 'demo-no-footer'))

    def test_settings_and_positive_negative_integrity_checks(self):
        complete = details(self.db, 'demo-complete')
        settings = {s['name']: s for s in complete['settings']}
        self.assertEqual(settings['method'], {'name': 'method', 'req': 'gear2only',
                                              'eff': 'trap', 'diff': True})
        self.assertEqual(settings['maxstep']['def'], '1 ns')
        good = {c['check']: c for c in complete['checks']}
        self.assertEqual(good['log_status']['last_status'], 'PASS')
        self.assertTrue(good['raw']['end_marker'])
        self.assertTrue(good['raw']['expected_stop_reached'])
        bad = next(c for c in details(self.db, 'demo-raw-incomplete')['checks'] if c['check'] == 'raw')
        self.assertFalse(bad['end_marker'])
        self.assertFalse(bad['expected_stop_reached'])
        self.assertEqual(bad['last_saved_time_s'], 4e-8)
        mismatch = next(c for c in details(self.db, 'demo-analysis-mismatch')['checks']
                        if c['check'] == 'log_status')
        self.assertEqual(mismatch['status'], 'unknown')
        self.assertEqual(mismatch['analysis'], 'tran_demo')
        self.assertNotIn('last_status', mismatch)

    def test_rescan_is_idempotent_and_leaves_inputs_unchanged(self):
        before_hashes = fixture_hashes()
        before_events = self.db.execute('SELECT count(*) FROM events').fetchone()[0]
        before_cursor = status(self.db)['cursor']
        collect(self.db, self.configs)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], before_events)
        self.assertEqual(status(self.db)['cursor'], before_cursor)
        self.assertEqual(fixture_hashes(), before_hashes)


if __name__ == '__main__':
    unittest.main()
