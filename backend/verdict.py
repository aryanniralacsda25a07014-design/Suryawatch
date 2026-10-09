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
                 rain_ahead: list[dict] | None = None) -> dict:
    """Build the day's verdict.

    system   : {kwp, pr_ref?, unit_value?}
    readings : [{time 'YYYY-MM-DDTHH:MM', e_today_kwh?, power_kw?, e_total_kwh?}]
    hourly   : output of solar.expected_hourly (must include `date`)
    air      : output of weather.air_quality_hourly
    previous : earlier verdicts (newest last) for sudden-drop detection
    """
    reading = latest_energy_reading(readings, date)
    sky = day_sky_summary(hourly, date)
    aod = daylight_mean(air, date, "aod")
    pm25 = daylight_mean(air, date, "pm25")
    aqi = daylight_mean(air, date, "aqi")
    base = {"date": date, "sky": sky, "aod": aod, "pm25": pm25, "aqi": aqi}

    if reading is None:
        return {**base, "code": "no_data", "title": "No reading yet",
                "message": "Upload a photo of the inverter display to check today.", "final": False}

    at = parse_local(reading["time"])
    final = at.hour >= FINAL_AFTER_HOUR
    expected = expected_energy_until(hourly, date, None if final else at)
    actual = float(reading["e_today_kwh"])
    if expected < 0.05:
        return {**base, "code": "too_early", "title": "Too early to judge",
                "message": "Check again after 10 AM.", "final": final,
                "actual_kwh": actual, "expected_kwh": round(expected, 2)}

    pi = actual / expected
    haze = haze_loss_estimate(aod)
    expected_after_haze = expected * (1 - haze)
    pi_adj = actual / expected_after_haze if expected_after_haze > 0 else pi
    panel_loss = max(0.0, 1 - pi_adj)
    unit_value = float(system.get("unit_value") or DEFAULT_UNIT_VALUE)
    lost_kwh = max(0.0, expected_after_haze - actual)
    day_fraction = 1.0 if final else max(expected / max(expected_energy_until(hourly, date, None), 0.01), 0.05)
    rupees_week = lost_kwh / day_fraction * 7 * unit_value

    result = {**base, "final": final, "reading_time": reading["time"],
              "actual_kwh": round(actual, 2), "expected_kwh": round(expected, 2),
              "performance": round(pi, 3), "haze_loss": round(haze, 3),
              "performance_after_haze": round(pi_adj, 3), "panel_loss": round(panel_loss, 3),
              "lost_kwh": round(lost_kwh, 2), "rupees_lost_per_week": round(rupees_week, 0)}

    cloudy = sky.get("sky_factor") is not None and sky["sky_factor"] < 0.45
    prev_adj = [p["performance_after_haze"] for p in (previous or [])[-3:]
                if p.get("performance_after_haze") is not None]

    if pi_adj >= HEALTHY_AT:
        if haze >= 0.08:
            code, title = "smog", "Smog day - your panels are fine"
            msg = (f"Haze (AOD {aod:.2f}, PM2.5 {pm25:.0f}) cut about {haze*100:.0f}% of the sunlight today. "
                   f"Your panels made what the hazy sky allowed. Nothing to fix.")
        else:
            code, title = "healthy", "Working well"
            msg = f"Your system made {pi*100:.0f}% of what today's sunlight should give. No action needed."
    elif prev_adj and pi_adj < 0.6 * median(prev_adj) and not cloudy:
        code, title = "fault", "Sudden drop - possible fault"
        msg = (f"Output fell to {pi_adj*100:.0f}% of expected, far below your recent "
               f"{median(prev_adj)*100:.0f}%. Check the inverter for an error code or a tripped switch, "
               f"then call your installer.")
    elif days_since_clean_or_rain is None or days_since_clean_or_rain >= 3:
        code, title = "dust", "Dust on panels - clean them"
        msg = (f"After allowing for haze, your panels made {panel_loss*100:.0f}% less than they should. "
               f"That is about ₹{rupees_week:.0f} a week.")
        rain = next((d for d in (rain_ahead or [])[:2]
                     if (d.get("rain_mm") or 0) >= 5 and (d.get("rain_prob_pct") or 0) >= 60), None)
        if rain:
            msg += f" Rain is likely on {rain['date']} - wait for it and save the water."
        else:
            msg += " Clean early morning or evening with plain water and a soft cloth."
    else:
        code, title = "check", "Lower than expected"
        msg = (f"Output is {panel_loss*100:.0f}% below expected even though the panels were cleaned or "
               f"rained on recently. Look for new shade, a loose cable or inverter warnings.")

    if cloudy:
        msg += " It was a cloudy day, so this estimate is less certain."
    if not final:
        msg += f" (Based on the {at.strftime('%I:%M %p').lstrip('0')} reading; the day is not over.)"
    return {**result, "code": code, "title": title, "message": msg}


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
