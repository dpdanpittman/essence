#!/usr/bin/env python3
"""essence-nudge: a UserPromptSubmit hook. When the conversation has grown long since the last compaction, it prints
one short reminder, which the harness puts in front of the agent with the user's next message:
update the landscapes you worked in and the sketchbook NOW, while you still hold the picture. When the sketchbook's
current month is over ESSENCE_SKETCHBOOK_WARN_KB (default 400), the reminder also says to rotate it early.

Why: a landscape can only be written by the session that built the understanding. A hook that runs at compaction
time is too late, because it cannot give the agent a turn to write.

How it measures "long": the bytes the session transcript has grown since the last compaction line in it (or since
its start). It nudges once when that passes ESSENCE_NUDGE_MB (default 6), and again every ESSENCE_NUDGE_AGAIN_MB
(default 3) after that. A compaction starts the count over.

Input: the hook JSON on stdin (uses "transcript_path"). Output: the reminder on stdout, or nothing.
State: ~/.claude/essence/nudge-state.json (how far each transcript was scanned; no conversation text).
It reads only new lines since its last run, never writes to the transcript, and always exits 0 so a failure here
can never block a prompt. Standard library only.
"""
import json, os, sys, tempfile

DIR = os.environ.get("ESSENCE_DIR") or os.path.expanduser("~/.claude/essence")
STATE = os.path.join(DIR, "nudge-state.json")
FIRST = float(os.environ.get("ESSENCE_NUDGE_MB", "6")) * 1_000_000
AGAIN = float(os.environ.get("ESSENCE_NUDGE_AGAIN_MB", "3")) * 1_000_000
WARN_KB = os.environ.get("ESSENCE_SKETCHBOOK_WARN_KB", "400")
SUMMARY = b"This session is being continued from a previous conversation"


def sketchbook_note(d=None, warn_kb=None):
    """One sentence when the sketchbook's current month is over the size mark, else ''."""
    try:
        limit = max(1, int(warn_kb or WARN_KB)) * 1024
        size = os.path.getsize(os.path.join(d or DIR, "sketchbook", "current.md"))
    except (OSError, ValueError):
        return ""
    if size <= limit:
        return ""
    return (f" The sketchbook's current month is {size // 1024} KB, over the {limit // 1024} KB mark: "
            "rotate it early (sketchbook-rotate --early).")


def scan(path, start):
    """Return (new scan offset, offset of the last compaction line seen after `start` or None)."""
    last = None
    with open(path, "rb") as f:
        f.seek(start)
        pos = start
        for raw in f:
            if not raw.endswith(b"\n"):
                break
            if SUMMARY in raw[:8000] or b"isCompactSummary" in raw[:8000]:
                try:
                    o = json.loads(raw)
                    c = (o.get("message") or {}).get("content")
                    if o.get("type") == "user" and (o.get("isCompactSummary") or (isinstance(c, str) and c.lstrip().startswith(SUMMARY.decode()))):
                        last = pos
                except Exception:
                    pass
            pos += len(raw)
    return pos, last


def decide(st, size, first=FIRST, again=AGAIN):
    """Pure. st = {"base": offset of the last compaction, "nudged": bytes-since-base at the last nudge or 0}.
    Returns (new st, bytes since base if a nudge is due else 0)."""
    st = dict(st)
    grown = size - st.get("base", 0)
    last = st.get("nudged", 0)
    due = grown >= first and (last == 0 or grown - last >= again)
    if due:
        st["nudged"] = grown
    return st, (grown if due else 0)


def main():
    try:
        path = (json.load(sys.stdin) or {}).get("transcript_path") or ""
        if not path or not os.path.isfile(path):
            return 0
        try:
            allst = json.load(open(STATE))
        except Exception:
            allst = {}
        st = allst.get(path) or {"scan": 0, "base": 0, "nudged": 0}
        size = os.path.getsize(path)
        if st.get("scan", 0) > size:                      # the file is shorter than last time: start over
            st = {"scan": 0, "base": 0, "nudged": 0}
        st["scan"], compact = scan(path, st.get("scan", 0))
        if compact is not None:                           # a compaction happened: the count starts again
            st["base"], st["nudged"] = compact, 0
        st, grown = decide(st, st["scan"])
        allst[path] = st
        allst = dict(list(allst.items())[-100:])
        os.makedirs(DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DIR)
        with os.fdopen(fd, "w") as f:
            json.dump(allst, f)
        os.replace(tmp, STATE)
        if grown:
            print(f"[Essence nudge] This conversation has grown about {grown / 1e6:.0f} MB since the last compaction, "
                  "so a compaction may be near. Before you go on: update every landscape you worked in "
                  "(portrait section 11: rewrite its open threads, add new traps and decisions with dates) and bring "
                  "the sketchbook up to date (one clock-stamped sketch per change, with note)." + sketchbook_note() +
                  " Do it in this turn, then answer the user's message. "
                  "This note is from a hook, not from the user.")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
