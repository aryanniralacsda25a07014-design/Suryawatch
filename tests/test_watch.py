"""Offline tests for Watch mode (systems, readings, photo reading, day verdicts)."""
import base64
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

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
        import planner
        self._ghi = planner.monthly_ghi
        planner.monthly_ghi = lambda lat, lon: (list(weather.DELHI_FALLBACK_GHI), "test")
        os.environ["SURYAWATCH_MOCK_AI"] = "1"

    def tearDown(self):
        weather.sunlight_hourly, weather.air_quality_hourly, weather.rain_forecast = self._orig
        import planner
        planner.monthly_ghi = self._ghi
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


class PromiseTests(WatchApiTests):
    def _promise(self, sid):
        return self.call("GET", f"/systems/{sid}")[1]["promise"]

    def test_promise_from_e_total(self):
        import planner
        sid = self.make_system()
        self.assertFalse(self._promise(sid)["ready"])
        oct_per_day = planner.monthly_yield_per_kwp(28.7, 77.1)[0][9] * 3 / 31
        self.call("POST", f"/systems/{sid}/readings", {"readings": [
            {"time": "2026-10-04T17:45", "e_total_kwh": 1000},
            {"time": "2026-10-07T17:45", "e_total_kwh": round(1000 + 3 * oct_per_day * 0.8, 1)}]})
        p = self._promise(sid)
        self.assertTrue(p["ready"])
        self.assertEqual(p["source"], "suryawatch")
        self.assertEqual(p["method"], "e_total")
        self.assertAlmostEqual(p["month"]["ratio"], 0.8, delta=0.03)
        self.assertGreater(p["month"]["gap_rupees"], 0)

    def test_installer_and_plan_promise(self):
        code, s = self.call("POST", "/systems", {"lat": 28.7, "lon": 77.1, "kwp": 3, "promise_kwh_year": 4500})
        self.assertEqual(self._promise(s["system_id"])["promise_kwh_year"], 4500)
        self.assertEqual(self._promise(s["system_id"])["source"], "installer")
        code, s2 = self.call("POST", "/systems", {"lat": 28.7, "lon": 77.1, "kwp": 3, "promise_kwh_year": 4400,
                                                 "promise_source": "plan", "plan_id": "abc123"})
        self.assertEqual(self._promise(s2["system_id"])["source"], "plan")

    def test_promise_from_daily_readings(self):
        sid = self.make_system()
        date = "2026-10-08"
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, date, date))
        full = solar.expected_energy_until(hourly, date)
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{date}T18:30", "e_today_kwh": full * 0.9}]})
        self.call("GET", f"/systems/{sid}/day", params={"date": date})
        p = self._promise(sid)
        self.assertTrue(p["ready"])
        self.assertEqual(p["method"], "daily")
        self.assertEqual(p["all"]["days"], 1)


class OutlookTests(WatchApiTests):
    def test_clear_outlook(self):
        sid = self.make_system()
        code, body = self.call("GET", f"/systems/{sid}/outlook")
        self.assertEqual(code, 200, body)
        self.assertEqual(len(body["days"]), 2)
        self.assertEqual(body["days"][0]["code"], "clear")
        self.assertGreater(body["days"][0]["likely_kwh"], 5)

    def test_smog_and_rain_outlook(self):
        sid = self.make_system()
        weather.air_quality_hourly = lambda lat, lon, s, e: [
            {"time": f"{d}T{h:02d}:00", "pm25": 220, "aqi": 270, "aod": 1.3, "dust": 30}
            for d in (s, e) for h in range(24)]
        days = self.call("GET", f"/systems/{sid}/outlook")[1]["days"]
        self.assertEqual(days[0]["code"], "smog_heavy")
        self.assertLess(days[0]["likely_kwh"], days[0]["expected_kwh"])
        first = days[0]["date"]
        weather.rain_forecast = lambda lat, lon, n=5: [{"date": first, "rain_mm": 12, "rain_prob_pct": 80}]
        self.assertEqual(self.call("GET", f"/systems/{sid}/outlook")[1]["days"][0]["code"], "rain")

    def test_evening_email_warns_about_tomorrow(self):
        import daily_check
        sid = self.make_system()
        today = watch.today()
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, today, today))
        full = solar.expected_energy_until(hourly, today)
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{today}T18:30", "e_today_kwh": full * 0.97}]})
        self.call("POST", f"/systems/{sid}/alerts", {"email": "owner@example.com"})
        weather.air_quality_hourly = lambda lat, lon, s, e: [
            {"time": f"{d}T{h:02d}:00", "pm25": 220, "aqi": 270, "aod": 1.3 if d != today else 0.35, "dust": 30}
            for d in (s, e) for h in range(24)]
        r = daily_check.run_for(sid)
        self.assertEqual(r.get("tomorrow"), "smog_heavy")
        log = open(os.path.join(self.tmp.name, "outbox", "alerts.log"), encoding="utf-8").read()
        self.assertIn("Heavy smog expected tomorrow", log)


