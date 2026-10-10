"""Offline tests for the SuryaWatch engine. Run from the repo root:

    python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import api        # noqa: E402
import planner    # noqa: E402
import solar      # noqa: E402
import verdict    # noqa: E402
import weather    # noqa: E402

DELHI = (28.61, 77.21)


def fake_day(date: str, gti_scale: float = 1.0, ghi_scale: float = 0.85) -> list[dict]:
    """Synthetic hourly weather for a sunny Delhi day built from the clear-sky model."""
    rows = []
    start = datetime.fromisoformat(date).replace(tzinfo=solar.IST)
    for h in range(1, 25):
        end = start + timedelta(hours=h)
        cs = solar.clear_sky_hour_mean(*DELHI, end)
        rows.append({"time": end.strftime("%Y-%m-%dT%H:%M"), "ghi": cs * ghi_scale,
                     "gti": cs * 1.1 * gti_scale, "temp": 32.0, "cloud": 5, "precip": 0.0})
    return rows


def fake_air(date: str, aod: float, pm25: float) -> list[dict]:
    return [{"time": f"{date}T{h:02d}:00", "pm25": pm25, "aqi": 180, "aod": aod, "dust": 20}
            for h in range(24)]


class SolarTests(unittest.TestCase):
    def test_noon_sun_in_delhi(self):
        z, az = solar.solar_position(*DELHI, datetime(2026, 10, 9, 12, 8, tzinfo=solar.IST))
        self.assertAlmostEqual(z, 34.9, delta=1.0)     # latitude minus (negative) declination
        self.assertAlmostEqual(az, 180, delta=3)        # sun due south at solar noon

    def test_night_has_no_sun(self):
        self.assertEqual(solar.clear_sky_ghi(solar.solar_position(*DELHI, datetime(2026, 10, 9, 23, 0, tzinfo=solar.IST))[0]), 0.0)

    def test_bearing_conversion(self):
        self.assertEqual(solar.bearing_to_open_meteo_azimuth(180), 0)
        self.assertEqual(solar.bearing_to_open_meteo_azimuth(90), -90)
        self.assertEqual(solar.bearing_to_open_meteo_azimuth(270), 90)
        self.assertEqual(abs(solar.bearing_to_open_meteo_azimuth(0)), 180)

    def test_expected_day_is_realistic(self):
        rows = solar.expected_hourly({"lat": DELHI[0], "lon": DELHI[1], "kwp": 3}, fake_day("2026-10-09"))
        kwh = solar.expected_energy_until(rows, "2026-10-09")
        self.assertTrue(12 < kwh < 20, kwh)            # 3 kW in clear October Delhi: ~4-6 kWh per kW
        half = solar.expected_energy_until(rows, "2026-10-09", datetime(2026, 10, 9, 12, 30, tzinfo=solar.IST))
        self.assertTrue(0.35 * kwh < half < 0.65 * kwh)
        noon_kw = solar.expected_power_at(rows, datetime(2026, 10, 9, 12, 0, tzinfo=solar.IST))
        self.assertTrue(1.8 < noon_kw < 3.0, noon_kw)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self._orig = planner.monthly_ghi
        planner.monthly_ghi = lambda lat, lon: (list(weather.DELHI_FALLBACK_GHI), "test")

    def tearDown(self):
        planner.monthly_ghi = self._orig

    def test_slabs(self):
        self.assertEqual(planner.energy_charge(150), 450)
        self.assertEqual(planner.energy_charge(300), 1050)
        self.assertEqual(planner.energy_charge(500), 600 + 900 + 650)
        self.assertAlmostEqual(planner.units_from_bill(1050), 300, delta=1)

    def test_subsidies(self):
        self.assertEqual(planner.central_subsidy(1), 30000)
        self.assertEqual(planner.central_subsidy(2), 60000)
        self.assertEqual(planner.central_subsidy(3), 78000)
        self.assertEqual(planner.central_subsidy(6), 78000)
        self.assertEqual(planner.delhi_capital_subsidy(3), 6000)
        self.assertEqual(planner.delhi_capital_subsidy(8), 10000)

    def test_typical_delhi_home(self):
        r = planner.plan({"lat": DELHI[0], "lon": DELHI[1], "roof_area_m2": 60, "monthly_units": 450, "state": "delhi"})
        self.assertEqual(r["limited_by"], "usage")
        self.assertTrue(3.0 <= r["system_kw"] <= 4.0, r["system_kw"])
        self.assertTrue(1350 < r["yield_kwh_per_kwp"] < 1650)
        self.assertEqual(r["net_cost"], r["gross_cost"] - r["central_subsidy"] - r["state_subsidy"])
        self.assertTrue(2 < r["payback_years"] < 8, r["payback_years"])
        self.assertEqual(len(r["months"]), 12)

    def test_small_roof_limits_size(self):
        r = planner.plan({"lat": DELHI[0], "lon": DELHI[1], "roof_area_m2": 25, "monthly_units": 900})
        self.assertEqual(r["limited_by"], "roof")
        self.assertEqual((r["panels_approx"], r["system_kw"]), (3, 1.65))      # 17.5 m2 usable fits 3 panels

    def test_size_is_whole_panels_not_rounded(self):
        r = planner.plan({"lat": DELHI[0], "lon": DELHI[1], "roof_area_m2": 80, "monthly_units": 410, "state": "delhi"})
        self.assertAlmostEqual(r["system_kw"], r["panels_approx"] * 0.55, places=6)
        self.assertNotEqual(r["system_kw"] * 2, int(r["system_kw"] * 2))        # e.g. 3.3 kW, not cut down to 3

    def test_bill_input_and_errors(self):
        r = planner.plan({"lat": DELHI[0], "lon": DELHI[1], "roof_area_m2": 80, "monthly_bill": 2150})
        self.assertAlmostEqual(r["inputs"]["monthly_units"], 500, delta=1)
        with self.assertRaises(ValueError):
            planner.plan({"lat": 28, "lon": 77, "roof_area_m2": 5, "monthly_units": 300})
        with self.assertRaises(ValueError):
            planner.plan({"lat": 28, "lon": 77, "roof_area_m2": 50})


class VerdictTests(unittest.TestCase):
    date = "2026-10-09"
    system = {"lat": DELHI[0], "lon": DELHI[1], "kwp": 3}

    def hourly(self):
        return solar.expected_hourly(self.system, fake_day(self.date))

    def run_case(self, actual_share, aod, pm25=60, days=5, previous=None, at="18:30", rain=None):
        hourly = self.hourly()
        full = solar.expected_energy_until(hourly, self.date)
        readings = [{"time": f"{self.date}T{at}", "e_today_kwh": full * actual_share}]
        return verdict.diagnose_day(self.system, self.date, readings, hourly, fake_air(self.date, aod, pm25),
                                    previous=previous, days_since_clean_or_rain=days, rain_ahead=rain)

    def test_healthy(self):
        self.assertEqual(self.run_case(0.97, aod=0.35)["code"], "healthy")

    def test_smog_not_blamed_on_panels(self):
        v = self.run_case(0.82, aod=1.2, pm25=180)
        self.assertEqual(v["code"], "smog")
        self.assertGreater(v["haze_loss"], 0.15)

    def test_dust(self):
        v = self.run_case(0.78, aod=0.45)
        self.assertEqual(v["code"], "dust")
        self.assertGreater(v["rupees_lost_per_week"], 0)

    def test_dust_waits_for_rain(self):
        v = self.run_case(0.78, aod=0.45, rain=[{"date": "2026-10-10", "rain_mm": 12, "rain_prob_pct": 80}])
        self.assertIn("Rain is likely on 2026-10-10", v["message"])

    def test_sudden_drop_is_fault(self):
        prev = [{"performance_after_haze": 0.95}] * 3
        self.assertEqual(self.run_case(0.45, aod=0.4, previous=prev)["code"], "fault")

    def test_recently_cleaned_but_low(self):
        self.assertEqual(self.run_case(0.75, aod=0.4, days=1)["code"], "check")

    def test_partial_day(self):
        hourly = self.hourly()
        at = datetime(2026, 10, 9, 13, 0, tzinfo=solar.IST)
        part = solar.expected_energy_until(hourly, self.date, at)
        v = verdict.diagnose_day(self.system, self.date, [{"time": f"{self.date}T13:00", "e_today_kwh": part * 0.96}],
                                 hourly, fake_air(self.date, 0.35, 50))
        self.assertFalse(v["final"])
        self.assertEqual(v["code"], "healthy")

    def test_reading_just_before_sunset_counts_as_final(self):
        self.assertTrue(self.run_case(0.97, aod=0.35, at="17:45")["final"])
        self.assertFalse(self.run_case(0.97, aod=0.35, at="15:00")["final"])

    def test_calibration(self):
        v = self.run_case(0.95, aod=0.4)
        self.assertAlmostEqual(verdict.calibrate_pr(self.system, v), 0.85 * v["performance_after_haze"], places=2)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._ghi, self._put = planner.monthly_ghi, api.store.put
        planner.monthly_ghi = lambda lat, lon: (list(weather.DELHI_FALLBACK_GHI), "test")
        self.saved = []
        api.store.put = lambda pk, sk, data: self.saved.append(pk)

    def tearDown(self):
        planner.monthly_ghi, api.store.put = self._ghi, self._put

    def call(self, method, path, body=None, params=None):
        ev = {"requestContext": {"http": {"method": method}}, "rawPath": path,
              "queryStringParameters": params, "body": json.dumps(body) if body else None}
        r = api.handler(ev, None)
        return r["statusCode"], json.loads(r["body"]) if r["body"] else None

    def test_health_and_404(self):
        self.assertEqual(self.call("GET", "/health")[0], 200)
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("OPTIONS", "/plan")[0], 204)

    def test_plan_route(self):
        code, body = self.call("POST", "/plan", {"lat": 28.6, "lon": 77.2, "roof_area_m2": 60, "monthly_units": 400})
        self.assertEqual(code, 200, body)
        self.assertIn("payback_years", body)
        self.assertTrue(self.saved and self.saved[0].startswith("PLAN#"))

    def test_plan_validation(self):
        code, body = self.call("POST", "/plan", {"lat": 200, "lon": 77, "roof_area_m2": 60, "monthly_units": 400})
        self.assertEqual(code, 400)
        code, body = self.call("POST", "/plan", {"lat": 28.6, "lon": 77.2, "roof_area_m2": 60})
        self.assertEqual(code, 400)
        self.assertIn("monthly", body["error"])


if __name__ == "__main__":
    unittest.main()
