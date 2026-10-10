"""Evening check, run by Amazon EventBridge Scheduler at 7:30 PM IST.

For every system with alert emails: build today's verdict and email the owner when there is
something to act on (dust, fault, check), something reassuring to know (smog day), or no reading yet.
Systems without alerts that had a reading today get their verdict saved (no email).
Run by hand on a laptop:  python backend/daily_check.py
"""
from __future__ import annotations

import os

import alerts
import assistant
import dust
import store
import watch

ALERT_CODES = {"dust", "fault", "check", "smog"}


def tomorrow(sid: str) -> dict | None:
    try:
        return watch.outlook(sid, days=1)["days"][0]
    except Exception as exc:
        print(f"outlook failed for {sid}: {exc}")
        return None


def cleaning_tip(sid: str) -> str:
    """One line from the roof's dust plan, e.g. 'Best day to clean: 2026-10-14.'"""
    try:
        a = dust.plan(sid)["advice"]
    except Exception as exc:
        print(f"dust plan failed for {sid}: {exc}")
        return ""
    if a["code"] == "wait_rain":
        return f"\n\nBest plan: wait for the rain on {a['date']} (about {a['rain_mm']} mm); it will wash the panels for free."
    if a["code"] == "clean_now":
        return "\n\nBest plan: clean today or tomorrow morning. Dust now costs more than a cleaning."
    if a["code"] == "clean_on":
        return f"\n\nBest day to clean: {a['date']}. Until then dust costs less than a cleaning."
    return ""


def run_for(sid: str, app_url: str | None = None, force: bool = False) -> dict:
    day = watch.day_view(sid)
    v, system = day["verdict"], day["system"]
    nxt = tomorrow(sid)
    tail = f"\n\nTomorrow: {nxt['title']}. {nxt['message']}" if nxt else ""
    if v["code"] == "no_data":
        subject = f"SuryaWatch: add tonight's reading ({system['name']})"
        body = ("No inverter reading was added today. Photograph the display after sunset (the E-Today or Day "
                "screen) and upload it, and SuryaWatch will tell you if your panels need cleaning.")
        body += tail
        if app_url:
            body += f"\n\nOpen your dashboard: {app_url}?system={sid}#watch"
        status = alerts.send(sid, subject, body)
        return {"system": sid, "code": "no_data", "sent": status}
    if v["code"] in ALERT_CODES or force:
        if v["code"] == "dust":
            tail = cleaning_tip(sid) + tail
        subject, body = alerts.compose(system, v, app_url, assistant.hindi_line(v), tail)
        return {"system": sid, "code": v["code"], "sent": alerts.send(sid, subject, body)}
    if nxt and nxt["code"] in ("smog_heavy", "rain"):
        what = "Heavy smog expected tomorrow" if nxt["code"] == "smog_heavy" else "Rain tomorrow: skip cleaning"
        subject = f"SuryaWatch: {what} ({system['name']})"
        body = f"Today: {v['title']}.{tail}"
        if app_url:
            body += f"\n\nOpen your dashboard: {app_url}?system={sid}#watch"
        return {"system": sid, "code": v["code"], "tomorrow": nxt["code"], "sent": alerts.send(sid, subject, body)}
    return {"system": sid, "code": v["code"], "sent": None}


def handler(event=None, _context=None):
    app_url = os.environ.get("APP_URL")
    results = []
    for meta in store.scan_prefix("SYSTEM#", "META"):
        sid = meta["pk"].split("#", 1)[1]
        if not alerts.subscribed(sid):
            # no email, but still save the day's verdict so history and the public impact page count it
            if store.query(f"SYSTEM#{sid}", f"READING#{watch.today()}"):
                try:
                    watch.day_view(sid)
                except Exception as exc:
                    print(f"day check failed for {sid}: {exc}")
            continue
        try:
            results.append(run_for(sid, app_url))
        except Exception as exc:      # one bad system must not stop the others
            print(f"daily check failed for {sid}: {exc}")
            results.append({"system": sid, "error": str(exc)[:200]})
    print({"checked": len(results), "results": results})
    return {"checked": len(results), "results": results}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    print(handler())
