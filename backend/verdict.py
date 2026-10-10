"""Watch mode: compare what the roof produced with what the sunlight should have produced,
then split the gap into SKY loss (smog/haze - not the owner's fault) and PANEL loss
(dust or a fault - the owner can act).

How the split works
-------------------
Expected output uses Open-Meteo sunlight from weather models. Those models only know
average haze, so on a smoggy Delhi day they over-estimate sunlight. We therefore estimate the
extra haze loss from the measured aerosol optical depth (AOD) of that day:

    haze_loss ~= 0.25 x (AOD - 0.4), clipped to 0-40%

(each extra 0.1 of AOD removes roughly 2-3% of global sunlight at Delhi sun angles). The
remaining gap is panel loss. This is a transparent heuristic; the cleaning test on the team's
real roof is how we check it, and `calibrate_pr` folds that result back in.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from i18n import tr
from solar import day_sky_summary, expected_energy_until, parse_local

BASE_AOD = 0.4
HAZE_PER_AOD = 0.25
HEALTHY_AT = 0.92
FINAL_AFTER_HOUR = 18          # an E-Today reading after 6 PM counts as the day's total
DEFAULT_UNIT_VALUE = 6.0       # Rs per unit (bill saving + incentive), overridable per system


def haze_loss_estimate(aod: float | None) -> float:
    if aod is None:
        return 0.0
    return max(0.0, min(0.4, HAZE_PER_AOD * (aod - BASE_AOD)))


def daylight_mean(rows: list[dict], date: str, key: str) -> float | None:
    vals = []
    for r in rows:
        t = parse_local(r["time"])
        if t.date().isoformat() == date and 8 <= t.hour <= 17 and r.get(key) is not None:
            vals.append(float(r[key]))
    return round(sum(vals) / len(vals), 3) if vals else None


def latest_energy_reading(readings: list[dict], date: str) -> dict | None:
    """Most recent reading on `date` that has today's energy (E-Today)."""
    day = [r for r in readings if r.get("e_today_kwh") is not None and r["time"][:10] == date]
    return max(day, key=lambda r: r["time"]) if day else None


def diagnose_day(system: dict, date: str, readings: list[dict], hourly: list[dict],
                 air: list[dict], previous: list[dict] | None = None,
                 days_since_clean_or_rain: int | None = None,
                 rain_ahead: list[dict] | None = None, lang: str = "en") -> dict:
    """Build the day's verdict (messages in English or Hindi).

    system   : {kwp, pr_ref?, unit_value?}
    readings : [{time 'YYYY-MM-DDTHH:MM', e_today_kwh?, power_kw?, e_total_kwh?}]
    hourly   : output of solar.expected_hourly (must include `date`)
    air      : output of weather.air_quality_hourly
    previous : earlier verdicts (newest last) for sudden-drop detection
    """
    L = lang
    reading = latest_energy_reading(readings, date)
    sky = day_sky_summary(hourly, date)
    fault_state = inverter_fault(readings, date)
    aod = daylight_mean(air, date, "aod")
    pm25 = daylight_mean(air, date, "pm25")
    aqi = daylight_mean(air, date, "aqi")
    base = {"date": date, "sky": sky, "aod": aod, "pm25": pm25, "aqi": aqi}
    clock = lambda t: parse_local(t).strftime("%I:%M %p").lstrip("0")

    if fault_state:
        return {**base, "code": "fault", "title": tr(L, "fault_state.title"),
                "message": tr(L, "fault_state.msg", state=fault_state["state"], time=clock(fault_state["time"])),
                "final": False, "reading_time": fault_state["time"]}
    if reading is None:
        return {**base, "code": "no_data", "title": tr(L, "no_data.title"), "message": tr(L, "no_data.msg"),
                "final": False}

    at = parse_local(reading["time"])
    day_total = expected_energy_until(hourly, date, None)
    # Final when it is evening, or when less than 3% of the day's sunlight energy was still to come
    # (inverters switch off around sunset, so the last reading is often taken at about 5:45 PM).
    final = at.hour >= FINAL_AFTER_HOUR or (day_total > 0 and expected_energy_until(hourly, date, at) >= 0.97 * day_total)
    expected = day_total if final else expected_energy_until(hourly, date, at)
    actual = float(reading["e_today_kwh"])
    if expected < 0.05:
        return {**base, "code": "too_early", "title": tr(L, "too_early.title"), "message": tr(L, "too_early.msg"),
                "final": final, "actual_kwh": actual, "expected_kwh": round(expected, 2)}

    pi = actual / expected
    haze = haze_loss_estimate(aod)
    expected_after_haze = expected * (1 - haze)
    pi_adj = actual / expected_after_haze if expected_after_haze > 0 else pi
    panel_loss = max(0.0, 1 - pi_adj)
    # shares of what the sunlight allowed, so they add up: performance + shortfall = 100%,
    # and the shortfall is the haze plus whatever is left over (dust, shade or a fault on this roof)
    shortfall = max(0.0, 1 - pi)
    panel_share = max(0.0, 1 - pi - haze)
    unit_value = float(system.get("unit_value") or DEFAULT_UNIT_VALUE)
    lost_kwh = max(0.0, expected_after_haze - actual)
    day_fraction = 1.0 if final else max(expected / max(day_total, 0.01), 0.05)
    rupees_week = lost_kwh / day_fraction * 7 * unit_value

    result = {**base, "final": final, "reading_time": reading["time"],
              "actual_kwh": round(actual, 2), "expected_kwh": round(expected, 2),
              "performance": round(pi, 3), "haze_loss": round(haze, 3),
              "performance_after_haze": round(pi_adj, 3), "panel_loss": round(panel_loss, 3),
              "shortfall": round(shortfall, 3), "panel_share": round(panel_share, 3),
              "lost_kwh": round(lost_kwh, 2), "rupees_lost_per_week": round(rupees_week, 0)}

    cloudy = sky.get("sky_factor") is not None and sky["sky_factor"] < 0.45
    prev_adj = [p["performance_after_haze"] for p in (previous or [])[-3:]
                if p.get("performance_after_haze") is not None]
    pct = lambda x: f"{x * 100:.0f}"

    if pi_adj >= HEALTHY_AT:
        if haze >= 0.08:
            code = "smog"
            air_txt = ", ".join(p for p in (f"AOD {aod:.2f}" if aod is not None else "",
                                            f"PM2.5 {pm25:.0f}" if pm25 is not None else "") if p)
            msg = tr(L, "smog.msg", air=air_txt, haze=pct(haze))
        else:
            code = "healthy"
            msg = tr(L, "healthy.msg", pi=pct(pi))
    elif prev_adj and pi_adj < 0.6 * median(prev_adj) and not cloudy:
        code = "fault"
        msg = tr(L, "fault.msg", pi=pct(pi_adj), median=pct(median(prev_adj)))
    elif days_since_clean_or_rain is None or days_since_clean_or_rain >= 3:
        code = "dust"
        msg = tr(L, "dust.msg", loss=pct(panel_share), rupees=f"{rupees_week:.0f}")
        rain = next((d for d in (rain_ahead or [])[:2]
                     if (d.get("rain_mm") or 0) >= 5 and (d.get("rain_prob_pct") or 0) >= 60), None)
        msg += tr(L, "dust.rain", date=rain["date"]) if rain else tr(L, "dust.clean")
    else:
        code = "check"
        msg = tr(L, "check.msg", loss=pct(panel_share))

    if cloudy:
        msg += tr(L, "cloudy")
    if not final:
        msg += tr(L, "partial", time=clock(reading["time"]))
    return {**result, "code": code, "title": tr(L, f"{code}.title"), "message": msg}


