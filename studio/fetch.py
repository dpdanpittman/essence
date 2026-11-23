"""The one network helper of the studio.

Only this module opens network connections. Every other module reaches the
network through ``ctx.fetch``, which is this ``fetch_text`` or ``None``.

Rules: https only, the host must be exactly in the allow list, a redirect may
only go to another allowed https host, the body is capped at ``max_bytes``,
one try, a fixed User-Agent, no cookies.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Sequence

USER_AGENT = "essence-studio/1"


class FetchError(Exception):
    """A fetch was refused or failed. The message never holds page content."""


def _check_url(url: str, allow_hosts: Sequence[str]) -> None:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise FetchError("not a url") from exc
    if parts.scheme != "https":
        raise FetchError("only https is allowed")
    host = (parts.hostname or "").lower()
    allowed = {h.lower() for h in allow_hosts}
    if not host or host not in allowed:
        raise FetchError(f"host not allowed: {host or '(none)'}")
    if parts.username or parts.password:
        raise FetchError("credentials in url are not allowed")


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an allowed https host."""

    max_redirections = 3

    def __init__(self, allow_hosts: Sequence[str]):
        super().__init__()
        self.allow_hosts = list(allow_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        _check_url(newurl, self.allow_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(allow_hosts: Sequence[str]) -> urllib.request.OpenerDirector:
    """An opener with the guarded redirect handler and no cookie handler."""
    return urllib.request.build_opener(_GuardedRedirects(allow_hosts))


_clock = time.monotonic  # tests replace it
CHUNK = 64 * 1024


def _read_bounded(resp, max_bytes: int, deadline: float) -> bytes:
    """Read the body in small pieces with one overall deadline.

    The socket timeout only limits each read; a server that trickles bytes could otherwise hold
    the fetch far longer. read1 returns after one underlying read, so the deadline is checked
    between reads (worst case: the deadline plus one socket timeout)."""
    read1 = getattr(resp, "read1", None)
    parts = []
    got = 0
    while True:
        if _clock() > deadline:
            raise FetchError("fetch took too long")
        want = min(CHUNK, max_bytes + 1 - got)
        try:
            chunk = read1(want) if read1 is not None else resp.read(want)
        except (OSError, ValueError) as exc:
            raise FetchError(f"read failed: {type(exc).__name__}") from None
        if not chunk:
            return b"".join(parts)
        parts.append(chunk)
        got += len(chunk)
        if got > max_bytes:
            raise FetchError("response too large")


def fetch_text(
    url: str,
    allow_hosts: Sequence[str],
    timeout: float = 10,
    max_bytes: int = 1_000_000,
    *,
    opener=None,
) -> str:
    """Fetch ``url`` once and return its body as text.

    ``opener`` is for tests only: any object with ``open(request, timeout=)``.
    Raises ``FetchError`` on any refusal or failure.
    """
    _check_url(url, allow_hosts)
    deadline = _clock() + timeout
    if opener is None:
        opener = build_opener(allow_hosts)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        method="GET",
    )
    try:
        resp = opener.open(req, timeout=timeout)
    except FetchError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"fetch failed: {type(exc).__name__}") from None
    try:
        final = resp.geturl() if hasattr(resp, "geturl") else url
        _check_url(final or url, allow_hosts)
        length = None
        headers = getattr(resp, "headers", None)
        if headers is not None:
            raw_len = headers.get("Content-Length")
            if raw_len and raw_len.strip().isdigit():
                length = int(raw_len.strip())
        if length is not None and length > max_bytes:
            raise FetchError("response too large")
        body = _read_bounded(resp, max_bytes, deadline)
        if len(body) > max_bytes:
            raise FetchError("response too large")
        charset = "utf-8"
        if headers is not None and hasattr(headers, "get_content_charset"):
            charset = headers.get_content_charset() or "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")
    finally:
        close = getattr(resp, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass
