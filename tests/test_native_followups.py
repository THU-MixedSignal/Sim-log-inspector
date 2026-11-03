"""Follow-ups from the native Spectre review: the progress meter, parsed frame counts,
uncoded tags outside Spectre blocks, evidence from older generations and the phases of
non-transient analyses.

Native fixtures are replayed read-only. The DC, AC and Monte Carlo lines below are
hand-written in the layout of local native Spectre 21.1.0.509 logs (banners, headers,
meters, iteration lines); those logs themselves are not part of the repository.
"""
import json
import tempfile
import unittest
from pathlib import Path

from simcheck import render
from simcheck.parser import METER, initial, meter_cells, parse
from simcheck.store import connect, details, evidence, measurement_page, problem_groups, scan, status

FIX = Path(__file__).parent / 'fixtures'
LIVE = FIX / 'live_20261103'


def replay(path, until=None):
    """Parser state after the first `until` lines of a log."""
    state = initial()
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines()[:until], 1):
        parse(line, state, n)
    return state


def states(lines):
    state, seen = initial(), []
    for n, line in enumerate(lines, 1):
        parse(line, state, n)
        seen.append(dict(state))
    return seen


class Logged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        self.log = self.p / 'spectre.out'
        self.db = connect(self.p / 'events.db')
        self.c = {'id': 'run', 'log': str(self.log)}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def write(self, text, mode='w'):
        with self.log.open(mode, encoding='utf-8', newline='') as f:
            f.write(text)

    def run_state(self):
        return status(self.db)['runs'][0]

    def groups(self):
        return {g['problem_key']: g for g in problem_groups(self.db, 'run', limit=500)}


class ProgressMeter(Logged):
    def test_native_meter_lines(self):
        # adc-a-tt logs no "time =" after its transient starts: the meter is its only progress.
        adc = LIVE / 'adc-a-tt.log'
        self.assertEqual([replay(adc, n)['meter'] for n in (223, 224, 265, 266, 267, 268)],
                         [None, 0, 0, 31, 50, 70])
        self.assertIsNone(replay(adc)['last_time_s'])
        self.assertEqual(replay(LIVE / 'rc-normal.log')['meter'], 70)
        self.assertEqual(replay(LIVE / 'tran-minstep.log')['meter'], 17)
        # Negative: numbered advice at column 0 ("10. Try ...", minstep.log:298) is not a meter.
        self.assertEqual(replay(FIX / 'minstep.log')['meter'], 0)
        self.assertEqual(meter_cells('10. Try to simplify the nonlinear component models'), 0)
        self.assertEqual(meter_cells('             .probe 0     '), 0)
        self.assertEqual(meter_cells('......9......8......7......6...R4MEAS,0,231,8'), 31)
        self.assertEqual(meter_cells(METER + 'R4MEAS,2,183'), 70)

    def test_meter_tracks_the_testbench_frame_time(self):
        # The testbench prints each frame's own time (tenth R4MEAS value) right after the meter.
        state, frames = initial(), 0
        for n, line in enumerate((FIX / 'noise.log').read_text(encoding='utf-8').splitlines(), 1):
            parse(line, state, n)
            if line[:1] == '.' and 'R4MEAS,' in line:
                frame_time = float(line.split('R4MEAS,', 1)[1].split(',')[9])
                stop = state['analyses'][state['analysis']]['stop_time_s']
                # Within one of the 70 cells; on this run the meter ran up to 0.76 points ahead.
                self.assertLess(abs(state['meter'] / len(METER) - frame_time / stop), 1 / len(METER), n)
                frames += 1
        self.assertEqual((frames, state['meter']), (70, 70))

    def test_meter_restarts_per_analysis_and_ignores_other_dots(self):
        seen = states(['.option before any analysis',
                       '*********************************************',
                       "DC Analysis `dc1': vcm = (1e-03 -> 809e-03)",
                       '*********************************************',
                       '......9......8.',
                       '',
                       "Warning from spectre at vcm = 181e-03 during DC analysis `dc1'.",
                       '......9......8..',
                       '    .probe 0',
                       '1              0.00% ',
                       '10. Try to simplify the circuit.',
                       '**************************************************',
                       "AC Analysis `ac1': freq = (1 MHz -> 2 MHz)",
                       '......9'])
        self.assertEqual([s['meter'] for s in seen], [None, None, 0, 0, 15, 15, 15, 16, 16, 16, 16, 16, 0, 7])

    def test_unfinished_last_line_is_read_but_not_indexed(self):
        lines = (LIVE / 'adc-a-tt.log').read_text(encoding='utf-8').splitlines(True)
        first, second = lines[265], lines[266]  # log lines 266 and 267: meter then R4MEAS frame 0 / 1
        self.write(''.join(lines[:265]) + first[:40])
        scan(self.db, self.c)
        run = self.run_state()
        self.assertEqual((run['state'], run.get('t'), run['meter'], run.get('frames')), ('unknown', None, 44.3, None))
        self.assertIn('tran_perf meter 44% of 359ns', render.status(status(self.db)))
        # Spectre reprints the meter after each newline; a half-written reprint never lowers it.
        self.write(first[40:] + second[:20], 'a')
        scan(self.db, self.c)
        run = self.run_state()
        self.assertEqual((run['meter'], run['frames']), (44.3, {'n': 1, 'frame': 0, 'code': 231}))
        self.write(second[20:], 'a')
        scan(self.db, self.c)
        run = self.run_state()
        self.assertEqual((run['meter'], run['frames']), (71.4, {'n': 2, 'frame': 1, 'code': 44}))
        self.assertIn('frames 2 last 1 code 44', render.status(status(self.db)))
        self.write(''.join(lines[267:]), 'a')
        scan(self.db, self.c)
        run = self.run_state()  # Complete: the footer says enough, no progress is shown.
        self.assertEqual((run['state'], 'meter' in run, run['frames']['n']), ('complete', False, 3))

    def test_meter_is_shown_only_when_ahead_of_logged_time(self):
        self.write(''.join((LIVE / 'tran-minstep.log').read_text(encoding='utf-8').splitlines(True)[:-3]))
        scan(self.db, self.c)
        run = self.run_state()  # 17 cells (24.3 %) are behind the logged 5.00081 ns of 20 ns (25.0 %).
        self.assertEqual((run['t'], run['pct'], 'meter' in run), (5.00081e-09, 25.0041, False))


