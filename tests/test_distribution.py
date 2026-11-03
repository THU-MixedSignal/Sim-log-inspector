"""Relocatable demo delivery and refusal to export unrecorded/tampered inputs."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.package_handoff import FIX, PATH_FIELDS, SOURCE_MANIFEST, stage_demo
from simcheck.store import collect, connect, manifest, status


class Distribution(unittest.TestCase):
    def test_demo_runs_after_export_to_a_different_folder(self):
        with tempfile.TemporaryDirectory(prefix='simcheck moved space ') as tmp:
            target = Path(tmp) / 'demo'
            stage_demo(target)
            configs = manifest(target / 'manifest.json')['runs']
            for config in configs:
                for key in PATH_FIELDS:
                    if key in config:
                        self.assertEqual(Path(config[key]).parent, target / 'fixtures')
            with connect(Path(tmp) / 'runtime.sqlite') as db:
                collect(db, configs)
                observed = {r['run']: r['state'] for r in status(db)['runs']}
            self.assertEqual(observed, {'demo-complete': 'complete', 'demo-warning': 'running',
                                       'demo-fatal-exit0': 'failed', 'demo-no-footer': 'unknown',
                                       'demo-raw-incomplete': 'incomplete',
                                       'demo-analysis-mismatch': 'incomplete'})
            names = {p.name for p in (target / 'fixtures').iterdir()}
            meta = json.loads((FIX / 'provenance.json').read_text(encoding='utf-8'))
            self.assertEqual(names, set(meta['files']) | {'provenance.json'})

    def test_manifest_cannot_export_an_unrecorded_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
            data['runs'][0]['log'] = str(base / 'unrecorded.log')
            source = base / 'manifest.json'
            source.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'recorded synthetic'):
                stage_demo(base / 'demo', source)
            self.assertFalse((base / 'demo').exists())

    def test_altered_demo_copy_is_not_exported_as_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            copied = base / 'fixtures'
            shutil.copytree(FIX, copied)
            (copied / 'warning.log').write_text('Altered synthetic copy\n', encoding='utf-8')
            data = json.loads(SOURCE_MANIFEST.read_text(encoding='utf-8'))
            for run in data['runs']:
                for key in PATH_FIELDS:
                    if key in run:
                        run[key] = str(copied / Path(run[key]).name)
            source = base / 'manifest.json'
            source.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
                stage_demo(base / 'demo', source, copied)
            self.assertFalse((base / 'demo').exists())


if __name__ == '__main__':
    unittest.main()