class BillTests(WatchApiTests):
    def test_parse_bill(self):
        r = reader.parse_bill('```json\n{"units": "824 kWh", "period_days": 61, "amount_rs": "4,512.00", '
                              '"sanctioned_load_kw": "5 kW", "discom": "BSES Rajdhani Power Ltd", '
                              '"history": [{"month": "Jun", "units": 510}, {"month": "Jul", "units": 470}, '
                              '{"month": "Aug", "units": 430}], "export_units": null, "confidence": "high"}\n```')
        self.assertEqual(r["units"], 824)
        self.assertAlmostEqual(r["monthly_units"], 410, delta=2)      # two-month bill -> per month
        self.assertEqual(r["average_monthly_units"], 470)
        self.assertEqual(r["state"], "delhi")
        self.assertEqual(r["sanctioned_load_kw"], 5)
        self.assertEqual(reader.parse_bill('{"units": 300, "discom": "UHBVN"}')["state"], "other")

    def test_bill_route(self):
        img = base64.b64encode(b"\xff\xd8\xff" + os.urandom(3000)).decode()
        code, body = self.call("POST", "/bill", {"image_base64": img})
        self.assertEqual(code, 200, body)
        self.assertTrue(body["ai_available"])
        self.assertIsNotNone(body["average_monthly_units"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "photos")))   # bills are never stored
        self.assertEqual(self.call("POST", "/bill", {"image_base64": "xx"})[0], 400)

    def test_sanctioned_load_note(self):
        code, body = self.call("POST", "/plan", {"lat": 28.6, "lon": 77.2, "roof_area_m2": 80, "monthly_units": 600,
                                                 "sanctioned_load_kw": 3})
        self.assertEqual(code, 200, body)
        self.assertTrue(any("sanctioned load is 3 kW" in n for n in body["notes"]), body["notes"])


class HindiTests(WatchApiTests):
    def test_every_message_has_hindi(self):
        import i18n
        self.assertEqual(set(i18n.TEXT["en"]), set(i18n.TEXT["hi"]))
        for key, en in i18n.TEXT["en"].items():
            self.assertEqual(sorted(re.findall(r"{(\w+)}", en)), sorted(re.findall(r"{(\w+)}", i18n.TEXT["hi"][key])), key)

    def test_day_outlook_and_plan_in_hindi(self):
        sid = self.make_system()
        today = watch.today()
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, today, today))
        full = solar.expected_energy_until(hourly, today)
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{today}T18:30", "e_today_kwh": full * 0.97}]})
        en = self.call("GET", f"/systems/{sid}/day", params={"date": today})[1]["verdict"]
        hi = self.call("GET", f"/systems/{sid}/day", params={"date": today, "lang": "hi"})[1]["verdict"]
        self.assertEqual(en["code"], hi["code"])
        self.assertRegex(hi["title"] + hi["message"], "[\\u0900-\\u097F]")
        self.assertNotRegex(en["title"] + en["message"], "[\\u0900-\\u097F]")
        out = self.call("GET", f"/systems/{sid}/outlook", params={"lang": "hi"})[1]["days"][0]
        self.assertRegex(out["title"], "[\\u0900-\\u097F]")
        code, plan = self.call("POST", "/plan", {"lat": 28.6, "lon": 77.2, "roof_area_m2": 80, "monthly_units": 600,
                                                 "sanctioned_load_kw": 3, "lang": "hi"})
        self.assertEqual(code, 200, plan)
        self.assertTrue(any("स्वीकृत लोड 3 kW" in n for n in plan["notes"]), plan["notes"])
        self.assertTrue(all(re.search("[\\u0900-\\u097F]", a) for a in plan["assumptions"]))


