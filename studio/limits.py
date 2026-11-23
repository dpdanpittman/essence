"""Limits: the kill switch, the usage ledger, the nightly allowance and the caps of one wake-up."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .folder import Paths, write_private
from .types import Usage


# ---- kill switch -------------------------------------------------------------------------------

def switch_off(paths: Paths) -> bool:
    """True when the kill switch file is there (the studio is off)."""
    return os.path.lexists(paths.kill_switch)


def turn_off(paths: Paths, now: Optional[datetime] = None) -> None:
    parent = os.path.dirname(paths.kill_switch)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    write_private(paths.kill_switch, stamp + "\n")


def turn_on(paths: Paths) -> None:
    try:
        os.unlink(paths.kill_switch)
    except FileNotFoundError:
        pass


# ---- usage ledger ------------------------------------------------------------------------------

def read_ledger(paths: Paths) -> dict:
    try:
        with open(paths.usage, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def night_usage(paths: Paths, night: str) -> Usage:
    return Usage.from_dict(read_ledger(paths).get(night, {}))


def night_total(paths: Paths, night: str) -> int:
    return night_usage(paths, night).total()


def record(paths: Paths, night: str, usage: Usage, cost_usd: Optional[float], estimated_turns: int,
           started_model: bool) -> None:
    """Add one wake-up to the night's line in state/usage.json."""
    ledger = read_ledger(paths)
    row = ledger.get(night) if isinstance(ledger.get(night), dict) else {}
    before = Usage.from_dict(row)
    after = before + usage

    def num(k, kind=int):
        v = row.get(k, 0)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else kind(0)

    new = after.as_dict()
    new["wakeups"] = int(num("wakeups")) + (1 if started_model else 0)
    new["cost_usd"] = round(float(num("cost_usd", float)) + float(cost_usd or 0.0), 6)
    new["estimated_turns"] = int(num("estimated_turns")) + estimated_turns
    ledger[night] = new
    write_private(paths.usage, json.dumps(ledger, indent=1, sort_keys=True) + "\n")


# ---- caps of one wake-up -----------------------------------------------------------------------

@dataclass
class WakeCaps:
    """Counts one wake-up against its limits. check() says why to stop, or None."""
    limits: object                 # cfg.limits
    planned_end: datetime
    hard_end: datetime
    night_before: int              # the night's total before this wake-up
    turns: int = 0
    usage: Usage = field(default_factory=Usage)
    estimated_turns: int = 0
    cost_usd: Optional[float] = None
    ledger: bool = True            # False: the allowance is not looked at (measure)

    def add(self, usage: Usage, estimated: bool, cost: Optional[float]) -> None:
        self.usage = self.usage + usage
        if estimated:
            self.estimated_turns += 1
        if cost is not None:
            self.cost_usd = cost

    def check(self, now: datetime, off: bool) -> Optional[str]:
        """Before each send: off, turns, time, tokens, allowance (in that order)."""
        if off:
            return "off"
        if self.turns >= self.limits.max_turns:
            return "turns"
        if now >= self.planned_end or now >= self.hard_end:
            return "time"
        if self.usage.total() >= self.limits.wakeup_tokens:
            return "tokens"
        if self.ledger and self.night_before + self.usage.total() >= self.limits.daily_tokens:
            return "allowance"
        return None
