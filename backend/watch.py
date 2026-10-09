"""Watch mode service layer: systems, readings, events and the day view."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import solar
import store
import verdict
import weather

TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RAIN_DAY_MM = 2.0
UNKNOWN_DRY_DAYS = 8


class NotFound(LookupError):
    pass


def today() -> str:
    return datetime.now(solar.IST).date().isoformat()


def _f(value, name, lo, hi, required=False):
    if value is None or value == "":
        if required:
            raise ValueError(f"'{name}' is required.")
        return None
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{name}' must be a number.") from exc
    if not lo <= x <= hi:
        raise ValueError(f"'{name}' must be between {lo} and {hi}.")
    return x


# --------------------------------------------------------------------------- systems
def create_system(req: dict) -> dict:
    meta = {
        "name": (str(req.get("name") or "My rooftop").strip() or "My rooftop")[:60],
        "lat": _f(req.get("lat"), "lat", -90, 90, True),
        "lon": _f(req.get("lon"), "lon", -180, 180, True),
        "kwp": _f(req.get("kwp"), "kwp", 0.1, 500, True),
        "tilt": _f(req.get("tilt"), "tilt", 0, 90) if req.get("tilt") not in (None, "") else 20.0,
        "facing": _f(req.get("facing"), "facing", 0, 360) if req.get("facing") not in (None, "") else 180.0,
        "unit_value": _f(req.get("unit_value"), "unit_value", 1, 30) or verdict.DEFAULT_UNIT_VALUE,
        "pr_ref": solar.DEFAULT_PR,
        "created": store.now_iso(),
    }
    sid = store.new_id()
    store.put(f"SYSTEM#{sid}", "META", meta)
    return {"system_id": sid, **meta}


def get_system(sid: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{6,20}", sid or ""):
        raise NotFound("No such system.")
    meta = store.get(f"SYSTEM#{sid}", "META")
    if not meta:
        raise NotFound("No such system. It may have been created on a different server.")
    meta = {k: v for k, v in meta.items() if k not in ("pk", "sk")}
    return {"system_id": sid, **meta}


def cleaning_effect(verdicts: list[dict], events: list[dict], unit_value: float) -> dict | None:
    """Compare panel performance (haze removed) on the days before and after the latest cleaning."""
    cleans = [e for e in events if e.get("type") == "cleaned"]
    if not cleans:
        return None
    ev = cleans[-1]
    day, hour = ev["time"][:10], int(ev["time"][11:13])
    final = [v for v in verdicts if v.get("final") and v.get("performance_after_haze") is not None]
    before = [v for v in final if v["date"] < day][-3:]
    after = [v for v in final if v["date"] > day or (v["date"] == day and hour < 11)][:3]
    out = {"cleaned_at": ev["time"], "days_before": len(before), "days_after": len(after)}
    if not before or not after:
        return {**out, "ready": False}
    b = sum(v["performance_after_haze"] for v in before) / len(before)
    a = sum(v["performance_after_haze"] for v in after) / len(after)
    expected = sum(v.get("expected_kwh") or 0 for v in after) / len(after)
    gain_kwh_day = max(0.0, (a - b) * expected)
    return {**out, "ready": True, "before": round(b, 3), "after": round(a, 3),
            "gain_pct": round((a / b - 1) * 100, 1) if b > 0 else None,
            "kwh_per_day": round(gain_kwh_day, 2), "rupees_per_week": round(gain_kwh_day * 7 * unit_value, 0)}


def system_summary(sid: str) -> dict:
    meta = get_system(sid)
    verdicts = [{k: v for k, v in x.items() if k not in ("pk", "sk")} for x in store.query(f"SYSTEM#{sid}", "VERDICT#")]
    events = [{k: v for k, v in x.items() if k not in ("pk", "sk")} for x in store.query(f"SYSTEM#{sid}", "EVENT#")]
    alert_cfg = store.get(f"SYSTEM#{sid}", "ALERTS") or {}
    return {**meta, "verdicts": verdicts[-60:], "events": events[-20:],
            "cleaning": cleaning_effect(verdicts, events, float(meta.get("unit_value") or verdict.DEFAULT_UNIT_VALUE)),
            "alert_emails": len(alert_cfg.get("emails", []))}


# --------------------------------------------------------------------------- readings & events
def add_readings(sid: str, items: list[dict]) -> list[dict]:
    get_system(sid)
    if not isinstance(items, list) or not items:
        raise ValueError("Send at least one reading.")
    saved = []
    for it in items[:50]:
        t = str(it.get("time") or "")
        if not TIME_RE.match(t):
            raise ValueError("Each reading needs a time like 2026-10-09T14:00.")
        r = {
            "time": t,
            "power_kw": _f(it.get("power_kw"), "power_kw", 0, 500),
            "e_today_kwh": _f(it.get("e_today_kwh"), "e_today_kwh", 0, 5000),
            "e_total_kwh": _f(it.get("e_total_kwh"), "e_total_kwh", 0, 10_000_000),
            "state": (str(it.get("state")).strip()[:40] or None) if it.get("state") else None,
            "source": it.get("source") if it.get("source") in ("photo", "manual") else "manual",
            "photo_key": it.get("photo_key"),
            "created": store.now_iso(),
        }
        if r["power_kw"] is None and r["e_today_kwh"] is None and r["e_total_kwh"] is None and not r["state"]:
            raise ValueError(f"The reading at {t} has no numbers.")
        store.put(f"SYSTEM#{sid}", f"READING#{t}", r)
        saved.append(r)
    return saved


def delete_reading(sid: str, time: str) -> None:
    get_system(sid)
    if not TIME_RE.match(time or ""):
        raise ValueError("Give the reading's time.")
    store.delete(f"SYSTEM#{sid}", f"READING#{time}")


def add_event(sid: str, req: dict) -> dict:
    get_system(sid)
    kind = req.get("type")
    if kind not in ("cleaned", "note"):
        raise ValueError("Event type must be 'cleaned' or 'note'.")
    t = str(req.get("time") or datetime.now(solar.IST).strftime("%Y-%m-%dT%H:%M"))
    if not TIME_RE.match(t):
        raise ValueError("Event time must look like 2026-10-10T07:30.")
    ev = {"type": kind, "time": t, "note": str(req.get("note") or "")[:200], "created": store.now_iso()}
    store.put(f"SYSTEM#{sid}", f"EVENT#{t}", ev)
    return ev


# --------------------------------------------------------------------------- day view
def _dry_days(date: str, hourly: list[dict], events: list[dict]) -> int:
    """Days since the panels were last cleaned or rained on (>= 2 mm in a day)."""
    rain_by_day: dict[str, float] = {}
    for r in hourly:
        start = solar.parse_local(r["time"]) - timedelta(hours=1)
        day = start.date().isoformat()
        rain_by_day[day] = rain_by_day.get(day, 0.0) + (r.get("precip") or 0.0)
    candidates = [d for d, mm in rain_by_day.items() if mm >= RAIN_DAY_MM and d <= date]
    candidates += [e["time"][:10] for e in events if e.get("type") == "cleaned" and e["time"][:10] <= date]
    if not candidates:
        return UNKNOWN_DRY_DAYS
    return verdict.days_between(max(candidates), date)


def day_view(sid: str, date: str | None = None) -> dict:
    system = get_system(sid)
    date = date or today()
    if not DATE_RE.match(date):
        raise ValueError("Date must look like 2026-10-09.")
    if date > today():
        raise ValueError("That date is in the future.")
    pk = f"SYSTEM#{sid}"
    readings = [{k: v for k, v in x.items() if k not in ("pk", "sk")} for x in store.query(pk, f"READING#{date}")]
    events = [{k: v for k, v in x.items() if k not in ("pk", "sk")} for x in store.query(pk, "EVENT#")]
    start = (datetime.fromisoformat(date) - timedelta(days=7)).date().isoformat()

    rows = weather.sunlight_hourly(system["lat"], system["lon"], system["tilt"], system["facing"], start, date)
    hourly = solar.expected_hourly(system, rows)
    try:
        air = weather.air_quality_hourly(system["lat"], system["lon"], date, date)
    except Exception as exc:
        print(f"air quality unavailable: {exc}")
        air = []
    rain_ahead = []
    if date == today():
        try:
            rain_ahead = weather.rain_forecast(system["lat"], system["lon"], 3)
        except Exception as exc:
            print(f"rain forecast unavailable: {exc}")

    previous = [v for v in store.query(pk, "VERDICT#") if v.get("date", "") < date and v.get("final")]
    v = verdict.diagnose_day(system, date, readings, hourly, air, previous=previous,
                             days_since_clean_or_rain=_dry_days(date, hourly, events), rain_ahead=rain_ahead)
    if v.get("code") not in ("no_data", "too_early"):
        keep = ("date", "code", "title", "final", "actual_kwh", "expected_kwh", "performance",
                "performance_after_haze", "haze_loss", "panel_loss", "rupees_lost_per_week", "aod", "pm25")
        store.put(pk, f"VERDICT#{date}", {k: v.get(k) for k in keep})

    curve = []
    running = 0.0
    for r in solar._rows_for_date(hourly, date):
        running += r["expected_kw"]
        end = solar.parse_local(r["time"])
        if 5 <= end.hour <= 20:
            curve.append({"time": r["time"], "expected_kw": r["expected_kw"],
                          "expected_cum_kwh": round(running, 3), "clear_ghi": r["clear_ghi"], "ghi": r.get("ghi")})
    return {
        "system": system,
        "date": date,
        "is_today": date == today(),
        "verdict": v,
        "curve": curve,
        "readings": readings,
        "instant": verdict.instant_check(hourly, readings),
        "events": [e for e in events if e["time"][:10] <= date][-10:],
    }
