"""Build a portable skill from an exact file allowlist, never from the worktree."""
from pathlib import Path
import os
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

import core
from release_check import BUNDLE_FILES, SCRIPTS, check_directory, check_zip, validate_content


def build(root=None):
    root = Path(root or Path(__file__).resolve().parent)
    bundle = root / 'bundle/day-recap'
    if bundle.is_symlink():
        raise ValueError('Bundle destination must not be a symlink.')
    if bundle.exists():
        for path in bundle.rglob('*'):
            if path.is_symlink() or (path.is_file() and path.relative_to(bundle).as_posix() not in BUNDLE_FILES):
                raise ValueError('Unexpected existing bundle entry. Inspect it before rebuilding.')
    contents = {'SKILL.md': (root / 'skill/SKILL.md').read_bytes(),
                'README.md': (root / 'skill/README.md').read_bytes(),
                'LICENSE': (root / 'LICENSE').read_bytes(), 'VERSION': (root / 'VERSION').read_bytes()}
    contents.update({'scripts/' + name: (root / name).read_bytes() for name in SCRIPTS})
    for name, content in contents.items():
        validate_content(name, content)
    for name, content in contents.items():
        core.atomic(bundle / name, content.decode('utf-8'))
    check_directory(bundle)
    archive_path = root / 'bundle/day-recap.zip'
    fd, name = tempfile.mkstemp(prefix='.day-recap-', suffix='.zip.tmp', dir=root / 'bundle')
    os.close(fd)
    temp = Path(name)
    try:
        with ZipFile(temp, 'w', ZIP_DEFLATED) as archive:
            for name in sorted(contents):
                archive.writestr('day-recap/' + name, contents[name])
        check_zip(temp)
        temp.replace(archive_path)
    finally:
        temp.unlink(missing_ok=True)
    return bundle


if __name__ == '__main__':
    print(build())
