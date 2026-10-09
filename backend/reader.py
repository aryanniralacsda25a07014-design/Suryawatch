"""Read an inverter display photo with Amazon Bedrock (Amazon Nova, multimodal).

Returns the numbers a solar owner cares about, already converted to kW / kWh:
    {power_kw, e_today_kwh, e_total_kwh, display_time, other_values, confidence, notes, model}

On a laptop without AWS credentials, set SURYAWATCH_MOCK_AI=1 to get simulated readings so the
whole Watch flow can be tested before deployment.
"""
from __future__ import annotations

import json
import os
import random
import re

DEFAULT_MODELS = ["us.amazon.nova-2-lite-v1:0", "us.amazon.nova-lite-v1:0", "us.amazon.nova-pro-v1:0"]

PROMPT = """You are reading a photo of a solar inverter display (or its mobile-app screen) on an Indian rooftop.
Many Indian string inverters (Eastman SolarLink, Growatt, Solis, Sofar, Deye and others) have a small two-line
character LCD that shows one pair of readings at a time, for example:
  "Power: 1335W" / "State: Normal"      or      "E-Today: 5.2kWh" / "E-Total: 1234kWh"
The LCD can be faint, greenish and partly covered by glare. Read each character carefully.
Common labels:
- current output: "Power", "Pac", "Output Power", "P", "Now" (W or kW)
- energy produced today: "E-Today", "E-Day", "Day", "Today", "Daily Energy", "Today Yield", "Eday" (kWh)
- lifetime energy: "E-Total", "Total", "Total Yield", "Etotal", "Lifetime" (kWh or MWh)
- inverter status: "State", "Status", "Mode" (for example Normal, Waiting, Checking, Fault, an error code)
Rules: convert W to kW and MWh to kWh. Use null for anything not visible or not legible.
Never guess a digit you cannot read: if glare hides part of a number, return null and say so in notes.
Reply with JSON only, no other text, in exactly this shape:
{"power_kw": number|null, "e_today_kwh": number|null, "e_total_kwh": number|null, "state": string|null,
 "display_time": "HH:MM"|null, "other_values": [{"label": string, "value": string}],
 "confidence": "high"|"medium"|"low", "notes": string}"""


class ReaderUnavailable(RuntimeError):
    pass


def _num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else None


