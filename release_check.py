"""Reject unexpected bundle entries and common private-data markers."""
from pathlib import Path
import re
from zipfile import ZipFile

SCRIPTS = ('cli.py', 'core.py', 'reader.py', 'setup_ui.py', 'runtime.py', 'temporary.py')
BUNDLE_FILES = {'SKILL.md', 'README.md', 'LICENSE', 'VERSION', *('scripts/' + name for name in SCRIPTS)}
PRIVATE = re.compile(r'/home/[^/\s]+(?:/|\b)|/Users/[^/\s]+(?:/|\b)|[A-Z]:\\Users\\|'
                     r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|'
                     r'\bsk-[A-Za-z0-9_-]{20,}|'
                     r'(?i:api[_-]?key|access[_-]?token|password)\s*[=:]\s*[\"\x27][^\"\x27\s]{8,}')


def validate_content(name, content):
    if name not in BUNDLE_FILES:
        raise ValueError('Unexpected release file: ' + name)
    if PRIVATE.search(content.decode('utf-8')):
        raise ValueError('Potential private data or author path in ' + name)


def check_directory(directory):
    directory = Path(directory)
    names = set()
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink is not allowed in a release bundle.')
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            if name not in BUNDLE_FILES:
                raise ValueError('Unexpected release file: ' + name)
            validate_content(name, path.read_bytes())
            names.add(name)
    if names != BUNDLE_FILES:
        raise ValueError('Missing bundle files: ' + ', '.join(sorted(BUNDLE_FILES - names)))


def check_zip(path):
    with ZipFile(path) as archive:
        expected = {'day-recap/' + name for name in BUNDLE_FILES}
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
            raise ValueError('Archive entries do not match the exact release allowlist.')
        for name in archive.namelist():
            validate_content(name.removeprefix('day-recap/'), archive.read(name))


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    check_directory(root / 'bundle/day-recap')
    check_zip(root / 'bundle/day-recap.zip')
    print('Release allowlist and private-data checks passed.')
