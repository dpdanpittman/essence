"""Reading: the verb ``read`` and the reading fetcher. OFF by default.

Reading is on only when ``reading.start_date`` is set and is today or
earlier (schedule time zone) and ``reading.sources`` is not empty. Until
then the verb answers ``Nothing to read here yet.``

A source is ``{"name", "kind", "url"}`` with kind ``rss``, ``atom`` or
``shelf``. Feeds are fetched through ``ctx.fetch`` only, from the hosts of
the configured URLs, at most one fetch per ``read``. ``shelf`` items are
``*.txt`` files in the studio's ``shelf/`` folder. One item is picked that
has not been read before (``state/read.json`` keeps hashes, not text),
stripped to plain text and cut to ``reading.max_chars``. No link is ever
passed to the agent.
"""

import hashlib
import html.parser
import json
import os
import stat
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .types import VerbResult, VerbSpec

OFF_TEXT = "Nothing to read here yet."
MAX_SHELF_BYTES = 64 * 1024
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def _item(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _start_date(cfg) -> date | None:
    value = cfg.reading.start_date
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _sources(cfg) -> list:
    return list(cfg.reading.sources or [])


def is_on(cfg, today: date) -> bool:
    start = _start_date(cfg)
    return start is not None and start <= today and bool(_sources(cfg))


def status(cfg, today: date) -> str:
    """One status phrase for ``studio status``."""
    start = _start_date(cfg)
    n = len(_sources(cfg))
    if start is None:
        return "off (no start date set)"
    if start > today:
        return f"off (starts {start.isoformat()})"
    if n == 0:
        return "off (no sources)"
    return f"on ({n} source{'s' if n != 1 else ''})"


def allowed_hosts(cfg) -> list[str]:
    hosts = []
    for src in _sources(cfg):
        if _item(src, "kind") == "shelf":
            continue
        url = _item(src, "url") or ""
        try:
            parts = urllib.parse.urlsplit(url)
        except ValueError:
            continue
        if parts.scheme == "https" and parts.hostname:
            hosts.append(parts.hostname.lower())
    return sorted(set(hosts))


# ------------------------------------------------------------- plain text


class _Text(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BREAK = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BREAK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def plain_text(markup: str) -> str:
    """HTML or text to plain paragraphs, control and format characters removed."""
    p = _Text()
    try:
        p.feed(markup or "")
        p.close()
    except Exception:
        pass
    text = "".join(p.out)
    kept = []
    for ch in text:
        if ch == "\n":
            kept.append(ch)
        elif ch == "\t":
            kept.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs"):
            continue
        else:
            kept.append(ch)
    paras = [" ".join(line.split()) for line in "".join(kept).split("\n")]
    return "\n".join(x for x in paras if x)


def cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = max(head.rfind(" "), head.rfind("\n"))
    return (head[:space] if space > limit // 2 else head).rstrip()


# ------------------------------------------------------------------ feeds


def parse_feed(xml_text: str) -> list[dict]:
    """Items of an RSS or Atom feed: {'id', 'title', 'body'}."""
    lowered = xml_text[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        body = it.findtext(CONTENT) or it.findtext("description") or ""
        ident = (it.findtext("guid") or it.findtext("link") or title).strip()
        items.append({"id": ident, "title": title, "body": body})
    for it in root.iter(ATOM + "entry"):
        title = (it.findtext(ATOM + "title") or "").strip()
        body = it.findtext(ATOM + "content") or it.findtext(ATOM + "summary") or ""
        link = it.find(ATOM + "link")
        href = link.get("href", "") if link is not None else ""
        ident = (it.findtext(ATOM + "id") or href or title).strip()
        items.append({"id": ident, "title": title, "body": body})
    return [i for i in items if i["title"] or i["body"]]


def shelf_items(shelf: str) -> list[dict]:
    out = []
    try:
        names = sorted(os.listdir(shelf))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".txt") or name.startswith("."):
            continue
        path = os.path.join(shelf, name)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            continue
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SHELF_BYTES:
                continue
            data = os.read(fd, MAX_SHELF_BYTES)
        except OSError:
            continue
        finally:
            os.close(fd)
        text = data.decode("utf-8", errors="replace")
        out.append({"id": "shelf:" + name, "title": name[:-4].replace("-", " "), "body": text})
    return out


# ------------------------------------------------------------ read memory


def _read_path(ctx) -> str:
    return os.path.join(ctx.paths.state, "read.json")


def _key(source_name: str, ident: str) -> str:
    return hashlib.sha256(f"{source_name}\n{ident}".encode()).hexdigest()[:32]


def _load_read(ctx) -> list[str]:
    try:
        with open(_read_path(ctx), encoding="utf-8") as fh:
            data = json.load(fh)
        return [x for x in data.get("read", []) if isinstance(x, str)]
    except (OSError, ValueError, AttributeError):
        return []


def _save_read(ctx, seen: list[str]) -> None:
    if ctx.dry:
        return
    from .folder import write_private

    try:
        write_private(_read_path(ctx), json.dumps({"version": 1, "read": seen[-2000:]}, indent=1) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------- verb


def _today(ctx) -> date:
    return ctx.now().astimezone(ZoneInfo(ctx.cfg.schedule.time_zone)).date()


def _read(ctx, _arg: str) -> VerbResult:
    cfg = ctx.cfg
    if not is_on(cfg, _today(ctx)):
        return VerbResult(OFF_TEXT)
    seen = _load_read(ctx)
    sources = _sources(cfg)
    order = list(range(len(sources)))
    ctx.rng.shuffle(order)
    fetched = False
    hosts = allowed_hosts(cfg)
    for idx in order:
        src = sources[idx]
        kind, name = _item(src, "kind"), str(_item(src, "name") or "a source")
        if kind == "shelf":
            items = shelf_items(ctx.paths.shelf)
        elif kind in ("rss", "atom"):
            if fetched or ctx.fetch is None:
                continue
            fetched = True
            try:
                items = parse_feed(ctx.fetch(_item(src, "url"), hosts))
            except Exception:
                continue
        else:
            continue
        for it in items:
            k = _key(name, it["id"])
            if k in seen:
                continue
            title = plain_text(it["title"]).replace("\n", " ")
            body = plain_text(it["body"])
            if not body and not title:
                continue
            head = f"From {plain_text(name)}: {title}." if title else f"From {plain_text(name)}."
            text = cut(head + ("\n\n" + body if body else ""), cfg.reading.max_chars)
            seen.append(k)
            _save_read(ctx, seen)
            return VerbResult(text, happened="read something")
    return VerbResult("Nothing new to read just now.")


def verb_specs(cfg) -> list:
    if not cfg.verbs.read:
        return []

    def handler(ctx, arg):
        try:
            return _read(ctx, arg)
        except Exception:
            return VerbResult("That did not work just now.")

    return [VerbSpec("read", "read one thing from the shelf or an approved list", False, handler)]
