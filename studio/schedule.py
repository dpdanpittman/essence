"""The night plan: drawing start times, finding the one that is due, marking missed ones, the tick."""
from __future__ import annotations

import fcntl
import json
import os
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .config import hhmm_minutes
from .folder import Paths, write_private

DUE_MINUTES = 3
TRIES = 200


def tz(cfg) -> ZoneInfo:
    return ZoneInfo(cfg.schedule.time_zone)


def night_of(cfg, now: datetime) -> str:
    """The night date (schedule time zone) for an aware time."""
    return now.astimezone(tz(cfg)).date().isoformat()


def _local(night: date, minutes: int, zone: ZoneInfo) -> Optional[datetime]:
    """The aware local time `minutes` after midnight of night, or None when it does not exist (DST)."""
    naive = datetime.combine(night, time(0, 0)) + timedelta(minutes=minutes)
    aware = naive.replace(tzinfo=zone)
    back = aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    return aware if back == naive else None


def window(cfg, night: str) -> tuple:
    """(window_start, end_by) of a night as aware datetimes."""
    d = date.fromisoformat(night)
    zone = tz(cfg)
    start = datetime.combine(d, time(0, 0), zone) + timedelta(minutes=hhmm_minutes(cfg.schedule.window_start))
    end = datetime.combine(d, time(0, 0), zone) + timedelta(minutes=hhmm_minutes(cfg.schedule.end_by))
    return start, end


def in_window(cfg, now: datetime) -> bool:
    local = now.astimezone(tz(cfg))
    m = local.hour * 60 + local.minute
    return hhmm_minutes(cfg.schedule.window_start) <= m < hhmm_minutes(cfg.schedule.end_by)


def plan_night(cfg, night: str, rng: random.Random) -> list:
    """Draw the night's start times: count of them, min_gap_minutes apart, each <= end_by - wall_seconds."""
    d = date.fromisoformat(night)
    zone = tz(cfg)
    first = hhmm_minutes(cfg.schedule.window_start)
    last_s = hhmm_minutes(cfg.schedule.end_by) * 60 - cfg.limits.wall_seconds
    last = last_s // 60
    gap = timedelta(minutes=cfg.schedule.min_gap_minutes)
    count = cfg.schedule.count
    if count <= 0 or last < first:
        return []
    while count > 0:
        for _ in range(TRIES):
            picks = []
            for _ in range(count):
                t = _local(d, rng.randint(first, last), zone)
                if t is None:
                    break
                picks.append(t)
            if len(picks) != count:
                continue
            picks.sort(key=lambda x: x.astimezone(timezone.utc))
            if all(picks[i + 1].astimezone(timezone.utc) - picks[i].astimezone(timezone.utc) >= gap
                   for i in range(len(picks) - 1)):
                return picks
        count -= 1
    return []


def new_plan(cfg, night: str, rng: random.Random, now: datetime) -> dict:
    return {"night": night, "made": now.astimezone(tz(cfg)).isoformat(timespec="seconds"),
            "entries": [{"at": t.isoformat(timespec="seconds"), "status": "planned"}
                        for t in plan_night(cfg, night, rng)]}


def read_plan(paths: Paths, night: str) -> Optional[dict]:
    try:
        with open(paths.plan(night), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    return data


def planned_runs_logged(paths: Paths, night: str) -> bool:
    """True when wakeups.jsonl already has a planned wake-up for this night."""
    try:
        with open(paths.wakeups, encoding="utf-8") as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("night") == night and d.get("planned"):
                    return True
    except OSError:
        return False
    return False


def save_plan(paths: Paths, plan: dict) -> None:
    write_private(paths.plan(plan["night"]), json.dumps(plan, indent=1) + "\n")


def _at(entry: dict) -> datetime:
    return datetime.fromisoformat(entry["at"])


def due(plan: dict, now: datetime) -> Optional[int]:
    """The index of the first planned entry with at <= now < at + 3 min, or None."""
    for i, e in enumerate(plan.get("entries", [])):
        if e.get("status") != "planned":
            continue
        at = _at(e)
        if at <= now < at + timedelta(minutes=DUE_MINUTES):
            return i
    return None


def mark_missed(plan: dict, now: datetime) -> int:
    """Mark planned entries whose 3 minutes have passed. Returns how many."""
    n = 0
    for e in plan.get("entries", []):
        if e.get("status") == "planned" and _at(e) + timedelta(minutes=DUE_MINUTES) <= now:
            e["status"] = "missed"
            n += 1
    return n


class Lock:
    """A non-blocking flock on state/lock. acquired is False when another run holds it."""

    def __init__(self, path: str):
        self.path = path
        self.fd: Optional[int] = None
        self.acquired = False

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError:
            self.acquired = False
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            if self.acquired:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        return False


def tick(cfg, paths: Paths, now: datetime, run_wakeup: Callable, rng: Optional[random.Random] = None,
         after_last: Optional[Callable] = None, out=print) -> int:
    """One timer fire. run_wakeup(planned_at, n) returns an outcome with reason, turns, usage, exit_code.

    The caller has made the folder. Outside the window: exit 0, nothing printed, nothing touched.
    """
    if not in_window(cfg, now):
        return 0
    with Lock(paths.lock) as lock:
        if not lock.acquired:
            return 0
        night = night_of(cfg, now)
        plan = read_plan(paths, night)
        if plan is None:
            if os.path.lexists(paths.plan(night)) or planned_runs_logged(paths, night):
                # The plan was lost or damaged after the night began. Drawing fresh times could
                # give more than `count` wake-ups, so this night gets no more.
                plan = {"night": night, "made": now.astimezone(tz(cfg)).isoformat(timespec="seconds"),
                        "entries": [], "note": "plan unreadable; no more wake-ups tonight"}
            else:
                plan = new_plan(cfg, night, rng or random.Random(os.urandom(16)), now)
            save_plan(paths, plan)
        if mark_missed(plan, now):
            save_plan(paths, plan)
        i = due(plan, now)
        if i is None:
            return 0
        entry = plan["entries"][i]
        entry["status"] = "running"
        save_plan(paths, plan)
        outcome = None
        try:
            outcome = run_wakeup(_at(entry), i + 1)
        finally:
            entry["status"] = outcome.reason if outcome is not None else "terminated"
            save_plan(paths, plan)
        out(f"studio: wake-up {i + 1} ended ({outcome.reason}), {outcome.turns} turns, "
            f"{outcome.usage.total()} tokens")
        if after_last is not None and i == len(plan["entries"]) - 1:
            try:
                after_last(night)
            except Exception:
                pass
        return outcome.exit_code
