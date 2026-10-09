"""Deterministic history collection for the Daily Recap.

Standard library only. Read-only access to known local history formats.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import sqlite3
from pathlib import Path

__all__ = [
    "timestamp",
    "window",
    "allowed",
    "collect",
    "desktop_pages",
    "segments",
]

UTC = _dt.timezone.utc

_ROLES = {"user", "assistant", "system", "tool", "developer"}

_TEXT_BLOCK_TYPES = {"input_text", "output_text", "text", "commentary"}

_INJECTED_PREFIXES = (
    "<environment_context>",
    "<user_instructions>",
    "<permissions",
    "<permissions>",
    "<system-reminder",
    "<system-reminder>",
    "<delegated_history",
    "# agents.md",
    "## instructions",
    "agents.md",
    "external_codex_apps_open_page",
    "<external_codex_apps_open_page",
    "<send_user_message_question_reply",
    "the following is the codex agent history",
)

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\.env\b(?!\.example\b)"),
    re.compile(r"(?i)\b(?:auth|credentials)\.(?:json|toml|yaml)\b"),
    re.compile(r"(?i)/(?:secrets|credentials|private|\.ssh)/|\b(?:id_rsa|id_ed25519|Platforms\.md)\b"),
    re.compile(r"(?i)\b(?:[A-Z_]*API_KEY|[A-Z_]*TOKEN|PASSWORD|SECRET)\s*[:=]\s*\S+"),
    re.compile(r"(?i)BEGIN [A-Z ]*PRIVATE KEY|\bprintenv\b|os\.environ\b"),
)

_REDACT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(api[_-]?key|secret|password|passwd|token|authorization)\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{16,}"),
)


# --- Timestamp / window -------------------------------------------------


def _as_datetime(value):
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return None


def timestamp(value):
    """Parse ISO offsets/Z or epoch seconds/milliseconds to aware UTC datetime."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        num = float(value)
        if not math.isfinite(num):
            return None
        if num < 0:
            return None
        seconds = num / 1000.0 if num > 1e11 else num
        try:
            return _dt.datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        candidate = raw
        if candidate.endswith("Z") or candidate.endswith("z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = _dt.datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return _as_datetime(parsed)

    if isinstance(value, _dt.datetime):
        return _as_datetime(value)

    return None


def window(day, zone):
    """Local [start, end) UTC datetimes for local midnight to next midnight."""
    from zoneinfo import ZoneInfo

    if isinstance(day, _dt.date) and not isinstance(day, _dt.datetime):
        day_str = day.isoformat()
    else:
        day_str = str(day)
    d = _dt.date.fromisoformat(day_str)
    tz = ZoneInfo(zone)
    start_local = _dt.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + _dt.timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


# --- Path scope ---------------------------------------------------------


def _canonical(path):
    if path is None:
        return None
    if isinstance(path, str):
        if not path.strip():
            return None
    if not os.path.isabs(str(path)):
        return None
    try:
        real = os.path.realpath(str(path))
    except (OSError, ValueError):
        return None
    name = os.path.normpath(real)
    if not os.path.isabs(name):
        return None
    return name


def _is_ancestor(parent, child):
    try:
        common = os.path.commonpath([parent, child])
    except ValueError:
        return False
    return common == parent


def allowed(workspace, roots, excludes=()):
    """True when workspace canonicalizes inside a root and outside excludes."""
    canon = _canonical(workspace)
    if canon is None:
        return False

    root_paths = []
    for root in roots or ():
        if root is None:
            continue
        resolved = _canonical(root)
        if resolved is not None:
            root_paths.append(resolved)
    if not root_paths:
        return False

    inside = any(canon == root or _is_ancestor(root, canon) for root in root_paths)
    if not inside:
        return False

    for exclude in excludes or ():
        if exclude is None:
            continue
        resolved = _canonical(exclude)
        if resolved is None:
            continue
        if canon == resolved or _is_ancestor(resolved, canon):
            return False

    return True


def _iso(dt):
    return dt.astimezone(UTC).isoformat()


# --- Text helpers -------------------------------------------------------


def _extract_text_blocks(content):
    """Extract text blocks from a Codex/OpenAI style content list."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        return ""
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in _TEXT_BLOCK_TYPES:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(p for p in parts if p)


def _text_of(message):
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        value = message.get("text")
        if isinstance(value, str):
            return value
        return _extract_text_blocks(message.get("content"))
    if isinstance(message, list):
        return _extract_text_blocks(message)
    return ""


def _is_injected_wrapper(text):
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    lowered = stripped.lower()
    if lowered.startswith("# agents.md") or lowered.startswith("agents.md"):
        return True
    if lowered.startswith("## instructions"):
        return True
    for marker in _INJECTED_PREFIXES:
        if lowered.startswith(marker):
            return True
    return False


def _has_sensitive_reference(obj):
    if obj is None:
        return False
    if isinstance(obj, str):
        return any(p.search(obj) for p in _SENSITIVE_PATTERNS)
    if isinstance(obj, dict):
        return any(_has_sensitive_reference(k) or _has_sensitive_reference(v) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return any(_has_sensitive_reference(v) for v in obj)
    return False


def _redact(text):
    if not isinstance(text, str):
        return text
    redacted = text
    for pattern in _REDACT_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def _compact_outcome(text):
    """Keep small verification results, rather than source dumps or listings."""
    if isinstance(text, (list, dict)):
        data = text
    else:
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
    def outputs(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, dict):
            for key in ('output', 'text', 'content'):
                if key in value:
                    yield from outputs(value[key], depth + 1)
            if isinstance(value.get('exit_code'), int):
                yield f"Process exit code {value['exit_code']}"
        elif isinstance(value, list):
            for item in value:
                yield from outputs(item, depth + 1)
        elif isinstance(value, str):
            try:
                nested = json.loads(value)
            except ValueError:
                nested = None
            if isinstance(nested, (list, dict)):
                yield from outputs(nested, depth + 1)
            else:
                yield value
    candidates = list(outputs(data)) if data is not None else [text]
    lines = []
    for candidate in candidates:
        for line in candidate.splitlines():
            if len(line) <= 400 and re.search(r'^\s*(?:\d+\s+(?:passed|failed|skipped)\b|Ran \d+ tests\b|FAILED\s+(?:tests/|/|\.\./)|(?:PASSED|FAILED|OK)$|(?:Process )?exit(?:ed with)? code\b|\w*(?:Error|Exception):|All checks passed)', line, re.I):
                lines.append(line)
    return '\n'.join(lines)


def _is_excluded_kind(kind):
    if kind is None:
        return False
    if isinstance(kind, dict):
        if kind.get("subagent"):
            return True
        kind = kind.get("type") or kind.get("name")
    if kind is None:
        return False
    return str(kind).lower() in {
        "guardian",
        "guardian_review",
        "subagent",
        "subagent_review",
        "review",
    }


def _iter_jsonl(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line), None
            except json.JSONDecodeError:
                yield None, "malformed"


# --- Record bookkeeping -------------------------------------------------


def _add_record(result, record):
    key = (
        record.get("source"),
        record.get("session_id"),
        record.get("message_id"),
    )
    if key in result["__seen"]:
        return False
    result["__seen"].add(key)
    result["records"].append(record)
    return True


def _coverage(result, source):
    cov = result["__coverage"].get(source)
    if cov is None:
        cov = {
            "source": source,
            "status": "not_present",
            "records": 0,
            "sessions": 0,
            "unknown_workspace": 0,
            "malformed": 0,
            "unreadable": 0,
            "notes": [],
            "excluded_sessions": 0,
        }
        result["__coverage"][source] = cov
    return cov


def _mark_partial(coverage, note=None):
    if note:
        coverage["notes"].append(note)
    if coverage["status"] in ("not_present", "empty", "read", "ok"):
        coverage["status"] = "partial"
    elif coverage["status"] == "metadata-only":
        pass
    else:
        coverage["status"] = "partial"


# --- Generic emit / context --------------------------------------------


def _select_windowed_and_context(entries, start, end, context_count):
    """Return (windowed, context) preserving timestamps; context are prior dated."""
    dated = [e for e in entries if e.get("timestamp") is not None]
    dated.sort(key=lambda e: e["timestamp"])
    windowed = [e for e in dated if start <= e["timestamp"] < end]
    if not windowed:
        return [], []
    first_ts = windowed[0]["timestamp"]
    prior = [e for e in dated if e["timestamp"] < start and e.get('kind') == 'message']
    context = prior[-context_count:] if context_count else []
    return windowed, context


def _emit_entries(
    result,
    source,
    session_id,
    cwd,
    title,
    entries,
    start,
    end,
    context_cfg,
    source_ref_base,
    session_meta=None,
):
    """Emit windowed records plus prior dated context for one session."""
    coverage = _coverage(result, source)
    windowed, context = _select_windowed_and_context(
        entries, start, end, context_cfg["context_count"]
    )
    if not windowed:
        return 0

    title = title or (session_meta or {}).get("title")
    emitted = 0
    for entry in windowed:
        ref = entry.get("source_ref") or f"{source_ref_base}:{entry['message_id']}"
        record = {
            "source": source,
            "session_id": str(session_id),
            "message_id": str(entry["message_id"]),
            "title": title,
            "workspace": cwd,
            "timestamp": _iso(entry["timestamp"]),
            "role": entry.get("role", "user"),
            "text": entry.get("text", ""),
            "source_ref": ref,
            "kind": entry.get("kind", "message"),
        }
        if entry.get("note"):
            record["note"] = entry["note"]
        if entry.get("truncated"):
            record["truncated"] = True
        if _add_record(result, record):
            coverage["records"] += 1
            emitted += 1

    for entry in context:
        ref = entry.get("source_ref") or f"{source_ref_base}:{entry['message_id']}"
        record = {
            "source": source,
            "session_id": str(session_id),
            "message_id": str(entry["message_id"]),
            "title": title,
            "workspace": cwd,
            "timestamp": _iso(entry["timestamp"]),
            "role": entry.get("role", "user"),
            "text": entry.get("text", ""),
            "source_ref": ref,
            "kind": "context",
        }
        _add_record(result, record)

    if emitted:
        coverage["sessions"] += 1
    return emitted


# --- Codex --------------------------------------------------------------


def _load_thread_titles(index_path):
    titles = {}
    if not index_path or not os.path.isfile(index_path):
        return titles
    try:
        for obj, err in _iter_jsonl(index_path):
            if not isinstance(obj, dict):
                continue
            sessions = obj.get("sessions") or obj.get("session_ids") or []
            if isinstance(sessions, str):
                sessions = [sessions]
            title = obj.get("thread_name") or obj.get("title") or obj.get("name")
            sid = obj.get("session_id") or obj.get("id")
            if sid and title:
                titles[str(sid)] = str(title)
            for s in sessions:
                if title:
                    titles[str(s)] = str(title)
    except (OSError, ValueError):
        pass
    return titles


def _read_codex(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    titles = _load_thread_titles(os.path.join(root, "session_index.jsonl"))
    session_dirs = [
        os.path.join(root, "sessions"),
        os.path.join(root, "archived_sessions"),
    ]
    found = []
    for base in session_dirs:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in sorted(filenames):
                if not name.startswith("rollout-") or not name.endswith(".jsonl"):
                    continue
                found.append(os.path.join(dirpath, name))

    if not found:
        coverage["status"] = "empty"
        return

    saw = False
    for path in sorted(found):
        saw = True
        _read_codex_file(
            path, day, zone, roots, excludes, home, result, context_cfg, titles, coverage
        )
    if coverage["status"] == "not_present":
        coverage["status"] = "read"


def _read_codex_file(
    path, day, zone, roots, excludes, home, result, context_cfg, titles, coverage
):
    start, end = window(day, zone)
    # Select by recorded metadata before loading conversation bodies. All files
    # are still considered, including old sessions and archived sessions.
    try:
        for metadata, error in _iter_jsonl(path):
            if isinstance(metadata, dict) and metadata.get('type') == 'session_meta':
                payload = metadata.get('payload', {})
                kind = payload.get('thread_source') or payload.get('source')
                cwd = payload.get('cwd')
                if _is_excluded_kind(kind) or (_canonical(cwd) is not None and not allowed(cwd, roots, excludes)):
                    coverage['excluded_sessions'] += 1
                    return
                break
    except OSError:
        coverage['unreadable'] += 1
        _mark_partial(coverage, f'unreadable: {path}')
        return
    try:
        lines = list(_iter_jsonl(path))
    except OSError:
        coverage["unreadable"] += 1
        _mark_partial(coverage, f"unreadable: {path}")
        return

    session_id = None
    cwd = None
    source_kind = None
    staged = []

    for lineno, (obj, err) in enumerate(lines, start=1):
        if err == "malformed":
            coverage["malformed"] += 1
            _mark_partial(coverage, f"malformed line {lineno}: {path}")
            continue
        if not isinstance(obj, dict):
            coverage["malformed"] += 1
            continue

        otype = obj.get("type")
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if otype == "session_meta":
            if session_id is None:
                session_id = payload.get("session_id") or payload.get("id") or obj.get("id")
            cwd = payload.get("cwd") or cwd
            source_kind = (
                payload.get("thread_source")
                or payload.get("source")
                or source_kind
            )
            continue

        if otype in ("response_item", "message"):
            staged.append((lineno, otype, obj, payload))
            continue

    if session_id is None:
        session_id = Path(path).stem

    if _is_excluded_kind(source_kind):
        coverage["excluded_sessions"] += 1
        return

    recorded_cwd = cwd
    allowed_cwd = recorded_cwd is not None and allowed(recorded_cwd, roots, excludes)
    if _canonical(recorded_cwd) is not None and not allowed_cwd:
        coverage['excluded_sessions'] += 1
        return

    title = titles.get(str(session_id))

    entries = []
    unknown_ts = False
    sensitive_calls = {payload.get('call_id') for _, _, _, payload in staged
                       if payload.get('type') in ('function_call', 'custom_tool_call')
                       and _has_sensitive_reference(payload.get('arguments', payload.get('input', '')))}
    for lineno, otype, obj, payload in staged:
        item_type = payload.get("type") or otype
        role = payload.get("role")
        channel = payload.get("channel")
        message_id = payload.get("id")
        ts = timestamp(payload.get("timestamp") or obj.get("timestamp"))
        source_ref = f"codex:{path}:{lineno}:{message_id or ''}"

        if item_type in ('function_call_output', 'custom_tool_call_output') or otype == 'function_call_output':
            if ts is None or not start <= ts < end:
                continue
            if payload.get('call_id') in sensitive_calls or _has_sensitive_reference(payload):
                coverage.setdefault('sensitive_outputs_skipped', 0)
                coverage['sensitive_outputs_skipped'] += 1
                continue
            output = payload.get("output")
            if output is None:
                output = payload.get("content")
            if not isinstance(output, (str, list, dict)) or not output:
                continue
            text = _redact(_compact_outcome(output))
            if not text:
                coverage['routine_outputs_skipped'] = coverage.get('routine_outputs_skipped', 0) + 1
                continue
            note = ""
            truncated = False
            if len(text) > context_cfg["outcome_cap"]:
                text = text[: context_cfg["outcome_cap"]]
                note = "truncated: function_call_output"
                truncated = True
                _mark_partial(coverage, "capped function_call_output")
            mid = message_id or f"{session_id}:line{lineno}"
            entries.append({
                "message_id": str(mid),
                "timestamp": ts,
                "role": "tool",
                "text": text,
                "kind": "outcome",
                "note": note,
                "truncated": truncated,
                "source_ref": source_ref,
            })
            if ts is None:
                unknown_ts = True
            continue

        if channel in ("analysis", "reasoning") or item_type in ("reasoning", "analysis"):
            continue

        if role == "assistant":
            if item_type != "message" and channel not in ("final", "commentary", None):
                continue
            text = _extract_text_blocks(payload.get("content"))
        elif role == "user":
            text = _extract_text_blocks(payload.get("content"))
        else:
            continue

        if not text:
            continue
        if _is_injected_wrapper(text):
            continue
        text = _redact(text)
        mid = message_id or f"{session_id}:line{lineno}"
        entries.append({
            "message_id": str(mid),
            "timestamp": ts,
            "role": role,
            "text": text,
            "kind": "message",
            "source_ref": source_ref,
        })
        if ts is None:
            unknown_ts = True

    if unknown_ts:
        coverage["malformed"] += 1
        _mark_partial(coverage, f"missing timestamp in {path}")

    if not allowed_cwd:
        dated = [e for e in entries if e.get("timestamp") is not None and start <= e['timestamp'] < end]
        if dated:
            marker = ('codex', str(session_id))
            if marker not in result['__unknown_sessions']:
                result['__unknown_sessions'].add(marker)
                coverage["unknown_workspace"] += 1
                _mark_partial(coverage, 'dated Codex session has unknown workspace')
        return

    _emit_entries(
        result,
        "codex",
        session_id,
        recorded_cwd,
        title,
        entries,
        start,
        end,
        context_cfg,
        f"codex:{path}",
    )


# --- Claude -------------------------------------------------------------


def _read_claude(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    base = os.path.join(root, "projects")
    if not os.path.isdir(base):
        return
    found = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in sorted(filenames):
            if name.endswith(".jsonl"):
                found.append(os.path.join(dirpath, name))
    if not found:
        coverage["status"] = "empty"
        return
    for path in found:
        _read_claude_file(path, day, zone, roots, excludes, result, context_cfg, coverage)
    if coverage["status"] == "not_present":
        coverage["status"] = "read"


def _read_claude_file(path, day, zone, roots, excludes, result, context_cfg, coverage):
    start, end = window(day, zone)
    lowered_path = path.replace(os.sep, "/").lower()
    if "/subagents/" in lowered_path or "subagent" in os.path.basename(path).lower():
        coverage["excluded_sessions"] += 1
        return

    try:
        lines = list(_iter_jsonl(path))
    except OSError:
        coverage["unreadable"] += 1
        _mark_partial(coverage, f"unreadable: {path}")
        return

    session_id = None
    cwd = None
    is_sidechain = False
    staged = []
    for lineno, (obj, err) in enumerate(lines, start=1):
        if err:
            coverage["malformed"] += 1
            _mark_partial(coverage, f"malformed line {lineno}: {path}")
            continue
        if not isinstance(obj, dict):
            coverage["malformed"] += 1
            continue
        sid = obj.get("sessionId") or obj.get("session_id")
        if sid:
            session_id = sid
        c = obj.get("cwd")
        if c:
            cwd = c
        if obj.get("isSidechain"):
            is_sidechain = True
        staged.append((lineno, obj))

    if is_sidechain:
        coverage["excluded_sessions"] += 1
        return

    if session_id is None:
        session_id = os.path.splitext(os.path.basename(path))[0]

    entries = []
    for lineno, obj in staged:
        message = obj.get("message") or {}
        role = message.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        text = _text_of(message.get("content"))
        if not text or _is_injected_wrapper(text):
            continue
        text = _redact(text)
        ts = timestamp(obj.get("timestamp"))
        mid = obj.get("uuid") or obj.get("id") or f"{session_id}:line{lineno}"
        entries.append({
            "message_id": str(mid),
            "timestamp": ts,
            "role": role,
            "text": text,
            "kind": "message",
            "source_ref": f"claude:{path}:{lineno}:{mid}",
        })

    if cwd is None:
        if any(e.get("timestamp") and start <= e['timestamp'] < end for e in entries):
            coverage["unknown_workspace"] += 1
            _mark_partial(coverage, f"unknown cwd: {path}")
        return
    if not allowed(cwd, roots, excludes):
        coverage['excluded_sessions'] += 1
        return

    _emit_entries(
        result, "claude", session_id, cwd, None, entries, start, end, context_cfg, f"claude:{path}"
    )


# --- Kimi ---------------------------------------------------------------


def _read_kimi(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    base = os.path.join(root, "sessions")
    if not os.path.isdir(base):
        return
    found = []
    for entry in sorted(os.listdir(base)):
        sdir = os.path.join(base, entry)
        if not os.path.isdir(sdir):
            continue
        for sub in sorted(os.listdir(sdir)):
            if not sub.startswith("session_"):
                continue
            wire = os.path.join(sdir, sub, "agents", "main", "wire.jsonl")
            if os.path.isfile(wire):
                found.append((os.path.join(sdir, sub), wire))
    if not found:
        coverage["status"] = "empty"
        return
    for session_dir, wire_path in found:
        _read_kimi_session(
            session_dir, wire_path, day, zone, roots, excludes, result, context_cfg, coverage
        )
    if coverage["status"] == "not_present":
        coverage["status"] = "read"


def _read_kimi_session(
    session_dir, wire_path, day, zone, roots, excludes, result, context_cfg, coverage
):
    start, end = window(day, zone)
    state_path = os.path.join(session_dir, "state.json")
    state = {}
    if os.path.isfile(state_path):
        try:
            with open(state_path, "r", encoding="utf-8", errors="replace") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            coverage["malformed"] += 1
            _mark_partial(coverage, f"malformed state: {state_path}")
            state = {}
    if not isinstance(state, dict):
        state = {}

    sid = state.get("id") or os.path.basename(session_dir)
    cwd = state.get("cwd")
    title = state.get("title")

    if not cwd:
        dated = False
        try:
            for obj, error in _iter_jsonl(wire_path):
                if isinstance(obj, dict):
                    ts = timestamp(obj.get('time') or obj.get('timestamp'))
                    if ts and start <= ts < end:
                        dated = True
                        break
        except OSError:
            coverage['unreadable'] += 1
            _mark_partial(coverage, f'unreadable history: {wire_path}')
        if dated:
            coverage["unknown_workspace"] += 1
            _mark_partial(coverage, f"dated session missing cwd: {state_path}")
        return
    if not allowed(cwd, roots, excludes):
        return

    try:
        lines = list(_iter_jsonl(wire_path))
    except OSError:
        coverage["unreadable"] += 1
        _mark_partial(coverage, f"unreadable: {wire_path}")
        return

    entries = []
    for lineno, (obj, err) in enumerate(lines, start=1):
        if err or not isinstance(obj, dict):
            coverage["malformed"] += 1
            continue
        if obj.get("type") != "agent.message.appended":
            continue
        message = obj.get("message") or {}
        msg = message.get("message") or {}
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        if msg.get("type") == "thinking" or message.get("type") == "thinking":
            continue
        text = _text_of(msg.get("content"))
        if not text or _is_injected_wrapper(text):
            continue
        text = _redact(text)
        ts = timestamp(obj.get("time") or obj.get("timestamp"))
        mid = msg.get("id") or obj.get("id") or f"{sid}:line{lineno}"
        entries.append({
            "message_id": str(mid),
            "timestamp": ts,
            "role": role,
            "text": text,
            "kind": "message",
            "source_ref": f"kimi:{wire_path}:{lineno}:{mid}",
        })

    _emit_entries(
        result, "kimi", sid, cwd, title, entries, start, end, context_cfg, f"kimi:{wire_path}"
    )


# --- SQLite helpers -----------------------------------------------------


def _ro_uri(path):
    try:
        return Path(path).resolve().as_uri() + "?mode=ro"
    except ValueError:
        return "file:" + str(path) + "?mode=ro"


# --- OpenCode -----------------------------------------------------------


def _read_opencode(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    start, end = window(day, zone)
    db_path = os.path.join(root, "opencode.db")
    if not os.path.isfile(db_path):
        return
    coverage['status'] = 'empty'
    try:
        conn = sqlite3.connect(_ro_uri(db_path), uri=True)
    except sqlite3.Error:
        coverage["unreadable"] += 1
        _mark_partial(coverage, f"unreadable: {db_path}")
        return
    try:
        cur = conn.cursor()
        try:
            sessions = cur.execute("SELECT id, directory, title FROM session").fetchall()
        except sqlite3.Error:
            coverage["unreadable"] += 1
            _mark_partial(coverage, f"schema error: {db_path}")
            return

        valid = {}
        unknown_sessions = 0
        for sid, directory, title in sessions:
            if sid is None:
                continue
            if not directory:
                dated = cur.execute('SELECT 1 FROM message WHERE session_id=? AND time_created>=? AND time_created<? LIMIT 1',
                                    (sid, start.timestamp()*1000, end.timestamp()*1000)).fetchone()
                unknown_sessions += bool(dated)
                continue
            if not allowed(directory, roots, excludes):
                continue
            valid[sid] = (directory, title)

        if unknown_sessions:
            coverage["unknown_workspace"] += unknown_sessions
            _mark_partial(coverage, "unknown opencode workspaces")

        if not valid:
            coverage["status"] = "empty"
            return

        try:
            rows = []
            for sid in valid:
                lo, hi = start.timestamp()*1000, end.timestamp()*1000
                dated = cur.execute('SELECT id, session_id, time_created, data FROM message WHERE session_id=? AND time_created>=? AND time_created<? ORDER BY time_created,id', (sid,lo,hi)).fetchall()
                if dated:
                    prior = cur.execute('SELECT id, session_id, time_created, data FROM message WHERE session_id=? AND time_created<? ORDER BY time_created DESC,id DESC LIMIT 2', (sid,lo)).fetchall()
                    rows.extend(list(reversed(prior)) + dated)
        except sqlite3.Error:
            coverage["unreadable"] += 1
            _mark_partial(coverage, f"schema error: {db_path}")
            return

        by_session = {}
        for mid, sid, created, data_json in rows:
            if sid not in valid:
                continue
            role = None
            if isinstance(data_json, str):
                try:
                    data = json.loads(data_json)
                    if isinstance(data, dict):
                        role = data.get("role")
                except ValueError:
                    coverage["malformed"] += 1
                    _mark_partial(coverage, "malformed opencode message JSON")
            if role not in ("user", "assistant"):
                continue
            ts = timestamp(created)
            if ts is None:
                if isinstance(data_json, str):
                    try:
                        data = json.loads(data_json)
                        if isinstance(data, dict):
                            ts = timestamp(data.get("time_created"))
                    except ValueError:
                        ts = None
            text = _opencode_message_text(cur, mid, coverage)
            if not text or _is_injected_wrapper(text):
                continue
            directory, title = valid[sid]
            by_session.setdefault(sid, []).append({
                "message_id": str(mid),
                "timestamp": ts,
                "role": role,
                "text": _redact(text),
                "kind": "message",
                "source_ref": f"opencode:{db_path}:{sid}:{mid}",
                "directory": directory,
                "title": title,
            })

        for sid, entries in by_session.items():
            directory, title = valid[sid]
            _emit_entries(
                result, "opencode", sid, directory, title, entries, start, end,
                context_cfg, f"opencode:{db_path}",
            )
    finally:
        conn.close()


def _opencode_message_text(cur, message_id, coverage):
    try:
        rows = cur.execute("SELECT data FROM part WHERE message_id = ?", (message_id,)).fetchall()
    except sqlite3.Error:
        return ""
    parts = []
    for (data_json,) in rows:
        if not isinstance(data_json, str):
            continue
        try:
            data = json.loads(data_json)
        except ValueError:
            coverage["malformed"] += 1
            continue
        if isinstance(data, dict) and data.get("type") == "text" and isinstance(data.get("text"), str):
            parts.append(data["text"])
    return "\n".join(parts)


# --- Hermes -------------------------------------------------------------


def _read_hermes(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    start, end = window(day, zone)
    db_path = os.path.join(root, "state.db")
    if not os.path.isfile(db_path):
        return
    coverage['status'] = 'empty'
    try:
        conn = sqlite3.connect(_ro_uri(db_path), uri=True)
    except sqlite3.Error:
        coverage["unreadable"] += 1
        _mark_partial(coverage, f"unreadable: {db_path}")
        return
    try:
        cur = conn.cursor()
        try:
            sessions = cur.execute("SELECT id, cwd, title FROM sessions").fetchall()
        except sqlite3.Error:
            coverage["unreadable"] += 1
            _mark_partial(coverage, f"schema error: {db_path}")
            return

        valid = {}
        unknown_sessions = 0
        for sid, cwd, title in sessions:
            if sid is None:
                continue
            if not cwd:
                dated = cur.execute('SELECT 1 FROM messages WHERE session_id=? AND timestamp>=? AND timestamp<? LIMIT 1',
                                    (sid, start.timestamp(), end.timestamp())).fetchone()
                unknown_sessions += bool(dated)
                continue
            if not allowed(cwd, roots, excludes):
                continue
            valid[sid] = (cwd, title)

        if unknown_sessions:
            coverage["unknown_workspace"] += unknown_sessions
            _mark_partial(coverage, "unknown hermes workspaces")

        if not valid:
            coverage["status"] = "empty"
            return

        try:
            rows = []
            columns = {r[1] for r in cur.execute('PRAGMA table_info(messages)')}
            active = ' AND active=1' if 'active' in columns else ''
            for sid in valid:
                lo, hi = start.timestamp(), end.timestamp()
                dated = cur.execute('SELECT id, session_id, role, content, timestamp FROM messages WHERE session_id=? AND timestamp>=? AND timestamp<?'+active+' ORDER BY timestamp,id', (sid,lo,hi)).fetchall()
                if dated:
                    prior = cur.execute('SELECT id, session_id, role, content, timestamp FROM messages WHERE session_id=? AND timestamp<?'+active+' ORDER BY timestamp DESC,id DESC LIMIT 2', (sid,lo)).fetchall()
                    rows.extend(list(reversed(prior)) + dated)
        except sqlite3.Error:
            coverage["unreadable"] += 1
            _mark_partial(coverage, f"schema error: {db_path}")
            return

        by_session = {}
        for mid, sid, role, content, ts_raw in rows:
            if sid not in valid:
                continue
            if role not in ("user", "assistant"):
                continue
            ts = timestamp(ts_raw)
            text = content if isinstance(content, str) else _text_of(content)
            if not text or _is_injected_wrapper(text):
                continue
            cwd, title = valid[sid]
            by_session.setdefault(sid, []).append({
                "message_id": str(mid),
                "timestamp": ts,
                "role": role,
                "text": _redact(text),
                "kind": "message",
                "source_ref": f"hermes:{db_path}:{sid}:{mid}",
                "cwd": cwd,
                "title": title,
            })

        for sid, entries in by_session.items():
            cwd, title = valid[sid]
            _emit_entries(
                result, "hermes", sid, cwd, title, entries, start, end,
                context_cfg, f"hermes:{db_path}",
            )
    finally:
        conn.close()


# --- Cursor -------------------------------------------------------------


def _read_cursor(root, day, zone, roots, excludes, home, result, context_cfg, coverage):
    db_path = os.path.join(root, "globalStorage", "conversation-search.db")
    if os.path.isfile(db_path):
        coverage["status"] = "metadata-only"
        coverage["notes"].append("metadata-only: bodies unavailable")


# --- Coverage finalize --------------------------------------------------


def _finalize_coverage(result):
    order = ["codex", "claude", "kimi", "opencode", "hermes", "cursor", "chatgpt"]
    coverage = []
    seen = set()
    for source in order:
        cov = result["__coverage"].get(source)
        if cov is None:
            cov = _coverage(result, source)
        if source == 'chatgpt':
            cov['status'] = 'unavailable'
            cov['notes'] = ['Desktop ChatGPT collection is required.']
        elif cov['status'] not in ('not_present', 'metadata-only'):
            if cov['unknown_workspace'] or cov['malformed'] or cov['unreadable'] or cov['status'] == 'partial':
                cov['status'] = 'partial'
            else:
                cov['status'] = 'read' if cov['records'] else 'empty'
        coverage.append(cov)
        seen.add(source)
    for source, cov in result["__coverage"].items():
        if source not in seen:
            coverage.append(cov)
    return coverage


# --- collect ------------------------------------------------------------


def collect(day, zone, roots, excludes=(), home=None):
    """Collect history records for the given local day across known sources."""
    if home is None:
        home = Path.home()
    home = Path(home)
    result = {
        "records": [],
        "coverage": [],
        "__seen": set(),
        "__coverage": {},
        "__unknown_sessions": set(),
    }

    context_cfg = {"context_count": 2, "outcome_cap": 4000}

    sources = [
        ("codex", os.path.join(home, ".codex"), _read_codex),
        ("claude", os.path.join(home, ".claude"), _read_claude),
        ("kimi", os.path.join(home, ".kimi-code"), _read_kimi),
        ("opencode", os.path.join(home, ".local", "share", "opencode"), _read_opencode),
        ("hermes", os.path.join(home, ".hermes"), _read_hermes),
        ("cursor", os.path.join(home, ".config", "Cursor", "User"), _read_cursor),
    ]

    for source, root, func in sources:
        coverage = _coverage(result, source)
        try:
            func(root, day, zone, roots, excludes, home, result, context_cfg, coverage)
        except Exception as exc:  # noqa: BLE001 - keep other sources collecting
            coverage["unreadable"] += 1
            _mark_partial(coverage, f"error: {exc.__class__.__name__}")

    records = result["records"]
    records.sort(key=lambda r: (
        r.get("timestamp") or "",
        r.get("source") or "",
        r.get("session_id") or "",
        r.get("message_id") or "",
    ))
    return {"records": records, "coverage": _finalize_coverage(result)}


# --- ChatGPT desktop pages ---------------------------------------------


def _clean_ref(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"::chatgpt-content-reference\{[^}]*\}", "", text).strip()


def desktop_pages(pages, day, zone):
    """Normalize ChatGPT read_thread JSON pages supplied by the lead."""
    start, end = window(day, zone)
    records = []
    seen = set()
    status = {
        "source": "chatgpt",
        "status": "ok",
        "records": 0,
        "sessions": 0,
        "unknown_workspace": 0,
        "malformed": 0,
        "unreadable": 0,
        "notes": [],
        "excluded_sessions": 0,
        "unavailable": 0,
        "truncated": 0,
    }

    if not pages:
        status["status"] = "unavailable"
        status["notes"].append("chatgpt status requires desktop collection")
        return {"records": [], "coverage": [status]}

    threads = {}
    requested_cursors = {}
    supplied_cursors = set()
    failed = False
    partial = False

    for page in pages:
        if not isinstance(page, dict):
            status["malformed"] += 1
            partial = True
            continue
        if page.get("error"):
            failed = True
            partial = True
            status["notes"].append("failed page envelope")
            continue
        thread = page.get("thread") or {}
        page_meta = page.get("page") or {}
        tid = thread.get("id") or "unknown"
        title = thread.get("title")
        entry = threads.setdefault(tid, {"title": title})
        if title and not entry.get("title"):
            entry["title"] = title

        cursor = page_meta.get("cursor")
        if cursor:
            supplied_cursors.add((tid, cursor))
        next_cursor = page_meta.get("nextCursor")
        envelope_has_more = bool(page_meta.get("hasMore"))
        if envelope_has_more:
            if not next_cursor:
                partial = True
                status["notes"].append("hasMore without next cursor")
            else:
                if next_cursor in requested_cursors.get(tid, set()):
                    partial = True
                    status['notes'].append('repeated next-page cursor')
                requested_cursors.setdefault(tid, set()).add(next_cursor)

        for turn in page.get("turns") or []:
            if not isinstance(turn, dict):
                status["malformed"] += 1
                continue
            turn_id = turn.get("id") or str(len(records))
            user_ts = timestamp(turn.get("startedAt"))
            agent_ts = timestamp(turn.get("completedAt"))
            for item in turn.get("items") or []:
                if not isinstance(item, dict):
                    status["malformed"] += 1
                    continue
                item_id = item.get("id") or f"{turn_id}:{len(records)}"
                itype = item.get("type")
                item_ts = timestamp(
                    item.get("timestamp") or item.get("time") or item.get("createdAt")
                )
                if itype == "userMessage":
                    role = "user"
                    ts = item_ts or user_ts
                    text = _extract_text_blocks(item.get("content"))
                    if not text and isinstance(item.get("text"), str):
                        text = item["text"]
                elif itype == "agentMessage":
                    role = "assistant"
                    ts = item_ts or agent_ts
                    text = item.get("text") if isinstance(item.get("text"), str) else ""
                    if not text:
                        text = _extract_text_blocks(item.get("content"))
                else:
                    continue

                if ts is None or not (start <= ts < end):
                    continue

                block_truncated = bool(item.get("truncated"))
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("truncated"):
                            block_truncated = True
                cleaned = _clean_ref(text)
                key = ('chatgpt', str(tid), str(item_id))
                if key in seen:
                    continue
                seen.add(key)
                if block_truncated:
                    status['truncated'] += 1
                    partial = True
                if not cleaned and itype == "agentMessage":
                    status["unavailable"] += 1
                    partial = True
                    continue
                if not cleaned:
                    continue

                record = {
                    "source": "chatgpt",
                    "session_id": str(tid),
                    "message_id": str(item_id),
                    "title": threads[tid].get("title"),
                    "workspace": None,
                    "timestamp": _iso(ts),
                    "role": role,
                    "text": _redact(cleaned),
                    "source_ref": f"chatgpt:{tid}:{item_id}",
                    "kind": "message",
                }
                if block_truncated:
                    record["truncated"] = True
                records.append(record)
                status["records"] += 1

    for tid, cursors in requested_cursors.items():
        for cursor in cursors:
            if (tid, cursor) not in supplied_cursors:
                partial = True
                status["notes"].append(f"missing next page for cursor {cursor!r}")

    if failed:
        partial = True
    if status['malformed']:
        partial = True
    status["status"] = "partial" if partial else "read"
    if status["status"] == "read" and not records:
        status["status"] = "empty"
        status["notes"].append("no messages in window")

    if records:
        status["sessions"] = len({r["session_id"] for r in records})

    records.sort(key=lambda r: (
        r.get("timestamp") or "",
        r.get("source") or "",
        r.get("session_id") or "",
        r.get("message_id") or "",
    ))
    return {"records": records, "coverage": [status]}


# --- Segmentation -------------------------------------------------------


def segments(records, max_chars=24000):
    """Split records into bounded segments without dropping characters."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    out = []
    current = []
    current_size = 0

    def flush():
        nonlocal current, current_size
        if current:
            out.append(current)
            current = []
            current_size = 0

    for record in records:
        text = record.get("text", "")
        if not isinstance(text, str):
            text = str(text)

        if len(text) <= max_chars:
            if current and current_size + len(text) > max_chars:
                flush()
            current.append(dict(record))
            current_size += len(text)
            continue

        flush()
        total_parts = (len(text) + max_chars - 1) // max_chars
        for part_index, start in enumerate(range(0, len(text), max_chars)):
            part = text[start:start + max_chars]
            chunk = dict(record)
            chunk["text"] = part
            chunk["original_message_id"] = record.get("message_id")
            chunk["part_index"] = part_index
            chunk["part_id"] = part_index
            chunk["part_total"] = total_parts
            chunk["message_id"] = f"{record.get('message_id')}#part{part_index}"
            out.append([chunk])

    flush()
    return out
