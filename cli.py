"""Deterministic preparation and storage for the desktop recap skill."""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

# Resolve bundled imports even under Python's isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import core
import runtime
import setup_ui
import temporary


def installed_skill_root():
    """Detect the installed skill directory from this bundled script's location."""
    here = Path(__file__).resolve()
    candidate = here.parent.parent if here.parent.name == 'scripts' else here.parent
    return candidate if (candidate / 'SKILL.md').is_file() else None


def discover(home=None):
    """Stat known history locations only. Never open bodies or provider config."""
    home = Path(home or Path.home())
    paths = {'codex': ('.codex/sessions', '.codex/archived_sessions'),
             'claude': ('.claude/projects',), 'kimi': ('.kimi-code/sessions',),
             'opencode': ('.local/share/opencode/opencode.db',),
             'hermes': ('.hermes/state.db',),
             'cursor': ('.config/Cursor/User/globalStorage/conversation-search.db',)}
    result = {}
    for name, locations in paths.items():
        found, inaccessible = False, False
        for location in locations:
            path = home / location
            try:
                path.stat()
                found = True
                inaccessible |= not os.access(path, os.R_OK)
            except FileNotFoundError:
                pass
            except PermissionError:
                inaccessible = True
        status = ('Inaccessible' if inaccessible else 'Message bodies unavailable' if name == 'cursor' and found
                  else 'History location found' if found else 'Not detected')
        result[name] = {'exists': found, 'status': status,
                        'paths': [str(home / p) for p in locations]}
    result['chatgpt'] = {'exists': None, 'status': 'Check in desktop; separate opt-in', 'paths': []}
    return result


def model_metadata(cfg, evidence=None):
    details = runtime.require_ready(cfg, evidence)
    return {'runtime_details': details, 'model': details['observed']['model'],
            'reasoning': details['observed']['reasoning'], 'runtime': details['observed']['host']}


def prepare(root, cfg, day, pages=None, evidence=None):
    import reader
    core.report_path(root, day)
    if 'sources' not in cfg or not cfg.get('data_notice_accepted'):
        raise RuntimeError('Collection scope has not been confirmed. Rerun setup before collecting.')
    if pages and 'chatgpt' not in cfg['sources']:
        raise RuntimeError('ChatGPT was not selected. Desktop pages were not read.')
    details = model_metadata(cfg, evidence)
    data = reader.collect(day, cfg['timezone'], cfg['roots'], cfg['excludes'],
                          enabled_sources=cfg['sources'])
    if pages:
        desktop = reader.desktop_pages(core.read_json(pages), day, cfg['timezone'], cfg.get('chat_excludes', []))
        data['records'].extend(desktop['records'])
        data['coverage'] = [c for c in data['coverage'] if c['source'] != 'chatgpt'] + desktop['coverage']
    chunks = reader.segments(data['records'])
    directory = temporary.create(root, day)
    metadata = core.provenance(data, chunks)
    start, end = reader.window(day, cfg['timezone'])
    manifest = {'key': day, 'timezone': cfg['timezone'], **details,
                'task_directory': str(directory),
                'date_range': {'start_inclusive': start.isoformat(), 'end_exclusive': end.isoformat()},
                'input_characters': sum(len(r['text']) for r in data['records']), **metadata}
    if pages:
        manifest['coverage'].append({'source': 'chatgpt_enumeration', 'status': 'partial',
            'notes': ['Desktop active listing is bounded to 50 recent unpinned chats plus all pinned chats.',
                      'This run inspected returned eligible chats; complete historical active enumeration has no cursor.',
                      'Archived listing must be checked separately in the desktop runtime.']})
    core.json_write(directory / 'manifest.json', manifest)
    for index, chunk in enumerate(chunks):
        core.json_write(directory / f'segment-{index:04d}.json', chunk)
    return {'temporary_directory': str(directory), 'segments': len(chunks),
            'characters': manifest['input_characters'], 'coverage': data['coverage'],
            'runtime_details': details['runtime_details']}


def reuse(root, key):
    core.recover(root, key)
    existing = core.completion(root, key)
    if existing:
        return {'status': 'reused', 'path': str(core.report_path(root, key)),
                'delivery': existing.get('delivery', 'pending'),
                'display_required': existing.get('delivery') != 'delivered', 'edited': existing['edited'],
                'sha256': core.digest(core.report_path(root, key).read_text())}
    return None


