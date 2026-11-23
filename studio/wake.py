"""The wake-up loop: wake the model with no task, send pulses, do the verbs it reaches for, write what happened.

Also the dry run (prints, writes nothing) and the measure runs (real model, temp folders).
"""
from __future__ import annotations

import json
import os
import random
import shutil
import signal
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from . import folder, journal, limits, pulse, schedule, wire
from .folder import Paths
from .model import FakeSession, ModelStartError, TokenError, open_session
from .types import Context, ModelReply, Usage, VerbResult

FAILURES = {"model-timeout", "model-exit", "model-error", "model-start", "unsafe", "no-identity", "no-token",
            "error"}
STATUS_REASON = {"timeout": "model-timeout", "exit": "model-exit", "error": "model-error",
                 "unsafe": "unsafe", "off": "off", "deadline": "time"}
ENGINE_VERBS = ("journal", "write", "paper", "nothing", "sleep")
_DEFAULT = object()

FAKE_SCRIPT = [".", "do: window", "the wind again.", "do: write the wind came up twice.",
               "do: paper It was windy.", "do: sleep"]

MEASURE_KINDS = ("quiet", "song", "journal", "busy")
MEASURE_JOURNAL = [
    ("2027-01-04 09:12", ["looked out the window"], ["grey all morning, the gulls loud."]),
    ("2027-01-04 10:40", [], []),
    ("2027-01-05 09:55", ["put the song on"], ["the song ended before I knew it."]),
    ("2027-01-06 09:03", ["felt the sun", "checked my temperature"], []),
    ("2027-01-06 11:20", [], ["the fan ran a long time tonight."]),
]


@dataclass
class Outcome:
    reason: str
    turns: int = 0
    usage: Usage = field(default_factory=Usage)
    exit_code: int = 0
    n: int = 0
    started_model: bool = False
    cost_usd: Optional[float] = None
    seconds: float = 0.0
    detail: Optional[str] = None


class _Terminated(Exception):
    pass


def exit_code_for(reason: str) -> int:
    if reason == "terminated":
        return 143
    return 1 if reason in FAILURES else 0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- identity ---------------------------------------------------------------------------------

def load_identity(cfg) -> tuple:
    """(text, "") for the identity section from config, else (None, why). The text is never logged."""
    ident = cfg.identity
    if not ident.path:
        return None, "no identity path"
    try:
        with open(ident.path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError):
        return None, "identity file unreadable"
    out, inside, ended = [], False, False
    for line in lines:
        if not inside:
            if line.startswith(ident.start):
                inside = True
                out.append(line)
            continue
        if line.startswith(ident.end):
            ended = True
            break
        out.append(line)
    if not inside or not ended:
        return None, "identity markers missing"
    text = "\n".join(out).strip()
    if not text:
        return None, "identity section empty"
    if len(text) > ident.max_chars:
        return None, "identity section too long"
    return text, ""


# ---- small file helpers -----------------------------------------------------------------------

def _wakeup_lines(paths: Paths) -> list:
    try:
        with open(paths.wakeups, encoding="utf-8") as f:
            raw = f.read().splitlines()
    except OSError:
        return []
    out = []
    for ln in raw:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def last_wakeup(paths: Paths) -> Optional[dict]:
    lines = _wakeup_lines(paths)
    return lines[-1] if lines else None


def _prune_transcripts(paths: Paths, keep_days: int, today: date) -> None:
    try:
        names = os.listdir(paths.transcripts)
    except OSError:
        return
    cutoff = today - timedelta(days=keep_days)
    for name in names:
        try:
            d = date.fromisoformat(name[:10])
        except ValueError:
            continue
        if d < cutoff:
            try:
                os.unlink(os.path.join(paths.transcripts, name))
            except OSError:
                pass


