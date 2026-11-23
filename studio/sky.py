"""The sky over the configured town: sun, moon and weather.

Sun and moon are computed on the machine (NOAA solar equations, a short
lunar series after Meeus). Weather comes from the Open-Meteo forecast API
(https://open-meteo.com, CC BY 4.0, no key), fetched only through
``ctx.fetch`` and cached in ``state/weather.json``. When the fetch fails or
there is no network, the sky is told from the sun and moon alone.

Provides the sense ``sky`` and the verbs ``window`` and ``sun``.
"""

import json
import math
import os
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .types import SenseReading, VerbResult, VerbSpec

WEATHER_HOST = "api.open-meteo.com"
WEATHER_FIELDS = (
    "temperature_2m,cloud_cover,wind_speed_10m,wind_direction_10m,"
    "precipitation,weather_code"
)
RISE_SET_ALTITUDE = -0.833  # degrees: refraction plus the sun's radius


# ---------------------------------------------------------------- sun math


def julian_day(when: datetime) -> float:
    """Julian day of an aware datetime."""
    when = when.astimezone(timezone.utc)
    return when.timestamp() / 86400.0 + 2440587.5


def _sun_core(jd: float):
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (
        math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
        + math.sin(3 * mr) * 0.000289
    )
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(
        math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long)))
    )
    y = math.tan(math.radians(eps / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr)
    )
    return app_long % 360.0, decl, eot


def sun_position(when: datetime, lat: float, lon: float) -> tuple[float, float]:
    """Geometric altitude and azimuth (degrees, azimuth from north, clockwise)."""
    _, decl, eot = _sun_core(julian_day(when))
    utc = when.astimezone(timezone.utc)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60.0 + utc.microsecond / 6e7
    tst = (minutes + eot + 4.0 * lon) % 1440.0
    ha = tst / 4.0 - 180.0
    latr, declr, har = map(math.radians, (lat, decl, ha))
    cos_z = math.sin(latr) * math.sin(declr) + math.cos(latr) * math.cos(declr) * math.cos(har)
    cos_z = max(-1.0, min(1.0, cos_z))
    zen = math.acos(cos_z)
    alt = 90.0 - math.degrees(zen)
    az = math.degrees(
        math.atan2(
            math.sin(har),
            math.cos(har) * math.sin(latr) - math.tan(declr) * math.cos(latr),
        )
    )
    az = (az + 180.0) % 360.0
    return alt, az


def sun_altitude(when: datetime, lat: float, lon: float) -> float:
    return sun_position(when, lat, lon)[0]


