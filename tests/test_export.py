"""Saved snapshots keep original evidence and its limits, independently of live inputs."""
import json
import tempfile
import unittest
from pathlib import Path

from simcheck.export import export_file
from simcheck.store import collect, connect, manifest, open_readonly, scan

ROOT = Path(__file__).resolve().parents[1]


class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / 'examples.sqlite'
        with connect(cls.path) as db:
            collect(db, manifest(ROOT / 'examples/synthetic-cases.json')['runs'])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def save(self, run, format='json', path=None):
        with open_readonly(path or self.path) as db:
            file, name, kind = export_file(db, run, format)
            self.assertTrue(db.in_transaction)
            with file:
                return file.read().decode('utf-8'), name, kind

    def test_json_has_every_collected_event_and_original_locations(self):
        text, name, kind = self.save('demo-warning')
        saved = json.loads(text)
        self.assertTrue(saved['export_complete'])
        self.assertEqual((saved['export_version'], saved['v']), (1, 4))
        self.assertTrue(name.startswith('demo-warning-g1-'))
        self.assertTrue(name.endswith('.json'))
        self.assertEqual(kind, 'application/json; charset=utf-8')
        self.assertFalse(saved['scope']['source_files_embedded'])
        self.assertEqual(saved['scope']['events'], len(saved['events']))
        with open_readonly(self.path) as db:
            for event in saved['events']:
                source = Path(event['source_path']).read_bytes()
                raw = source[event['byte_offset']:].splitlines()[0].decode()
                self.assertEqual(event['raw'], raw)
                self.assertEqual(event['run_id'], 'demo-warning')
                self.assertEqual(event['generation'], 1)
            self.assertEqual(db.total_changes, 0)
        self.assertTrue(any('Further occurrences' in e['raw'] for e in saved['events']))
        self.assertTrue(any(e.get('reported_valid') == 0 for e in saved['events']))
        untimed = next(g for g in saved['problems']['groups'] if g['key'] == 'DEMO-99')
        self.assertNotIn('t', untimed)
        self.assertTrue(saved['coverage']['limitations'])

    def test_unknown_incomplete_and_fatal_do_not_become_passes(self):
        expected = {'demo-no-footer': 'unknown', 'demo-raw-incomplete': 'incomplete',
                    'demo-analysis-mismatch': 'incomplete', 'demo-fatal-exit0': 'failed'}
        for run, state in expected.items():
            with self.subTest(run=run):
                data = json.loads(self.save(run)[0])
                self.assertEqual(data['summary']['state'], state)
                self.assertEqual(data['problems']['state'], state)
                html = self.save(run, 'html')[0]
                self.assertIn(f'>{state}</p>', html)
                self.assertIn('Snapshot export complete.', html)
        self.assertTrue(any(e.get('severity') == 'FATAL' for e in data['events']))

    def test_export_survives_source_log_becoming_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'read-once.log'
            path = Path(tmp) / 'db.sqlite'
            raw = '    WARNING (SAVE-1): stored original evidence'
            log.write_text('Warning from spectre during transient analysis `tran\'.\n' + raw + '\n', encoding='utf-8')
            with connect(path) as db:
                scan(db, {'id': 'kept', 'log': str(log)})
            log.unlink()
            data = json.loads(self.save('kept', path=path)[0])
            event = next(e for e in data['events'] if e.get('code') == 'SAVE-1')
            self.assertEqual((event['raw'], event['source_path'], event['line']), (raw, str(log), 2))

    def test_more_than_one_measurement_page_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'many.log'
            path = Path(tmp) / 'db.sqlite'
            log.write_text(''.join(f'R4MEAS,{i},24,8,8,8,16,24,1\n' for i in range(503)), encoding='utf-8')
            with connect(path) as db:
                scan(db, {'id': 'many', 'log': str(log)})
            saved = json.loads(self.save('many', path=path)[0])
            frames = [e['frame'] for e in saved['events'] if 'frame' in e]
            text, _, kind = self.save('many', 'txt', path)
            self.assertTrue(kind.startswith('text/plain'))
            for event in saved['events']:
                self.assertIn(f"e{event['event_id']}  {log}:{event['line']}  {event['raw']}\n", text)
            self.assertEqual(frames, list(range(503)))
            html = self.save('many', 'html', path)[0]
            self.assertIn('R4MEAS,502,24,8,8,8,16,24,1', html)

    def test_only_the_current_generation_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'rotated.log'
            path = Path(tmp) / 'db.sqlite'
            old = 'Warning from spectre during transient analysis `tran\'.\n    WARNING (OLD-1): earlier generation\n'
            log.write_text(old, encoding='utf-8')
            config = {'id': 'rotated', 'log': str(log)}
            with connect(path) as db:
                scan(db, config)
                log.write_text('spectre completes with 0 errors, 0 warnings, and 0 notices.\n', encoding='utf-8')
                scan(db, config)
            data = json.loads(self.save('rotated', path=path)[0])
            self.assertEqual(data['scope']['generation'], 2)
            self.assertTrue(all(e['generation'] == 2 for e in data['events']))
            self.assertNotIn('OLD-1', json.dumps(data))

    def test_unknown_runs_and_invalid_formats_are_rejected(self):
        with open_readonly(self.path) as db:
            with self.assertRaisesRegex(ValueError, 'format'):
                export_file(db, 'demo-warning', 'exe')
            with self.assertRaises(LookupError):
                export_file(db, 'missing')

    def test_untrusted_run_names_are_escaped_and_safe_as_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'safe.log'
            path = Path(tmp) / 'db.sqlite'
            run = '../../保存\r\nInjected: <script>bad</script>'
            log.write_text('spectre completes with 0 errors, 0 warnings, and 0 notices.\n', encoding='utf-8')
            with connect(path) as db:
                scan(db, {'id': run, 'log': str(log)})
            html, name, _ = self.save(run, 'html', path)
            self.assertRegex(name, r'^[A-Za-z0-9_.-]+\.html$')
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', html)
            self.assertEqual(json.loads(self.save(run, path=path)[0])['run'], run)


if __name__ == '__main__':
    unittest.main()
