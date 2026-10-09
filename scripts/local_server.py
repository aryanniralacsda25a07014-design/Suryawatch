"""Run SuryaWatch on your laptop: the web app and the real API code on one port.

    python scripts/local_server.py                      live weather data (needs internet)
    python scripts/local_server.py --mock-ai            ...and simulated photo reading (no AWS needed)
    python scripts/local_server.py --offline --mock-ai  no internet needed at all (sample weather)

Then open http://localhost:8080 . Data is saved in ./data/ (ignored by git).
Real AI photo reading needs AWS Bedrock, so it only works after deployment.
"""
import http.server
import os
import sys
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
for var in ("TABLE_NAME", "PHOTO_BUCKET"):
    os.environ.pop(var, None)                       # always use local storage here
if "--mock-ai" in sys.argv:
    os.environ["SURYAWATCH_MOCK_AI"] = "1"

import api      # noqa: E402
import planner  # noqa: E402
import solar    # noqa: E402
import weather  # noqa: E402

if "--offline" in sys.argv:
    def fake_sun(lat, lon, tilt, facing, start, end):
        rows = []
        day = datetime.fromisoformat(start).replace(tzinfo=solar.IST)
        last = datetime.fromisoformat(end).replace(tzinfo=solar.IST)
        while day <= last:
            haze = 0.78 if day.day % 2 == 0 else 0.86
            for h in range(1, 25):
                t = day + timedelta(hours=h)
                cs = solar.clear_sky_hour_mean(lat, lon, t)
                rows.append({"time": t.strftime("%Y-%m-%dT%H:%M"), "ghi": cs * haze, "gti": cs * haze * 1.12,
                             "temp": 33.0, "cloud": 10, "precip": 0.0})
            day += timedelta(days=1)
        return rows

    def fake_air(lat, lon, start, end):
        d = datetime.fromisoformat(start)
        aod = 1.1 if d.day % 2 == 0 else 0.45
        return [{"time": f"{start}T{h:02d}:00", "pm25": 160 if aod > 1 else 70, "aqi": 210 if aod > 1 else 140,
                 "aod": aod, "dust": 25} for h in range(24)]

    def fake_rain(lat, lon, days=5):
        base = datetime.now(solar.IST).date()
        return [{"date": (base + timedelta(days=i)).isoformat(), "rain_mm": 0.0, "rain_prob_pct": 5} for i in range(days)]

    for mod in (weather, api.weather):
        mod.sunlight_hourly, mod.air_quality_hourly, mod.rain_forecast = fake_sun, fake_air, fake_rain
    import watch  # noqa: E402
    watch.weather.sunlight_hourly, watch.weather.air_quality_hourly, watch.weather.rain_forecast = fake_sun, fake_air, fake_rain
    planner.monthly_ghi = lambda lat, lon: (list(weather.DELHI_FALLBACK_GHI), "offline sample data")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "frontend"), **k)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _api(self, method):
        u = urlparse(self.path)
        length = int(self.headers.get("content-length") or 0)
        event = {"requestContext": {"http": {"method": method}}, "rawPath": u.path[len("/api"):],
                 "queryStringParameters": {k: v[0] for k, v in parse_qs(u.query).items()} or None,
                 "body": self.rfile.read(length).decode("utf-8") if length else None}
        r = api.handler(event, None)
        body = r["body"].encode("utf-8")
        self.send_response(r["statusCode"])
        for k, v in r["headers"].items():
            self.send_header(k, v)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._api("GET")
        if self.path.startswith("/config.js"):
            body = b'window.SURYAWATCH_API = "/api";'
            self.send_response(200)
            self.send_header("content-type", "application/javascript")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return super().do_GET()

    def do_POST(self):
        return self._api("POST")

    def do_OPTIONS(self):
        return self._api("OPTIONS")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    mode = []
    if "--offline" in sys.argv:
        mode.append("sample weather")
    if "--mock-ai" in sys.argv:
        mode.append("simulated AI photo reading")
    print(f"SuryaWatch running at http://localhost:{port}" + (f"  ({', '.join(mode)})" if mode else ""))
    print("Press Ctrl+C to stop.")
    http.server.ThreadingHTTPServer(("", port), Handler).serve_forever()