def platform_check():
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    if sys.platform != 'linux' or core.fcntl is None:
        raise RuntimeError('Unsupported platform for this beta. Linux is supported; macOS is unverified and Windows locking is unavailable.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DAY_RECAP_DIR', Path.home() / '.local/share/day-recap')))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('discover')
    setup = sub.add_parser('setup')
    setup.add_argument('--root', action='append')
    setup.add_argument('--source', action='append', choices=setup_ui.SOURCES)
    setup.add_argument('--exclude', action='append', default=[])
    setup.add_argument('--exclude-chat', action='append', default=[])
    setup.add_argument('--workspace', type=Path, default=Path.cwd())
    setup.add_argument('--report-dir', type=Path)
    setup.add_argument('--zone')
    setup.add_argument('--start-date')
    setup.add_argument('--model')
    setup.add_argument('--reasoning')
    setup.add_argument('--accept-data-notice', action='store_true')
    setup.add_argument('--numbered', action='store_true')
    for command in ('collect', 'weekly'):
        collect = sub.add_parser(command)
        collect.add_argument('date' if command == 'collect' else 'week', **({} if command == 'collect' else {'nargs': '?'}))
        collect.add_argument('--refresh', action='store_true')
        collect.add_argument('--desktop-runtime', type=Path)
        if command == 'collect':
            collect.add_argument('--desktop-pages', type=Path)
    check = sub.add_parser('runtime-check')
    check.add_argument('--desktop-runtime', type=Path)
    save = sub.add_parser('commit')
    save.add_argument('key')
    save.add_argument('--draft', type=Path, required=True)
    save.add_argument('--manifest', type=Path, required=True)
    save.add_argument('--processed', action='append', default=[])
    save.add_argument('--refresh', action='store_true')
    sub.add_parser('pending')
    sub.add_parser('temporary-list')
    sub.add_parser('temporary-create').add_argument('key')
    cleanup = sub.add_parser('cleanup')
    cleanup.add_argument('directory', type=Path)
    for command in ('start-notice', 'delivered', 'show', 'promote', 'archive-candidate'):
        action = sub.add_parser(command)
        action.add_argument('key')
        if command == 'delivered':
            action.add_argument('--sha256')
    schedule = sub.add_parser('schedule-config')
    schedule.add_argument('--time', required=True)
    args = parser.parse_args()
    platform_check()
    settings_root = args.data_dir.expanduser().resolve()
    if args.command == 'discover':
        print(json.dumps({'sources': discover(), 'desktop': 'Check required history tools and model in desktop.'}, indent=2))
        return
    cfg = core.read_json(settings_root / 'preferences.json')
    if args.command == 'setup':
        scripted = any((args.root is not None, args.source is not None, args.exclude, args.exclude_chat,
                        args.zone, args.start_date, args.model, args.reasoning, args.report_dir,
                        args.accept_data_notice))
        if scripted:
            if args.source is None or not args.accept_data_notice:
                parser.error('Scripted setup requires explicit --source and --accept-data-notice. ' + setup_ui.NOTICE)
            if args.reasoning and not args.model:
                parser.error('--reasoning requires a requested --model.')
            zone = args.zone or (cfg or {}).get('timezone') or core.computer_zone()
            preference = ({'policy': 'specific', 'model': args.model, 'reasoning': args.reasoning}
                          if args.model else {'policy': 'inherit'})
            chosen = setup_ui.build_preferences(cfg, args.source, args.root or [], args.exclude,
                args.report_dir or (cfg or {}).get('report_dir', str(settings_root)), args.workspace,
                zone, bool(args.zone) or (cfg or {}).get('timezone_mode') == 'fixed',
                args.exclude_chat, preference, args.start_date)
        else:
            chosen = setup_ui.wizard(cfg, settings_root, args.workspace, discover(), args.numbered)
        if chosen is None:
            print(json.dumps({'status': 'cancelled', 'note': 'Existing settings and reports preserved.'}))
            return
        skill_root = installed_skill_root()
        if skill_root is not None:
            core.ensure_storage_outside_skill(skill_root, chosen['report_dir'], settings_root)
        chosen['excludes'] = list(dict.fromkeys([str(settings_root), *chosen['excludes']]))
        storage = Path(chosen['report_dir'])
        # Probe actual advisory locking and write access before replacing settings.
        with core.locked(storage):
            import tempfile
            fd, probe = tempfile.mkstemp(prefix='.setup-probe-', dir=storage)
            os.close(fd)
            try:
                core.atomic(probe, 'probe')
            finally:
                Path(probe).unlink(missing_ok=True)
        with core.locked(settings_root):
            core.json_write(settings_root / 'preferences.json', chosen)
        result = {'status': 'saved', 'preferences': chosen,
                  'next': f'In desktop, request $day-recap yesterday with --data-dir {settings_root}. Verify runtime before collection.',
                  'note': 'No history collection or schedule was started.'}
    else:
        if not cfg:
            raise RuntimeError('Run setup first.')
        root = Path(cfg.get('report_dir', settings_root)).resolve()
        if cfg.get('timezone_mode', 'computer') == 'computer' and args.command in ('collect', 'weekly', 'pending'):
            cfg['timezone'] = core.computer_zone()
        if args.command in ('collect', 'weekly'):
            if args.command == 'weekly':
                today = datetime.now(ZoneInfo(cfg['timezone'])).date()
                key = args.week or core.prior_week(today)
                core.report_path(root, key)
                year, number = key.split('-W')
                if date.fromisocalendar(int(year), int(number), 7) >= today:
                    raise ValueError('Weekly reviews require a completed Monday-to-Sunday week.')
            else:
                key = args.date
            existing = reuse(root, key)
            if existing and not args.refresh:
                result = existing
            else:
                evidence = core.read_json(args.desktop_runtime) if args.desktop_runtime else None
                if args.command == 'collect':
                    result = prepare(root, cfg, key, args.desktop_pages, evidence) if evidence else prepare(root, cfg, key, args.desktop_pages)
                else:
                    details = model_metadata(cfg, evidence)
                    data = core.weekly_input(root, key)
                    directory = temporary.create(root, key)
                    core.json_write(directory / 'weekly-input.json', data)
                    core.json_write(directory / 'manifest.json', {'key': key, 'timezone': cfg['timezone'], **details,
                        'task_directory': str(directory), 'missing_days': data['missing_days'], 'partial_days': data['partial_days'],
                        'daily_references': [d['source_ref'] for d in data['days']],
                        'date_range': {'start_inclusive': data['start'], 'end_exclusive': str(date.fromisoformat(data['end']) + timedelta(days=1))},
                        'coverage': [{'source': 'daily_reports', 'status': 'partial' if data['missing_days'] or data['partial_days'] else 'read'}],
                        'segments': [{'id': 'weekly-input'}]})
                    result = {'temporary_directory': str(directory), 'week': key,
                              'missing_days': data['missing_days'], 'partial_days': data['partial_days']}
        elif args.command == 'runtime-check':
            evidence = core.read_json(args.desktop_runtime) if args.desktop_runtime else None
            result = runtime.snapshot(cfg, evidence)
        elif args.command == 'commit':
            manifest = core.read_json(args.manifest)
            expected = {s['id'] for s in manifest['segments']}
            if len(expected) != len(manifest['segments']):
                raise ValueError('Manifest contains duplicate segment IDs.')
            if set(args.processed) != expected or len(args.processed) != len(expected):
                raise RuntimeError('Every input segment must be reviewed exactly once before committing.')
            if manifest['key'] != args.key:
                raise ValueError('Manifest date does not match report date.')
            task = manifest.get('task_directory')
            if task:
                owner = temporary.owned(root, Path(task))
                if owner['key'] != args.key or args.manifest.resolve().parent != Path(task):
                    raise ValueError('Manifest does not belong to this report attempt.')
            manifest['processed_segments'] = args.processed
            result = core.commit(root, args.key, args.draft.read_text(), manifest, args.refresh)
            if task:
                temporary.cleanup(root, task)
                result['temporary_cleaned'] = True
        elif args.command == 'temporary-create':
            core.report_path(root, args.key)
            result = {'temporary_directory': str(temporary.create(root, args.key))}
        elif args.command == 'temporary-list':
            result = {'interrupted_attempts': temporary.pending(root),
                      'next': 'Resume an owned attempt, or use cleanup DIRECTORY to discard its extraction files.'}
        elif args.command == 'cleanup':
            temporary.cleanup(root, args.directory)
            result = {'status': 'cleaned', 'directory': str(args.directory)}
        elif args.command == 'pending':
            result = core.pending(root, cfg)
        elif args.command == 'start-notice':
            result = {'key': args.key, 'notify': core.start_notice(root, args.key)}
        elif args.command == 'schedule-config':
            hour, minute = map(int, args.time.split(':'))
            time(hour, minute)
            cfg['schedule']['daily_time'] = f'{hour:02d}:{minute:02d}'
            core.json_write(settings_root / 'preferences.json', cfg)
            result = {'schedule': cfg['schedule'], 'note': 'Experimental preference only. Manual sample acceptance and live desktop verification required before automation.'}
        elif args.command == 'delivered':
            core.recover(root, args.key)
            core.delivered(root, args.key, args.sha256)
            result = {'key': args.key, 'delivery': 'delivered'}
        elif args.command == 'show':
            core.recover(root, args.key)
            print(core.report_path(root, args.key).read_text())
            return
        elif args.command == 'promote':
            result = core.promote(root, args.key)
        elif args.command == 'archive-candidate':
            result = core.archive_candidate(root, args.key)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f'Daily Recap: {exc}', file=sys.stderr)
        raise SystemExit(1)
