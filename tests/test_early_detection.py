"""Early-detection behaviour: what becomes visible, when, who is told, and how compactly."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from simcheck import render, store
from simcheck.parser import initial, parse
from simcheck.store import (collect, collector_status, connect, detect_changes, evidence, heartbeat,
                            manifest, problem_groups, retire, scan, show, snapshot, status, wait_for_change)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests' / 'fixtures'
FOOT = 'spectre completes with 0 errors, 0 warnings, and 0 notices.\n'
NEWTON = 'NOTICE:Newton iteration fails to converge at time = # ps step = # s.'
FLOATING = 'NOTICE:Only one connection to the following # nodes:'
SOA = ['CMI-2751', 'CMI-2752', 'CMI-2753', 'CMI-2754', 'CMI-2755']


def parse_lines(lines):
    state = initial()
    return [e for n, l in enumerate(lines, 1) for e in parse(l, state, n)], state


def brief(db, run):
    return next(r for r in snapshot(db)['runs'] if r['run_id'] == run)


def empty_values(value, path='$'):
    """Paths of null/false/empty values; the agent contract omits those keys instead."""
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'live':
                continue  # collector liveness is reported either way
            if v is None or v is False or (isinstance(v, (str, list, dict)) and not v):
                found.append(f'{path}.{k}')
            found += empty_values(v, f'{path}.{k}')
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += empty_values(v, f'{path}[{i}]')
    return found


class Fixture(unittest.TestCase):
    """One temporary database with selected real fixture logs indexed."""
    runs = ()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / 'db.sqlite')
        for name in self.runs:
            scan(self.db, {'id': name, 'log': str(FIX / (name + '.log')),
                           'state': str(FIX / (name + '.state.json'))})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def group(self, run, key):
        return next(g for g in problem_groups(self.db, run, limit=500) if g['problem_key'] == key)


class HeaderScopedTime(Fixture):
    runs = ('noise',)

    def test_message_time_comes_from_its_own_header(self):
        out, state = parse_lines(["Warning from spectre at time = 5 ns during transient analysis `tran'.",
                                  '    WARNING (A-1): timed',
                                  "Warning from spectre during transient analysis `tran'.",
                                  '    WARNING (B-2): untimed'])
        timed, untimed = [e for e in out if e['kind'] == 'native_message']
        self.assertAlmostEqual(timed['sim_time_s'], 5e-9)
        self.assertEqual(timed['header_line'], 1)
        self.assertIsNone(untimed['sim_time_s'])  # never inherited from the previous block
        self.assertEqual(untimed['header_line'], 3)
        self.assertAlmostEqual(state['last_time_s'], 5e-9)  # progress context is kept separately

    def test_real_untimed_header(self):
        swap = self.group('noise', 'SPECTRE-555')
        e = evidence(self.db, swap['first_evidence_id'])
        self.assertNotIn('t', e)
        self.assertEqual(e['header']['raw'], "Warning from spectre during transient analysis `tran_perf'.")
        self.assertIsNone(swap['first_sim_time_s'])
        cmi = self.group('noise', 'CMI-2754')
        self.assertAlmostEqual(evidence(self.db, cmi['first_evidence_id'])['t'], 60.0961e-9)


class Notices(Fixture):
    runs = ('minstep', 'noise', 'license')

    def test_minstep_notices_are_captured_without_escalation(self):
        newton = self.group('minstep', NEWTON)
        self.assertEqual((newton['severity'], newton['printed_count'], newton['phase']),
                         ('NOTICE', 5, 'tran_test'))
        self.assertAlmostEqual(newton['first_sim_time_s'], 95.0439e-12)
        self.assertAlmostEqual(newton['first_fraction'], 95.0439e-12 / 820e-9)
        self.assertTrue(newton['suppressed_after'])
        self.assertEqual(newton['severity_source'], 'header')
        floating = evidence(self.db, self.group('minstep', FLOATING)['first_evidence_id'])
        self.assertEqual([c['raw'].strip() for c in floating['cont']], ['DO_7', 'DO_6', 'DO_5', 'DO_4', 'DO_3'])
        self.assertIn('Further occurrences of this notice will be suppressed', floating['suppression']['raw'])
        run = brief(self.db, 'minstep')
        self.assertEqual(run['coverage']['suppressed_totals'], {'notice': 195})
        self.assertEqual(run['problems']['by_severity']['NOTICE'], 11)
        self.assertEqual(run['problems']['by_severity']['ERROR'], 2)  # SPECTRE-16927 + premature termination
        self.assertEqual(run['state']['status'], 'failed')

    def test_notices_never_change_completion(self):
        noise = brief(self.db, 'noise')
        self.assertEqual(noise['state']['status'], 'complete')
        self.assertGreater(noise['problems']['by_severity']['NOTICE'], 0)
        self.assertNotIn('ERROR', noise['problems']['by_severity'])

    def test_suppression_totals_are_not_notices(self):
        keys = [g['problem_key'] for r in ('noise', 'minstep') for g in problem_groups(self.db, r, limit=500)]
        self.assertFalse([k for k in keys if 'suppressed' in k])

    def test_license_wait_is_visible(self):
        keys = [g['problem_key'] for g in problem_groups(self.db, 'license', limit=500)]
        self.assertIn('NOTICE:Waiting for available license for Spectre.', keys)

    def test_indented_text_outside_a_header_block_is_not_a_message(self):
        out, state = parse_lines(['Important parameter values:', '    step = 820 ps', '    method = trap',
                                  'Reading file:  /x', '    indented free text'])
        self.assertFalse([e for e in out if e['kind'] == 'native_message'])
        self.assertIn('None:effective:method', state['settings'])


class Suppression(Fixture):
    runs = ('noise',)

    def test_per_code_suppression_is_attached_to_the_last_printed_message(self):
        cmi = self.group('noise', 'CMI-2754')
        self.assertTrue(cmi['suppressed_after'])
        first = evidence(self.db, cmi['first_evidence_id'])
        self.assertNotIn('suppression', first)
        self.assertEqual(first['group'], {'n': 5, 'sup': True, 'first': cmi['first_evidence_id'],
                                          'last': cmi['last_evidence_id']})
        last = evidence(self.db, cmi['last_evidence_id'])
        self.assertIn('Further occurrences of this warning will be suppressed', last['suppression']['raw'])
        self.assertFalse(self.group('noise', 'SFE-1131')['suppressed_after'])


class FirstAppearance(Fixture):
    runs = ('noise', 'a_fft')

    def test_stop_time_phase_and_first_appearance(self):
        run = brief(self.db, 'noise')
        self.assertAlmostEqual(run['state']['stop_time_s'], 103.259e-6)
        soa = self.group('noise', 'CMI-2755')
        self.assertEqual(soa['phase'], 'tran_perf')
        self.assertAlmostEqual(soa['first_sim_time_s'], 60.096e-9)
        self.assertAlmostEqual(soa['first_fraction'], 60.096e-9 / 103.259e-6)
        self.assertIsInstance(soa['first_observed_epoch'], float)
        setup = self.group('noise', 'SFE-1131')
        self.assertEqual(setup['phase'], 'setup')
        self.assertIsNone(setup['first_sim_time_s'])


class Examples(unittest.TestCase):
    """The 8 real logs through the example manifest, as an agent would see them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db = connect(Path(cls.tmp.name) / 'db.sqlite')
        collect(cls.db, manifest(ROOT / 'examples' / 'real-fixtures.json')['runs'])
        cls.snap = snapshot(cls.db)
        cls.runs = {r['run_id']: r for r in cls.snap['runs']}
        cls.digest = status(cls.db)
        cls.by_id = {r['run']: r for r in cls.digest['runs']}

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def test_example_rules(self):
        noise = self.runs['noise']
        self.assertEqual(sorted(h['problem_key'] for h in noise['rule_hits'] if h['rule'].startswith('SOA')), SOA)
        self.assertIn('rule', noise['attention'])
        self.assertEqual(self.runs['a_fft']['rule_hits'], [])  # same testbench, no SOA messages
        self.assertEqual(self.runs['a_fft']['attention'], [])
        self.assertEqual([h['problem_key'] for h in self.runs['minstep']['rule_hits']], [NEWTON])

    def test_baseline_lists_only_keys_missing_from_the_reference(self):
        missing = {k['problem_key'] for k in self.runs['noise']['baseline']['keys_not_in_baseline']}
        self.assertTrue({'CMI-2751', 'CMI-2755', 'SPECTRE-555'} <= missing)
        self.assertNotIn('SFE-1131', missing)
        self.assertIsNone(self.runs['a_fft']['baseline'])
        self.assertIsNone(self.runs['minstep']['baseline'])

    def test_rule_thresholds(self):
        groups = [{'problem_key': 'X-1', 'code': 'X-1', 'severity': 'WARNING', 'printed_count': 1,
                   'message': 'slow node', 'first_evidence_id': 1, 'first_sim_time_s': None,
                   'first_fraction': None}]
        self.assertEqual(store.rule_hits([{'name': 'r', 'code': 'X-*', 'min_count': 2}], groups), [])
        self.assertEqual(store.rule_hits([{'name': 'r', 'code': 'X-*', 'severity': 'ERROR'}], groups), [])
        self.assertEqual(store.rule_hits([{'name': 'r', 'text': 'SLOW'}], groups)[0]['problem_key'], 'X-1')

    def test_status_is_small_and_omits_empty_fields(self):
        size = len(json.dumps(self.digest, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        self.assertLess(size, 5000)  # 8 runs; v0.3 sent about 18 KB for the same logs
        self.assertEqual(empty_values(self.digest), [])
        self.assertLess(len(render.status(self.digest).encode('utf-8')), 3500)
        self.assertNotIn('t', self.by_id['noise'])  # progress is not repeated once a run completed normally

    def test_attention_first_and_failed_runs_lead_with_their_first_errors(self):
        order = [r['run'] for r in self.digest['runs']]
        self.assertEqual(order, ['compile', 'license', 'minstep', 'output_limit', 'b_fft', 'noise', 'static', 'a_fft'])
        self.assertNotIn('flags', self.by_id['a_fft'])
        minstep = self.by_id['minstep']
        self.assertEqual([g['key'] for g in minstep['errors']], ['SPECTRE-16927', 'premature_termination'])
        self.assertEqual((minstep['errors'][0]['t'], minstep['errors'][0]['pct']), (1.14929e-09, 0.1402))
        self.assertEqual(minstep['rules'][0]['keys'], [NEWTON])
        output = self.by_id['output_limit']
        self.assertEqual([g['key'] for g in output['errors']], ['SPECTRE-27', 'SPECTRE-7082'])  # log order
        self.assertEqual(output['n']['E'], 4)
        noise = self.by_id['noise']
        self.assertEqual(sorted(noise['rules'][0]['keys']), SOA)
        self.assertAlmostEqual(noise['rules'][0]['t'], 60.096e-9)
        self.assertEqual(noise['base'], {'ref': 'a_fft', 'new': SOA, 'n': 6})

    def test_show_lists_notices_only_when_a_rule_names_them(self):
        brief_view = show(self.db, 'minstep')
        keys = [g['key'] for g in brief_view['groups']]
        self.assertIn(NEWTON, keys)
        self.assertNotIn(FLOATING, keys)
        self.assertGreater(brief_view['hidden_notices'], 0)
        self.assertEqual(empty_values(brief_view), [])
        self.assertIn(FLOATING, [g['key'] for g in show(self.db, 'minstep', full=True)['groups']])
        noise = {g['key']: g for g in show(self.db, 'noise')['groups']}
        self.assertTrue(noise['CMI-2751']['base_new'])
        self.assertNotIn('base_new', noise['SFE-1131'])
        self.assertEqual(noise['CMI-2754']['rules'], ['SOA limit'])

    def test_text_points_to_handles_and_locations(self):
        minstep = self.by_id['minstep']
        first = minstep['errors'][0]['e']
        text = render.status(self.digest)
        self.assertIn(f"cursor {self.digest['cursor']}", text.splitlines()[0])
        self.assertIn(f'e{first} ERROR SPECTRE-16927 x1 @1.14929ns (0.140%):', text)
        self.assertIn(f'e{first} SPECTRE-16927 x1 @1.14929ns (0.140%):', render.show(show(self.db, 'minstep')))
        cmi = next(g for g in show(self.db, 'noise')['groups'] if g['key'] == 'CMI-2754')
        lines = render.evidence(evidence(self.db, cmi['e'])).splitlines()
        self.assertTrue(lines[1].endswith('noise.log:276'))
        self.assertTrue(lines[2].startswith('  275 Warning from spectre at time = 60.0961 ns'))
        self.assertTrue(lines[3].startswith('> 276     WARNING (CMI-2754):'))


class Liveness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.log = self.p / 'spectre.out'
        self.db = connect(self.p / 'db.sqlite')
        self.c = {'id': 'live', 'log': str(self.log), 'quiet_after_s': 600}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def age(self, seconds):
        old = time.time() - seconds
        os.utime(self.log, (old, old))

    def test_quiet_log_is_reported_only_while_not_ended(self):
        self.log.write_text('WARNING (X-1): running\n')
        self.age(7200)
        scan(self.db, self.c)
        run = brief(self.db, 'live')
        self.assertIn('quiet', run['attention'])
        self.assertGreater(run['state']['quiet_for_s'], 7000)
        self.assertGreater(status(self.db)['runs'][0]['log_age'], 7000)
        with self.log.open('a') as f:
            f.write(FOOT)
        self.age(7200)
        scan(self.db, self.c)
        run = brief(self.db, 'live')
        self.assertTrue(run['state']['ended'])
        self.assertNotIn('quiet', run['attention'])
        self.assertNotIn('log_age', status(self.db)['runs'][0])

    def test_collector_heartbeat(self):
        self.assertFalse(collector_status(self.db)['alive'])
        heartbeat(self.db, time.time(), 2, port=8765)
        state = collector_status(self.db)
        self.assertTrue(state['alive'])
        self.assertEqual((state['pid'], state['port']), (os.getpid(), 8765))
        self.db.execute('UPDATE collectors SET heartbeat=heartbeat-100')
        self.db.commit()
        self.assertFalse(collector_status(self.db)['alive'])
        retire(self.db)
        self.assertIsNone(collector_status(self.db)['pid'])

    def test_bad_sidecar_is_contained(self):
        self.log.write_text(FOOT)
        bad = self.p / 'state.json'
        bad.write_text('[]')
        r = scan(self.db, dict(self.c, state=str(bad)))
        self.assertEqual(r['integrity']['status'], 'incomplete')
        self.assertEqual(r['integrity']['checks'][0]['detail'], 'state JSON is not an object')

    def test_one_failing_run_does_not_block_the_others(self):
        self.log.write_text(FOOT)
        other = self.p / 'other.out'
        other.write_text('WARNING (Y-1): fine\n' + FOOT)
        real = store.inspect

        def flaky(config, *args):
            if config['id'] == 'live':
                raise RuntimeError('boom')
            return real(config, *args)

        configs = [self.c, {'id': 'other', 'log': str(other)}]
        with mock.patch.object(store, 'inspect', flaky):
            results = collect(self.db, configs)
        self.assertIn('boom', results['live']['collector_error'])
        runs = {r['run_id']: r for r in snapshot(self.db)['runs']}
        self.assertEqual(runs['other']['state']['status'], 'complete')
        self.assertIn('collector_error', runs['live']['attention'])
        self.assertIn('boom', status(self.db, ['live'])['runs'][0]['error'])
        collect(self.db, configs)
        self.assertNotIn('collector_error', brief(self.db, 'live')['attention'])
        with self.assertRaises(LookupError):
            status(self.db, ['missing'])


class Waiting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.path = self.p / 'db.sqlite'
        self.log = self.p / 'spectre.out'
        self.log.write_text("Warning from spectre at time = 1 ns during transient analysis `tran'.\n"
                            '    WARNING (X-1): first\n')
        self.db = connect(self.path)
        self.c = {'id': 'live', 'log': str(self.log), 'watch': [{'name': 'Z rule', 'code': 'Z-*'}]}
        scan(self.db, self.c)
        heartbeat(self.db, time.time(), 2)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def append(self, text):
        with self.log.open('a') as f:
            f.write(text)
        scan(self.db, self.c)

    def test_new_groups_wake_known_repeats_do_not(self):
        base = snapshot(self.db)
        after = base['last_event_id']
        self.append("Warning from spectre at time = 9 ns during transient analysis `tran'.\n"
                    '    WARNING (X-1): again\n')
        self.assertEqual(detect_changes(self.db, base, after)[1], [])
        repeats = detect_changes(self.db, base, after, repeats=True)[1]
        self.assertEqual([c['type'] for c in repeats], ['more'])
        self.append('    WARNING (Y-2): new kind\n')
        changes = detect_changes(self.db, base, after)[1]
        self.assertEqual([(c['type'], c['key']) for c in changes], [('new', 'Y-2')])
        self.assertAlmostEqual(changes[0]['t'], 9e-9)
        self.assertEqual(empty_values(changes), [])
        self.append('Notice from spectre during transient analysis `tran\'.\n    Something informational.\n')
        self.assertEqual(len(detect_changes(self.db, base, after)[1]), 1)
        self.assertEqual(len(detect_changes(self.db, base, after, notices=True)[1]), 2)

    def test_a_new_group_that_hits_a_rule_is_one_change(self):
        base = snapshot(self.db)
        self.append('    WARNING (Z-9): watched\n')
        changes = detect_changes(self.db, base, base['last_event_id'])[1]
        self.assertEqual([(c['type'], c['key'], c.get('rules')) for c in changes], [('new', 'Z-9', ['Z rule'])])
        self.assertIn('rule=Z rule', render.change_line(changes[0]))

    def test_status_change_and_stable_token(self):
        base = snapshot(self.db)
        scan(self.db, self.c)
        self.assertEqual(snapshot(self.db)['token'], base['token'])  # observation time alone is not a change
        self.append(FOOT)
        current, changes = detect_changes(self.db, base, base['last_event_id'])
        self.assertIn({'type': 'status', 'run': 'live', 'from': 'unknown', 'to': 'complete'}, changes)
        self.assertNotEqual(current['token'], base['token'])

    def test_wait_wakes_times_out_and_needs_a_collector(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 4:
                self.append('    ERROR (E-3): stopped\n')

        result, code = wait_for_change(self.path, timeout=60, interval=2, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(code, 0)
        self.assertEqual([c['type'] for c in result['changes']], ['status', 'new'])
        self.assertEqual(result['changes'][0]['to'], 'failed')
        self.assertEqual(set(result), {'v', 'changed', 'changes', 'cursor'})  # no run summaries attached
        text = render.wait(result)
        self.assertIn(f"next: simcheck wait --cursor {result['cursor']}", text)
        quiet, code = wait_for_change(self.path, cursor=result['cursor'], timeout=5, interval=2,
                                      clock=lambda: clock[0], sleep=sleep)
        self.assertEqual((code, quiet['reason']), (3, 'timeout'))
        stale = result['cursor'].split('.')[0] + '.000000000000'
        moved, code = wait_for_change(self.path, cursor=stale, timeout=5, interval=2,
                                      clock=lambda: clock[0], sleep=sleep)
        self.assertEqual((code, moved['changes'][0]['type']), (0, 'state_changed'))
        with self.assertRaises(ValueError):
            wait_for_change(self.path, cursor='later', timeout=1)
        retire(self.db)
        offline, code = wait_for_change(self.path, timeout=5)
        self.assertEqual((code, offline['reason']), (4, 'collector_offline'))
        self.assertIn('no collector running', render.wait(offline))


if __name__ == '__main__':
    unittest.main()
