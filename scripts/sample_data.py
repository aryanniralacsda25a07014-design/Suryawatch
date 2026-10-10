"""Create a clearly labelled SAMPLE system with ten days of made-up readings, so every screen
(verdicts, charts, green history calendar, cleaning effect) can be shown before real data arrives.

The readings are generated from each day's real expected output (live weather) times a
"dirt factor": dusty panels for a week, a cleaning, then clean panels. They are NOT measurements.
A few sample neighbours nearby (clean panels) are added too, with one day when every roof dips together,
so the neighbourhood check has something to compare.

    python scripts/sample_data.py                               # local server (run local_server.py first)
    python scripts/sample_data.py --api https://xxxx.execute-api.us-east-1.amazonaws.com
"""
import argparse
import json
import random
import urllib.request
from datetime import date, timedelta

DIRT = [0.86, 0.85, 0.83, 0.82, 0.80, 0.79, 0.78]      # 7 dusty days, slowly getting worse
CLEAN = [0.95, 0.94, 0.94]                             # after cleaning
AREA_DIP_DAY, AREA_DIP = 2, 0.6                        # one dust-storm day when every roof nearby loses 40%


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def add_neighbours(base, a, days, dip_day):
    """A few sample rooftops 1-2 km away with clean panels, all dipping together on one dusty-sky day."""
    if a.neighbours <= 0:
        return
    print(f"Adding {a.neighbours} sample neighbours within 2 km (for the neighbourhood check)...", flush=True)
    rnd = random.Random(7)
    for n in range(a.neighbours):
        lat, lon = a.lat + rnd.uniform(-0.012, 0.012), a.lon + rnd.uniform(-0.012, 0.012)
        s = call(base, "POST", "/systems", {"name": f"Sample neighbour {n + 1} (demo data)", "demo": True, "lat": lat, "lon": lon,
                                            "kwp": a.kwp, "tilt": 20, "facing": 180, "unit_value": 6})
        for d in days:
            exp = call(base, "GET", f"/expected?lat={lat}&lon={lon}&kwp={a.kwp}&tilt=20&facing=180&date={d.isoformat()}")
            f = rnd.uniform(0.92, 0.97) * (AREA_DIP if d == dip_day else 1)
            call(base, "POST", f"/systems/{s['system_id']}/readings", {"readings": [
                {"time": f"{d.isoformat()}T17:50", "e_today_kwh": round(exp["expected_kwh"] * f, 1), "source": "manual"}]})
            call(base, "GET", f"/systems/{s['system_id']}/day?date={d.isoformat()}")
        print(f"  neighbour {n + 1} done", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8080/api")
    ap.add_argument("--lat", type=float, default=28.6139)
    ap.add_argument("--lon", type=float, default=77.2090)
    ap.add_argument("--kwp", type=float, default=3.0)
    ap.add_argument("--neighbours", type=int, default=3, help="sample rooftops nearby, for the neighbourhood check")
    a = ap.parse_args()
    base = a.api.rstrip("/")

    s = call(base, "POST", "/systems", {"name": "Sample rooftop (demo data)", "demo": True, "lat": a.lat, "lon": a.lon,
                                        "kwp": a.kwp, "tilt": 20, "facing": 180, "unit_value": 6})
    sid = s["system_id"]
    print(f"Created sample system {sid}")
    print("Fetching real weather for 10 days and building each day's verdict (about a minute)...", flush=True)
    today = date.today()
    days = [today - timedelta(days=i) for i in range(10, 0, -1)]   # the 10 days before today
    factors = DIRT + CLEAN
    clean_day = days[len(DIRT)]
    dip_day = days[AREA_DIP_DAY]
    add_neighbours(base, a, days, dip_day)
    total = 4000.0
    for d, f in zip(days, factors):
        exp = call(base, "GET", f"/expected?lat={a.lat}&lon={a.lon}&kwp={a.kwp}&tilt=20&facing=180&date={d.isoformat()}")
        if d == dip_day:
            f *= AREA_DIP
        made = round(exp["expected_kwh"] * f, 1)
        noon = max(h["expected_kw"] for h in exp["hourly"]) * f
        total += made
        if d == clean_day:
            call(base, "POST", f"/systems/{sid}/events", {"type": "cleaned", "time": f"{d.isoformat()}T07:30",
                                                         "note": "sample data"})
        call(base, "POST", f"/systems/{sid}/readings", {"readings": [
            {"time": f"{d.isoformat()}T13:00", "power_kw": round(noon, 2), "state": "Normal", "source": "manual"},
            {"time": f"{d.isoformat()}T17:45", "e_today_kwh": made, "e_total_kwh": round(total), "source": "manual"},
        ]})
        v = call(base, "GET", f"/systems/{sid}/day?date={d.isoformat()}")["verdict"]
        print(f"  {d}  made {made:5.1f} of {exp['expected_kwh']:5.1f} kWh  ->  {v['title']}", flush=True)
    page = base[:-4] if base.endswith("/api") else "<your web app address>"
    print(f"\nDone. Open this link (it includes the system ID):\n  {page}/?system={sid}#watch", flush=True)


if __name__ == "__main__":
    main()
