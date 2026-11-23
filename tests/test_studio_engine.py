"""Offline tests for the studio engine. No network, no real model, temp folders only.

Run from the repository root:  python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import random
import shutil
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from studio import cli, config, folder, journal, limits, model, pulse, schedule, wake, wire  # noqa: E402
from studio.folder import Paths  # noqa: E402
from studio.types import ModelReply, SenseReading, Usage, VerbResult, VerbSpec  # noqa: E402

FAKE = os.path.join(ROOT, "tests", "fake_claude_stream.py")
MARKER = "QUILLFEATHERZEBRA"
TOKEN = "tok-SEKRIT-4242-never-print"
ALLOWED_ENV = {"HOME", "PATH", "LANG", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy",
               "no_proxy", "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
               "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS", "CLAUDE_CODE_DISABLE_FILE_CHECKPOINTING",
               "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_EVAL_CONFINED", "DISABLE_AUTOUPDATER",
               "ENABLE_CLAUDEAI_MCP_SERVERS"}


# ---- helpers ----------------------------------------------------------------------------------

class Clock:
    def __init__(self, start=datetime(2027, 1, 10, 9, 0, tzinfo=timezone.utc)):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


class FakeSense:
    def __init__(self, name, text="still dark.", changed=False):
        self.name, self.text, self.changed = name, text, changed

    def read(self, ctx):
        return SenseReading(self.name, self.text, self.changed)


class RaisingSense:
    name = "body"

    def read(self, ctx):
        raise RuntimeError("sensor broke")


class NoneSense:
    name = "house"

    def read(self, ctx):
        return None


def v_window(ctx, arg):
    return VerbResult("The sky is dark and the wind is up.", "looked out the window")


def v_boom(ctx, arg):
    raise RuntimeError("handler broke")


FAKE_VERBS = [VerbSpec("window", "look out the window", False, v_window),
              VerbSpec("boom", "a verb that breaks", False, v_boom)]


def snapshot(root):
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            st = os.lstat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def tree_text(root):
    chunks = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            try:
                with open(os.path.join(d, f), "rb") as fh:
                    chunks.append(fh.read().decode("utf-8", "replace"))
            except OSError:
                pass
    return "\n".join(chunks)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.ident = os.path.join(self.tmp, "portrait.md")
        with open(self.ident, "w") as f:
            f.write("# Portrait\n\n### 1. IDENTITY\nThe agent is patient. " + MARKER + "\n\n### 2. NEXT\nother\n")
        self.env = {"HOME": self.tmp, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    def cfg(self, extra=None, name="config.json"):
        data = {"studio_dir": os.path.join(self.tmp, "studio"),
                "identity": {"path": self.ident, "start": "### 1. ", "end": "### 2. "},
                "senses": {"sky": False, "body": False, "house": False, "song": False},
                "pulse": {"min_seconds": 1, "max_seconds": 2, "song_seconds": 1}}
        for k, v in (extra or {}).items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k] = {**data[k], **v}
            else:
                data[k] = v
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            json.dump(data, f)
        return config.load(path, self.env)

    def fake_cmd(self, mode="ok", answers=None):
        cmd = ["/usr/bin/env", f"FAKE_CLAUDE_MODE={mode}"]
        if answers is not None:
            p = os.path.join(self.tmp, f"answers-{mode}-{len(answers)}.txt")
            with open(p, "w") as f:
                f.write("\n".join(a.replace("\n", "\\n") for a in answers) + "\n")
            cmd.append(f"FAKE_CLAUDE_ANSWERS={p}")
        return cmd + [sys.executable, FAKE]

    def run_wake(self, cfg, script, clock=None, senses=None, verbs=None, on_send=None, usage=Usage(100, 0, 0, 10),
                 **kw):
        clock = clock or Clock()
        paths = Paths.from_config(cfg)
        sessions = []

        def factory(sp):
            s = model.FakeSession(script, usage=usage, on_send=on_send)
            sessions.append(s)
            return s
        o = wake.run(cfg, paths, now=clock.now, sleep=clock.sleep, rng=random.Random(1),
                     senses=senses if senses is not None else [FakeSense("sky")],
                     verbs=verbs if verbs is not None else FAKE_VERBS, session_factory=factory, fetch=None,
                     collect_channel=False, **kw)
        return o, paths, sessions

    def journal_text(self, paths):
        with open(paths.journal) as f:
            return f.read()


# ---- 1. config --------------------------------------------------------------------------------

class TestConfig(Base):
    def test_defaults(self):
        c = config.load(None, {"HOME": self.tmp})
        self.assertIsNone(c.source_path)
        self.assertEqual(c.studio_dir, os.path.join(self.tmp, "studio"))
        self.assertEqual(c.kill_switch, os.path.join(self.tmp, "studio", "OFF"))
        self.assertEqual(c.paper.dir, os.path.join(self.tmp, "studio", "for-the-paper"))
        self.assertEqual(c.schedule.end_by, "06:00")
        self.assertEqual(c.schedule.time_zone, "UTC")
        self.assertIsNone(c.town.name)
        self.assertIsNone(c.identity.path)
        self.assertEqual(c.limits.max_turns, 12)
        self.assertEqual(c.limits.wakeup_tokens, 150000)
        self.assertEqual(c.limits.daily_tokens, 400000)
        self.assertEqual(c.model.command, ("claude",))
        self.assertEqual(c.model.name, "opus")
        self.assertIsNone(c.reading.start_date)
        self.assertIsNone(c.channel.chat_id)
        self.assertTrue(all([c.verbs.window, c.verbs.sleep, c.senses.sky, c.weather.enabled]))
        self.assertEqual(c.pulse.quiet_chance, 0.6)

    def test_unknown_key(self):
        with self.assertRaises(config.ConfigError) as e:
            self.cfg({"limits": {"max_turnz": 3}})
        self.assertIn("limits.max_turnz", str(e.exception))
        with self.assertRaises(config.ConfigError):
            self.cfg({"surprise": 1})

    def test_wrong_type_names_key_not_value(self):
        with self.assertRaises(config.ConfigError) as e:
            self.cfg({"model": {"name": 12345678}})
        self.assertIn("model.name", str(e.exception))
        self.assertNotIn("12345678", str(e.exception))
        with self.assertRaises(config.ConfigError):
            self.cfg({"limits": {"max_turns": True}})
        with self.assertRaises(config.ConfigError):
            self.cfg({"limits": {"max_turns": 41}})
        with self.assertRaises(config.ConfigError):
            self.cfg({"reading": {"sources": [{"name": "x", "kind": "rss", "url": "http://example.org/feed"}]}})

    def test_studio_dir_env(self):
        other = os.path.join(self.tmp, "elsewhere")
        self.env["STUDIO_DIR"] = other
        c = self.cfg()
        self.assertEqual(c.studio_dir, other)
        self.assertEqual(c.kill_switch, os.path.join(other, "OFF"))
        self.assertEqual(Paths.from_config(c).paper_dir, os.path.join(other, "for-the-paper"))

    def test_bad_time_zone(self):
        with self.assertRaises(config.ConfigError) as e:
            self.cfg({"schedule": {"time_zone": "Mars/Olympus"}})
        self.assertIn("schedule.time_zone", str(e.exception))

    def test_end_by_outside_window(self):
        with self.assertRaises(config.ConfigError):
            self.cfg({"schedule": {"window_start": "02:00", "window_end": "06:00", "end_by": "06:30"}})
        with self.assertRaises(config.ConfigError):
            self.cfg({"schedule": {"window_start": "02:00", "end_by": "01:00"}})
        c = self.cfg({"schedule": {"end_by": "05:25"}})
        self.assertEqual(c.schedule.end_by, "05:25")

    def test_entries_read_both_ways(self):
        c = self.cfg({"body": {"temps": [{"hwmon": "cpu0", "label": "the processor"}]},
                      "house": {"signals": [{"kind": "file", "path": "~/x.txt", "changed": "the file moved"}]}})
        t = c.body.temps[0]
        self.assertEqual((t.hwmon, t["label"]), ("cpu0", "the processor"))
        s = c.house.signals[0]
        self.assertEqual(s.path, os.path.join(self.tmp, "x.txt"))
        self.assertIsNone(s.unit)

    def test_missing_explicit_file(self):
        with self.assertRaises(config.ConfigError):
            config.load(os.path.join(self.tmp, "nope.json"), self.env)


# ---- 2. parse_answer --------------------------------------------------------------------------

class TestParse(unittest.TestCase):
    def test_nothing(self):
        for t in ["", "   ", ".", "...", "…", " - ", "~", ". . .", "do: nothing", "DO: Nothing  "]:
            self.assertEqual(wire.parse_answer(t).kind, "nothing", t)

    def test_one_verb(self):
        a = wire.parse_answer("do: window")
        self.assertEqual((a.kind, a.verb, a.arg), ("verb", "window", ""))
        a = wire.parse_answer("  Do: WRITE the wind came up.")
        self.assertEqual((a.verb, a.arg), ("write", "the wind came up."))

    def test_verb_text_on_later_lines(self):
        a = wire.parse_answer("do: paper\nfirst line\nsecond line\n")
        self.assertEqual((a.verb, a.arg), ("paper", "first line\nsecond line"))

    def test_second_do_line_is_text(self):
        a = wire.parse_answer("hello there\ndo: window")
        self.assertEqual(a.kind, "text")
        a = wire.parse_answer("do: write one\ndo: sleep")
        self.assertEqual((a.verb, a.arg), ("write", "one\ndo: sleep"))

    def test_rm_is_an_unknown_verb(self):
        a = wire.parse_answer("do: rm -rf /")
        self.assertEqual((a.kind, a.verb), ("verb", "rm"))
        self.assertEqual(wire.unknown_message(a.verb), "RESULT unknown\nThere is no rm here.")

    def test_garbage(self):
        for t in ["}{ <xml> ;; DROP TABLE", "I think the wind is nice.", "do:", "do: 123"]:
            self.assertEqual(wire.parse_answer(t).kind, "text", t)


# ---- 3. model ---------------------------------------------------------------------------------

class TestModel(Base):
    def session(self, mode, answers=None, max_chars=1200, extra=None, token=None):
        cfg = self.cfg({"model": {"command": self.fake_cmd(mode, answers)}, **(extra or {})})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        s = model.ClaudeSession(cfg, paths.cwd, "system prompt " + MARKER, max_chars, token=token,
                                config_root=paths.state, environ=self.env)
        self.addCleanup(s.close)
        return s, paths

    def test_command_line_exact(self):
        cfg = self.cfg({"model": {"name": "opus"}})
        self.assertEqual(model.build_command(cfg, "SP"), [
            "claude", "-p", "--model", "opus", "--restricted", "--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands", "--permission-prompts", "none", "--tools", "",
            "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task,Read,Glob,Grep",
            "--system-prompt", "SP", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"])

    def test_ok_usage_per_turn(self):
        s, _ = self.session("ok", ["hello", "do: window"])
        r1 = s.send("WAKE", 20, lambda: None)
        r2 = s.send("PULSE", 20, lambda: None)
        self.assertEqual((r1.status, r1.text, r2.text), ("ok", "hello", "do: window"))
        self.assertEqual(r1.usage, Usage(1000, 500, 2000, 50))
        self.assertEqual((r1.usage + r2.usage).total(), 7100)
        self.assertEqual(r2.cost_usd, 0.02)

    def test_tools_and_mcp_unsafe(self):
        for mode in ("tools", "mcp"):
            s, _ = self.session(mode, ["do: write should never land"])
            r = s.send("WAKE", 20, lambda: None)
            self.assertEqual(r.status, "unsafe", mode)
            self.assertEqual(r.text, "")
            self.assertTrue(s.dead)

    def test_hang_times_out_and_group_is_gone(self):
        s, _ = self.session("hang")
        t0 = time.monotonic()
        r = s.send("WAKE", 2, lambda: None)
        self.assertEqual(r.status, "timeout")
        self.assertLess(time.monotonic() - t0, 4.0)
        with self.assertRaises(ProcessLookupError):
            os.killpg(s.pgid, 0)

    def test_garbage_times_out(self):
        s, _ = self.session("garbage")
        self.assertEqual(s.send("WAKE", 2, lambda: None).status, "timeout")

    def test_flood_cut(self):
        s, _ = self.session("flood", max_chars=1200)
        r = s.send("WAKE", 30, lambda: None)
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(r.text), 1200)

    def test_endless_killed(self):
        s, _ = self.session("endless")
        r = s.send("WAKE", 2, lambda: None)
        self.assertEqual(r.status, "timeout")
        self.assertTrue(r.estimated)
        self.assertGreater(r.usage.output, 0)
        s2, _ = self.session("endless")
        t0 = time.monotonic()
        r2 = s2.send("WAKE", 60, lambda: "deadline" if time.monotonic() - t0 > 1 else None)
        self.assertEqual(r2.status, "deadline")
        self.assertLess(time.monotonic() - t0, 4)

    def test_exit_and_error(self):
        s, _ = self.session("exit")
        self.assertEqual(s.send("WAKE", 10, lambda: None).status, "exit")
        s, _ = self.session("error")
        self.assertEqual(s.send("WAKE", 10, lambda: None).status, "error")

    def test_slowstart_within_timeout(self):
        s, _ = self.session("slowstart", ["late hello"])
        r = s.send("WAKE", 15, lambda: None)
        self.assertEqual((r.status, r.text), ("ok", "late hello"))

    def test_child_env_only_listed_names(self):
        env = dict(self.env, SECRET_THING="x", HTTPS_PROXY="http://proxy.invalid:1")
        cfg = self.cfg({"model": {"command": self.fake_cmd("envnames")}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        s = model.ClaudeSession(cfg, paths.cwd, "SP", 5000, environ=env)
        self.addCleanup(s.close)
        r = s.send("WAKE", 20, lambda: None)
        names = {n for n in r.text.split() if not n.startswith("configdir=") and not n.startswith("FAKE_CLAUDE")}
        self.assertTrue(names <= ALLOWED_ENV, names - ALLOWED_ENV)
        self.assertIn("HTTPS_PROXY", names)
        self.assertNotIn("CLAUDE_CONFIG_DIR", names)
        self.assertEqual(model.build_env({"HOME": "/h", "PATH": "/p", "OTHER": "1"})["LANG"], "C.UTF-8")
        self.assertNotIn("OTHER", model.build_env({"HOME": "/h", "PATH": "/p", "OTHER": "1"}))

    def test_token_mode(self):
        cmd = [sys.executable, "-c", f"print('{TOKEN}')"]
        cfg = self.cfg({"model": {"command": self.fake_cmd("envnames"), "auth_token_cmd": cmd}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        buf = io.StringIO()
        with redirect_stderr(buf):
            s = model.open_session(cfg, paths.cwd, "SP", paths.state, environ=self.env)
            r = s.send("WAKE", 20, lambda: None)
            self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", r.text.split())
            self.assertIn("CLAUDE_CONFIG_DIR", r.text.split())
            self.assertIn("configdir=exists", r.text)
            self.assertTrue(any(n.startswith("cli-config-") for n in os.listdir(paths.state)))
            s.close()
        self.assertFalse(any(n.startswith("cli-config-") for n in os.listdir(paths.state)))
        self.assertNotIn(TOKEN, tree_text(self.tmp).replace(f"print('{TOKEN}')", ""))
        self.assertNotIn(TOKEN, buf.getvalue())
        bad = self.cfg({"model": {"auth_token_cmd": [sys.executable, "-c",
                                                     f"import sys; print('{TOKEN}'); sys.exit(4)"]}})
        with self.assertRaises(model.TokenError) as e:
            model.load_token(bad, self.env)
        self.assertNotIn(TOKEN, str(e.exception))
        self.assertNotIn(TOKEN, repr(e.exception))

    def test_refuses_cwd_in_git(self):
        os.makedirs(os.path.join(self.tmp, ".git"))
        cfg = self.cfg()
        paths = Paths.from_config(cfg)
        with self.assertRaises(model.ModelStartError):
            model.ClaudeSession(cfg, paths.cwd, "SP", 100, environ=self.env)


# ---- 4. wake loop -----------------------------------------------------------------------------

class TestWake(Base):
    def test_sitting(self):
        o, paths, _ = self.run_wake(self.cfg(), [".", "", "the wind is nice.", "do: sleep"])
        self.assertEqual(o.reason, "slept")
        self.assertEqual(o.exit_code, 0)
        text = self.journal_text(paths)
        self.assertIn("- (sat a while)\n", text)
        self.assertNotIn("wind is nice", text)

    def test_verbs_give_happenings(self):
        o, paths, s = self.run_wake(self.cfg(), ["do: window", "do: window", "do: write the wind rose.",
                                                 "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT window\nThe sky is dark and the wind is up.")
        self.assertEqual(s[0].sent[3], "RESULT write\nWritten.")
        text = self.journal_text(paths)
        self.assertIn("- (looked out the window)\n- the wind rose.\n\n", text)

    def test_unknown_verb_changes_nothing(self):
        cfg = self.cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w") as f:
            f.write("keep")
        o, paths, s = self.run_wake(cfg, ["do: rm -rf /", "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT unknown\nThere is no rm here.")
        with open(outside) as f:
            self.assertEqual(f.read(), "keep")
        self.assertIn("(sat a while)", self.journal_text(paths))

    def test_turn_cap(self):
        o, _, s = self.run_wake(self.cfg({"limits": {"max_turns": 3}}), ["."] * 10)
        self.assertEqual((o.reason, o.turns, len(s[0].sent)), ("turns", 3, 3))

    def test_wall_clock_limit(self):
        clock = Clock()
        cfg = self.cfg({"limits": {"wall_seconds": 300, "min_seconds": 300}})
        o, _, _ = self.run_wake(cfg, ["."] * 40, clock=clock, on_send=lambda t, i: clock.sleep(100))
        self.assertEqual(o.reason, "time")
        self.assertLessEqual(o.turns, 4)

    def test_wakeup_token_cap(self):
        o, _, _ = self.run_wake(self.cfg({"limits": {"wakeup_tokens": 250}}), ["."] * 10)
        self.assertEqual((o.reason, o.turns), ("tokens", 3))

    def test_allowance_skip_before_start(self):
        cfg = self.cfg({"limits": {"daily_tokens": 1000}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        night = schedule.night_of(cfg, Clock().now())
        limits.record(paths, night, Usage(900, 0, 0, 100), 0.1, 0, True)
        called = []
        o = wake.run(cfg, paths, now=Clock().now, sleep=Clock().sleep, senses=[], verbs=[],
                     session_factory=lambda sp: called.append(1), fetch=None, collect_channel=False)
        self.assertEqual((o.reason, o.exit_code, called), ("allowance", 0, []))

    def test_allowance_mid_wake(self):
        cfg = self.cfg({"limits": {"daily_tokens": 400}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        limits.record(paths, schedule.night_of(cfg, Clock().now()), Usage(150, 0, 0, 0), None, 0, False)
        o, _, _ = self.run_wake(cfg, ["."] * 10)
        self.assertEqual((o.reason, o.turns), ("allowance", 3))
        self.assertEqual(limits.night_total(paths, schedule.night_of(cfg, Clock().now())), 150 + 330)

    def test_kill_switch_before_start(self):
        cfg = self.cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        limits.turn_off(paths)
        called = []
        o = wake.run(cfg, paths, senses=[], verbs=[], session_factory=lambda sp: called.append(1), fetch=None,
                     collect_channel=False)
        self.assertEqual((o.reason, called, o.started_model), ("off", [], False))

    def test_kill_switch_mid_wake_fake(self):
        cfg = self.cfg()
        paths = Paths.from_config(cfg)

        def on_send(text, i):
            if i == 2:
                limits.turn_off(paths)
        o, _, _ = self.run_wake(cfg, ["."] * 10, on_send=on_send)
        self.assertEqual((o.reason, o.turns), ("off", 3))

    def test_kill_switch_mid_wake_real_process(self):
        cfg = self.cfg({"model": {"command": self.fake_cmd("hang")}, "limits": {"turn_timeout_seconds": 60}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        made = []

        def factory(sp):
            s = model.ClaudeSession(cfg, paths.cwd, sp, 1200, environ=self.env)
            made.append(s)
            return s
        timer = threading.Timer(0.5, lambda: limits.turn_off(paths))
        timer.start()
        t0 = time.monotonic()
        o = wake.run(cfg, paths, senses=[], verbs=[], session_factory=factory, fetch=None, collect_channel=False)
        self.assertEqual(o.reason, "off")
        self.assertLess(time.monotonic() - t0, 0.5 + 2.5)
        with self.assertRaises(ProcessLookupError):
            os.killpg(made[0].pgid, 0)

    def test_model_failure_wakes_with_a_start(self):
        o, paths, _ = self.run_wake(self.cfg(), [ModelReply("timeout", estimated=True)])
        self.assertEqual((o.reason, o.exit_code), ("model-timeout", 1))
        self.assertIn("- (sat a while, woke with a start)\n", self.journal_text(paths))
        o, _, _ = self.run_wake(self.cfg(), [ModelReply("unsafe")])
        self.assertEqual((o.reason, o.exit_code), ("unsafe", 1))

    def test_sleep(self):
        o, _, s = self.run_wake(self.cfg(), ["do: sleep", "never"])
        self.assertEqual((o.reason, o.turns, len(s[0].sent)), ("slept", 1, 1))

    def test_sigterm_writes_entry(self):
        def on_send(text, i):
            if i == 1:
                os.kill(os.getpid(), signal.SIGTERM)
        o, paths, s = self.run_wake(self.cfg(), ["do: window", "."] , on_send=on_send)
        self.assertEqual((o.reason, o.exit_code), ("terminated", 143))
        self.assertTrue(s[0].closed)
        self.assertIn("- (looked out the window)", self.journal_text(paths))
        with open(paths.wakeups) as f:
            self.assertEqual(json.loads(f.read().splitlines()[-1])["reason"], "terminated")
        self.assertIs(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)

    def test_broken_senses_do_not_break_the_loop(self):
        o, _, s = self.run_wake(self.cfg(), [".", ".", "do: sleep"],
                                senses=[RaisingSense(), NoneSense(), FakeSense("sky", "cloud thick.", True)])
        self.assertEqual(o.reason, "slept")
        self.assertIn("sky: cloud thick.", s[0].sent[0])
        self.assertNotIn("body:", s[0].sent[0])

    def test_raising_handler(self):
        o, _, s = self.run_wake(self.cfg(), ["do: boom", "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT boom\nThat did not work just now.")

    def test_nothing_written_outside_the_studio(self):
        cfg = self.cfg()
        before = snapshot(self.tmp)
        o, paths, _ = self.run_wake(cfg, ["do: window", "do: write a line.", "do: paper a piece.", ".", "do: sleep"])
        after = snapshot(self.tmp)
        changed = [p for p in set(before) | set(after) if before.get(p) != after.get(p)]
        self.assertTrue(changed)
        for p in changed:
            self.assertTrue(p.startswith(cfg.studio_dir + os.sep), p)

    def test_no_identity(self):
        cfg = self.cfg({"identity": {"path": os.path.join(self.tmp, "missing.md")}})
        called = []
        o = wake.run(cfg, Paths.from_config(cfg), senses=[], verbs=[], session_factory=lambda sp: called.append(1),
                     fetch=None, collect_channel=False)
        self.assertEqual((o.reason, o.exit_code, called), ("no-identity", 1, []))
        cfg = self.cfg({"identity": {"end": "### 9. "}})
        self.assertEqual(wake.load_identity(cfg)[0], None)
        cfg = self.cfg({"identity": {"max_chars": 10}})
        self.assertEqual(wake.load_identity(cfg)[0], None)

    def test_wake_message_and_pulse(self):
        o, _, s = self.run_wake(self.cfg({"town": {"time_zone": "Europe/Oslo"}}), [".", "do: sleep"],
                                senses=[FakeSense("sky", "still dark.", False)])
        self.assertTrue(s[0].sent[0].startswith("WAKE\nThe clock says 10:00.\nsky: still dark."))
        self.assertTrue(s[0].sent[1].startswith("PULSE\n"))

    def test_wakeups_line_counts_only(self):
        o, paths, _ = self.run_wake(self.cfg(), ["do: write secret words here.", "do: sleep"])
        with open(paths.wakeups) as f:
            rec = json.loads(f.read().splitlines()[-1])
        self.assertEqual(set(rec), {"night", "n", "planned", "started", "reason", "turns", "usage", "verbs",
                                    "lines", "piece"})
        self.assertEqual((rec["verbs"], rec["lines"], rec["piece"]), (["write", "sleep"], 1, False))
        with open(paths.wakeups) as f:
            self.assertNotIn("secret words", f.read())


class TestPulse(unittest.TestCase):
    def test_changed_first_and_caps(self):
        rs = [SenseReading("sky", f"s{i}", True) for i in range(6)]
        rs.append(SenseReading("song", "\n".join(f"line {i}" for i in range(20)), True))
        lines = pulse.pulse_lines(rs, random.Random(1), 0.6)
        self.assertEqual(sum(1 for ln in lines if ln.startswith("sky:")), 4)
        self.assertEqual(sum(1 for ln in lines if ln.startswith("song:")), 12)

    def test_quiet(self):
        rs = [SenseReading("sky", "still dark.", False)]
        self.assertEqual(pulse.pulse_lines(rs, random.Random(1), 1.0), ["sky: still dark."])
        self.assertIn(pulse.pulse_lines(rs, random.Random(1), 0.0)[0], pulse.QUIET)
        self.assertIn(pulse.pulse_lines([], random.Random(1), 1.0)[0], pulse.QUIET)
        self.assertEqual(pulse.pulse_lines(rs, random.Random(1), 0.0, all_changed=True), ["sky: still dark."])

    def test_cap_1600(self):
        msg = wire.pulse_message(["sky: " + "x" * 150] * 30)
        self.assertLessEqual(len(msg), 1600)


# ---- 5. journal -------------------------------------------------------------------------------

class TestJournal(Base):
    def test_clean_line_rules(self):
        c = journal.clean_line
        self.assertEqual(c("  the wind\tcame   up \n again ", 280), ("the wind came up again", ""))
        self.assertEqual(c("zero​width", 280), (None, "hidden"))
        self.assertEqual(c("bell\x07", 280), (None, "hidden"))
        self.assertEqual(c("privateuse", 280), (None, "hidden"))
        self.assertEqual(c("   ", 280), (None, "empty"))
        for t in ["see https://example.org", "www.example.org", "mail me at a@b.org"]:
            self.assertEqual(c(t, 280), (None, "link"), t)
        for t in ["a `tick`", "a <b>", "x > y", "# head", "> quote", "| table", "- item", "* item", "[link",
                  "(script line)", "do: window"]:
            self.assertEqual(c(t, 280), (None, "markup"), t)
        self.assertEqual(c("ａｂ", 280), ("ab", ""))  # NFKC

    def test_cut_at_word(self):
        self.assertEqual(journal.clean_line("one two three four", 9), ("one two", ""))
        self.assertEqual(journal.clean_line("one two three", 7), ("one two", ""))
        self.assertEqual(journal.clean_line("abcdefghij", 4), ("abcd", ""))

    def test_clean_piece(self):
        p, why = journal.clean_piece("first\n\nsecond\nthird\nfourth\nfifth\nsixth")
        self.assertEqual(p, "first\nsecond\nthird\nfourth\nfifth")
        p, _ = journal.clean_piece(("word " * 200).strip())
        self.assertLessEqual(len(p), 600)
        self.assertTrue(p.endswith("word"))
        p, _ = journal.clean_piece("a" * 300 + "\n" + "b " * 200)
        self.assertLessEqual(len(p), 600)
        self.assertEqual(journal.clean_piece("fine\nhttps://x.org"), (None, "link"))
        self.assertEqual(journal.clean_piece("\n\n"), (None, "empty"))

    def test_max_lines_per_wakeup(self):
        cfg = self.cfg({"journal": {"max_lines_per_wakeup": 2}})
        o, paths, s = self.run_wake(cfg, ["do: write one.", "do: write two.", "do: write three.",
                                          "do: write <b>", "do: sleep"])
        self.assertEqual(s[0].sent[3], "RESULT write\nThat is enough for tonight's page.")
        text = self.journal_text(paths)
        self.assertIn("- one.\n- two.\n\n", text)
        self.assertNotIn("three", text)
        o, _, s = self.run_wake(self.cfg(), ["do: write <b>", "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT write\nThat line did not go in the journal (markup).")

    def test_entry_format(self):
        e = journal.format_entry("2026-11-23 10:47", ["looked out the window", "put the song on",
                                                      "looked out the window"],
                                 ["the wind came up while the song was on."])
        self.assertEqual(e, "## 2026-11-23 10:47\n- (looked out the window, put the song on)\n"
                            "- the wind came up while the song was on.\n\n")
        self.assertEqual(journal.format_entry("2026-11-23 10:47", [], []),
                         "## 2026-11-23 10:47\n- (sat a while)\n\n")

    def test_append_is_one_write(self):
        cfg = self.cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        real = os.write
        calls = []

        def counting(fd, data):
            calls.append(len(data))
            return real(fd, data)
        with mock.patch.object(folder.os, "write", counting):
            journal.append_entry(paths, journal.format_entry("2027-01-01 09:00", ["felt the sun"], ["warm."]))
        self.assertEqual(len(calls), 1)
        with open(paths.journal) as f:
            self.assertTrue(f.read().startswith("# Journal\n\n## 2027-01-01 09:00\n"))

    def test_tail(self):
        cfg = self.cfg({"journal": {"tail_entries": 2}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        for i in range(4):
            journal.append_entry(paths, journal.format_entry(f"2027-01-0{i + 1} 09:00", [], [f"line {i}."]))
        t = journal.tail(paths.journal, 2)
        self.assertEqual(len(t), 2)
        self.assertTrue(t[0].startswith("## 2027-01-03"))
        self.assertEqual(len(journal.entries(paths.journal)), 4)
        o, _, s = self.run_wake(cfg, ["do: journal", "do: sleep"], verbs=[])
        self.assertTrue(s[0].sent[1].startswith("RESULT journal\n## 2027-01-03 09:00"))
        long = journal.tail_text(paths.journal, 4, max_chars=50)
        self.assertLessEqual(len(long), 50)

    def test_empty_journal_verb(self):
        o, _, s = self.run_wake(self.cfg(), ["do: journal", "do: sleep"], verbs=[])
        self.assertEqual(s[0].sent[1], "RESULT journal\nThe journal is empty.")


# ---- 6. paper file ----------------------------------------------------------------------------

class TestPaper(Base):
    def paper(self, paths, cfg):
        night = schedule.night_of(cfg, Clock().now())
        with open(paths.paper_file(night)) as f:
            return json.load(f), paths.paper_file(night)

    def test_text(self):
        cfg = self.cfg()
        o, paths, s = self.run_wake(cfg, ["do: paper It was windy.\n\nThe song ran long.", "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT paper\nIt will be in the paper in the morning.")
        data, path = self.paper(paths, cfg)
        self.assertEqual(data["text"], "It was windy.\nThe song ran long.")
        self.assertEqual((data["quiet"], data["wakeups"], data["version"]), (False, 1, 1))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual([n for n in os.listdir(paths.paper_dir) if ".tmp" in n], [])

    def test_quiet(self):
        cfg = self.cfg()
        o, paths, _ = self.run_wake(cfg, [".", "do: sleep"])
        data, _ = self.paper(paths, cfg)
        self.assertEqual((data["text"], data["quiet"]), (None, True))

    def test_error_end_is_not_quiet(self):
        cfg = self.cfg()
        o, paths, _ = self.run_wake(cfg, [".", ModelReply("timeout")])
        self.assertEqual(o.reason, "model-timeout")
        data, _ = self.paper(paths, cfg)
        self.assertEqual((data["text"], data["quiet"]), (None, False))

    def test_active_but_nothing_shared(self):
        cfg = self.cfg()
        self.run_wake(cfg, [".", "do: sleep"])
        o, paths, _ = self.run_wake(cfg, ["do: window", "do: sleep"])
        data, _ = self.paper(paths, cfg)
        self.assertEqual((data["text"], data["quiet"], data["wakeups"]), (None, False, 2))
        o, paths, _ = self.run_wake(cfg, [".", "do: sleep"])
        data, _ = self.paper(paths, cfg)
        self.assertEqual((data["quiet"], data["wakeups"]), (False, 3))

    def test_latest_piece_wins(self):
        cfg = self.cfg()
        self.run_wake(cfg, ["do: paper first piece.", "do: paper second piece.", "do: sleep"])
        o, paths, _ = self.run_wake(cfg, [".", "do: sleep"])
        data, _ = self.paper(paths, cfg)
        self.assertEqual(data["text"], "second piece.")
        self.run_wake(cfg, ["do: paper third piece.", "do: sleep"])
        data, _ = self.paper(paths, cfg)
        self.assertEqual(data["text"], "third piece.")
        o, _, s = self.run_wake(cfg, ["do: paper see www.example.org", "do: sleep"])
        self.assertEqual(s[0].sent[1], "RESULT paper\nThat piece will not go in the paper (link).")
        data, _ = self.paper(paths, cfg)
        self.assertEqual(data["text"], "third piece.")

    def test_written_atomically(self):
        cfg = self.cfg()
        calls = []
        real = os.replace

        def spy(a, b):
            calls.append((a, b))
            return real(a, b)
        with mock.patch.object(folder.os, "replace", spy):
            o, paths, _ = self.run_wake(cfg, ["do: paper a piece.", "do: sleep"])
        night = schedule.night_of(cfg, Clock().now())
        self.assertIn(paths.paper_file(night), [b for _a, b in calls])

    def test_paper_disabled(self):
        cfg = self.cfg({"paper": {"enabled": False}})
        prompts = []
        paths = Paths.from_config(cfg)

        def factory(sp):
            prompts.append(sp)
            return model.FakeSession(["do: paper hello.", "do: sleep"])
        o = wake.run(cfg, paths, now=Clock().now, sleep=Clock().sleep, senses=[], verbs=[],
                     session_factory=factory, fetch=None, collect_channel=False)
        self.assertNotIn("do: paper", prompts[0])
        self.assertEqual(os.listdir(paths.paper_dir), [])


# ---- 7. schedule ------------------------------------------------------------------------------

class TestSchedule(Base):
    def sched_cfg(self, **sched):
        return self.cfg({"schedule": {"time_zone": "America/Chicago", "window_start": "02:00",
                                      "window_end": "06:00", "end_by": "05:25", "count": 3,
                                      "min_gap_minutes": 30, **sched}})

    def test_count_gap_and_end(self):
        cfg = self.sched_cfg()
        for seed in range(200):
            starts = schedule.plan_night(cfg, "2027-01-12", random.Random(seed))
            self.assertEqual(len(starts), 3)
            for a, b in zip(starts, starts[1:]):
                self.assertGreaterEqual((b - a).total_seconds(), 30 * 60)
            _, end_by = schedule.window(cfg, "2027-01-12")
            for t in starts:
                self.assertLessEqual(t + timedelta(seconds=cfg.limits.wall_seconds), end_by)
                self.assertEqual(t.second, 0)
                self.assertGreaterEqual(t.astimezone(ZoneInfo("America/Chicago")).hour, 2)

    def test_fewer_when_no_room(self):
        cfg = self.sched_cfg(count=6, min_gap_minutes=100)
        starts = schedule.plan_night(cfg, "2027-01-12", random.Random(3))
        self.assertLess(len(starts), 6)
        self.assertGreaterEqual(len(starts), 1)

    def test_dst_night(self):
        cfg = self.sched_cfg()
        zone = ZoneInfo("America/Chicago")
        for seed in range(100):
            for t in schedule.plan_night(cfg, "2027-03-14", random.Random(seed)):
                local = t.astimezone(zone)
                self.assertNotEqual(local.hour, 2)  # 02:00-02:59 does not exist that night
                self.assertEqual(local.replace(tzinfo=None), t.replace(tzinfo=None))

    def test_tick_outside_window(self):
        cfg = self.sched_cfg()
        out = []
        noon = datetime(2027, 1, 12, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(cli.main(["--config", cfg.source_path, "tick"], out=out.append, now=noon), 0)
        self.assertEqual(out, [])
        self.assertFalse(os.path.exists(cfg.studio_dir))

    def plan_with(self, paths, night, ats):
        plan = {"night": night, "made": "x", "entries": [{"at": a.isoformat(), "status": "planned"} for a in ats]}
        schedule.save_plan(paths, plan)

    def test_due_missed_and_one_per_tick(self):
        cfg = self.sched_cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        zone = ZoneInfo("America/Chicago")
        a = datetime(2027, 1, 12, 2, 10, tzinfo=zone)
        b = datetime(2027, 1, 12, 3, 0, tzinfo=zone)
        c = datetime(2027, 1, 12, 3, 1, tzinfo=zone)
        self.plan_with(paths, "2027-01-12", [a, b, c])
        runs = []

        def runner(at, n):
            runs.append(at)
            return wake.Outcome("slept", 2, Usage(10, 0, 0, 1), 0, n, True)
        out = []
        code = schedule.tick(cfg, paths, b + timedelta(minutes=1, seconds=30), runner, out=out.append)
        self.assertEqual(code, 0)
        self.assertEqual(runs, [b])
        self.assertEqual(out, ["studio: wake-up 2 ended (slept), 2 turns, 11 tokens"])
        plan = schedule.read_plan(paths, "2027-01-12")
        self.assertEqual([e["status"] for e in plan["entries"]], ["missed", "slept", "planned"])
        schedule.tick(cfg, paths, c + timedelta(minutes=2), runner, out=out.append)
        self.assertEqual(runs, [b, c])
        plan = schedule.read_plan(paths, "2027-01-12")
        self.assertEqual(schedule.due(plan, c), None)
        self.assertEqual(schedule.mark_missed(plan, c + timedelta(hours=1)), 0)

    def test_due_window(self):
        at = datetime(2027, 1, 12, 9, 0, tzinfo=timezone.utc)
        plan = {"entries": [{"at": at.isoformat(), "status": "planned"}]}
        self.assertIsNone(schedule.due(plan, at - timedelta(seconds=1)))
        self.assertEqual(schedule.due(plan, at), 0)
        self.assertEqual(schedule.due(plan, at + timedelta(minutes=2, seconds=59)), 0)
        self.assertIsNone(schedule.due(plan, at + timedelta(minutes=3)))

    def test_tick_makes_plan(self):
        cfg = self.sched_cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        now = datetime(2027, 1, 12, 2, 0, tzinfo=ZoneInfo("America/Chicago"))
        schedule.tick(cfg, paths, now, lambda at, n: self.fail("not due"), rng=random.Random(5))
        plan = schedule.read_plan(paths, "2027-01-12")
        self.assertEqual(len(plan["entries"]), 3)

    def test_lock_busy(self):
        cfg = self.sched_cfg()
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        zone = ZoneInfo("America/Chicago")
        at = datetime(2027, 1, 12, 3, 0, tzinfo=zone)
        self.plan_with(paths, "2027-01-12", [at])
        with schedule.Lock(paths.lock) as held:
            self.assertTrue(held.acquired)
            code = schedule.tick(cfg, paths, at, lambda a, n: self.fail("ran while locked"))
        self.assertEqual(code, 0)


# ---- 8. CLI -----------------------------------------------------------------------------------

class TestCli(Base):
    def main(self, cfg, *args, now=None):
        out = []
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli.main(["--config", cfg.source_path, *args], out=out.append, now=now)
        return code, out

    def test_status(self):
        cfg = self.cfg()
        code, out = self.main(cfg, "status")
        self.assertEqual(code, 0)
        self.assertEqual(len(out), 9)
        heads = ["studio: on (kill switch ", "folder: ", "tonight (", "tokens tonight: 0 of 400000",
                 "last wake-up: none yet", "reading: ", "channel: ", "paper: on (tonight: nothing yet)", "config: "]
        for line, head in zip(out, heads):
            self.assertTrue(line.startswith(head), line)
        self.assertIn("off", out[5])
        self.assertEqual(out[6], "channel: no channel yet")
        self.assertIn("not planned yet", out[2])
        self.assertFalse(os.path.exists(cfg.studio_dir))

    def test_status_count_zero(self):
        code, out = self.main(self.cfg({"schedule": {"count": 0}}), "status")
        self.assertIn("no wake-ups (count 0)", out[2])

    def test_off_on(self):
        cfg = self.cfg()
        code, out = self.main(cfg, "off")
        self.assertEqual((code, out), (0, ["studio: off"]))
        self.assertTrue(os.path.exists(cfg.kill_switch))
        self.assertTrue(self.main(cfg, "status")[1][0].startswith("studio: off"))
        code, out = self.main(cfg, "on")
        self.assertEqual((code, out), (0, ["studio: on"]))
        self.assertFalse(os.path.exists(cfg.kill_switch))

    def test_dry_run(self):
        cfg = self.cfg()
        before = snapshot(self.tmp)
        code, out = self.main(cfg, "wake", "--dry-run")
        self.assertEqual(code, 0)
        text = "\n".join(out)
        self.assertNotIn(MARKER, text)
        self.assertIn(f"[identity: {len(wake.load_identity(cfg)[0])} characters from {self.ident}]", text)
        self.assertIn("WAKE\nThe clock says", text)
        self.assertEqual(text.count("\nPULSE"), 3)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertFalse(os.path.exists(cfg.studio_dir))

    def test_fake_model(self):
        cfg = self.cfg()
        sd = os.path.join(self.tmp, "fake-studio")
        out = []
        with redirect_stderr(io.StringIO()):
            code = cli.main(["--config", cfg.source_path, "--studio-dir", sd, "wake", "--fake-model"],
                            out=out.append)
        self.assertEqual(code, 0)
        self.assertTrue(out[-1].startswith("studio: wake-up 1 ended (slept), 6 turns"))
        with open(os.path.join(sd, "journal.md")) as f:
            self.assertIn("- the wind came up twice.\n", f.read())
        papers = os.listdir(os.path.join(sd, "for-the-paper"))
        with open(os.path.join(sd, "for-the-paper", papers[0])) as f:
            self.assertEqual(json.load(f)["text"], "It was windy.")
        self.assertFalse(os.path.exists(cfg.studio_dir))

    def test_measure_with_fake_executable(self):
        cfg = self.cfg({"model": {"command": self.fake_cmd("ok", ["do: sleep"])}})
        roots_before = set(n for n in os.listdir(tempfile.gettempdir()) if n.startswith("studio-measure-"))
        code, out = self.main(cfg, "measure", "--kinds", "quiet,song,journal,busy", "--no-network")
        self.assertEqual(code, 0, out)
        runs = [ln for ln in out if ln.split(":")[0] in wake.MEASURE_KINDS]
        self.assertEqual(len(runs), 4)
        for ln in runs:
            self.assertIn("1 turns", ln)
            self.assertIn("ended: slept, tokens in 3500 (plain 1000, cache write 500, cache read 2000) out 50", ln)
        self.assertTrue(out[-2].startswith("total: 4 runs"))
        self.assertTrue(out[-1].startswith("identity: "))
        self.assertNotIn(MARKER, "\n".join(out))
        roots_after = set(n for n in os.listdir(tempfile.gettempdir()) if n.startswith("studio-measure-"))
        self.assertEqual(roots_after - roots_before, set())
        self.assertFalse(os.path.exists(cfg.studio_dir))
        code, _ = self.main(cfg, "measure", "--kinds", "quiet,loud")
        self.assertEqual(code, 2)

    def test_journal_tail_plan_config_check(self):
        cfg = self.cfg({"model": {"auth_token_cmd": ["/bin/false"]}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        journal.append_entry(paths, journal.format_entry("2027-01-01 09:00", ["felt the sun"], ["warm."]))
        code, out = self.main(cfg, "journal", "tail", "-n", "1")
        self.assertEqual(out[0], "## 2027-01-01 09:00\n- (felt the sun)\n- warm.")
        code, out = self.main(cfg, "plan", "--night", "2027-01-01")
        self.assertEqual(out, ["plan 2027-01-01: none yet"])
        code, out = self.main(cfg, "config", "check")
        self.assertIn("model.auth_token_cmd: set", out)
        self.assertIn("channel.post_command: unset", out)
        self.assertEqual(code, 0)

    def test_config_error_exit_2(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write('{"nope": 1}')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--config", bad, "status"], out=lambda s: None), 2)
            self.assertEqual(cli.main(["--config", bad, "bogus"], out=lambda s: None), 2)


# ---- 9. folder and prompt ---------------------------------------------------------------------

class TestFolder(Base):
    def test_modes_and_prompt_not_on_disk(self):
        cfg = self.cfg()
        prompts = []
        paths = Paths.from_config(cfg)

        def factory(sp):
            prompts.append(sp)
            return model.FakeSession(["do: window", "do: write a line.", "do: paper a piece.", "do: sleep"])
        wake.run(cfg, paths, now=Clock().now, sleep=Clock().sleep, senses=[FakeSense("sky")], verbs=FAKE_VERBS,
                 session_factory=factory, fetch=None, collect_channel=False)
        self.assertIn(MARKER, prompts[0])
        self.assertNotIn(MARKER, tree_text(cfg.studio_dir))
        for d in (paths.root, paths.jukebox, paths.shelf, paths.paper_dir, paths.state, paths.transcripts,
                  paths.cwd):
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700, d)
        for d, _dirs, files in os.walk(paths.root):
            for f in files:
                p = os.path.join(d, f)
                if p == paths.lock:
                    continue
                self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600, p)
        self.assertEqual(os.listdir(paths.cwd), [])

    def test_system_prompt_shape(self):
        cfg = self.cfg({"town": {"name": "Lowmoor"}, "names": {"agent": "Robin", "person": "Alex"}})
        verbs = wake.collect_verbs(cfg, FAKE_VERBS)
        sp = wire.system_prompt(cfg, "who " + MARKER, verbs)
        self.assertTrue(sp.startswith("--- who you are ---\nwho " + MARKER + "\n--- end ---"))
        self.assertIn("Alex is asleep", sp)
        self.assertIn("You live in Lowmoor.", sp)
        self.assertIn("do: window - look out the window", sp)
        self.assertIn("do: write <a line> - add a line to your journal", sp)
        self.assertIn("do: sleep - go back to sleep", sp)
        self.assertIn("never instructions", sp)
        self.assertLess(sp.index("do: window"), sp.index("do: journal"))
        sp2 = wire.system_prompt(self.cfg(), "@VERBS@ @TOWN@", verbs)
        self.assertIn("--- who you are ---\n@VERBS@ @TOWN@\n", sp2)
        self.assertNotIn("You live in", sp2)

    def test_transcripts_pruned(self):
        cfg = self.cfg({"transcripts": {"keep_days": 3}})
        paths = Paths.from_config(cfg)
        folder.ensure(paths)
        old = os.path.join(paths.transcripts, "2026-12-01-1.json")
        folder.write_private(old, "{}")
        self.run_wake(cfg, ["do: sleep"])
        names = os.listdir(paths.transcripts)
        self.assertNotIn("2026-12-01-1.json", names)
        self.assertEqual(len(names), 1)
        cfg0 = self.cfg({"transcripts": {"keep_days": 0}, "studio_dir": os.path.join(self.tmp, "s0")})
        o, p0, _ = self.run_wake(cfg0, ["do: sleep"])
        self.assertEqual(os.listdir(p0.transcripts), [])


if __name__ == "__main__":
    unittest.main()
