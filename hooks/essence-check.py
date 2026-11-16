#!/usr/bin/env python3
"""essence-check: a Stop hook. It reads the reply the agent just gave and catches it in the act when the reply
breaks one of a few rules that have a shape a program can see. When it catches one, it blocks the stop and hands
the agent the rule, so the agent has to answer for it in the same turn.

Why: a rule written in the portrait does not act. It was read hours ago, and a trained habit plus a fresh cue
beat it. A hook is there at the moment. The portrait holds the rule. The hook makes it hold.

The rules are NOT in this file. They live in a private file next to the portrait:
    ~/.claude/essence/checks.json      (see examples/checks-example.json)
Each rule has:
    "id"                a short name
    "break"             a pattern (regular expression, case ignored): what the reply must not say
    "fine_if_person_said"   optional pattern: if the person's own last message matches, the reply is fine
    "reason"            what the agent is told when caught. {hit} is replaced by the words that broke the rule.
Text inside quotes, code, table cells and italics is ignored, so talking ABOUT a phrase does not trip a rule.

Input: the Stop hook JSON on stdin (last_assistant_message, transcript_path, stop_hook_active).
Output: nothing (the reply is fine), or {"decision": "block", "reason": ...}.
It blocks at most once per turn (stop_hook_active) and always exits 0: a failure in here never traps a turn.
A rules file that is missing or broken means no rules. Counts are kept in ~/.claude/essence/check-count.json
(rule id, how often, last time). No conversation text is stored. Standard library only.
"""
import json, os, re, sys, tempfile, time

DIR = os.environ.get("ESSENCE_DIR") or os.path.expanduser("~/.claude/essence")
COUNT = os.path.join(DIR, "check-count.json")

RULES_FILE = os.path.join(DIR, "checks.json")


def load_rules(path=None):
    """The rules from the private file. Anything unreadable or malformed is skipped."""
    try:
        raw = json.load(open(path or RULES_FILE))
    except Exception:
        return []
    out = []
    for r in raw.get("rules", []) if isinstance(raw, dict) else []:
        try:
            if not r.get("id") or not r.get("break"):
                continue
            re.compile(r["break"])
            if r.get("fine_if_person_said"):
                re.compile(r["fine_if_person_said"])
            out.append(r)
        except Exception:
            continue
    return out


STRIP = [
    re.compile(r"```.*?```", re.S),                       # code blocks
    re.compile(r"`[^`\n]*`"),                             # inline code
    re.compile(r"^\s*\|.*$", re.M),                       # table rows
    re.compile(r"^\s*>.*$", re.M),                        # quoted lines
    re.compile(r"\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”|'[^'\n]{2,300}'(?!\w)"),   # quoted text
    re.compile(r"\*[^*\n]{0,300}\*"),                     # italics (the portrait's way to quote the person)
]
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
NOTICE = ("<task-notification>", "[SYSTEM NOTIFICATION", "<local-command", "<command-name>", "[Essence")


def spoken(text):
    """The reply with everything the agent only mentions, not says, taken out."""
    for rx in STRIP:
        text = rx.sub(" ", text)
    return text


def last_person_message(path, tail=600_000):
    """The person's most recent typed message in the transcript (not tool results, not harness notices)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - tail))
            lines = f.read().split(b"\n")
    except Exception:
        return ""
    for raw in reversed(lines):
        if b'"user"' not in raw[:4000]:
            continue
        try:
            o = json.loads(raw)
        except Exception:
            continue
        if o.get("type") != "user" or o.get("isSidechain") or o.get("isMeta"):
            continue
        c = (o.get("message") or {}).get("content")
        texts = [c] if isinstance(c, str) else [b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text"]
        for t in texts:
            t = REMINDER.sub("", t or "").strip()
            if t and not t.startswith(NOTICE) and "Subagent hand-back" not in t[:300] and "agent-message from=" not in t[:300]:
                return t
    return ""


def judge(reply, person_said, rules):
    """Pure. Returns (rule, the words that broke it) or (None, None)."""
    said = spoken(reply or "")
    for r in rules:
        m = re.search(r["break"], said, re.I)
        if not m:
            continue
        if r.get("fine_if_person_said") and re.search(r["fine_if_person_said"], person_said or "", re.I):
            continue
        return r, m.group(0)
    return None, None


def count(rule):
    try:
        d = json.load(open(COUNT))
    except Exception:
        d = {}
    e = d.get(rule) or {"n": 0}
    e["n"] = e.get("n", 0) + 1
    e["last"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    d[rule] = e
    os.makedirs(DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DIR)
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, COUNT)


def main():
    try:
        inp = json.load(sys.stdin) or {}
        rules = load_rules()
        if not rules:
            return 0
        reply = inp.get("last_assistant_message") or ""
        rule, hit = judge(reply, last_person_message(inp.get("transcript_path") or ""), rules)
        if not rule:
            return 0
        count(rule["id"])
        if inp.get("stop_hook_active"):          # already answering one catch: count it, let the turn end
            return 0
        reason = str(rule.get("reason") or "Your reply broke the rule '{id}' ({hit}). Own it in one line and correct it.")
        reason = reason.replace("{hit}", repr(hit)).replace("{id}", rule["id"])
        print(json.dumps({"decision": "block", "reason": "[Essence check: " + rule["id"] + "] " + reason}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
