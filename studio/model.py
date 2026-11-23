"""The model run: one tool-less `claude -p` process per wake-up, speaking stream-json, with hard limits.

The model gets text and gives text. It has no tools and no MCP servers; every init event is
checked and a run that shows any tool is killed at once. Also: a scripted FakeSession for tests.
"""
from __future__ import annotations

import ctypes
import fcntl
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, List, Optional, Sequence, Union

from .types import ModelReply, Usage

DISALLOWED = "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,Task,Read,Glob,Grep"
FIXED_ENV = {
    "LANG": "C.UTF-8",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS": "1",
    "CLAUDE_CODE_DISABLE_FILE_CHECKPOINTING": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_EVAL_CONFINED": "1",
    "DISABLE_AUTOUPDATER": "1",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}
PROXY_NAMES = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")
MAX_LINE = 8 * 1024 * 1024
CLOSE_WAIT_S = 15
TOKEN_TIMEOUT_S = 60
_EOF = object()


class ModelStartError(Exception):
    """The model process could not be started. The message never holds a secret."""


class TokenError(Exception):
    """The token command failed. The message never holds its output."""


# ---- command, environment, token ----------------------------------------------------------------

def build_command(cfg, prompt_path: str) -> list:
    """The exact argv (contract section 0). Never run through a shell.

    The system prompt holds the identity text, so it never goes on the command line, where any
    local account could read it through /proc/<pid>/cmdline. The CLI reads it from `prompt_path`,
    which is /dev/fd/<n> of an in-memory file handed to the child (see prompt_fd)."""
    return list(cfg.model.command) + [
        "-p", "--model", cfg.model.name, "--restricted", "--strict-mcp-config", "--no-session-persistence",
        "--disable-slash-commands", "--permission-prompts", "none", "--tools", "",
        "--disallowedTools", DISALLOWED,
        "--system-prompt-file", prompt_path,
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
    ]


def build_env(environ, token_env: Optional[str] = None, token: Optional[str] = None,
              config_dir: Optional[str] = None) -> dict:
    """The child's whole environment: only the names the contract lists."""
    env = {}
    for k in ("HOME", "PATH"):
        if environ.get(k):
            env[k] = environ[k]
    for k in PROXY_NAMES:
        if environ.get(k):
            env[k] = environ[k]
    env.update(FIXED_ENV)
    if token is not None and token_env:
        env[token_env] = token
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir
    return env


def load_token(cfg, environ=os.environ) -> str:
    """Run model.auth_token_cmd once (stdin /dev/null, 60 s); its stripped stdout is the token."""
    cmd = list(cfg.model.auth_token_cmd or ())
    if not cmd:
        raise TokenError("no token command configured")
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=TOKEN_TIMEOUT_S, env=dict(environ), check=False)
    except subprocess.TimeoutExpired:
        raise TokenError("token command timed out") from None
    except OSError:
        raise TokenError("token command could not start") from None
    if r.returncode != 0:
        raise TokenError(f"token command failed (exit {r.returncode})")
    token = r.stdout.decode("utf-8", "replace").strip()
    if not token or "\n" in token:
        raise TokenError("token command gave no usable token")
    return token


