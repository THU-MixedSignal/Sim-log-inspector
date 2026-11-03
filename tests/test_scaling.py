"""Performance invariants exercised through collection and the public query path."""
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from simcheck import cli, store

WARNING = b'    WARNING (X-1): repeated warning\n'
FOOT = b'spectre completes with 0 errors, 0 warnings, and 0 notices.\n'


class Scaling(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / 'db.sqlite'
        self.db = store.connect(self.path)
        self.addCleanup(self.db.close)
        self.log = self.root / 'spectre.out'
        self.cfg = {'id': 'one', 'log': str(self.log)}

    def test_groups_restart_and_transaction_failure(self):
        self.log.write_bytes(WARNING * 2200)
        self.db.execute("CREATE TRIGGER fail_group BEFORE INSERT ON groups BEGIN SELECT raise(abort,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            store.scan(self.db, self.cfg)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
        self.assertIsNone(self.db.execute('SELECT id FROM runs').fetchone())
        self.db.execute('DROP TRIGGER fail_group')
        while store.scan(self.db, self.cfg)['backlog']:
            pass
        with store.connect(self.path) as other:
            writes = other.total_changes
            store.scan(other, self.cfg)
            self.assertEqual(other.total_changes, writes)
            first = store.problem_groups(other, 'one')[0]
            self.assertEqual((first['printed_count'], first['first_evidence_id'], first['last_evidence_id']),
                             (2200, 1, 2200))
            self.assertEqual(store.evidence(other, 2200)['line'], 2200)
            base = store.snapshot(other)
            with patch.object(store, '_run_state', side_effect=AssertionError('idle poll read run')):
                self.assertEqual(store.detect_changes(other, base, 2200)[1], [])

    def test_time_only_transitions_wake(self):
        self.log.write_bytes(WARNING)
        self.cfg['quiet_after_s'] = 2
        store.scan(self.db, self.cfg)
        now = time.time()
        store.heartbeat(self.db, now, 1)
        base = store.snapshot(self.db, now)
        with patch.object(store.time, 'time', return_value=now + 3):
            quiet, changes = store.detect_changes(self.db, base, 1)
        self.assertEqual([c['type'] for c in changes], ['quiet'])
        with patch.object(store.time, 'time', return_value=now + 20):
            self.assertIn('collector_offline', [c['type'] for c in store.detect_changes(self.db, quiet, 1)[1]])

    def test_nul_holds_offset_including_newline(self):
        self.log.write_bytes(WARNING + b'\x00\n' + FOOT)
        r = store.scan(self.db, self.cfg, final=True)
        self.assertEqual(r['indexed_bytes'], len(WARNING))
        self.assertNotEqual(r['integrity']['status'], 'complete')
        with self.log.open('r+b') as f:
            f.seek(len(WARNING))
            f.write(b' \n')
        recovered = store.scan(self.db, self.cfg)
        self.assertEqual(recovered['integrity']['status'], 'complete')
        self.assertEqual(recovered['generation'], r['generation'])
        self.assertEqual(store.problem_groups(self.db, 'one')[0]['printed_count'], 1)

    def test_context_limit_preserves_evidence(self):
        self.log.write_bytes(b"Transient Analysis `tran0': time = (0 s -> 2 ns)\n" + FOOT)
        self.assertEqual(store.scan(self.db, self.cfg)['integrity']['status'], 'complete')
        self.log.write_bytes(b''.join(f"Transient Analysis `tran{i}': time = (0 s -> 2 ns)\n".encode()
                                      for i in range(150)) + FOOT)
        result = store.scan(self.db, self.cfg)
        self.assertEqual(len(result['parser']['analyses']), 128)
        self.assertEqual(result['integrity']['status'], 'incomplete')
        self.assertEqual(result['integrity']['coverage_limited'], 'parser_context_limit')
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE generation=? AND kind='analysis_start'",
                                         (result['generation'],)).fetchone()[0], 150)

    def test_live_discovery_idle_gate_and_sidecar_only_change(self):
        manifest = self.root / 'manifest.json'
        runs = self.root / 'runs'
        runs.mkdir()
        (runs / 'ignore-me').mkdir()
        manifest.write_text(json.dumps({'roots': [{'alias': 'farm', 'root': 'runs', 'log': 'spectre.out',
                                                  'state': 'state.json', 'exclude': ['ignore-*']}]}))
        moment = [0.0]
        def advance(seconds):
            moment[0] += seconds
            folder = runs / 'a'
            if moment[0] >= 2 and not folder.exists():
                folder.mkdir()
                (folder / 'state.json').write_text('{"status":"queued"}')
            if moment[0] >= 35 and not (folder / 'spectre.out').exists():
                (folder / 'spectre.out').touch()
            if moment[0] == 40:
                (folder / 'state.json').write_text('{"status":"running"}')
        class Stop:
            is_set = staticmethod(lambda: moment[0] >= 45)
            wait = staticmethod(advance)
        with patch.object(cli.time, 'monotonic', side_effect=lambda: moment[0]), patch.object(cli, 'scan', wraps=store.scan) as scans:
            cli.collector_loop(self.path, [], 1, Stop(), manifest_path=manifest)
        self.assertEqual(scans.call_count, 3)
        self.assertEqual(store.status(self.db)['runs'][0]['state'], 'running')
        self.assertEqual(self.db.execute('SELECT id FROM runs').fetchone()[0], 'farm/a')

    def test_does_not_create_db_on_recognized_network_filesystem(self):
        target = self.root / 'remote.sqlite'
        with patch.object(store, 'network_fs', return_value=True), self.assertRaisesRegex(ValueError, 'local filesystem'):
            store.connect(target)
        self.assertFalse(target.exists())
