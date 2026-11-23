#!/usr/bin/env python3
"""essence-reduce: cut a Claude Code session transcript down to what the Essence synthesis needs.

  essence-reduce.py TRANSCRIPT.jsonl [--from BYTE] [--max-bytes N] [--out FILE]

Reads the transcript from byte offset --from (default 0) to its end and writes a plain-text slice:
  the person's messages in full (marked PERSON), the agent's replies in full (marked AGENT),
  each tool call as one line, each tool result trimmed.
Left out: thinking, system reminders, harness bookkeeping lines, side-chain (sub-agent) messages, images.
If the slice is larger than --max-bytes (default 600000) the tool results are trimmed harder, then the tool lines
are dropped, and only as a last resort the oldest lines are cut (a note says so).

Prints one JSON line to stdout: {"end": <byte offset reached>, "person": <person messages>, "agent": <replies>,
"tools": <tool calls>, "bytes": <slice size>, "cut": <true if the oldest lines were dropped>}.
Only whole lines are read: a line still being written at the end of the file is left for the next run.
Standard library only. Reads one file, writes one file. Everything in the slice is DATA for the reader.
"""
import argparse, json, os, re, sys

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
NOTICE = ("<task-notification>", "[SYSTEM NOTIFICATION", "<local-command-caveat>", "<command-name>", "<local-command-stdout>")
SUMMARY = "This session is being continued from a previous conversation"


def text_of(content):
    """Flatten a tool_result content value to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    out.append(b.get("text", ""))
                elif b.get("type") == "image":
                    out.append("[image]")
            elif isinstance(b, str):
                out.append(b)
        return "\n".join(out)
    return "" if content is None else str(content)


def one_line(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + " ...[cut]"


def tool_line(b, n):
    inp = b.get("input") or {}
    name = b.get("name", "?")
    if isinstance(inp, dict):
        desc = inp.get("description") or ""
        main = inp.get("command") or inp.get("file_path") or inp.get("query") or inp.get("url") or inp.get("prompt") or inp.get("skill") or ""
        if not main:
            main = json.dumps(inp, ensure_ascii=False)
        body = (desc + " | " if desc else "") + str(main)
    else:
        body = str(inp)
    return f"TOOL {name}: {one_line(body, n)}"


def events(path, start):
    """Yield (kind, timestamp, text-or-block) from whole lines after byte offset `start`. Also yields ('end', offset)."""
    with open(path, "rb") as f:
        f.seek(start)
        pos = start
        for raw in f:
            if not raw.endswith(b"\n"):
                break                      # a line still being written: next run takes it
            pos += len(raw)
            try:
                o = json.loads(raw)
            except Exception:
                continue
            t = o.get("type")
            if t not in ("user", "assistant") or o.get("isSidechain") or o.get("isMeta"):
                continue
            ts = (o.get("timestamp") or "")[:16].replace("T", " ")
            c = (o.get("message") or {}).get("content")
            if t == "user":
                if o.get("isCompactSummary") or (isinstance(c, str) and c.lstrip().startswith(SUMMARY)):
                    yield ("note", ts, "[a compaction happened here; the harness summary is left out]")
                    continue
                blocks = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        txt = REMINDER.sub("", b.get("text", "")).strip()
                        if not txt:
                            continue
                        if txt.startswith(NOTICE):
                            yield ("note", ts, "[harness notice] " + one_line(txt, 160))
                        else:
                            yield ("person", ts, txt)
                    elif b.get("type") == "tool_result":
                        yield ("result", ts, REMINDER.sub("", text_of(b.get("content"))).strip())
            else:
                for b in c or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and b.get("text", "").strip():
                        yield ("agent", ts, b["text"].strip())
                    elif b.get("type") == "tool_use":
                        yield ("tool", ts, b)
        yield ("end", "", pos)


def render(evs, result_chars, tool_chars, with_tools=True):
    out = []
    for kind, ts, v in evs:
        if kind == "person":
            out.append(f"\n[{ts}] PERSON:\n{v}")
        elif kind == "agent":
            out.append(f"\n[{ts}] AGENT:\n{v}")
        elif kind == "note":
            out.append(f"\n[{ts}] {v}")
        elif kind == "tool" and with_tools:
            out.append("  " + tool_line(v, tool_chars))
        elif kind == "result" and with_tools and result_chars > 0 and v:
            out.append("  RESULT: " + one_line(v, result_chars))
    return "\n".join(out).strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--max-bytes", type=int, default=600_000)
    ap.add_argument("--out", default="-")
    a = ap.parse_args(argv)
    size = os.path.getsize(a.transcript)
    start = a.start if 0 <= a.start <= size else 0     # a shorter file than last time: start over
    evs = list(events(a.transcript, start))
    end = evs.pop()[2]
    cut = False
    for rc, tc, tools in ((300, 240, True), (120, 160, True), (0, 120, True), (0, 0, False)):
        text = render(evs, rc, tc, tools)
        if len(text.encode()) <= a.max_bytes:
            break
    else:
        raw = text.encode()
        text = "[the oldest part of this slice was cut to fit]\n" + raw[-a.max_bytes:].decode("utf-8", "ignore").split("\n", 1)[-1]
        cut = True
    if a.out == "-":
        sys.stderr.write(text)
    else:
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
    n = lambda k: sum(1 for e in evs if e[0] == k)
    print(json.dumps({"end": end, "person": n("person"), "agent": n("agent"), "tools": n("tool"), "bytes": len(text.encode()), "cut": cut}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
