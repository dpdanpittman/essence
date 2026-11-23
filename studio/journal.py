"""The journal and the paper piece: checking model text, writing entries, reading the tail, the engine verbs."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from typing import Optional, Sequence

from .folder import Paths, append_private, write_private
from .types import Context, VerbResult, VerbSpec

PIECE_MAX = 600
PIECE_PARAGRAPHS = 5
TAIL_MAX = 1500

_EMAIL = re.compile(r"\S+@\S+\.\w+")
_HIDDEN = {"Cc", "Cf", "Co", "Cs"}

PHRASES = {
    "window": "looked out the window",
    "sun": "felt the sun",
    "temperature": "checked my temperature",
    "journal": "read the journal",
    "write": "",
    "song": "put the song on",
    "read": "read something",
    "paper": "left a piece for the paper",
    "sleep": "",
}


# ---- checking text the model wants written ----------------------------------------------------

def _cut_words(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    i = s[:n + 1].rfind(" ")
    return (s[:i] if i > 0 else s[:n]).rstrip()


def clean_line(text: str, max_chars: int) -> tuple:
    """(line, "") when the text may go in the journal, else (None, reason)."""
    s = unicodedata.normalize("NFKC", text or "")
    chars = []
    for ch in s:
        if ch in "\n\t":
            chars.append(" ")
        elif unicodedata.category(ch) in _HIDDEN:
            return None, "hidden"
        else:
            chars.append(ch)
    s = " ".join("".join(chars).split())
    if not s:
        return None, "empty"
    if "://" in s or "www." in s.lower() or _EMAIL.search(s):
        return None, "link"
    if any(c in s for c in "`<>") or s[0] in "#>|-*[(" or s.lower().startswith("do:"):
        return None, "markup"
    return _cut_words(s, max_chars), ""


def clean_piece(text: str) -> tuple:
    """(piece, "") for the morning paper, at most 5 paragraphs and 600 characters, else (None, reason)."""
    paras = [p for p in (text or "").split("\n") if p.strip()][:PIECE_PARAGRAPHS]
    if not paras:
        return None, "empty"
    cleaned = []
    for p in paras:
        line, why = clean_line(p, PIECE_MAX)
        if line is None:
            return None, why
        cleaned.append(line)
    out: list = []
    size = 0
    for p in cleaned:
        sep = 1 if out else 0
        if size + sep + len(p) <= PIECE_MAX:
            out.append(p)
            size += sep + len(p)
            continue
        room = PIECE_MAX - size - sep
        if room >= 20:
            part = _cut_words(p, room)
            if part:
                out.append(part)
        break
    return "\n".join(out), ""


# ---- entries ----------------------------------------------------------------------------------

def format_entry(heading: str, happenings: Sequence[str], lines: Sequence[str], start: bool = False) -> str:
    """One journal entry, ending with a blank line (contract 5a)."""
    seen, order = set(), []
    for h in happenings:
        if h and h not in seen:
            seen.add(h)
            order.append(h)
    if not order and not lines:
        order = ["sat a while"]
    first = ", ".join(order)
    if start:
        first = (first + ", " if first else "") + "woke with a start"
    out = [f"## {heading}"]
    if first:
        out.append(f"- ({first})")
    out.extend(f"- {ln}" for ln in lines)
    return "\n".join(out) + "\n\n"


def append_entry(paths: Paths, entry: str) -> None:
    """Append one entry in a single write."""
    append_private(paths.journal, entry)


def entries(path: str) -> list:
    """All entries of a journal file, each as its text without the trailing blank line."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    out, cur = [], None
    for line in text.split("\n"):
        if line.startswith("## "):
            if cur is not None:
                out.append("\n".join(cur).strip())
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        out.append("\n".join(cur).strip())
    return out


def tail(path: str, n: int) -> list:
    return entries(path)[-n:] if n > 0 else []


