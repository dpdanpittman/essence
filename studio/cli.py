"""The studio command line: status, tick, wake, measure, off, on, journal tail, plan, config check.

Output is counts, status words, times and paths. Never model text, except `journal tail`.
Exit 0 ok or skipped, 1 failure, 2 usage or config error.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from . import VERSION, config, folder, journal, limits, schedule, wake
from .folder import Paths


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"studio: {message}\n")
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    p = _Parser(prog="studio", description="The studio: a few short night wake-ups with no task.")
    p.add_argument("--config", help="config file (else STUDIO_CONFIG, else ~/.config/studio/config.json)")
    p.add_argument("--studio-dir", help="studio folder (overrides the config and STUDIO_DIR)")
    p.add_argument("--version", action="version", version=f"studio {VERSION}")
    # The global options also work after a command (studio wake --fake-model --studio-dir X).
    common = _Parser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--studio-dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", parser_class=_Parser)
    _add = sub.add_parser

    def add_parser(name, **kw):
        return _add(name, parents=[common], **kw)
    sub.add_parser = add_parser
    sub.add_parser("status", help="say how the studio stands")
    sub.add_parser("tick", help="run a planned wake-up when one is due (the timer runs this)")
    w = sub.add_parser("wake", help="one wake-up now, outside the plan")
    g = w.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="no model, write nothing, print the prompt and messages")
    g.add_argument("--fake-model", action="store_true", help="the full loop with a scripted model")
    m = sub.add_parser("measure", help="real model, one short run per kind, in temp folders")
    m.add_argument("--kinds", default="quiet,song,journal,busy")
    m.add_argument("--no-network", action="store_true")
    m.add_argument("--keep", action="store_true")
    sub.add_parser("off", help="turn the studio off (kill switch)")
    sub.add_parser("on", help="turn the studio on")
    j = sub.add_parser("journal", help="the journal")
    jsub = j.add_subparsers(dest="jcmd", parser_class=_Parser)
    t = jsub.add_parser("tail", help="print the last entries", parents=[common])
    t.add_argument("-n", type=int, default=5)
    pl = sub.add_parser("plan", help="print a night's plan")
    pl.add_argument("--night")
    c = sub.add_parser("config", help="the config")
    csub = c.add_subparsers(dest="ccmd", parser_class=_Parser)
    csub.add_parser("check", help="load and print the resolved keys", parents=[common])
    return p


def _load(args) -> config.Config:
    env = dict(os.environ)
    if args.studio_dir:
        env["STUDIO_DIR"] = args.studio_dir
    return config.load(args.config, env)


def _hhmm(iso: str, zone: ZoneInfo) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(zone).strftime("%H:%M")
    except (TypeError, ValueError):
        return "?"


# ---- commands ---------------------------------------------------------------------------------

def cmd_status(cfg, paths: Paths, out, now: datetime) -> int:
    zone = ZoneInfo(cfg.schedule.time_zone)
    night = schedule.night_of(cfg, now)
    out(f"studio: {'off' if limits.switch_off(paths) else 'on'} (kill switch {paths.kill_switch})")
    out(f"folder: {paths.root} (journal: {len(journal.entries(paths.journal))} entries)")
    if cfg.schedule.count == 0:
        tonight = "no wake-ups (count 0)"
    else:
        plan = schedule.read_plan(paths, night)
        if plan is None:
            tonight = "not planned yet"
        else:
            parts = [f"{_hhmm(e.get('at'), zone)} {e.get('status', '?')}" for e in plan["entries"]]
            tonight = ", ".join(parts) if parts else "no wake-ups fit the window"
    out(f"tonight ({night}, {cfg.schedule.time_zone}): {tonight}")
    u = limits.night_usage(paths, night)
    out(f"tokens tonight: {u.total()} of {cfg.limits.daily_tokens} (input {u.input}, cache write "
        f"{u.cache_creation}, cache read {u.cache_read}, output {u.output})")
    last = wake.last_wakeup(paths)
    if last is None:
        out("last wake-up: none yet")
    else:
        out(f"last wake-up: {last.get('night', '?')} {_hhmm(last.get('started'), zone)}, "
            f"{last.get('turns', 0)} turns, ended: {last.get('reason', '?')}"
            + (f" ({last['detail']})" if isinstance(last.get("detail"), str) else ""))
    today = now.astimezone(zone).date()
    try:
        from . import reading
        rs = reading.status(cfg, today)
    except Exception:
        rs = "unknown (the reading module did not load)"
    out(f"reading: {rs}")
    try:
        from . import channel
        cs = channel.status(cfg)
    except Exception:
        cs = "unknown (the channel module did not load)"
    out(f"channel: {cs}")
    if not cfg.paper.enabled:
        out("paper: off")
    else:
        p = journal.read_paper(paths, night)
        if p is None:
            word = "nothing yet"
        elif isinstance(p.get("text"), str):
            word = "piece"
        elif p.get("quiet") is True:
            word = "quiet"
        else:
            word = "nothing yet"
        out(f"paper: on (tonight: {word})")
    out(f"config: {cfg.source_path or 'none (all defaults)'}")
    return 0


def _post_piece(cfg, paths: Paths):
    def after_last(night: str) -> None:
        if not cfg.channel.post_piece:
            return
        from . import channel
        if not channel.enabled(cfg):
            return
        p = journal.read_paper(paths, night)
        if p and isinstance(p.get("text"), str):
            channel.post(cfg, p["text"])
    return after_last


def cmd_tick(cfg, paths: Paths, out, now: datetime) -> int:
    if not schedule.in_window(cfg, now):
        return 0
    folder.ensure(paths)
    return schedule.tick(cfg, paths, now, lambda at, n: wake.run(cfg, paths, planned=at),
                         after_last=_post_piece(cfg, paths), out=out)


def cmd_wake(cfg, paths: Paths, args, out) -> int:
    if args.dry_run:
        return wake.dry_run(cfg, paths, out=out)
    if args.fake_model:
        if not args.studio_dir:
            root = tempfile.mkdtemp(prefix="studio-fake-")
            cfg = replace(cfg, studio_dir=root, kill_switch=os.path.join(root, "OFF"),
                          paper=replace(cfg.paper, dir=os.path.join(root, "for-the-paper")))
            paths = Paths.from_config(cfg)
            out(f"studio: fake-model folder {root}")
        cfg = replace(cfg, pulse=replace(cfg.pulse, min_seconds=1, max_seconds=1, song_seconds=1),
                      channel=replace(cfg.channel, chat_id=None, inbox_dir=None, post_command=None))
        folder.ensure(paths)
        with schedule.Lock(paths.lock) as lock:
            if not lock.acquired:
                out("studio: busy (another run holds the lock)")
                return 0
            o = wake.run(cfg, paths, session_factory=wake.fake_session_factory, fetch=None, collect_channel=False)
        out(f"studio: wake-up {o.n} ended ({o.reason}{', ' + o.detail if o.detail else ''}), {o.turns} turns, {o.usage.total()} tokens")
        return o.exit_code
    folder.ensure(paths)
    with schedule.Lock(paths.lock) as lock:
        if not lock.acquired:
            out("studio: busy (another run holds the lock)")
            return 0
        o = wake.run(cfg, paths)
    out(f"studio: wake-up {o.n} ended ({o.reason}{', ' + o.detail if o.detail else ''}), {o.turns} turns, {o.usage.total()} tokens")
    return o.exit_code


def cmd_plan(cfg, paths: Paths, night: Optional[str], out, now: datetime) -> int:
    night = night or schedule.night_of(cfg, now)
    plan = schedule.read_plan(paths, night)
    if plan is None:
        out(f"plan {night}: none yet")
        return 0
    zone = ZoneInfo(cfg.schedule.time_zone)
    out(f"plan {night} ({cfg.schedule.time_zone}):")
    if not plan["entries"]:
        out("  no wake-ups")
    for e in plan["entries"]:
        out(f"  {_hhmm(e.get('at'), zone)} {e.get('status', '?')}")
    return 0


def _flat(obj, prefix=""):
    if is_dataclass(obj):
        for f in fields(obj):
            yield from _flat(getattr(obj, f.name), f"{prefix}{f.name}.")
    else:
        yield prefix.rstrip("."), obj


def cmd_config_check(cfg, out) -> int:
    for key, value in _flat(cfg):
        if key in ("model.auth_token_cmd", "channel.post_command"):
            value = "set" if value else "unset"
        elif isinstance(value, tuple):
            value = json.dumps([dict(v) if hasattr(v, "keys") else v for v in value])
        elif value is None:
            value = "null"
        out(f"{key}: {value}")
    out("config: ok")
    return 0


def main(argv: Optional[Sequence[str]] = None, out=print, now: Optional[datetime] = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2
    try:
        cfg = _load(args)
    except config.ConfigError as e:
        sys.stderr.write(f"studio: config error: {e}\n")
        return 2
    paths = Paths.from_config(cfg)
    now = now or datetime.now(timezone.utc)
    if args.cmd == "status":
        return cmd_status(cfg, paths, out, now)
    if args.cmd == "tick":
        return cmd_tick(cfg, paths, out, now)
    if args.cmd == "wake":
        return cmd_wake(cfg, paths, args, out)
    if args.cmd == "measure":
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        bad = [k for k in kinds if k not in wake.MEASURE_KINDS]
        if bad or not kinds:
            sys.stderr.write(f"studio: --kinds takes {','.join(wake.MEASURE_KINDS)}\n")
            return 2
        return wake.measure(cfg, kinds, network=not args.no_network, keep=args.keep, out=out)
    if args.cmd == "off":
        limits.turn_off(paths, now)
        out("studio: off")
        return 0
    if args.cmd == "on":
        limits.turn_on(paths)
        out("studio: on")
        return 0
    if args.cmd == "journal":
        if args.jcmd != "tail":
            sys.stderr.write("studio: journal takes: tail [-n N]\n")
            return 2
        for entry in journal.tail(paths.journal, max(0, args.n)):
            out(entry)
            out("")
        return 0
    if args.cmd == "plan":
        if args.night:
            try:
                datetime.strptime(args.night, "%Y-%m-%d")
            except ValueError:
                sys.stderr.write("studio: --night takes YYYY-MM-DD\n")
                return 2
        return cmd_plan(cfg, paths, args.night, out, now)
    if args.cmd == "config":
        if args.ccmd != "check":
            sys.stderr.write("studio: config takes: check\n")
            return 2
        return cmd_config_check(cfg, out)
    parser.print_usage(sys.stderr)
    return 2
