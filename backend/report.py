"""Installer report: a system's results over a chosen period, ready to print or send.

Everything here is numbers and short codes; the web app words them in English or Hindi.
Days already checked are read from storage; days with newer readings are re-checked (a few per request,
so the report stays fast even when the weather services are slow).
"""
from __future__ import annotations

from datetime import date, timedelta

import store
import verdict
import watch

MAX_DAYS = 92
MAX_RECHECK = 10
ROW_KEYS = ("date", "code", "final", "actual_kwh", "expected_kwh", "haze_loss", "performance",
            "performance_after_haze", "panel_loss", "lost_kwh", "pm25", "aod", "reading_time")


def _clean(rows):
    return [{k: v for k, v in r.items() if k not in ("pk", "sk")} for r in rows]


def _period(start: str | None, end: str | None) -> tuple[str, str]:
    today = watch.today()
    for value in (start, end):
        if value and not watch.DATE_RE.match(value):
            raise ValueError("Dates must look like 2026-10-09.")
    end = min(end or today, today)
    start = start or (date.fromisoformat(end) - timedelta(days=29)).isoformat()
    if start > end:
        raise ValueError("The start date must be before the end date.")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 > MAX_DAYS:
        raise ValueError(f"Choose a period of up to {MAX_DAYS} days.")
    return start, end


def build(sid: str, start: str | None = None, end: str | None = None, lang: str = "en") -> dict:
    meta = watch.get_system(sid)
    start, end = _period(start, end)
    pk = f"SYSTEM#{sid}"
    readings = _clean(store.query(pk, "READING#"))
    events = _clean(store.query(pk, "EVENT#"))
    in_range = [r for r in readings if start <= r["time"][:10] <= end]
    stored = {v["date"]: v for v in _clean(store.query(pk, "VERDICT#"))}

    rows, rechecked, unchecked = [], 0, 0
    for d in sorted({r["time"][:10] for r in in_range}):
        v = stored.get(d)
        changed = v is None or v.get("sig") != watch.readings_sig([r for r in in_range if r["time"][:10] == d])
        if changed and rechecked < MAX_RECHECK:
            try:
                v = watch.day_view(sid, d, lang)["verdict"]
                rechecked += 1
            except Exception as exc:      # weather service down: keep what we had
                print(f"report re-check failed for {sid} {d}: {exc}")
        if v is None or v.get("code") in (None, "no_data"):
            unchecked += 1
            rows.append({"date": d, "code": None})
            continue
        rows.append({k: v.get(k) for k in ROW_KEYS})

    # every verdict (not just this period) is needed for the promise and the cleaning comparison
    all_verdicts = sorted(_clean(store.query(pk, "VERDICT#")), key=lambda v: v["date"])
    unit_value = float(meta.get("unit_value") or verdict.DEFAULT_UNIT_VALUE)

    full = [r for r in rows if r.get("final") and r.get("actual_kwh") is not None and r.get("expected_kwh")]
    made = sum(float(r["actual_kwh"]) for r in full)
    allowed = sum(float(r["expected_kwh"]) for r in full)
    after_haze = sum(float(r["expected_kwh"]) * (1 - float(r.get("haze_loss") or 0)) for r in full)
    lost = sum(max(0.0, float(r["expected_kwh"]) * (1 - float(r.get("haze_loss") or 0)) - float(r["actual_kwh"]))
               for r in full)
    codes = [r.get("code") for r in rows if r.get("code")]
    counts = {c: codes.count(c) for c in ("healthy", "smog", "dust", "check", "fault")}

    faults = []
    for d in sorted({r["time"][:10] for r in in_range}):
        f = verdict.inverter_fault(in_range, d)
        if f:
            faults.append({"time": f["time"], "state": f["state"]})

    cleanings = [e["time"] for e in events if e.get("type") == "cleaned" and start <= e["time"][:10] <= end]
    effect = watch.cleaning_effect(all_verdicts, events, unit_value)
    if not effect or effect["cleaned_at"][:10] < start or effect["cleaned_at"][:10] > end:
        effect = None

    totals = sorted((r["time"], float(r["e_total_kwh"])) for r in in_range if r.get("e_total_kwh") is not None)
    counter = None
    if len(totals) >= 2 and totals[-1][1] >= totals[0][1]:
        counter = {"from_time": totals[0][0], "from_kwh": totals[0][1], "to_time": totals[-1][0],
                   "to_kwh": totals[-1][1], "units": round(totals[-1][1] - totals[0][1], 1)}

    try:
        promise = watch.promise_status(meta, readings, all_verdicts)
    except Exception as exc:
        print(f"promise check failed: {exc}")
        promise = None

    perf = made / after_haze if after_haze > 0 else None
    actions = []
    if faults or counts["fault"]:
        actions.append({"code": "fault", "n": max(len(faults), counts["fault"])})
    if counts["check"]:
        actions.append({"code": "check", "n": counts["check"]})
    if promise and promise.get("ready") and promise.get("all", {}).get("ratio") is not None \
            and promise["all"]["ratio"] < 0.95:
        actions.append({"code": "behind", "pct": round(promise["all"]["ratio"] * 100),
                        "units": round(promise["all"]["gap_kwh"])})
    if perf is not None and perf < 0.85 and cleanings:
        actions.append({"code": "low_after_clean", "pct": round(perf * 100)})
    if counts["dust"]:
        actions.append({"code": "dust", "n": counts["dust"]})
    if not actions and full:
        actions.append({"code": "ok"})

    return {
        "system": {k: meta.get(k) for k in ("system_id", "name", "kwp", "tilt", "facing", "lat", "lon",
                                             "unit_value", "created", "promise_kwh_year", "promise_source")},
        "from": start, "to": end, "made_on": watch.today(),
        "days": rows,
        "summary": {
            "days_with_readings": len(rows), "full_days": len(full), "unchecked_days": unchecked,
            "made_kwh": round(made, 1), "allowed_kwh": round(allowed, 1), "allowed_after_haze_kwh": round(after_haze, 1),
            "performance_after_haze": round(perf, 3) if perf is not None else None,
            "haze_kwh": round(allowed - after_haze, 1), "lost_kwh": round(lost, 1),
            "lost_rupees": round(lost * unit_value), "counts": counts,
        },
        "faults": faults, "cleanings": cleanings, "cleaning_effect": effect,
        "counter": counter, "promise": promise, "actions": actions,
        "healthy_at": verdict.HEALTHY_AT,
    }
