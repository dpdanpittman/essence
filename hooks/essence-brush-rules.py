#!/usr/bin/env python3
"""essence-brush-rules: rules that ride on a brush.

Some rules belong to an ability, not to an area of work. "Read the platform's current docs before you touch it,
they change fast" is true of every job that uses that platform's login. So the rule lives on the BRUSH (a short
"Before you use this brush" part at its top), not in each landscape. This check makes sure the rule reaches the work:
a landscape whose text involves a platform must name one of that platform's brushes on its Brushes line, and those
brushes must still carry the rule. A new landscape that forgets the brush is caught the moment it is written.

Rules: ~/.claude/essence/brush-rules.json (override with --rules or ESSENCE_BRUSH_RULES); start from
examples/brush-rules-example.json. Each rule has
    name, platform        a short id and the platform's display name
    words_any_case        words that mean the platform, matched case-insensitively
    words_exact_case      words matched with their exact case (short product names that are also ordinary words)
    brushes               brush file names (no .md); at least one must be on the landscape's Brushes line
    suggest               optional: the brush to suggest first
    rule_title, marker    the rule's heading, and the exact text every brush in 'brushes' must contain
Words match whole: a letter, digit or underscore right before or after means no match. A landscape that only
QUOTES a word still mentions it and must list the brush. Adding a platform is a JSON edit only.
A Brushes line is "- Brushes (notes): a, b (why)" or one "- Brush: a (brushes/a.md). scope" line per brush.

Usage:
    essence-brush-rules.py --all              every landscape, every rule brush; exit 0 clean, 1 problems, 2 broken rules file
    essence-brush-rules.py --file <path>      one landscape (plus the rules' own brush files existing)
    essence-brush-rules.py --hook             PostToolUse hook: tool JSON on stdin
    --essence DIR  (or ESSENCE_DIR) the essence folder; --rules FILE the rules file
It never edits anything. Standard library only; works under python3 -I.

Hook mode FAILS OPEN on purpose: this is a reminder, not a security guard. It does nothing unless the edited path
is under essence/landscapes/ or essence/brushes/ or is the rules file; any internal error prints one line on stderr
and exits 0. On a problem it prints {"decision": "block", "reason": ...}, which hands the agent what is missing and
the line to add. It always exits 0. Shell edits bypass a tool hook: run --all on a schedule as the net.
"""
import json
import os
import re
import sys

WORDCH = "A-Za-z0-9_"
TOKCH = "A-Za-z0-9_.-"   # brush names contain hyphens; a hyphenated longer name is a different brush
BRUSHES_LINE = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?Brush(?:es)?\b")   # "- Brushes (notes): a, b" or "- Brush: a (brushes/a.md)"


class RulesError(Exception):
    pass


def essence_dir(arg=None):
    return os.path.abspath(os.path.expanduser(arg or os.environ.get("ESSENCE_DIR") or "~/.claude/essence"))


def rules_path(ess, arg=None):
    return os.path.abspath(os.path.expanduser(arg or os.environ.get("ESSENCE_BRUSH_RULES") or os.path.join(ess, "brush-rules.json")))


def word_re(words, exact):
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![{WORDCH}])(?:{alts})(?![{WORDCH}])", 0 if exact else re.I)


