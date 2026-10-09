import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import reader  # noqa: E402


DAY_TS = dt.datetime(2026, 10, 9, 1, 0, tzinfo=dt.timezone.utc)
DAY_EPOCH = DAY_TS.timestamp()
PREV_TS = dt.datetime(2026, 10, 8, 1, 0, tzinfo=dt.timezone.utc)
PREV_EPOCH = PREV_TS.timestamp()


def iso(dt_value):
    return dt_value.astimezone(dt.timezone.utc).isoformat()


class TimestampTests(unittest.TestCase):
    def test_iso_z_and_offset(self):
        a = reader.timestamp("2026-10-09T00:00:00Z")
        b = reader.timestamp("2026-10-09T08:00:00+08:00")
        self.assertEqual(a, b)
        self.assertEqual(a.tzinfo, dt.timezone.utc)

    def test_epoch_seconds_and_millis(self):
        sec = reader.timestamp(DAY_EPOCH)
        ms = reader.timestamp(DAY_EPOCH * 1000)
        self.assertEqual(sec, ms)

    def test_invalid_values(self):
        self.assertIsNone(reader.timestamp(True))
        self.assertIsNone(reader.timestamp(False))
        self.assertIsNone(reader.timestamp(float("nan")))
        self.assertIsNone(reader.timestamp(float("inf")))
        self.assertIsNone(reader.timestamp("not-a-date"))
        self.assertIsNone(reader.timestamp(None))


class WindowTests(unittest.TestCase):
    def test_midnight(self):
        start, end = reader.window("2026-10-09", "UTC")
        self.assertEqual(start, dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc))
        self.assertEqual(end - start, dt.timedelta(days=1))

    def test_dst(self):
        start, end = reader.window("2026-03-08", "America/New_York")
        self.assertEqual((end - start).total_seconds(), 23 * 3600)
        start2, end2 = reader.window("2026-11-01", "America/New_York")
        self.assertEqual((end2 - start2).total_seconds(), 25 * 3600)


class AllowedTests(unittest.TestCase):
    def test_boundary_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            root = tmp / "root"
            root.mkdir()
            inside = root / "proj"
            inside.mkdir()
            outside = tmp / "other"
            outside.mkdir()
            link = root / "escape"
            os.symlink(outside, link)

            self.assertTrue(reader.allowed(inside, [root]))
            self.assertTrue(reader.allowed(root, [root]))
            self.assertFalse(reader.allowed(outside, [root]))
            self.assertFalse(reader.allowed(link, [root]))
            self.assertFalse(reader.allowed(inside, [root], [inside]))

    def test_unknown_cwd(self):
        self.assertFalse(reader.allowed(None, ["/tmp"]))
        self.assertFalse(reader.allowed("", ["/tmp"]))
        self.assertFalse(reader.allowed("relative/path", ["/tmp"]))


class SegmentsTests(unittest.TestCase):
    def test_bounded_and_complete(self):
        recs = [
            {"message_id": "m1", "source": "s", "text": "a" * 10},
            {"message_id": "m2", "source": "s", "text": "b" * 50},
        ]
        segs = reader.segments(recs, max_chars=20)
        total = "".join(r["text"] for seg in segs for r in seg)
        self.assertEqual(total, "a" * 10 + "b" * 50)
        for seg in segs:
            self.assertLessEqual(sum(len(r["text"]) for r in seg), 20)
        parts = [r for seg in segs for r in seg if r.get("original_message_id") == "m2"]
        self.assertGreaterEqual(len(parts), 3)
        self.assertTrue(all(r["message_id"].startswith("m2#part") for r in parts))
        self.assertTrue(all(r["part_total"] == 3 for r in parts))

    def test_preserves_source(self):
        recs = [{"message_id": "m1", "source": "codex", "text": "x" * 100}]
        segs = reader.segments(recs, max_chars=10)
        for seg in segs:
            for r in seg:
                self.assertEqual(r["source"], "codex")
                self.assertEqual(r["original_message_id"], "m1")

    def test_message_id_traceable(self):
        recs = [{"message_id": "m1", "source": "s", "text": "z" * 25}]
        segs = reader.segments(recs, max_chars=10)
        chunks = [r for seg in segs for r in seg]
        self.assertEqual(len(chunks), 3)
        self.assertEqual([c["part_index"] for c in chunks], [0, 1, 2])
        self.assertTrue(all(c["original_message_id"] == "m1" for c in chunks))


