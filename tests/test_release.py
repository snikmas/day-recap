import json
from pathlib import Path
import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import build_bundle
import manage_skill
import release_check

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def legacy_skill(self, directory):
        (directory / 'scripts').mkdir(parents=True)
        (directory / 'SKILL.md').write_text('---\nname: day-recap\n---\n# Daily Recap\n')
        for name in ('cli.py', 'core.py', 'reader.py'):
            (directory / 'scripts' / name).write_text('# Synthetic legacy module\n')

    def stage(self, root):
        for name in ('skill/SKILL.md', 'skill/README.md', 'LICENSE', 'VERSION', *release_check.SCRIPTS):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        return build_bundle.build(root)

    def test_rebuild_preserves_unrelated_file_with_old_temporary_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.stage(root)
            unrelated = root / 'bundle/.day-recap.zip.tmp'
            unrelated.write_text('unrelated user note')
            build_bundle.build(root)
            self.assertEqual(unrelated.read_text(), 'unrelated user note')

    def test_bundle_allowlist_rejects_private_names_without_reading_them(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = self.stage(Path(temp))
            unexpected = bundle / 'preferences.json'
            unexpected.write_text('synthetic settings')
            real_read = Path.read_bytes
            def guarded(path):
                if path == unexpected:
                    raise AssertionError('Do not read a rejected settings file')
                return real_read(path)
            with patch.object(Path, 'read_bytes', guarded):
                with self.assertRaisesRegex(ValueError, 'Unexpected'):
                    release_check.check_directory(bundle)

    def test_private_marker_and_author_path_rejected(self):
        for value in ('/home/example/private', 'sk-' + 'x' * 32, '-----BEGIN PRIVATE KEY-----'):
            with self.assertRaisesRegex(ValueError, 'private'):
                release_check.validate_content('README.md', value.encode())

    def test_archive_extra_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.stage(root)
            path = root / 'bundle/day-recap.zip'
            with ZipFile(path, 'a') as archive:
                archive.writestr('day-recap/reports/personal.md', 'synthetic')
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                release_check.check_zip(path)

    def test_clean_install_setup_sample_two_refreshes_update_and_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            installed = root / 'skills/day-recap'
            data = root / 'data'
            work = root / 'work'
            work.mkdir()
            manage_skill.manage('install', installed, bundle)
            script = installed / 'scripts/cli.py'
            def run(*args):
                result = subprocess.run([sys.executable, '-I', str(script), '--data-dir', str(data), *args],
                                        cwd=installed / 'scripts', capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            run('setup', '--source', 'codex', '--root', str(work), '--zone', 'UTC',
                '--workspace', str(root / 'recap-chat'), '--accept-data-notice')
            prefs = (data / 'preferences.json').read_text()
            run('start-notice', '2026-10-08')
            # This synthetic sample verifies installed storage/delivery mechanics.
            # It does not collect personal histories or prove desktop model access.
            draft = root / 'draft.md'
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'key': '2026-10-08', 'timezone': 'UTC',
                                            'segments': [], 'coverage': [], 'model': 'unknown'}))
            draft.write_text('Synthetic initial sample')
            saved = run('commit', '2026-10-08', '--draft', str(draft), '--manifest', str(manifest))
            report = Path(saved['path'])
            self.assertTrue(run('collect', '2026-10-08')['display_required'])
            run('delivered', '2026-10-08')
            self.assertFalse(run('collect', '2026-10-08')['display_required'])
            for text in ('Synthetic refreshed sample', 'Synthetic second refresh'):
                draft.write_text(text)
                run('commit', '2026-10-08', '--draft', str(draft), '--manifest', str(manifest), '--refresh')
                promoted = run('promote', '2026-10-08')
                self.assertTrue(Path(promoted['previous']).is_file())
                self.assertEqual(report.read_text(), text)
            update = manage_skill.manage('update', installed, bundle)
            self.assertTrue(Path(update['previous']).exists())
            self.assertEqual((data / 'preferences.json').read_text(), prefs)
            self.assertEqual(run('collect', '2026-10-08')['status'], 'reused')
            removed = manage_skill.manage('uninstall', installed)
            self.assertFalse(installed.exists())
            self.assertTrue(Path(removed['archived_skill']).exists())
            self.assertFalse(Path(removed['archived_skill']).is_relative_to(installed.parent))
            self.assertEqual(report.read_text(), 'Synthetic second refresh')
            self.assertEqual((data / 'preferences.json').read_text(), prefs)

    def test_clean_numbered_wizard_saves_only_after_final_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            installed = root / 'skills/day-recap'
            data = root / 'data'
            work = root / 'work'
            work.mkdir()
            manage_skill.manage('install', installed, bundle)
            master, slave = pty.openpty()
            process = subprocess.Popen([sys.executable, '-I', '-u', str(installed / 'scripts/cli.py'),
                                        '--data-dir', str(data), 'setup', '--numbered'],
                                       stdin=slave, stdout=slave, stderr=slave, cwd=work)
            os.close(slave)
            output = b''
            deadline = time.monotonic() + 5
            try:
                while b'Numbers separated' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        output += os.read(master, 65536)
                self.assertFalse((data / 'preferences.json').exists())
                # Choices stop before the final Save confirmation.
                os.write(master, ('1\n' + str(work) + '\n1\n' + str(data) + '\n1\n1\n').encode())
                while b'Review and save' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(b'Review and save', output)
                self.assertFalse((data / 'preferences.json').exists())
                os.write(master, b'1\n')
                while process.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                self.assertEqual(process.wait(timeout=2), 0, output.decode())
                cfg = json.loads((data / 'preferences.json').read_text())
                self.assertEqual(cfg['sources'], ['codex'])
                self.assertEqual(cfg['model_preference'], {'policy': 'inherit'})
                self.assertFalse(cfg['schedule']['enabled'])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)

    def test_update_failure_restores_installed_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'source')
            target = root / 'installed'
            manage_skill.manage('install', target, bundle)
            original = Path.rename
            def interrupted(path, dest):
                if path.name.startswith('.day-recap-install-'):
                    raise OSError('interrupted')
                return original(path, dest)
            with patch.object(Path, 'rename', interrupted):
                with self.assertRaises(OSError):
                    manage_skill.manage('update', target, bundle)
            self.assertTrue((target / 'SKILL.md').exists())

    def test_update_refuses_nested_data_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            target = root / 'installed'
            manage_skill.manage('install', target, bundle)
            report = target / 'reports/2026/10/2026-10-08.md'
            report.parent.mkdir(parents=True)
            report.write_text('synthetic private report')
            with self.assertRaisesRegex(ValueError, 'outside the release bundle'):
                manage_skill.manage('update', target, bundle)
            self.assertEqual(report.read_text(), 'synthetic private report')
            self.assertTrue((target / 'SKILL.md').exists())

    def test_uninstall_refuses_nested_data_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            target = root / 'installed'
            manage_skill.manage('install', target, bundle)
            prefs = target / 'preferences.json'
            prefs.write_text('{"synthetic": true}')
            with self.assertRaisesRegex(ValueError, 'outside the release bundle'):
                manage_skill.manage('uninstall', target)
            self.assertEqual(prefs.read_text(), '{"synthetic": true}')
            self.assertTrue((target / 'SKILL.md').exists())

    def test_update_refuses_symlinked_entries_and_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            target = root / 'installed'
            manage_skill.manage('install', target, bundle)
            external = root / 'external-scripts'
            external.mkdir()
            (external / 'private.py').write_text('synthetic private data')
            shutil.rmtree(target / 'scripts')
            (target / 'scripts').symlink_to(external, target_is_directory=True)
            secret = root / 'secret.txt'
            secret.write_text('synthetic secret')
            (target / 'LICENSE').unlink()
            (target / 'LICENSE').symlink_to(secret)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                manage_skill.manage('update', target, bundle)
            # The link targets and the installed skill are untouched.
            self.assertEqual((external / 'private.py').read_text(), 'synthetic private data')
            self.assertEqual(secret.read_text(), 'synthetic secret')
            self.assertTrue((target / 'SKILL.md').exists())
            self.assertTrue((target / 'scripts').is_symlink())

    def test_uninstall_refuses_symlinked_entry_and_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            target = root / 'installed'
            manage_skill.manage('install', target, bundle)
            external = root / 'external-data'
            external.mkdir()
            (external / 'body').write_text('synthetic body')
            (target / 'reports').symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                manage_skill.manage('uninstall', target)
            self.assertEqual((external / 'body').read_text(), 'synthetic body')
            self.assertTrue((target / 'SKILL.md').exists())

    def test_migrate_rejects_unrelated_skill_with_skill_md(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            other = root / 'other'
            other.mkdir()
            (other / 'SKILL.md').write_text('# Unrelated Skill\n')
            link = root / 'skills/day-recap'
            link.parent.mkdir(parents=True)
            link.symlink_to(other, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'recognizable'):
                manage_skill.manage('migrate', link, bundle)
            self.assertTrue(link.is_symlink())
            self.assertTrue((other / 'SKILL.md').exists())

    def test_setup_rejects_report_storage_nested_in_installed_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            installed = root / 'skills/day-recap'
            data = root / 'data'
            work = root / 'work'
            work.mkdir()
            manage_skill.manage('install', installed, bundle)
            script = installed / 'scripts/cli.py'
            nested = installed / 'reports'
            result = subprocess.run(
                [sys.executable, '-I', str(script), '--data-dir', str(data),
                 'setup', '--source', 'codex', '--root', str(work), '--zone', 'UTC',
                 '--workspace', str(root / 'recap-chat'), '--accept-data-notice',
                 '--report-dir', str(nested)],
                cwd=installed / 'scripts', capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('outside the installed skill', result.stderr)
            self.assertFalse((data / 'preferences.json').exists())
            self.assertFalse(nested.exists())
            self.assertTrue((installed / 'SKILL.md').exists())

    def test_setup_accepts_external_report_dir_and_persists_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            installed = root / 'skills/day-recap'
            data = root / 'data'
            work = root / 'work'
            reports = root / 'reports'
            work.mkdir()
            manage_skill.manage('install', installed, bundle)
            script = installed / 'scripts/cli.py'
            result = subprocess.run(
                [sys.executable, '-I', str(script), '--data-dir', str(data),
                 'setup', '--source', 'codex', '--root', str(work), '--zone', 'UTC',
                 '--workspace', str(root / 'recap-chat'), '--accept-data-notice',
                 '--report-dir', str(reports)],
                cwd=installed / 'scripts', capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            cfg = json.loads((data / 'preferences.json').read_text())
            self.assertEqual(cfg['report_dir'], str(reports.resolve()))
            self.assertTrue(reports.is_dir())

    def test_migrate_legacy_symlink_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            legacy_target = root / 'legacy-bundle'
            self.legacy_skill(legacy_target)
            (legacy_target / 'old-note.txt').write_text('unrelated user note')
            link = root / 'skills/day-recap'
            link.parent.mkdir(parents=True)
            link.symlink_to(legacy_target, target_is_directory=True)
            result = manage_skill.manage('migrate', link, bundle)
            installed = Path(result['installed'])
            self.assertTrue(installed.is_dir())
            self.assertFalse(installed.is_symlink())
            self.assertTrue((installed / 'VERSION').is_file())
            self.assertTrue(Path(result['legacy_symlink']).is_symlink())
            self.assertFalse(Path(result['legacy_symlink']).is_relative_to(link.parent))
            self.assertEqual(list(link.parent.iterdir()), [link])
            self.assertTrue((Path(result['legacy_target']) / 'SKILL.md').is_file())
            self.assertTrue((legacy_target / 'SKILL.md').exists())
            self.assertEqual((legacy_target / 'old-note.txt').read_text(), 'unrelated user note')

    def test_migrate_legacy_failure_restores_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            legacy_target = root / 'legacy-bundle'
            self.legacy_skill(legacy_target)
            link = root / 'skills/day-recap'
            link.parent.mkdir(parents=True)
            link.symlink_to(legacy_target, target_is_directory=True)
            original = Path.rename
            def interrupted(path, dest):
                if Path(path).name.startswith('.day-recap-migrate-'):
                    raise OSError('interrupted migrate')
                return original(path, dest)
            with patch.object(Path, 'rename', interrupted):
                with self.assertRaises(OSError):
                    manage_skill.manage('migrate', link, bundle)
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), legacy_target)
            self.assertTrue((legacy_target / 'SKILL.md').exists())

    def test_migrate_rejects_unrecognized_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            non_skill = root / 'some-dir'
            non_skill.mkdir()
            (non_skill / 'readme.txt').write_text('not a skill')
            link = root / 'skills/day-recap'
            link.parent.mkdir(parents=True)
            link.symlink_to(non_skill, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'recognizable'):
                manage_skill.manage('migrate', link, bundle)
            self.assertTrue(link.is_symlink())
            self.assertTrue((non_skill / 'readme.txt').exists())

    def test_migrate_validates_bundle_before_touching_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            (bundle / 'unexpected.txt').write_text('not allowed')
            legacy_target = root / 'legacy-bundle'
            self.legacy_skill(legacy_target)
            (legacy_target / 'user-note.txt').write_text('preserve')
            link = root / 'skills/day-recap'
            link.parent.mkdir(parents=True)
            link.symlink_to(legacy_target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'Unexpected'):
                manage_skill.manage('migrate', link, bundle)
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), legacy_target)
            self.assertEqual((legacy_target / 'user-note.txt').read_text(), 'preserve')

    def test_migrate_relative_link_preserves_original_text_and_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            legacy = root / 'skills/legacy-source'
            self.legacy_skill(legacy)
            link = root / 'skills/day-recap'
            link.symlink_to('legacy-source', target_is_directory=True)
            result = manage_skill.manage('migrate', link, bundle)
            self.assertEqual(os.readlink(result['legacy_symlink']), 'legacy-source')
            self.assertEqual(result['legacy_link_text'], 'legacy-source')
            self.assertEqual(Path(result['legacy_target']), legacy)
            self.assertTrue((legacy / 'SKILL.md').exists())
            self.assertFalse(Path(result['legacy_symlink']).is_relative_to(link.parent))

    def test_migrate_relative_link_rollback_restores_exact_link(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            legacy = root / 'skills/legacy-source'
            self.legacy_skill(legacy)
            link = root / 'skills/day-recap'
            link.symlink_to('legacy-source', target_is_directory=True)
            real_rename = Path.rename
            def interrupted(path, destination):
                if path.name.startswith('.day-recap-migrate-'):
                    raise OSError('synthetic migration failure')
                return real_rename(path, destination)
            with patch.object(Path, 'rename', interrupted):
                with self.assertRaises(OSError):
                    manage_skill.manage('migrate', link, bundle)
            self.assertEqual(os.readlink(link), 'legacy-source')
            self.assertEqual(link.resolve(), legacy)

    def test_migration_does_not_adopt_a_skill_that_only_mentions_day_recap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            other = root / 'day-recap-other'
            self.legacy_skill(other)
            (other / 'SKILL.md').write_text('---\nname: other\n---\nCompare with day-recap.\n')
            link = root / 'skills/day-recap'
            link.parent.mkdir()
            link.symlink_to(other, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'recognizable'):
                manage_skill.manage('migrate', link, bundle)
            self.assertTrue(link.is_symlink())

    def test_cache_directory_does_not_hide_user_files_or_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            target = root / 'skills/day-recap'
            manage_skill.manage('install', target, bundle)
            cache = target / 'scripts/__pycache__'
            cache.mkdir()
            (cache / 'reader.cpython-313.pyc').write_bytes(b'synthetic cache')
            self.assertEqual(manage_skill._extra_entries(target), [])
            note = cache / 'personal-report.md'
            note.write_text('Synthetic report')
            for command in ('update', 'uninstall'):
                with self.assertRaisesRegex(ValueError, 'Refusing'):
                    manage_skill.manage(command, target, bundle)
            self.assertEqual(note.read_text(), 'Synthetic report')
            note.unlink()
            (cache / 'link.pyc').symlink_to(root / 'missing')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                manage_skill.manage('uninstall', target)

    def test_migrate_requires_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = self.stage(root / 'release')
            realdir = root / 'skills/day-recap'
            realdir.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                manage_skill.manage('migrate', realdir, bundle)


class KeyboardTests(unittest.TestCase):
    def test_arrow_space_enter_and_escape_on_real_pseudo_terminal(self):
        for keys, expected in ((b'\x1b[B \r', '[1]'), (b'\x1b', 'cancelled')):
            master, slave = pty.openpty()
            code = "import setup_ui\ntry:\n print('RESULT',setup_ui.Terminal().choose('Sources',['a','b'],multiple=True))\nexcept setup_ui.Cancelled:\n print('RESULT cancelled')"
            env = dict(os.environ)
            env['TERM'] = 'xterm'
            process = subprocess.Popen([sys.executable, '-u', '-c', code], cwd=ROOT,
                                       stdin=slave, stdout=slave, stderr=slave, env=env)
            os.close(slave)
            try:
                output = b''
                deadline = time.monotonic() + 5
                while b'Esc cancels' not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        output += os.read(master, 65536)
                self.assertIn(b'Esc cancels', output)
                os.write(master, keys)
                while process.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            output += os.read(master, 65536)
                        except OSError:
                            break
                process.wait(timeout=2)
                self.assertIn(expected.encode(), output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
