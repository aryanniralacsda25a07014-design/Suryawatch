"""Neighbourhood check: did rooftops nearby dip on the same day?

If most SuryaWatch rooftops within a few kilometres were also low, the cause is the sky (thick smog, a
dust storm, cloud the forecast missed), not one roof's panels. If they did fine and this roof did not,
the problem is on this roof: dust, new shade or a fault.

Privacy: only a count and the middle value (median) of at least two neighbours are returned. Never a
neighbour's name, ID, location or single figure. Demo rooftops are only compared with demo rooftops.
"""
from __future__ import annotations

import math
import time
from statistics import median

import store

RADIUS_KM = 5.0
MIN_NEIGHBOURS = 2        # fewer than this and we say so, rather than reveal one roof's figure
LOW = 0.85                # share of possible output (after haze) below which a day counts as a dip
GAP = 0.08                # this roof must be this much below its neighbours to call it "only you"
CACHE_SECONDS = 120
_cache: dict = {}


def forget() -> None:
    _cache.clear()


def distance_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _is_demo(meta: dict) -> bool:
    return bool(meta.get("demo")) or "(demo data)" in str(meta.get("name", "")).lower()


def _systems() -> list[dict]:
    hit = _cache.get("systems")
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    rows = [{"sid": m["pk"].split("#", 1)[1], "lat": float(m["lat"]), "lon": float(m["lon"]), "demo": _is_demo(m)}
            for m in store.scan_prefix("SYSTEM#", "META") if m.get("lat") is not None and m.get("lon") is not None]
    _cache["systems"] = (time.time(), rows)
    return rows


def nearby(sid: str, meta: dict) -> list[str]:
    demo = _is_demo(meta)
    return [s["sid"] for s in _systems()
            if s["sid"] != sid and s["demo"] == demo
            and distance_km(float(meta["lat"]), float(meta["lon"]), s["lat"], s["lon"]) <= RADIUS_KM]


def check(sid: str, meta: dict, date: str, mine: dict | None) -> dict:
    """Compare this roof's day with its neighbours' finished days. Returns codes and numbers only."""
    ids = nearby(sid, meta)
    perf = []
    for n in ids:
        v = store.get(f"SYSTEM#{n}", f"VERDICT#{date}")
        if v and v.get("final") and v.get("performance_after_haze") is not None and v.get("code") != "fault":
            perf.append(float(v["performance_after_haze"]))
    out = {"radius_km": RADIUS_KM, "nearby": len(ids), "reporting": len(perf)}
    if len(perf) < MIN_NEIGHBOURS:
        return {**out, "code": "too_few"}
    mid = median(perf)
    out.update(median=round(mid, 3), low_share=round(sum(p < LOW for p in perf) / len(perf), 2))
    p = mine.get("performance_after_haze") if mine and mine.get("final") else None
    if p is None:
        code = "area_low" if mid < LOW else "area_ok"
    elif p < LOW and mid < LOW:
        code = "area_wide"
    elif p < LOW and p < mid - GAP:
        code = "only_you"
    elif p >= LOW and mid < LOW:
        code = "you_ok_area_low"
    else:
        code = "all_ok"
    return {**out, "code": code}
