"""The machine itself: temperatures, fans, load and the disk working.

Reads only plain files under ``body.sys_root`` (default ``/``):
``sys/class/hwmon/*``, ``proc/loadavg``, ``proc/cpuinfo``,
``proc/diskstats`` and ``sys/block``. Nothing is written.

Provides the sense ``body`` and the verb ``temperature``.
"""

import glob
import os
import re
import time

from .types import SenseReading, VerbResult, VerbSpec

_sleep = time.sleep  # tests replace it
_clock = time.monotonic  # tests replace it
DISK_GAP_SECONDS = 0.25


def _item(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _root(cfg) -> str:
    return cfg.body.sys_root or "/"


def _p(cfg, *parts) -> str:
    return os.path.join(_root(cfg), *parts)


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(65536)
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    text = _read(path)
    if text is None:
        return None
    try:
        return int(text.strip())
    except ValueError:
        return None


def _natural(s: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


def hwmon_dirs(cfg) -> list[tuple[str, str]]:
    """(name, directory) for each hwmon device, in a stable order."""
    out = []
    for d in sorted(glob.glob(_p(cfg, "sys", "class", "hwmon", "hwmon*")), key=_natural):
        name = (_read(os.path.join(d, "name")) or "").strip()
        if name:
            out.append((name, d))
    return out


def _temp_inputs(d: str) -> list[str]:
    return sorted(glob.glob(os.path.join(d, "temp*_input")), key=_natural)


def temperatures(cfg) -> list[tuple[str, float]]:
    """(label, degrees C) for the configured sensors, or every sensor found."""
    devices = hwmon_dirs(cfg)
    out = []
    wanted = list(cfg.body.temps or [])
    if wanted:
        for item in wanted:
            hw, label = _item(item, "hwmon"), _item(item, "label")
            for name, d in devices:
                if name != hw:
                    continue
                inputs = _temp_inputs(d)
                first = os.path.join(d, "temp1_input")
                path = first if first in inputs else (inputs[0] if inputs else None)
                value = _read_int(path) if path else None
                if value is not None:
                    out.append((label, value / 1000.0))
                    break
        return out
    for name, d in devices:
        inputs = _temp_inputs(d)
        for path in inputs:
            value = _read_int(path)
            if value is None:
                continue
            label = name
            if len(inputs) > 1:
                lab = (_read(path.replace("_input", "_label")) or "").strip()
                label = f"{name} {lab}" if lab else f"{name} {os.path.basename(path)[:-6]}"
            out.append((label, value / 1000.0))
    return out


def fans(cfg) -> list[int]:
    """Fan speeds in rpm. Empty when the machine has no fan sensor."""
    out = []
    for _, d in hwmon_dirs(cfg):
        for path in sorted(glob.glob(os.path.join(d, "fan*_input")), key=_natural):
            value = _read_int(path)
            if value is not None:
                out.append(value)
    return out


def _cpu_count(cfg) -> int:
    text = _read(_p(cfg, "proc", "cpuinfo"))
    if text:
        n = sum(1 for line in text.splitlines() if re.match(r"processor\s*:", line))
        if n:
            return n
    return os.cpu_count() or 1


def load_word(cfg) -> str | None:
    text = _read(_p(cfg, "proc", "loadavg"))
    if not text:
        return None
    try:
        load1 = float(text.split()[0])
    except (ValueError, IndexError):
        return None
    ratio = load1 / _cpu_count(cfg)
    if ratio < 0.25:
        return "light"
    if ratio < 0.75:
        return "moderate"
    if ratio < 1.5:
        return "busy"
    return "heavy"


def _whole_disks(cfg) -> set[str] | None:
    block = _p(cfg, "sys", "block")
    try:
        return set(os.listdir(block))
    except OSError:
        return None


def disk_sample(cfg) -> dict[str, int] | None:
    """Milliseconds spent doing I/O, per chosen disk, from ``proc/diskstats``."""
    text = _read(_p(cfg, "proc", "diskstats"))
    if text is None:
        return None
    chosen = cfg.body.disk
    whole = _whole_disks(cfg) if not chosen else None
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) < 13:
            continue
        name = f[2]
        if chosen:
            if name != chosen:
                continue
        else:
            if re.match(r"(loop|ram|zram)\d", name):
                continue
            if whole is not None and name not in whole:
                continue
        try:
            out[name] = int(f[12])
        except ValueError:
            continue
    return out


def disk_busy(prev: dict[str, int], cur: dict[str, int], elapsed_s: float) -> float:
    """Highest share of time any disk spent working between two samples (0..1)."""
    if elapsed_s <= 0:
        return 0.0
    best = 0.0
    for name, ms in cur.items():
        if name in prev:
            share = max(0, ms - prev[name]) / (elapsed_s * 1000.0)
            best = max(best, min(1.0, share))
    return best


def disk_word(share: float) -> str:
    if share < 0.05:
        return "the disk is quiet"
    if share < 0.40:
        return "the disk is working"
    return "the disk is busy"


def _disk(ctx) -> str | None:
    mem = ctx.memory.setdefault("body", {})
    prev = mem.get("disk")
    if prev is None:
        first = disk_sample(ctx.cfg)
        if not first:
            return None
        t0 = _clock()
        _sleep(DISK_GAP_SECONDS)
        prev = (t0, first)
    cur = disk_sample(ctx.cfg)
    if not cur:
        return None
    t1 = _clock()
    mem["disk"] = (t1, cur)
    return disk_word(disk_busy(prev[1], cur, t1 - prev[0]))


def _fan_word(rpms: list[int]) -> str | None:
    if not rpms:
        return None
    top = max(rpms)
    if top == 0:
        return "the fans are still"
    return f"fan {top} rpm"


def _bucket_key(temps, rpms, load, disk) -> tuple:
    return (
        tuple((label, int(c // 5)) for label, c in temps),
        (max(rpms) // 300) if rpms else None,
        load,
        disk,
    )


def _temps_text(temps) -> str:
    return ", ".join(f"{label} {round(c)} C" for label, c in temps)


class BodySense:
    """Sense ``body``: heat, fans, load and disk, from plain system files."""

    name = "body"

    def read(self, ctx):
        try:
            cfg = ctx.cfg
            temps = temperatures(cfg)
            rpms = fans(cfg)
            load = load_word(cfg)
            disk = _disk(ctx)
            parts = []
            if temps:
                parts.append(_temps_text(temps))
            fan = _fan_word(rpms)
            if fan:
                parts.append(fan)
            if load:
                parts.append(f"load {load}")
            if disk:
                parts.append(disk)
            if not parts:
                return None
            text = (". ".join(parts) + ".")[:160]
            mem = ctx.memory.setdefault("body", {})
            key = _bucket_key(temps, rpms, load, disk)
            changed = mem.get("last_key") != key
            mem["last_key"] = key
            return SenseReading("body", text, changed)
        except Exception:
            return None


def _temperature(ctx, _arg: str) -> VerbResult:
    cfg = ctx.cfg
    temps = temperatures(cfg)
    rpms = fans(cfg)
    load = load_word(cfg)
    sentences = []
    if temps:
        bits = [f"{label} at {round(c)} C" for label, c in temps]
        sentences.append(bits[0][0].upper() + bits[0][1:] + (", " + ", ".join(bits[1:]) if bits[1:] else "") + ".")
    else:
        sentences.append("No temperature can be read just now.")
    if rpms:
        if max(rpms) == 0:
            sentences.append("The fans are still.")
        else:
            sentences.append(f"The fans turn at up to {max(rpms)} rpm.")
    else:
        sentences.append("There is no fan to hear.")
    if load:
        sentences.append(f"The load is {load}.")
    return VerbResult(" ".join(sentences)[:600], happened="checked my temperature")


def sense(cfg):
    return BodySense() if cfg.senses.body else None


def verb_specs(cfg) -> list:
    if not cfg.verbs.temperature:
        return []

    def handler(ctx, arg):
        try:
            return _temperature(ctx, arg)
        except Exception:
            return VerbResult("That did not work just now.")

    return [VerbSpec("temperature", "check your temperature (the machine's heat and fans)", False, handler)]
