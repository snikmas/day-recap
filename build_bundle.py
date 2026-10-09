"""Build an installable skill containing only code and instructions."""
from pathlib import Path
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
bundle = root / 'bundle' / 'day-recap'
bundle.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / 'skill' / 'SKILL.md', bundle / 'SKILL.md')
if (root / 'skill' / 'README.md').is_file():
    shutil.copy2(root / 'skill' / 'README.md', bundle / 'README.md')
(bundle / 'scripts').mkdir(exist_ok=True)
for name in ('cli.py', 'core.py', 'reader.py'):
    shutil.copy2(root / name, bundle / 'scripts' / name)
names = ['SKILL.md', 'scripts/cli.py', 'scripts/core.py', 'scripts/reader.py']
if (bundle / 'README.md').is_file():
    names.append('README.md')
with ZipFile(root / 'bundle' / 'day-recap.zip', 'w', ZIP_DEFLATED) as archive:
    for name in names:
        archive.write(bundle / name, 'day-recap/' + name)
print(bundle)
