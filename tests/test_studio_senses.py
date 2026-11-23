"""Offline tests for the studio senses, sense verbs, fetcher, reading and channel.

No network, no model, no chat service. Every file is written in a temporary
folder. Fixtures in tests/fixtures/studio/ are invented.
"""

import ast
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)

from studio import body, channel, config, fetch, folder, house, reading, senses, sky, song  # noqa: E402
from studio.types import Context, SenseReading, VerbResult  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "studio")
UTC = timezone.utc


def rd(path, encoding="utf-8"):
    with open(path, encoding=encoding) as fh:
        return fh.read()


def wr(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


BASE = {
    "version": 1,
    "town": {"name": "Lowmoor", "latitude": 61.2, "longitude": 7.1, "time_zone": "Europe/Oslo"},
    "schedule": {"time_zone": "UTC"},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="studio-senses-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def cfg(self, extra=None, base=True):
        data = deep_merge(BASE if base else {"version": 1}, extra or {})
        data.setdefault("studio_dir", os.path.join(self.tmp, "studio"))
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return config.load(path, env={"HOME": self.tmp})

    def ctx(self, cfg, now, fetch_fn=None, dry=False, memory=None):
        paths = folder.paths(cfg)
        folder.ensure(paths)
        clock = now if callable(now) else (lambda: now)
        return Context(cfg=cfg, paths=paths, now=clock, rng=random.Random(7),
                       memory={} if memory is None else memory, fetch=fetch_fn, dry=dry)


# ------------------------------------------------------------------- sky


class SunAndMoon(unittest.TestCase):
    # Source: timeanddate.com, sun table for London, United Kingdom, June and
    # December 2024: 21 June sunrise 04:43, sunset 21:21 (BST), maximum
    # altitude 61.9 degrees; 21 December sunrise 08:04, sunset 15:53 (GMT).
    LAT, LON = 51.5074, -0.1278
    TZ = ZoneInfo("Europe/London")

    def close_to(self, got, h, m, minutes=3):
        want = got.replace(hour=h, minute=m, second=0, microsecond=0)
        self.assertLessEqual(abs((got - want).total_seconds()), minutes * 60, got)

    def test_sunrise_sunset_summer(self):
        rise, sett = sky.sun_events(date(2024, 6, 21), self.TZ, self.LAT, self.LON)
        self.close_to(rise, 4, 43)
        self.close_to(sett, 21, 21)

    def test_sunrise_sunset_winter(self):
        rise, sett = sky.sun_events(date(2024, 12, 21), self.TZ, self.LAT, self.LON)
        self.close_to(rise, 8, 4)
        self.close_to(sett, 15, 53)

    def test_noon_altitude(self):
        noon = datetime(2024, 6, 21, 12, 2, tzinfo=self.TZ)
        best = max(sky.sun_altitude(noon + timedelta(minutes=m), self.LAT, self.LON)
                   for m in range(-40, 40))
        self.assertAlmostEqual(best, 61.9, delta=1.0)

    def test_polar_night_and_day(self):
        tz = ZoneInfo("UTC")
        self.assertEqual(sky.sun_events(date(2024, 12, 21), tz, 78.2, 15.6), (None, None))
        self.assertEqual(sky.sun_events(date(2024, 6, 21), tz, 78.2, 15.6), (None, None))
        self.assertGreater(sky.sun_altitude(datetime(2024, 6, 21, 12, tzinfo=UTC), 78.2, 15.6), 0)

    def test_moon_phase(self):
        # Source: NASA/GSFC phases of the moon (Espenak): new moon
        # 2024-01-11 11:57 UTC, full moon 2024-01-25 17:54 UTC.
        name, lit = sky.moon_phase(datetime(2024, 1, 11, 11, 57, tzinfo=UTC))
        self.assertEqual(name, "new")
        self.assertLess(lit, 0.01)
        name, lit = sky.moon_phase(datetime(2024, 1, 25, 17, 54, tzinfo=UTC))
        self.assertEqual(name, "full")
        self.assertGreater(lit, 0.99)
        self.assertEqual(sky.moon_phase(datetime(2024, 1, 18, 3, 53, tzinfo=UTC))[0], "at first quarter")

    def test_compass(self):
        self.assertEqual(sky.compass(40), "north-east")
        self.assertEqual(sky.compass(359), "north")
        self.assertEqual(sky.compass(200), "south")


class Weather(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)

    def canned(self):
        with open(os.path.join(FIX, "open-meteo.json"), encoding="utf-8") as fh:
            return fh.read()

    def test_parse(self):
        w = sky.parse_weather(self.canned())
        self.assertEqual(w["weather_code"], 71)
        self.assertAlmostEqual(w["temperature"], -2.4)
        self.assertAlmostEqual(w["wind_speed"], 6.3)
        self.assertEqual(sky.parse_weather("not json"), None)
        self.assertEqual(sky.parse_weather("{}"), None)

    def test_url(self):
        url = sky.weather_url(61.2, 7.1, "Europe/Oslo")
        self.assertTrue(url.startswith("https://api.open-meteo.com/v1/forecast?"))
        for part in ("latitude=61.2000", "longitude=7.1000", "wind_speed_unit=ms",
                     "timezone=Europe%2FOslo",
                     "current=temperature_2m,cloud_cover,wind_speed_10m,wind_direction_10m,precipitation,weather_code"):
            self.assertIn(part, url)

    def test_fetch_and_cache(self):
        calls = []

        def fake(url, hosts):
            calls.append((url, list(hosts)))
            return self.canned()

        cfg = self.cfg()
        c = self.ctx(cfg, self.NOW, fake)
        w = sky.weather(c)
        self.assertEqual(w["weather_code"], 71)
        self.assertEqual(calls[0][1], ["api.open-meteo.com"])
        cache = os.path.join(c.paths.state, "weather.json")
        self.assertEqual(os.stat(cache).st_mode & 0o777, 0o600)
        # a new wake-up within the cache time reads the cache, no fetch
        c2 = self.ctx(cfg, self.NOW + timedelta(minutes=10), fake)
        self.assertEqual(sky.weather(c2)["weather_code"], 71)
        self.assertEqual(len(calls), 1)
        # after the cache time it fetches again
        c3 = self.ctx(cfg, self.NOW + timedelta(minutes=45), fake)
        sky.weather(c3)
        self.assertEqual(len(calls), 2)

    def test_fetch_failure_one_try_and_sun_only(self):
        calls = []

        def broken(url, hosts):
            calls.append(url)
            raise fetch.FetchError("fetch failed: URLError")

        c = self.ctx(self.cfg(), self.NOW, broken)
        r1 = sky.SkySense().read(c)
        r2 = sky.SkySense().read(c)
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(r1, SenseReading)
        self.assertNotIn("wind", r1.text)
        self.assertTrue(r1.changed)
        self.assertFalse(r2.changed)

    def test_no_network_and_dry_write_nothing(self):
        c = self.ctx(self.cfg(), self.NOW, None, dry=True)
        self.assertIsNone(sky.weather(c))
        c = self.ctx(self.cfg(), self.NOW, lambda u, h: self.canned(), dry=True)
        sky.weather(c)
        self.assertFalse(os.path.exists(os.path.join(c.paths.state, "weather.json")))

    def test_disabled(self):
        calls = []
        c = self.ctx(self.cfg({"weather": {"enabled": False}}), self.NOW,
                     lambda u, h: calls.append(u) or self.canned())
        self.assertIsNone(sky.weather(c))
        self.assertEqual(calls, [])


class SkySenseAndVerbs(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)

    def canned(self, **cur):
        data = json.loads(rd(os.path.join(FIX, "open-meteo.json"), encoding="utf-8"))
        data["current"].update(cur)
        return json.dumps(data)

    def test_reading_and_change(self):
        text = {"t": self.canned()}
        c = self.ctx(self.cfg({"weather": {"cache_minutes": 1}}), self.NOW, lambda u, h: text["t"])
        s = sky.SkySense()
        first = s.read(c)
        self.assertTrue(first.changed)
        self.assertIn("light snow", first.text)
        self.assertIn("wind 6 m/s from the north-east", first.text)
        self.assertLessEqual(len(first.text), 160)
        same = s.read(c)
        self.assertFalse(same.changed)
        # the wind rises: a later reading in the same wake-up says so
        c.memory["sky"]["weather"] = sky.parse_weather(self.canned(wind_speed_10m=12.5))
        c.memory["sky"]["weather_at"] = self.NOW
        os.unlink(os.path.join(c.paths.state, "weather.json"))
        up = s.read(c)
        self.assertTrue(up.changed)
        self.assertIn("the wind picked up.", up.text)

    def test_window_and_sun(self):
        cfg = self.cfg()
        c = self.ctx(cfg, self.NOW, lambda u, h: self.canned())
        specs = {v.name: v for v in senses.verbs(cfg)}
        w = specs["window"].handler(c, "")
        self.assertTrue(w.text.startswith("In Lowmoor the sky is overcast with light snow."))
        self.assertIn("Wind 6 m/s from the north-east.", w.text)
        self.assertIn("-2 C.", w.text)
        self.assertIn("The moon is", w.text)
        self.assertEqual(w.happened, "looked out the window")
        sun = specs["sun"].handler(c, "")
        self.assertEqual(sun.happened, "felt the sun")
        self.assertRegex(sun.text, r"^The sun is (up|down), \d+ degrees? (above|below) the horizon")
        self.assertRegex(sun.text, r"(rose|rises) at \d\d:\d\d")
        self.assertLessEqual(len(sun.text), 600)

    def test_window_without_weather(self):
        cfg = self.cfg()
        c = self.ctx(cfg, self.NOW, None)
        w = {v.name: v for v in senses.verbs(cfg)}["window"].handler(c, "")
        self.assertIn("In Lowmoor the weather cannot be seen just now.", w.text)

    def test_no_town_no_sky(self):
        cfg = self.cfg({"town": {"name": None}})
        names = {v.name for v in senses.verbs(cfg)}
        self.assertNotIn("window", names)
        self.assertNotIn("sun", names)
        self.assertNotIn("sky", [p.name for p in senses.providers(cfg)])


# ----------------------------------------------------------------- fetch


class FakeResp:
    def __init__(self, body=b"hello", url="https://a.example/x", headers=None):
        self._body = body
        self._url = url
        self.headers = headers if headers is not None else {}
        self.closed = False

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def open(self, req, timeout=None):
        self.calls.append((req.full_url, timeout, dict(req.header_items())))
        if self.exc:
            raise self.exc
        return self.resp


class Fetch(unittest.TestCase):
    HOSTS = ["a.example"]

    def test_ok(self):
        op = FakeOpener(FakeResp(b"fine"))
        self.assertEqual(fetch.fetch_text("https://a.example/x", self.HOSTS, opener=op), "fine")
        url, timeout, headers = op.calls[0]
        self.assertEqual(timeout, 10)
        self.assertEqual(headers.get("User-agent"), "essence-studio/1")
        self.assertNotIn("Cookie", headers)

    def test_refuses_http(self):
        op = FakeOpener(FakeResp())
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_text("http://a.example/x", self.HOSTS, opener=op)
        self.assertEqual(op.calls, [])

    def test_refuses_other_host(self):
        op = FakeOpener(FakeResp())
        for url in ("https://b.example/x", "https://a.example.evil.test/x", "https://user@a.example/x"):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_text(url, self.HOSTS, opener=op)
        self.assertEqual(op.calls, [])

    def test_refuses_redirect_to_other_host(self):
        op = FakeOpener(FakeResp(url="https://b.example/landing"))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_text("https://a.example/x", self.HOSTS, opener=op)
        handler = fetch._GuardedRedirects(self.HOSTS)
        req = urllib.request.Request("https://a.example/x")
        with self.assertRaises(fetch.FetchError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://b.example/y")
        with self.assertRaises(fetch.FetchError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://a.example/y")
        ok = handler.redirect_request(req, None, 302, "Found", {}, "/same-host")
        self.assertEqual(ok.full_url, "https://a.example/same-host")
        # the real opener carries the guard and no cookie handler
        opener = fetch.build_opener(self.HOSTS)
        kinds = [type(h).__name__ for h in opener.handlers]
        self.assertIn("_GuardedRedirects", kinds)
        self.assertNotIn("HTTPCookieProcessor", kinds)

    def test_refuses_too_big(self):
        op = FakeOpener(FakeResp(b"x" * 101))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_text("https://a.example/x", self.HOSTS, max_bytes=100, opener=op)
        op = FakeOpener(FakeResp(b"x", headers={"Content-Length": "5000"}))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_text("https://a.example/x", self.HOSTS, max_bytes=100, opener=op)

    def test_one_try(self):
        op = FakeOpener(exc=urllib.error.URLError("down"))
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_text("https://a.example/x", self.HOSTS, opener=op)
        self.assertEqual(len(op.calls), 1)

    def test_only_fetch_imports_network(self):
        studio_dir = os.path.join(ROOT, "studio")
        for name in sorted(os.listdir(studio_dir)):
            if not name.endswith(".py") or name == "fetch.py":
                continue
            src = rd(os.path.join(studio_dir, name))
            for node in ast.walk(ast.parse(src)):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                for m in mods:
                    if m in ("urllib.parse",):
                        continue
                    top = m.split(".")[0]
                    if m.startswith(("urllib.request", "urllib.error", "http.client")) or m == "urllib" \
                            or top in ("socket", "ssl", "http", "requests", "httpx"):
                        self.fail(f"{name} imports {m}")


# ------------------------------------------------------------------ body


class Body(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)

    def sysroot(self):
        dst = os.path.join(self.tmp, "sys")
        shutil.copytree(os.path.join(FIX, "sys"), dst)
        return dst

    def test_temps_named(self):
        root = self.sysroot()
        cfg = self.cfg({"body": {"sys_root": root, "temps": [
            {"hwmon": "cpuchip", "label": "the processor"},
            {"hwmon": "diskchip", "label": "the drive"},
            {"hwmon": "absent", "label": "nothing"}]}})
        self.assertEqual(body.temperatures(cfg), [("the processor", 44.25), ("the drive", 38.0)])

    def test_temps_all(self):
        cfg = self.cfg({"body": {"sys_root": self.sysroot()}})
        self.assertEqual(body.temperatures(cfg),
                         [("cpuchip Tctl", 44.25), ("cpuchip Tccd1", 47.125), ("diskchip", 38.0)])

    def test_no_fans_and_load(self):
        root = self.sysroot()
        cfg = self.cfg({"body": {"sys_root": root}})
        self.assertEqual(body.fans(cfg), [])
        self.assertEqual(body.load_word(cfg), "light")  # 0.40 over 4 cpus
        with open(os.path.join(root, "proc", "loadavg"), "w") as fh:
            fh.write("5.20 3.00 2.00 1/1 1\n")
        self.assertEqual(body.load_word(cfg), "busy")
        with open(os.path.join(root, "sys", "class", "hwmon", "hwmon1", "fan1_input"), "w") as fh:
            fh.write("1250\n")
        self.assertEqual(body.fans(cfg), [1250])

    def test_disk_two_reads(self):
        root = self.sysroot()
        cfg = self.cfg({"body": {"sys_root": root}})
        first = body.disk_sample(cfg)
        self.assertEqual(first, {"sda": 10000})  # loop and partition left out
        self.assertAlmostEqual(body.disk_busy({"sda": 10000}, {"sda": 10200}, 1.0), 0.2)
        self.assertEqual(body.disk_word(0.01), "the disk is quiet")
        self.assertEqual(body.disk_word(0.2), "the disk is working")
        self.assertEqual(body.disk_word(0.9), "the disk is busy")
        stats = os.path.join(root, "proc", "diskstats")
        clock = {"t": 100.0}

        def fake_sleep(s):
            clock["t"] += s
            text = rd(stats).replace(" 10000 1400", " 10200 1600")
            wr(stats, text)

        c = self.ctx(cfg, self.NOW)
        with mock.patch.object(body, "_sleep", fake_sleep), \
                mock.patch.object(body, "_clock", lambda: clock["t"]):
            r = body.BodySense().read(c)
        self.assertIn("the disk is busy", r.text)  # 200 ms of I/O in 250 ms
        self.assertIn("cpuchip Tctl 44 C", r.text)
        self.assertIn("load light", r.text)
        self.assertTrue(r.changed)
        clock["t"] += 10
        with mock.patch.object(body, "_clock", lambda: clock["t"]):
            r2 = body.BodySense().read(c)
        self.assertIn("the disk is quiet", r2.text)
        self.assertTrue(r2.changed)
        clock["t"] += 10
        with mock.patch.object(body, "_clock", lambda: clock["t"]):
            r3 = body.BodySense().read(c)
        self.assertFalse(r3.changed)

    def test_selected_disk(self):
        cfg = self.cfg({"body": {"sys_root": self.sysroot(), "disk": "sda1"}})
        self.assertEqual(body.disk_sample(cfg), {"sda1": 9000})

    def test_temperature_verb(self):
        cfg = self.cfg({"body": {"sys_root": self.sysroot(), "temps": [
            {"hwmon": "cpuchip", "label": "the processor"}, {"hwmon": "diskchip", "label": "the drive"}]}})
        c = self.ctx(cfg, self.NOW)
        v = {s.name: s for s in senses.verbs(cfg)}["temperature"]
        r = v.handler(c, "")
        self.assertEqual(r.text, "The processor at 44 C, the drive at 38 C. There is no fan to hear. The load is light.")
        self.assertEqual(r.happened, "checked my temperature")

    def test_empty_tree(self):
        cfg = self.cfg({"body": {"sys_root": os.path.join(self.tmp, "nothing")}})
        self.assertIsNone(body.BodySense().read(self.ctx(cfg, self.NOW)))


# ----------------------------------------------------------------- house


SHOW_RUNNING = "ActiveState=active\nExecMainExitTimestamp=\n"
SHOW_DONE = "ActiveState=inactive\nExecMainExitTimestamp=Thu 2026-01-15 08:30:00 UTC\n"
SHOW_OLD = "ActiveState=inactive\nExecMainExitTimestamp=Mon 2026-01-12 03:20:00 UTC\n"


class House(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)
    SIG = {"kind": "unit", "unit": "nightly-copy.service",
           "running": "the disk is busy: the copy is running", "finished": "the copy finished"}

    def test_parse_show(self):
        self.assertEqual(house.parse_show(SHOW_DONE),
                         ("inactive", datetime(2026, 1, 15, 8, 30, tzinfo=UTC)))
        self.assertEqual(house.parse_show("ActiveState=failed\nExecMainExitTimestamp=n/a\n"), ("failed", None))

    def test_unit_running_then_finished(self):
        cfg = self.cfg({"house": {"signals": [self.SIG]}})
        c = self.ctx(cfg, self.NOW)
        calls = []
        answers = [SHOW_RUNNING, SHOW_RUNNING, SHOW_DONE]

        def fake(argv):
            calls.append(argv)
            return answers.pop(0)

        with mock.patch.object(house, "runner", fake):
            s = house.HouseSense()
            r1, r2, r3 = s.read(c), s.read(c), s.read(c)
        self.assertEqual(calls[0], ["systemctl", "--user", "show", "nightly-copy.service",
                                    "-p", "ActiveState", "-p", "ExecMainExitTimestamp"])
        self.assertEqual(r1.text, "the disk is busy: the copy is running.")
        self.assertTrue(r1.changed)
        self.assertFalse(r2.changed)
        self.assertEqual(r3.text, "the copy finished.")
        self.assertTrue(r3.changed)

    def test_unit_old_run_says_nothing(self):
        cfg = self.cfg({"house": {"signals": [self.SIG]}})
        with mock.patch.object(house, "runner", lambda argv: SHOW_OLD):
            self.assertIsNone(house.HouseSense().read(self.ctx(cfg, self.NOW)))
        with mock.patch.object(house, "runner", lambda argv: None):
            self.assertIsNone(house.HouseSense().read(self.ctx(cfg, self.NOW)))

    def test_file_signal(self):
        target = os.path.join(self.tmp, "edition.txt")
        wr(target, "x")
        cfg = self.cfg({"house": {"signals": [{"kind": "file", "path": target,
                                               "changed": "the morning paper got built"}]}})
        old = (self.NOW - timedelta(days=2)).timestamp()
        os.utime(target, (old, old))
        c = self.ctx(cfg, self.NOW)
        s = house.HouseSense()
        self.assertIsNone(s.read(c))
        new = (self.NOW - timedelta(minutes=1)).timestamp()
        os.utime(target, (new, new))
        r = s.read(c)
        self.assertEqual(r.text, "the morning paper got built.")
        self.assertTrue(r.changed)

    def test_no_signals_no_sense(self):
        self.assertNotIn("house", [p.name for p in senses.providers(self.cfg())])


# ------------------------------------------------------------------ song


class Song(Base):
    T0 = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)

    def test_header_parse(self):
        text = rd(os.path.join(FIX, "jukebox", "lanterns.txt"))
        s = song.parse_song(text, "fallback")
        self.assertEqual(s["title"], "Lanterns")
        self.assertEqual(s["by"], "someone")
        self.assertEqual(s["length"], 40)
        self.assertEqual(len(s["lines"]), 4)

    def test_no_length_no_title(self):
        s = song.parse_song("one\ntwo\nthree\n", "a tune")
        self.assertEqual(s["title"], "a tune")
        self.assertEqual(s["length"], 15)
        self.assertIsNone(song.parse_song("title: x\n\n\n", "y"))

    def test_line_timing(self):
        s = {"lines": ["a", "b", "c", "d"], "start": self.T0, "length": 40, "next": 0}
        lines, nxt = song.due_lines(s, self.T0)
        self.assertEqual((lines, nxt), (["a"], 1))
        s["next"] = nxt
        self.assertEqual(song.due_lines(s, self.T0 + timedelta(seconds=9))[0], [])
        lines, nxt = song.due_lines(s, self.T0 + timedelta(seconds=21))
        self.assertEqual((lines, nxt), (["b", "c"], 3))
        s["next"] = nxt
        self.assertEqual(song.due_lines(s, self.T0 + timedelta(seconds=99)), (["d"], 4))

    def test_twelve_line_cap(self):
        s = {"lines": [f"l{i}" for i in range(30)], "start": self.T0, "length": 30, "next": 0}
        lines, nxt = song.due_lines(s, self.T0 + timedelta(seconds=29.5))
        self.assertEqual(len(lines), 12)
        self.assertEqual(lines[-1], "l29")
        self.assertEqual(nxt, 30)

    def test_verb_and_sense(self):
        cfg = self.cfg()
        clock = {"t": self.T0}
        c = self.ctx(cfg, lambda: clock["t"])
        shutil.copy(os.path.join(FIX, "jukebox", "lanterns.txt"), c.paths.jukebox)
        verb = {v.name: v for v in senses.verbs(cfg)}["song"]
        r = verb.handler(c, "")
        self.assertEqual(r.text, "The song is on: Lanterns.")
        self.assertEqual(r.happened, "put the song on")
        self.assertTrue(song.is_on(c))
        self.assertEqual(verb.handler(c, "").text, "The song is already on.")
        sense = song.SongSense()
        self.assertEqual(sense.read(c).text, "the lamps went on along the quay")
        clock["t"] = self.T0 + timedelta(seconds=25)
        self.assertEqual(sense.read(c).text, "and one by one the boats came in\na gull complained about the rain")
        clock["t"] = self.T0 + timedelta(seconds=41)
        self.assertEqual(sense.read(c).text, "and the lamps went out one by one")
        self.assertEqual(sense.read(c).text, "the song ended.")
        self.assertIsNone(sense.read(c))
        self.assertFalse(song.is_on(c))
        heard = json.loads(rd(os.path.join(c.paths.state, "heard.json")))
        self.assertEqual(heard["heard"], ["lanterns.txt"])
        self.assertEqual(os.stat(os.path.join(c.paths.state, "heard.json")).st_mode & 0o777, 0o600)

    def test_new_before_heard(self):
        cfg = self.cfg()
        c = self.ctx(cfg, self.T0)
        for name, title in (("old.txt", "Old"), ("new.txt", "New")):
            wr(os.path.join(c.paths.jukebox, name), f"title: {title}\n\nla\n")
        os.utime(os.path.join(c.paths.jukebox, "old.txt"), (1, 1))
        folder.write_private(os.path.join(c.paths.state, "heard.json"), json.dumps({"heard": ["new.txt"]}))
        self.assertEqual(song._song(c, "").text, "The song is on: Old.")

    def test_no_song(self):
        cfg = self.cfg()
        c = self.ctx(cfg, self.T0)
        self.assertEqual(song._song(c, "").text, "No song is here.")

    def test_symlink_refused(self):
        cfg = self.cfg()
        c = self.ctx(cfg, self.T0)
        outside = os.path.join(self.tmp, "outside.txt")
        wr(outside, "title: Secret\n\nline\n")
        os.symlink(outside, os.path.join(c.paths.jukebox, "link.txt"))
        self.assertEqual(song._song(c, "").text, "No song is here.")
        self.assertIsNone(song.load_song(os.path.join(c.paths.jukebox, "link.txt")))

    def test_too_big_refused(self):
        c = self.ctx(self.cfg(), self.T0)
        wr(os.path.join(c.paths.jukebox, "big.txt"), "la\n" * 30000)
        self.assertEqual(song._song(c, "").text, "No song is here.")

    def test_dry_writes_nothing(self):
        c = self.ctx(self.cfg(), self.T0, dry=True)
        shutil.copy(os.path.join(FIX, "jukebox", "lanterns.txt"), c.paths.jukebox)
        song._song(c, "")
        self.assertFalse(os.path.exists(os.path.join(c.paths.state, "heard.json")))


# --------------------------------------------------------------- reading


class Reading(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)
    SRC = [{"name": "An almanac", "kind": "rss", "url": "https://feeds.example.org/rss"}]

    def feed(self, name="feed.xml"):
        return rd(os.path.join(FIX, name))

    def test_off_null_start(self):
        cfg = self.cfg({"reading": {"sources": self.SRC}})
        self.assertEqual(reading.status(cfg, date(2026, 1, 15)), "off (no start date set)")
        calls = []
        c = self.ctx(cfg, self.NOW, lambda u, h: calls.append(u) or self.feed())
        r = {v.name: v for v in senses.verbs(cfg)}["read"].handler(c, "")
        self.assertEqual(r.text, "Nothing to read here yet.")
        self.assertEqual(calls, [])

    def test_off_future_date_and_no_sources(self):
        cfg = self.cfg({"reading": {"start_date": "2026-02-01", "sources": self.SRC}})
        self.assertEqual(reading.status(cfg, date(2026, 1, 15)), "off (starts 2026-02-01)")
        c = self.ctx(cfg, self.NOW, lambda u, h: self.feed())
        self.assertEqual(reading._read(c, "").text, "Nothing to read here yet.")
        cfg = self.cfg({"reading": {"start_date": "2026-01-01"}})
        self.assertEqual(reading.status(cfg, date(2026, 1, 15)), "off (no sources)")
        self.assertEqual(reading._read(self.ctx(cfg, self.NOW), "").text, "Nothing to read here yet.")

    def test_on_with_feed(self):
        cfg = self.cfg({"reading": {"start_date": "2026-01-15", "sources": self.SRC, "max_chars": 200}})
        self.assertEqual(reading.status(cfg, date(2026, 1, 15)), "on (1 source)")
        calls = []

        def fake(url, hosts):
            calls.append((url, list(hosts)))
            return self.feed()

        c = self.ctx(cfg, self.NOW, fake)
        r1 = reading._read(c, "")
        self.assertEqual(calls[0], ("https://feeds.example.org/rss", ["feeds.example.org"]))
        self.assertEqual(r1.text, "From An almanac: On kettles.\n\nA kettle sings before it boils.\nNobody knows why it waits.")
        self.assertNotIn("alert", r1.text)
        self.assertNotIn("://", r1.text)
        self.assertEqual(r1.happened, "read something")
        r2 = reading._read(c, "")
        self.assertTrue(r2.text.startswith("From An almanac: The tide table."))
        self.assertEqual(reading._read(c, "").text, "Nothing new to read just now.")
        seen = json.loads(rd(os.path.join(c.paths.state, "read.json")))
        self.assertEqual(len(seen["read"]), 2)
        self.assertNotIn("kettles", json.dumps(seen))

    def test_atom_and_cut(self):
        items = reading.parse_feed(self.feed("atom.xml"))
        self.assertEqual(items[0]["title"], "Moss on the north side")
        self.assertEqual(reading.cut("one two three four", 9), "one two")
        self.assertEqual(reading.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>'), [])

    def test_shelf(self):
        cfg = self.cfg({"reading": {"start_date": "2026-01-01",
                                    "sources": [{"name": "the shelf", "kind": "shelf", "url": ""}]}})
        c = self.ctx(cfg, self.NOW, None)
        wr(os.path.join(c.paths.shelf, "a-small-poem.txt"), "The stove ticks as it cools.\n")
        r = reading._read(c, "")
        self.assertEqual(r.text, "From the shelf: a small poem.\n\nThe stove ticks as it cools.")

    def test_no_network_nothing(self):
        cfg = self.cfg({"reading": {"start_date": "2026-01-15", "sources": self.SRC}})
        self.assertEqual(reading._read(self.ctx(cfg, self.NOW, None), "").text, "Nothing new to read just now.")


# --------------------------------------------------------------- channel


class Channel(Base):
    NOW = datetime(2026, 1, 15, 8, 45, tzinfo=UTC)

    def inbox(self):
        d = os.path.join(self.tmp, "inbox")
        os.makedirs(d, exist_ok=True)
        return d

    def test_disabled(self):
        cfg = self.cfg({"channel": {"inbox_dir": self.inbox(), "allowed_sender_id": 42,
                                    "post_command": [sys.executable, "-c", "raise SystemExit(0)"]}})
        self.assertEqual(channel.status(cfg), "no channel yet")
        self.assertFalse(channel.enabled(cfg))
        msg = os.path.join(self.inbox(), "m1.json")
        wr(msg, json.dumps({"from_id": 42, "date": "2026-01-15T08:00:00+00:00", "text": "hi"}))
        self.assertEqual(channel.collect(self.ctx(cfg, self.NOW)), 0)
        self.assertTrue(os.path.exists(msg))
        with mock.patch.object(channel.subprocess, "run") as run:
            self.assertFalse(channel.post(cfg, "a piece"))
            run.assert_not_called()

    def test_collect(self):
        inbox = self.inbox()
        cfg = self.cfg({"channel": {"chat_id": -5, "allowed_sender_id": 42, "inbox_dir": inbox}})
        self.assertEqual(channel.status(cfg), "on")
        wr(os.path.join(inbox, "a.json"), json.dumps(
            {"from_id": 42, "date": "2026-01-15T08:00:05+00:00", "text": "a song for you\u200b\x07\nsecond line"}))
        wr(os.path.join(inbox, "b.json"), json.dumps(
            {"from_id": 99, "date": "2026-01-15T08:01:00+00:00", "text": "not from the person"}))
        wr(os.path.join(inbox, "c.json"), "not json")
        c = self.ctx(cfg, self.NOW)
        self.assertEqual(channel.collect(c), 1)
        self.assertEqual(os.listdir(inbox), [])
        self.assertEqual(c.memory["channel"], {"accepted": 1, "ignored": 2})
        files = os.listdir(c.paths.jukebox)
        self.assertEqual(files, ["channel-20260115-080005.txt"])
        path = os.path.join(c.paths.jukebox, files[0])
        self.assertEqual(rd(path), "title: from the channel\n\na song for you\nsecond line\n")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(song._song(c, "").text, "The song is on: from the channel.")
        self.assertNotIn("not from the person", json.dumps([rd(os.path.join(c.paths.jukebox, f))
                                                             for f in os.listdir(c.paths.jukebox)]))

    def test_no_allowed_sender_ignores_all(self):
        inbox = self.inbox()
        cfg = self.cfg({"channel": {"chat_id": -5, "inbox_dir": inbox}})
        wr(os.path.join(inbox, "a.json"), json.dumps({"from_id": 42, "date": "", "text": "x"}))
        c = self.ctx(cfg, self.NOW)
        self.assertEqual(channel.collect(c), 0)
        self.assertEqual(os.listdir(inbox), [])
        self.assertEqual(os.listdir(c.paths.jukebox), [])

    def test_post_enabled(self):
        out = os.path.join(self.tmp, "posted.txt")
        script = f"import sys; open({out!r}, 'w').write(sys.stdin.read())"
        cfg = self.cfg({"channel": {"chat_id": -5, "post_command": [sys.executable, "-c", script]}})
        self.assertTrue(channel.post(cfg, "It was windy."))
        self.assertEqual(rd(out), "It was windy.")
        bad = self.cfg({"channel": {"chat_id": -5, "post_command": [sys.executable, "-c", "raise SystemExit(4)"]}})
        self.assertFalse(channel.post(bad, "x"))
        self.assertFalse(channel.post(self.cfg({"channel": {"chat_id": -5}}), "x"))


# ------------------------------------------------------------- providers


class Providers(Base):
    def test_all_on(self):
        cfg = self.cfg({"house": {"signals": [House.SIG]}})
        self.assertEqual([p.name for p in senses.providers(cfg)], ["sky", "body", "house", "song"])
        self.assertEqual([v.name for v in senses.verbs(cfg)], ["window", "sun", "temperature", "song", "read"])
        for v in senses.verbs(cfg):
            self.assertRegex(v.name, r"^[a-z]{2,12}$")
            self.assertFalse(v.takes_text)
            self.assertTrue(v.says and "\n" not in v.says)

    def test_each_key(self):
        for key in ("sky", "body", "house", "song"):
            cfg = self.cfg({"senses": {key: False}, "house": {"signals": [House.SIG]}})
            self.assertNotIn(key, [p.name for p in senses.providers(cfg)])
        for key in ("window", "sun", "temperature", "song", "read"):
            cfg = self.cfg({"verbs": {key: False}})
            names = [v.name for v in senses.verbs(cfg)]
            self.assertNotIn(key, names)
            self.assertEqual(len(names), 4)
        # engine verb keys do not touch the sense verbs
        cfg = self.cfg({"verbs": {"journal": False, "write": False, "paper": False}})
        self.assertEqual(len(senses.verbs(cfg)), 5)

    def test_defaults_generic(self):
        cfg = self.cfg(base=False)
        self.assertEqual([p.name for p in senses.providers(cfg)], ["body", "song"])
        self.assertEqual([v.name for v in senses.verbs(cfg)], ["temperature", "song", "read"])

    def test_handlers_never_raise(self):
        cfg = self.cfg()
        c = self.ctx(cfg, datetime(2026, 1, 15, 8, 45, tzinfo=UTC))
        c.paths = None  # break every file path
        for v in senses.verbs(cfg):
            r = v.handler(c, "")
            self.assertIsInstance(r, VerbResult)
        for p in senses.providers(cfg):
            r = p.read(c)
            self.assertTrue(r is None or isinstance(r, SenseReading))


if __name__ == "__main__":
    unittest.main()
