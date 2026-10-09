"""Deterministic preparation and storage for the desktop recap skill."""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import tempfile

import core


def discover(home=None):
    home = Path(home or Path.home())
    paths = {'codex': '.codex/sessions', 'codex_archived': '.codex/archived_sessions',
             'claude': '.claude/projects', 'kimi': '.kimi-code/sessions',
             'opencode': '.local/share/opencode/opencode.db', 'hermes': '.hermes/state.db',
             'cursor': '.config/Cursor/User/globalStorage/conversation-search.db'}
    return {name: {'exists': (home / path).exists(), 'path': str(home / path)} for name, path in paths.items()}


def prepare(root, cfg, day, pages=None):
    import reader
    data = reader.collect(day, cfg['timezone'], cfg['roots'], cfg['excludes'])
    if pages:
        desktop = reader.desktop_pages(core.read_json(pages), day, cfg['timezone'])
        data['records'].extend(desktop['records'])
        data['coverage'] = [c for c in data['coverage'] if c['source'] != 'chatgpt'] + desktop['coverage']
    chunks = reader.segments(data['records'])
    directory = Path(tempfile.mkdtemp(prefix='day-recap-'))
    metadata = core.provenance(data, chunks)
    start, end = reader.window(day, cfg['timezone'])
    manifest = {'key': day, 'timezone': cfg['timezone'], 'model': 'gpt-6.1-sol',
                'reasoning': 'high', 'runtime': 'existing Codex agent',
                'date_range': {'start_inclusive': start.isoformat(), 'end_exclusive': end.isoformat()},
                'input_characters': sum(len(r['text']) for r in data['records']),
                **metadata}
    if pages:
        manifest['coverage'].append({'source': 'chatgpt_enumeration', 'status': 'partial',
           'notes': ['Desktop active listing is bounded to 50 recent unpinned chats plus all pinned chats.',
                     'This run inspected returned eligible chats; complete historical active enumeration has no cursor.',
                     'Archived listing must be checked separately in the desktop runtime.']})
    core.json_write(directory / 'manifest.json', manifest)
    for index, chunk in enumerate(chunks):
        core.json_write(directory / f'segment-{index:04d}.json', chunk)
    return {'temporary_directory': str(directory), 'segments': len(chunks),
            'characters': manifest['input_characters'], 'coverage': data['coverage']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DAY_RECAP_DIR', Path(__file__).resolve().parent)))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('discover')
    setup = sub.add_parser('setup')
    setup.add_argument('--root', action='append', required=True)
    setup.add_argument('--exclude', action='append', default=[])
    setup.add_argument('--zone')
    setup.add_argument('--start-date')
    collect = sub.add_parser('collect')
    collect.add_argument('date')
    collect.add_argument('--desktop-pages', type=Path)
    collect.add_argument('--refresh', action='store_true')
    week = sub.add_parser('weekly')
    week.add_argument('week', nargs='?')
    save = sub.add_parser('commit')
    save.add_argument('key')
    save.add_argument('--draft', type=Path, required=True)
    save.add_argument('--manifest', type=Path, required=True)
    save.add_argument('--processed', action='append', default=[])
    save.add_argument('--refresh', action='store_true')
    sub.add_parser('pending')
    notice = sub.add_parser('start-notice')
    notice.add_argument('key')
    schedule = sub.add_parser('schedule-config')
    schedule.add_argument('--time', required=True)
    delivery = sub.add_parser('delivered')
    delivery.add_argument('key')
    show = sub.add_parser('show')
    show.add_argument('key')
    promote = sub.add_parser('promote')
    promote.add_argument('key')
    args = parser.parse_args()
    root = args.data_dir.resolve()
    cfg = core.read_json(root / 'preferences.json')
    if cfg and cfg.get('timezone_mode', 'computer') == 'computer' and args.command not in ('setup', 'discover'):
        cfg['timezone'] = core.computer_zone()
    if args.command == 'discover':
        result = {'local_sources': discover(), 'chatgpt': 'Use desktop list_threads, read_thread and list_archived_threads.'}
    elif args.command == 'setup':
        zone = args.zone or core.computer_zone()
        from zoneinfo import ZoneInfo
        ZoneInfo(zone)
        start_date = args.start_date or str(datetime.now(ZoneInfo(zone)).date())
        date.fromisoformat(start_date)
        old_schedule = (cfg or {}).get('schedule', {})
        cfg = {'version': 1, 'timezone': zone, 'timezone_mode': 'fixed' if args.zone else 'computer',
               'roots': [str(Path(p).expanduser().resolve()) for p in args.root],
               'excludes': list(dict.fromkeys([str(root)] + [str(Path(p).expanduser().resolve()) for p in args.exclude])),
               'model': 'gpt-6.1-sol', 'reasoning': 'high',
               'schedule': {**old_schedule, 'daily_time': old_schedule.get('daily_time'), 'weekly': True,
                            'start_date': old_schedule.get('start_date', start_date),
                            'enabled': old_schedule.get('enabled', False)}}
        root.mkdir(parents=True, exist_ok=True)
        for folder in ('reports/daily', 'reports/weekly'):
            (root / folder).mkdir(parents=True, exist_ok=True)
        core.json_write(root / 'preferences.json', cfg)
        result = {'preferences': cfg, 'sources': discover(), 'next': 'Invoke $day-recap for a sample date in the desktop chat.'}
    else:
        if not cfg:
            raise RuntimeError('Run setup first.')
        if args.command == 'collect':
            existing = core.completion(root, args.date)
            result = ({'status': 'reused', 'path': str(core.report_path(root, args.date)), 'delivery': existing.get('delivery')}
                      if existing and not args.refresh else prepare(root, cfg, args.date, args.desktop_pages))
        elif args.command == 'weekly':
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo(cfg['timezone'])).date()
            key = args.week or core.prior_week(today)
            core.report_path(root, key)
            year, number = key.split('-W')
            if date.fromisocalendar(int(year), int(number), 7) >= today:
                raise ValueError('Weekly reviews require a completed Monday-to-Sunday week.')
            data = core.weekly_input(root, key)
            directory = Path(tempfile.mkdtemp(prefix='day-recap-week-'))
            core.json_write(directory / 'weekly-input.json', data)
            core.json_write(directory / 'manifest.json', {'key': key, 'timezone': cfg['timezone'],
                'model': 'gpt-6.1-sol', 'reasoning': 'high', 'runtime': 'existing Codex agent',
                'missing_days': data['missing_days'], 'partial_days': data['partial_days'],
                'daily_references': [d['source_ref'] for d in data['days']],
                'date_range': {'start_inclusive': data['start'], 'end_exclusive': str(date.fromisoformat(data['end']) + timedelta(days=1))},
                'coverage': [{'source': 'daily_reports', 'status': 'partial' if data['missing_days'] or data['partial_days'] else 'read'}],
                'segments': [{'id': 'weekly-input'}]})
            result = {'temporary_directory': str(directory), 'week': key, 'missing_days': data['missing_days'], 'partial_days': data['partial_days']}
        elif args.command == 'commit':
            manifest = core.read_json(args.manifest)
            expected = {s['id'] for s in manifest['segments']}
            if set(args.processed) != expected or len(args.processed) != len(expected):
                raise RuntimeError('Every input segment must be reviewed exactly once before committing.')
            if manifest['key'] != args.key:
                raise ValueError('Manifest date does not match report date.')
            manifest['processed_segments'] = args.processed
            result = core.commit(root, args.key, args.draft.read_text(), manifest, args.refresh)
        elif args.command == 'pending':
            result = core.pending(root, cfg)
        elif args.command == 'start-notice':
            result = {'key': args.key, 'notify': core.start_notice(root, args.key)}
        elif args.command == 'schedule-config':
            hour, minute = map(int, args.time.split(':'))
            time(hour, minute)
            cfg['schedule']['daily_time'] = f'{hour:02d}:{minute:02d}'
            core.json_write(root / 'preferences.json', cfg)
            result = {'schedule': cfg['schedule'], 'note': 'Preference saved; create or update the native desktop heartbeat separately.'}
        elif args.command == 'delivered':
            core.delivered(root, args.key)
            result = {'key': args.key, 'delivery': 'delivered'}
        elif args.command == 'show':
            print(core.report_path(root, args.key).read_text())
            return
        elif args.command == 'promote':
            result = core.promote(root, args.key)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
