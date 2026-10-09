"""Free public data sources used by SuryaWatch (no API keys needed).

* Open-Meteo forecast API  - hourly sunlight on the panel plane, temperature, cloud, rain
* Open-Meteo air-quality   - hourly PM2.5, US AQI, aerosol optical depth (haze), dust
* NASA POWER climatology   - long-term monthly sunlight, used by the planner
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from solar import bearing_to_open_meteo_azimuth

TZ = "Asia/Kolkata"
_CACHE: dict[str, object] = {}

# Approximate long-term monthly GHI for Delhi (kWh/m2/day). Used only if NASA POWER is unreachable.
DELHI_FALLBACK_GHI = [3.6, 4.6, 5.6, 6.4, 6.7, 6.0, 5.0, 4.8, 5.0, 4.8, 4.0, 3.4]


def _get_json(url: str, timeout: float = 12.0):
    if url in _CACHE:
        return _CACHE[url]
    req = urllib.request.Request(url, headers={"User-Agent": "SuryaWatch/1.0 (Environmental Hacks 2026)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    _CACHE[url] = data
    return data


def _columns_to_rows(hourly: dict, mapping: dict) -> list[dict]:
    times = hourly.get("time", [])
    rows = []
    for i, t in enumerate(times):
        row = {"time": t}
        for out_key, api_key in mapping.items():
            vals = hourly.get(api_key)
            row[out_key] = vals[i] if vals is not None and i < len(vals) else None
        rows.append(row)
    return rows


def sunlight_hourly(lat: float, lon: float, tilt: float, facing_bearing: float,
                    start_date: str, end_date: str) -> list[dict]:
    """Hourly rows: time (hour-ending, IST), ghi, gti (W/m2), temp (C), cloud (%), precip (mm)."""
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "hourly": "shortwave_radiation,global_tilted_irradiance,temperature_2m,cloud_cover,precipitation",
        "tilt": round(tilt, 1), "azimuth": round(bearing_to_open_meteo_azimuth(facing_bearing), 1),
        "timezone": TZ, "start_date": start_date, "end_date": end_date,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    return _columns_to_rows(data.get("hourly", {}), {
        "ghi": "shortwave_radiation", "gti": "global_tilted_irradiance",
        "temp": "temperature_2m", "cloud": "cloud_cover", "precip": "precipitation",
    })


def air_quality_hourly(lat: float, lon: float, start_date: str, end_date: str) -> list[dict]:
    """Hourly rows: time, pm25 (ug/m3), aqi (US AQI), aod (aerosol optical depth), dust (ug/m3)."""
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "hourly": "pm2_5,us_aqi,aerosol_optical_depth,dust",
        "timezone": TZ, "start_date": start_date, "end_date": end_date,
    }
    url = "https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode(params)
    data = _get_json(url)
    return _columns_to_rows(data.get("hourly", {}), {
        "pm25": "pm2_5", "aqi": "us_aqi", "aod": "aerosol_optical_depth", "dust": "dust",
    })


def rain_forecast(lat: float, lon: float, days: int = 5) -> list[dict]:
    """Daily rain forecast: [{date, rain_mm, rain_prob_pct}] for the next `days` days."""
    params = {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "daily": "precipitation_sum,precipitation_probability_max",
        "timezone": TZ, "forecast_days": days,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    d = _get_json(url).get("daily", {})
    out = []
    for i, day in enumerate(d.get("time", [])):
        out.append({
            "date": day,
            "rain_mm": (d.get("precipitation_sum") or [None])[i],
            "rain_prob_pct": (d.get("precipitation_probability_max") or [None])[i],
        })
    return out


def monthly_ghi(lat: float, lon: float) -> tuple[list[float], str]:
    """Long-term mean daily GHI per month (kWh/m2/day) and the source used."""
    url = ("https://power.larc.nasa.gov/api/temporal/climatology/point?"
           + urllib.parse.urlencode({"parameters": "ALLSKY_SFC_SW_DWN", "community": "RE",
                                     "longitude": round(lon, 3), "latitude": round(lat, 3),
                                     "format": "JSON"}))
    try:
        data = _get_json(url, timeout=15)
        vals = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        ghi = [float(vals[m]) for m in months]
        if all(g > 0 for g in ghi):
            return ghi, "NASA POWER long-term climatology"
    except Exception as exc:  # network or format problem: fall back, but say so
        print(f"NASA POWER unavailable: {exc}")
    return list(DELHI_FALLBACK_GHI), "approximate Delhi averages (NASA POWER unreachable)"