class ImpactTests(WatchApiTests):
    def setUp(self):
        super().setUp()
        import impact
        self.impact = impact
        impact._cache.clear()

    def _day(self, sid, day, frac, e_total=None):
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, day, day))
        full = solar.expected_energy_until(hourly, day)
        r = {"time": f"{day}T18:30", "e_today_kwh": round(full * frac, 2)}
        if e_total is not None:
            r["e_total_kwh"] = e_total
        self.call("POST", f"/systems/{sid}/readings", {"readings": [r]})
        self.call("GET", f"/systems/{sid}/day", params={"date": day})
        return r["e_today_kwh"]

    def test_evening_check_saves_verdicts_without_alerts(self):
        import daily_check
        sid = self.make_system()
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{watch.today()}T18:30", "e_today_kwh": 11.5}]})
        daily_check.handler()
        self.assertIsNotNone(store.get(f"SYSTEM#{sid}", f"VERDICT#{watch.today()}"))

    def test_units_tracked_takes_the_larger_count(self):
        readings = [{"time": "2026-10-01T18:30", "e_total_kwh": 4000}, {"time": "2026-10-05T18:30", "e_total_kwh": 4048}]
        verdicts = [{"final": True, "actual_kwh": 12}, {"final": True, "actual_kwh": 11}, {"final": False, "actual_kwh": 5}]
        self.assertEqual(self.impact.units_tracked(readings, verdicts), 48)
        self.assertEqual(self.impact.units_tracked(readings[:1], verdicts), 23)

    def test_totals_skip_demo_and_hide_identity(self):
        real = self.make_system()
        today = date.fromisoformat(watch.today())
        d1, d2 = (today - timedelta(days=2)).isoformat(), (today - timedelta(days=1)).isoformat()
        made = self._day(real, d1, 0.95) + self._day(real, d2, 0.80)
        code, demo = self.call("POST", "/systems", {"name": "Sample rooftop (demo data)", "demo": True,
                                                    "lat": 28.6, "lon": 77.2, "kwp": 5})
        self._day(demo["system_id"], d2, 0.9)
        for lat in (28.6, 28.6, 28.7):          # the same roof planned twice counts once
            self.call("POST", "/plan", {"lat": lat, "lon": 77.2, "roof_area_m2": 60, "monthly_units": 300})

        code, body = self.call("GET", "/impact")
        self.assertEqual(code, 200, body)
        w = body["watch"]
        self.assertEqual((w["rooftops"], w["kw"], w["days_checked"]), (1, 3.0, 2))
        self.assertAlmostEqual(w["units"], made, places=1)
        self.assertAlmostEqual(w["co2_kg"], made * 0.727, places=0)
        self.assertEqual(body["demo_systems"], 1)
        self.assertFalse(body["includes_demo"])
        self.assertEqual(body["plan"]["roofs"], 2)
        self.assertEqual(len(body["calendar"]), 35)
        self.assertEqual(body["calendar"][-2]["rooftops"], 1)
        text = json.dumps(body)
        for secret in (real, demo["system_id"], "Test roof", "Sample rooftop", "28.7", "77.1"):
            self.assertNotIn(secret, text)

        self.impact._cache.clear()
        body = self.call("GET", "/impact", params={"demo": "1"})[1]
        self.assertEqual((body["watch"]["rooftops"], body["watch"]["kw"]), (2, 8.0))
        self.assertTrue(body["includes_demo"])


