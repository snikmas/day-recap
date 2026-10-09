"""Small terminal setup wizard. No collection, model calls, or configuration scan."""
from copy import deepcopy
from datetime import date, datetime
import os
from pathlib import Path
import select
import sys
from zoneinfo import ZoneInfo

import core

SOURCES = ('codex', 'claude', 'kimi', 'opencode', 'hermes', 'cursor', 'chatgpt')
NOTICE = ('Selected conversation text goes to the current desktop agent. Reports can '
          'contain personal information. Redaction is limited. ChatGPT is a separate '
          'opt-in across topics; access and incomplete coverage are checked in desktop.')
BACK = object()


class Cancelled(Exception):
    pass


def path_value(value, directory=False):
    value = str(value)
    if not value.strip():
        raise ValueError('Enter a folder path.')
    path = Path(value).expanduser().absolute().resolve()
    if path.exists() and not path.is_dir():
        raise ValueError('Choose a directory, not a file.')
    if directory and not path.is_dir():
        raise ValueError('Work folder must already exist.')
    parent = path
    while not parent.exists():
        parent = parent.parent
    if not directory and not os.access(parent, os.W_OK | os.X_OK):
        raise ValueError('Report storage is not writable.')
    return str(path)


def build_preferences(old, sources, roots, excludes, report_dir, workspace, zone,
                      fixed_zone=False, chat_excludes=(), preference=None, start=None):
    if set(sources) - set(SOURCES):
        raise ValueError('Unknown source selected.')
    core.validate_zone(zone)
    report_dir = path_value(report_dir)
    roots = [path_value(p, directory=True) for p in roots]
    if any(s != 'chatgpt' for s in sources) and not roots:
        raise ValueError('Select a work folder for local sources.')
    if not sources:
        raise ValueError('Select at least one conversation source explicitly.')
    schedule = deepcopy((old or {}).get('schedule', {}))
    date.fromisoformat(start or schedule.get('start_date', str(datetime.now(ZoneInfo(zone)).date())))
    schedule.setdefault('start_date', start or str(datetime.now(ZoneInfo(zone)).date()))
    schedule.setdefault('daily_time', None)
    schedule.setdefault('weekly', True)
    schedule.setdefault('enabled', False)
    preference = preference or {'policy': 'inherit'}
    if preference.get('policy') not in ('inherit', 'specific'):
        raise ValueError('Invalid model policy.')
    if preference['policy'] == 'specific' and not preference.get('model'):
        raise ValueError('Enter the requested desktop model name.')
    return {'version': 2, 'sources': list(dict.fromkeys(sources)), 'roots': roots,
            'excludes': list(dict.fromkeys([report_dir, str(Path(workspace).resolve()),
                                          *[path_value(p) for p in excludes]])),
            'chat_excludes': list(dict.fromkeys(chat_excludes)), 'report_dir': report_dir,
            'timezone': zone, 'timezone_mode': 'fixed' if fixed_zone else 'computer',
            'model_preference': preference, 'schedule': schedule,
            'data_notice_accepted': True, 'desktop_check': 'pending'}


class Terminal:
    def __init__(self, numbered=False):
        self.numbered = numbered or os.environ.get('TERM', 'dumb') == 'dumb'

    def text(self, prompt, default=''):
        try:
            value = input(f'{prompt}' + (f' [{default}]' if default else '') + ': ')
        except (EOFError, KeyboardInterrupt):
            raise Cancelled() from None
        if value.lower() in ('q', 'cancel') or '\x1b' in value:
            raise Cancelled()
        if value.lower() in ('b', 'back'):
            return BACK
        return '' if value == '-' else value or default

    def key(self):
        import termios
        import tty
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        try:
            tty.setraw(fd, when=termios.TCSANOW)
            key = os.read(fd, 1).decode()
            if key == '\x1b' and select.select([sys.stdin], [], [], 0.05)[0]:
                key += os.read(fd, 2).decode()
            return key
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)

    def choose(self, title, choices, selected=(), multiple=False):
        checked = set(selected)
        if self.numbered:
            while True:
                print(title)
                for i, label in enumerate(choices):
                    print(f'  {i + 1}. {"[x]" if i in checked else "[ ]"} {label}')
                value = self.text('Numbers separated by commas; b Back; q Cancel')
                if value is BACK:
                    return BACK
                if not value.strip():
                    print('Enter an explicit selection. Empty input does not confirm a choice.')
                    continue
                try:
                    indexes = {int(n.strip()) - 1 for n in value.split(',')}
                    if not indexes or min(indexes) < 0 or max(indexes) >= len(choices):
                        raise ValueError()
                    if not multiple and len(indexes) != 1:
                        raise ValueError()
                    return sorted(indexes) if multiple else indexes.pop()
                except ValueError:
                    print('Choose valid numbers from this screen.')
        cursor = min(checked) if checked else 0
        while True:
            print('\x1b[2J\x1b[H' + title)
            for i, label in enumerate(choices):
                marker = '[x]' if i in checked else '[ ]'
                print(f'{">" if i == cursor else " "} {marker if multiple else ""} {label}')
            print('Arrows move | Space selects | Enter continues | Backspace returns | Esc cancels')
            key = self.key()
            if key in ('\x03', '\x1b', ''):
                raise Cancelled()
            if key in ('\x7f', 'b'):
                return BACK
            if key == '\x1b[A':
                cursor = (cursor - 1) % len(choices)
            elif key == '\x1b[B':
                cursor = (cursor + 1) % len(choices)
            elif key == ' ':
                if multiple:
                    checked.symmetric_difference_update({cursor})
                else:
                    checked = {cursor}
            elif key in ('\r', '\n'):
                if multiple:
                    if checked:
                        return sorted(checked)
                else:
                    return cursor