def prompt_fd(text: str) -> int:
    """An in-memory, sealed, read-only-content file holding `text`. Never on disk, not in argv.

    Opening /dev/fd/<n> of a memfd gives a fresh read from the start, so the CLI may read it more
    than once. Only the same user (or root) can open another process's /proc/<pid>/fd entries."""
    fd = os.memfd_create("studio-prompt", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        data = text.encode("utf-8")
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        try:
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        except (AttributeError, OSError):
            pass
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        os.close(fd)
        raise


def check_cwd(path: str) -> None:
    """Refuse a working directory inside a git repository."""
    p = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            raise ModelStartError("the model's working directory is inside a git repository")
        parent = os.path.dirname(p)
        if parent == p:
            return
        p = parent


_libc = None
try:
    _libc = ctypes.CDLL(None, use_errno=True)
except Exception:  # pragma: no cover
    _libc = None


def _child_setup() -> None:
    """In the child, before exec: die when the parent dies (PR_SET_PDEATHSIG = SIGKILL)."""
    try:
        if _libc is not None:
            _libc.prctl(1, signal.SIGKILL, 0, 0, 0)
    except Exception:
        pass


def usage_from_result(u) -> Usage:
    """Usage of one turn from a result event's `usage` (the CLI's field names)."""
    if not isinstance(u, dict):
        return Usage()

    def num(k):
        v = u.get(k, 0)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0
    return Usage(num("input_tokens"), num("cache_creation_input_tokens"), num("cache_read_input_tokens"),
                 num("output_tokens"))


def user_line(text: str) -> bytes:
    return (json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode("utf-8")


AUTH_HINTS = ("authenticat", "oauth", "log in", "/login", "not logged in", "api key", "unauthorized")


def error_detail(ev) -> Optional[str]:
    """A fixed word for a failed result: "auth" when it reads like a login problem, else None.

    Only this word is kept; the CLI's own message is never stored or printed."""
    parts = [ev.get("subtype"), ev.get("result"), ev.get("error")]
    errs = ev.get("errors")
    if isinstance(errs, list):
        parts.extend(errs)
    blob = " ".join(p for p in parts if isinstance(p, str)).lower()
    return "auth" if any(h in blob for h in AUTH_HINTS) else None


# ---- the real session ---------------------------------------------------------------------------

class ClaudeSession:
    """One claude process for one wake-up. send() gives one turn; close() ends it."""

    def __init__(self, cfg, cwd: str, system_prompt: str, max_answer_chars: int,
                 token: Optional[str] = None, config_root: Optional[str] = None, environ=os.environ):
        self.max_chars = max_answer_chars
        self.dead = False
        self.closed = False
        self.config_dir: Optional[str] = None
        self.last_input = Usage()
        self.cost: Optional[float] = None
        check_cwd(cwd)
        os.makedirs(cwd, mode=0o700, exist_ok=True)
        os.chmod(cwd, 0o700)
        if token is not None:
            root = config_root or os.path.dirname(cwd)
            n = 0
            while True:
                n += 1
                cand = os.path.join(root, f"cli-config-{os.getpid()}-{n}")
                try:
                    os.mkdir(cand, 0o700)
                    break
                except FileExistsError:
                    continue
            self.config_dir = cand
        env = build_env(environ, cfg.model.auth_token_env, token, self.config_dir)
        try:
            pfd = prompt_fd(system_prompt)
        except OSError as e:
            self._drop_config_dir()
            raise ModelStartError(f"could not hold the system prompt ({type(e).__name__})") from None
        argv = build_command(cfg, f"/dev/fd/{pfd}")
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, cwd=cwd, env=env, pass_fds=(pfd,),
                                         start_new_session=True, preexec_fn=_child_setup, close_fds=True)
        except OSError as e:
            self._drop_config_dir()
            raise ModelStartError(f"could not start the model command ({type(e).__name__})") from None
        finally:
            os.close(pfd)
        self.pgid = self.proc.pid
        self.events: "queue.Queue" = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        f = self.proc.stdout
        try:
            while True:
                line = f.readline(MAX_LINE)
                if not line:
                    break
                if not line.endswith(b"\n") and len(line) >= MAX_LINE:
                    while True:  # an over-long line: skip the rest of it
                        more = f.readline(MAX_LINE)
                        if not more or more.endswith(b"\n"):
                            break
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    self.events.put(ev)
        except (OSError, ValueError):
            pass
        self.events.put(_EOF)

    def _kill(self) -> None:
        self.dead = True
        try:
            os.killpg(self.pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def _estimate(self, chars: int) -> Usage:
        li = self.last_input
        return Usage(li.input, li.cache_creation, li.cache_read, chars // 3)

    def send(self, text: str, timeout_s: float, stop: Callable[[], Optional[str]]) -> ModelReply:
        if self.dead or self.closed:
            return ModelReply("exit")
        try:
            self.proc.stdin.write(user_line(text))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._kill()
            return ModelReply("exit")
        start = time.monotonic()
        kept: List[str] = []
        kept_len = 0
        streamed = 0
        next_stop = start
        while True:
            now = time.monotonic()
            if now >= next_stop:
                word = stop()
                next_stop = now + 1.0
                if word:
                    self._kill()
                    return ModelReply(word if word in ("off", "deadline") else "off",
                                      usage=self._estimate(streamed), cost_usd=self.cost, estimated=True)
            if now - start >= timeout_s:
                self._kill()
                return ModelReply("timeout", usage=self._estimate(streamed), cost_usd=self.cost, estimated=True)
            wait = max(0.01, min(next_stop - now, timeout_s - (now - start)))
            try:
                ev = self.events.get(timeout=wait)
            except queue.Empty:
                continue
            if ev is _EOF:
                self._kill()
                return ModelReply("exit", usage=self._estimate(streamed), cost_usd=self.cost, estimated=True)
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                if ev.get("tools") != [] or ev.get("mcp_servers") != []:
                    self._kill()
                    return ModelReply("unsafe", usage=self._estimate(streamed), cost_usd=self.cost, estimated=True)
            elif kind == "assistant":
                content = (ev.get("message") or {}).get("content") if isinstance(ev.get("message"), dict) else None
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "tool_use":
                            self._kill()
                            return ModelReply("unsafe", usage=self._estimate(streamed), cost_usd=self.cost,
                                              estimated=True)
                        t = block.get("text")
                        if block.get("type") == "text" and isinstance(t, str):
                            streamed += len(t)
                            if kept_len < self.max_chars:
                                kept.append(t[:self.max_chars - kept_len])
                                kept_len += len(kept[-1])
            elif kind == "result":
                usage = usage_from_result(ev.get("usage"))
                cost = ev.get("total_cost_usd")
                if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                    self.cost = float(cost)
                self.last_input = Usage(usage.input, usage.cache_creation, usage.cache_read, 0)
                result = ev.get("result")
                if ev.get("is_error") or not isinstance(result, str):
                    return ModelReply("error", usage=usage, cost_usd=self.cost, detail=error_detail(ev))
                return ModelReply("ok", text=result[:self.max_chars], usage=usage, cost_usd=self.cost)

    def _drop_config_dir(self) -> None:
        if self.config_dir:
            shutil.rmtree(self.config_dir, ignore_errors=True)
            self.config_dir = None

    def close(self) -> None:
        """Close stdin, wait at most 15 s, kill the process group. Safe to call twice."""
        if self.closed:
            return
        self.closed = True
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        if not self.dead:
            try:
                self.proc.wait(timeout=CLOSE_WAIT_S)
            except subprocess.TimeoutExpired:
                pass
        self.dead = True
        try:
            os.killpg(self.pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            if self.proc.stdout:
                self.proc.stdout.close()
        except OSError:
            pass
        self._drop_config_dir()


def open_session(cfg, cwd: str, system_prompt: str, state_dir: str, environ=os.environ) -> ClaudeSession:
    """Start the real session, in token mode when model.auth_token_cmd is set."""
    token = load_token(cfg, environ) if cfg.model.auth_token_cmd else None
    return ClaudeSession(cfg, cwd, system_prompt, cfg.limits.max_answer_chars, token=token,
                         config_root=state_dir, environ=environ)


# ---- the scripted session -----------------------------------------------------------------------

class FakeSession:
    """A scripted model for tests and `wake --fake-model`. Each item is an answer text or a ModelReply."""

    def __init__(self, script: Sequence[Union[str, ModelReply]], usage: Usage = Usage(100, 0, 0, 10),
                 on_send: Optional[Callable[[str, int], None]] = None, default: str = "."):
        self.script = list(script)
        self.usage = usage
        self.on_send = on_send
        self.default = default
        self.sent: List[str] = []
        self.closed = False
        self.cost = 0.0

    def send(self, text: str, timeout_s: float, stop: Callable[[], Optional[str]]) -> ModelReply:
        if self.closed:
            return ModelReply("exit")
        i = len(self.sent)
        self.sent.append(text)
        if self.on_send is not None:
            self.on_send(text, i)
        word = stop()
        if word:
            return ModelReply(word if word in ("off", "deadline") else "off", estimated=True)
        item = self.script[i] if i < len(self.script) else self.default
        if isinstance(item, ModelReply):
            return item
        self.cost += 0.001
        return ModelReply("ok", text=item, usage=self.usage, cost_usd=round(self.cost, 6))

    def close(self) -> None:
        self.closed = True
