"""Load, default and validate the studio config file (one JSON file).

The path comes from --config, else env STUDIO_CONFIG, else ~/.config/studio/config.json.
Env STUDIO_DIR overrides studio_dir. Unknown keys and wrong types are errors.
A ConfigError names the key, never the value.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping as _MappingABC
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

DEFAULT_PATH = "~/.config/studio/config.json"
VERB_NAMES = ("window", "sun", "temperature", "journal", "write", "song", "read", "paper", "nothing", "sleep")
TOKEN_ENVS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


class ConfigError(Exception):
    """The config file is missing, broken or holds a bad key. The message names the key only."""


class Entry(_MappingABC):
    """A read-only record from a list in the config. Works as entry.key and entry["key"]."""

    __slots__ = ("_d",)

    def __init__(self, d: dict):
        object.__setattr__(self, "_d", dict(d))

    def __getitem__(self, k):
        return self._d[k]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)

    def __getattr__(self, k):
        try:
            return self._d[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        raise AttributeError("Entry is read-only")

    def __repr__(self):
        return f"Entry({self._d!r})"

    def __eq__(self, other):
        if isinstance(other, Entry):
            return self._d == other._d
        if isinstance(other, dict):
            return self._d == other
        return NotImplemented

    def __hash__(self):
        return hash(tuple(sorted((k, repr(v)) for k, v in self._d.items())))


@dataclass(frozen=True)
class Names:
    agent: str
    person: str


@dataclass(frozen=True)
class Town:
    name: Optional[str]
    latitude: float
    longitude: float
    time_zone: str


@dataclass(frozen=True)
class Schedule:
    time_zone: str
    window_start: str
    window_end: str
    end_by: str
    count: int
    min_gap_minutes: int


@dataclass(frozen=True)
class Limits:
    wall_seconds: int
    min_seconds: int
    max_turns: int
    turn_timeout_seconds: int
    max_answer_chars: int
    wakeup_tokens: int
    daily_tokens: int


@dataclass(frozen=True)
class Pulse:
    min_seconds: int
    max_seconds: int
    song_seconds: int
    quiet_chance: float


@dataclass(frozen=True)
class Identity:
    path: Optional[str]
    start: str
    end: str
    max_chars: int


@dataclass(frozen=True)
class Model:
    command: tuple
    name: str
    auth_token_cmd: Optional[tuple]
    auth_token_env: str


@dataclass(frozen=True)
class Senses:
    sky: bool
    body: bool
    house: bool
    song: bool


@dataclass(frozen=True)
class Weather:
    enabled: bool
    cache_minutes: int


@dataclass(frozen=True)
class Body:
    sys_root: str
    temps: tuple
    disk: Optional[str]


@dataclass(frozen=True)
class House:
    signals: tuple


@dataclass(frozen=True)
class Verbs:
    window: bool
    sun: bool
    temperature: bool
    journal: bool
    write: bool
    song: bool
    read: bool
    paper: bool
    nothing: bool
    sleep: bool


@dataclass(frozen=True)
class Reading:
    start_date: Optional[str]
    sources: tuple
    max_chars: int


@dataclass(frozen=True)
class Channel:
    chat_id: Optional[int]
    allowed_sender_id: Optional[int]
    inbox_dir: Optional[str]
    post_command: Optional[tuple]
    post_piece: bool


@dataclass(frozen=True)
class Paper:
    enabled: bool
    dir: str


@dataclass(frozen=True)
class Journal:
    max_line_chars: int
    max_lines_per_wakeup: int
    tail_entries: int


@dataclass(frozen=True)
class Transcripts:
    keep_days: int


@dataclass(frozen=True)
class Config:
    version: int
    studio_dir: str
    kill_switch: str
    names: Names
    town: Town
    schedule: Schedule
    limits: Limits
    pulse: Pulse
    identity: Identity
    model: Model
    senses: Senses
    weather: Weather
    body: Body
    house: House
    verbs: Verbs
    reading: Reading
    channel: Channel
    paper: Paper
    journal: Journal
    transcripts: Transcripts
    source_path: Optional[str]


_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTTPS = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s]*)?$")
_MISSING = object()


def hhmm_minutes(s: str) -> int:
    """Minutes after midnight for an "HH:MM" string."""
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _safe_key(k: Any) -> str:
    s = str(k)
    s = re.sub(r"[^A-Za-z0-9_.-]", "?", s)[:60]
    return s or "?"


class _Section:
    """Reads one JSON object, checks each key, remembers which keys were used."""

    def __init__(self, data: Any, prefix: str, ctx: "_Load"):
        if data is _MISSING or data is None and prefix:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"wrong type for {prefix.rstrip('.') or 'the config'} (expected an object)")
        self.data = data
        self.prefix = prefix
        self.ctx = ctx
        self.seen: set = set()

    def key(self, k: str) -> str:
        return self.prefix + k

    def raw(self, k: str):
        self.seen.add(k)
        return self.data.get(k, _MISSING)

    def done(self):
        for k in self.data:
            if k not in self.seen:
                raise ConfigError(f"unknown key {self.prefix}{_safe_key(k)}")

    def sub(self, k: str) -> "_Section":
        v = self.raw(k)
        if v is _MISSING:
            v = {}
        if not isinstance(v, dict):
            raise ConfigError(f"wrong type for {self.key(k)} (expected an object)")
        return _Section(v, self.key(k) + ".", self.ctx)

    def _bad(self, k, what):
        return ConfigError(f"wrong type for {self.key(k)} (expected {what})")

    def int_(self, k, default, lo=None, hi=None):
        v = self.raw(k)
        if v is _MISSING:
            return default
        if not isinstance(v, int) or isinstance(v, bool):
            raise self._bad(k, "an integer")
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            raise ConfigError(f"out of range: {self.key(k)} (allowed {lo}..{hi})")
        return v

    def nint(self, k, default=None):
        v = self.raw(k)
        if v is _MISSING or v is None:
            return default
        if not isinstance(v, int) or isinstance(v, bool):
            raise self._bad(k, "an integer or null")
        return v

    def float_(self, k, default, lo=None, hi=None):
        v = self.raw(k)
        if v is _MISSING:
            return default
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise self._bad(k, "a number")
        v = float(v)
        if v != v or (lo is not None and v < lo) or (hi is not None and v > hi):
            raise ConfigError(f"out of range: {self.key(k)} (allowed {lo}..{hi})")
        return v

    def bool_(self, k, default):
        v = self.raw(k)
        if v is _MISSING:
            return default
        if not isinstance(v, bool):
            raise self._bad(k, "true or false")
        return v

    def str_(self, k, default, nullable=False, nonempty=True, choices=None):
        v = self.raw(k)
        if v is _MISSING:
            return default
        if v is None and nullable:
            return None
        if not isinstance(v, str) or (nonempty and not v.strip()):
            raise self._bad(k, "a string" + (" or null" if nullable else ""))
        if choices is not None and v not in choices:
            raise ConfigError(f"not allowed: {self.key(k)} (allowed: {', '.join(choices)})")
        return v

    def path(self, k, default, nullable=False):
        v = self.str_(k, default, nullable=nullable)
        if v is None:
            return None
        return self.ctx.expand(v)

    def hhmm(self, k, default, nullable=False):
        v = self.str_(k, default, nullable=nullable)
        if v is None:
            return None
        if not _HHMM.match(v):
            raise self._bad(k, '"HH:MM"')
        return v

    def tz(self, k, default):
        v = self.str_(k, default)
        try:
            ZoneInfo(v)
        except Exception:
            raise ConfigError(f"unknown time zone in {self.key(k)}") from None
        return v

    def strlist(self, k, default, nullable=False):
        v = self.raw(k)
        if v is _MISSING:
            return default
        if v is None and nullable:
            return None
        if (not isinstance(v, list) or not v
                or not all(isinstance(x, str) and x for x in v)):
            raise self._bad(k, "a non-empty list of strings" + (" or null" if nullable else ""))
        return tuple(v)

    def objlist(self, k):
        v = self.raw(k)
        if v is _MISSING:
            return []
        if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
            raise self._bad(k, "a list of objects")
        return v


class _Load:
    def __init__(self, env: Mapping[str, str], base_dir: str):
        self.env = env
        self.base_dir = base_dir

    def home(self) -> str:
        return self.env.get("HOME") or os.path.expanduser("~")

    def expand(self, p: str) -> str:
        if p == "~" or p.startswith("~/"):
            p = self.home() + p[1:]
        if not os.path.isabs(p):
            p = os.path.join(self.base_dir, p)
        return os.path.normpath(p)


def _entries(sec: _Section, k: str, fields: dict, item_name: str) -> list:
    """Check each object in a list: exactly the given keys, each a non-empty string."""
    out = []
    for i, item in enumerate(sec.objlist(k)):
        where = f"{sec.key(k)}[{i}]"
        for key in item:
            if key not in fields:
                raise ConfigError(f"unknown key {where}.{_safe_key(key)}")
        for key, required in fields.items():
            if key not in item:
                if required:
                    raise ConfigError(f"missing key {where}.{key}")
                continue
            if not isinstance(item[key], str) or not item[key].strip():
                raise ConfigError(f"wrong type for {where}.{key} (expected a string)")
        out.append(item)
    return out


def load(path: Optional[str] = None, env: Mapping[str, str] = os.environ) -> Config:
    """Load the config. A missing file at the default path gives all defaults."""
    explicit = path or env.get("STUDIO_CONFIG") or None
    ctx0 = _Load(env, os.getcwd())
    file_path = ctx0.expand(explicit or DEFAULT_PATH)
    data: Any = {}
    source: Optional[str] = None
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeDecodeError):
            raise ConfigError("cannot read the config file") from None
        except json.JSONDecodeError as e:
            raise ConfigError(f"the config file is not valid JSON (line {e.lineno})") from None
        source = file_path
    elif explicit:
        raise ConfigError("the config file does not exist")
    ctx = _Load(env, os.path.dirname(file_path))
    top = _Section(data, "", ctx)

    version = top.int_("version", 1)
    if version != 1:
        raise ConfigError("not allowed: version (must be 1)")
    studio_dir = top.path("studio_dir", "~/studio")
    if env.get("STUDIO_DIR"):
        studio_dir = ctx.expand(env["STUDIO_DIR"])
    kill_switch = top.path("kill_switch", None, nullable=True) or os.path.join(studio_dir, "OFF")

    s = top.sub("names")
    names = Names(s.str_("agent", "the agent"), s.str_("person", "the person"))
    s.done()

    s = top.sub("town")
    town = Town(s.str_("name", None, nullable=True), s.float_("latitude", 0.0, -90, 90),
                s.float_("longitude", 0.0, -180, 180), s.tz("time_zone", "UTC"))
    s.done()

    s = top.sub("schedule")
    tz = s.tz("time_zone", "UTC")
    ws = s.hhmm("window_start", "02:00")
    we = s.hhmm("window_end", "06:00")
    eb = s.hhmm("end_by", None, nullable=True) or we
    schedule = Schedule(tz, ws, we, eb, s.int_("count", 3, 0, 6), s.int_("min_gap_minutes", 30, 0, 1440))
    s.done()
    if not hhmm_minutes(ws) < hhmm_minutes(eb) <= hhmm_minutes(we):
        raise ConfigError("schedule.end_by must be after schedule.window_start and not after schedule.window_end")

    s = top.sub("limits")
    limits = Limits(s.int_("wall_seconds", 300, 30, 900), s.int_("min_seconds", 120, 1, 900),
                    s.int_("max_turns", 12, 1, 40), s.int_("turn_timeout_seconds", 90, 1, 900),
                    s.int_("max_answer_chars", 1200, 1, 100000), s.int_("wakeup_tokens", 150000, 0),
                    s.int_("daily_tokens", 400000, 0))
    s.done()
    if limits.min_seconds > limits.wall_seconds:
        raise ConfigError("limits.min_seconds must not be more than limits.wall_seconds")

    s = top.sub("pulse")
    pulse = Pulse(s.int_("min_seconds", 20, 0, 3600), s.int_("max_seconds", 60, 0, 3600),
                  s.int_("song_seconds", 15, 0, 3600), s.float_("quiet_chance", 0.6, 0.0, 1.0))
    s.done()
    if pulse.min_seconds > pulse.max_seconds:
        raise ConfigError("pulse.min_seconds must not be more than pulse.max_seconds")

    s = top.sub("identity")
    identity = Identity(s.path("path", None, nullable=True), s.str_("start", "### 1. "),
                        s.str_("end", "### 2. "), s.int_("max_chars", 12000, 1))
    s.done()

    s = top.sub("model")
    model = Model(s.strlist("command", ("claude",)), s.str_("name", "opus"),
                  s.strlist("auth_token_cmd", None, nullable=True),
                  s.str_("auth_token_env", "CLAUDE_CODE_OAUTH_TOKEN", choices=TOKEN_ENVS))
    s.done()

    s = top.sub("senses")
    senses = Senses(s.bool_("sky", True), s.bool_("body", True), s.bool_("house", True), s.bool_("song", True))
    s.done()

    s = top.sub("weather")
    weather = Weather(s.bool_("enabled", True), s.int_("cache_minutes", 30, 0))
    s.done()

    s = top.sub("body")
    temps = tuple(Entry(t) for t in _entries(s, "temps", {"hwmon": True, "label": True}, "temp"))
    body = Body(s.path("sys_root", "/"), temps, s.str_("disk", None, nullable=True))
    s.done()

    s = top.sub("house")
    signals = []
    for i, item in enumerate(s.objlist("signals")):
        where = f"house.signals[{i}]"
        kind = item.get("kind")
        if kind == "unit":
            fields = ("kind", "unit", "running", "finished")
        elif kind == "file":
            fields = ("kind", "path", "changed")
        else:
            raise ConfigError(f"not allowed: {where}.kind (allowed: unit, file)")
        for key in item:
            if key not in fields:
                raise ConfigError(f"unknown key {where}.{_safe_key(key)}")
        for key in fields:
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ConfigError(f"wrong type for {where}.{key} (expected a string)")
        full = {"kind": kind, "unit": None, "running": None, "finished": None, "path": None, "changed": None}
        full.update(item)
        if kind == "file":
            full["path"] = ctx.expand(item["path"])
        signals.append(Entry(full))
    house = House(tuple(signals))
    s.done()

    s = top.sub("verbs")
    verbs = Verbs(*(s.bool_(n, True) for n in VERB_NAMES))
    s.done()

    s = top.sub("reading")
    start_date = s.str_("start_date", None, nullable=True)
    if start_date is not None:
        try:
            if not _DATE.match(start_date):
                raise ValueError
            date.fromisoformat(start_date)
        except ValueError:
            raise ConfigError('wrong type for reading.start_date (expected "YYYY-MM-DD" or null)') from None
    sources = []
    for i, item in enumerate(s.objlist("sources")):
        where = f"reading.sources[{i}]"
        for key in item:
            if key not in ("name", "kind", "url"):
                raise ConfigError(f"unknown key {where}.{_safe_key(key)}")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ConfigError(f"wrong type for {where}.name (expected a string)")
        kind = item.get("kind")
        if kind not in ("rss", "atom", "shelf"):
            raise ConfigError(f"not allowed: {where}.kind (allowed: rss, atom, shelf)")
        url = item.get("url", "")
        if not isinstance(url, str):
            raise ConfigError(f"wrong type for {where}.url (expected a string)")
        if kind != "shelf" and not _HTTPS.match(url):
            raise ConfigError(f"not allowed: {where}.url (https only)")
        sources.append(Entry({"name": item["name"], "kind": kind, "url": url}))
    reading = Reading(start_date, tuple(sources), s.int_("max_chars", 4000, 1, 100000))
    s.done()

    s = top.sub("channel")
    channel = Channel(s.nint("chat_id"), s.nint("allowed_sender_id"), s.path("inbox_dir", None, nullable=True),
                      s.strlist("post_command", None, nullable=True), s.bool_("post_piece", False))
    s.done()

    s = top.sub("paper")
    paper = Paper(s.bool_("enabled", True),
                  s.path("dir", None, nullable=True) or os.path.join(studio_dir, "for-the-paper"))
    s.done()

    s = top.sub("journal")
    journal = Journal(s.int_("max_line_chars", 280, 1, 2000), s.int_("max_lines_per_wakeup", 3, 0, 40),
                      s.int_("tail_entries", 5, 1, 100))
    s.done()

    s = top.sub("transcripts")
    transcripts = Transcripts(s.int_("keep_days", 14, 0, 3650))
    s.done()

    top.done()
    return Config(version, studio_dir, kill_switch, names, town, schedule, limits, pulse, identity, model,
                  senses, weather, body, house, verbs, reading, channel, paper, journal, transcripts, source)
