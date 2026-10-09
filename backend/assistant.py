"""SuryaWatch helper: answers rooftop-solar questions in English or Hindi with Amazon Bedrock,
grounded in the user's own plan or day result plus a fixed set of scheme facts.
"""
from __future__ import annotations

import json
import os
import re

from reader import DEFAULT_MODELS

FACTS = """Facts you may use (India, checked October 2026):
- PM Surya Ghar: Muft Bijli Yojana gives a central subsidy of Rs 30,000 per kW for the first 2 kW and Rs 18,000 for the 3rd kW, capped at Rs 78,000, paid to the bank account after the net meter is installed and the system is inspected. Collateral-free bank loans of about 7% are available for systems up to 3 kW.
- Steps on pmsuryaghar.gov.in: register with state, DISCOM and consumer number; log in with consumer number and mobile; apply; wait for DISCOM approval; install through a registered vendor (vendor ratings are on the portal); submit plant details and apply for a net meter; DISCOM installs the net meter, inspects and issues a commissioning certificate; submit bank details and a cancelled cheque; the subsidy arrives in the bank account.
- What the portal asks for along the way: the consumer number from the electricity bill, the registered mobile number, and later bank details with a cancelled cheque. For any other document, tell the user to check the portal or ask the DISCOM.
- Delhi Solar Policy 2024: extra Rs 2,000 per kW capped at Rs 10,000 per consumer; generation-based incentive of Rs 3 per unit for systems up to 3 kW and Rs 2 per unit for 3-10 kW, for 5 years; group net metering, community solar and a zero-upfront RESCO model are allowed.
- Net metering: one meter counts units imported from and exported to the grid; you pay only for the net units, and surplus is credited.
- Shade-free roof needed: about 10 square metres per kW. In Delhi, panels usually face south, tilted at roughly 20-28 degrees.
- Dust and air pollution can cut Indian solar output by 17-25% (Duke University study at IIT Gandhinagar); in that study, output from dusty test panels rose about 50% after each cleaning.
- Safe cleaning: early morning or evening when panels are cool; plain water and a soft cloth or mop; no detergent, no pressure washer, no metal scrapers; never step on panels; never clean near an unprotected roof edge; never touch wiring. Cold water on hot glass at midday can crack it.
- Smog days: haze blocks sunlight before it reaches the roof, so output falls even with clean panels; there is nothing to fix.
- Inverter fault codes differ by brand; note the code, switch off and on once only if the installer allows, then call the installer."""

SYSTEM = ("You are SuryaWatch, a friendly rooftop-solar adviser for Indian households. Answer in at most 120 words, "
          "in simple language, using only the facts and the user's numbers given. If you are not sure, say so and "
          "suggest asking the DISCOM or the installer. Never invent subsidy amounts, prices or rules. "
          "Use plain sentences or a short numbered list; no tables.")

MOCK_ANSWER = {
    "en": "TEST MODE (no AI on this laptop): after deployment, Amazon Bedrock answers this using your own numbers "
          "and the PM Surya Ghar and Delhi Solar Policy facts.",
    "hi": "टेस्ट मोड (इस लैपटॉप पर AI नहीं): डिप्लॉय होने के बाद Amazon Bedrock आपके अपने आंकड़ों और "
          "पीएम सूर्य घर व दिल्ली सोलर पॉलिसी के तथ्यों से जवाब देगा।",
}


def detect_lang(text: str, lang: str | None) -> str:
    if lang in ("hi", "en"):
        return lang
    return "hi" if re.search(r"[ऀ-ॿ]", text or "") else "en"


def ask(question: str, context: dict | None = None, lang: str | None = None) -> dict:
    question = (question or "").strip()
    if len(question) < 3:
        raise ValueError("Please type a question.")
    if len(question) > 500:
        raise ValueError("Please keep the question under 500 characters.")
    lang = detect_lang(question, lang)
    if os.environ.get("SURYAWATCH_MOCK_AI") == "1":
        return {"answer": MOCK_ANSWER[lang], "lang": lang, "model": "mock"}
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        return {"answer": None, "lang": lang, "unavailable": "The helper runs on AWS after deployment."}

    language = "Hindi (Devanagari script, simple everyday Hindi)" if lang == "hi" else "English"
    ctx = json.dumps(context or {}, ensure_ascii=False)[:3000]
    prompt = f"{FACTS}\n\nThe user's own result from SuryaWatch (JSON):\n{ctx}\n\nAnswer in {language}.\nQuestion: {question}"
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "us-east-1")
    for model in dict.fromkeys([m for m in [os.environ.get("MODEL_ID")] + DEFAULT_MODELS if m]):
        try:
            resp = client.converse(modelId=model, system=[{"text": SYSTEM}],
                                   messages=[{"role": "user", "content": [{"text": prompt}]}],
                                   inferenceConfig={"maxTokens": 500, "temperature": 0.2})
            text = "".join(p.get("text", "") for p in resp["output"]["message"]["content"]).strip()
            return {"answer": text, "lang": lang, "model": model}
        except NoCredentialsError:
            return {"answer": None, "lang": lang, "unavailable": "The helper runs on AWS after deployment."}
        except ClientError as exc:
            print(f"Bedrock model {model} failed: {exc}")
            continue
    return {"answer": None, "lang": lang, "unavailable": "The AI helper is busy. Please try again in a minute."}


def hindi_line(verdict: dict) -> str | None:
    """One-line Hindi summary for alert emails (best effort; None if AI is unavailable)."""
    if os.environ.get("SURYAWATCH_MOCK_AI") == "1":
        return None
    try:
        r = ask("Summarise this result for the owner in one or two short sentences.",
                {"title": verdict.get("title"), "message": verdict.get("message")}, "hi")
        return r.get("answer")
    except Exception as exc:
        print(f"hindi summary failed: {exc}")
        return None
