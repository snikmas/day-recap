"""Install, update, migrate, or archive a skill. Report storage is never touched."""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from release_check import BUNDLE_FILES, check_directory


def _extra_entries(directory):
    """Names under an installed skill that are not part of the release bundle.

    Only entry names and link status are inspected; file contents are never
    read. A clean release bundle contains no symlinks, so any symlink is treated
    as a possible pointer to user data that must not be silently moved or
    archived, even when its name matches an allowlisted bundle file.
    """
    extras = []
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
        rel_dir = os.path.relpath(dirpath, directory)
        for name in list(dirnames):
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, '/')
            if os.path.islink(os.path.join(dirpath, name)):
                extras.append(rel + '/ (symlink)')
                dirnames.remove(name)
                continue
            if rel in ('scripts', '__pycache__', 'scripts/__pycache__'):
                continue
            extras.append(rel + '/')
            dirnames.remove(name)  # Do not inspect data inside unexpected folders.
        for name in filenames:
            rel = os.path.normpath(os.path.join(rel_dir, name)).replace(os.sep, '/')
            if os.path.islink(os.path.join(dirpath, name)):
                extras.append(rel + ' (symlink)')
                continue
            if rel_dir.replace(os.sep, '/') in ('__pycache__', 'scripts/__pycache__') and name.endswith('.pyc'):
                continue
            if rel in BUNDLE_FILES:
                continue
            extras.append(rel)
    return extras


def _refuse_unsafe_layout(target):
    extras = _extra_entries(target)
    if extras:
        raise ValueError(
            'Skill directory contains data outside the release bundle (for example: '
            + ', '.join(extras[:5])
            + '). Refusing to move or archive it. Move that data outside the skill '
            'before updating or uninstalling. Files preserved.'
        )


def _recognizable_skill(directory):
    """Confirm a directory is the day-recap skill without reading private data.

    Only the skill's own ``SKILL.md`` is inspected, and only for the public
    skill name. Unrelated skills or data directories must not be adopted.
    """
    directory = Path(directory)
    skill_md = directory / 'SKILL.md'
    if not skill_md.is_file() or skill_md.is_symlink():
        return False
    try:
        with skill_md.open(encoding='utf-8', errors='replace') as stream:
            lines = stream.read(8192).splitlines()
    except OSError:
        return False
    if not lines or lines[0].strip() != '---':
        return False
    name = None
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if line.startswith('name:'):
            name = line.split(':', 1)[1].strip().strip('"\'')
    scripts = directory / 'scripts'
    return (name == 'day-recap' and scripts.is_dir() and not scripts.is_symlink()
            and all((scripts / filename).is_file() and not (scripts / filename).is_symlink()
                    for filename in ('cli.py', 'core.py', 'reader.py')))


def migrate_legacy(target, bundle=None):
    """Replace an old unversioned symlink install with the versioned bundle.

    The original symlink and its target are preserved and never modified. The
    current bundle is installed as a real directory at the symlink location, and
    the symlink is restored if installation fails.
    """
    target = Path(target).expanduser().absolute()
    if not target.is_symlink():
        raise ValueError('Legacy migration requires a symlink installation; files preserved.')
    resolved = target.resolve()
    if not resolved.is_dir() or not _recognizable_skill(resolved):
        raise ValueError('Symlink target is not a recognizable day-recap skill; files preserved.')
    bundle = Path(bundle or Path(__file__).resolve().parent / 'bundle/day-recap')
    check_directory(bundle)
    target.parent.mkdir(parents=True, exist_ok=True)
    archives = target.parent.parent / 'day-recap-archives'
    if archives.is_symlink():
        raise ValueError('Archive directory must not be a symlink.')
    archives.mkdir(parents=True, exist_ok=True)
    preserved = archives / (target.name + '.legacy-symlink-' + uuid.uuid4().hex[:8])
    original_link = os.readlink(target)
    staging = Path(tempfile.mkdtemp(prefix='.day-recap-migrate-', dir=target.parent))
    try:
        shutil.copytree(bundle, staging, dirs_exist_ok=True)
        check_directory(staging)
        # Renaming the symlink itself never touches its target directory.
        os.rename(target, preserved)
        try:
            staging.rename(target)
        except OSError:
            if not target.exists() and not target.is_symlink() and preserved.is_symlink():
                os.rename(preserved, target)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {'installed': str(target), 'legacy_symlink': str(preserved),
            'legacy_target': str(resolved), 'legacy_link_text': original_link,
            'target_unchanged': True}


def manage(command, target, bundle=None):
    target = Path(target).expanduser().absolute()
    if command == 'migrate':
        return migrate_legacy(target, bundle)
    if target.is_symlink():
        raise ValueError(
            'Choose a real skill directory, not a symlink; use migrate for a '
            'legacy symlink installation.'
        )
    if command == 'install' and target.exists():
        raise FileExistsError('Skill already exists. Use update to preserve the old version.')
    if command != 'install':
        if not (target / 'VERSION').is_file() or not (target / 'SKILL.md').is_file():
            raise ValueError('Target is not an installed versioned skill; files preserved.')
        _refuse_unsafe_layout(target)
    archives = target.parent.parent / 'day-recap-archives'
    if archives.is_symlink():
        raise ValueError('Archive directory must not be a symlink.')
    if command == 'uninstall':
        archives.mkdir(parents=True, exist_ok=True)
        backup = archives / (target.name + '.uninstalled-' + uuid.uuid4().hex[:8])
        target.rename(backup)
        return {'archived_skill': str(backup), 'reports': 'preserved'}
    bundle = Path(bundle or Path(__file__).resolve().parent / 'bundle/day-recap')
    check_directory(bundle)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.day-recap-install-', dir=target.parent))
    backup = None
    try:
        shutil.copytree(bundle, staging, dirs_exist_ok=True)
        check_directory(staging)
        if command == 'update':
            archives.mkdir(parents=True, exist_ok=True)
            backup = archives / (target.name + '.previous-' + uuid.uuid4().hex[:8])
            target.rename(backup)
        try:
            staging.rename(target)
        except OSError:
            if backup:
                backup.rename(target)
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {'installed': str(target), 'previous': str(backup) if backup else None,
            'reports': 'preserved'}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('install', 'update', 'uninstall', 'migrate'))
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    print(json.dumps(manage(args.command, args.target), indent=2))
