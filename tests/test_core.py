import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meta = {'timezone': 'Asia/Shanghai', 'coverage': [], 'segments': []}

    def tearDown(self):
        self.temp.cleanup()

    def test_reuse_edits_and_candidate(self):
        core.commit(self.root, '2026-10-08', 'original', self.meta)
        path = core.report_path(self.root, '2026-10-08')
        path.write_text('user edit')
        reused = core.commit(self.root, '2026-10-08', 'new', self.meta)
        self.assertEqual(reused['status'], 'reused')
        self.assertTrue(reused['edited'])
        self.assertEqual(path.read_text(), 'user edit')
        candidate = core.commit(self.root, '2026-10-08', 'new', self.meta, True)
        self.assertEqual(Path(candidate['path']).read_text(), 'new')
        self.assertEqual(path.read_text(), 'user edit')

    def test_interrupted_metadata_recovers_matching_report(self):
        original = core.json_write
        writes = []
        def interrupted(path, data):
            writes.append(path)
            if len(writes) == 2:
                raise OSError('interrupted')
            original(path, data)
        with patch.object(core, 'json_write', side_effect=interrupted):
            with self.assertRaises(OSError):
                core.commit(self.root, '2026-10-08', 'saved text', self.meta)
        self.assertTrue(core.completion(self.root, '2026-10-08')['recovered'])
        self.assertEqual(core.commit(self.root, '2026-10-08', 'replacement', self.meta)['status'], 'reused')
        self.assertEqual(core.report_path(self.root, '2026-10-08').read_text(), 'saved text')

    def test_promote_keeps_user_edits_in_backup(self):
        core.commit(self.root, '2026-10-08', 'original', self.meta)
        path = core.report_path(self.root, '2026-10-08')
        path.write_text('my edits')
        core.commit(self.root, '2026-10-08', 'new report', self.meta, True)
        result = core.promote(self.root, '2026-10-08')
        self.assertEqual(path.read_text(), 'new report')
        self.assertEqual(Path(result['previous']).read_text(), 'my edits')

    def test_pending_sleep_catchup_and_delivery(self):
        cfg = {'timezone': 'Asia/Shanghai', 'schedule': {'start_date': '2026-10-05', 'daily_time': '06:00'}}
        before = core.pending(self.root, cfg, datetime(2026, 10, 8, 21, 59, tzinfo=timezone.utc))
        self.assertEqual(before['daily'], ['2026-10-05', '2026-10-06', '2026-10-07'])
        after = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertEqual(after['daily'][-1], '2026-10-11')
        self.assertEqual(after['weekly'], ['2026-W41'])
        core.commit(self.root, '2026-10-05', 'done', self.meta)
        resumed = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertNotIn('2026-10-05', resumed['daily'])
        self.assertIn('2026-10-05', resumed['delivery'])
        core.delivered(self.root, '2026-10-05')
        self.assertNotIn('2026-10-05', core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))['delivery'])

    def test_iso_week_year_and_missing_partial_days(self):
        self.assertEqual(core.prior_week(datetime(2021, 1, 4).date()), '2020-W53')
        meta = {**self.meta, 'coverage': [{'source': 'chatgpt', 'status': 'partial'}]}
        core.commit(self.root, '2020-12-28', 'only Monday', meta)
        data = core.weekly_input(self.root, '2020-W53')
        self.assertEqual(len(data['missing_days']), 6)
        self.assertEqual(data['partial_days'], ['2020-12-28'])
        self.assertEqual(len(data['days']), 1)
        self.assertIn('2020', str(core.report_path(self.root, '2020-W53')))

    def test_manifest_contains_no_transcript(self):
        record = {'source': 'codex', 'session_id': 's', 'message_id': 'm', 'text': 'private body',
                  'timestamp': '2026-10-08T00:00:00Z', 'kind': 'message', 'title': 'Topic'}
        manifest = core.provenance({'records': [record], 'coverage': []}, [[record]])
        self.assertNotIn('private body', str(manifest))
        self.assertEqual(manifest['segments'][0]['characters'], 12)

    def test_atomic_failure_preserves_previous_text(self):
        path = self.root / 'report.md'
        core.atomic(path, 'old')
        with patch.object(core.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                core.atomic(path, 'new')
        self.assertEqual(path.read_text(), 'old')
        self.assertEqual(list(self.root.glob('.recap-*')), [])


if __name__ == '__main__':
    unittest.main()
