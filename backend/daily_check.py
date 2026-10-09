"""Evening check, run by Amazon EventBridge Scheduler at 7:30 PM IST.

For every system with alert emails: build today's verdict and email the owner when there is
something to act on (dust, fault, check), something reassuring to know (smog day), or no reading yet.
Run by hand on a laptop:  python backend/daily_check.py
"""
from __future__ import annotations

import os

import alerts
import assistant
import store
import watch

ALERT_CODES = {"dust", "fault", "check", "smog"}


def run_for(sid: str, app_url: str | None = None, force: bool = False) -> dict:
    day = watch.day_view(sid)
    v, system = day["verdict"], day["system"]
    if v["code"] == "no_data":
        subject = f"SuryaWatch: add tonight's reading ({system['name']})"
        body = ("No inverter reading was added today. Photograph the display after sunset (the E-Today or Day "
                "screen) and upload it, and SuryaWatch will tell you if your panels need cleaning.")
        if app_url:
            body += f"\n\nOpen your dashboard: {app_url}?system={sid}#watch"
        status = alerts.send(sid, subject, body)
        return {"system": sid, "code": "no_data", "sent": status}
    if v["code"] in ALERT_CODES or force:
        subject, body = alerts.compose(system, v, app_url, assistant.hindi_line(v))
        return {"system": sid, "code": v["code"], "sent": alerts.send(sid, subject, body)}
    return {"system": sid, "code": v["code"], "sent": None}


def handler(event=None, _context=None):
    app_url = os.environ.get("APP_URL")
    results = []
    for meta in store.scan_prefix("SYSTEM#", "META"):
        sid = meta["pk"].split("#", 1)[1]
        if not alerts.subscribed(sid):
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
