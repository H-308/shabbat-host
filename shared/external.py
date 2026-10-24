"""The external tool: Shabbat times (Hebcal) + Friday-evening weather (Open-Meteo).

Both APIs are free and keyless. Network access goes through `fetch_json`, which
tests replace with a fake, so the offline suite never touches the network.
The return value is deliberately tiny: ~60 tokens instead of two multi-KB JSON payloads.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

CITIES = {  # small offline geocoder: name -> (lat, lon)
    "גבעת שמואל": (32.0780, 34.8490), "givat shmuel": (32.0780, 34.8490),
    "תל אביב": (32.0853, 34.7818), "tel aviv": (32.0853, 34.7818),
    "ירושלים": (31.7683, 35.2137), "jerusalem": (31.7683, 35.2137),
    "חיפה": (32.7940, 34.9896), "haifa": (32.7940, 34.9896),
    "בני ברק": (32.0809, 34.8338), "רמת גן": (32.0684, 34.8248),
    "פתח תקווה": (32.0840, 34.8878), "באר שבע": (31.2518, 34.7913),
}


class ExternalError(RuntimeError):
    pass


def fetch_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "shabbat-host-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # network, HTTP or JSON errors all become one error type
        raise ExternalError(f"{type(e).__name__}: {e}") from e


def _geocode(city: str) -> tuple[float, float]:
    key = city.strip().lower()
    for name, coords in CITIES.items():
        if name == key or name in key or key in name:
            return coords
    raise ExternalError(f"unknown city '{city}'. known: גבעת שמואל, תל אביב, ירושלים, חיפה, בני ברק, רמת גן, פתח תקווה, באר שבע")


def shabbat_info(city: str, friday: dt.date, fetch=fetch_json) -> dict:
    lat, lon = _geocode(city)
    hq = urllib.parse.urlencode({
        "cfg": "json", "latitude": lat, "longitude": lon, "tzid": "Asia/Jerusalem",
        "M": "on", "lg": "he", "gy": friday.year, "gm": friday.month, "gd": friday.day,
    })
    heb = fetch(f"https://www.hebcal.com/shabbat?{hq}")
    out: dict = {"friday": friday.isoformat()}
    for it in heb.get("items", []):
        cat = it.get("category")
        if cat == "candles" and "candles" not in out:
            out["candles"] = it["date"][11:16]
        elif cat == "havdalah":
            out["havdalah"] = it["date"][11:16]
        elif cat == "parashat":
            out["parasha"] = it.get("hebrew") or it.get("title")
    if "candles" not in out:
        raise ExternalError("hebcal returned no candle-lighting time")

    wq = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Jerusalem",
        "hourly": "temperature_2m,precipitation_probability",
        "start_date": friday.isoformat(), "end_date": friday.isoformat(),
    })
    try:
        w = fetch(f"https://api.open-meteo.com/v1/forecast?{wq}")["hourly"]
        idx = [i for i, t in enumerate(w["time"]) if 18 <= int(t[11:13]) <= 22]
        temps = [w["temperature_2m"][i] for i in idx if w["temperature_2m"][i] is not None]
        rain = [w["precipitation_probability"][i] for i in idx if w["precipitation_probability"][i] is not None]
        if temps:
            out["eve_temp_c"] = round(sum(temps) / len(temps))
        if rain:
            out["eve_rain_pct"] = max(rain)
    except (ExternalError, KeyError, ValueError, TypeError) as e:
        # Forecasts only reach ~16 days ahead; the Shabbat times are still useful alone.
        out["weather"] = f"unavailable ({str(e)[:60]})"
    return out
