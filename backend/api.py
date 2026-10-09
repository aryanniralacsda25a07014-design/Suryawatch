"""SuryaWatch HTTP API - one Lambda behind an API Gateway HTTP API.

Stage 1 routes
    GET  /health                      liveness check
    POST /plan                        Plan mode: size, cost, subsidy, payback (saved to DynamoDB)
    GET  /expected                    expected output curve for a system and date
"""
from __future__ import annotations

import base64
import json
import traceback
from datetime import datetime

import planner
import solar
import store
import weather

JSON_HEADERS = {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET,POST,OPTIONS",
}


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
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise BadRequest("Request body must be JSON.") from exc


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


# --------------------------------------------------------------------------- handlers
def health(_event, _params):
    return {"ok": True, "service": "suryawatch", "stage": 1}


def make_plan(event, _params):
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


def expected_curve(_event, params):
    lat = num(params, "lat", lo=-90, hi=90)
    lon = num(params, "lon", lo=-180, hi=180)
    kwp = num(params, "kwp", lo=0.1, hi=1000)
    tilt = num(params, "tilt", 20, lo=0, hi=90)
    facing = num(params, "facing", 180, lo=0, hi=360)
    date = params.get("date") or datetime.now(solar.IST).date().isoformat()
    rows = weather.sunlight_hourly(lat, lon, tilt, facing, date, date)
    system = {"lat": lat, "lon": lon, "kwp": kwp, "pr_ref": params.get("pr")}
    hourly = solar.expected_hourly(system, rows)
    return {
        "date": date,
        "expected_kwh": round(solar.expected_energy_until(hourly, date), 2),
        "sky": solar.day_sky_summary(hourly, date),
        "hourly": hourly,
    }


ROUTES = {
    ("GET", "/health"): health,
    ("POST", "/plan"): make_plan,
    ("GET", "/expected"): expected_curve,
}


def handler(event, _context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    if method == "OPTIONS":
        return respond(204, None)
    fn = ROUTES.get((method, path.rstrip("/") or "/"))
    if fn is None:
        return respond(404, {"error": f"No route for {method} {path}"})
    try:
        return respond(200, fn(event, event.get("queryStringParameters") or {}))
    except (BadRequest, ValueError) as exc:
        return respond(400, {"error": str(exc)})
    except Exception as exc:
        traceback.print_exc()
        return respond(502 if "urlopen" in repr(exc) or "timed out" in str(exc) else 500,
                       {"error": "Something went wrong on our side. Please try again.",
                        "detail": str(exc)[:200]})
