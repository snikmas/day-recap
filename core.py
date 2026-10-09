"""Report storage and eligibility. No model calls or transcript archive."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo


def computer_zone():
    path = Path('/etc/localtime').resolve()
    if 'zoneinfo' in path.parts:
        return '/'.join(path.parts[path.parts.index('zoneinfo') + 1:])
    p = Path('/etc/timezone')
    if p.is_file():
        value = p.read_text().strip()
        ZoneInfo(value)
        return value
    raise RuntimeError('Cannot detect the operating system timezone; supply --zone.')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def atomic(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.recap-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_write(path, data):
    atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


@contextmanager
def locked(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.run.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def report_path(root, key):
    if '-W' in key:
        year, week = key.split('-W')
        monday = date.fromisocalendar(int(year), int(week), 1)
        if key != f'{monday.isocalendar().year:04d}-W{monday.isocalendar().week:02d}':
            raise ValueError('Use YYYY-Www.')
        return Path(root) / 'reports' / 'weekly' / year / (key + '.md')
    day = date.fromisoformat(key)
    if key != day.isoformat():
        raise ValueError('Use YYYY-MM-DD.')
    return Path(root) / 'reports' / 'daily' / f'{day.year:04d}' / f'{day.month:02d}' / (key + '.md')


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def completion(root, key):
    path = report_path(root, key)
    meta = read_json(path.with_suffix('.meta.json'))
    if not path.exists() or not meta:
        return None
    actual = digest(path.read_text())
    if meta.get('status') == 'writing':
        if actual != meta['sha256']:
            return None
        return {**meta, 'status': 'saved', 'recovered': True, 'edited': False}
    # Edits are preserved. A changed report remains complete, flagged for weekly
    # provenance and explicit refresh; an ordinary run must not overwrite it.
    return {**meta, 'edited': actual != meta['sha256']}


def commit(root, key, text, metadata, refresh=False):
    if not text.strip():
        raise ValueError('Empty report.')
    path = report_path(root, key)
    with locked(root):
        existing = completion(root, key)
        if existing and not refresh:
            if existing.get('recovered'):
                recovered = {k: v for k, v in existing.items() if k not in ('edited', 'recovered')}
                json_write(path.with_suffix('.meta.json'), recovered)
            return {'status': 'reused', 'path': str(path), 'edited': existing['edited']}
        if path.exists() and not existing and not refresh:
            raise RuntimeError('Report exists without completion metadata; inspect it and use refresh. Existing text preserved.')
        if refresh:
            base_hash = digest(path.read_text()) if path.exists() else None
            path = path.with_name(path.stem + '.candidate.md')
            if path.exists():
                raise FileExistsError('Refresh candidate already exists; review it first.')
        meta = {**metadata, 'key': key, 'generated_at': datetime.now(timezone.utc).isoformat(),
                'sha256': digest(text), 'status': 'writing', 'delivery': 'pending'}
        if refresh:
            meta['base_sha256'] = base_hash
        json_write(path.with_suffix('.meta.json'), meta)
        atomic(path, text)
        meta['status'] = 'saved'
        json_write(path.with_suffix('.meta.json'), meta)
        if not refresh:
            state = read_json(Path(root) / 'state.json', {'reports': {}})
            state.setdefault('reports', {})[key] = {'status': 'saved', 'delivery': 'pending'}
            json_write(Path(root) / 'state.json', state)
    return {'status': 'candidate' if refresh else 'saved', 'path': str(path)}


def promote(root, key):
    """An explicit user-requested candidate promotion; preserve the old text."""
    import uuid
    path = report_path(root, key)
    candidate = path.with_name(path.stem + '.candidate.md')
    with locked(root):
        meta = read_json(candidate.with_suffix('.meta.json'))
        if not meta or not candidate.exists() or digest(candidate.read_text()) != meta['sha256']:
            raise RuntimeError('Candidate missing, interrupted, or edited; review it before promotion.')
        current = digest(path.read_text()) if path.exists() else None
        if current != meta.get('base_sha256'):
            raise RuntimeError('Original changed after refresh; preserve the new edits and prepare another candidate.')
        backup = None
        if path.exists():
            backup = path.with_name(path.stem + '.previous-' + uuid.uuid4().hex[:8] + '.md')
            atomic(backup, path.read_text())
        meta.pop('base_sha256', None)
        meta['status'] = 'writing'
        json_write(path.with_suffix('.meta.json'), meta)
        atomic(path, candidate.read_text())
        meta['status'] = 'saved'
        json_write(path.with_suffix('.meta.json'), meta)
        state = read_json(Path(root) / 'state.json', {'reports': {}})
        state.setdefault('reports', {})[key] = {'status': 'saved', 'delivery': 'pending'}
        json_write(Path(root) / 'state.json', state)
    return {'status': 'promoted', 'path': str(path), 'previous': str(backup) if backup else None}


def delivered(root, key):
    with locked(root):
        path = report_path(root, key)
        meta = completion(root, key)
        if not meta:
            raise RuntimeError('Cannot mark an unsaved report delivered.')
        meta.pop('edited', None)
        meta.pop('recovered', None)
        meta['delivery'] = 'delivered'
        meta['delivered_at'] = datetime.now(timezone.utc).isoformat()
        json_write(path.with_suffix('.meta.json'), meta)
        state = read_json(Path(root) / 'state.json', {'reports': {}})
        state.setdefault('reports', {})[key] = {'status': 'saved', 'delivery': 'delivered'}
        json_write(Path(root) / 'state.json', state)


def prior_week(today):
    monday = today - timedelta(days=today.weekday() + 7)
    return f'{monday.isocalendar().year:04d}-W{monday.isocalendar().week:02d}'


def start_notice(root, key):
    """Checkpoint a single start notice; a failed run remains eligible."""
    report_path(root, key)
    with locked(root):
        state = read_json(Path(root) / 'state.json', {'reports': {}})
        entry = state.setdefault('reports', {}).setdefault(key, {})
        if entry.get('start_notice_at') or completion(root, key):
            return False
        entry.update(status='pending', start_notice_at=datetime.now(timezone.utc).isoformat())
        json_write(Path(root) / 'state.json', state)
        return True


def weekly_input(root, week):
    report_path(root, week)  # validate the key before reading paths
    year, number = week.split('-W')
    monday = date.fromisocalendar(int(year), int(number), 1)
    result = {'week': week, 'start': str(monday), 'end': str(monday + timedelta(days=6)),
              'days': [], 'missing_days': [], 'partial_days': []}
    for offset in range(7):
        day = str(monday + timedelta(days=offset))
        path = report_path(root, day)
        meta = completion(root, day)
        if not meta:
            result['missing_days'].append(day)
            continue
        partial = any(c.get('status') not in ('read', 'empty', 'not_present', 'excluded')
                      for c in meta.get('coverage', []))
        if partial:
            result['partial_days'].append(day)
        result['days'].append({'date': day, 'report': path.read_text(), 'source_ref': str(path),
                               'timezone': meta.get('timezone'), 'coverage': meta.get('coverage', []),
                               'edited': meta['edited']})
    return result


def pending(root, cfg, now=None):
    zone = ZoneInfo(cfg['timezone'])
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    clock = cfg.get('schedule', {}).get('daily_time')
    if not clock:
        return {'daily': [], 'weekly': [], 'delivery': [], 'reason': 'Daily run time has not been chosen.'}
    hour, minute = map(int, clock.split(':'))
    time(hour, minute)  # validate
    last = now.date() - timedelta(days=1 if now.time() >= time(hour, minute) else 2)
    start = date.fromisoformat(cfg['schedule']['start_date'])
    result = {'daily': [], 'weekly': [], 'delivery': []}
    day = start
    weeks = set()
    while day <= last:
        key = str(day)
        meta = completion(root, key)
        if not meta:
            result['daily'].append(key)
        elif meta.get('delivery') != 'delivered':
            result['delivery'].append(key)
        iso = day.isocalendar()
        week = f'{iso.year:04d}-W{iso.week:02d}'
        sunday = date.fromisocalendar(iso.year, iso.week, 7)
        if sunday <= last:
            weeks.add(week)
        day += timedelta(days=1)
    if cfg['schedule'].get('weekly', True):
        for week in sorted(weeks):
            meta = completion(root, week)
            if not meta:
                result['weekly'].append(week)
            elif meta.get('delivery') != 'delivered':
                result['delivery'].append(week)
    return result


def provenance(collection, segment_list):
    sessions = {}
    for record in collection['records']:
        key = (record['source'], record['session_id'])
        session = sessions.setdefault(key, {k: record.get(k) for k in
                                      ('source', 'session_id', 'title', 'workspace')})
        session.setdefault('records', []).append({k: record.get(k) for k in
                                                ('message_id', 'timestamp', 'source_ref', 'kind')})
    return {'coverage': collection['coverage'], 'sessions': list(sessions.values()),
            'segments': [{'id': f'segment-{i:04d}', 'record_parts': len(segment),
                          'characters': sum(len(r['text']) for r in segment)}
                         for i, segment in enumerate(segment_list)]}
