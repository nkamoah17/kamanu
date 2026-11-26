"""The hallmark record (hallmark-v1): its canonical form, its signature, its schema and its hold.

    canonical(x) -> bytes            json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False), UTF-8
    digests(rec) -> {field: sha256 hex of canonical(value)} for every top-level field but "signature"
    sign(rec, seed) -> rec with "signature": {"alg": "Ed25519", "key", "digests", "sig"}
    read_key(path) -> bytes          a key file: 64 hex digits (a 32-byte seed or public key)
    schema() -> the JSON Schema the package ships (kamanu/assay/hallmark.schema.json, equal to
                schema/hallmark.schema.json)
    schema_errors(inst, sch) -> [(top-level field or "", message)]
    held(third_party, notified, today, days) -> bool   R8b's hold (rule E5)

Standard library only.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

from kamanu.assay import ed25519

FORMAT = "hallmark-v1"
SCHEMA = Path(__file__).resolve().parent / "hallmark.schema.json"
HOLD_ENV = "KAMANU_SHARE_HOLD_DAYS"            # R8b's hold, in days from the day the maintainer was told
HOLD_DEFAULT = 30
KEY_ENV = "KAMANU_ASSAY_KEY"
FIELDS = ("hallmark", "date", "limit", "engine", "bounds", "face", "ceiling", "fineness", "stranded", "sound", "tight",
          "verdicts", "failure", "hypotheses", "hashes", "commit", "version", "third_party", "notified", "held",
          "signature")


def canonical(x) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def digests(rec: dict) -> dict:
    return {k: sha256(canonical(v)) for k, v in rec.items() if k != "signature"}


def read_key(path) -> bytes:
    """The 32 bytes a key file holds as 64 hex digits (whitespace around them ignored). ValueError otherwise."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError as e:
        raise ValueError(f"cannot read the key file {path}: {e.strerror or e}") from None
    if not re.fullmatch(r"[0-9a-fA-F]{64}", text):
        raise ValueError(f"the key file {path} does not hold 64 hex digits")
    return bytes.fromhex(text)


def sign(rec: dict, seed: bytes) -> dict:
    out = {k: v for k, v in rec.items() if k != "signature"}
    dg = digests(out)
    out["signature"] = {"alg": "Ed25519", "key": ed25519.public_key(seed).hex(), "digests": dg,
                        "sig": ed25519.sign(seed, canonical(dg)).hex()}
    return out


def hold_days() -> int:
    raw = os.environ.get(HOLD_ENV)
    if raw is None or not raw.strip():
        return HOLD_DEFAULT
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{HOLD_ENV} is {raw!r}, not a whole number of days") from None


def today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def held(third_party: bool, notified: str | None, now: datetime.date, days: int) -> bool:
    """R8b's rule: someone else's engine is held until its maintainer was told and `days` days have passed."""
    if not third_party:
        return False
    if notified is None:
        return True
    return now < datetime.date.fromisoformat(notified) + datetime.timedelta(days=days)


def release_day(notified: str | None, days: int) -> datetime.date | None:
    return None if notified is None else datetime.date.fromisoformat(notified) + datetime.timedelta(days=days)


# ---------------------------------------------------------------- the schema (a reader of the keywords it uses)
def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _is(x, t: str) -> bool:
    if t == "object":
        return isinstance(x, dict)
    if t == "array":
        return isinstance(x, list)
    if t == "string":
        return isinstance(x, str)
    if t == "integer":
        return isinstance(x, int) and not isinstance(x, bool)
    if t == "number":
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    if t == "boolean":
        return isinstance(x, bool)
    if t == "null":
        return x is None
    raise ValueError(f"the schema names a type this reader does not know: {t}")


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b if isinstance(a, bool) or isinstance(b, bool) else a == b


def _errors(inst, sch, root, path: str) -> list[str]:
    if sch is True or sch == {}:
        return []
    if sch is False:
        return [f"{path}: nothing is allowed here"]
    errs: list[str] = []
    if "$ref" in sch:
        node = root
        for part in [p for p in sch["$ref"].lstrip("#").split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        errs += _errors(inst, node, root, path)
    if "type" in sch:
        ts = sch["type"] if isinstance(sch["type"], list) else [sch["type"]]
        if not any(_is(inst, t) for t in ts):
            return errs + [f"{path}: {json.dumps(inst)[:60]} is not {' or '.join(ts)}"]
    if "const" in sch and not _same(inst, sch["const"]):
        errs.append(f"{path}: {json.dumps(inst)[:60]} is not {json.dumps(sch['const'])}")
    if "enum" in sch and not any(_same(inst, v) for v in sch["enum"]):
        errs.append(f"{path}: {json.dumps(inst)[:60]} is not one of {', '.join(map(json.dumps, sch['enum']))}")
    if isinstance(inst, str):
        if "minLength" in sch and len(inst) < sch["minLength"]:
            errs.append(f"{path}: shorter than {sch['minLength']}")
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            errs.append(f"{path}: {inst[:60]!r} does not match {sch['pattern']}")
    if _is(inst, "number") and "minimum" in sch and inst < sch["minimum"]:
        errs.append(f"{path}: {inst} is below {sch['minimum']}")
    if isinstance(inst, dict):
        for k in sch.get("required", []):
            if k not in inst:
                errs.append(f"{path}: {k} is missing")
        props = sch.get("properties", {})
        for k, v in inst.items():
            if k in props:
                errs += _errors(v, props[k], root, f"{path}.{k}")
            elif "additionalProperties" in sch:
                errs += _errors(v, sch["additionalProperties"], root, f"{path}.{k}")
    if isinstance(inst, list):
        if "minItems" in sch and len(inst) < sch["minItems"]:
            errs.append(f"{path}: fewer than {sch['minItems']} items")
        if isinstance(sch.get("items"), (dict, bool)):
            for i, v in enumerate(inst):
                errs += _errors(v, sch["items"], root, f"{path}[{i}]")
    for s in sch.get("allOf", []):
        errs += _errors(inst, s, root, path)
    if "anyOf" in sch:
        branches = [_errors(inst, s, root, path) for s in sch["anyOf"]]
        if all(branches):
            errs.append(f"{path}: matches none of its forms ({'; '.join(b[0] for b in branches)})")
    return errs


def schema_errors(inst, sch: dict | None = None) -> list[tuple[str, str]]:
    """(the top-level field an error is about, or "" for the record as a whole, the error)."""
    sch = schema() if sch is None else sch
    out = []
    for e in _errors(inst, sch, sch, "$"):
        m = re.match(r"\$\.([A-Za-z_]\w*)", e)
        field = m.group(1) if m else ""
        if not field:
            m = re.match(r"\$: (\w+) is missing", e)
            field = m.group(1) if m else ""
        out.append((field, e))
    return out