def sweep_cli_config(paths: Paths, keep_pid: Optional[int] = None) -> int:
    """Remove per-run CLI config folders left by a run that was killed (SIGKILL, OOM, power loss).

    Called while holding the lock, so no other wake-up of this studio is running: every
    state/cli-config-<pid>-<n> folder that is not this process's own is stale."""
    keep_pid = os.getpid() if keep_pid is None else keep_pid
    try:
        names = os.listdir(paths.state)
    except OSError:
        return 0
    gone = 0
    for name in names:
        if not name.startswith("cli-config-"):
            continue
        bits = name.split("-")
        if len(bits) == 4 and bits[2] == str(keep_pid):
            continue
        full = os.path.join(paths.state, name)
        if os.path.islink(full) or not os.path.isdir(full):
            continue
        shutil.rmtree(full, ignore_errors=True)
        gone += 1
    return gone


def _after_end_by(cfg, night: str, t: datetime) -> bool:
    """True between end_by and window_end of the night: a hand-run wake-up then would share the
    machine with the jobs that follow the window, so it is refused."""
    _start, end_by = schedule.window(cfg, night)
    window_end = (datetime.combine(date.fromisoformat(night), datetime.min.time(), schedule.tz(cfg))
                  + timedelta(minutes=schedule.hhmm_minutes(cfg.schedule.window_end)))
    return end_by <= t < window_end


# ---- senses and verbs -------------------------------------------------------------------------

def _senses_module():
    from . import senses as senses_mod  # SENSES owns it; imported late so the engine loads alone
    return senses_mod


def collect_verbs(cfg, sense_verbs: Sequence) -> list:
    """Engine verbs plus sense verbs. The engine's names cannot be taken by a sense verb."""
    out = list(journal.engine_verbs(cfg))
    for v in sense_verbs:
        if v.name not in ENGINE_VERBS:
            out.append(v)
    return wire.ordered_verbs(out)


def _default_fetch():
    from . import fetch as fetch_mod
    return fetch_mod.fetch_text


# ---- the loop ---------------------------------------------------------------------------------