def parse_reply(text: str) -> dict:
    """Pull the JSON object out of the model's reply and sanity-check units."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("The AI reply did not contain readings.")
    data = json.loads(m.group())
    out = {
        "power_kw": _num(data.get("power_kw")),
        "e_today_kwh": _num(data.get("e_today_kwh")),
        "e_total_kwh": _num(data.get("e_total_kwh")),
        "state": (str(data.get("state")).strip()[:40] or None) if data.get("state") else None,
        "display_time": data.get("display_time") or None,
        "other_values": data.get("other_values") or [],
        "confidence": data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low",
        "notes": str(data.get("notes") or "")[:300],
    }
    # A home system is under ~100 kW: a bigger "kW" figure was almost certainly watts.
    if out["power_kw"] is not None and out["power_kw"] > 100:
        out["power_kw"] = round(out["power_kw"] / 1000, 3)
        out["notes"] = (out["notes"] + " Power converted from W.").strip()
    if out["e_today_kwh"] is not None and out["e_today_kwh"] > 500:
        out["e_today_kwh"] = round(out["e_today_kwh"] / 1000, 3)
        out["notes"] = (out["notes"] + " Today's energy converted from Wh.").strip()
    return out


def _mock(image: bytes) -> dict:
    rnd = random.Random(len(image))
    return {"power_kw": round(rnd.uniform(1.2, 2.4), 2), "e_today_kwh": round(rnd.uniform(4, 11), 1),
            "e_total_kwh": round(rnd.uniform(2000, 6000), 0), "state": "Normal", "display_time": None, "other_values": [],
            "confidence": "medium", "notes": "TEST MODE: simulated reading, not from the photo.", "model": "mock"}


def _ask_image(image: bytes, fmt: str, prompt: str, parse, max_tokens: int = 700) -> dict:
    """Send one image + instruction to Bedrock (trying each model in turn) and parse the JSON reply."""
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError as exc:
        raise ReaderUnavailable("AI reading runs on AWS. Type the numbers in for now.") from exc

    region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "us-east-1"
    client = boto3.client("bedrock-runtime", region_name=region)
    models = list(dict.fromkeys([m for m in [os.environ.get("MODEL_ID")] + DEFAULT_MODELS if m]))
    last_error = None
    for model in models:
        try:
            resp = client.converse(
                modelId=model,
                messages=[{"role": "user", "content": [
                    {"image": {"format": fmt, "source": {"bytes": image}}},
                    {"text": prompt},
                ]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
            )
            text = "".join(part.get("text", "") for part in resp["output"]["message"]["content"])
            result = parse(text)
            result["model"] = model
            return result
        except NoCredentialsError as exc:
            raise ReaderUnavailable("AI reading runs on AWS. Type the numbers in for now.") from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            last_error = exc
            print(f"Bedrock model {model} failed: {code} {exc}")
            if code in ("AccessDeniedException", "ValidationException", "ResourceNotFoundException"):
                continue        # try the next model
            raise
    raise ReaderUnavailable(f"No Bedrock model could read the photo ({last_error}).")


def read_display(image: bytes, fmt: str) -> dict:
    if os.environ.get("SURYAWATCH_MOCK_AI") == "1":
        return _mock(image)
    return _ask_image(image, fmt, PROMPT, parse_reply)


# --------------------------------------------------------------------------- electricity bills (Plan mode)
BILL_PROMPT = """You are reading a photo of an Indian household electricity bill.
Extract ONLY these energy facts. Do NOT copy the customer's name, address, phone, consumer number, account number
or meter number into your reply.
- units billed this period (kWh), and the number of days in the billing period
- total amount payable (Rs)
- sanctioned / contracted load (kW)
- the electricity company (DISCOM), e.g. BSES Rajdhani, BSES Yamuna, Tata Power-DDL, NDMC, UHBVN, PVVNL
- the consumption history table if printed (month and units for each past month)
- for net-metered (solar) consumers: units exported to the grid this period
Use null for anything not visible. Never guess digits you cannot read.
Reply with JSON only, no other text, in exactly this shape:
{"units": number|null, "period_days": number|null, "amount_rs": number|null, "sanctioned_load_kw": number|null,
 "discom": string|null, "history": [{"month": string, "units": number}], "export_units": number|null,
 "confidence": "high"|"medium"|"low", "notes": string}"""

DELHI_DISCOMS = ("bses", "rajdhani", "yamuna", "tata power-ddl", "tpddl", "tata power delhi", "ndmc", "new delhi municipal")


def parse_bill(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("The AI reply did not contain bill details.")
    data = json.loads(m.group())
    units, days = _num(data.get("units")), _num(data.get("period_days"))
    history = []
    for h in data.get("history") or []:
        u = _num(h.get("units")) if isinstance(h, dict) else None
        if u is not None and 0 < u < 20000:
            history.append({"month": str(h.get("month") or "")[:20], "units": u})
    monthly = None
    if units is not None and units > 0:
        monthly = units / (days / 30.4) if days and 20 <= days <= 70 else units
    avg = round(sum(h["units"] for h in history) / len(history), 0) if len(history) >= 3 else None
    discom = (str(data.get("discom")).strip()[:40] or None) if data.get("discom") else None
    return {
        "units": units, "period_days": days,
        "monthly_units": round(monthly, 0) if monthly else None,
        "average_monthly_units": avg, "history": history[:12],
        "amount_rs": _num(data.get("amount_rs")),
        "sanctioned_load_kw": _num(data.get("sanctioned_load_kw")),
        "discom": discom,
        "state": "delhi" if discom and any(k in discom.lower() for k in DELHI_DISCOMS) else ("other" if discom else None),
        "export_units": _num(data.get("export_units")),
        "confidence": data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low",
        "notes": str(data.get("notes") or "")[:300],
    }


def read_bill(image: bytes, fmt: str) -> dict:
    """Energy facts from a bill photo. The photo itself is never stored."""
    if os.environ.get("SURYAWATCH_MOCK_AI") == "1":
        rnd = random.Random(len(image))
        hist = [{"month": m, "units": round(rnd.uniform(320, 560))} for m in ("Apr", "May", "Jun", "Jul", "Aug", "Sep")]
        return {"units": hist[-1]["units"], "period_days": 30, "monthly_units": hist[-1]["units"],
                "average_monthly_units": round(sum(h["units"] for h in hist) / 6), "history": hist,
                "amount_rs": None, "sanctioned_load_kw": 3.0, "discom": "BSES Rajdhani", "state": "delhi",
                "export_units": None, "confidence": "medium",
                "notes": "TEST MODE: simulated bill reading, not from the photo.", "model": "mock"}
    return _ask_image(image, fmt, BILL_PROMPT, parse_bill, max_tokens=900)
