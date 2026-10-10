"""Storage. On AWS: DynamoDB (TABLE_NAME) and S3 (PHOTO_BUCKET).
On a laptop (those variables unset): a JSON file and a photos folder under ./data/.

Item keys (pk / sk):
    PLAN#<id>        / META                 a saved Plan-mode result
    SYSTEM#<id>      / META                 a registered rooftop system
    SYSTEM#<id>      / READING#<time>       one reading (from a display photo or typed in)
    SYSTEM#<id>      / VERDICT#<date>       the day's diagnosis (summary)
    SYSTEM#<id>      / EVENT#<time>         cleaning / note
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCAL_DIR = os.environ.get("LOCAL_DATA_DIR") or os.path.join(_ROOT, "data")
_lock = threading.Lock()
_table = None
_s3 = None


def on_aws() -> bool:
    return bool(os.environ.get("TABLE_NAME"))


# --------------------------------------------------------------------------- helpers
def to_dynamo(obj):
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


# --------------------------------------------------------------------------- local JSON store
def _local_path() -> str:
    os.makedirs(_LOCAL_DIR, exist_ok=True)
    return os.path.join(_LOCAL_DIR, "local_db.json")


def _local_load() -> dict:
    try:
        with open(_local_path(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _local_save(db: dict) -> None:
    tmp = _local_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=1)
    os.replace(tmp, _local_path())


# --------------------------------------------------------------------------- DynamoDB
def table():
    global _table
    if _table is None:
        import boto3
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _table


# --------------------------------------------------------------------------- public API
def put(pk: str, sk: str, data: dict) -> None:
    item = {"pk": pk, "sk": sk, **data}
    if on_aws():
        table().put_item(Item=to_dynamo(item))
        return
    with _lock:
        db = _local_load()
        db[f"{pk}|{sk}"] = json.loads(json.dumps(item))
        _local_save(db)


def get(pk: str, sk: str) -> dict | None:
    if on_aws():
        item = table().get_item(Key={"pk": pk, "sk": sk}).get("Item")
        return from_dynamo(item) if item else None
    with _lock:
        return _local_load().get(f"{pk}|{sk}")


def delete(pk: str, sk: str) -> None:
    if on_aws():
        table().delete_item(Key={"pk": pk, "sk": sk})
        return
    with _lock:
        db = _local_load()
        db.pop(f"{pk}|{sk}", None)
        _local_save(db)


def query(pk: str, prefix: str) -> list[dict]:
    """All items under pk whose sk starts with prefix, sorted by sk."""
    if on_aws():
        from boto3.dynamodb.conditions import Key
        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
        while True:
            resp = table().query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return from_dynamo(items)
    with _lock:
        db = _local_load()
    rows = [v for v in db.values() if v.get("pk") == pk and v.get("sk", "").startswith(prefix)]
    return sorted(rows, key=lambda r: r["sk"])


def scan_prefix(pk_prefix: str, sk: str) -> list[dict]:
    """Items whose pk starts with pk_prefix and whose sk equals sk (used to list all systems)."""
    if on_aws():
        from boto3.dynamodb.conditions import Attr
        items, kwargs = [], {"FilterExpression": Attr("pk").begins_with(pk_prefix) & Attr("sk").eq(sk)}
        while True:
            resp = table().scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return from_dynamo(items)
    with _lock:
        db = _local_load()
    return [v for v in db.values() if v.get("pk", "").startswith(pk_prefix) and v.get("sk") == sk]


def scan_all() -> list[dict]:
    """Every item in the table (for the public impact totals; the table holds no photos)."""
    if on_aws():
        items, kwargs = [], {}
        while True:
            resp = table().scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return from_dynamo(items)
    with _lock:
        return list(_local_load().values())


def save_photo(system_id: str, data: bytes, ext: str) -> str:
    key = f"photos/{system_id}/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{new_id()[:6]}.{ext}"
    bucket = os.environ.get("PHOTO_BUCKET")
    if bucket:
        global _s3
        if _s3 is None:
            import boto3
            _s3 = boto3.client("s3")
        _s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=f"image/{'jpeg' if ext == 'jpg' else ext}")
    else:
        path = os.path.join(_LOCAL_DIR, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return key
