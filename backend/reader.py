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
Extract the readings exactly as shown. Common labels:
- current output: "Pac", "Power", "Output Power", "P", "Now" (W or kW)
- energy produced today: "E-Today", "E-Day", "Today", "Daily Energy", "Today Yield", "Eday" (kWh)
- lifetime energy: "E-Total", "Total", "Total Yield", "Etotal", "Lifetime" (kWh or MWh)
Rules: convert W to kW and MWh to kWh. Use null for anything not visible. Never guess a number you cannot read.
Reply with JSON only, no other text, in exactly this shape:
{"power_kw": number|null, "e_today_kwh": number|null, "e_total_kwh": number|null,
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
            "e_total_kwh": round(rnd.uniform(2000, 6000), 0), "display_time": None, "other_values": [],
            "confidence": "medium", "notes": "TEST MODE: simulated reading, not from the photo.", "model": "mock"}


def read_display(image: bytes, fmt: str) -> dict:
    if os.environ.get("SURYAWATCH_MOCK_AI") == "1":
        return _mock(image)
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
                    {"text": PROMPT},
                ]}],
                inferenceConfig={"maxTokens": 700, "temperature": 0},
            )
            text = "".join(part.get("text", "") for part in resp["output"]["message"]["content"])
            result = parse_reply(text)
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