class FrameCounts(Logged):
    def test_other_testbench_lines_are_not_frames(self):
        # Native tb-records: frames 0, 1 and 2 (valid=0) parse; "R4MEAS,3,broken", FAIL and PASS lines do not.
        self.c.update(log=str(LIVE / 'tb-records.log'), analysis='tran_live')
        scan(self.db, self.c)
        self.assertEqual(self.run_state()['frames'], {'n': 3, 'other': 3, 'frame': 2, 'code': 23})
        self.assertEqual(measurement_page(self.db, 'run')['total'], 6)
        self.assertIn('frames 3 (+3 other TB lines)', render.status(status(self.db)))

    def test_only_raw_lines(self):
        self.write('PASS, all frames reported\n' + 'spectre completes with 0 errors, 0 warnings, and 0 notices.\n')
        scan(self.db, self.c)
        self.assertEqual(self.run_state()['frames'], {'n': 0, 'other': 1})


class UncodedTags(Logged):
    FOOT = 'spectre completes with 0 errors, 1 warnings, and 0 notices.\n'

    def test_testbench_tag_lines_are_evidence_not_spectre_errors(self):
        self.write("Warning from spectre at time = 2 ns during transient analysis `tran'.\n"
                   '    WARNING (X-1): native\n'
                   'ERROR: frame 1 code 24 does not match the expected code 25\n'
                   'FATAL: testbench gave up\n' + self.FOOT)
        scan(self.db, self.c)
        self.assertEqual(self.run_state()['state'], 'complete')
        groups = self.groups()
        self.assertEqual({k: g['severity'] for k, g in groups.items()},
                         {'X-1': 'WARNING', 'TB:reported_ERROR': 'INFO', 'TB:reported_FATAL': 'INFO'})
        e = evidence(self.db, groups['TB:reported_ERROR']['first_evidence_id'])
        self.assertEqual((e['line'], e['raw']), (3, 'ERROR: frame 1 code 24 does not match the expected code 25'))
        self.assertIn('not counted as a Spectre message', e['limitation'])
        self.assertNotIn('cont', evidence(self.db, groups['X-1']['first_evidence_id']))
        self.assertEqual(measurement_page(self.db, 'run')['total'], 2)

    def test_spectre_tags_still_count(self):
        # Positive: an uncoded FATAL indented under Spectre's header, and a coded tag anywhere.
        for text in ('Fatal error found by spectre during topology check.\n    FATAL: loop of rigid branches\n',
                     'ERROR (SFE-23): model not found\n'):
            with self.subTest(text=text):
                self.write(text + self.FOOT)
                scan(self.db, self.c)
                self.assertEqual(self.run_state()['state'], 'failed')
        for name, line in (('live_20261103/topology.log', 88), ('live_20261103/output-limit.log', 175),
                           ('live_20261103/wall-limit.log', 176), ('output_limit.log', 289)):
            with self.subTest(name=name):
                state, found = initial(), []
                for n, text in enumerate((FIX / name).read_text(encoding='utf-8').splitlines(), 1):
                    found += [e for e in parse(text, state, n) if n == line]
                self.assertEqual([(e['kind'], e['severity'], e['code']) for e in found],
                                 [('native_message', 'FATAL', None)])


