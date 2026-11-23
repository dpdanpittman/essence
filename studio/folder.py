"""The studio folder: its paths, creating the tree with private modes, and safe file writes."""
from __future__ import annotations

import os
from dataclasses import dataclass

JOURNAL_HEAD = "# Journal\n\n"


@dataclass(frozen=True)
class Paths:
    root: str
    journal: str
    jukebox: str
    shelf: str
    paper_dir: str
    state: str
    transcripts: str
    cwd: str
    kill_switch: str

    @property
    def lock(self) -> str:
        return os.path.join(self.state, "lock")

    @property
    def usage(self) -> str:
        return os.path.join(self.state, "usage.json")

    @property
    def wakeups(self) -> str:
        return os.path.join(self.state, "wakeups.jsonl")

    def plan(self, night: str) -> str:
        return os.path.join(self.state, f"plan-{night}.json")

    def paper_file(self, night: str) -> str:
        return os.path.join(self.paper_dir, f"{night}.json")

    @classmethod
    def from_config(cls, cfg) -> "Paths":
        root = cfg.studio_dir
        state = os.path.join(root, "state")
        return cls(root=root,
                   journal=os.path.join(root, "journal.md"),
                   jukebox=os.path.join(root, "jukebox"),
                   shelf=os.path.join(root, "shelf"),
                   paper_dir=cfg.paper.dir,
                   state=state,
                   transcripts=os.path.join(state, "transcripts"),
                   cwd=os.path.join(state, "cwd"),
                   kill_switch=cfg.kill_switch)


def paths(cfg) -> Paths:
    """The Paths for a config."""
    return Paths.from_config(cfg)


def _private_dir(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def ensure(p: Paths) -> None:
    """Create the folder tree: folders 0700, a new journal 0600 with its heading."""
    for d in (p.root, p.jukebox, p.shelf, p.state, p.transcripts, p.cwd, p.paper_dir):
        _private_dir(d)
    try:
        fd = os.open(p.journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, JOURNAL_HEAD.encode("utf-8"))
    finally:
        os.close(fd)


def write_private(path: str, text: str) -> None:
    """Write a whole file atomically with mode 0600 (temp file, fsync, rename)."""
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        data = text.encode("utf-8")
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    os.replace(tmp, path)


def append_private(path: str, text: str) -> None:
    """Append text (O_APPEND), creating the file 0600 if needed.

    Normally one write call. A short write (a full disk) continues with the bytes not yet written,
    never the same bytes twice; if nothing more can be written it raises OSError, so the caller
    can record "journal-short-write"-style failures instead of silently keeping half an entry."""
    data = memoryview(text.encode("utf-8"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        while data:
            n = os.write(fd, data)
            if n <= 0:
                raise OSError("short write")
            data = data[n:]
    finally:
        os.close(fd)
