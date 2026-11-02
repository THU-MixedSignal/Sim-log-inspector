"""Early-detection behaviour: what becomes visible, when, and who is told."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from simcheck import store
from simcheck.parser import initial, parse
from simcheck.store import (collect, collector_status, connect, detect_changes, evidence, heartbeat,
                            manifest, problem_groups, retire, scan, summaries, wait_for_change)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests' / 'fixtures'
FOOT = 'spectre completes with 0 errors, 0 warnings, and 0 notices.\n'
NEWTON = 'NOTICE:Newton iteration fails to converge at time = # ps step = # s.'
FLOATING = 'NOTICE:Only one connection to the following # nodes:'


def parse_lines(lines):
    state = initial()
    return [e for n, l in enumerate(lines, 1) for e in parse(l, state, n)], state


def brief(db, run):
    return next(r for r in summaries(db)['runs'] if r['run_id'] == run)


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
        self.assertIsNone(e['observed']['sim_time_s'])
        self.assertEqual(e['header']['raw'], "Warning from spectre during transient analysis `tran_perf'.")
        self.assertIsNone(swap['first_sim_time_s'])
        cmi = self.group('noise', 'CMI-2754')
        self.assertAlmostEqual(evidence(self.db, cmi['first_evidence_id'])['observed']['sim_time_s'], 60.0961e-9)


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
        self.assertEqual([c['raw'].strip() for c in floating['continuation']], ['DO_7', 'DO_6', 'DO_5', 'DO_4', 'DO_3'])
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
        self.assertIsNone(evidence(self.db, cmi['first_evidence_id'])['suppression'])
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


class RulesAndBaseline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.tmp.name) / 'db.sqlite')
        collect(self.db, manifest(ROOT / 'examples' / 'real-fixtures.json')['runs'])
        self.runs = {r['run_id']: r for r in summaries(self.db)['runs']}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_example_rules(self):
        noise = self.runs['noise']
        soa = sorted(h['problem_key'] for h in noise['rule_hits'] if h['rule'].startswith('SOA'))
        self.assertEqual(soa, ['CMI-2751', 'CMI-2752', 'CMI-2753', 'CMI-2754', 'CMI-2755'])
        self.assertIn('rule_hit', noise['attention'])
        self.assertEqual(self.runs['a_fft']['rule_hits'], [])  # same testbench, no SOA messages
        self.assertEqual(self.runs['a_fft']['attention'], [])
        self.assertEqual([h['problem_key'] for h in self.runs['minstep']['rule_hits']], [NEWTON])
        self.assertTrue(all(g['problem_key'].startswith('CMI-') for g in noise['problems']['top']))

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
        self.assertIn('log_quiet', run['attention'])
        self.assertGreater(run['state']['quiet_for_s'], 7000)
        with self.log.open('a') as f:
            f.write(FOOT)
        self.age(7200)
        scan(self.db, self.c)
        run = brief(self.db, 'live')
        self.assertTrue(run['state']['ended'])
        self.assertNotIn('log_quiet', run['attention'])

    def test_collector_heartbeat(self):
        self.assertFalse(collector_status(self.db)['alive'])
        heartbeat(self.db, time.time(), 2, port=8765)
        status = collector_status(self.db)
        self.assertTrue(status['alive'])
        self.assertEqual((status['pid'], status['port']), (os.getpid(), 8765))
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
        runs = {r['run_id']: r for r in summaries(self.db)['runs']}
        self.assertEqual(runs['other']['state']['status'], 'complete')
        self.assertIn('collector_error', runs['live']['attention'])
        collect(self.db, configs)
        self.assertNotIn('collector_error', brief(self.db, 'live')['attention'])


class Waiting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.path = self.p / 'db.sqlite'
        self.log = self.p / 'spectre.out'
        self.log.write_text("Warning from spectre at time = 1 ns during transient analysis `tran'.\n"
                            '    WARNING (X-1): first\n')
        self.db = connect(self.path)
        self.c = {'id': 'live', 'log': str(self.log)}
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
        base = summaries(self.db)
        after = base['last_event_id']
        self.append("Warning from spectre at time = 9 ns during transient analysis `tran'.\n"
                    '    WARNING (X-1): again\n')
        self.assertEqual(detect_changes(self.db, base, after)[1], [])
        repeats = detect_changes(self.db, base, after, repeats=True)[1]
        self.assertEqual([c['type'] for c in repeats], ['more_occurrences'])
        self.append('    WARNING (Y-2): new kind\n')
        changes = detect_changes(self.db, base, after)[1]
        self.assertEqual([(c['type'], c['problem_key']) for c in changes], [('new_problem_group', 'Y-2')])
        self.assertAlmostEqual(changes[0]['first_sim_time_s'], 9e-9)
        self.append('Notice from spectre during transient analysis `tran\'.\n    Something informational.\n')
        self.assertEqual(len(detect_changes(self.db, base, after)[1]), 1)
        self.assertEqual(len(detect_changes(self.db, base, after, notices=True)[1]), 2)

    def test_status_change_and_stable_token(self):
        base = summaries(self.db)
        scan(self.db, self.c)
        self.assertEqual(summaries(self.db)['token'], base['token'])  # observation time alone is not a change
        self.append(FOOT)
        current, changes = detect_changes(self.db, base, base['last_event_id'])
        self.assertIn({'type': 'status', 'run_id': 'live', 'from': 'unknown', 'to': 'complete'}, changes)
        self.assertNotEqual(current['token'], base['token'])

    def test_wait_wakes_times_out_and_needs_a_collector(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= 4:
                self.append('    ERROR (Z-3): stopped\n')

        result, code = wait_for_change(self.path, timeout=60, interval=2,
                                       clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(code, 0)
        self.assertEqual([c['type'] for c in result['changes']], ['status', 'new_problem_group'])
        self.assertEqual(result['runs'][0]['state']['status'], 'failed')
        quiet, code = wait_for_change(self.path, after=result['last_event_id'], since=result['token'],
                                      timeout=5, interval=2, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual((code, quiet['reason']), (3, 'timeout'))
        stale, code = wait_for_change(self.path, since='0' * 12, timeout=5, interval=2,
                                      clock=lambda: clock[0], sleep=sleep)
        self.assertEqual((code, stale['changes'][0]['type']), (0, 'state_changed_since_token'))
        retire(self.db)
        offline, code = wait_for_change(self.path, timeout=5)
        self.assertEqual((code, offline['reason']), (4, 'collector_offline'))


if __name__ == '__main__':
    unittest.main()