def run(cfg, paths: Paths, *, planned: Optional[datetime] = None,
        now: Optional[Callable[[], datetime]] = None, sleep: Optional[Callable[[float], None]] = None,
        rng: Optional[random.Random] = None, senses=None, verbs=None,
        session_factory: Optional[Callable[[str], object]] = None, fetch=_DEFAULT,
        ledger: bool = True, all_changed: bool = False, first_pulse_extra: Sequence[str] = (),
        collect_channel: bool = True, install_signals: bool = True) -> Outcome:
    """One wake-up. The caller holds the lock. Returns what happened (counts only)."""
    now = now or utcnow
    sleep = sleep or time.sleep
    rng = rng or random.Random(os.urandom(16))
    t0 = time.monotonic()
    started = now()
    night = schedule.night_of(cfg, planned or started)
    folder.ensure(paths)
    sweep_cli_config(paths)
    n = sum(1 for d in _wakeup_lines(paths) if d.get("night") == night) + 1

    def log_line(reason, turns=0, usage=Usage(), verbs_used=(), lines=0, piece=False, detail=None):
        rec = {"night": night, "n": n, "planned": planned.isoformat(timespec="seconds") if planned else None,
               "started": started.isoformat(timespec="seconds"), "reason": reason, "turns": turns,
               "usage": usage.as_dict(), "verbs": list(verbs_used), "lines": lines, "piece": piece}
        if detail:
            rec["detail"] = detail
        folder.append_private(paths.wakeups, json.dumps(rec) + "\n")

    def skip(reason):
        log_line(reason)
        return Outcome(reason, exit_code=exit_code_for(reason), n=n, seconds=time.monotonic() - t0)

    if limits.switch_off(paths):
        return skip("off")
    if planned is None and _after_end_by(cfg, night, started):
        return skip("late")
    night_before = limits.night_total(paths, night) if ledger else 0
    if ledger and night_before >= cfg.limits.daily_tokens:
        return skip("allowance")
    identity, _why = load_identity(cfg)
    if identity is None:
        return skip("no-identity")

    if fetch is _DEFAULT:
        fetch = _default_fetch()
    ctx = Context(cfg=cfg, paths=paths, now=now, rng=rng, memory={}, fetch=fetch, dry=False)
    if senses is None or verbs is None:
        smod = _senses_module()
        if senses is None:
            senses = smod.providers(cfg)
        if verbs is None:
            verbs = smod.verbs(cfg)
    if collect_channel:
        try:
            from . import channel as channel_mod
            if channel_mod.enabled(cfg):
                channel_mod.collect(ctx)
        except Exception:
            pass
    verb_list = collect_verbs(cfg, verbs)
    verb_map = {v.name: v for v in verb_list}
    prompt = wire.system_prompt(cfg, identity, verb_list)
    del identity

    hard_end = started + timedelta(seconds=cfg.limits.wall_seconds)
    win_start, win_end = schedule.window(cfg, night)
    if planned is not None or win_start <= started < win_end:
        # A hand-run wake-up inside the night window keeps the same end, so it never runs into
        # the jobs that follow the window.
        hard_end = min(hard_end, win_end)
    length = rng.uniform(cfg.limits.min_seconds, cfg.limits.wall_seconds)
    planned_end = min(started + timedelta(seconds=length), hard_end)
    caps = limits.WakeCaps(cfg.limits, planned_end, hard_end, night_before, ledger=ledger)
    town_now = started.astimezone(ZoneInfo(cfg.town.time_zone))
    clock = town_now.strftime("%H:%M")
    heading = town_now.strftime("%Y-%m-%d %H:%M")

    if session_factory is None:
        def session_factory(sp):
            return open_session(cfg, paths.cwd, sp, paths.state)

    happenings: list = []
    verbs_used: list = []
    transcript: list = []
    reason: Optional[str] = None
    detail: Optional[str] = None
    session = None
    song_on = False
    max_answer = cfg.limits.max_answer_chars

    def send_stop():
        if limits.switch_off(paths):
            return "off"
        if now() >= hard_end:
            return "deadline"
        return None

    def wait_stop():
        if limits.switch_off(paths):
            return "off"
        t = now()
        if t >= planned_end or t >= hard_end:
            return "time"
        return None

    old_handlers = {}

    def on_signal(signum, frame):
        raise _Terminated()

    def quiet_signal(signum, frame):
        pass

    use_signals = install_signals and threading.current_thread() is threading.main_thread()
    if use_signals:
        for sig in (signal.SIGTERM, signal.SIGINT):
            old_handlers[sig] = signal.signal(sig, on_signal)
    try:
        try:
            try:
                session = session_factory(prompt)
            except TokenError:
                reason = "no-token"
            except ModelStartError:
                reason = "model-start"
            if session is not None:
                message = wire.wake_message(clock, pulse.gather(ctx, senses))
                first_pulse = True
                while True:
                    reason = caps.check(now(), limits.switch_off(paths))
                    if reason:
                        break
                    caps.turns += 1
                    transcript.append({"from": "script", "text": message})
                    reply = session.send(message, cfg.limits.turn_timeout_seconds, send_stop)
                    if not isinstance(reply, ModelReply):
                        reply = ModelReply("error")
                    caps.add(reply.usage, reply.estimated, reply.cost_usd)
                    if reply.status != "ok":
                        reason = STATUS_REASON.get(reply.status, "model-error")
                        detail = reply.detail if reply.detail in ("auth",) else None
                        break
                    text = (reply.text or "")[:max_answer]
                    transcript.append({"from": "agent", "text": text})
                    ans = wire.parse_answer(text, verb_map.keys())
                    if ans.kind == "verb":
                        spec = verb_map.get(ans.verb)
                        if spec is None:
                            verbs_used.append("unknown")
                            message = wire.unknown_message(ans.verb)
                            continue
                        verbs_used.append(spec.name)
                        if spec.name == "sleep":
                            reason = "slept"
                            break
                        try:
                            res = spec.handler(ctx, ans.arg)
                            if not isinstance(res, VerbResult):
                                raise TypeError("not a VerbResult")
                        except Exception:
                            message = wire.failed_message(spec.name)
                            continue
                        if res.happened:
                            happenings.append(res.happened)
                        if res.end_wakeup:
                            reason = "slept"
                            break
                        if spec.name == "song":
                            song_on = True
                        message = wire.result_message(spec.name, res.text[:5000])
                        continue
                    word = pulse.wait(pulse.next_gap(cfg, rng, song_on), now, sleep, wait_stop)
                    if word:
                        reason = word
                        break
                    readings = pulse.gather(ctx, senses)
                    song_on = pulse.song_playing(readings)
                    extra = first_pulse_extra if first_pulse else ()
                    first_pulse = False
                    message = pulse.pulse_text(readings, rng, cfg.pulse.quiet_chance, all_changed, extra)
        except _Terminated:
            reason = "terminated"
        except Exception:
            # A bug or an OSError inside the loop must not skip _finish: the turns already paid
            # for still go into the ledger, and the night still gets its log line.
            reason = "error"
        finally:
            if use_signals:
                for sig in old_handlers:
                    signal.signal(sig, quiet_signal)
            if session is not None:
                session.close()
        return _finish(cfg, paths, night, n, planned, started, now, reason or "done", caps, session is not None,
                       happenings, ctx, verbs_used, transcript, heading, ledger, t0, log_line, detail)
    finally:
        if use_signals:
            for sig, h in old_handlers.items():
                signal.signal(sig, h)


