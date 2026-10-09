"""Email alerts through Amazon SNS (one topic, filtered per system).

On AWS: ALERT_TOPIC_ARN is set; subscribing sends the owner an AWS confirmation email they must click.
On a laptop: alerts are written to data/outbox/alerts.log instead of being emailed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import store

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_sns = None


def _client():
    global _sns
    if _sns is None:
        import boto3
        _sns = boto3.client("sns")
    return _sns


def topic() -> str | None:
    return os.environ.get("ALERT_TOPIC_ARN") or None


def subscribe(sid: str, email: str) -> dict:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 120:
        raise ValueError("Please enter a valid email address.")
    cfg = store.get(f"SYSTEM#{sid}", "ALERTS") or {"emails": []}
    emails = sorted(set(cfg.get("emails", []) + [email]))
    if topic():
        _client().subscribe(TopicArn=topic(), Protocol="email", Endpoint=email,
                            Attributes={"FilterPolicy": json.dumps({"system_id": [sid]})},
                            ReturnSubscriptionArn=True)
        note = "Check your inbox and click the AWS confirmation link to start getting alerts."
    else:
        note = "Saved. On this laptop alerts go to data/outbox/alerts.log; once deployed they arrive by email."
    store.put(f"SYSTEM#{sid}", "ALERTS", {"emails": emails, "updated": store.now_iso()})
    return {"subscribed": email, "message": note}


def subscribed(sid: str) -> bool:
    cfg = store.get(f"SYSTEM#{sid}", "ALERTS")
    return bool(cfg and cfg.get("emails"))


def send(sid: str, subject: str, message: str) -> str:
    subject = re.sub(r"[\r\n]+", " ", subject)[:99]
    if topic():
        _client().publish(TopicArn=topic(), Subject=subject, Message=message,
                          MessageAttributes={"system_id": {"DataType": "String", "StringValue": sid}})
        return "emailed"
    out = os.path.join(store._LOCAL_DIR, "outbox")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "alerts.log"), "a", encoding="utf-8") as f:
        f.write(f"--- {datetime.now().isoformat(timespec='seconds')}  system {sid}\nSubject: {subject}\n{message}\n\n")
    print(f"[alert for {sid}] {subject}")
    return "written to data/outbox/alerts.log"


def compose(system: dict, verdict: dict, app_url: str | None = None, hindi: str | None = None) -> tuple[str, str]:
    """Subject and plain-text body for a day's verdict."""
    name = system.get("name") or "your rooftop"
    subject = f"SuryaWatch: {verdict.get('title', 'Daily check')} ({name})"
    lines = [verdict.get("message", "")]
    if verdict.get("actual_kwh") is not None:
        lines += ["", f"Made today: {verdict['actual_kwh']} kWh. Today's sunlight allowed about {verdict['expected_kwh']} kWh."]
    if verdict.get("pm25") is not None:
        lines.append(f"Air today: PM2.5 {round(verdict['pm25'])} ug/m3, aerosol optical depth {verdict.get('aod')}.")
    if hindi:
        lines += ["", hindi]
    if app_url:
        lines += ["", f"Open your dashboard: {app_url}?system={system.get('system_id', '')}#watch"]
    lines += ["", "- SuryaWatch (Environmental Hacks 2026)"]
    return subject, "\n".join(lines)