class ReportTests(WatchApiTests):
    def _evening(self, sid, day, frac, e_total=None, state=None, view=True):
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, day, day))
        full = solar.expected_energy_until(hourly, day)
        r = {"time": f"{day}T18:30", "e_today_kwh": round(full * frac, 2)}
        if e_total is not None:
            r["e_total_kwh"] = e_total
        if state:
            r["state"] = state
        self.call("POST", f"/systems/{sid}/readings", {"readings": [r]})
        if view:
            self.call("GET", f"/systems/{sid}/day", params={"date": day})
        return r["e_today_kwh"]

    def test_report(self):
        sid = self.make_system()
        today = date.fromisoformat(watch.today())
        days = [(today - timedelta(days=i)).isoformat() for i in (5, 4, 3, 2, 1)]
        made = self._evening(sid, days[0], 0.95, 5000)
        made += self._evening(sid, days[1], 0.94, 5013)
        self._evening(sid, days[2], 0.93, 5026, state="Fault F07")      # a fault day has no performance figures
        made += self._evening(sid, days[3], 0.94, 5039)
        made += self._evening(sid, days[4], 0.95, 5052, view=False)       # never viewed: the report checks it
        self.call("POST", f"/systems/{sid}/events", {"type": "cleaned", "time": f"{days[1]}T07:30"})

        code, r = self.call("GET", f"/systems/{sid}/report", params={"from": days[0], "to": days[-1]})
        self.assertEqual(code, 200, r)
        self.assertEqual(len(r["days"]), 5)
        self.assertEqual(r["summary"]["unchecked_days"], 0)
        self.assertEqual(r["faults"], [{"time": f"{days[2]}T18:30", "state": "Fault F07"}])
        self.assertEqual(r["actions"][0]["code"], "fault")
        self.assertEqual(r["counter"]["units"], 52)
        self.assertEqual(r["cleanings"], [f"{days[1]}T07:30"])
        self.assertEqual(r["days"][2]["code"], "fault")
        self.assertEqual(r["summary"]["full_days"], 4)
        self.assertAlmostEqual(r["summary"]["made_kwh"], made, delta=0.2)
        self.assertNotIn("emails", json.dumps(r))

        # a newer reading on an already checked day is picked up
        self._evening(sid, days[0], 0.60, view=False)
        r2 = self.call("GET", f"/systems/{sid}/report", params={"from": days[0], "to": days[-1]})[1]
        self.assertLess(r2["days"][0]["actual_kwh"], r["days"][0]["actual_kwh"])

    def test_report_periods(self):
        sid = self.make_system()
        today = date.fromisoformat(watch.today())
        code, r = self.call("GET", f"/systems/{sid}/report", params={"to": (today + timedelta(days=5)).isoformat()})
        self.assertEqual((code, r["to"], r["days"]), (200, today.isoformat(), []))
        self.assertEqual(r["from"], (today - timedelta(days=29)).isoformat())
        self.assertEqual(self.call("GET", f"/systems/{sid}/report", params={"from": "2026-10-05", "to": "2026-10-01"})[0], 400)
        self.assertEqual(self.call("GET", f"/systems/{sid}/report", params={"from": "2026-01-01", "to": "2026-10-01"})[0], 400)
        self.assertEqual(self.call("GET", f"/systems/{sid}/report", params={"from": "5 Oct"})[0], 400)
        self.assertEqual(self.call("GET", "/systems/abcdef1234/report")[0], 404)


