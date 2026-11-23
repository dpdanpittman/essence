"""Checks that the studio's public files hold nothing personal, and that the
studio's config template, example and journal example keep their shape.

The impersonality check runs one pattern over every studio file in this
repository. The words of the pattern are stored in rot13 here, so this file
does not match its own pattern.
"""

import codecs
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _r(text):
    return codecs.decode(text, "rot13")


# The same words as the integrator's grep, one alternative each.
_WORDS = [
    r"\b" + _r("qna") + r"\b",
    _r("znohf"),
    _r("erlxwni"),
    _r("uryran"),
    _r("qraire"),
    _r("mncubq"),
    "/" + _r("ubzr") + "/",
    "19" + r"2\.1" + "68",
    _r("gnvyp") + "74" + "255",
    _r("ohega"),
    _r("rneabf"),
    _r("cvggzna"),
    "5516" + "63660",
    "-1" + "00[0-9]{6,}",
    _r("jrrxyl-wbo-gbxra"),
    _r("cc-trg"),
    _r("bc-trg"),
    _r("pnapre"),
    _r("yboeran"),
    _r("djbla"),
    _r("x10grzc"),
]
PATTERN = re.compile("|".join(_WORDS), re.IGNORECASE)

# The words the integrator checks in the added lines of the shared files.
_DIFF_WORDS = [
    r"\b" + _r("qna") + r"\b",
    _r("znohf"),
    _r("erlxwni"),
    _r("qraire"),
    "/" + _r("ubzr") + "/",
    _r("ohega"),
    _r("rneabf"),
    "5516" + "63660",
]
DIFF_PATTERN = re.compile("|".join(_DIFF_WORDS), re.IGNORECASE)


def studio_files():
    """Every public studio file the pattern must not hit."""
    out = []

    def walk(path):
        if os.path.isfile(path):
            out.append(path)
            return
        if not os.path.isdir(path):
            return
        for base, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                out.append(os.path.join(base, name))

    walk(os.path.join(ROOT, "studio"))
    tests = os.path.join(ROOT, "tests")
    for name in sorted(os.listdir(tests)):
        if name.startswith("test_studio_") and name.endswith(".py"):
            out.append(os.path.join(tests, name))
    walk(os.path.join(tests, "fake_claude_stream.py"))
    walk(os.path.join(tests, "fixtures", "studio"))
    walk(os.path.join(ROOT, "docs", "studio.md"))
    walk(os.path.join(ROOT, "templates", "studio-config.json"))
    examples = os.path.join(ROOT, "examples")
    for name in sorted(os.listdir(examples)):
        if name.startswith("studio-") and (name.endswith(".json") or name.endswith(".md")):
            out.append(os.path.join(examples, name))
    walk(os.path.join(ROOT, "site", "src", "components", "Studio.astro"))
    return out


def flatten(obj, prefix=""):
    keys = []
    for key, value in obj.items():
        name = prefix + key
        if isinstance(value, dict):
            keys.extend(flatten(value, name + "."))
        else:
            keys.append(name)
    return keys


def load_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


