"""SuryaWatch HTTP API - one Lambda behind an API Gateway HTTP API.

Routes
    GET  /health                              liveness check
    POST /plan                                Plan mode: size, cost, subsidy, payback
    GET  /expected                            expected output curve for a location and date
    POST /systems                             register a rooftop system for Watch mode
    GET  /systems/{id}                        system details, recent verdicts and events
    GET  /systems/{id}/day?date=YYYY-MM-DD    readings, expected curve and the day's verdict
    POST /systems/{id}/photo                  read an inverter-display photo with Amazon Bedrock
    POST /systems/{id}/readings               save readings (after the owner checks them)
    POST /systems/{id}/readings/delete        remove one reading
    POST /systems/{id}/events                 log a cleaning or a note
    GET  /systems/{id}/outlook                next two days: expected output, smog and rain forecast
    POST /systems/{id}/alerts                 subscribe an email to alerts (Amazon SNS)
    POST /systems/{id}/alerts/test            send today's check right now
    POST /ask                                 helper: questions in English or Hindi (Amazon Bedrock)
    POST /bill                                read units, load and DISCOM from a bill photo (not stored)
"""
from __future__ import annotations

import base64
import json
import os
import re
import traceback
from datetime import datetime

import alerts
import assistant
import daily_check
import impact
import planner
import reader
import report
import solar
import store
import watch
import weather

JSON_HEADERS = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET,POST,OPTIONS",
}
MAX_PHOTO_BYTES = 4_000_000


class BadRequest(ValueError):
    pass


def respond(status: int, body) -> dict:
    return {"statusCode": status, "headers": JSON_HEADERS,
            "body": "" if body is None else json.dumps(body, default=str)}


def body_of(event) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise BadRequest("Request body must be JSON.") from exc
    if not isinstance(data, (dict, list)):
        raise BadRequest("Request body must be a JSON object.")
    return data


def num(params: dict, key: str, default=None, lo=None, hi=None) -> float:
    val = params.get(key, default)
    if val is None or val == "":
        raise BadRequest(f"Missing '{key}'.")
    try:
        x = float(val)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"'{key}' must be a number.") from exc
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise BadRequest(f"'{key}' must be between {lo} and {hi}.")
    return x


# --------------------------------------------------------------------------- Plan
def health(_e, _p, _m):
    return {"ok": True, "service": "suryawatch", "stage": 4, "storage": "aws" if store.on_aws() else "local",
            "alerts": "sns" if alerts.topic() else "local"}


def make_plan(event, _p, _m):
    req = body_of(event)
    num(req, "lat", lo=-90, hi=90)
    num(req, "lon", lo=-180, hi=180)
    result = planner.plan(req)
    plan_id = store.new_id()
    try:
        store.put(f"PLAN#{plan_id}", "META", {"created": store.now_iso(), "result": result})
    except Exception as exc:  # saving is nice-to-have; never fail the user's plan over it
        print(f"could not save plan: {exc}")
    return {"plan_id": plan_id, **result}


def expected_curve(_e, params, _m):
    lat = num(params, "lat", lo=-90, hi=90)
    lon = num(params, "lon", lo=-180, hi=180)
    kwp = num(params, "kwp", lo=0.1, hi=1000)
    tilt = num(params, "tilt", 20, lo=0, hi=90)
    facing = num(params, "facing", 180, lo=0, hi=360)
    date = params.get("date") or datetime.now(solar.IST).date().isoformat()
    rows = weather.sunlight_hourly(lat, lon, tilt, facing, date, date)
    hourly = solar.expected_hourly({"lat": lat, "lon": lon, "kwp": kwp, "pr_ref": params.get("pr")}, rows)
    return {"date": date, "expected_kwh": round(solar.expected_energy_until(hourly, date), 2),
            "sky": solar.day_sky_summary(hourly, date), "hourly": hourly}


# --------------------------------------------------------------------------- Watch
def create_system(event, _p, _m):
    return watch.create_system(body_of(event))


def get_system(_e, _p, m):
    return watch.system_summary(m["sid"])


def day(_e, params, m):
    return watch.day_view(m["sid"], params.get("date"), params.get("lang") or "en")


