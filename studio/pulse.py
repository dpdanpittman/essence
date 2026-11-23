"""The pulse: when the next small message comes, and what it carries from the senses."""
from __future__ import annotations

import datetime as _dt
import random
import threading
from typing import Callable, Optional, Sequence

from .types import Context, SenseReading
from . import wire

QUIET = ["nothing new.", "still.", "quiet.", "the same as before."]
SENSE_TIMEOUT_S = 5.0


def next_gap(cfg, rng: random.Random, song_on: bool) -> float:
    """Seconds to wait after an answer before the next pulse."""
    if song_on:
        return float(cfg.pulse.song_seconds)
    return rng.uniform(cfg.pulse.min_seconds, cfg.pulse.max_seconds)


def _read_one(sense, ctx: Context) -> Optional[SenseReading]:
    """One sense reading, at most about 5 s; a sense that raises or hangs gives None."""
    box: list = []

    def run():
        try:
            box.append(sense.read(ctx))
        except Exception:
            box.append(None)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(SENSE_TIMEOUT_S + 1.0)
    if not box:
        return None
    r = box[0]
    if not isinstance(r, SenseReading) or not isinstance(r.text, str) or not r.text.strip():
        return None
    return r


def gather(ctx: Context, senses: Sequence) -> list:
    """Ask every sense for a reading. Readings that are None, broken or late are left out."""
    out = []
    for s in senses:
        r = _read_one(s, ctx)
        if r is not None:
            out.append(r)
    return out


def song_playing(readings: Sequence[SenseReading]) -> bool:
    return any(r.sense == "song" for r in readings)


def pulse_lines(readings: Sequence[SenseReading], rng: random.Random, quiet_chance: float,
                all_changed: bool = False) -> list:
    """The lines of one pulse (without the PULSE header), by the rules in the contract (3c)."""
    others = [r for r in readings if r.sense != "song"]
    songs = [r for r in readings if r.sense == "song"]
    changed = [r for r in others if r.changed or all_changed][:wire.PULSE_MAX_SENSES]
    song_changed = [r for r in songs if r.changed or all_changed]
    lines: list = []
    for r in changed:
        lines.extend(wire.reading_lines(r))
    song_lines: list = []
    for r in song_changed:
        song_lines.extend(wire.reading_lines(r))
    lines.extend(song_lines[:wire.PULSE_MAX_SONG_LINES])
    if lines:
        return lines
    if others and rng.random() < quiet_chance:
        return wire.reading_lines(rng.choice(others))[:1] or [rng.choice(QUIET)]
    return [rng.choice(QUIET)]


def pulse_text(readings: Sequence[SenseReading], rng: random.Random, quiet_chance: float,
               all_changed: bool = False, extra: Sequence[str] = ()) -> str:
    """A full PULSE message."""
    return wire.pulse_message(list(extra) + pulse_lines(readings, rng, quiet_chance, all_changed))


def wait(seconds: float, now: Callable, sleep: Callable[[float], None],
         stop: Callable[[], Optional[str]]) -> Optional[str]:
    """Wait, looking at stop() every second. Returns stop()'s word if it spoke, else None."""
    end = now() + _dt.timedelta(seconds=max(0.0, seconds))
    while True:
        word = stop()
        if word:
            return word
        left = (end - now()).total_seconds()
        if left <= 0:
            return None
        sleep(min(1.0, left))