FAULT_WORDS = ("fault", "error", "fail", "alarm", "isolation", "grid lost", "no grid", "over", "under", "abnormal")
OK_WORDS = ("normal", "waiting", "wait", "checking", "check", "standby", "start", "generating", "on-grid", "ongrid")


def inverter_fault(readings: list[dict], date: str) -> dict | None:
    """The latest reading of the day whose inverter state looks like a fault (e.g. 'Fault', 'F07', 'Error 31')."""
    for r in sorted((r for r in readings if r["time"][:10] == date and r.get("state")), key=lambda r: r["time"], reverse=True):
        s = str(r["state"]).lower()
        if any(w in s for w in OK_WORDS) and not any(w in s for w in FAULT_WORDS[:4]):
            return None                      # most recent state is fine
        if any(w in s for w in FAULT_WORDS) or re_code(s):
            return r
        return None
    return None


def re_code(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"\s*(f|e|err|w)\s*-?\s*\d{1,3}\s*", s, re.IGNORECASE))


def instant_check(hourly: list[dict], power_readings: list[dict]) -> list[dict]:
    """Pair each instantaneous power reading with the expected power at that minute."""
    from solar import expected_power_at
    out = []
    for r in power_readings:
        if r.get("power_kw") is None:
            continue
        t = parse_local(r["time"])
        exp = expected_power_at(hourly, t)
        out.append({"time": r["time"], "power_kw": r["power_kw"], "expected_kw": round(exp, 3),
                    "ratio": round(r["power_kw"] / exp, 3) if exp > 0.05 else None})
    return out


def calibrate_pr(system: dict, verdict: dict) -> float | None:
    """After a cleaning, a clear day's result tells us this roof's true clean performance ratio."""
    if verdict.get("performance_after_haze") is None or not verdict.get("final"):
        return None
    sky = verdict.get("sky") or {}
    if (sky.get("sky_factor") or 0) < 0.6:
        return None
    from solar import DEFAULT_PR
    current = float(system.get("pr_ref") or DEFAULT_PR)
    return round(max(0.55, min(0.95, current * verdict["performance_after_haze"])), 3)


def days_between(a: str, b: str) -> int:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days


def yesterday(date: str) -> str:
    return (datetime.fromisoformat(date) - timedelta(days=1)).date().isoformat()
