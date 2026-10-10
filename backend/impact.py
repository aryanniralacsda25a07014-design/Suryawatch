"""Public impact totals: what SuryaWatch has measured and planned so far, across every rooftop.

Only totals and counts leave this module: no names, system IDs, addresses or locations.
Demo systems (made by scripts/sample_data.py) are left out unless asked for, and the page says so.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta

import planner
import store
import verdict
import watch

CACHE_SECONDS = 60
CALENDAR_DAYS = 35
_cache: dict = {}


def _is_demo(meta: dict) -> bool:
    return bool(meta.get("demo")) or "(demo data)" in str(meta.get("name", "")).lower()


def _clean(rows):
    return [{k: v for k, v in r.items() if k not in ("pk", "sk")} for r in rows]


def units_tracked(readings: list[dict], verdicts: list[dict]) -> float:
    """Units (kWh) the system is known to have made while SuryaWatch watched it.

    Two lower bounds, and we keep the larger: the rise of the inverter's lifetime counter (E-Total)
    between the first and last photo of it, and the sum of each finished day's E-Today reading.
    """
    totals = sorted((r["time"], float(r["e_total_kwh"])) for r in readings if r.get("e_total_kwh") is not None)
    by_counter = max(0.0, totals[-1][1] - totals[0][1]) if len(totals) >= 2 else 0.0
    by_days = sum(float(v["actual_kwh"]) for v in verdicts if v.get("final") and v.get("actual_kwh") is not None)
    return max(by_counter, by_days)


def _system_stats(meta: dict, rows: list[dict]) -> dict:
    readings = _clean(r for r in rows if r["sk"].startswith("READING#"))
    verdicts = _clean(r for r in rows if r["sk"].startswith("VERDICT#"))
    events = _clean(r for r in rows if r["sk"].startswith("EVENT#"))
    alerts_cfg = next((r for r in rows if r["sk"] == "ALERTS"), {}) or {}
    unit_value = float(meta.get("unit_value") or verdict.DEFAULT_UNIT_VALUE)
    final = [v for v in verdicts if v.get("final")]
    units = units_tracked(readings, verdicts)
    clean = watch.cleaning_effect(verdicts, events, unit_value)
    reading_days = {r["time"][:10] for r in readings}
    return {
        "kwp": float(meta.get("kwp") or 0),
        "units": units,
        "rupees": units * unit_value,
        "days_checked": len(final),
        "days_with_readings": len(reading_days),
        "codes": [v.get("code") for v in final],
        "cleanings": sum(1 for e in events if e.get("type") == "cleaned"),
        "recovered_kwh_day": clean["kwh_per_day"] if clean and clean.get("ready") else 0.0,
        "has_alerts": bool(alerts_cfg.get("emails")),
        "final": final,
    }


def _plan_totals(plans: list[dict]) -> dict:
    """Roofs planned, counted once per roof (the same roof re-planned, or switched to Hindi, counts once)."""
    latest = {}
    for p in sorted(plans, key=lambda p: p.get("created", "")):
        r = p.get("result") or {}
        inp = r.get("inputs") or {}
        if inp.get("lat") is None or inp.get("lon") is None or not r.get("system_kw"):
            continue
        latest[(round(float(inp["lat"]), 4), round(float(inp["lon"]), 4))] = r
    res = list(latest.values())
    return {
        "roofs": len(res),
        "kw": round(sum(float(r["system_kw"]) for r in res), 1),
        "units_year": round(sum(float(r.get("yearly_generation_kwh") or 0) for r in res)),
        "co2_tonnes_year": round(sum(float(r.get("co2_tonnes_per_year") or 0) for r in res), 1),
        "subsidy": round(sum(float(r.get("central_subsidy") or 0) + float(r.get("state_subsidy") or 0) for r in res)),
    }


def _calendar(stats: list[dict], today: date) -> list[dict]:
    """Per day for the last few weeks: rooftops checked, their average share of possible output, units made."""
    by_day = defaultdict(list)
    for s in stats:
        for v in s["final"]:
            by_day[v["date"]].append(v)
    out = []
    for i in range(CALENDAR_DAYS - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        vs = by_day.get(d, [])
        perf = [float(v["performance_after_haze"]) for v in vs if v.get("performance_after_haze") is not None]
        out.append({"date": d, "rooftops": len(vs),
                    "performance": round(sum(perf) / len(perf), 3) if perf else None,
                    "units": round(sum(float(v.get("actual_kwh") or 0) for v in vs), 1),
                    "smog": sum(1 for v in vs if v.get("code") == "smog")})
    return out


def impact(include_demo: bool = False) -> dict:
    key = bool(include_demo)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    groups = defaultdict(list)
    for item in store.scan_all():
        groups[item["pk"]].append(item)
    plans, stats, demo_systems = [], [], 0
    for pk, rows in groups.items():
        meta = next((r for r in rows if r.get("sk") == "META"), None)
        if not meta:
            continue
        if pk.startswith("PLAN#"):
            plans.append(meta)
        elif pk.startswith("SYSTEM#"):
            if _is_demo(meta):
                demo_systems += 1
                if not include_demo:
                    continue
            stats.append(_system_stats(meta, rows))

    units = sum(s["units"] for s in stats)
    codes = [c for s in stats for c in s["codes"]]
    result = {
        "updated": store.now_iso(),
        "includes_demo": bool(include_demo and demo_systems),
        "demo_systems": demo_systems,
        "watch": {
            "rooftops": len(stats),
            "kw": round(sum(s["kwp"] for s in stats), 1),
            "units": round(units, 1),
            "co2_kg": round(units * planner.CO2_KG_PER_KWH, 1),
            "rupees": round(sum(s["rupees"] for s in stats)),
            "days_checked": sum(s["days_checked"] for s in stats),
            "days_with_readings": sum(s["days_with_readings"] for s in stats),
            "healthy_days": codes.count("healthy"),
            "smog_days": codes.count("smog"),
            "dust_days": codes.count("dust"),
            "fault_days": codes.count("fault"),
            "check_days": codes.count("check"),
            "area_days": codes.count("area"),
            "cleanings": sum(s["cleanings"] for s in stats),
            "recovered_kwh_day": round(sum(s["recovered_kwh_day"] for s in stats), 2),
            "with_alerts": sum(1 for s in stats if s["has_alerts"]),
        },
        "plan": _plan_totals(plans),
        "calendar": _calendar(stats, date.fromisoformat(watch.today())),
        "co2_kg_per_kwh": planner.CO2_KG_PER_KWH,
    }
    _cache[key] = (time.time(), result)
    return result
