"""The jukebox: a song in time.

Songs are text files the person placed in ``jukebox/`` (or that the channel
adapter saved there). The script never fetches lyrics; only text already in
the folder plays. A song file:

    title: Lanterns
    by: someone
    length: 3:12

    first line
    second line

The verb ``song`` puts one on. While it is on, the sense ``song`` hands the
lines over at their real pace: line i is due at ``start + length * i / N``.
Each reading carries the lines due since the last one, at most 12 (when
more are due, the older ones went by unheard). Lines not delivered before
the wake-up ends are lost. Songs played are remembered in
``state/heard.json`` so the next one is a new one while new ones exist.

``memory["song"]`` is shared by the verb and the sense. ``is_on(ctx)``
tells the engine whether a song is playing (it shortens the pulse gap).
"""

import json
import os
import re
import stat
import unicodedata
from datetime import timedelta

from .types import SenseReading, VerbResult, VerbSpec

MAX_FILE_BYTES = 64 * 1024
MAX_LINES = 200
MAX_LINE_CHARS = 200
PER_READING = 12
READING_CHARS = 1200
SECONDS_PER_LINE = 5
HEADER = re.compile(r"^(title|by|length)\s*:\s*(.*)$", re.IGNORECASE)
LENGTH = re.compile(r"^(\d{1,3}):([0-5]\d)$")


def _plain(text: str) -> str:
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch == "\t":
            out.append(" ")
        elif cat in ("Cc", "Cf", "Co", "Cs"):
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def parse_song(text: str, fallback_title: str) -> dict | None:
    """{'title', 'by', 'length' (seconds), 'lines'} or None when no lines."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header = {}
    i = 0
    while i < len(raw):
        m = HEADER.match(raw[i].strip())
        if not m or m.group(1).lower() in header:
            break
        header[m.group(1).lower()] = m.group(2).strip()
        i += 1
    if header and i < len(raw) and raw[i].strip() == "":
        i += 1
    lines = []
    for line in raw[i:]:
        clean = _plain(line)
        if not clean:
            continue
        lines.append(clean[:MAX_LINE_CHARS])
        if len(lines) >= MAX_LINES:
            break
    if not lines:
        return None
    title = _plain(header.get("title", ""))[:120] or fallback_title
    length = None
    m = LENGTH.match(header.get("length", "").strip())
    if m:
        length = int(m.group(1)) * 60 + int(m.group(2))
    if not length:
        length = SECONDS_PER_LINE * len(lines)
    return {"title": title, "by": _plain(header.get("by", ""))[:120], "length": length, "lines": lines}


def song_files(jukebox: str) -> list[tuple[float, str]]:
    """(mtime, path) of playable files: regular *.txt, no symlinks, <= 64 KB."""
    out = []
    try:
        names = os.listdir(jukebox)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".txt") or name.startswith("."):
            continue
        path = os.path.join(jukebox, name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES or st.st_size == 0:
            continue
        out.append((st.st_mtime, path))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return out


def load_song(path: str) -> dict | None:
    """Read one song file safely (no symlink is followed)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
            return None
        data = os.read(fd, MAX_FILE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_BYTES:
        return None
    stem = os.path.basename(path)[:-4].replace("-", " ").replace("_", " ")
    return parse_song(data.decode("utf-8", errors="replace"), _plain(stem) or "a song")


def _heard_path(ctx) -> str:
    return os.path.join(ctx.paths.state, "heard.json")


def read_heard(ctx) -> list[str]:
    try:
        with open(_heard_path(ctx), encoding="utf-8") as fh:
            data = json.load(fh)
        heard = data.get("heard", [])
        return [h for h in heard if isinstance(h, str)]
    except (OSError, ValueError, AttributeError):
        return []


def _write_heard(ctx, heard: list[str]) -> None:
    if ctx.dry:
        return
    from .folder import write_private

    try:
        write_private(_heard_path(ctx), json.dumps({"version": 1, "heard": heard[-500:]}, indent=1) + "\n")
    except OSError:
        pass


def is_on(ctx) -> bool:
    """True while a song is playing in this wake-up."""
    s = ctx.memory.get("song")
    if not s or not s.get("on"):
        return False
    if ctx.now() >= s["start"] + timedelta(seconds=s["length"]):
        if s["next"] >= len(s["lines"]):
            return False
    return True


def _song(ctx, _arg: str) -> VerbResult:
    mem = ctx.memory.setdefault("song", {})
    if mem.get("on") and is_on(ctx):
        return VerbResult("The song is already on.")
    files = song_files(ctx.paths.jukebox)
    if not files:
        return VerbResult("No song is here.")
    heard = read_heard(ctx)
    names = [os.path.basename(p) for _, p in files]
    fresh = [p for (_, p), n in zip(files, names) if n not in heard]
    song = None
    chosen = None
    for path in fresh:
        song = load_song(path)
        if song:
            chosen = path
            break
    if song is None:
        pool = [p for _, p in files]
        ctx.rng.shuffle(pool)
        for path in pool:
            song = load_song(path)
            if song:
                chosen = path
                break
    if song is None:
        return VerbResult("No song is here.")
    mem.clear()
    mem.update(
        {
            "on": True,
            "title": song["title"],
            "lines": song["lines"],
            "length": song["length"],
            "start": ctx.now(),
            "next": 0,
            "ended_told": False,
        }
    )
    name = os.path.basename(chosen)
    if name in heard:
        heard.remove(name)
    heard.append(name)
    _write_heard(ctx, heard)
    return VerbResult(f"The song is on: {song['title']}."[:600], happened="put the song on")


def due_lines(s: dict, now) -> tuple[list[str], int]:
    """Lines due since the last delivery (latest 12) and the new next index."""
    n = len(s["lines"])
    elapsed = (now - s["start"]).total_seconds()
    if elapsed < 0:
        return [], s["next"]
    due_count = n if elapsed >= s["length"] else min(n, int(elapsed * n / s["length"]) + 1)
    start = s["next"]
    if due_count <= start:
        return [], start
    picked = s["lines"][max(start, due_count - PER_READING):due_count]
    return picked, due_count


class SongSense:
    """Sense ``song``: the lines of the song that is on, as they come."""

    name = "song"

    def read(self, ctx):
        try:
            s = ctx.memory.get("song")
            if not s or not s.get("on"):
                return None
            lines, nxt = due_lines(s, ctx.now())
            s["next"] = nxt
            if lines:
                kept, size = [], 0
                for line in lines:
                    if size + len(line) + 1 > READING_CHARS:
                        break
                    kept.append(line)
                    size += len(line) + 1
                return SenseReading("song", "\n".join(kept), True)
            if nxt >= len(s["lines"]) and ctx.now() >= s["start"] + timedelta(seconds=s["length"]):
                s["on"] = False
                if not s.get("ended_told"):
                    s["ended_told"] = True
                    return SenseReading("song", "the song ended.", True)
            return None
        except Exception:
            return None


def sense(cfg):
    return SongSense() if cfg.senses.song else None


def verb_specs(cfg) -> list:
    if not cfg.verbs.song:
        return []

    def handler(ctx, arg):
        try:
            return _song(ctx, arg)
        except Exception:
            return VerbResult("That did not work just now.")

    return [VerbSpec("song", "put the song on", False, handler)]
