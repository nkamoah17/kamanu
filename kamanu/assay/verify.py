"""`kamanu assay --verify RECORD --key PUBLIC [--recompute]`: check a hallmark record.

The checks, each failing one printed as a line "FAIL <field>: ..." naming the record's top-level field:

    signature   alg Ed25519, its key is PUBLIC, and sig is a valid Ed25519 signature of canonical(digests) by it
                (kamanu.assay.ed25519, the standard library alone)
    digests     every top-level field's SHA-256 is the one signed: a changed, added or dropped field fails by name
    schema      the schema the package ships (kamanu/assay/hallmark.schema.json)
    fineness    follows from face and ceiling (three decimals, never rounded up)
    recompute   (--recompute) the embedded policy, profile and bounds, run through lint again here, give the same
                form, bounds, face, ceiling, fineness, stranded budget, levels, verdicts, failure, hypotheses and
                hashes

It reads nothing but the record, the key and the installed package, and opens no connection.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

RECOMPUTED = ("limit", "bounds", "face", "ceiling", "fineness", "stranded", "sound", "tight", "verdicts", "failure",
              "hypotheses", "hashes")


def _short(x) -> str:
    s = json.dumps(x, sort_keys=True, ensure_ascii=False)
    return s if len(s) <= 120 else s[:117] + "..."


def check(rec, public: bytes, recompute: bool) -> list[tuple[str, str]]:
    """[(field, what is wrong)]: empty when every check passes."""
    from kamanu.assay import ed25519, fineness
    from kamanu.assay import record as R
    if not isinstance(rec, dict):
        return [("record", "the record is not a JSON object")]
    bad: list[tuple[str, str]] = []
    sig = rec.get("signature")
    if not isinstance(sig, dict):
        return [("signature", "the record carries no signature object")]
    if sig.get("alg") != "Ed25519":
        bad.append(("signature", f"alg is {sig.get('alg')!r}, not Ed25519"))
    if sig.get("key") != public.hex():
        bad.append(("signature", "it was not made with the public key given (signature.key is another key)"))
    dg = sig.get("digests")
    try:
        ok = isinstance(dg, dict) and ed25519.verify(public, R.canonical(dg), bytes.fromhex(str(sig.get("sig"))))
    except ValueError:
        ok = False
    if not ok:
        bad.append(("signature", "sig is not a valid Ed25519 signature of the digests by the public key given"))
    if isinstance(dg, dict):
        now = R.digests(rec)
        for k in sorted(set(now) | set(dg)):
            if k not in dg:
                bad.append((k, "this field is not signed (it is not in signature.digests)"))
            elif k not in now:
                bad.append((k, "this field was signed and is missing from the record"))
            elif now[k] != dg[k]:
                bad.append((k, "this field changed after it was signed (its SHA-256 is not the signed digest)"))
    else:
        bad.append(("signature", "signature.digests is not an object"))
    for field, err in R.schema_errors(rec):
        bad.append((field or "record", f"schema: {err}"))
    face, ceiling = rec.get("face"), rec.get("ceiling")
    try:
        want = fineness(face, ceiling)
    except (ValueError, TypeError):
        want = None
    if want is None:
        bad.append(("fineness", f"it cannot follow from face {_short(face)} and ceiling {_short(ceiling)}"))
    elif rec.get("fineness") != want:
        bad.append(("fineness", f"it is {_short(rec.get('fineness'))}; face {face} over ceiling {ceiling} is {want} "
                                f"(three decimals, never rounded up)"))
    if recompute:
        bad += recomputed(rec)
    return bad


def recomputed(rec: dict) -> list[tuple[str, str]]:
    """Run the embedded policy and profile through lint here and compare."""
    from kamanu.assay import hallmark as H
    try:
        text = rec["limit"]["policy"]
        profile = rec["engine"]["profile"]
        b = rec["bounds"]
        in_flight, failures, amounts = int(b["in_flight"]), int(b["failures"]), b.get("amounts")
        face = rec["face"]
        if not isinstance(text, str) or not isinstance(profile, dict) or not isinstance(face, int):
            raise TypeError("not a policy text, a profile object and an integer face")
    except (KeyError, TypeError, ValueError) as e:
        return [("limit", f"recompute: the record does not hold a policy, a profile, bounds and a face to run ({e})")]
    tmp = Path(tempfile.mkdtemp(prefix="kamanu-assay-"))
    try:
        pol, eng = tmp / "policy.dw", tmp / "engine.json"
        pol.write_bytes(text.encode("utf-8"))
        eng.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        am = ",".join(str(x) for x in amounts) if isinstance(amounts, list) and amounts else None
        rc, obj, err = H.run_lint(str(pol), str(eng), face, in_flight, failures, am)
        try:
            got = H.assay(obj, profile, text, str(eng), in_flight, failures)
        except H.Undecided as e:
            return [(k, f"recompute: lint here does not decide the embedded policy ({e})")
                    for k in ("limit", "ceiling", "stranded")]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    bad = []
    for k in RECOMPUTED:
        have = rec.get(k)
        want = got[k]
        if k == "limit":
            have = (have or {}).get("form") if isinstance(have, dict) else have
            want = want["form"]
        if have != want:
            bad.append((k, f"recompute: the record says {_short(have)}; its policy and profile give {_short(want)}"))
    return bad


def verify(record: str, key: str, recompute: bool) -> int:
    from kamanu.assay import record as R
    try:
        public = R.read_key(key)
    except ValueError as e:
        print(f"kamanu assay --verify: {e}", file=sys.stderr)
        return 3
    try:
        rec = json.loads(Path(record).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"kamanu assay --verify: cannot read {record}: {e}", file=sys.stderr)
        return 3
    bad = check(rec, public, recompute)
    if bad:
        for field, why in bad:
            print(f"FAIL {field}: {why}")
        print(f"kamanu assay --verify: {record}: {len(bad)} check(s) do not pass")
        return 1
    print(f"OK signature: Ed25519 by {public.hex()}")
    print("OK digests: every field is the one signed")
    print("OK schema: hallmark-v1")
    print(f"OK fineness: {rec['fineness']} is face {rec['face']} over ceiling {rec['ceiling']}, rounded down")
    if recompute:
        print("OK recompute: the embedded policy and profile give the same form, bounds, face, ceiling, fineness, "
              "stranded budget, levels, verdicts, shortest trace, hypotheses and hashes")
    print(f"kamanu assay --verify: {record}: verified")
    return 0