def tail_text(path: str, n: int, max_chars: int = TAIL_MAX) -> str:
    """The last n entries, cut from the front to max_chars."""
    text = "\n\n".join(tail(path, n))
    if len(text) > max_chars:
        text = text[-max_chars:]
        nl = text.find("\n")
        if 0 <= nl < len(text) - 1:
            text = text[nl + 1:]
    return text


# ---- the paper file ---------------------------------------------------------------------------

def read_paper(paths: Paths, night: str) -> Optional[dict]:
    try:
        with open(paths.paper_file(night), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("date") == night else None


def write_paper(paths: Paths, night: str, piece: Optional[str], active: bool, written_at: datetime) -> dict:
    """Merge this wake-up into the night's paper file and write it atomically (0600).

    piece: tonight's new piece from this wake-up, or None. active: this wake-up used a verb with a
    happenings phrase or wrote a journal line. Call it only for wake-ups that started a model run.
    """
    old = read_paper(paths, night) or {}
    text = piece if piece is not None else (old.get("text") if isinstance(old.get("text"), str) else None)
    was_quiet = old.get("quiet", True) if isinstance(old.get("quiet"), bool) else True
    wakeups = old.get("wakeups") if isinstance(old.get("wakeups"), int) else 0
    data = {
        "version": 1,
        "date": night,
        "text": text,
        "quiet": bool(text is None and was_quiet and not active),
        "wakeups": wakeups + 1,
        "written_at": written_at.isoformat(timespec="seconds"),
    }
    os.makedirs(paths.paper_dir, mode=0o700, exist_ok=True)
    write_private(paths.paper_file(night), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data


# ---- engine verbs -----------------------------------------------------------------------------

def _book(ctx: Context) -> dict:
    return ctx.memory.setdefault("journal", {"lines": [], "piece": None})


def engine_verbs(cfg) -> list:
    """The enabled engine verbs: journal, write, paper, nothing, sleep."""
    max_line = cfg.journal.max_line_chars
    max_lines = cfg.journal.max_lines_per_wakeup

    def v_journal(ctx: Context, arg: str) -> VerbResult:
        text = tail_text(ctx.paths.journal, ctx.cfg.journal.tail_entries)
        return VerbResult(text or "The journal is empty.", PHRASES["journal"])

    def v_write(ctx: Context, arg: str) -> VerbResult:
        book = _book(ctx)
        if len(book["lines"]) >= max_lines:
            return VerbResult("That is enough for tonight's page.")
        line, why = clean_line(arg, max_line)
        if line is None:
            return VerbResult(f"That line did not go in the journal ({why}).")
        book["lines"].append(line)
        return VerbResult("Written.")

    def v_paper(ctx: Context, arg: str) -> VerbResult:
        piece, why = clean_piece(arg)
        if piece is None:
            return VerbResult(f"That piece will not go in the paper ({why}).")
        _book(ctx)["piece"] = piece
        return VerbResult("It will be in the paper in the morning.", PHRASES["paper"])

    def v_nothing(ctx: Context, arg: str) -> VerbResult:
        return VerbResult("")

    def v_sleep(ctx: Context, arg: str) -> VerbResult:
        return VerbResult("", "", end_wakeup=True)

    specs = []
    if cfg.verbs.journal:
        specs.append(VerbSpec("journal", "read the last entries of your journal", False, v_journal))
    if cfg.verbs.write:
        specs.append(VerbSpec("write", "<a line> - add a line to your journal", True, v_write))
    if cfg.verbs.paper and cfg.paper.enabled:
        specs.append(VerbSpec("paper", "<a few lines> - leave a short piece for the morning paper; "
                                       "a new one replaces tonight's earlier one", True, v_paper))
    if cfg.verbs.nothing:
        specs.append(VerbSpec("nothing", "do nothing", False, v_nothing))
    if cfg.verbs.sleep:
        specs.append(VerbSpec("sleep", "go back to sleep", False, v_sleep))
    return specs
