"""Run SuryaWatch locally: serves the web app and the real Lambda handler on one port.

    python scripts/local_server.py            # live weather APIs (needs internet)
    python scripts/local_server.py --offline  # synthetic sunny-day weather, no internet needed

Then open http://localhost:8080 . Nothing is saved: DynamoDB writes are skipped.
"""
import http.server
import json
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import api      # noqa: E402
import planner  # noqa: E402
import solar    # noqa: E402
import weather  # noqa: E402

api.store.put = lambda *a, **k: None   # no database locally

if "--offline" in sys.argv:
    def fake_sun(lat, lon, tilt, facing, start, end):
        rows, day = [], datetime.fromisoformat(start).replace(tzinfo=solar.IST)
        for h in range(1, 25):
            t = day + timedelta(hours=h)
            cs = solar.clear_sky_hour_mean(lat, lon, t)
            rows.append({"time": t.strftime("%Y-%m-%dT%H:%M"), "ghi": cs * 0.82, "gti": cs * 0.95,
                         "temp": 33.0, "cloud": 10, "precip": 0.0})
        return rows
    weather.sunlight_hourly = fake_sun
    api.weather.sunlight_hourly = fake_sun
    planner.monthly_ghi = lambda lat, lon: (list(weather.DELHI_FALLBACK_GHI), "offline sample data")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "frontend"), **k)

    def _api(self, method):
        u = urlparse(self.path)
        length = int(self.headers.get("content-length") or 0)
        event = {"requestContext": {"http": {"method": method}}, "rawPath": u.path[len("/api"):],
                 "queryStringParameters": {k: v[0] for k, v in parse_qs(u.query).items()} or None,
                 "body": self.rfile.read(length).decode() if length else None}
        r = api.handler(event, None)
        self.send_response(r["statusCode"])
        for k, v in r["headers"].items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(r["body"].encode())

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        if self.path.startswith("/config.js"):
            body = b'window.SURYAWATCH_API = "/api";'
            self.send_response(200)
            self.send_header("content-type", "application/javascript")
            self.end_headers()
            return self.wfile.write(body)
        return super().do_GET()

    def do_POST(self):
        return self._api("POST")

    def do_OPTIONS(self):
        return self._api("OPTIONS")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"SuryaWatch running at http://localhost:{port}")
    http.server.ThreadingHTTPServer(("", port), Handler).serve_forever()
