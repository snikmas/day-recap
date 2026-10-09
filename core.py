"""Report storage and eligibility. No model calls or transcript archive."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on unsupported platforms
    fcntl = None


def validate_zone(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter an IANA timezone, such as UTC or Asia/Shanghai.')
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError('Unknown IANA timezone: ' + value + '. Choose a timezone installed on this computer.') from exc
    return value


def computer_zone():
    try:
        path = Path('/etc/localtime').resolve()
        if 'zoneinfo' in path.parts:
            return validate_zone('/'.join(path.parts[path.parts.index('zoneinfo') + 1:]))
        p = Path('/etc/timezone')
        if p.is_file():
            return validate_zone(p.read_text().strip())
    except (OSError, ValueError) as exc:
        raise RuntimeError('Cannot detect a usable computer timezone; choose a timezone in setup or supply --zone.') from exc
    raise RuntimeError('Cannot detect the operating system timezone; supply --zone.')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def is_within(path, parent):
    """True when ``path`` canonicalizes inside ``parent``, following symlinks."""
    try:
        resolved_path = os.path.normpath(os.path.realpath(str(path)))
        resolved_parent = os.path.normpath(os.path.realpath(str(parent)))
    except (OSError, ValueError):
        return False
    try:
        return os.path.commonpath([resolved_parent, resolved_path]) == resolved_parent
    except ValueError:
        return False


def ensure_storage_outside_skill(skill_root, report_dir, data_dir):
    """Reject report or preferences storage nested inside the installed skill."""
    skill_root = Path(skill_root).resolve()
    for label, value in (('Report storage', report_dir), ('Preferences directory', data_dir)):
        if is_within(value, skill_root):
            raise ValueError(
                label + ' must be outside the installed skill directory so that '
                'updating or uninstalling the skill never moves or deletes your '
                'data. Choose another folder.'
            )


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
    if fcntl is None:
        raise RuntimeError(
            'File locking is not supported on this platform; '
            'report commits require an operating system that provides fcntl advisory locks.'
        )
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
    if not isinstance(meta, dict) or not isinstance(meta.get('sha256'), str):
        raise RuntimeError('Completion metadata is invalid; report preserved for review.')
    actual = digest(path.read_text())
    if meta.get('status') == 'writing':
        if actual != meta['sha256']:
            return None
        return {**meta, 'status': 'saved', 'recovered': True, 'edited': False}
    # Edits are preserved. A changed report remains complete, flagged for weekly
    # provenance and explicit refresh; an ordinary run must not overwrite it.
    return {**meta, 'edited': actual != meta['sha256']}


def _candidate_path(root, key):
    path = report_path(root, key)
    return path.with_name(path.stem + '.candidate.md')


def _journal_path(root, key):
    return report_path(root, key).with_suffix('.promotion.json')


def _write_state(root, key, status='saved', delivery='pending'):
    state = read_json(Path(root) / 'state.json', {'reports': {}})
    entry = state.setdefault('reports', {}).setdefault(key, {})
    entry['status'] = status
    entry['delivery'] = delivery
    json_write(Path(root) / 'state.json', state)


def _journal_intent(root, key, meta, candidate_text):
    """Record authorization, backup identity and metadata before replacing text."""
    import uuid
    path = report_path(root, key)
    backup = path.with_name(path.stem + '.previous-' + uuid.uuid4().hex + '.md') if path.exists() else None
    journal = {'key': key, 'candidate_sha256': digest(candidate_text),
               'base_sha256': meta.get('base_sha256'),
               'backup': backup.name if backup else None,
               'metadata': {k: v for k, v in meta.items() if k != 'base_sha256'},
               'original_metadata': read_json(path.with_suffix('.meta.json'))}
    json_write(_journal_path(root, key), journal)
    return journal


def _unlink(path):
    path.unlink(missing_ok=True)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _resume_promotion(root, key):
    """Finish one journaled promotion, including cleanup, without replacing edits."""
    journal = read_json(_journal_path(root, key))
    if not journal:
        return None
    if (not isinstance(journal, dict) or journal.get('key') != key
            or not isinstance(journal.get('metadata'), dict)
            or journal['metadata'].get('sha256') != journal.get('candidate_sha256')
            or 'base_sha256' not in journal
            or journal.get('backup') and Path(journal['backup']).name != journal['backup']):
        raise RuntimeError('Promotion journal is invalid; files preserved for review.')
    path = report_path(root, key)
    candidate = _candidate_path(root, key)
    base, target = journal['base_sha256'], journal['candidate_sha256']
    current_text = path.read_text() if path.exists() else None
    current = digest(current_text) if current_text is not None else None
    if current not in (base, target):
        raise RuntimeError('Canonical report changed after promotion began; edits preserved. Review and archive the candidate before refreshing.')
    candidate_text = candidate.read_text() if candidate.exists() else None
    if candidate_text is not None and digest(candidate_text) != target:
        raise RuntimeError('Candidate changed after interrupted promotion; review it before recovery.')
    if candidate_text is None and current != target:
        raise RuntimeError('Candidate missing before promotion completed; original and journal preserved.')
    backup = path.parent / journal['backup'] if journal['backup'] else None
    if backup:
        if backup.exists():
            if digest(backup.read_text()) != base:
                raise RuntimeError('Promotion backup changed; all files preserved for review.')
        elif current == base:
            atomic(backup, current_text)
        else:
            raise RuntimeError('Promotion backup missing; all files preserved for review.')
    meta = dict(journal['metadata'])
    # A matching canonical is evidence of replacement, including a crash before
    # checkpointing metadata. Preserve delivery already checkpointed on retry.
    saved = completion(root, key)
    if saved and saved.get('sha256') == target and saved.get('delivery') == 'delivered':
        meta.update(delivery='delivered', delivered_at=saved.get('delivered_at'))
    if current != target:
        meta['status'] = 'writing'
        json_write(path.with_suffix('.meta.json'), meta)
        atomic(path, candidate_text)
    meta['status'] = 'saved'
    json_write(path.with_suffix('.meta.json'), meta)
    _write_state(root, key, delivery=meta.get('delivery', 'pending'))
    # Keep intent until BOTH candidate files are durably removed. A crash after
    # either unlink resumes from the matching canonical and journal metadata.
    _unlink(candidate)
    _unlink(candidate.with_suffix('.meta.json'))
    _unlink(_journal_path(root, key))
    return {'status': 'promoted', 'path': str(path), 'previous': str(backup) if backup else None}


def recover(root, key):
    if _journal_path(root, key).exists():
        with locked(root):
            return _resume_promotion(root, key)
    return None


def archive_candidate(root, key):
    """Explicitly reject a candidate by archiving it, preserving all user text."""
    import uuid
    path = report_path(root, key)
    with locked(root):
        candidate = _candidate_path(root, key)
        journal_path = _journal_path(root, key)
        journal = read_json(journal_path)
        present = [item for item in (candidate, candidate.with_suffix('.meta.json'), journal_path) if item.exists()]
        if not present:
            raise RuntimeError('No candidate or interrupted promotion to archive.')
        canonical_is_target = journal and path.exists() and digest(path.read_text()) == journal['candidate_sha256']
        if canonical_is_target and journal.get('backup'):
            backup = path.parent / journal['backup']
            if not backup.exists() or digest(backup.read_text()) != journal['base_sha256']:
                raise RuntimeError('Promotion backup missing or edited; files preserved for review.')
        restore_meta = (journal['metadata'] if canonical_is_target else journal.get('original_metadata')) if journal else None
        if restore_meta:
            restore_meta = {**restore_meta, 'status': 'saved'}
            json_write(path.with_suffix('.meta.json'), restore_meta)
            _write_state(root, key, delivery=restore_meta.get('delivery', 'pending'))
        archive = path.parent / (path.stem + '.rejected-' + uuid.uuid4().hex)
        archive.mkdir(mode=0o700)
        for item in present:
            os.replace(item, archive / item.name)
        return {'status': 'archived', 'path': str(archive)}


def commit(root, key, text, metadata, refresh=False):
    if not text.strip():
        raise ValueError('Empty report.')
    path = report_path(root, key)
    with locked(root):
        _resume_promotion(root, key)
        existing = completion(root, key)
        if existing and not refresh:
            if existing.get('recovered'):
                recovered = {k: v for k, v in existing.items() if k not in ('edited', 'recovered')}
                json_write(path.with_suffix('.meta.json'), recovered)
            if existing.get('delivery') != 'delivered':
                # Reuse of a saved report must still leave delivery outstanding.
                return {'status': 'reused', 'path': str(path), 'edited': existing['edited'],
                        'delivery': 'pending'}
            return {'status': 'reused', 'path': str(path), 'edited': existing['edited'],
                    'delivery': existing.get('delivery')}
        if path.exists() and not existing and not refresh:
            raise RuntimeError('Report exists without completion metadata; inspect it and use refresh. Existing text preserved.')
        if refresh:
            base_hash = digest(path.read_text()) if path.exists() else None
            path = _candidate_path(root, key)
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
            _write_state(root, key, status='saved', delivery='pending')
    return {'status': 'candidate' if refresh else 'saved', 'path': str(path)}


def promote(root, key):
    """An explicit user-requested candidate promotion; preserve the old text."""
    path = report_path(root, key)
    candidate = _candidate_path(root, key)
    with locked(root):
        resumed = _resume_promotion(root, key)
        if resumed:
            return resumed
        meta = read_json(candidate.with_suffix('.meta.json'))
        if not meta or not candidate.exists() or digest(candidate.read_text()) != meta['sha256']:
            raise RuntimeError('Candidate missing, interrupted, or edited; review it before promotion.')
        current = digest(path.read_text()) if path.exists() else None
        if current != meta.get('base_sha256'):
            raise RuntimeError('Original changed after refresh; preserve the new edits and prepare another candidate.')
        candidate_text = candidate.read_text()
        # Journal the intent before touching the canonical report so an
        # interruption can be resumed idempotently.
        _journal_intent(root, key, meta, candidate_text)
        return _resume_promotion(root, key)


def delivered(root, key, expected_hash=None):
    with locked(root):
        path = report_path(root, key)
        meta = completion(root, key)
        if not meta:
            raise RuntimeError('Cannot mark an unsaved report delivered.')
        if expected_hash and digest(path.read_text()) != expected_hash:
            raise RuntimeError('Report changed since display; delivery remains pending. Display the current text first.')
        meta.pop('edited', None)
        meta.pop('recovered', None)
        meta['delivery'] = 'delivered'
        meta['delivered_at'] = datetime.now(timezone.utc).isoformat()
        json_write(path.with_suffix('.meta.json'), meta)
        _write_state(root, key, status='saved', delivery='delivered')


def prior_week(today):
    monday = today - timedelta(days=today.weekday() + 7)
    return f'{monday.isocalendar().year:04d}-W{monday.isocalendar().week:02d}'


def start_notice(root, key):
    """Checkpoint a single start notice; a failed run remains eligible.

    An existing entry keeps its original ``start_notice_at`` timestamp; only
    the status is refreshed so a later update never overwrites the recorded
    notice time.
    """
    report_path(root, key)
    with locked(root):
        _resume_promotion(root, key)
        state = read_json(Path(root) / 'state.json', {'reports': {}})
        entry = state.setdefault('reports', {}).setdefault(key, {})
        if entry.get('start_notice_at') or completion(root, key):
            return False
        entry['status'] = 'pending'
        entry['start_notice_at'] = datetime.now(timezone.utc).isoformat()
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
        recover(root, day)
        meta = completion(root, day)
        if not meta:
            result['missing_days'].append(day)
            continue
        partial = any(c.get('status') not in ('read', 'empty', 'not_present', 'excluded', 'disabled')
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
        recover(root, key)
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
            recover(root, week)
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
