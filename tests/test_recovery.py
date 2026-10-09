import sys
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meta = {'timezone': 'Asia/Shanghai', 'coverage': [], 'segments': []}

    def tearDown(self):
        self.temp.cleanup()

    def _report(self, key='2026-10-08'):
        return core.report_path(self.root, key)

    def _candidate(self, key='2026-10-08'):
        path = self._report(key)
        return path.with_name(path.stem + '.candidate.md')

    def test_two_refresh_promotion_cycles_succeed(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        first = core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertEqual(Path(first['previous']).read_text(), 'v1')
        self.assertFalse(self._candidate(key).exists())
        self.assertFalse(self._candidate(key).with_suffix('.meta.json').exists())
        self.assertFalse(core._journal_path(self.root, key).exists())

        core.commit(self.root, key, 'v3 candidate', self.meta, True)
        second = core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v3 candidate')
        self.assertEqual(Path(second['previous']).read_text(), 'v2 candidate')
        self.assertNotEqual(first['previous'], second['previous'])
        self.assertFalse(self._candidate(key).exists())
        self.assertFalse(self._candidate(key).with_suffix('.meta.json').exists())

    def test_backup_every_prior_canonical_including_user_edits(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        self._report(key).write_text('user edited v1')
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        result = core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertEqual(Path(result['previous']).read_text(), 'user edited v1')

    def test_commit_refresh_recovers_pending_promotion_before_new_candidate(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        meta = core.read_json(self._candidate(key).with_suffix('.meta.json'))
        core._journal_intent(self.root, key, meta, self._candidate(key).read_text())
        # Interrupt before any canonical replacement happens.
        candidate = core.commit(self.root, key, 'v3 candidate', self.meta, True)
        self.assertEqual(Path(candidate['path']).read_text(), 'v3 candidate')
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertFalse(core._journal_path(self.root, key).exists())
        backups = list(self._report(key).parent.glob('2026-10-08.previous-*.md'))
        self.assertTrue(any(b.read_text() == 'v1' for b in backups))

    def test_interruption_between_backup_and_canonical_is_resumed(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        real_atomic = core.atomic
        calls = []

        def failing_atomic(path, content):
            calls.append(Path(path))
            if Path(path).name.startswith('2026-10-08.md'):
                raise OSError('interrupted before canonical save')
            return real_atomic(path, content)

        with patch.object(core, 'atomic', side_effect=failing_atomic):
            with self.assertRaises(OSError):
                core.promote(self.root, key)
        # Backup exists, canonical still original, journal still present.
        self.assertEqual(self._report(key).read_text(), 'v1')
        self.assertTrue(core._journal_path(self.root, key).exists())
        backups = list(self._report(key).parent.glob('2026-10-08.previous-*.md'))
        self.assertTrue(any(b.read_text() == 'v1' for b in backups))
        # A refresh must resume the pending promotion, not create a new candidate blind.
        result = core._resume_promotion(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertFalse(core._journal_path(self.root, key).exists())
        self.assertFalse(self._candidate(key).exists())
        self.assertFalse(self._candidate(key).with_suffix('.meta.json').exists())
        self.assertTrue(result['previous'])

    def test_interruption_before_state_save_is_resumed(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        real_write_state = core._write_state

        def failing_state(root, k, status='saved', delivery='pending'):
            raise OSError('interrupted during state save')

        with patch.object(core, '_write_state', side_effect=failing_state):
            with self.assertRaises(OSError):
                core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertTrue(core._journal_path(self.root, key).exists())
        core._resume_promotion(self.root, key)
        state = core.read_json(self.root / 'state.json')
        self.assertEqual(state['reports'][key]['status'], 'saved')
        self.assertEqual(state['reports'][key]['delivery'], 'pending')
        self.assertFalse(core._journal_path(self.root, key).exists())
        self.assertFalse(self._candidate(key).exists())

    def test_interruption_during_candidate_cleanup_is_resumed(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        real_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if self.name.endswith('.candidate.md'):
                raise OSError('interrupted during cleanup')
            return real_unlink(self, *args, **kwargs)

        with patch.object(Path, 'unlink', failing_unlink):
            with self.assertRaises(OSError):
                core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')
        self.assertTrue(core._journal_path(self.root, key).exists())
        self.assertTrue(self._candidate(key).exists())
        resumed = core.recover(self.root, key)
        self.assertEqual(resumed['status'], 'promoted')
        self.assertFalse(self._candidate(key).exists())
        self.assertFalse(core._journal_path(self.root, key).exists())
        self.assertEqual(self._report(key).read_text(), 'v2 candidate')

    def test_edited_canonical_rejected_safely(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        self._report(key).write_text('intervening user edit')
        with self.assertRaises(RuntimeError):
            core.promote(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'intervening user edit')
        self.assertTrue(self._candidate(key).exists())

    def test_edited_canonical_after_intent_rejected_on_resume(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        meta = core.read_json(self._candidate(key).with_suffix('.meta.json'))
        core._journal_intent(self.root, key, meta, self._candidate(key).read_text())
        self._report(key).write_text('intervening edit after intent')
        with self.assertRaises(RuntimeError):
            core._resume_promotion(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'intervening edit after intent')
        self.assertTrue(core._journal_path(self.root, key).exists())

    def test_edited_candidate_rejected_on_resume(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        meta = core.read_json(self._candidate(key).with_suffix('.meta.json'))
        core._journal_intent(self.root, key, meta, self._candidate(key).read_text())
        self._candidate(key).write_text('tampered candidate')
        with self.assertRaises(RuntimeError):
            core._resume_promotion(self.root, key)
        self.assertEqual(self._report(key).read_text(), 'v1')

    def test_only_consumed_candidate_and_metadata_removed(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        sibling = self._report(key).with_name('unrelated.candidate.md')
        sibling.write_text('unrelated')
        core.promote(self.root, key)
        self.assertTrue(sibling.exists())
        self.assertFalse(self._candidate(key).exists())
        self.assertFalse(self._candidate(key).with_suffix('.meta.json').exists())

    def test_pending_delivery_retry_and_single_notice(self):
        cfg = {'timezone': 'Asia/Shanghai',
               'schedule': {'start_date': '2026-10-05', 'daily_time': '06:00'}}
        self.assertTrue(core.start_notice(self.root, '2026-10-05'))
        first = core.read_json(self.root / 'state.json')['reports']['2026-10-05']['start_notice_at']
        self.assertFalse(core.start_notice(self.root, '2026-10-05'))
        second = core.read_json(self.root / 'state.json')['reports']['2026-10-05']['start_notice_at']
        self.assertEqual(first, second)
        core.commit(self.root, '2026-10-05', 'done', self.meta)
        state = core.read_json(self.root / 'state.json')['reports']['2026-10-05']
        self.assertEqual(state['start_notice_at'], first)
        self.assertEqual(state['delivery'], 'pending')
        due = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertIn('2026-10-05', due['delivery'])
        self.assertNotIn('2026-10-05', due['daily'])
        core.delivered(self.root, '2026-10-05')
        quiet = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertNotIn('2026-10-05', quiet['delivery'])

    def test_saved_reports_reused_and_delivered_stay_quiet(self):
        cfg = {'timezone': 'Asia/Shanghai',
               'schedule': {'start_date': '2026-10-05', 'daily_time': '06:00'}}
        core.commit(self.root, '2026-10-05', 'v1', self.meta)
        reused = core.commit(self.root, '2026-10-05', 'ignored', self.meta)
        self.assertEqual(reused['status'], 'reused')
        self.assertEqual(reused['delivery'], 'pending')
        due = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertIn('2026-10-05', due['delivery'])
        core.delivered(self.root, '2026-10-05')
        again = core.commit(self.root, '2026-10-05', 'ignored again', self.meta)
        self.assertEqual(again['status'], 'reused')
        self.assertEqual(again['delivery'], 'delivered')
        quiet = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertNotIn('2026-10-05', quiet['delivery'])

    def test_refresh_candidate_excluded_from_scheduled_delivery(self):
        cfg = {'timezone': 'Asia/Shanghai',
               'schedule': {'start_date': '2026-10-05', 'daily_time': '06:00'}}
        core.commit(self.root, '2026-10-05', 'v1', self.meta)
        core.commit(self.root, '2026-10-05', 'v2 candidate', self.meta, True)
        due = core.pending(self.root, cfg, datetime(2026, 10, 12, 1, tzinfo=timezone.utc))
        self.assertIn('2026-10-05', due['delivery'])
        self.assertNotIn('2026-10-05', due['daily'])
        # Candidate itself is not part of scheduled delivery.
        self.assertEqual(core.completion(self.root, '2026-10-05')['delivery'], 'pending')

    def test_start_notice_timestamp_retained_across_state_updates(self):
        key = '2026-10-08'
        self.assertTrue(core.start_notice(self.root, key))
        original = core.read_json(self.root / 'state.json')['reports'][key]['start_notice_at']
        core.commit(self.root, key, 'report', self.meta)
        state = core.read_json(self.root / 'state.json')['reports'][key]
        self.assertEqual(state['start_notice_at'], original)
        self.assertFalse(core.start_notice(self.root, key))
        self.assertEqual(
            core.read_json(self.root / 'state.json')['reports'][key]['start_notice_at'],
            original,
        )

    def test_delivery_hash_rejects_an_unseen_replacement(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'shown text', self.meta)
        seen = core.digest(self._report(key).read_text())
        core.commit(self.root, key, 'new replacement', self.meta, True)
        core.promote(self.root, key)
        with self.assertRaisesRegex(RuntimeError, 'changed since display'):
            core.delivered(self.root, key, seen)
        self.assertEqual(core.completion(self.root, key)['delivery'], 'pending')
        core.delivered(self.root, key, core.digest('new replacement'))
        self.assertEqual(core.completion(self.root, key)['delivery'], 'delivered')

    def test_every_promotion_checkpoint_can_retry_before_and_after_failure(self):
        key = '2026-10-08'
        # Count real write/cleanup calls, then interrupt each boundary both before
        # and after it. Fresh storage per case keeps prior failures independent.
        operations = []
        real_atomic, real_unlink = core.atomic, core._unlink
        def recording_atomic(path, content):
            operations.append(('atomic', Path(path).name))
            return real_atomic(path, content)
        def recording_unlink(path):
            operations.append(('unlink', Path(path).name))
            return real_unlink(path)
        core.commit(self.root, key, 'original', self.meta)
        core.commit(self.root, key, 'replacement', self.meta, True)
        with patch.object(core, 'atomic', recording_atomic), patch.object(core, '_unlink', recording_unlink):
            core.promote(self.root, key)
        for index in range(len(operations)):
            for after in (False, True):
                with self.subTest(index=index, after=after), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    core.commit(root, key, 'original', self.meta)
                    core.commit(root, key, 'replacement', self.meta, True)
                    counter = [0]
                    def interrupt(function, *args):
                        point = counter[0]
                        counter[0] += 1
                        if point == index and not after:
                            raise OSError('interrupted checkpoint')
                        value = function(*args)
                        if point == index and after:
                            raise OSError('interrupted checkpoint')
                        return value
                    with patch.object(core, 'atomic', side_effect=lambda *a: interrupt(real_atomic, *a)), patch.object(core, '_unlink', side_effect=lambda *a: interrupt(real_unlink, *a)):
                        with self.assertRaises(OSError):
                            core.promote(root, key)
                    if core._journal_path(root, key).exists():
                        core.recover(root, key)
                    elif core._candidate_path(root, key).exists():
                        core.promote(root, key)
                    self.assertEqual(core.report_path(root, key).read_text(), 'replacement')
                    self.assertEqual(core.completion(root, key)['status'], 'saved')
                    self.assertFalse(core._candidate_path(root, key).exists())
                    self.assertFalse(core._candidate_path(root, key).with_suffix('.meta.json').exists())
                    backups = list(core.report_path(root, key).parent.glob('*.previous-*.md'))
                    self.assertEqual([p.read_text() for p in backups], ['original'])
                    core.commit(root, key, 'next refresh', self.meta, True)
                    core.promote(root, key)

    def test_archive_conflicted_candidate_preserves_edits_and_allows_refresh(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'original', self.meta)
        core.commit(self.root, key, 'candidate', self.meta, True)
        meta = core.read_json(self._candidate(key).with_suffix('.meta.json'))
        core._journal_intent(self.root, key, meta, 'candidate')
        self._report(key).write_text('new user edit')
        with self.assertRaises(RuntimeError):
            core.recover(self.root, key)
        result = core.archive_candidate(self.root, key)
        self.assertEqual((Path(result['path']) / self._candidate(key).name).read_text(), 'candidate')
        self.assertEqual(self._report(key).read_text(), 'new user edit')
        self.assertTrue(core.completion(self.root, key)['edited'])
        core.commit(self.root, key, 'new refresh', self.meta, True)
        core.promote(self.root, key)

    def test_unsupported_platform_lock_error_is_readable(self):
        with patch.object(core, 'fcntl', None):
            with self.assertRaises(RuntimeError) as raised:
                with core.locked(self.root):
                    pass
        self.assertIn('not supported', str(raised.exception))

    def test_recovery_validation_rejects_missing_candidate(self):
        key = '2026-10-08'
        core.commit(self.root, key, 'v1', self.meta)
        core.commit(self.root, key, 'v2 candidate', self.meta, True)
        meta = core.read_json(self._candidate(key).with_suffix('.meta.json'))
        core._journal_intent(self.root, key, meta, self._candidate(key).read_text())
        self._candidate(key).unlink()
        with self.assertRaises(RuntimeError):
            core.recover(self.root, key)
        self.assertTrue(core._journal_path(self.root, key).exists())
        self.assertEqual(self._report(key).read_text(), 'v1')


if __name__ == '__main__':
    unittest.main()
