import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cli
import core
import reader
import runtime
import setup_ui
import temporary


class ScriptedTerminal:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.titles = []

    def choose(self, title, choices, selected=(), multiple=False):
        self.titles.append(title)
        return next(self.actions)

    def text(self, prompt, default=''):
        result = next(self.actions)
        if result == 'cancel':
            raise setup_ui.Cancelled()
        return result


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.data = self.root / 'data'
        self.detected = {s: {'status': 'Test status'} for s in setup_ui.SOURCES}

    def tearDown(self):
        self.temp.cleanup()

    def wizard(self, actions, old=None):
        return setup_ui.wizard(old, self.data, self.root, self.detected,
                               terminal=ScriptedTerminal(actions))

    def test_cancel_at_each_screen_leaves_preferences_and_reports_unchanged(self):
        self.data.mkdir()
        settings = self.data / 'preferences.json'
        settings.write_text('{"untouched":true}')
        report = self.data / 'report.md'
        report.write_text('user edits')
        for actions in ([setup_ui.BACK], [[0], 'cancel'], [[0], str(self.work), 0, 'cancel'],
                        [[0], str(self.work), 0, str(self.data), 0, setup_ui.BACK, 'cancel'],
                        [[0], str(self.work), 0, str(self.data), 0, 0, 2]):
            with patch.object(core, 'computer_zone', return_value='Asia/Shanghai'), patch('sys.stdout', io.StringIO()):
                self.assertIsNone(self.wizard(actions))
            self.assertEqual(settings.read_text(), '{"untouched":true}')
            self.assertEqual(report.read_text(), 'user edits')

    def test_back_changes_source_and_final_save_is_only_mutation_boundary(self):
        actions = [[0], setup_ui.BACK, [6], 'excluded-chat', str(self.data), 0, 0, 0]
        with patch.object(core, 'computer_zone', return_value='UTC'), patch('sys.stdout', io.StringIO()):
            cfg = self.wizard(actions)
        self.assertEqual(cfg['sources'], ['chatgpt'])
        self.assertEqual(cfg['chat_excludes'], ['excluded-chat'])
        self.assertEqual(cfg['roots'], [])
        self.assertIn(str(self.root), cfg['excludes'])
        self.assertIn(str(self.data), cfg['excludes'])
        self.assertFalse(self.data.exists())

    def test_existing_preferences_prefill_without_enabling_new_sources(self):
        old = {'sources': ['codex'], 'timezone': 'UTC', 'timezone_mode': 'fixed',
               'roots': [str(self.work)], 'model_preference': {'policy': 'inherit'},
               'schedule': {'start_date': '2026-10-01', 'automation_id': 'existing'}}
        actions = [[0], str(self.work), 0, str(self.data), 0, 0, 0]
        with patch('sys.stdout', io.StringIO()):
            cfg = self.wizard(actions, old)
        self.assertEqual(cfg['sources'], ['codex'])
        self.assertEqual(cfg['schedule']['automation_id'], 'existing')
        self.assertEqual(cfg['schedule']['start_date'], '2026-10-01')

    def test_invalid_storage_retries_screen(self):
        file = self.root / 'file'
        file.write_text('unrelated')
        actions = [[0], str(self.work), 0, str(file), str(self.data), 0, 0, 0]
        with patch.object(core, 'computer_zone', return_value='UTC'), patch('sys.stdout', io.StringIO()):
            cfg = self.wizard(actions)
        self.assertEqual(cfg['report_dir'], str(self.data))
        self.assertEqual(file.read_text(), 'unrelated')

    def test_invalid_timezone_is_correctable_before_final_save(self):
        actions = [[0], str(self.work), 0, str(self.data), 'Invalid/Zone',
                   str(self.data), 'UTC', 0, 0, 0]
        out = io.StringIO()
        with patch.object(core, 'computer_zone', side_effect=RuntimeError('not detected')), patch('sys.stdout', out):
            cfg = self.wizard(actions)
        self.assertIn('Unknown IANA timezone', out.getvalue())
        self.assertEqual(cfg['timezone'], 'UTC')
        self.assertEqual(cfg['timezone_mode'], 'fixed')
        self.assertFalse(self.data.exists())

    def test_invalid_scripted_timezone_leaves_saved_settings_untouched(self):
        self.data.mkdir()
        settings = self.data / 'preferences.json'
        previous = {'timezone': 'UTC', 'timezone_mode': 'fixed'}
        core.json_write(settings, previous)
        args = ['cli.py', '--data-dir', str(self.data), 'setup', '--source', 'codex',
                '--root', str(self.work), '--zone', 'Invalid/Zone', '--accept-data-notice']
        with patch('sys.argv', args), patch('sys.stdout', io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'Unknown IANA timezone'):
                cli.main()
        self.assertEqual(core.read_json(settings), previous)

    def test_numbered_fallback_empty_is_not_consent_and_eof_cancels(self):
        ui = setup_ui.Terminal(numbered=True)
        with patch('builtins.input', side_effect=['', '9', '1,2']), patch('sys.stdout', io.StringIO()):
            self.assertEqual(ui.choose('Sources', ['a', 'b'], multiple=True), [0, 1])
        with patch('builtins.input', side_effect=EOFError), patch('sys.stdout', io.StringIO()):
            with self.assertRaises(setup_ui.Cancelled):
                ui.choose('Confirm', ['Save', 'Cancel'])

    def test_noninteractive_setup_fails_without_writing(self):
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaises(RuntimeError):
                setup_ui.wizard(None, self.data, self.root, self.detected)
        self.assertFalse(self.data.exists())

    def test_discovery_only_stats_known_locations(self):
        location = self.root / '.codex/sessions'
        location.mkdir(parents=True)
        with patch.object(Path, 'read_text', side_effect=AssertionError('No content reads')):
            detected = cli.discover(self.root)
        self.assertTrue(detected['codex']['exists'])
        self.assertEqual(detected['chatgpt']['status'], 'Check in desktop; separate opt-in')

    def test_unsupported_platform_error(self):
        with patch.object(sys, 'platform', 'win32'):
            with self.assertRaisesRegex(RuntimeError, 'Unsupported platform'):
                cli.platform_check()


