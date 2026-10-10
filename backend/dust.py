"""How fast dust builds up on each roof, and the best day to clean it.

After every wash (a cleaning, or a day with at least 2 mm of rain) the panels' output, with haze already
taken out, falls slowly as dust settles. For each clean spell we look at how performance changes with the
days since that wash. All spells share one slope (the roof's dust rate) but keep their own starting level,
so a spell whose start we never saw still helps measure the slope.

Until a roof has enough days, a typical rate is used: about 0.4% of output lost per day, measured on an
IIT Bombay rooftop in the dry season (pv magazine India, July 2021).

Best cleaning interval: if dust costs r rupees more each day and one cleaning costs C, cleaning every
T = sqrt(2C / r) days keeps the total cost lowest (dust loss over a spell is r*T*T/2).
"""
from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, timedelta

import planner
import solar
import store
import verdict
import watch
import weather

TYPICAL_RATE = 0.004          # fraction of output lost per day of dust (IIT Bombay rooftop, dry season)
MIN_POINTS = 5                # evening readings needed before trusting the roof's own rate
MIN_SPREAD = 4                # ...spread over at least this many days since a wash
MAX_RATE = 0.03
MAX_LOSS = 0.5
MAX_INTERVAL = 30.0          # clean at least once a month: the straight-line dust model is not trusted further
DEFAULT_CLEAN_COST = 200.0    # rupees per cleaning, an assumption the owner can change
RAIN_WASH_MM = watch.RAIN_DAY_MM
RAIN_WAIT_MM, RAIN_WAIT_PROB = 5.0, 60
HISTORY_DAYS = 90
SKIP_CODES = {"fault", "check", "area"}   # those days are low for reasons other than dust


def _clean(rows):
    return [{k: v for k, v in r.items() if k not in ("pk", "sk")} for r in rows]


def rain_days(hourly: list[dict]) -> dict[str, float]:
    """Millimetres of rain per local day, from hourly rows (hour-ending times)."""
    out: dict[str, float] = defaultdict(float)
    for r in hourly:
        day = (solar.parse_local(r["time"]) - timedelta(hours=1)).date().isoformat()
        out[day] += r.get("precip") or 0.0
    return dict(out)


def wash_starts(events: list[dict], rain_mm: dict[str, float]) -> list[dict]:
    """The first clean day after each wash: a morning cleaning counts that day, a later one the next day;
    rain counts from the next day."""
    starts = {}
    for e in events:
        if e.get("type") != "cleaned":
            continue
        d = date.fromisoformat(e["time"][:10])
        if int(e["time"][11:13]) >= 11:
            d += timedelta(days=1)
        starts[d.isoformat()] = "cleaned"
    for day, mm in rain_mm.items():
        if mm >= RAIN_WASH_MM:
            nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            starts.setdefault(nxt, "rain")
    return [{"date": d, "kind": k} for d, k in sorted(starts.items())]


def fit(points: list[dict]) -> dict | None:
    """Shared slope, one intercept per spell. points: [{spell, x, y}]. None if there is not enough spread."""
    groups = defaultdict(list)
    for p in points:
        groups[p["spell"]].append(p)
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    n = sum(len(v) for v in groups.values())
    if n < MIN_POINTS:
        return None
    sxx = sxy = 0.0
    means = {}
    for k, v in groups.items():
        mx = sum(p["x"] for p in v) / len(v)
        my = sum(p["y"] for p in v) / len(v)
        means[k] = (mx, my)
        sxx += sum((p["x"] - mx) ** 2 for p in v)
        sxy += sum((p["x"] - mx) * (p["y"] - my) for p in v)
    spread = max(max(p["x"] for p in v) - min(p["x"] for p in v) for v in groups.values())
    if sxx <= 0 or spread < MIN_SPREAD:
        return None
    slope = sxy / sxx
    resid = sum((p["y"] - (means[k][1] + slope * (p["x"] - means[k][0]))) ** 2 for k, v in groups.items() for p in v)
    dof = n - len(groups) - 1
    se = math.sqrt(resid / dof / sxx) if dof > 0 else None
    starts = {k: means[k][1] - slope * means[k][0] for k in groups}
    return {"slope": slope, "se": se, "n": n, "spells": len(groups), "starts": starts}


def _kwh_per_day(meta: dict, verdicts: list[dict], today: date) -> float:
    recent = [float(v["expected_kwh"]) for v in verdicts[-14:] if v.get("final") and v.get("expected_kwh")]
    if len(recent) >= 3:
        return sum(recent) / len(recent)
    monthly, _ = planner.monthly_yield_per_kwp(meta["lat"], meta["lon"])
    return monthly[today.month - 1] * float(meta["kwp"]) / calendar.monthrange(today.year, today.month)[1]


