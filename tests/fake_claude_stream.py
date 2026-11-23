#!/usr/bin/env python3
"""A fake `claude` for the studio tests. It speaks stream-json on stdin and stdout and writes nothing.

Behaviour comes from env FAKE_CLAUDE_MODE:
  ok        per user line: init (no tools), one assistant message, a result with usage
  tools     like ok, but the init lists a tool
  mcp       like ok, but the init lists an MCP server
  hang      reads lines, never answers
  garbage   prints lines that are not JSON, never a result
  flood     one assistant message of 1 MB, then a result with that text
  endless   assistant events forever, never a result
  exit      exits 3 after the first line
  error     a result with is_error true
  slowstart sleeps 5 s, then behaves like ok
  envnames  like ok, but the answer is the sorted names of its environment (names only, never values)
            and whether CLAUDE_CONFIG_DIR exists
  prompt    like ok, but the answer reports on --system-prompt-file: the sha256 of its text, whether two
            reads agree, and whether that text also appears anywhere in argv
Answers for ok come from the file named by FAKE_CLAUDE_ANSWERS, one per line, "\\n" for a newline.
"""
import hashlib
import json
import os
import sys
import time

USAGE = {"input_tokens": 1000, "cache_creation_input_tokens": 500, "cache_read_input_tokens": 2000,
         "output_tokens": 50}


def emit(obj):
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        os._exit(0)


def answers():
    path = os.environ.get("FAKE_CLAUDE_ANSWERS")
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n").replace("\\n", "\n") for ln in f]


def main():
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    if mode == "slowstart":
        time.sleep(5)
        mode = "ok"
    script = answers()
    turn = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            json.loads(line)
        except ValueError:
            continue
        if mode == "hang":
            continue
        if mode == "exit":
            sys.exit(3)
        if mode == "garbage":
            sys.stdout.write("this is not json\n{broken\n")
            sys.stdout.flush()
            continue
        init = {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "model": "fake"}
        if mode == "tools":
            init["tools"] = ["Bash"]
        if mode == "mcp":
            init["mcp_servers"] = [{"name": "files", "status": "connected"}]
        emit(init)
        if mode == "endless":
            while True:
                emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "and on "}]}})
                time.sleep(0.01)
        text = script[turn] if turn < len(script) else "."
        if mode == "flood":
            text = "x" * 1_000_000
        if mode == "envnames":
            cd = os.environ.get("CLAUDE_CONFIG_DIR")
            text = " ".join(sorted(os.environ)) + " configdir=" + ("exists" if cd and os.path.isdir(cd) else "none")
        if mode == "prompt":
            path = sys.argv[sys.argv.index("--system-prompt-file") + 1]
            with open(path, encoding="utf-8") as f:
                first = f.read()
            with open(path, encoding="utf-8") as f:
                second = f.read()
            text = "sha=%s same=%s inargv=%s" % (hashlib.sha256(first.encode()).hexdigest(), first == second,
                                                  any(first and first in a for a in sys.argv))
        turn += 1
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        emit({"type": "result", "subtype": "success", "result": text, "is_error": mode == "error",
              "num_turns": 1, "usage": USAGE, "total_cost_usd": round(0.01 * turn, 4)})


if __name__ == "__main__":
    main()
