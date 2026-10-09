"""Offline tests for Watch mode (systems, readings, photo reading, day verdicts)."""
import base64
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.pop("TABLE_NAME", None)
os.environ.pop("PHOTO_BUCKET", None)

import api      # noqa: E402
import reader   # noqa: E402
import solar    # noqa: E402
import store    # noqa: E402
import watch    # noqa: E402
import weather  # noqa: E402


def fake_sun(lat, lon, tilt, facing, start, end):
    rows, day = [], datetime.fromisoformat(start).replace(tzinfo=solar.IST)
    last = datetime.fromisoformat(end).replace(tzinfo=solar.IST)
    while day <= last:
        for h in range(1, 25):
            t = day + timedelta(hours=h)
            cs = solar.clear_sky_hour_mean(lat, lon, t)
            rows.append({"time": t.strftime("%Y-%m-%dT%H:%M"), "ghi": cs * 0.85, "gti": cs * 0.95,
                         "temp": 32.0, "cloud": 5, "precip": 0.0})
        day += timedelta(days=1)
    return rows


class WatchApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store._LOCAL_DIR = self.tmp.name
        self._orig = (weather.sunlight_hourly, weather.air_quality_hourly, weather.rain_forecast)
        weather.sunlight_hourly = fake_sun
        weather.air_quality_hourly = lambda lat, lon, s, e: [
            {"time": f"{s}T{h:02d}:00", "pm25": 60, "aqi": 120, "aod": 0.4, "dust": 10} for h in range(24)]
        weather.rain_forecast = lambda lat, lon, days=5: []
        os.environ["SURYAWATCH_MOCK_AI"] = "1"

    def tearDown(self):
        weather.sunlight_hourly, weather.air_quality_hourly, weather.rain_forecast = self._orig
        os.environ.pop("SURYAWATCH_MOCK_AI", None)
        self.tmp.cleanup()

    def call(self, method, path, body=None, params=None):
        ev = {"requestContext": {"http": {"method": method}}, "rawPath": path,
              "queryStringParameters": params, "body": json.dumps(body) if body is not None else None}
        r = api.handler(ev, None)
        return r["statusCode"], (json.loads(r["body"]) if r["body"] else None)

    def make_system(self):
        code, body = self.call("POST", "/systems", {"name": "Test roof", "lat": 28.7, "lon": 77.1, "kwp": 3,
                                                    "tilt": 20, "facing": 180})
        self.assertEqual(code, 200, body)
        return body["system_id"]

    def test_full_day_flow(self):
        sid = self.make_system()
        date = "2026-10-08"
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, date, date))
        full = solar.expected_energy_until(hourly, date)
        code, body = self.call("POST", f"/systems/{sid}/readings", {"readings": [
            {"time": f"{date}T12:00", "power_kw": 1.9, "source": "manual"},
            {"time": f"{date}T18:30", "e_today_kwh": round(full * 0.75, 2), "source": "manual"},
        ]})
        self.assertEqual(code, 200, body)
        code, body = self.call("GET", f"/systems/{sid}/day", params={"date": date})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["verdict"]["code"], "dust")
        self.assertTrue(body["verdict"]["final"])
        self.assertEqual(len(body["readings"]), 2)
        self.assertTrue(body["curve"] and body["instant"])
        code, summary = self.call("GET", f"/systems/{sid}")
        self.assertEqual(summary["verdicts"][0]["code"], "dust")

    def test_cleaning_event_changes_verdict(self):
        sid = self.make_system()
        date = "2026-10-08"
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, date, date))
        full = solar.expected_energy_until(hourly, date)
        self.call("POST", f"/systems/{sid}/events", {"type": "cleaned", "time": f"{date}T07:00"})
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{date}T19:00", "e_today_kwh": full * 0.75}]})
        _, body = self.call("GET", f"/systems/{sid}/day", params={"date": date})
        self.assertEqual(body["verdict"]["code"], "check")      # clean panels but still low

    def test_photo_mock_and_validation(self):
        sid = self.make_system()
        img = base64.b64encode(b"\xff\xd8\xff" + os.urandom(4000)).decode()
        code, body = self.call("POST", f"/systems/{sid}/photo", {"image_base64": img})
        self.assertEqual(code, 200, body)
        self.assertTrue(body["ai_available"])
        self.assertIsNotNone(body["e_today_kwh"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, body["photo_key"])))
        self.assertEqual(self.call("POST", f"/systems/{sid}/photo", {"image_base64": "abc"})[0], 400)

    def test_errors(self):
        self.assertEqual(self.call("GET", "/systems/ffffffffff")[0], 404)
        sid = self.make_system()
        self.assertEqual(self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": "bad"}]})[0], 400)
        self.assertEqual(self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": "2026-10-08T10:00"}]})[0], 400)
        self.assertEqual(self.call("GET", f"/systems/{sid}/day", params={"date": "2999-01-01"})[0], 400)
        self.assertEqual(self.call("POST", "/systems", {"lat": 28.7, "lon": 77.1})[0], 400)

    def test_delete_reading(self):
        sid = self.make_system()
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": "2026-10-08T10:00", "power_kw": 1.2}]})
        self.assertEqual(self.call("POST", f"/systems/{sid}/readings/delete", {"time": "2026-10-08T10:00"})[0], 200)
        _, body = self.call("GET", f"/systems/{sid}/day", params={"date": "2026-10-08"})
        self.assertEqual(body["readings"], [])


class ReaderTests(unittest.TestCase):
    def test_parse_plain_json(self):
        r = reader.parse_reply('{"power_kw": 2.31, "e_today_kwh": 9.8, "e_total_kwh": 4521, "confidence": "high"}')
        self.assertEqual((r["power_kw"], r["e_today_kwh"], r["e_total_kwh"]), (2.31, 9.8, 4521.0))

    def test_parse_fenced_and_units(self):
        text = 'Here you go:\n```json\n{"power_kw": "2310 W", "e_today_kwh": "11.2kWh", "e_total_kwh": null}\n```'
        r = reader.parse_reply(text)
        self.assertEqual(r["power_kw"], 2.31)
        self.assertEqual(r["e_today_kwh"], 11.2)
        self.assertIsNone(r["e_total_kwh"])
        self.assertEqual(r["confidence"], "low")

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ValueError):
            reader.parse_reply("I cannot read this image.")


class StateTests(unittest.TestCase):
    def test_fault_state(self):
        import verdict
        rows = [{"time": "2026-10-08T11:00", "state": "Normal", "power_kw": 1.3},
                {"time": "2026-10-08T14:00", "state": "Fault F07"}]
        self.assertEqual(verdict.inverter_fault(rows, "2026-10-08")["time"], "2026-10-08T14:00")
        rows.append({"time": "2026-10-08T15:00", "state": "Normal"})
        self.assertIsNone(verdict.inverter_fault(rows, "2026-10-08"))
        self.assertTrue(verdict.re_code("E31"))
        self.assertIsNone(verdict.inverter_fault([{"time": "2026-10-08T07:00", "state": "Waiting"}], "2026-10-08"))

    def test_reader_state(self):
        r = reader.parse_reply('{"power_kw": "1335W", "state": "Normal", "e_today_kwh": null}')
        self.assertEqual(r["power_kw"], 1.335)
        self.assertEqual(r["state"], "Normal")


class Stage3Tests(WatchApiTests):
    def test_alerts_local_and_daily_check(self):
        import daily_check
        sid = self.make_system()
        self.assertEqual(self.call("POST", f"/systems/{sid}/alerts", {"email": "bad"})[0], 400)
        code, body = self.call("POST", f"/systems/{sid}/alerts", {"email": "owner@example.com"})
        self.assertEqual(code, 200, body)
        code, body = self.call("POST", f"/systems/{sid}/alerts/test", {})
        self.assertEqual(code, 200, body)
        self.assertIn("outbox", body["sent"])
        out = daily_check.handler()
        self.assertEqual(out["checked"], 1)
        log = open(os.path.join(self.tmp.name, "outbox", "alerts.log"), encoding="utf-8").read()
        self.assertIn("SuryaWatch", log)

    def test_ask_mock_and_language(self):
        code, body = self.call("POST", "/ask", {"question": "नेट मीटरिंग क्या है?"})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["lang"], "hi")
        code, body = self.call("POST", "/ask", {"question": "What documents do I need?", "context": {"system_kw": 3}})
        self.assertEqual(body["lang"], "en")
        self.assertEqual(self.call("POST", "/ask", {"question": ""})[0], 400)

    def test_cleaning_effect(self):
        sid = self.make_system()
        hourly = lambda d: solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, d, d))
        for d, share in [("2026-10-05", 0.78), ("2026-10-06", 0.77), ("2026-10-07", 0.95), ("2026-10-08", 0.96)]:
            full = solar.expected_energy_until(hourly(d), d)
            self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{d}T19:00", "e_today_kwh": round(full * share, 2)}]})
            if d == "2026-10-07":
                pass
        self.call("POST", f"/systems/{sid}/events", {"type": "cleaned", "time": "2026-10-07T07:15"})
        for d in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"):
            self.call("GET", f"/systems/{sid}/day", params={"date": d})
        _, summary = self.call("GET", f"/systems/{sid}")
        c = summary["cleaning"]
        self.assertTrue(c["ready"], c)
        self.assertGreater(c["gain_pct"], 15)
        self.assertGreater(c["rupees_per_week"], 0)


if __name__ == "__main__":
    unittest.main()
