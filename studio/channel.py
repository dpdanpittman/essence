"""The channel adapter. OFF until ``channel.chat_id`` is set.

The adapter never talks to a chat service and never polls one. Another
process (the author's own inbox job) writes one JSON file per message into
``channel.inbox_dir``: ``{"from_id": int, "date": iso, "text": str}``.

- ``collect(ctx)``: messages from ``channel.allowed_sender_id`` become
  jukebox files (``title: from the channel``). Every other file is ignored,
  counted and removed. Returns the number accepted.
- ``post(cfg, text)``: runs ``channel.post_command`` once with the text on
  stdin (timeout 30 s). The model never reaches it; the engine calls it.
- ``status(cfg)``: ``no channel yet`` or ``on``.
"""

import json
import os
import stat
import subprocess
import unicodedata
from datetime import datetime, timezone

MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEXT_CHARS = 4000


def enabled(cfg) -> bool:
    return cfg.channel.chat_id is not None


def status(cfg) -> str:
    return "on" if enabled(cfg) else "no channel yet"


def clean_text(text: str) -> str:
    """Control and format characters out, lines trimmed, at most 4000 characters."""
    kept = []
    for ch in text:
        if ch == "\n":
            kept.append(ch)
        elif ch in "\t\r":
            kept.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs"):
            continue
        else:
            kept.append(ch)
    lines = [" ".join(line.split()) for line in "".join(kept).split("\n")]
    out = "\n".join(lines).strip("\n")
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out[:MAX_TEXT_CHARS]


def _read_message(path: str):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_MESSAGE_BYTES:
            return None
        data = os.read(fd, MAX_MESSAGE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    return msg


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _stamp(msg: dict, ctx) -> str:
    when = None
    raw = msg.get("date")
    if isinstance(raw, str):
        try:
            when = datetime.fromisoformat(raw)
        except ValueError:
            when = None
    if when is None or when.tzinfo is None:
        when = ctx.now()
    return when.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def collect(ctx) -> int:
    """Turn accepted inbox files into jukebox files. Returns the accepted count."""
    cfg = ctx.cfg
    counts = ctx.memory.setdefault("channel", {"accepted": 0, "ignored": 0})
    if not enabled(cfg) or not cfg.channel.inbox_dir or ctx.dry:
        return 0
    inbox = cfg.channel.inbox_dir
    try:
        names = sorted(os.listdir(inbox))
    except OSError:
        return 0
    from .folder import write_private

    allowed = cfg.channel.allowed_sender_id
    accepted = 0
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(inbox, name)
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                continue
        except OSError:
            continue
        msg = _read_message(path)
        sender = msg.get("from_id") if msg else None
        text = msg.get("text") if msg else None
        ok = (
            allowed is not None
            and isinstance(sender, int)
            and not isinstance(sender, bool)
            and sender == allowed
            and isinstance(text, str)
        )
        if ok:
            body = clean_text(text)
            if body:
                stamp = _stamp(msg, ctx)
                target = os.path.join(ctx.paths.jukebox, f"channel-{stamp}.txt")
                n = 2
                while os.path.lexists(target):
                    target = os.path.join(ctx.paths.jukebox, f"channel-{stamp}-{n}.txt")
                    n += 1
                try:
                    write_private(target, "title: from the channel\n\n" + body + "\n")
                except OSError:
                    continue  # keep the message file; nothing was lost
                accepted += 1
            else:
                counts["ignored"] += 1
        else:
            counts["ignored"] += 1
        _remove(path)
    counts["accepted"] += accepted
    return accepted


def post(cfg, text: str) -> bool:
    """Run ``post_command`` once with ``text`` on stdin. False when off or failed."""
    command = cfg.channel.post_command
    if not enabled(cfg) or not command or not text:
        return False
    try:
        done = subprocess.run(
            list(command),
            input=text,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
