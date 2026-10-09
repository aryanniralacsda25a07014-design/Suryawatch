"""Solar geometry and expected-output model for SuryaWatch.

Pure Python (standard library only) so the Lambda package needs no extra dependencies.

Conventions
-----------
* Times passed in are timezone-aware datetimes. Weather rows use local time strings
  (Asia/Kolkata) as returned by Open-Meteo, where each hourly value is the MEAN over the
  PRECEDING hour (the 10:00 row covers 09:00-10:00).
* Panel facing is a compass bearing: 0 = north, 90 = east, 180 = south, 270 = west.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# Default physical assumptions (documented in the README; all overridable per system)
DEFAULT_PR = 0.85          # performance ratio of a CLEAN system, excluding temperature loss
TEMP_COEFF = -0.0035       # power change per deg C above 25 C (typical mono-PERC module)
NOCT_RISE = 0.03125        # (NOCT 45 C - 20 C) / 800 W/m2 -> deg C of cell heating per W/m2


# --------------------------------------------------------------------------- sun position
def solar_position(lat: float, lon: float, when: datetime) -> tuple[float, float]:
    """Return (zenith_deg, azimuth_deg_from_north) using the NOAA general solar position
    equations (accurate to well under a degree, plenty for hourly energy estimates)."""
    t = when.astimezone(timezone.utc)
    doy = t.timetuple().tm_yday
    hour = t.hour + t.minute / 60 + t.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    true_solar_min = hour * 60 + eqtime + 4 * lon
    ha = math.radians(true_solar_min / 4 - 180)
    phi = math.radians(lat)
    cos_z = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    cos_z = max(-1.0, min(1.0, cos_z))
    zenith = math.degrees(math.acos(cos_z))
    az = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(phi) - math.tan(decl) * math.cos(phi))) + 180
    return zenith, az % 360


def clear_sky_ghi(zenith_deg: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance (W/m2)."""
    cz = math.cos(math.radians(zenith_deg))
    if cz <= 0.01:
        return 0.0
    return 1098.0 * cz * math.exp(-0.057 / cz)


def clear_sky_hour_mean(lat: float, lon: float, hour_end: datetime, steps: int = 12) -> float:
    """Mean clear-sky GHI over the hour ENDING at hour_end (matches Open-Meteo's convention)."""
    total = 0.0
    for i in range(steps):
        t = hour_end - timedelta(minutes=60) + timedelta(minutes=(i + 0.5) * 60 / steps)
        total += clear_sky_ghi(solar_position(lat, lon, t)[0])
    return total / steps


# --------------------------------------------------------------------------- conversions
def bearing_to_open_meteo_azimuth(bearing: float) -> float:
    """Compass bearing (0=N, 90=E, 180=S) -> Open-Meteo azimuth (0=S, -90=E, 90=W, +-180=N)."""
    a = (bearing - 180) % 360
    return a - 360 if a > 180 else a


def parse_local(ts: str) -> datetime:
    """'2026-10-09T10:00' (local IST) -> aware datetime."""
    return datetime.fromisoformat(ts).replace(tzinfo=IST)


# --------------------------------------------------------------------------- power model
def module_power_kw(kwp: float, gti: float, air_temp: float | None, pr: float = DEFAULT_PR) -> float:
    """Expected AC power (kW) for plane-of-array irradiance gti (W/m2)."""
    if gti <= 0:
        return 0.0
    temp_factor = 1.0
    if air_temp is not None:
        cell = air_temp + NOCT_RISE * gti
        temp_factor = 1 + TEMP_COEFF * (cell - 25)
    return max(0.0, kwp * gti / 1000.0 * pr * temp_factor)


def expected_hourly(system: dict, weather_rows: list[dict]) -> list[dict]:
    """Attach expected kW, clear-sky GHI to each hourly weather row.

    system: {lat, lon, kwp, pr_ref?}
    weather_rows: [{time, ghi, gti, temp, cloud, precip}] - hour-ending local times.
    """
    pr = float(system.get("pr_ref") or DEFAULT_PR)
    out = []
    for r in weather_rows:
        end = parse_local(r["time"])
        cs = clear_sky_hour_mean(system["lat"], system["lon"], end)
        kw = module_power_kw(float(system["kwp"]), r.get("gti") or 0.0, r.get("temp"), pr)
        out.append({**r, "clear_ghi": round(cs, 1), "expected_kw": round(kw, 4)})
    return out


def _rows_for_date(rows: list[dict], date: str) -> list[dict]:
    """Hour-ending rows whose hour falls on `date` (01:00 .. 24:00 i.e. next-day 00:00)."""
    day = datetime.fromisoformat(date).date()
    keep = []
    for r in rows:
        start = parse_local(r["time"]) - timedelta(hours=1)
        if start.date() == day:
            keep.append(r)
    return keep


def expected_energy_until(rows: list[dict], date: str, until: datetime | None = None) -> float:
    """Expected kWh produced on `date` from midnight up to `until` (default: whole day)."""
    total = 0.0
    for r in _rows_for_date(rows, date):
        end = parse_local(r["time"])
        start = end - timedelta(hours=1)
        if until is None or end <= until:
            total += r["expected_kw"]
        elif start < until < end:
            total += r["expected_kw"] * (until - start).total_seconds() / 3600
    return total


def expected_power_at(rows: list[dict], at: datetime) -> float:
    """Instantaneous expected kW at time `at`, interpolating between hour-centre means."""
    pts = [(parse_local(r["time"]) - timedelta(minutes=30), r["expected_kw"]) for r in rows]
    pts.sort()
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if t0 <= at <= t1:
            f = (at - t0).total_seconds() / (t1 - t0).total_seconds()
            return p0 + f * (p1 - p0)
    return 0.0


def day_sky_summary(rows: list[dict], date: str) -> dict:
    """Sunlight summary for one day: actual vs clear-sky horizontal irradiation."""
    day_rows = _rows_for_date(rows, date)
    ghi = sum((r.get("ghi") or 0.0) for r in day_rows) / 1000.0        # kWh/m2
    clear = sum(r.get("clear_ghi", 0.0) for r in day_rows) / 1000.0
    gti = sum((r.get("gti") or 0.0) for r in day_rows) / 1000.0
    rain = sum((r.get("precip") or 0.0) for r in day_rows)
    cloud_vals = [r.get("cloud") for r in day_rows if r.get("cloud") is not None and (r.get("ghi") or 0) > 0]
    return {
        "ghi_kwh_m2": round(ghi, 3),
        "clear_ghi_kwh_m2": round(clear, 3),
        "gti_kwh_m2": round(gti, 3),
        "sky_factor": round(ghi / clear, 3) if clear > 0 else None,   # 1.0 = perfectly clear day
        "rain_mm": round(rain, 1),
        "mean_cloud_pct": round(sum(cloud_vals) / len(cloud_vals), 0) if cloud_vals else None,
    }