def sun_events(day: date, tz: ZoneInfo, lat: float, lon: float) -> tuple[datetime | None, datetime | None]:
    """Sunrise and sunset on a local calendar day, or None when it does not happen.

    Scans the day in 10-minute steps and bisects each crossing to the second.
    """
    start = datetime.combine(day, time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz).astimezone(timezone.utc)
    step = timedelta(minutes=10)
    rise = sett = None

    def f(t):
        return sun_altitude(t, lat, lon) - RISE_SET_ALTITUDE

    a = start
    fa = f(a)
    while a < end:
        b = min(a + step, end)
        fb = f(b)
        if (fa < 0) != (fb < 0):
            lo, hi, flo = a, b, fa
            while (hi - lo).total_seconds() > 1:
                mid = lo + (hi - lo) / 2
                fm = f(mid)
                if (fm < 0) == (flo < 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            crossing = (lo + (hi - lo) / 2).astimezone(tz)
            if fa < 0 and rise is None:
                rise = crossing
            elif fa >= 0 and sett is None:
                sett = crossing
        a, fa = b, fb
    return rise, sett


# --------------------------------------------------------------- moon math


def moon_elongation(when: datetime) -> float:
    """Moon longitude minus sun longitude, 0..360 degrees (0 new, 180 full)."""
    jd = julian_day(when)
    t = (jd - 2451545.0) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t
    d = math.radians(297.8501921 + 445267.1114034 * t)
    m = math.radians(357.5291092 + 35999.0502909 * t)
    mp = math.radians(134.9633964 + 477198.8675055 * t)
    f = math.radians(93.2720950 + 483202.0175233 * t)
    moon_long = (
        lp
        + 6.288774 * math.sin(mp)
        + 1.274027 * math.sin(2 * d - mp)
        + 0.658314 * math.sin(2 * d)
        + 0.213618 * math.sin(2 * mp)
        - 0.185116 * math.sin(m)
        - 0.114332 * math.sin(2 * f)
        + 0.058793 * math.sin(2 * d - 2 * mp)
        + 0.057066 * math.sin(2 * d - m - mp)
        + 0.053322 * math.sin(2 * d + mp)
        + 0.045758 * math.sin(2 * d - m)
    )
    sun_long, _, _ = _sun_core(jd)
    return (moon_long - sun_long) % 360.0


MOON_NAMES = (
    "new",
    "a waxing crescent",
    "at first quarter",
    "waxing gibbous",
    "full",
    "waning gibbous",
    "at last quarter",
    "a waning crescent",
)


def moon_phase(when: datetime) -> tuple[str, float]:
    """Phase words and illuminated fraction (0..1)."""
    elong = moon_elongation(when)
    idx = int(((elong + 22.5) % 360.0) // 45.0)
    lit = (1.0 - math.cos(math.radians(elong))) / 2.0
    return MOON_NAMES[idx], lit


def moon_sentence(when: datetime) -> str:
    name, _ = moon_phase(when)
    return f"The moon is {name}."


# ----------------------------------------------------------------- words

COMPASS = (
    "north", "north-east", "east", "south-east",
    "south", "south-west", "west", "north-west",
)


def compass(deg: float) -> str:
    return COMPASS[int(((deg % 360.0) + 22.5) // 45.0) % 8]


WEATHER_WORDS = {
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "thick drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "a thunderstorm", 96: "a thunderstorm with hail", 99: "a thunderstorm with hail",
}


def precip_kind(code: int | None) -> str:
    """'snow', 'rain', 'fog', 'storm' or ''."""
    if code is None:
        return ""
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if code >= 95:
        return "storm"
    return ""


def cloud_bucket(cover: float | None) -> int:
    if cover is None:
        return -1
    if cover <= 10:
        return 0
    if cover <= 40:
        return 1
    if cover <= 75:
        return 2
    return 3


CLOUD_SHORT = {0: "the sky is clear", 1: "a few clouds", 2: "broken cloud", 3: "cloud thick"}
CLOUD_SKY = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast"}


def wind_bucket(speed: float | None) -> int:
    if speed is None:
        return -1
    for i, top in enumerate((2.0, 6.0, 11.0, 17.0)):
        if speed < top:
            return i
    return 4


def light_phase(alt: float) -> int:
    """0 dark, 1 deep twilight, 2 twilight, 3 low sun, 4 day."""
    if alt < -12:
        return 0
    if alt < -6:
        return 1
    if alt < RISE_SET_ALTITUDE:
        return 2
    if alt < 10:
        return 3
    return 4


def light_words(phase: int, rising: bool) -> str:
    if phase == 0:
        return "dark"
    if phase == 1:
        return "still dark, a little grey low in the sky" if rising else "the last of the light is going"
    if phase == 2:
        return "the first grey light" if rising else "dusk"
    if phase == 3:
        return "the sun is low"
    return "daylight"


def light_change(old: int, new: int, rising: bool) -> str:
    if new > old:
        return {1: "the sky is getting a little grey.", 2: "the first grey light.",
                3: "the sun is up.", 4: "the sun is well up now."}[new]
    return {0: "it is dark now.", 1: "it is getting dark.", 2: "the sun went down.",
            3: "the sun is getting low."}[new]


def still_words(phase: int) -> str:
    return {0: "still dark.", 1: "still dark.", 2: "still grey.", 3: "the sun still low.",
            4: "still light."}[phase]


# --------------------------------------------------------------- weather


def weather_url(lat: float, lon: float, tz_name: str) -> str:
    q = urllib.parse.urlencode(
        {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": WEATHER_FIELDS,
            "wind_speed_unit": "ms",
            "timezone": tz_name,
        },
        safe=",",
    )
    return f"https://{WEATHER_HOST}/v1/forecast?{q}"


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return float(v)


def parse_weather(text: str) -> dict | None:
    """The 'current' block of an Open-Meteo answer, as plain numbers, or None."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        return None
    cur = data["current"]
    out = {
        "temperature": _num(cur.get("temperature_2m")),
        "cloud_cover": _num(cur.get("cloud_cover")),
        "wind_speed": _num(cur.get("wind_speed_10m")),
        "wind_direction": _num(cur.get("wind_direction_10m")),
        "precipitation": _num(cur.get("precipitation")),
        "weather_code": None,
    }
    code = _num(cur.get("weather_code"))
    if code is not None:
        out["weather_code"] = int(code)
    if all(v is None for v in out.values()):
        return None
    return out


def _cache_path(ctx) -> str:
    return os.path.join(ctx.paths.state, "weather.json")


def _read_cache(ctx, lat: float, lon: float, now: datetime, max_age: timedelta) -> dict | None:
    try:
        with open(_cache_path(ctx), encoding="utf-8") as fh:
            data = json.load(fh)
        if abs(float(data["latitude"]) - lat) > 1e-6 or abs(float(data["longitude"]) - lon) > 1e-6:
            return None
        fetched = datetime.fromisoformat(data["fetched_at"])
        if fetched.tzinfo is None:
            return None
        age = now - fetched
        if age < timedelta(0) or age > max_age:
            return None
        cur = data["current"]
        return cur if isinstance(cur, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(ctx, lat: float, lon: float, now: datetime, current: dict) -> None:
    if ctx.dry:
        return
    from .folder import write_private

    payload = {
        "version": 1,
        "fetched_at": now.isoformat(timespec="seconds"),
        "latitude": lat,
        "longitude": lon,
        "current": current,
    }
    try:
        write_private(_cache_path(ctx), json.dumps(payload, indent=1) + "\n")
    except OSError:
        pass


def weather(ctx) -> dict | None:
    """Current weather for the town: cache, else one fetch per wake-up, else None."""
    cfg = ctx.cfg
    if not cfg.weather.enabled or not cfg.town.name:
        return None
    mem = ctx.memory.setdefault("sky", {})
    now = ctx.now()
    lat, lon = cfg.town.latitude, cfg.town.longitude
    max_age = timedelta(minutes=cfg.weather.cache_minutes)
    cached = _read_cache(ctx, lat, lon, now, max_age)
    if cached is not None:
        mem["weather"] = cached
        return cached
    held = mem.get("weather")
    held_at = mem.get("weather_at")
    if held is not None and held_at is not None and now - held_at <= max_age:
        return held
    if ctx.fetch is None or mem.get("weather_tried"):
        return None  # no network, or the one try of this wake-up is spent
    mem["weather_tried"] = True
    try:
        text = ctx.fetch(weather_url(lat, lon, cfg.town.time_zone), [WEATHER_HOST])
    except Exception:
        return None
    current = parse_weather(text)
    if current is None:
        return None
    mem["weather"] = current
    mem["weather_at"] = now
    _write_cache(ctx, lat, lon, now, current)
    return current


# ----------------------------------------------------------- sky reading


def _town_tz(cfg) -> ZoneInfo:
    return ZoneInfo(cfg.town.time_zone)


def _state(ctx) -> dict:
    cfg = ctx.cfg
    now = ctx.now()
    lat, lon = cfg.town.latitude, cfg.town.longitude
    alt, az = sun_position(now, lat, lon)
    rising = sun_altitude(now + timedelta(minutes=10), lat, lon) > alt
    w = weather(ctx)
    return {"alt": alt, "az": az, "rising": rising, "weather": w, "now": now}


def _key(st: dict) -> tuple:
    w = st["weather"] or {}
    return (
        light_phase(st["alt"]),
        cloud_bucket(w.get("cloud_cover")),
        wind_bucket(w.get("wind_speed")),
        precip_kind(w.get("weather_code")),
    )


def _full_text(st: dict) -> str:
    parts = [light_words(light_phase(st["alt"]), st["rising"])]
    w = st["weather"]
    if w:
        code = w.get("weather_code")
        if code in WEATHER_WORDS:
            parts.append(WEATHER_WORDS[code])
        elif cloud_bucket(w.get("cloud_cover")) >= 0:
            parts.append(CLOUD_SHORT[cloud_bucket(w.get("cloud_cover"))])
        speed, direction = w.get("wind_speed"), w.get("wind_direction")
        if speed is not None:
            if speed < 0.5:
                parts.append("no wind")
            elif direction is not None:
                parts.append(f"wind {round(speed)} m/s from the {compass(direction)}")
            else:
                parts.append(f"wind {round(speed)} m/s")
        if w.get("temperature") is not None:
            parts.append(f"{round(w['temperature'])} C")
    return ". ".join(parts) + "."


def _change_text(old: tuple, new: tuple, st: dict) -> str:
    bits = []
    if new[0] != old[0]:
        bits.append(light_change(old[0], new[0], st["rising"]))
    if new[3] != old[3]:
        if new[3] and old[3]:
            bits.append({"snow": "it turned to snow.", "rain": "it turned to rain.",
                         "fog": "fog came in.", "storm": "a storm came up."}[new[3]])
        elif new[3]:
            bits.append({"snow": "it started to snow.", "rain": "it started to rain.",
                         "fog": "fog came in.", "storm": "a storm came up."}[new[3]])
        else:
            bits.append({"snow": "the snow stopped.", "rain": "the rain stopped.",
                         "fog": "the fog lifted.", "storm": "the storm passed."}[old[3]])
    if new[2] != old[2] and old[2] >= 0 and new[2] >= 0:
        bits.append("the wind picked up." if new[2] > old[2] else "the wind dropped.")
    if new[1] != old[1] and old[1] >= 0 and new[1] >= 0:
        bits.append("cloud is coming over." if new[1] > old[1] else "the cloud is breaking up.")
    if not bits:
        return _full_text(st)
    return " ".join(bits)


class SkySense:
    """Sense ``sky``: light, cloud, wind and warmth over the town."""

    name = "sky"

    def read(self, ctx):
        try:
            if not ctx.cfg.town.name:
                return None
            st = _state(ctx)
            mem = ctx.memory.setdefault("sky", {})
            key = _key(st)
            last = mem.get("last_key")
            mem["last_key"] = key
            if last is None:
                return SenseReading("sky", _full_text(st)[:160], True)
            if key != last:
                return SenseReading("sky", _change_text(last, key, st)[:160], True)
            return SenseReading("sky", still_words(key[0]), False)
        except Exception:
            return None


# ----------------------------------------------------------------- verbs


def _window(ctx, _arg: str) -> VerbResult:
    cfg = ctx.cfg
    st = _state(ctx)
    town = cfg.town.name
    w = st["weather"]
    sentences = []
    if w:
        bucket = cloud_bucket(w.get("cloud_cover"))
        code = w.get("weather_code")
        kind = precip_kind(code)
        if kind == "fog":
            sky = f"In {town} the sky is hidden in {WEATHER_WORDS[code]}."
        elif bucket >= 0:
            sky = f"In {town} the sky is {CLOUD_SKY[bucket]}"
            if kind:
                sky += f" with {WEATHER_WORDS[code]}"
            sky += "."
        elif kind:
            sky = f"In {town} there is {WEATHER_WORDS[code]}."
        else:
            sky = f"In {town} the sky is there, but its weather cannot be seen just now."
        sentences.append(sky)
        speed, direction = w.get("wind_speed"), w.get("wind_direction")
        if speed is not None:
            if speed < 0.5:
                sentences.append("No wind.")
            elif direction is not None:
                sentences.append(f"Wind {round(speed)} m/s from the {compass(direction)}.")
            else:
                sentences.append(f"Wind {round(speed)} m/s.")
        if w.get("temperature") is not None:
            sentences.append(f"{round(w['temperature'])} C.")
    else:
        sentences.append(f"In {town} the weather cannot be seen just now.")
    phase = light_phase(st["alt"])
    if st["alt"] >= RISE_SET_ALTITUDE:
        sentences.append(f"The sun is up in the {compass(st['az'])}.")
    elif phase == 0:
        sentences.append("The sun is below the horizon. It is dark.")
    else:
        sentences.append("The sun is below the horizon.")
    sentences.append(moon_sentence(st["now"]))
    return VerbResult(" ".join(sentences)[:600], happened="looked out the window")


def _clock(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _sun(ctx, _arg: str) -> VerbResult:
    cfg = ctx.cfg
    tz = _town_tz(cfg)
    now = ctx.now()
    lat, lon = cfg.town.latitude, cfg.town.longitude
    alt, az = sun_position(now, lat, lon)
    rising = sun_altitude(now + timedelta(minutes=10), lat, lon) > alt
    rise, sett = sun_events(now.astimezone(tz).date(), tz, lat, lon)
    local = now.astimezone(tz)
    degrees = abs(round(alt))
    if alt >= RISE_SET_ALTITUDE:
        unit = "degree" if degrees == 1 else "degrees"
        first = f"The sun is up, {degrees} {unit} above the horizon in the {compass(az)}."
        if alt < 10:
            first += " It gives little warmth."
        else:
            first += " There is some warmth in it."
    else:
        unit = "degree" if degrees == 1 else "degrees"
        first = f"The sun is down, {degrees} {unit} below the horizon."
    times = []
    if rise is None and sett is None:
        times.append("The sun does not set today." if alt >= RISE_SET_ALTITUDE
                     else "The sun does not rise today.")
    else:
        if rise is not None:
            times.append(("It rose at " if rise <= local else "It rises at ") + _clock(rise) + ".")
        if sett is not None:
            times.append(("It set at " if sett <= local else "It sets at ") + _clock(sett) + ".")
    if alt < RISE_SET_ALTITUDE and rising and rise is not None and rise > local:
        times.append("It is on its way up.")
    return VerbResult(" ".join([first] + times)[:600], happened="felt the sun")


def sense(cfg):
    if not cfg.senses.sky or not cfg.town.name:
        return None
    return SkySense()


def verb_specs(cfg) -> list:
    if not cfg.town.name:
        return []
    out = []
    if cfg.verbs.window:
        out.append(VerbSpec("window", "look out the window", False, _guard(_window, "window")))
    if cfg.verbs.sun:
        out.append(VerbSpec("sun", "feel the sun", False, _guard(_sun, "sun")))
    return out


def _guard(fn, _name):
    def handler(ctx, arg):
        try:
            return fn(ctx, arg)
        except Exception:
            return VerbResult("That did not work just now.")
    return handler