def load_rules(path):
    """Parsed, validated rules. Raises RulesError on anything malformed (exit 2)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        raise RulesError(f"rules file {path} does not exist")
    except Exception as e:
        raise RulesError(f"rules file {path} is not valid JSON ({type(e).__name__}: {e})")
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise RulesError(f"rules file {path} needs an object with a 'rules' list")
    out = []
    for i, r in enumerate(raw["rules"]):
        where = f"rule #{i + 1}"
        if not isinstance(r, dict):
            raise RulesError(f"{where} is not an object")
        name = r.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RulesError(f"{where} has no name")
        where = f"rule {name}"
        anyc, exact = r.get("words_any_case", []), r.get("words_exact_case", [])
        for k, v in (("words_any_case", anyc), ("words_exact_case", exact)):
            if not isinstance(v, list) or not all(isinstance(w, str) and w.strip() for w in v):
                raise RulesError(f"{where}: {k} must be a list of non-empty strings")
        if not anyc and not exact:
            raise RulesError(f"{where} has no words")
        brushes = r.get("brushes")
        if not isinstance(brushes, list) or not brushes or not all(isinstance(b, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", b) for b in brushes):
            raise RulesError(f"{where}: brushes must be a non-empty list of brush file names")
        marker = r.get("marker")
        if not isinstance(marker, str) or not marker.strip():
            raise RulesError(f"{where} has no marker")
        brushes = [b[:-3] if b.endswith(".md") else b for b in brushes]
        suggest = r.get("suggest") if r.get("suggest") in brushes else brushes[0]
        out.append({
            "name": name, "platform": r.get("platform") or name, "brushes": brushes, "suggest": suggest,
            "marker": marker, "title": r.get("rule_title") or "Before you use this brush",
            "res": ([word_re(anyc, False)] if anyc else []) + ([word_re(exact, True)] if exact else []),
        })
    return out


def first_mention(text, rule):
    """(line number, line) of the first line that mentions the platform, or None."""
    for n, line in enumerate(text.splitlines(), 1):
        if any(rx.search(line) for rx in rule["res"]):
            return n, line
    return None


def brushes_lines(text):
    """The text after the colon of every Brushes line ('- Brushes (notes): a, b (why)') or Brush line."""
    out = []
    for line in text.splitlines():
        if not BRUSHES_LINE.match(line):
            continue
        rest = BRUSHES_LINE.sub("", line, count=1).lstrip("*")
        if rest.lstrip().startswith("("):           # skip a parenthetical before the colon
            depth = 0
            for i, c in enumerate(rest):
                depth += (c == "(") - (c == ")")
                if depth == 0 and c == ")":
                    rest = rest[i + 1:]
                    break
        rest = rest.lstrip()
        if rest.startswith(":"):
            out.append(rest[1:])
    return out


def lists_brush(blines, brush):
    rx = re.compile(rf"(?<![{TOKCH}]){re.escape(brush)}(?:\.md)?(?![A-Za-z0-9_-])")
    return any(rx.search(b) for b in blines)


def short(line, n=80):
    line = " ".join(line.split())
    return line if len(line) <= n else line[: n - 3] + "..."


def check_landscape(path, rules):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return [f"landscape {os.path.basename(path)} cannot be read ({e.strerror})"]
    name = os.path.basename(path)[:-3] if path.endswith(".md") else os.path.basename(path)
    blines = brushes_lines(text)
    problems = []
    if not blines:
        problems.append(f"landscape {name} has no Brushes line"
                        f" (add: - Brushes (~/.claude/essence/brushes/): <brush names>)")
    for r in rules:
        hit = first_mention(text, r)
        if not hit or any(lists_brush(blines, b) for b in r["brushes"]):
            continue
        others = [b for b in r["brushes"] if b != r["suggest"]]
        fix = (f"add '{r['suggest']}' to its Brushes line" if blines
               else f"add the line: - Brushes (~/.claude/essence/brushes/): {r['suggest']}")
        problems.append(f"landscape {name} mentions {r['platform']} (line {hit[0]}: '{short(hit[1])}') but its Brushes "
                        f"line lists no {r['platform']} brush; {fix}" + (f" (or one of: {', '.join(others)})" if others else ""))
    return problems


def check_rule_brushes(ess, rules, markers=True):
    problems, bdir = [], os.path.join(ess, "brushes")
    for r in rules:
        for b in r["brushes"]:
            p = os.path.join(bdir, b + ".md")
            if not os.path.isfile(p):
                problems.append(f"rule {r['name']} names a brush file that does not exist: brushes/{b}.md")
                continue
            if markers:
                with open(p, encoding="utf-8", errors="replace") as f:
                    if r["marker"] not in f.read():
                        problems.append(f"brush {b} lost its '{r['title']}' rule (put back the text: '{r['marker']}')")
    return problems


def landscapes(ess):
    d = os.path.join(ess, "landscapes")
    try:
        return sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".md"))
    except OSError:
        return []


def run_all(ess, rules):
    problems = check_rule_brushes(ess, rules)
    for p in landscapes(ess):
        problems += check_landscape(p, rules)
    return problems


def run_file(ess, rules, path):
    return check_rule_brushes(ess, rules, markers=False) + check_landscape(path, rules)


# ---------------- hook ----------------
def hook(stdin, ess, rpath):
    """Never raises, always returns 0. Prints a block reason only when a check finds a problem."""
    try:
        inp = json.loads(stdin or "{}")
        ti = inp.get("tool_input") if isinstance(inp, dict) else None
        fp = ti.get("file_path") if isinstance(ti, dict) else None
        if not isinstance(fp, str) or not fp:
            return 0
        if ("landscapes" not in fp and "brushes" not in fp
                and os.path.basename(fp) != os.path.basename(rpath)):   # fast path: no file system work
            return 0
        real = os.path.realpath(os.path.expanduser(fp))
        ess_r = os.path.realpath(ess)
        land, brush = os.path.join(ess_r, "landscapes") + os.sep, os.path.join(ess_r, "brushes") + os.sep
        is_rules = real == os.path.realpath(rpath)
        is_land = real.startswith(land) and real.endswith(".md")
        is_brush = real.startswith(brush) and real.endswith(".md")
        if not (is_rules or is_land or is_brush):
            return 0
        try:
            rules = load_rules(rpath)
        except RulesError as e:
            if is_rules:
                _say([f"the brush rules file is broken: {e}"])
            return 0
        problems = run_file(ess_r, rules, real) if is_land else run_all(ess_r, rules)
        if problems:
            _say(problems)
    except Exception as e:  # fail open: a reminder must never get in the way of an edit
        sys.stderr.write(f"essence-brush-rules: skipped ({type(e).__name__})\n")
    return 0


def _say(problems):
    reason = ("[Essence brush rules] " + "; ".join(problems) +
              ". Fix it with a small exact edit (rules: ~/.claude/essence/brush-rules.json).")
    print(json.dumps({"decision": "block", "reason": reason}))


def main(argv):
    def opt(name):
        if name in argv:
            i = argv.index(name)
            if i + 1 >= len(argv):
                sys.stderr.write(f"{name} needs a value\n")
                sys.exit(2)
            return argv[i + 1]
        return None

    ess = essence_dir(opt("--essence"))
    rpath = rules_path(ess, opt("--rules"))
    if "--hook" in argv:
        try:
            data = sys.stdin.read()
        except Exception:
            data = ""
        return hook(data, ess, rpath)
    target = opt("--file")
    if "--all" not in argv and not target:
        sys.stderr.write("usage: essence-brush-rules.py --all | --file <landscape.md> | --hook  [--essence DIR] [--rules FILE]\n")
        return 2
    try:
        rules = load_rules(rpath)
    except RulesError as e:
        print(f"broken rules file: {e}")
        return 2
    problems = run_all(ess, rules) if "--all" in argv else run_file(ess, rules, os.path.abspath(target))
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
