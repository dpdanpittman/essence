"""Shared types for the engine and the senses. This is a frozen interface."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Literal, Optional, Protocol, Sequence

if TYPE_CHECKING:  # only for type checkers; no import cycle at run time
    from .config import Config
    from .folder import Paths


@dataclass(frozen=True)
class SenseReading:
    sense: str            # "sky" | "body" | "house" | "song"
    text: str             # plain, one line, <= 160 chars (song: up to 12 lines, <= 1200 chars)
    changed: bool         # noticeably different from this sense's last reading in this wake-up


@dataclass(frozen=True)
class VerbResult:
    text: str             # plain, <= 600 chars (read: <= reading.max_chars; journal: <= 1500)
    happened: str = ""    # fixed phrase for the journal happenings line, "" for none
    end_wakeup: bool = False


@dataclass(frozen=True)
class VerbSpec:
    name: str             # [a-z]{2,12}
    says: str             # one line for the system prompt
    takes_text: bool
    handler: Callable[["Context", str], VerbResult]   # must not raise; the engine catches anyway


@dataclass
class Context:
    cfg: "Config"
    paths: "Paths"
    now: Callable[[], datetime]          # aware UTC
    rng: random.Random
    memory: dict = field(default_factory=dict)   # per wake-up scratch, keyed by module name
    fetch: Optional[Callable[[str, Sequence[str]], str]] = None   # fetch.fetch_text, or None
    dry: bool = False                    # True: never write anything


class Sense(Protocol):
    name: str

    def read(self, ctx: Context) -> Optional[SenseReading]: ...


@dataclass(frozen=True)
class Usage:
    input: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    output: int = 0

    def total(self) -> int:
        return self.input + self.cache_creation + self.cache_read + self.output

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input + other.input,
                     self.cache_creation + other.cache_creation,
                     self.cache_read + other.cache_read,
                     self.output + other.output)

    def as_dict(self) -> dict:
        return {"input": self.input, "cache_creation": self.cache_creation,
                "cache_read": self.cache_read, "output": self.output}

    @staticmethod
    def from_dict(d) -> "Usage":
        def num(k):
            v = d.get(k, 0) if isinstance(d, dict) else 0
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
        return Usage(num("input"), num("cache_creation"), num("cache_read"), num("output"))


@dataclass(frozen=True)
class ModelReply:
    status: Literal["ok", "timeout", "exit", "error", "unsafe", "off", "deadline"]
    text: str = ""
    usage: Usage = Usage()
    cost_usd: Optional[float] = None     # process cumulative, last seen
    estimated: bool = False              # usage guessed for a killed turn
    detail: Optional[str] = None         # a fixed word for an error ("auth"), never the CLI's message


class ModelSession(Protocol):
    def send(self, text: str, timeout_s: float, stop: Callable[[], Optional[str]]) -> ModelReply: ...

    def close(self) -> None: ...