def wizard(old, data_dir, workspace, detected, numbered=False, terminal=None):
    if terminal is None and not sys.stdin.isatty():
        raise RuntimeError('Noninteractive setup needs explicit --source, --root, and --accept-data-notice flags.')
    ui = terminal or Terminal(numbered)
    values = {'sources': list((old or {}).get('sources', [])),
              'roots': list((old or {}).get('roots', [])),
              'excludes': list((old or {}).get('excludes', [])),
              'report_dir': (old or {}).get('report_dir', str(data_dir)),
              'chat_excludes': list((old or {}).get('chat_excludes', [])),
              'preference': (old or {}).get('model_preference', {'policy': 'inherit'})}
    try:
        zone = core.validate_zone((old or {}).get('timezone') or core.computer_zone())
    except (RuntimeError, ValueError, OSError):
        zone = None
    fixed = (old or {}).get('timezone_mode') == 'fixed'
    screen = 0
    try:
        while screen < 5:
            print(f'Daily Recap setup {screen + 1} / 5. b Back; q Cancel.')
            try:
                if screen == 0:
                    labels = [s + ' - ' + detected[s]['status'] for s in SOURCES]
                    choice = ui.choose('Choose conversation sources. ' + NOTICE, labels,
                                       [SOURCES.index(s) for s in values['sources']], multiple=True)
                    if choice is BACK:
                        raise Cancelled()
                    values['sources'] = [SOURCES[i] for i in choice]
                    if 'chatgpt' in values['sources']:
                        field = ui.text('Optional excluded ChatGPT IDs, comma separated; use - to clear. Check IDs in desktop',
                                        ','.join(values['chat_excludes']))
                        if field is BACK:
                            continue
                        values['chat_excludes'] = [s.strip() for s in field.split(',') if s.strip()]
                elif screen == 1:
                    if any(s != 'chatgpt' for s in values['sources']):
                        field = ui.text('Work folders, separated by semicolons', ';'.join(values['roots']))
                        if field is BACK:
                            screen -= 1
                            continue
                        values['roots'] = [path_value(p, True) for p in field.split(';') if p.strip()]
                        if not values['roots']:
                            raise ValueError('Enter at least one work folder.')
                        advanced = ui.choose('Add or change folder exclusions?', ['Continue', 'Edit exclusions'])
                        if advanced is BACK:
                            screen -= 1
                            continue
                        if advanced == 1:
                            field = ui.text('Excluded folders, separated by semicolons; use - to clear', ';'.join(values['excludes']))
                            if field is BACK:
                                continue
                            values['excludes'] = [path_value(p) for p in field.split(';') if p.strip()]
                elif screen == 2:
                    field = ui.text('Report storage folder', values['report_dir'])
                    if field is BACK:
                        screen -= 1
                        continue
                    values['report_dir'] = path_value(field)
                    if not zone:
                        field = ui.text('Timezone could not be detected. Enter an IANA timezone')
                        if field is BACK:
                            screen -= 1
                            continue
                        core.validate_zone(field)
                        zone, fixed = field, True
                    change = ui.choose(f'Timezone: {zone}', ['Continue', 'Change timezone'])
                    if change is BACK:
                        screen -= 1
                        continue
                    if change == 1:
                        field = ui.text('IANA timezone', zone)
                        if field is BACK:
                            continue
                        core.validate_zone(field)
                        zone, fixed = field, True
                elif screen == 3:
                    choice = ui.choose('Writing model. Availability: Check in desktop.',
                                       ['Use current desktop model and reasoning', 'Request a specific desktop model'],
                                       [1 if values['preference']['policy'] == 'specific' else 0])
                    if choice is BACK:
                        screen -= 1
                        continue
                    if choice == 0:
                        values['preference'] = {'policy': 'inherit'}
                    else:
                        field = ui.text('Requested model name. Change the model in desktop before the sample',
                                        values['preference'].get('model', ''))
                        if field is BACK:
                            continue
                        if not field.strip():
                            raise ValueError('Enter a model name or select current desktop model.')
                        reasoning = ui.text('Optional requested reasoning setting; use - to clear', values['preference'].get('reasoning', ''))
                        if reasoning is BACK:
                            continue
                        values['preference'] = {'policy': 'specific', 'model': field,
                                                'reasoning': reasoning or None}
                else:
                    cfg = build_preferences(old, workspace=workspace, zone=zone, fixed_zone=fixed, **values)
                    print('Sources: ' + ', '.join(cfg['sources']))
                    print('Work folders: ' + '; '.join(cfg['roots']))
                    print('Excluded folders: ' + '; '.join(cfg['excludes']))
                    print('Excluded chats: ' + ', '.join(cfg['chat_excludes']))
                    print('Reports: ' + cfg['report_dir'])
                    print('Model: ' + str(cfg['model_preference']) + '. Desktop checks pending.')
                    print('Schedule: ' + ('Existing preference retained, experimental.' if cfg['schedule']['enabled'] else 'Manual.'))
                    print(NOTICE)
                    choice = ui.choose('Review and save', ['Save setup', 'Back', 'Cancel'])
                    if choice is BACK or choice == 1:
                        screen -= 1
                        continue
                    if choice == 2:
                        raise Cancelled()
                    return cfg
                screen += 1
            except (ValueError, OSError) as exc:
                print(str(exc))
                if screen == 4:
                    screen = 1
    except (Cancelled, KeyboardInterrupt, EOFError):
        return None