class ScopeRuntimeTests(unittest.TestCase):
    def test_malformed_runtime_fields_are_rejected_before_collection(self):
        for evidence in ([], {'model': {'name': 'invented'}}, {'history_tools': [{}]},
                         {'available_models': ['valid', {}]}):
            with self.subTest(evidence=evidence), patch.object(reader, 'collect') as collect:
                with self.assertRaises(ValueError):
                    cli.prepare('/synthetic', {'sources': ['codex'], 'data_notice_accepted': True},
                                '2026-10-08', evidence=evidence)
                collect.assert_not_called()

    def test_disabled_local_sources_are_never_called(self):
        names = ['_read_codex', '_read_claude', '_read_kimi', '_read_opencode', '_read_hermes', '_read_cursor']
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(reader, name, side_effect=AssertionError('disabled reader accessed')))
            data = reader.collect('2026-10-08', 'UTC', [], home='/synthetic', enabled_sources=[])
        self.assertEqual(data['records'], [])
        self.assertTrue(all(c['status'] == 'disabled' for c in data['coverage']))

    def test_only_selected_reader_runs(self):
        with patch.object(reader, '_read_codex', side_effect=AssertionError('disabled')):
            with patch.object(reader, '_read_opencode') as selected:
                data = reader.collect('2026-10-08', 'UTC', [], home='/synthetic', enabled_sources=['opencode'])
        selected.assert_called_once()
        self.assertEqual(next(c for c in data['coverage'] if c['source'] == 'codex')['status'], 'disabled')

    def test_excluded_chat_turns_are_not_accessed(self):
        class Envelope(dict):
            def get(self, key, default=None):
                if key == 'turns':
                    raise AssertionError('Excluded body read')
                return super().get(key, default)
        pages = [Envelope(thread={'id': 'excluded'})]
        data = reader.desktop_pages(pages, '2026-10-08', 'UTC', ['excluded'])
        self.assertEqual(data['records'], [])
        self.assertEqual(data['coverage'][0]['excluded_sessions'], 1)

    def test_disabled_desktop_file_is_not_opened(self):
        cfg = {'sources': ['codex'], 'data_notice_accepted': True}
        with patch.object(core, 'read_json', side_effect=AssertionError('must not open pages')):
            with self.assertRaisesRegex(RuntimeError, 'not selected'):
                cli.prepare('/synthetic', cfg, '2026-10-08', '/unselected-pages.json')

    def test_inherit_records_unknown_without_runtime_evidence(self):
        details = runtime.require_ready({'sources': ['codex']})
        self.assertEqual(details['requested']['policy'], 'inherit')
        self.assertEqual(details['observed'], {'model': 'unknown', 'reasoning': 'unknown', 'host': 'unknown'})

    def test_specific_model_stays_pending_without_host_catalog_or_switch(self):
        cfg = {'sources': ['codex'], 'model_preference': {'policy': 'specific', 'model': 'requested'}}
        for evidence in (None, {'model': 'other', 'available_models': ['requested'], 'catalog_source': 'host'},
                         {'model': 'requested', 'available_models': ['requested'], 'catalog_source': 'cache'}):
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                runtime.require_ready(cfg, evidence)
        evidence = {'model': 'requested', 'available_models': ['requested'], 'catalog_source': 'host'}
        self.assertFalse(runtime.require_ready(cfg, evidence)['pending'])

    def test_host_selected_model_can_be_verified_without_a_catalog_capability(self):
        cfg = {'sources': ['codex'], 'model_preference': {'policy': 'specific', 'model': 'requested'}}
        evidence = {'model': 'requested', 'host': 'desktop', 'model_source': 'host'}
        self.assertFalse(runtime.require_ready(cfg, evidence)['pending'])

    def test_chatgpt_requires_actual_tool_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'history tools'):
            runtime.require_ready({'sources': ['chatgpt']}, {'model': 'available'})
        evidence = {'history_tools': list(runtime.HISTORY_TOOLS)}
        self.assertFalse(runtime.require_ready({'sources': ['chatgpt']}, evidence)['pending'])

    def test_scheduled_run_records_its_own_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = {'sources': ['codex'], 'model_preference': {'policy': 'inherit'},
                   'data_notice_accepted': True, 'timezone': 'UTC',
                   'roots': [str(root)], 'excludes': []}
            # Simulated desktop contexts exercise preparation AND persistent
            # report metadata. This does not prove native automation execution.
            for key, model, reasoning in (('2026-10-07', 'manual', 'high'),
                                          ('2026-10-08', 'scheduled', 'low')):
                evidence = {'model': model, 'reasoning': reasoning, 'host': 'desktop'}
                with patch.object(reader, 'collect', return_value={'records': [], 'coverage': []}):
                    prepared = cli.prepare(root, cfg, key, evidence=evidence)
                directory = Path(prepared['temporary_directory'])
                manifest = core.read_json(directory / 'manifest.json')
                core.commit(root, key, 'Synthetic report for ' + model, manifest)
                temporary.cleanup(root, directory)
            manual = core.completion(root, '2026-10-07')['runtime_details']
            scheduled = core.completion(root, '2026-10-08')['runtime_details']
            self.assertEqual(manual['observed']['model'], 'manual')
            self.assertEqual(scheduled['observed']['model'], 'scheduled')
            self.assertEqual(scheduled['observed']['reasoning'], 'low')
            self.assertEqual(cfg['model_preference'], {'policy': 'inherit'})


