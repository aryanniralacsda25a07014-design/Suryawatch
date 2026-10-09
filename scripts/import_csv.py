"""Add real readings from a spreadsheet (CSV) to a SuryaWatch system - e.g. to copy readings typed on a
laptop into the deployed app, or to load a day of hourly display photos you transcribed.

CSV columns (header row required; leave a cell empty if you don't have that value):
    time,power_kw,e_today_kwh,e_total_kwh,state
    2026-10-10T09:00,0.85,0.6,4123,Normal
    2026-10-10T17:45,,9.4,4132,Normal

    python scripts/import_csv.py --system <id> readings.csv                                   # local server
    python scripts/import_csv.py --api https://xxxx.execute-api.us-east-1.amazonaws.com --system <id> readings.csv
"""
import argparse
import csv
import json
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--system", required=True)
    ap.add_argument("--api", default="http://localhost:8080/api")
    a = ap.parse_args()
    rows = []
    with open(a.csv, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            item = {"time": (r.get("time") or "").strip(), "source": "manual", "state": (r.get("state") or "").strip() or None}
            for k in ("power_kw", "e_today_kwh", "e_total_kwh"):
                v = (r.get(k) or "").strip()
                item[k] = float(v) if v else None
            rows.append(item)
    base = a.api.rstrip("/")
    for i in range(0, len(rows), 50):
        req = urllib.request.Request(f"{base}/systems/{a.system}/readings", method="POST",
                                     data=json.dumps({"readings": rows[i:i + 50]}).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(json.loads(resp.read().decode())["saved"], "readings saved")
    for d in sorted({r["time"][:10] for r in rows}):
        with urllib.request.urlopen(f"{base}/systems/{a.system}/day?date={d}", timeout=60) as resp:
            v = json.loads(resp.read().decode())["verdict"]
        print(f"  {d}: {v['title']}")


if __name__ == "__main__":
    main()