def _finish(cfg, paths, night, n, planned, started, now, reason, caps, started_model, happenings, ctx,
            verbs_used, transcript, heading, ledger, t0, log_line, detail=None) -> Outcome:
    """Write what happened. Each write fails alone, so the ledger and the log line always get written."""
    book = ctx.memory.get("journal", {"lines": [], "piece": None})
    if not isinstance(book, dict):
        book = {"lines": [], "piece": None}
    lines = [x for x in book.get("lines", []) if isinstance(x, str)]
    piece = book.get("piece") if isinstance(book.get("piece"), str) else None
    failed: list = []

    def step(name, fn):
        try:
            fn()
        except Exception:
            failed.append(name)

    if started_model:
        start = reason.startswith("model-") or reason in ("unsafe", "error")
        step("journal", lambda: journal.append_entry(paths, journal.format_entry(heading, happenings, lines, start)))
        if cfg.paper.enabled:
            # A wake-up that ended by an error is not "sitting": it keeps the night from printing as quiet.
            step("paper", lambda: journal.write_paper(paths, night, piece, bool(happenings or lines or start),
                                                      now().astimezone(ZoneInfo(cfg.schedule.time_zone))))
        if cfg.transcripts.keep_days > 0 and transcript:
            def keep_transcript():
                folder.write_private(os.path.join(paths.transcripts, f"{night}-{n}.json"),
                                     json.dumps({"night": night, "n": n, "messages": transcript},
                                                ensure_ascii=False, indent=1) + "\n")
                _prune_transcripts(paths, cfg.transcripts.keep_days, date.fromisoformat(night))
            step("transcript", keep_transcript)
    if ledger:
        step("ledger", lambda: limits.record(paths, night, caps.usage, caps.cost_usd, caps.estimated_turns,
                                             started_model))
    if failed and not detail:
        detail = "write-failed:" + ",".join(failed)
    if failed and reason not in FAILURES and reason != "terminated":
        reason = "error"
    try:
        log_line(reason, caps.turns, caps.usage, verbs_used, len(lines), piece is not None, detail)
    except Exception:
        pass
    return Outcome(reason, caps.turns, caps.usage, exit_code_for(reason), n, started_model, caps.cost_usd,
                   time.monotonic() - t0, detail)


# ---- dry run ----------------------------------------------------------------------------------

def dry_run(cfg, paths: Paths, out=print, now: Optional[Callable[[], datetime]] = None,
            rng: Optional[random.Random] = None, senses=None, verbs=None) -> int:
    """Print the system prompt (identity replaced), the WAKE message and three pulses. Writes nothing."""
    now = now or utcnow
    rng = rng or random.Random(os.urandom(16))
    identity, why = load_identity(cfg)
    ctx = Context(cfg=cfg, paths=paths, now=now, rng=rng, memory={}, fetch=None, dry=True)
    if senses is None or verbs is None:
        smod = _senses_module()
        senses = smod.providers(cfg) if senses is None else senses
        verbs = smod.verbs(cfg) if verbs is None else verbs
    verb_list = collect_verbs(cfg, verbs)
    if identity is None:
        ident_note = f"[identity: missing ({why}); a real wake-up would not start]"
        prompt = wire.system_prompt(cfg, ident_note, verb_list)
    else:
        prompt = wire.dry_system_prompt(cfg, len(identity), cfg.identity.path, verb_list)
    del identity
    out("--- system prompt ---")
    out(prompt)
    clock = now().astimezone(ZoneInfo(cfg.town.time_zone)).strftime("%H:%M")
    out("--- message 1 ---")
    out(wire.wake_message(clock, pulse.gather(ctx, senses)))
    for i in range(3):
        out(f"--- message {i + 2} ---")
        out(pulse.pulse_text(pulse.gather(ctx, senses), rng, cfg.pulse.quiet_chance))
    return 0


