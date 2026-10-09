"""DynamoDB access. One table, items keyed by pk/sk:

    PLAN#<id>        / META                 a saved Plan-mode result
    SYSTEM#<id>      / META                 a registered rooftop system (Stage 2)
    SYSTEM#<id>      / READING#<time>       one reading from a display photo or typed in
    SYSTEM#<id>      / VERDICT#<date>       the day's diagnosis
    SYSTEM#<id>      / EVENT#<time>         cleaning / rain / note
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

_table = None


def table():
    global _table
    if _table is None:
        import boto3
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


def to_dynamo(obj):
    """Floats -> Decimal (DynamoDB rejects floats)."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def from_dynamo(obj):
    if isinstance(obj, list):
        return [from_dynamo(v) for v in obj]
    if isinstance(obj, dict):
        return {k: from_dynamo(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def put(pk: str, sk: str, data: dict) -> None:
    table().put_item(Item=to_dynamo({"pk": pk, "sk": sk, **data}))


def get(pk: str, sk: str) -> dict | None:
    item = table().get_item(Key={"pk": pk, "sk": sk}).get("Item")
    return from_dynamo(item) if item else None


def query(pk: str, prefix: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
    while True:
        resp = table().query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return from_dynamo(items)