def read_photo(event, _p, m):
    watch.get_system(m["sid"])
    req = body_of(event)
    raw = str(req.get("image_base64") or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        image = base64.b64decode(raw, validate=False)
    except Exception as exc:
        raise BadRequest("The photo could not be decoded.") from exc
    if len(image) < 1000:
        raise BadRequest("Please attach a photo of the inverter display.")
    if len(image) > MAX_PHOTO_BYTES:
        raise BadRequest("That photo is too large. Please use one under 4 MB.")
    fmt = "png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "webp" if image[8:12] == b"WEBP" else "jpeg"
    key = store.save_photo(m["sid"], image, "jpg" if fmt == "jpeg" else fmt)
    try:
        values = reader.read_display(image, fmt)
    except reader.ReaderUnavailable as exc:
        return {"photo_key": key, "ai_available": False, "message": str(exc)}
    return {"photo_key": key, "ai_available": True, **values}


def decode_photo(req: dict) -> tuple[bytes, str]:
    raw = str(req.get("image_base64") or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        image = base64.b64decode(raw, validate=False)
    except Exception as exc:
        raise BadRequest("The photo could not be decoded.") from exc
    if len(image) < 1000:
        raise BadRequest("Please attach a photo.")
    if len(image) > MAX_PHOTO_BYTES:
        raise BadRequest("That photo is too large. Please use one under 4 MB.")
    fmt = "png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "webp" if image[8:12] == b"WEBP" else "jpeg"
    return image, fmt


def read_bill(event, _p, _m):
    image, fmt = decode_photo(body_of(event))      # read in memory only; bills are never stored
    try:
        return {"ai_available": True, **reader.read_bill(image, fmt)}
    except reader.ReaderUnavailable as exc:
        return {"ai_available": False, "message": "Bill reading runs on AWS. Type your units for now."}


def save_readings(event, _p, m):
    req = body_of(event)
    items = req.get("readings") if isinstance(req, dict) else req
    saved = watch.add_readings(m["sid"], items)
    return {"saved": len(saved), "readings": saved}


def delete_reading(event, _p, m):
    watch.delete_reading(m["sid"], body_of(event).get("time"))
    return {"deleted": True}


def add_event(event, _p, m):
    return watch.add_event(m["sid"], body_of(event))


def outlook(_e, params, m):
    return watch.outlook(m["sid"], lang=params.get("lang") or "en")


def subscribe_alerts(event, _p, m):
    watch.get_system(m["sid"])
    return alerts.subscribe(m["sid"], body_of(event).get("email"))


def test_alert(_e, _p, m):
    watch.get_system(m["sid"])
    return daily_check.run_for(m["sid"], os.environ.get("APP_URL"), force=True)


def system_report(_e, params, m):
    return report.build(m["sid"], params.get("from"), params.get("to"), params.get("lang") or "en")


def impact_totals(_e, params, _m):
    return impact.impact(include_demo=str(params.get("demo", "")).lower() in ("1", "true", "yes"))


def ask(event, _p, _m):
    req = body_of(event)
    ctx = req.get("context") if isinstance(req.get("context"), dict) else {}
    return assistant.ask(req.get("question"), ctx, req.get("lang"))


SID = r"(?P<sid>[a-z0-9]{1,20})"
ROUTES = [
    ("GET", r"/health", health),
    ("POST", r"/plan", make_plan),
    ("GET", r"/expected", expected_curve),
    ("POST", r"/systems", create_system),
    ("GET", rf"/systems/{SID}", get_system),
    ("GET", rf"/systems/{SID}/day", day),
    ("POST", rf"/systems/{SID}/photo", read_photo),
    ("POST", rf"/systems/{SID}/readings", save_readings),
    ("POST", rf"/systems/{SID}/readings/delete", delete_reading),
    ("POST", rf"/systems/{SID}/events", add_event),
    ("GET", rf"/systems/{SID}/outlook", outlook),
    ("GET", rf"/systems/{SID}/report", system_report),
    ("POST", rf"/systems/{SID}/alerts", subscribe_alerts),
    ("POST", rf"/systems/{SID}/alerts/test", test_alert),
    ("POST", r"/ask", ask),
    ("POST", r"/bill", read_bill),
    ("GET", r"/impact", impact_totals),
]


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    if method == "OPTIONS":
        return respond(204, None)
    for route_method, pattern, fn in ROUTES:
        m = re.fullmatch(pattern, path)
        if m and route_method == method:
            break
    else:
        return respond(404, {"error": f"No route for {method} {path}"})
    try:
        return respond(200, fn(event, event.get("queryStringParameters") or {}, m.groupdict()))
    except watch.NotFound as exc:
        return respond(404, {"error": str(exc)})
    except (BadRequest, ValueError) as exc:
        return respond(400, {"error": str(exc)})
    except Exception as exc:
        traceback.print_exc()
        upstream = "urlopen" in repr(exc) or "timed out" in str(exc) or "HTTP Error" in str(exc)
        return respond(502 if upstream else 500,
                       {"error": "A data source did not answer. Please try again in a minute." if upstream
                        else "Something went wrong on our side. Please try again.",
                        "detail": str(exc)[:200]})