def plan(sid: str) -> dict:
    meta = watch.get_system(sid)
    pk = f"SYSTEM#{sid}"
    today = date.fromisoformat(watch.today())
    verdicts = sorted(_clean(store.query(pk, "VERDICT#")), key=lambda v: v["date"])
    events = _clean(store.query(pk, "EVENT#"))

    start = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    try:
        hourly = weather.sunlight_hourly(meta["lat"], meta["lon"], meta["tilt"], meta["facing"], start, today.isoformat())
        rain_mm = rain_days(hourly)
    except Exception as exc:          # without rain history, cleanings alone mark the washes
        print(f"rain history unavailable: {exc}")
        rain_mm = {}
    washes = wash_starts(events, rain_mm)
    wash_dates = [w["date"] for w in washes]

    # each finished day: which spell it belongs to and how many days after that spell's wash it is
    points = []
    for v in verdicts:
        if not v.get("final") or v.get("performance_after_haze") is None or v.get("code") in SKIP_CODES:
            continue
        if v["date"] < start or rain_mm.get(v["date"], 0) >= RAIN_WASH_MM:
            continue                                   # rainy days are cloudy and half-washed
        y = float(v["performance_after_haze"])
        if not 0.3 <= y <= 1.3:
            continue
        before = [d for d in wash_dates if d <= v["date"]]
        if before:
            spell, origin, known = before[-1], before[-1], True
        else:                                          # before the first wash we know of: slope only
            spell, origin, known = "unknown", (verdicts[0]["date"]), False
        x = (date.fromisoformat(v["date"]) - date.fromisoformat(origin)).days
        points.append({"date": v["date"], "spell": spell, "x": x, "y": round(y, 3), "known": known})

    f = fit(points)
    learned = None
    if f:
        rate = min(MAX_RATE, max(0.0, -f["slope"]))
        good = f["n"] >= 10 and f["se"] is not None and f["se"] < max(rate, 0.001) / 2
        learned = {"n": f["n"], "spells": f["spells"], "confidence": "good" if good else "rough"}
        known_starts = [s for k, s in f["starts"].items() if k != "unknown"]
        clean_level = sum(known_starts) / len(known_starts) if known_starts else None
    else:
        rate, clean_level = TYPICAL_RATE, None

    unit_value = float(meta.get("unit_value") or verdict.DEFAULT_UNIT_VALUE)
    clean_cost = float(meta.get("clean_cost") if meta.get("clean_cost") is not None else DEFAULT_CLEAN_COST)
    kwh_day = _kwh_per_day(meta, verdicts, today)
    growth = rate * kwh_day * unit_value                     # rupees lost per day, added each dusty day

    last = next((w for w in reversed(washes) if w["date"] <= today.isoformat()), None)
    days_since = (today - date.fromisoformat(last["date"])).days if last else None
    loss_now = min(MAX_LOSS, rate * days_since) if days_since is not None else None
    best = None
    if growth > 0:
        best = int(round(min(MAX_INTERVAL, max(3.0, math.sqrt(2 * clean_cost / growth)))))

    try:
        forecast = weather.rain_forecast(meta["lat"], meta["lon"], 5)
    except Exception as exc:
        print(f"rain forecast unavailable: {exc}")
        forecast = []
    rain = next((d for d in forecast if d["date"] >= today.isoformat() and (d.get("rain_mm") or 0) >= RAIN_WAIT_MM
                 and (d.get("rain_prob_pct") is None or d["rain_prob_pct"] >= RAIN_WAIT_PROB)), None)

    if f and rate == 0:
        advice = {"code": "no_buildup"}
    elif last is None:
        advice = {"code": "unknown_wash"}
    else:
        due = date.fromisoformat(last["date"]) + timedelta(days=best or 0)
        if rain and date.fromisoformat(rain["date"]) <= max(due, today) + timedelta(days=2):
            advice = {"code": "wait_rain", "date": rain["date"], "rain_mm": round(rain["rain_mm"]), "rain_prob": rain.get("rain_prob_pct")}
        elif due <= today:
            advice = {"code": "clean_now", "date": today.isoformat()}
        else:
            advice = {"code": "clean_on", "date": due.isoformat()}

    line = None
    if clean_level is not None:
        xmax = max([p["x"] for p in points if p["known"]] + [days_since or 0, 7])
        line = {"y0": round(clean_level, 3), "rate": round(rate, 5), "x_max": xmax}

    return {
        "rate": round(rate, 5), "rate_source": "learned" if f else "typical", "typical_rate": TYPICAL_RATE,
        "learned": learned, "points_needed": max(0, MIN_POINTS - len(points)) if not f else 0,
        "clean_level": round(clean_level, 3) if clean_level is not None else None,
        "last_wash": last, "days_since": days_since,
        "loss_now": round(loss_now, 4) if loss_now is not None else None,
        "kwh_day": round(kwh_day, 2), "unit_value": unit_value,
        "rupees_day_now": round(loss_now * kwh_day * unit_value, 1) if loss_now is not None else None,
        "lost_since_wash_rs": round(growth * days_since * days_since / 2) if days_since is not None else None,
        "clean_cost": clean_cost, "best_interval_days": best,
        "advice": advice, "rain_ahead": rain,
        "points": [p for p in points if p["known"]], "line": line,
    }


def update_settings(sid: str, req: dict) -> dict:
    """Owner-editable numbers: what one cleaning costs, and what one unit is worth to them."""
    meta = watch.get_system(sid)
    meta.pop("system_id", None)
    changed = False
    if req.get("clean_cost") not in (None, ""):
        meta["clean_cost"] = watch._f(req["clean_cost"], "clean_cost", 0, 5000)
        changed = True
    if req.get("unit_value") not in (None, ""):
        meta["unit_value"] = watch._f(req["unit_value"], "unit_value", 1, 30)
        changed = True
    if not changed:
        raise ValueError("Nothing to change.")
    store.put(f"SYSTEM#{sid}", "META", meta)
    return {"system_id": sid, **meta}


if __name__ == "__main__":       # quick look: python backend/dust.py <system_id>
    import json
    import sys
    print(json.dumps(plan(sys.argv[1]), indent=1, default=str))