# ---- measure ----------------------------------------------------------------------------------

def measure_config(cfg, root: str):
    """The config for one measure run: a temp folder, short limits, no channel. The kill switch stays."""
    return replace(
        cfg, studio_dir=root,
        paper=replace(cfg.paper, dir=os.path.join(root, "for-the-paper")),
        limits=replace(cfg.limits, wall_seconds=120, min_seconds=120, max_turns=6, wakeup_tokens=60000),
        pulse=replace(cfg.pulse, min_seconds=15, max_seconds=25),
        channel=replace(cfg.channel, chat_id=None, inbox_dir=None, post_command=None, post_piece=False),
        house=cfg.house)


def _measure_song_text() -> str:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "measure_song.txt"), encoding="utf-8") as f:
        return f.read()


def measure(cfg, kinds: Sequence[str], network: bool = True, keep: bool = False, out=print,
            session_factory_for: Optional[Callable] = None, senses=None, verbs=None) -> int:
    """Real model, at most 4 runs (one per kind), each in a fresh temp folder. Prints counts only."""
    kinds = [k for i, k in enumerate(kinds) if k in MEASURE_KINDS and k not in kinds[:i]][:4]
    identity, why = load_identity(cfg)
    if identity is None:
        out(f"identity: missing ({why})")
        return 1
    ident_chars = len(identity)
    del identity
    total = Usage()
    total_cost = 0.0
    turns = 0
    code = 0
    for kind in kinds:
        root = tempfile.mkdtemp(prefix="studio-measure-")
        try:
            mcfg = measure_config(cfg, root)
            paths = Paths.from_config(mcfg)
            folder.ensure(paths)
            extra: Sequence[str] = ()
            if kind == "song":
                folder.write_private(os.path.join(paths.jukebox, "measure-song.txt"), _measure_song_text())
                extra = ("song: a song is waiting in the jukebox.",)
            elif kind == "journal":
                for heading, happened, lines in MEASURE_JOURNAL:
                    journal.append_entry(paths, journal.format_entry(heading, happened, lines))
            factory = session_factory_for(mcfg, paths) if session_factory_for else None
            o = run(mcfg, paths, ledger=False, all_changed=(kind == "busy"), first_pulse_extra=extra,
                    fetch=_DEFAULT if network else None, collect_channel=False, session_factory=factory,
                    senses=senses, verbs=verbs)
            u = o.usage
            cost = f"{o.cost_usd:.4f}" if o.cost_usd is not None else "?"
            out(f"{kind}: {o.turns} turns, {o.seconds:.0f} s, ended: {o.reason}, tokens in "
                f"{u.input + u.cache_creation + u.cache_read} (plain {u.input}, cache write {u.cache_creation}, "
                f"cache read {u.cache_read}) out {u.output}, cost ${cost}")
            if keep:
                out(f"{kind}: folder kept at {root}")
            total = total + u
            total_cost += o.cost_usd or 0.0
            turns += o.turns
            if o.exit_code != 0:
                code = 1
        finally:
            if not keep:
                shutil.rmtree(root, ignore_errors=True)
    out(f"total: {len(kinds)} runs, {turns} turns, tokens in {total.input + total.cache_creation + total.cache_read} "
        f"out {total.output}, all counts {total.total()}, cost ${total_cost:.4f}")
    out(f"identity: {ident_chars} characters")
    return code


# ---- fake model -------------------------------------------------------------------------------

def fake_session_factory(sp: str) -> FakeSession:
    return FakeSession(FAKE_SCRIPT)
