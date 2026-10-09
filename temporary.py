"""Private, task-owned extraction directories with explicit recovery cleanup."""
import json
from pathlib import Path
import shutil
import tempfile
import uuid

import core


def create(root, key):
    base = Path(root).resolve() / '.temporary'
    if base.is_symlink():
        raise RuntimeError('Temporary storage must not be a symlink.')
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base.chmod(0o700)
    directory = Path(tempfile.mkdtemp(prefix='attempt-', dir=base))
    core.json_write(directory / 'owner.json',
                    {'version': 1, 'root': str(Path(root).resolve()), 'key': key,
                     'token': uuid.uuid4().hex})
    return directory


def owned(root, directory):
    directory = Path(directory)
    base = Path(root).resolve() / '.temporary'
    if base.is_symlink() or directory.is_symlink() or directory.parent != base:
        raise ValueError('Cleanup accepts only a registered task directory in this report storage.')
    owner_path = directory / 'owner.json'
    if owner_path.is_symlink():
        raise ValueError('Invalid task ownership marker.')
    owner = core.read_json(owner_path)
    if not owner or owner.get('root') != str(Path(root).resolve()) or not owner.get('token'):
        raise ValueError('Missing task ownership marker; directory preserved.')
    return owner


def cleanup(root, directory):
    directory = Path(directory).absolute()
    owned(root, directory)
    # rmtree does not follow symlinks within this one explicitly owned task.
    shutil.rmtree(directory)


def pending(root):
    base = Path(root).resolve() / '.temporary'
    if not base.exists():
        return []
    if base.is_symlink():
        raise ValueError('Temporary storage must not be a symlink.')
    result = []
    for directory in base.glob('attempt-*'):
        try:
            owner = owned(root, directory)
        except (ValueError, OSError, json.JSONDecodeError):
            result.append({'directory': str(directory), 'key': None, 'ownership': 'unverified',
                           'note': 'Ownership could not be verified. Files preserved; automatic cleanup is refused.'})
            continue
        result.append({'directory': str(directory), 'key': owner['key']})
    return result
