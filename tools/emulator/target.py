"""The tool side served by the AWS emulator (card R6c): a Lambda target that acts, holds, and
then fails or answers.

target(event, table) is the logic. It loads without boto3. handler(event, context) is the
Lambda entry point. It binds the held DynamoDB table named by $HELD_TABLE (default
kamanu-held) and calls target.

    event {"call_id": str, "amount": int, "hold_s": float >= 0, "fail_after_act": bool}

It acts first, with exactly one put_item({call_id, amount, held_at}), where held_at is the UTC
time it acted. It then holds hold_s seconds counted from the put. Then it raises if
fail_after_act; otherwise it returns {"call_id", "amount", "held_at"}.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone


class FailedAfterAct(RuntimeError):
    """The target acted (its item is in the held table) and then failed, as asked."""


def _utc(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def target(event: dict, table) -> dict:
    call_id = str(event["call_id"])
    amount = int(event["amount"])
    hold_s = float(event.get("hold_s", 0) or 0)
    if hold_s < 0:
        raise ValueError(f"hold_s {hold_s} < 0")
    fail = bool(event.get("fail_after_act", False))

    acted = time.time()
    held_at = _utc(acted)
    table.put_item(Item={"call_id": call_id, "amount": amount, "held_at": held_at})
    deadline = time.time() + hold_s                           # the hold counts from the put's return

    remaining = deadline - time.time()
    while remaining > 0:
        time.sleep(remaining)
        remaining = deadline - time.time()

    if fail:
        raise FailedAfterAct(f"call {call_id} acted at {held_at} and failed after acting")
    return {"call_id": call_id, "amount": amount, "held_at": held_at}


def handler(event, context=None):                            # the Lambda entry point
    import boto3                                              # only inside Lambda

    table = boto3.resource("dynamodb").Table(os.environ.get("HELD_TABLE", "kamanu-held"))
    return target(event, table)
