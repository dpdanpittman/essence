"""Offline tests for the sketchbook: scripts/sketchbook-rotate, scripts/note, the hook lines and the installer.
Temporary folders only. Run from the repository root:  python3 -m unittest discover -s tests -v
"""
import datetime
import fcntl
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
HOOKS = os.path.join(ROOT, "hooks")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


rot = load("sketchbook_rotate", os.path.join(SCRIPTS, "sketchbook-rotate"))
TZ = rot.zoneinfo.ZoneInfo("Europe/Berlin")


def read(path, binary=False):
    with open(path, "rb" if binary else "r") as f:
        return f.read()


def at(s):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)


JAN = """# Sketchbook 2027-01

## Sketches

- 2027-01-10 09:00 CET IN FLIGHT (current):
  W. an old question
- 2027-01-10 10:00 CET WORK LIST (current):
  1. [P1] old list
## PERSONAL OPEN LIST, written 2027-01-12 (invented)
MINE: (1) sort the shed.
- 2027-01-12 16:25 CET answers on the list
- 2027-01-20 08:00 CET OPEN LIST CORRECTION: not a list, never carried
- 2027-01-29 16:40 CET WORK LIST (current; replaces the 2027-01-10 list):
  1. [P1] Oven repair: booked.
  2. [P2] Sewing unit plan: waits on Max.
- 2027-01-31 18:00 CET a plain sketch that names IN FLIGHT and WORK LIST in prose
- 2027-01-31 21:10 CET IN FLIGHT (current):
  W. Sewing unit plan: read the draft
  R. 20:00 Pattern cards printing
- 2027-01-31 22:00 CET last sketch of January
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "sketchbook")
        self.notes = os.path.join(self.tmp.name, "notes")
        os.makedirs(self.dir)
        os.makedirs(self.notes)
        self.jan = os.path.join(self.dir, "2027-01.md")
        with open(self.jan, "w") as f:
            f.write(JAN)
        os.symlink("2027-01.md", os.path.join(self.dir, "current.md"))
        self.out = []

    def tearDown(self):
        self.tmp.cleanup()

    def rotate(self, now, **kw):
        return rot.rotate(self.dir, at(now), say=self.out.append, **kw)

    def snapshot(self):
        snap = {}
        for root in (self.dir, self.notes):
            for n in sorted(os.listdir(root)):
                p = os.path.join(root, n)
                snap[p] = ("link", os.readlink(p)) if os.path.islink(p) else ("file", read(p, True))
        return snap

    def current(self):
        return os.readlink(os.path.join(self.dir, "current.md"))


class RotateTest(Base):
    def test_month_change(self):
        self.assertEqual(self.rotate("2027-02-01 00:05"), "rotated")
        self.assertEqual(self.current(), "2027-02.md")

    def test_carried_blocks(self):
        self.rotate("2027-02-01 00:05")
        text = read(os.path.join(self.dir, "2027-02.md"))
        self.assertTrue(text.startswith("# Sketchbook 2027-02\n\n## OPEN ITEMS (carried from 2027-01)\n"))
        self.assertIn("- 2027-02-01 00:05 CET WORK LIST (carried from 2027-01-29 16:40 CET in 2027-01.md) "
                      "(current; replaces the 2027-01-10 list):\n  1. [P1] Oven repair: booked.", text)
        self.assertIn("- 2027-02-01 00:05 CET IN FLIGHT (carried from 2027-01-31 21:10 CET in 2027-01.md) "
                      "(current):\n  W. Sewing unit plan: read the draft\n  R. 20:00 Pattern cards printing\n", text)
        for gone in ("old list", "old question", "CORRECTION", "plain sketch", "sort the shed", "last sketch"):
            self.assertNotIn(gone, text)
        self.assertIn("## Sketches", text)

    def test_scope_all_carries_personal_lists(self):
        self.rotate("2027-02-01 00:05", scope="all")
        text = read(os.path.join(self.dir, "2027-02.md"))
        self.assertIn("## PERSONAL OPEN LIST (carried at 2027-02-01 00:05 CET from 2027-01.md), written", text)
        self.assertIn("MINE: (1) sort the shed.", text)
        self.assertNotIn("answers on the list", text)

    def test_stale_in_flight_keeps_its_stamp(self):
        with open(self.jan, "w") as f:
            f.write(JAN.replace("2027-01-31 21:10 CET IN FLIGHT", "2027-01-29 21:10 CET IN FLIGHT"))
        self.rotate("2027-02-01 00:05")
        self.assertIn("- 2027-01-29 21:10 CET IN FLIGHT (carried from 2027-01.md, stale) (current):",
                      read(os.path.join(self.dir, "2027-02.md")))

    def test_idempotent(self):
        self.rotate("2027-02-01 00:05")
        snap = self.snapshot()
        self.assertEqual(self.rotate("2027-02-01 00:06"), "nothing")
        self.assertEqual(self.rotate("2027-02-20 00:05"), "nothing")
        self.assertEqual(snap, self.snapshot())

    def test_old_month_untouched(self):
        before, mtime = read(self.jan, True), os.stat(self.jan).st_mtime_ns
        self.rotate("2027-02-01 00:05")
        self.rotate("2027-03-01 00:05")
        self.assertEqual(read(self.jan, True), before)
        self.assertEqual(os.stat(self.jan).st_mtime_ns, mtime)
        self.assertEqual(self.current(), "2027-03.md")
        self.assertIn("Oven repair: booked.", read(os.path.join(self.dir, "2027-03.md")))

    def test_dry_run_writes_nothing(self):
        snap = self.snapshot()
        self.assertEqual(self.rotate("2027-02-01 00:05", dry=True,
                                     compat=os.path.join(self.notes, "notes-*.md")), "would rotate")
        self.assertEqual(snap, self.snapshot())
        self.assertFalse(os.path.exists(os.path.join(self.dir, ".lock")))

    def test_compat_link(self):
        pattern = os.path.join(self.notes, "notes-*.md")
        os.symlink(self.jan, os.path.join(self.notes, "notes-2027-01-05.md"))
        self.rotate("2027-01-20 00:05", compat=pattern)          # January already has a link: none added
        self.assertEqual(sorted(os.listdir(self.notes)), ["notes-2027-01-05.md"])
        self.rotate("2027-02-01 00:05", compat=pattern)
        link = os.path.join(self.notes, "notes-2027-02-01.md")
        self.assertEqual(os.path.realpath(link), os.path.realpath(os.path.join(self.dir, "2027-02.md")))
        self.assertEqual(os.readlink(os.path.join(self.notes, "notes-2027-01-05.md")), self.jan)
        os.unlink(link)                                          # a run that stopped before the link
        self.rotate("2027-02-02 00:05", compat=pattern)
        self.assertTrue(os.path.islink(link))

    def test_compat_link_name_taken_is_refused(self):
        with open(os.path.join(self.notes, "notes-2027-02-01.md"), "w") as f:
            f.write("someone else\n")
        with self.assertRaises(rot.Refused):
            self.rotate("2027-02-01 00:05", compat=os.path.join(self.notes, "notes-*.md"))

    def test_finishes_a_stopped_run(self):
        with open(os.path.join(self.dir, "2027-02.md"), "w") as f:
            f.write("already written\n")
        self.assertEqual(self.rotate("2027-02-01 00:10"), "repointed")
        self.assertEqual(read(os.path.join(self.dir, "2027-02.md")), "already written\n")
        self.assertEqual(self.current(), "2027-02.md")

    def test_late_lines(self):
        real = rot._repoint

        def repoint(dir_, name):
            with open(self.jan, "a") as f:
                f.write("- 2027-02-01 00:05 CET late line\n")
            real(dir_, name)

        with mock.patch.object(rot, "_repoint", repoint):
            self.rotate("2027-02-01 00:05")
        feb = read(os.path.join(self.dir, "2027-02.md"))
        self.assertTrue(feb.endswith("- 2027-02-01 00:05 CET late line\n"))
        self.assertIn("LATE LINES", feb)
        self.assertIn("late line", read(self.jan))

    def test_early(self):
        self.assertEqual(self.rotate("2027-01-20 10:00", early=True), "rotated")
        self.assertEqual(self.current(), "2027-01-20.md")
        self.assertEqual(self.rotate("2027-01-21 00:05"), "nothing")
        self.rotate("2027-02-01 00:05")
        self.assertIn("carried from 2027-01-20", read(os.path.join(self.dir, "2027-02.md")))

    def test_busy_lock_and_refusal(self):
        fd = os.open(os.path.join(self.dir, ".lock"), os.O_WRONLY | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        env = {"ESSENCE_TZ": "Europe/Berlin"}
        try:
            with mock.patch.object(rot, "LOCK_WAIT_S", 0.3), mock.patch.dict(os.environ, env), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(rot.main(["--now", "2027-02-01 00:05", "--dir", self.dir]), 3)
        finally:
            os.close(fd)
        self.assertEqual(self.current(), "2027-01.md")
        os.unlink(os.path.join(self.dir, "current.md"))
        with mock.patch.dict(os.environ, env), redirect_stderr(io.StringIO()):
            self.assertEqual(rot.main(["--now", "2027-02-01 00:05", "--dir", self.dir]), 2)

    def test_init(self):
        d = os.path.join(self.tmp.name, "fresh", "sketchbook")
        self.assertEqual(rot.init(d, at("2027-01-05 09:00")), "made")
        self.assertEqual(os.readlink(os.path.join(d, "current.md")), "2027-01.md")
        self.assertIn("- 2027-01-05 09:00 CET Sketchbook started.", read(os.path.join(d, "2027-01.md")))
        self.assertEqual(rot.init(d, at("2027-02-05 09:00")), "kept")
        self.assertEqual(os.readlink(os.path.join(d, "current.md")), "2027-01.md")

    def test_size_mark(self):
        warn = os.path.join(self.dir, ".size-warning")
        self.assertIsNone(rot.size_check(self.dir, False, limit=1024))
        with open(self.jan, "a") as f:
            f.write("x" * 2048)
        line = rot.size_check(self.dir, True, limit=1024)
        self.assertIn("over the 1 KB mark", line)
        self.assertFalse(os.path.exists(warn))
        rot.size_check(self.dir, False, limit=1024)
        self.assertEqual(read(warn), line + "\n")
        self.rotate("2027-02-01 00:05")
        self.assertIsNone(rot.size_check(self.dir, False, limit=4096))
        self.assertFalse(os.path.exists(warn))

    def test_the_example_and_template_parse(self):
        lines = read(os.path.join(ROOT, "examples", "sketchbook-example.md")).splitlines()
        kinds = [b["kind"] for b in rot.newest(lines)]
        self.assertEqual(sorted(kinds), ["in-flight", "work-list"])
        tlines = read(os.path.join(ROOT, "templates", "sketchbook-month.md")).splitlines()
        self.assertTrue(tlines[0].startswith("# Sketchbook "))
        self.assertIn("## OPEN ITEMS (carried from YYYY-MM)", tlines)


class NoteTest(Base):
    def note(self, *args, tz="Europe/Berlin"):
        env = dict(os.environ, HOME=self.tmp.name, ESSENCE_DIR=self.tmp.name, ESSENCE_TZ=tz)
        return subprocess.run(["bash", os.path.join(SCRIPTS, "note"), *args], capture_output=True, text=True,
                              env=env)

    def test_appends_a_clock_stamped_line(self):
        self.rotate("2027-02-01 00:05")
        r = self.note("the oven", "man came")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("to 2027-02.md", r.stdout)
        self.assertRegex(read(os.path.join(self.dir, "2027-02.md")),
                         r"\n- \d{4}-\d{2}-\d{2} \d{2}:\d{2} CES?T the oven man came\n$")
        self.assertNotIn("oven man came", read(self.jan))

    def test_refuses_empty_and_missing(self):
        self.assertEqual(self.note("  ").returncode, 1)
        os.unlink(os.path.join(self.dir, "current.md"))
        self.assertEqual(self.note("x").returncode, 1)

    def test_waits_for_the_lock(self):
        fd = os.open(os.path.join(self.dir, ".lock"), os.O_WRONLY | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        env = dict(os.environ, HOME=self.tmp.name, ESSENCE_DIR=self.tmp.name)
        try:
            p = subprocess.Popen(["bash", os.path.join(SCRIPTS, "note"), "after the lock"], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            with self.assertRaises(subprocess.TimeoutExpired):
                p.wait(timeout=1)
            self.assertNotIn("after the lock", read(self.jan))
        finally:
            os.close(fd)
        p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0)
        self.assertIn("after the lock", read(self.jan))


class HookTest(Base):
    def test_session_start_names_the_sketchbook(self):
        ess = self.tmp.name
        with open(os.path.join(ROOT, "templates", "portrait.md")) as src, \
                open(os.path.join(ess, "portrait.md"), "w") as dst:
            dst.write(src.read())
        env = dict(os.environ, HOME=self.tmp.name, ESSENCE_DIR=ess)
        out = subprocess.run(["bash", os.path.join(HOOKS, "session-start-verify.sh")], env=env,
                             capture_output=True, text=True).stdout
        self.assertIn("Sketchbook", out)
        self.assertIn("Scope: work only; never a secret.", out)
        env["ESSENCE_SKETCHBOOK_SCOPE"] = "all"
        out = subprocess.run(["bash", os.path.join(HOOKS, "session-start-verify.sh")], env=env,
                             capture_output=True, text=True).stdout
        self.assertIn("Scope: work and personal", out)
        os.unlink(os.path.join(self.dir, "current.md"))
        out = subprocess.run(["bash", os.path.join(HOOKS, "session-start-verify.sh")], env=env,
                             capture_output=True, text=True).stdout
        self.assertNotIn("Sketchbook", out)

    def test_nudge_size_sentence(self):
        nudge = load("essence_nudge_sk", os.path.join(HOOKS, "essence-nudge.py"))
        self.assertEqual(nudge.sketchbook_note(self.tmp.name, "400"), "")
        with open(self.jan, "a") as f:
            f.write("x" * 3000)
        self.assertIn("over the 2 KB mark", nudge.sketchbook_note(self.tmp.name, "2"))
        self.assertEqual(nudge.sketchbook_note(os.path.join(self.tmp.name, "nowhere"), "2"), "")


class InstallTest(unittest.TestCase):
    def test_install_starts_the_sketchbook_and_sets_the_scope(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home)
            env.pop("CLAUDE_CONFIG_DIR", None)
            r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), "--tz", "Europe/Berlin",
                                "--sketchbook-scope", "all"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            sk = os.path.join(home, ".claude", "essence", "sketchbook")
            self.assertTrue(os.path.islink(os.path.join(sk, "current.md")))
            self.assertEqual(oct(os.stat(sk).st_mode & 0o777), "0o700")
            for f in ("note", "sketchbook-rotate"):
                self.assertTrue(os.access(os.path.join(home, ".claude", "scripts", f), os.X_OK))
            with open(os.path.join(home, ".claude", "settings.json")) as f:
                self.assertEqual(json.load(f)["env"]["ESSENCE_SKETCHBOOK_SCOPE"], "all")
            before = os.readlink(os.path.join(sk, "current.md"))
            r = subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(os.readlink(os.path.join(sk, "current.md")), before)
            r = subprocess.run(["bash", os.path.join(ROOT, "install.sh"), "--sketchbook-scope", "some"], env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)


class ImpersonalTest(unittest.TestCase):
    def test_sketchbook_files_hold_nothing_personal(self):
        from test_studio_public import PATTERN
        files = [os.path.join(ROOT, *p) for p in (
            ("docs", "sketchbook.md"), ("templates", "sketchbook-month.md"), ("examples", "sketchbook-example.md"),
            ("scripts", "note"), ("scripts", "sketchbook-rotate"), ("tests", "test_sketchbook.py"),
            ("site", "src", "components", "Sketchbook.astro"))]
        hits = []
        for path in files:
            self.assertTrue(os.path.isfile(path), path)
            for n, line in enumerate(read(path).splitlines(), 1):
                if PATTERN.search(line) or chr(0x2014) in line:
                    hits.append("%s:%d" % (os.path.relpath(path, ROOT), n))
        self.assertEqual(hits, [], "personal words or em dashes (file:line only)")


if __name__ == "__main__":
    unittest.main()