class StorageGuardTests(unittest.TestCase):
    def test_nested_storage_rejected_external_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills/day-recap"
            skill.mkdir(parents=True)
            outside = root / "data"
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, skill / "reports", outside)
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, outside, skill / "prefs")
            core.ensure_storage_outside_skill(skill, outside, outside)

    def test_symlink_into_skill_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills/day-recap"
            skill.mkdir(parents=True)
            outside = root / "data"
            outside.mkdir()
            link = root / "link"
            link.symlink_to(skill, target_is_directory=True)
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, link / "reports", outside)

    def test_ancestor_and_relative_nesting_into_skill_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            skill = root / "skills/day-recap"
            skill.mkdir(parents=True)
            outside = root / "data"
            outside.mkdir()
            # A symlinked ancestor that resolves back inside the skill.
            alias = root / "alias"
            alias.symlink_to(skill, target_is_directory=True)
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, alias / "nested/reports", outside)
            # A lexical .. that canonicalizes back inside the skill.
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, skill / ".." / "day-recap" / "prefs", outside)
            # A plain descendant is rejected for both storage kinds.
            with self.assertRaises(ValueError):
                core.ensure_storage_outside_skill(skill, outside, skill / "prefs")


class TemporaryTests(unittest.TestCase):
    def test_unverified_attempt_is_visible_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            attempt = root / '.temporary/attempt-interrupted'
            attempt.mkdir(parents=True)
            (attempt / 'synthetic.json').write_text('synthetic data')
            result = temporary.pending(root)
            self.assertEqual(result[0]['ownership'], 'unverified')
            with self.assertRaises(ValueError):
                temporary.cleanup(root, attempt)
            self.assertEqual((attempt / 'synthetic.json').read_text(), 'synthetic data')

    def test_owned_cleanup_preserves_unrelated_and_recovers_interrupted_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unrelated = root / '.temporary/unrelated'
            unrelated.mkdir(parents=True)
            (unrelated / 'body').write_text('preserve')
            attempt = temporary.create(root, '2026-10-08')
            (attempt / 'segment.json').write_text('synthetic body')
            self.assertEqual(temporary.pending(root)[0]['directory'], str(attempt))
            temporary.cleanup(root, attempt)
            self.assertFalse(attempt.exists())
            self.assertEqual((unrelated / 'body').read_text(), 'preserve')
            with self.assertRaises(ValueError):
                temporary.cleanup(root, unrelated)

    def test_cleanup_rejects_external_paths_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owned = temporary.create(root, '2026-10-08')
            link = owned.parent / 'attempt-link'
            link.symlink_to(owned, target_is_directory=True)
            for path in (root, link):
                with self.assertRaises(ValueError):
                    temporary.cleanup(root, path)
            self.assertTrue(owned.exists())

    def test_real_cli_commit_cleans_owned_attempt_and_reuse_is_delivery_aware(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = {'timezone': 'UTC', 'timezone_mode': 'fixed', 'sources': ['opencode'],
                   'roots': [str(root)], 'excludes': [], 'data_notice_accepted': True}
            core.json_write(root / 'preferences.json', cfg)
            with patch.object(reader, 'collect', return_value={'records': [], 'coverage': []}):
                prep = cli.prepare(root, cfg, '2026-10-08')
            task = Path(prep['temporary_directory'])
            draft = task / 'draft.md'
            draft.write_text('Synthetic report')
            with patch('sys.argv', ['cli.py', '--data-dir', str(root), 'commit', '2026-10-08',
                                    '--draft', str(draft), '--manifest', str(task / 'manifest.json')]), patch('sys.stdout', io.StringIO()):
                cli.main()
            self.assertFalse(task.exists())
            self.assertTrue(cli.reuse(root, '2026-10-08')['display_required'])
            core.delivered(root, '2026-10-08')
            self.assertFalse(cli.reuse(root, '2026-10-08')['display_required'])


if __name__ == '__main__':
    unittest.main()