class DustTests(WatchApiTests):
    def setUp(self):
        super().setUp()
        import dust
        self.dust = dust

    def _evening(self, sid, day, frac):
        hourly = solar.expected_hourly({"lat": 28.7, "lon": 77.1, "kwp": 3}, fake_sun(28.7, 77.1, 20, 180, day, day))
        full = solar.expected_energy_until(hourly, day)
        self.call("POST", f"/systems/{sid}/readings", {"readings": [{"time": f"{day}T18:30", "e_today_kwh": round(full * frac, 2)}]})
        self.call("GET", f"/systems/{sid}/day", params={"date": day})

    def test_fit_shared_slope(self):
        pts = [{"spell": "a", "x": x, "y": 0.97 - 0.006 * x + (0.004 if x % 2 else -0.004)} for x in range(0, 8)]
        pts += [{"spell": "b", "x": x, "y": 0.93 - 0.006 * x} for x in range(0, 5)]
        f = self.dust.fit(pts)
        self.assertAlmostEqual(-f["slope"], 0.006, delta=0.001)
        self.assertEqual(f["spells"], 2)
        self.assertIsNone(self.dust.fit(pts[:3]))                       # too few days

    def test_wash_starts(self):
        w = self.dust.wash_starts([{"type": "cleaned", "time": "2026-10-02T07:30"}, {"type": "cleaned", "time": "2026-10-05T17:00"},
                                   {"type": "note", "time": "2026-10-06T09:00"}], {"2026-10-08": 3.0, "2026-10-09": 0.5})
        self.assertEqual(w, [{"date": "2026-10-02", "kind": "cleaned"}, {"date": "2026-10-06", "kind": "cleaned"},
                             {"date": "2026-10-09", "kind": "rain"}])

    def test_learns_rate_and_best_day(self):
        sid = self.make_system()
        today = date.fromisoformat(watch.today())
        washed = today - timedelta(days=9)
        self.call("POST", f"/systems/{sid}/events", {"type": "cleaned", "time": f"{washed.isoformat()}T07:00"})
        for x in range(0, 9):
            self._evening(sid, (washed + timedelta(days=x)).isoformat(), 0.97 - 0.006 * x)
        code, d = self.call("GET", f"/systems/{sid}/dust")
        self.assertEqual(code, 200, d)
        self.assertEqual(d["rate_source"], "learned")
        self.assertAlmostEqual(d["rate"], 0.006, delta=0.0015)
        self.assertEqual(d["days_since"], 9)
        self.assertEqual(d["last_wash"], {"date": washed.isoformat(), "kind": "cleaned"})
        growth = d["rate"] * d["kwh_day"] * d["unit_value"]
        self.assertEqual(d["best_interval_days"], round(min(30, max(3, (2 * 200 / growth) ** 0.5))))
        self.assertIn(d["advice"]["code"], ("clean_on", "clean_now"))
        self.assertEqual(len(d["points"]), 9)

        # rain due soon: wait for it instead
        weather.rain_forecast = lambda lat, lon, days=5: [{"date": (today + timedelta(days=1)).isoformat(), "rain_mm": 14, "rain_prob_pct": 85}]
        d = self.call("GET", f"/systems/{sid}/dust")[1]
        self.assertEqual(d["advice"]["code"], "wait_rain")

        # a dearer cleaning means cleaning less often
        code, s = self.call("POST", f"/systems/{sid}/settings", {"clean_cost": 800})
        self.assertEqual((code, s["clean_cost"]), (200, 800))
        self.assertGreater(self.call("GET", f"/systems/{sid}/dust")[1]["best_interval_days"], d["best_interval_days"])
        self.assertEqual(self.call("POST", f"/systems/{sid}/settings", {"clean_cost": -5})[0], 400)
        self.assertEqual(self.call("POST", f"/systems/{sid}/settings", {})[0], 400)

    def test_typical_rate_until_enough_days(self):
        sid = self.make_system()
        today = date.fromisoformat(watch.today())
        self._evening(sid, (today - timedelta(days=1)).isoformat(), 0.9)
        d = self.call("GET", f"/systems/{sid}/dust")[1]
        self.assertEqual((d["rate_source"], d["rate"]), ("typical", 0.004))
        self.assertGreater(d["points_needed"], 0)
        self.assertEqual(d["advice"]["code"], "unknown_wash")


if __name__ == "__main__":
    unittest.main()
