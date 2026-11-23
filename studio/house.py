"""The house, lightly: a few signals the author chose, told in the author's words.

Two kinds of signal, from ``house.signals``:

- ``unit``: a systemd user unit. Running: its ``running`` text. Finished
  (it stopped during this wake-up, or its last run ended in the past
  ``RECENT_HOURS``): its ``finished`` text. Read with one
  ``systemctl --user show`` call per unit, timeout 5 s.
- ``file``: a file the author names. Its ``changed`` text when the file
  changed during this wake-up or in the past ``RECENT_HOURS``.

Nothing about people or devices. The agent hears only the fixed texts.
Provides the sense ``house``.
"""

import os
import subprocess
from datetime import datetime, timedelta, timezone

from .types import SenseReading

RECENT_HOURS = 6
ACTIVE = {"active", "activating", "reloading", "deactivating"}


def _item(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _run(argv: list[str]) -> str | None:
    """Run a read-only command, timeout 5 s, return stdout or None."""
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "USER")}
    env["TZ"] = "UTC"
    env["LC_ALL"] = "C"
    env.setdefault("PATH", "/usr/bin:/bin")
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


runner = _run  # tests replace it


def parse_show(text: str) -> tuple[str, datetime | None]:
    """ActiveState and ExecMainExitTimestamp (UTC) from ``systemctl show`` output."""
    state, ended = "", None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        value = value.strip()
        if key == "ActiveState":
            state = value
        elif key == "ExecMainExitTimestamp" and value and value != "n/a":
            # printed with TZ=UTC: "Sun 2026-11-22 10:20:11 UTC"
            bits = value.split()
            if len(bits) >= 3:
                try:
                    ended = datetime.strptime(f"{bits[1]} {bits[2]}", "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    ended = None
    return state, ended


def _unit_event(sig, mem: dict, now: datetime) -> tuple[str, str] | None:
    unit = _item(sig, "unit")
    if not unit or not isinstance(unit, str):
        return None
    out = runner(["systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "ExecMainExitTimestamp"])
    if out is None:
        return None
    state, ended = parse_show(out)
    seen = mem.setdefault("units", {})
    before = seen.get(unit)
    seen[unit] = (state, ended)
    if state in ACTIVE:
        return ("running:" + unit, _item(sig, "running") or "")
    finished = False
    if before is not None:
        old_state, old_ended = before
        if old_state in ACTIVE or (ended is not None and ended != old_ended):
            finished = True
    if ended is not None and timedelta(0) <= now - ended <= timedelta(hours=RECENT_HOURS):
        finished = True
    if finished:
        return ("finished:" + unit, _item(sig, "finished") or "")
    return None


def _file_event(sig, mem: dict, now: datetime) -> tuple[str, str] | None:
    path = _item(sig, "path")
    if not path or not isinstance(path, str):
        return None
    path = os.path.expanduser(path)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return None
    seen = mem.setdefault("files", {})
    before = seen.get(path)
    seen[path] = mtime
    when = datetime.fromtimestamp(mtime, tz=timezone.utc)
    recent = timedelta(0) <= now - when <= timedelta(hours=RECENT_HOURS)
    if recent or (before is not None and mtime != before):
        return ("changed:" + path + ":" + str(mtime), _item(sig, "changed") or "")
    return None


def _clean(text: str) -> str:
    text = " ".join(str(text).split())
    return text.rstrip(".")


class HouseSense:
    """Sense ``house``: the author's fixed texts for units and files."""

    name = "house"

    def read(self, ctx):
        try:
            signals = list(ctx.cfg.house.signals or [])
            if not signals:
                return None
            mem = ctx.memory.setdefault("house", {})
            now = ctx.now()
            events = []
            for sig in signals:
                kind = _item(sig, "kind")
                ev = None
                if kind == "unit":
                    ev = _unit_event(sig, mem, now)
                elif kind == "file":
                    ev = _file_event(sig, mem, now)
                if ev and _clean(ev[1]):
                    events.append(ev)
            if not events:
                mem["last_key"] = ()
                return None
            key = tuple(e[0] for e in events)
            changed = mem.get("last_key") != key
            mem["last_key"] = key
            text = ". ".join(_clean(e[1]) for e in events) + "."
            return SenseReading("house", text[:160], changed)
        except Exception:
            return None


def sense(cfg):
    if not cfg.senses.house or not list(cfg.house.signals or []):
        return None
    return HouseSense()