class DesktopPagesTests(unittest.TestCase):
    def _envelope(self, has_more=False, cursor=None):
        return {
            "thread": {"id": "chat1", "title": "Cake"},
            "page": {"hasMore": has_more, "nextCursor": cursor},
            "turns": [
                {
                    "id": "turn1",
                    "startedAt": DAY_EPOCH,
                    "completedAt": DAY_EPOCH + 1,
                    "items": [
                        {
                            "type": "userMessage",
                            "id": "u1",
                            "content": [
                                {"type": "text", "text": "How do I bake cake?", "truncated": False}
                            ],
                        },
                        {
                            "type": "agentMessage",
                            "id": "a1",
                            "text": '::chatgpt-content-reference{index="0" source_message_id="a1"}',
                        },
                    ],
                }
            ],
        }

    def test_basic(self):
        out = reader.desktop_pages([self._envelope()], "2026-10-09", "UTC")
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["records"][0]["role"], "user")
        self.assertEqual(out["coverage"][0]["unavailable"], 1)
        self.assertEqual(out["coverage"][0]["status"], "partial")

    def test_has_more_without_next_is_partial(self):
        env = self._envelope(has_more=True, cursor=None)
        out = reader.desktop_pages([env], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["status"], "partial")

    def test_missing_subsequent_page_is_partial(self):
        env = self._envelope(has_more=True, cursor="page2")
        out = reader.desktop_pages([env], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["status"], "partial")
        self.assertTrue(any("missing next page" in n for n in out["coverage"][0]["notes"]))

    def test_completed_pagination(self):
        first = self._envelope(has_more=True, cursor="page2")
        second = self._envelope()
        second["page"]["cursor"] = "page2"
        out = reader.desktop_pages([first, second], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["status"], "partial")  # placeholder reply

    def test_duplicate_pages_dedup(self):
        env = self._envelope()
        out = reader.desktop_pages([env, env], "2026-10-09", "UTC")
        self.assertEqual(len(out["records"]), 1)

    def test_failed_envelope_is_partial(self):
        out = reader.desktop_pages([{"error": "boom"}], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["status"], "partial")

    def test_truncated_block_flag(self):
        env = self._envelope()
        env["turns"][0]["items"][0]["content"][0]["truncated"] = True
        out = reader.desktop_pages([env], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["truncated"], 1)
        self.assertTrue(out["records"][0].get("truncated"))

    def test_out_of_window_message_not_counted(self):
        env = self._envelope()
        env["turns"][0]["startedAt"] = PREV_EPOCH
        env["turns"][0]["completedAt"] = PREV_EPOCH
        out = reader.desktop_pages([env], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["truncated"], 0)
        self.assertEqual(out["coverage"][0]["unavailable"], 0)

    def test_empty_is_unavailable(self):
        out = reader.desktop_pages([], "2026-10-09", "UTC")
        self.assertEqual(out["coverage"][0]["status"], "unavailable")


class CollectCodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir(parents=True)
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_rollout(self, name, cwd, session_id, messages, archived=False):
        base = "archived_sessions" if archived else "sessions"
        path = self.home / ".codex" / base / name
        body = _line({"type": "session_meta", "payload": {"id": session_id, "cwd": str(cwd) if cwd is not None else None}})
        for i, (role, text, ts) in enumerate(messages):
            body += _line({
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "id": f"m{i}",
                    "role": role,
                    "timestamp": ts,
                    "content": [{"type": "input_text", "text": text}],
                },
            })
        _write(path, body)

    def test_collects_window_and_skips_analysis(self):
        path = self.home / ".codex" / "sessions" / "rollout-1.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "sess1", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "m0", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "hello"}]},
        })
        body += _line({
            "type": "response_item",
            "payload": {"type": "reasoning", "id": "m1", "role": "assistant",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "secret reasoning"}]},
        })
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "m2", "role": "assistant",
                        "channel": "analysis", "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "analysis text"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        ids = [r["message_id"] for r in result["records"]]
        self.assertIn("m0", ids)
        self.assertNotIn("m1", ids)
        self.assertNotIn("m2", ids)
        texts = [r["text"] for r in result["records"]]
        self.assertNotIn("secret reasoning", texts)
        self.assertNotIn("analysis text", texts)

    def test_old_session_updated_on_requested_day(self):
        path = self.home / ".codex" / "sessions" / "rollout-old.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "s1", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "m1", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "late message"}]},
        })
        _write(path, body)
        old = 1000000
        os.utime(path, (old, old))
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["message_id"] == "m1" for r in result["records"]))

    def test_archived_logs(self):
        self._write_rollout(
            "rollout-arch.jsonl", self.ws, "a",
            [("user", "arch", iso(DAY_TS))],
            archived=True,
        )
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["message_id"] == "m0" for r in result["records"]))

    def test_different_identical_messages_stay_distinct(self):
        path = self.home / ".codex" / "sessions" / "rollout-2.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "sess2", "cwd": str(self.ws)}})
        for i, msg_id in enumerate(["m1", "m2"]):
            body += _line({
                "type": "response_item",
                "payload": {"type": "message", "id": msg_id, "role": "user",
                            "timestamp": iso(DAY_TS + dt.timedelta(minutes=i)),
                            "content": [{"type": "input_text", "text": "same"}]},
            })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertEqual(len([r for r in result["records"] if r["text"] == "same"]), 2)

    def test_session_id_fallback_preserved(self):
        path = self.home / ".codex" / "sessions" / "rollout-keep.jsonl"
        body = _line({"type": "session_meta", "payload": {"session_id": "kept", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "mX", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "x"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["session_id"] == "kept" for r in result["records"]))

    def test_malformed_and_unreadable_visible(self):
        path = self.home / ".codex" / "sessions" / "rollout-mal.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "m", "cwd": str(self.ws)}})
        body += "{not json}\n"
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "ok", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "fine"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "codex"][0]
        self.assertGreaterEqual(cov["malformed"], 1)
        self.assertEqual(cov["status"], "partial")

    def test_unknown_workspace_counted(self):
        self._write_rollout(
            "rollout-u.jsonl", None, "u",
            [("user", "x", iso(DAY_TS))],
        )
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "codex"][0]
        self.assertGreaterEqual(cov["unknown_workspace"], 1)
        self.assertEqual(result["records"], [])

    def test_outside_root_not_counted_unknown(self):
        outside = Path(self.tmp.name) / "far"
        outside.mkdir()
        path = self.home / ".codex" / "sessions" / "rollout-far.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "f", "cwd": str(outside)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "f1", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "far"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "codex"][0]
        self.assertEqual(cov["unknown_workspace"], 0)
        self.assertEqual(result["records"], [])

    def test_outcome_and_context(self):
        path = self.home / ".codex" / "sessions" / "rollout-o.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "o", "cwd": str(self.ws)}})
        for i, role in enumerate(["user", "assistant", "user"]):
            body += _line({
                "type": "response_item",
                "payload": {"type": "message", "id": f"c{i}", "role": role,
                            "timestamp": iso(PREV_TS + dt.timedelta(minutes=i)),
                            "content": [{"type": "input_text", "text": f"prev{i}"}]},
            })
        body += _line({
            "type": "response_item",
            "payload": {"type": "function_call_output", "id": "out1",
                        "timestamp": iso(DAY_TS), "output": "3 passed in 0.2s"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        kinds = {r["message_id"]: r["kind"] for r in result["records"]}
        self.assertEqual(kinds.get("out1"), "outcome")
        contexts = [r for r in result["records"] if r["kind"] == "context"]
        self.assertLessEqual(len(contexts), 2)

    def test_outcome_outside_window_skipped(self):
        path = self.home / ".codex" / "sessions" / "rollout-o2.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "o2", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "function_call_output", "id": "oldout",
                        "timestamp": iso(PREV_TS), "output": "2 passed in 0.2s"},
        })
        body += _line({
            "type": "response_item",
            "payload": {"type": "function_call_output", "id": "futureout",
                        "timestamp": iso(DAY_TS + dt.timedelta(days=1)), "output": "future"},
        })
        body += _line({
            "type": "response_item",
            "payload": {"type": "function_call_output", "id": "todayout",
                        "timestamp": iso(DAY_TS), "output": "3 passed in 0.2s"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        ids = {r["message_id"] for r in result["records"]}
        self.assertNotIn("oldout", ids)
        self.assertNotIn("futureout", ids)
        self.assertIn("todayout", ids)

    def test_sensitive_outcome_skipped(self):
        path = self.home / ".codex" / "sessions" / "rollout-sec.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "sec", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "function_call_output", "id": "secout",
                        "timestamp": iso(DAY_TS), "output": "cat /home/user/.env"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertFalse(any(r["message_id"] == "secout" for r in result["records"]))

    def test_injected_wrapper_skipped(self):
        path = self.home / ".codex" / "sessions" / "rollout-inj.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "inj", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "inj1", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text",
                                     "text": "<system-reminder>hidden</system-reminder>"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertEqual(result["records"], [])

    def test_excluded_guardian_session(self):
        path = self.home / ".codex" / "sessions" / "rollout-g.jsonl"
        body = _line({
            "type": "session_meta",
            "payload": {"id": "g", "cwd": str(self.ws), "source": "guardian_review"},
        })
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "g1", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "guardian"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "codex"][0]
        self.assertGreaterEqual(cov["excluded_sessions"], 1)
        self.assertEqual(result["records"], [])

    def test_title_from_session_index_thread_name(self):
        index_path = self.home / ".codex" / "session_index.jsonl"
        _write(index_path, _line({"session_id": "t1", "thread_name": "My Thread"}))
        path = self.home / ".codex" / "sessions" / "rollout-t.jsonl"
        body = _line({"type": "session_meta", "payload": {"id": "t1", "cwd": str(self.ws)}})
        body += _line({
            "type": "response_item",
            "payload": {"type": "message", "id": "tmsg", "role": "user",
                        "timestamp": iso(DAY_TS),
                        "content": [{"type": "input_text", "text": "titled"}]},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        rec = [r for r in result["records"] if r["message_id"] == "tmsg"][0]
        self.assertEqual(rec["title"], "My Thread")


class CollectClaudeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir(parents=True)
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_claude_requires_cwd(self):
        path = self.home / ".claude" / "projects" / "p" / "s.jsonl"
        body = _line({
            "sessionId": "s1", "cwd": str(self.ws), "uuid": "u1",
            "timestamp": iso(DAY_TS),
            "message": {"role": "user", "content": "hi"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["source"] == "claude" for r in result["records"]))

    def test_claude_missing_cwd_counts_unknown(self):
        path = self.home / ".claude" / "projects" / "p" / "n.jsonl"
        body = _line({
            "sessionId": "s2", "uuid": "u2", "timestamp": iso(DAY_TS),
            "message": {"role": "user", "content": "hi"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "claude"][0]
        self.assertGreaterEqual(cov["unknown_workspace"], 1)

    def test_claude_subagent_skipped(self):
        path = self.home / ".claude" / "projects" / "p" / "subagents" / "agent-x.jsonl"
        body = _line({
            "sessionId": "s3", "cwd": str(self.ws), "uuid": "u3",
            "timestamp": iso(DAY_TS), "isSidechain": True,
            "message": {"role": "user", "content": "sub"},
        })
        _write(path, body)
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "claude"][0]
        self.assertGreaterEqual(cov["excluded_sessions"], 1)
        self.assertFalse(any(r["source"] == "claude" for r in result["records"]))


class CollectKimiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir(parents=True)
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _session_dir(self, outer, inner):
        return self.home / ".kimi-code" / "sessions" / outer / inner

    def test_nested_kimi_layout(self):
        sdir = self._session_dir("proj", "session_abc")
        state = {"id": "k1", "cwd": str(self.ws), "title": "K"}
        _write(sdir / "state.json", json.dumps(state))
        wire = {
            "type": "agent.message.appended",
            "time": iso(DAY_TS),
            "message": {"message": {"id": "km1", "role": "user", "content": "kimi hi"}},
        }
        _write(sdir / "agents" / "main" / "wire.jsonl", _line(wire))
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["source"] == "kimi" for r in result["records"]))

    def test_kimi_thinking_excluded(self):
        sdir = self._session_dir("proj", "session_abc")
        state = {"id": "k2", "cwd": str(self.ws), "title": "K"}
        _write(sdir / "state.json", json.dumps(state))
        thinking = {
            "type": "agent.message.appended",
            "time": iso(DAY_TS),
            "message": {"type": "thinking",
                        "message": {"id": "kt1", "role": "assistant", "content": "hmm"}},
        }
        user = {
            "type": "agent.message.appended",
            "time": iso(DAY_TS),
            "message": {"message": {"id": "ku1", "role": "user", "content": "real"}},
        }
        _write(sdir / "agents" / "main" / "wire.jsonl", _line(thinking) + _line(user))
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        ids = {r["message_id"] for r in result["records"]}
        self.assertIn("ku1", ids)
        self.assertNotIn("kt1", ids)

    def test_kimi_missing_cwd_visible(self):
        sdir = self._session_dir("proj", "session_abc")
        _write(sdir / "state.json", json.dumps({"id": "k3", "title": "K"}))
        wire = {
            "type": "agent.message.appended",
            "time": iso(DAY_TS),
            "message": {"message": {"id": "km9", "role": "user", "content": "hi"}},
        }
        _write(sdir / "agents" / "main" / "wire.jsonl", _line(wire))
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        cov = [c for c in result["coverage"] if c["source"] == "kimi"][0]
        self.assertGreaterEqual(cov["unknown_workspace"], 1)


class CollectSqliteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir(parents=True)
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_opencode_readonly(self):
        db_dir = self.home / ".local" / "share" / "opencode"
        db_dir.mkdir(parents=True)
        db = db_dir / "opencode.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE session (id TEXT, directory TEXT, title TEXT)")
        conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created REAL, data TEXT)")
        conn.execute("CREATE TABLE part (message_id TEXT, data TEXT)")
        conn.execute("INSERT INTO session VALUES ('s1', ?, 'T')", (str(self.ws),))
        conn.execute(
            "INSERT INTO message VALUES ('m1','s1',?,?)",
            (DAY_EPOCH * 1000, json.dumps({"role": "user"})),
        )
        conn.execute(
            "INSERT INTO part VALUES ('m1', ?)",
            (json.dumps({"type": "text", "text": "db message"}),),
        )
        conn.commit()
        conn.close()
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["source"] == "opencode" for r in result["records"]))

    def test_opencode_distinct_sessions_same_workspace(self):
        db_dir = self.home / ".local" / "share" / "opencode"
        db_dir.mkdir(parents=True)
        db = db_dir / "opencode.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE session (id TEXT, directory TEXT, title TEXT)")
        conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created REAL, data TEXT)")
        conn.execute("CREATE TABLE part (message_id TEXT, data TEXT)")
        conn.execute("INSERT INTO session VALUES ('s1', ?, 'T1')", (str(self.ws),))
        conn.execute("INSERT INTO session VALUES ('s2', ?, 'T2')", (str(self.ws),))
        conn.execute("INSERT INTO message VALUES ('m1','s1',?,?)", (DAY_EPOCH * 1000, json.dumps({"role": "user"})))
        conn.execute("INSERT INTO message VALUES ('m2','s2',?,?)", (DAY_EPOCH * 1000, json.dumps({"role": "user"})))
        conn.execute("INSERT INTO part VALUES ('m1', ?)", (json.dumps({"type": "text", "text": "one"}),))
        conn.execute("INSERT INTO part VALUES ('m2', ?)", (json.dumps({"type": "text", "text": "two"}),))
        conn.commit()
        conn.close()
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        sids = {r["session_id"] for r in result["records"] if r["source"] == "opencode"}
        self.assertEqual(sids, {"s1", "s2"})

    def test_opencode_readonly_invariant(self):
        db_dir = self.home / ".local" / "share" / "opencode"
        db_dir.mkdir(parents=True)
        db = db_dir / "opencode.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE session (id TEXT, directory TEXT, title TEXT)")
        conn.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created REAL, data TEXT)")
        conn.execute("CREATE TABLE part (message_id TEXT, data TEXT)")
        conn.commit()
        conn.close()
        before = db.read_bytes()
        reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        after = db.read_bytes()
        self.assertEqual(before, after)

    def test_hermes_readonly(self):
        db_dir = self.home / ".hermes"
        db_dir.mkdir(parents=True)
        db = db_dir / "state.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id TEXT, cwd TEXT, title TEXT)")
        conn.execute(
            "CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT, timestamp REAL)"
        )
        conn.execute("INSERT INTO sessions VALUES ('s1', ?, 'T')", (str(self.ws),))
        conn.execute(
            "INSERT INTO messages VALUES ('m1','s1','user','hermes msg',?)",
            (DAY_EPOCH,),
        )
        conn.commit()
        conn.close()
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertTrue(any(r["source"] == "hermes" for r in result["records"]))

    def test_hermes_invalid_workspace_not_read(self):
        db_dir = self.home / ".hermes"
        db_dir.mkdir(parents=True)
        db = db_dir / "state.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id TEXT, cwd TEXT, title TEXT)")
        conn.execute(
            "CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT, timestamp REAL)"
        )
        conn.execute("INSERT INTO sessions VALUES ('s1', '/outside', 'T')")
        conn.execute(
            "INSERT INTO messages VALUES ('m1','s1','user','should not appear',?)",
            (DAY_EPOCH,),
        )
        conn.commit()
        conn.close()
        result = reader.collect("2026-10-09", "UTC", [str(self.ws)], (), home=self.home)
        self.assertFalse(any(r["source"] == "hermes" for r in result["records"]))


class CursorTests(unittest.TestCase):
    def test_cursor_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = home / ".config" / "Cursor" / "User" / "globalStorage" / "conversation-search.db"
            _write(db, "not-a-db")
            result = reader.collect("2026-10-09", "UTC", ["/tmp"], (), home=home)
            cov = [c for c in result["coverage"] if c["source"] == "cursor"][0]
            self.assertEqual(cov["status"], "metadata-only")
            self.assertEqual(result["records"], [])


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _line(obj):
    return json.dumps(obj) + "\n"


if __name__ == "__main__":
    unittest.main()