class OlderGenerations(Logged):
    def test_replaced_log_marks_its_old_evidence(self):
        self.write('WARNING (X-1): first run\n')
        scan(self.db, self.c)
        old = self.groups()['X-1']['first_evidence_id']
        self.write('WARNING (X-2): second run, different content\n')
        self.assertEqual(scan(self.db, self.c)['generation'], 2)
        e = evidence(self.db, old)
        self.assertEqual((e['gen'], e['latest_gen'], e['replaced'], e['raw']), (1, 2, True, 'WARNING (X-1): first run'))
        self.assertIn('the log was replaced since', render.evidence(e))
        current = evidence(self.db, self.groups()['X-2']['first_evidence_id'])
        self.assertEqual(current['gen'], 2)  # current generation: no marks
        self.assertFalse({'latest_gen', 'replaced'} & set(current))
        self.assertNotIn('generation', render.evidence(current))

    def test_appended_attempt_keeps_its_line(self):
        self.write('Spectre (R) Circuit Simulator\nWARNING (X-1): a\n')
        scan(self.db, self.c)
        old = self.groups()['X-1']['first_evidence_id']
        self.write('Spectre (R) Circuit Simulator\nWARNING (X-2): b\n', 'a')
        self.assertEqual(scan(self.db, self.c)['generation'], 2)
        e = evidence(self.db, old)
        self.assertEqual((e['gen'], e['latest_gen'], 'replaced' in e), (1, 2, False))
        self.assertEqual(self.log.read_text(encoding='utf-8').splitlines()[e['line'] - 1], e['raw'])
        self.assertIn('(earlier attempt, generation 1; now 2)', render.evidence(e))
        # A cursor written before file_generation existed cannot tell: warn rather than trust the line.
        cursor = json.loads(self.db.execute("SELECT cursor FROM runs WHERE id='run'").fetchone()[0])
        del cursor['file_generation']
        self.db.execute("UPDATE runs SET cursor=? WHERE id='run'", (json.dumps(cursor),))
        self.db.commit()
        self.assertTrue(evidence(self.db, old)['replaced'])