class ImpersonalTest(unittest.TestCase):
    def test_pattern_catches_its_words(self):
        # Guard against a pattern that matches nothing.
        self.assertTrue(PATTERN.search("seen in " + _r("Qraire") + " today"))
        self.assertTrue(PATTERN.search("/" + _r("ubzr") + "/someone"))
        self.assertFalse(PATTERN.search("Lowmoor, Robin and Alex"))
        self.assertFalse(PATTERN.search("dance and dandelions"))

    def test_docs_files_exist(self):
        for parts in (
            ("docs", "studio.md"),
            ("templates", "studio-config.json"),
            ("examples", "studio-config-example.json"),
            ("examples", "studio-journal-example.md"),
            ("site", "src", "components", "Studio.astro"),
        ):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, *parts)), "/".join(parts))

    def test_no_personal_words_in_studio_files(self):
        hits = []
        for path in studio_files():
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(lines, 1):
                if PATTERN.search(line):
                    hits.append("%s:%d" % (os.path.relpath(path, ROOT), n))
        self.assertEqual(hits, [], "personal words found (file:line only)")

    def test_added_lines_in_shared_files(self):
        try:
            res = subprocess.run(
                ["git", "-C", ROOT, "diff", "main", "--", "README.md", "AGENTS.md", "CHANGELOG.md", "site/src"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("git not available")
        if res.returncode != 0:
            self.skipTest("no main branch to compare with")
        hits = [
            line
            for line in res.stdout.splitlines()
            if line.startswith("+") and not line.startswith("+++") and DIFF_PATTERN.search(line)
        ]
        self.assertEqual(len(hits), 0, "personal words in added lines: %d" % len(hits))


class TemplateTest(unittest.TestCase):
    def test_template_holds_every_default(self):
        cfg = load_json("templates", "studio-config.json")
        self.assertEqual(cfg["version"], 1)
        self.assertIsNone(cfg["town"]["name"])
        self.assertIsNone(cfg["identity"]["path"])
        self.assertEqual(cfg["schedule"]["time_zone"], "UTC")
        self.assertEqual(cfg["town"]["time_zone"], "UTC")
        self.assertIsNone(cfg["reading"]["start_date"])
        self.assertEqual(cfg["reading"]["sources"], [])
        self.assertIsNone(cfg["channel"]["chat_id"])
        self.assertIsNone(cfg["model"]["auth_token_cmd"])
        self.assertEqual(cfg["limits"]["wall_seconds"], 300)
        self.assertEqual(cfg["limits"]["daily_tokens"], 400000)
        self.assertEqual(
            sorted(cfg["verbs"]),
            sorted(["window", "sun", "temperature", "journal", "write", "song", "read", "paper", "nothing", "sleep"]),
        )
        self.assertEqual(len(flatten(cfg)), 68)

    def test_docs_name_every_key(self):
        cfg = load_json("templates", "studio-config.json")
        with open(os.path.join(ROOT, "docs", "studio.md"), encoding="utf-8") as f:
            doc = f.read()
        missing = []
        for key in flatten(cfg):
            head, _, leaf = key.rpartition(".")
            if "`%s`" % key in doc:
                continue
            # grouped rows such as `senses.sky`, `.body`
            if head and ("`.%s`" % leaf in doc) and ("`%s." % head in doc):
                continue
            missing.append(key)
        self.assertEqual(missing, [])

    def test_example_is_keys_of_the_template(self):
        cfg = set(flatten(load_json("templates", "studio-config.json")))
        ex = load_json("examples", "studio-config-example.json")
        self.assertEqual(ex["town"]["name"], "Lowmoor")
        self.assertEqual(ex["town"]["latitude"], 61.2)
        self.assertEqual(ex["town"]["longitude"], 7.1)
        self.assertEqual(ex["town"]["time_zone"], "Europe/Oslo")
        self.assertEqual(ex["names"], {"agent": "Robin", "person": "Alex"})
        self.assertIsNone(ex["reading"]["start_date"])
        self.assertIsNone(ex["channel"]["chat_id"])
        for key in flatten(ex):
            self.assertIn(key, cfg)

    def test_engine_loads_template_and_example(self):
        try:
            from studio import config
        except Exception:
            self.skipTest("studio engine not importable")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"STUDIO_DIR": tmp, "HOME": tmp}
            for parts in (("templates", "studio-config.json"), ("examples", "studio-config-example.json")):
                cfg = config.load(os.path.join(ROOT, *parts), env)
                self.assertEqual(cfg.studio_dir, tmp)
            ex = config.load(os.path.join(ROOT, "examples", "studio-config-example.json"), env)
            self.assertEqual(ex.town.name, "Lowmoor")
            self.assertIsNotNone(ex.schedule.end_by)


class JournalExampleTest(unittest.TestCase):
    def test_entries_have_the_exact_shape(self):
        with open(os.path.join(ROOT, "examples", "studio-journal-example.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(text.startswith("# Journal\n\n"))
        entries = text[len("# Journal\n\n"):].split("\n\n")
        entries = [e for e in entries if e.strip()]
        self.assertEqual(len(entries), 3)
        for entry in entries:
            lines = entry.split("\n")
            self.assertRegex(lines[0], r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
            self.assertRegex(lines[1], r"^- \(.+\)$")
            for line in lines[2:]:
                self.assertRegex(line, r"^- [^(#>|\-*\[`<]")
        self.assertIn("- (sat a while)", text)
        self.assertTrue(text.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