class NonTransientAnalyses(Logged):
    DC = ['Warning from spectre during hierarchy flattening.',
          "    WARNING (SFE-1131): Scope option `scalefactor' specified with scope `TopCircuit' twice.",
          '',
          'Analysis and control statement inventory:',
          '                 dc 1     ',
          '',
          '*********************************************',
          "DC Analysis `dc1': vcm = (1e-03 -> 809e-03)",
          '*********************************************',
          '',
          'Important parameter values:',
          '    reltol = 100e-06',
          '......9......8.',
          '',
          "Warning from spectre at vcm = 181e-03 during DC analysis `dc1'.",
          '    WARNING (CMI-2753): M1: Vgb(=991 mV) has exceeded vgb_max(=990 mV).',
          '    WARNING (CMI-2753): M2: Vgb(=1.001 V) has exceeded vgb_max(=990 mV).',
          '        Further occurrences of this warning will be suppressed.',
          '',
          '......9......8..']
    DC_END = [METER,
              'Accumulated DC solution time =            0 s.',
              '',
              "Notice from spectre at vcm = 809e-03 during DC analysis `dc1'.",
              "    The value of parameter 'vcm' has been reset to the original value 0.405.",
              '',
              "Total time required for dc analysis `dc1': CPU = 105.765 ms, elapsed = 106.255 ms.",
              'spectre completes with 0 errors, 3 warnings, and 1 notices.']

    def test_dc_sweep_problems_belong_to_the_dc_analysis(self):
        self.write('\n'.join(self.DC) + '\n')
        scan(self.db, self.c)
        run = self.run_state()
        self.assertEqual((run['analysis'], 'stop' in run, 't' in run, run['meter']), ('dc1', False, False, 22.9))
        self.assertIn('dc1 meter 23%', render.status(status(self.db)))
        self.write('\n'.join(self.DC_END) + '\n', 'a')
        scan(self.db, self.c)
        groups = self.groups()
        self.assertEqual(groups['CMI-2753']['phase'], 'dc1')
        self.assertTrue(groups['CMI-2753']['suppressed_after'])
        self.assertIsNone(groups['CMI-2753']['first_sim_time_s'])  # a sweep point is not a time
        self.assertEqual(groups['SFE-1131']['phase'], 'setup')
        self.assertEqual(groups["NOTICE:The value of parameter 'vcm' has been reset to the original value #."]['phase'],
                         'dc1')
        self.assertEqual(self.run_state()['state'], 'complete')
        d = details(self.db, 'run')
        self.assertNotIn('stops', d)  # a DC sweep has no stop time
        self.assertIn({'name': 'reltol', 'eff': '100e-06'}, d['settings'])

    def test_monte_carlo_failure_names_the_inner_ac_analysis(self):
        self.write('\n'.join([
            '***************************************************',
            "Monte Carlo Analysis `mc1': iteration = (1 -> 2)",
            '***************************************************',
            "**** Performing monte carlo loop for `mc1'",
            '',
            '1              0.00% ',
            '',
            "Warning from spectre at iteration = 1 during AC analysis `ac1', during Monte Carlo analysis `mc1'.",
            '    WARNING (SPECTRE-16002): Monte Carlo iteration 1 terminated prematurely because of the following error(s):',
            "Error found by spectre at iteration = 1 during AC analysis `ac1', during Monte Carlo analysis `mc1'.",
            '    ERROR (SPECTRE-16108): ac1: Stop limit must not equal start limit.',
            '',
            "Analysis `ac1' was terminated prematurely due to an error.",
            '2             50.00% ',
            '    mc1: iteration = 2           (50 %), step = 1            (50 %)',
            "Total time required for montecarlo analysis `mc1': CPU = 21.555 ms, elapsed = 24.873 ms.",
            'spectre completes with 1 errors, 1 warnings, and 0 notices.']) + '\n')
        r = scan(self.db, self.c)
        groups = self.groups()
        self.assertEqual({k: g['phase'] for k, g in groups.items()},
                         {'SPECTRE-16108': 'ac1', 'premature_termination': 'ac1', 'SPECTRE-16002': 'ac1'})
        self.assertEqual(r['integrity']['status'], 'failed')
        # The AC analysis printed no banner; "Analysis `ac1' was terminated" is not one either.
        self.assertEqual(r['parser']['analyses'], {'mc1': {'kind': 'Monte Carlo', 'stop_time_s': None, 'line': 2}})
        self.assertEqual((r['parser']['meter'], r['parser']['last_time_s']), (0, None))

    def test_ac_and_dc_reports_are_not_simulation_time(self):
        seen = states(["Monte Carlo Analysis `mc2': iteration = (1 -> 1)",
                       "AC Analysis `ac2': freq = (1 MHz -> 2 MHz)",
                       'DC simulation time: CPU = 2.543 ms, elapsed = 2.54893 ms.',
                       METER,
                       'Accumulated DC solution time =            0 s.',
                       'Intrinsic ac analysis time =              0 s.',
                       "Total time required for ac analysis `ac2': CPU = 9.016 ms, elapsed = 9.48095 ms.",
                       "DC Analysis `dc2'",
                       'Important parameter values:',
                       '    reltol = 1e-03',
                       "Total time required for dc analysis `dc2': CPU = 2.936 ms, elapsed = 3.60703 ms."])
        self.assertEqual([(s['analysis'], s['meter'], s['last_time_s']) for s in seen[3:8]],
                         [('ac2', 70, None), ('ac2', 70, None), ('ac2', 70, None), ('ac2', 70, None), ('dc2', 0, None)])
        self.assertEqual(seen[-1]['analysis'], 'dc2')
        self.assertIn('dc2:effective:reltol', seen[-1]['settings'])

    def test_transient_phases_unchanged(self):
        # Negative: body text "during DC analysis." names no analysis; IC notices stay in the transient.
        seen = states(["Transient Analysis `tran1': time = (0 s -> 20 ns)",
                       "Notice from spectre during IC analysis, during transient analysis `tran1'.",
                       '    GminDC = 1 pS is large enough to noticeably affect the DC solution.',
                       '    Bad pivoting is found during DC analysis. Option dc_pivot_check=yes is recommended.',
                       'Accumulated DC solution time =            0 s.',
                       "Warning from spectre at time = 5 ns during transient analysis `tran1'.",
                       '    WARNING (X-1): late'])
        self.assertEqual({s['analysis'] for s in seen}, {'tran1'})
        self.assertEqual(seen[-1]['last_time_s'], 5e-9)
        self.assertEqual(seen[-1]['analyses'], {'tran1': {'kind': 'Transient', 'stop_time_s': 2e-08, 'line': 1}})


if __name__ == '__main__':
    unittest.main()
