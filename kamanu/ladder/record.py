"""R8b: the corpus record (record-v1): schema, redaction, local-first sharing, licence.

    validate(rec) -> list[str]     the errors of rec against schemas/record-v1.json ([] when valid)
    redact(rec) -> dict            a redacted copy: identifiers replaced by stable <KIND_n> tokens
    write(rec, root=None) -> Path  writes rec locally (root, else $KAMANU_RECORDS_DIR, else
                                   ~/.kamanu/records); never uploads
    share(rec, *, confirm, upload, today=None) -> dict
                                   the hold, then the redacted preview, then a yes, then one upload
    hunt_record(rep, ...) / check_record(verdict, ...)
                                   the record a `kamanu hunt` / `kamanu check` run writes

A record is local by default. Nothing leaves the machine except through share(), which shows
the redacted record (the exact payload) and uploads only after confirm() says yes. A record of
another party's engine (engine.third_party) is refused until its maintainer was notified
("notified": YYYY-MM-DD) at least KAMANU_SHARE_HOLD_DAYS (default 30) days ago. Every shared
record carries "license": "CDLA-Permissive-2.0" (RECORDS-LICENSE); the code stays Apache-2.0.

Redaction replaces, in every string of the record (and in every JSON document held in a string,
at any depth, re-encoded only when something in it changed): AWS ARNs; AWS account IDs; access
key IDs (AKIA/ASIA/AIDA/AROA...); secret keys, session tokens, bearer tokens, JWTs and API keys;
gateway IDs (in a gateway URL, --gateway-identifier, gatewayId); session IDs (Mcp-Session-Id,
sessionId, UUIDs); hostnames under any top-level domain other than a short list of public ones
(a dotted name that is plainly a file or module name -- FILE_EXTS, MODULE_ROOTS, `python -m X` -- is
kept); IPv4 and IPv6 addresses; the
owner of a rotn upstream URL and any IAM user name the record's ARNs name. A value under a
sensitive JSON key (SecretAccessKey, SessionToken, Host, sourceIp, ...) is replaced whole. The
same identifier of one kind gets the same placeholder throughout one record; numbering follows
the record's order, so redact is deterministic, and it is idempotent (a placeholder is never
redacted again, and new numbers start above any placeholder already present).
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

LICENSE = "CDLA-Permissive-2.0"
SCHEMA_ID = "record-v1"
HOLD_ENV = "KAMANU_SHARE_HOLD_DAYS"
HOLD_DEFAULT = 30
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = ROOT / "schemas" / "record-v1.json"

DATE_RX = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$"
DAY_RX = r"^\d{4}-\d\d-\d\d$"

# The schema, as schemas/record-v1.json holds it (the file is read when present; this copy keeps
# validate() working from an installed wheel, and a test keeps the two equal).
SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://kamanu.dev/schemas/record-v1.json",
    "title": "KAMANU corpus record, version 1",
    "type": "object",
    "required": ["schema", "command", "engine", "date", "live", "probes", "profile", "policy",
                 "scorecard", "fix", "kamanu_version", "calibration_version", "seed", "notified"],
    "properties": {
        "schema": {"const": "record-v1"},
        "command": {"enum": ["hunt", "check", "fix"]},
        "engine": {
            "type": "object",
            "required": ["name", "version", "third_party"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string"},
                "third_party": {"type": "boolean"},
            },
        },
        "date": {"type": "string", "pattern": DATE_RX},
        "live": {"type": "boolean"},
        "probes": {"type": "array", "items": {"$ref": "#/$defs/probe"}},
        "profile": {
            "type": "object",
            "required": ["answers"],
            "properties": {"answers": {"type": "array", "items": {"$ref": "#/$defs/answer"}}},
        },
        "policy": {
            "type": "object",
            "required": ["text", "shape"],
            "properties": {"text": {"type": ["string", "null"]}, "shape": {"type": "string"}},
        },
        "scorecard": {"type": "array", "items": {"type": "string"}},
        "fix": {"anyOf": [{"type": "null"}, {
            "type": "object",
            "required": ["proposed", "accepted"],
        }]},
        "kamanu_version": {"type": "string"},
        "calibration_version": {"type": ["string", "null"]},
        "seed": {"type": ["integer", "null"]},
        "notified": {"anyOf": [{"type": "null"}, {"type": "string", "pattern": DAY_RX}]},
        "license": {"const": LICENSE},
    },
    "$defs": {
        "probe": {
            "type": "object",
            "required": ["id", "request", "response", "verdict"],
            "properties": {"id": {"type": "string"}, "verdict": {"type": "string"}},
        },
        "answer": {
            "type": "object",
            "required": ["question", "answer", "evidence_class"],
            "properties": {"question": {"type": "string"},
                           "evidence_class": {"type": "string", "minLength": 1}},
        },
    },
}


# ---------------------------------------------------------------- validation
def schema() -> dict:
    try:
        return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SCHEMA


def _is(x, t: str) -> bool:
    return {"null": lambda: x is None,
            "boolean": lambda: isinstance(x, bool),
            "integer": lambda: isinstance(x, int) and not isinstance(x, bool),
            "number": lambda: isinstance(x, (int, float)) and not isinstance(x, bool),
            "string": lambda: isinstance(x, str),
            "array": lambda: isinstance(x, list),
            "object": lambda: isinstance(x, dict)}.get(t, lambda: False)()


def _same(a, b) -> bool:
    if _is(a, "number") and _is(b, "number"):
        return a == b
    return type(a) is type(b) and a == b


def _errors(inst, sch, root, path) -> list[str]:
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
            return errs + [f"{path}: not {' or '.join(ts)}"]
    if "const" in sch and not _same(inst, sch["const"]):
        errs.append(f"{path}: must be {sch['const']!r}")
    if "enum" in sch and not any(_same(inst, v) for v in sch["enum"]):
        errs.append(f"{path}: must be one of {sch['enum']}")
    if isinstance(inst, str):
        if len(inst) < sch.get("minLength", 0):
            errs.append(f"{path}: empty" if sch["minLength"] == 1 else f"{path}: too short")
        if "pattern" in sch and not re.search(sch["pattern"], inst):
            errs.append(f"{path}: {inst!r} does not match {sch['pattern']}")
    if _is(inst, "number") and "minimum" in sch and inst < sch["minimum"]:
        errs.append(f"{path}: below {sch['minimum']}")
    if isinstance(inst, dict):
        for k in sch.get("required", []):
            if k not in inst:
                errs.append(f"{path}: missing {k}")
        props = sch.get("properties", {})
        for k, v in inst.items():
            if k in props:
                errs += _errors(v, props[k], root, f"{path}.{k}")
            elif "additionalProperties" in sch:
                errs += _errors(v, sch["additionalProperties"], root, f"{path}.{k}")
    if isinstance(inst, list):
        if len(inst) < sch.get("minItems", 0):
            errs.append(f"{path}: fewer than {sch['minItems']} items")
        if isinstance(sch.get("items"), (dict, bool)):
            for i, v in enumerate(inst):
                errs += _errors(v, sch["items"], root, f"{path}[{i}]")
    for s in sch.get("allOf", []):
        errs += _errors(inst, s, root, path)
    if "anyOf" in sch and all(_errors(inst, s, root, path) for s in sch["anyOf"]):
        errs.append(f"{path}: matches none of the allowed forms")
    if "oneOf" in sch and sum(not _errors(inst, s, root, path) for s in sch["oneOf"]) != 1:
        errs.append(f"{path}: does not match exactly one allowed form")
    return errs


def validate(rec) -> list[str]:
    """The errors of rec against record-v1 ([] when valid)."""
    s = schema()
    return _errors(rec, s, s, "$")


# ---------------------------------------------------------------- redaction
PLACEHOLDER = re.compile(r"<([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*?)_(\d+)>")
_ANY_PLACEHOLDER = re.compile(r"^<[A-Z][A-Z0-9_]*>$")

PUBLIC_HOSTS = frozenset({
    "github.com", "www.github.com", "raw.githubusercontent.com", "gitlab.com", "pypi.org",
    "amazon.com", "aws.amazon.com", "docs.aws.amazon.com", "amazonaws.com",
    "example.com", "example.org", "example.net", "kamanu.dev", "json-schema.org",
    "cdla.dev", "www.apache.org", "apache.org", "spdx.org", "lamport.azurewebsites.net",
})
# A dotted name is a host to redact under ANY top-level domain (R11d; R8b kept a host only when its
# top-level domain was on an allowlist, so .lan, .home.arpa, .test, .dev, ... leaked: NOTES N227),
# unless it is on PUBLIC_HOSTS or is plainly a file or module name: it ends in one of the file
# extensions KAMANU's own policies, specs, model configs, schemas, records, modules, docs and plan
# use (FILE_EXTS), or it is a module path under one of MODULE_ROOTS, or it follows `python -m`.
FILE_EXTS = frozenset({
    "dw", "tla", "cfg", "json", "jsonl", "py", "pyi", "md", "yaml", "yml", "toml", "txt", "itf",
    "csv", "ini", "rst", "html", "svg", "png", "whl", "gz", "zip", "tar", "sh", "ps1", "log",
})
MODULE_ROOTS = frozenset({"kamanu"})

# Values under these JSON keys (compared lower-case, without - and _) are replaced whole.
SENSITIVE_KEYS = {
    "account": "ACCOUNT", "accountid": "ACCOUNT", "awsaccountid": "ACCOUNT", "owneraccount": "ACCOUNT",
    "accesskeyid": "KEY", "awsaccesskeyid": "KEY",
    "secretaccesskey": "SECRET", "awssecretaccesskey": "SECRET", "secret": "SECRET",
    "password": "SECRET", "clientsecret": "SECRET",
    "sessiontoken": "TOKEN", "awssessiontoken": "TOKEN", "token": "TOKEN", "accesstoken": "TOKEN",
    "idtoken": "TOKEN", "refreshtoken": "TOKEN", "authorization": "TOKEN", "apikey": "TOKEN",
    "xapikey": "TOKEN", "bearer": "TOKEN",
    "gatewayid": "GATEWAY", "gatewayidentifier": "GATEWAY", "gatewayarn": "ARN",
    "sessionid": "SESSION", "mcpsessionid": "SESSION",
    "host": "HOST", "hostname": "HOST", "hostheader": "HOST", "endpoint": "HOST",
    "sourceip": "IP", "sourceipaddress": "IP", "clientip": "IP", "remoteaddr": "IP", "ip": "IP",
    "ipaddress": "IP", "xforwardedfor": "IP",
    "username": "USER", "iamuser": "USER", "arn": "ARN", "resourcearn": "ARN", "rolearn": "ARN",
}

_KV_KEYS = (r"SecretAccessKey|SessionToken|AccessKeyId|aws_session_token|aws_access_key_id|"
            r"gatewayId|gateway_id|gatewayIdentifier|sessionId|session_id|sourceIp|source_ip|"
            r"api[_-]?key|access[_-]?token|password|UserName|user_name")
_KV_KIND = {"secretaccesskey": "SECRET", "sessiontoken": "TOKEN", "accesskeyid": "KEY",
            "awssessiontoken": "TOKEN", "awsaccesskeyid": "KEY", "gatewayid": "GATEWAY",
            "gatewayidentifier": "GATEWAY", "sessionid": "SESSION", "sourceip": "IP",
            "apikey": "TOKEN", "accesstoken": "TOKEN", "password": "SECRET", "username": "USER"}

_VAL = r"(?!<)([^\s\"'`,;<>\\)}\]]+)"     # a value after a key, not already a placeholder

# (kind, compiled regex, group holding the identifier). Order matters: specific forms first.
RULES: list[tuple[str, re.Pattern, int]] = [
    ("ARN", re.compile(r"(?<![\w<-])(arn:aws[\w-]*:[\w-]*:[\w-]*:[\w-]*:[\w/+=,.@:*-]*[\w/+=@*-])"), 1),
    ("USER", re.compile(r"(github\.com[/:])(?!<)([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)(?=/rotn(?:\.git)?(?![\w-]))", re.I), 2),
    ("GATEWAY", re.compile(r"(?<![\w<.-])([a-z0-9][a-z0-9-]*)(?=\.gateway\.bedrock-agentcore\.)", re.I), 1),
    ("GATEWAY", re.compile(r"(--gateway-(?:id|identifier)(?:\s+|=)[\"']?)" + _VAL), 2),
    ("SESSION", re.compile(r"(mcp-session-id[\"']?\s*[:=]\s*[\"']?)" + _VAL, re.I), 2),
    ("SECRET", re.compile(r"(aws_secret_access_key[\"']?\s*[:=]\s*[\"']?)" + _VAL, re.I), 2),
    ("TOKEN", re.compile(r"(\bBearer\s+)" + _VAL, re.I), 2),
    ("TOKEN", re.compile(r"(x-api-key[\"']?\s*[:=]\s*[\"']?)" + _VAL, re.I), 2),
    ("KV", re.compile(r"((?<![\w-])[\"']?(" + _KV_KEYS + r")[\"']?\s*[:=]\s*[\"']?)" + r"(?!<)([^\s\"'`,;<>\\)}\]]+)", re.I), 3),
    ("KEY", re.compile(r"(?<![A-Za-z0-9])((?:AKIA|ASIA|AIDA|AROA|AGPA|ANPA|ANVA|AIPA|APKA)[A-Z0-9]{16})(?![A-Za-z0-9])"), 1),
    ("TOKEN", re.compile(r"(?<![\w-])(eyJ[\w-]+\.[\w-]+\.[\w-]*)"), 1),
    ("SESSION", re.compile(r"(?<![\w-])([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![\w-])", re.I), 1),
    ("IP", re.compile(r"(?<![\w:.<])((?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4})(?![\w:])", re.I), 1),
    ("IP", re.compile(r"(?<![\w:.<])((?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,5})?)(?![\w:])", re.I), 1),
    ("HOST", re.compile(r"(?<![\w.<-])([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)(?![\w-]|\.\w)", re.I), 1),
    ("IP", re.compile(r"(?<![\w.<])((?:\d{1,3}\.){3}\d{1,3})(?![\w]|\.\d)"), 1),
    ("ACCOUNT", re.compile(r"(?<![\w.<-])(\d{12})(?![\w-])"), 1),
]


def _host_ok(h: str, before: str = "") -> bool:
    """True when h (a dotted name; `before` is the text just ahead of it) is a hostname to redact:
    any dotted name whose last label is a letter-led top-level domain of two or more characters,
    unless it is a public host, a file name (FILE_EXTS), a module path (MODULE_ROOTS) or the
    module of `python -m`."""
    low = h.lower()
    labels = low.split(".")
    last = labels[-1]
    if low in PUBLIC_HOSTS or len(last) < 2 or not last[0].isalpha():
        return False
    if last in FILE_EXTS or labels[0] in MODULE_ROOTS:
        return False
    if re.search(r"(?:^|\s)-m\s+$", before):
        return False
    return not all(l.isdigit() for l in labels)


def _ipv4_ok(s: str) -> bool:
    return all(0 <= int(p) <= 255 for p in s.split("."))


class _Redactor:
    def __init__(self, rec):
        self.table: dict[tuple[str, str], str] = {}
        self.next: dict[str, int] = {}
        for s in _all_strings(rec):
            for m in PLACEHOLDER.finditer(s):
                self.next[m.group(1)] = max(self.next.get(m.group(1), 0), int(m.group(2)))
        # IAM user names named by the record's ARNs (H9: the IAM user name is also the
        # repository owner's handle, so it is redacted wherever it appears).
        self.users = sorted({m.group(1) for s in _all_strings(rec)
                             for m in re.finditer(r"arn:aws[\w-]*:iam::[^:\s\"]*:user/(?:[\w+=,.@-]+/)*([\w+=,.@-]+)", s)
                             if len(m.group(1)) >= 3}, key=lambda u: (-len(u), u))

    def ph(self, kind: str, value: str) -> str:
        key = (kind, value.lower() if kind in ("HOST", "IP", "SESSION") else value)
        if key not in self.table:
            n = self.next.get(kind, 0) + 1
            self.next[kind] = n
            self.table[key] = f"<{kind}_{n}>"
        return self.table[key]

    # ---- strings
    def text(self, s: str) -> str:
        for kind, rx, g in RULES:
            s = rx.sub(lambda m, kind=kind, g=g: self._sub(m, kind, g), s)
        for u in self.users:
            s = re.sub(rf"(?<![\w<]){re.escape(u)}(?![\w>])",
                       lambda m: self.ph("USER", m.group(0)), s, flags=re.I)
        return s

    def _sub(self, m: re.Match, kind: str, g: int) -> str:
        val = m.group(g)
        if _ANY_PLACEHOLDER.match(val):
            return m.group(0)
        if kind == "HOST" and not _host_ok(val, m.string[max(0, m.start(g) - 12): m.start(g)]):
            return m.group(0)
        if kind == "IP" and "." in val and not _ipv4_ok(val):
            return m.group(0)
        if kind == "KV":
            kind = _KV_KIND.get(re.sub(r"[-_]", "", m.group(2).lower()), "SECRET")
        s, e = m.span(g)
        base = m.start(0)
        whole = m.group(0)
        return whole[: s - base] + self.ph(kind, val) + whole[e - base:]

    def string(self, s: str, depth: int = 0) -> str:
        if depth < 8 and s.lstrip()[:1] in ("{", "["):
            try:
                doc = json.loads(s)
            except ValueError:
                doc = None
            if isinstance(doc, (dict, list)):
                new = self.value(doc, depth + 1)
                if new == doc:
                    return s
                return _dump_like(s, doc, new)
        return self.text(s)

    def value(self, x, depth: int = 0):
        if isinstance(x, str):
            return self.string(x, depth)
        if isinstance(x, list):
            return [self.value(v, depth) for v in x]
        if isinstance(x, dict):
            out = {}
            for k, v in x.items():
                kind = SENSITIVE_KEYS.get(re.sub(r"[-_ ]", "", str(k).lower()))
                nk = self.text(k) if isinstance(k, str) else k
                if kind and isinstance(v, str) and v and not _ANY_PLACEHOLDER.match(v):
                    if kind == "HOST" and v.split(":")[0].lower() in PUBLIC_HOSTS:
                        out[nk] = self.value(v, depth)
                    else:
                        out[nk] = self.ph(kind, v)
                elif kind == "ACCOUNT" and isinstance(v, int) and not isinstance(v, bool) and len(str(v)) == 12:
                    out[nk] = self.ph(kind, str(v))
                else:
                    out[nk] = self.value(v, depth)
            return out
        return x


def _dump_like(original: str, old, new) -> str:
    """new encoded as JSON in the layout original used for old (default layout otherwise)."""
    for kw in ({}, {"separators": (",", ":")}, {"indent": 2}, {"indent": 1}, {"indent": 4},
               {"ensure_ascii": False}, {"separators": (",", ":"), "ensure_ascii": False},
               {"indent": 2, "ensure_ascii": False}):
        if json.dumps(old, **kw) == original:
            return json.dumps(new, **kw)
    return json.dumps(new)


def _all_strings(x, out=None, depth=0) -> list[str]:
    out = [] if out is None else out
    if isinstance(x, str):
        out.append(x)
        if depth < 8 and x.lstrip()[:1] in ("{", "["):
            try:
                _all_strings(json.loads(x), out, depth + 1)
            except ValueError:
                pass
    elif isinstance(x, dict):
        for k, v in x.items():
            out.append(str(k))
            _all_strings(v, out, depth)
    elif isinstance(x, list):
        for v in x:
            _all_strings(v, out, depth)
    return out


# Top-level fields that are structure, not content: never touched.
KEEP = ("schema", "command", "date", "live", "kamanu_version", "calibration_version", "seed",
        "notified", "license")


def redact(rec: dict) -> dict:
    """A redacted copy of rec; rec itself is not changed."""
    rec = copy.deepcopy(rec)
    r = _Redactor(rec)
    out = {}
    for k, v in rec.items():
        if k in KEEP:
            out[k] = v
        elif k == "engine" and isinstance(v, dict):
            out[k] = {ek: (ev if ek == "third_party" else r.value(ev)) for ek, ev in v.items()}
        else:
            out[k] = r.value(v)
    return out


# ---------------------------------------------------------------- local records
def records_dir(root=None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("KAMANU_RECORDS_DIR")
    return Path(env) if env else Path.home() / ".kamanu" / "records"


def write(rec: dict, root=None) -> Path:
    """Writes rec as JSON into root, else $KAMANU_RECORDS_DIR, else ~/.kamanu/records. Never
    uploads. A record that is not live is never written under an evidence/ directory."""
    d = records_dir(root)
    if not rec.get("live") and "evidence" in d.resolve().parts:
        raise ValueError(f"{d}: a record that is not live is never written under evidence/")
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rec, indent=2, ensure_ascii=False) + "\n"
    stamp = re.sub(r"[^0-9T]", "", str(rec.get("date", "")))[:15] or "undated"
    name = f"{rec.get('command', 'record')}-{stamp}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}"
    p = d / f"{name}.json"
    n = 1
    while p.exists() and p.read_text(encoding="utf-8") != text:
        n += 1
        p = d / f"{name}-{n}.json"
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------- sharing
def hold_days() -> int:
    raw = os.environ.get(HOLD_ENV, "").strip()
    if not raw:
        return HOLD_DEFAULT
    try:
        h = int(raw)
    except ValueError:
        raise ValueError(f"{HOLD_ENV}={raw!r} is not a whole number of days") from None
    if h < 0:
        raise ValueError(f"{HOLD_ENV}={raw!r} is negative")
    return h


def held(rec: dict, today: dt.date | None = None) -> str | None:
    """The reason rec may not be shared yet (the never-cut rule), or None."""
    eng = rec.get("engine") or {}
    if not eng.get("third_party"):
        return None
    today = today or dt.datetime.now(dt.timezone.utc).date()
    name = eng.get("name", "?")
    note = rec.get("notified")
    if not note:
        return (f"the record names another party's engine ({name}) and no maintainer-notified date is "
                f"recorded: set \"notified\" to the day its maintainer was told, then wait the hold")
    try:
        day = dt.date.fromisoformat(note)
    except (TypeError, ValueError):
        return f"\"notified\" is {note!r}, not a YYYY-MM-DD date"
    h = hold_days()
    until = day + dt.timedelta(days=h)
    if today < until:
        return (f"the record names another party's engine ({name}); its maintainer was notified on "
                f"{day.isoformat()} and the hold of {h} days ({HOLD_ENV}) ends on {until.isoformat()}")
    return None


def payload_of(rec: dict) -> dict:
    p = redact(rec)
    p["license"] = LICENSE
    return p


def preview_of(payload: dict) -> str:
    return ("This is the record that would be shared, exactly as it would be sent (redacted). "
            f"It is published under {LICENSE} (see RECORDS-LICENSE).\n"
            + json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def share(rec: dict, *, confirm, upload, today: dt.date | None = None) -> dict:
    """Shares rec: refuses while the hold applies; otherwise shows the redacted payload through
    confirm(preview) once and, on a yes, calls upload(payload) once."""
    try:
        why = held(rec, today)
    except ValueError as e:
        return {"shared": False, "reason": str(e)}
    if why:
        return {"shared": False, "reason": why}
    payload = payload_of(rec)
    errs = validate(payload)
    if errs:
        return {"shared": False, "reason": "the record is not a valid record-v1: " + "; ".join(errs[:5])}
    if not confirm(preview_of(payload)):
        return {"shared": False, "reason": "not confirmed: nothing was sent"}
    resp = upload(payload)
    return {"shared": True, "reason": "shared after the preview and a yes", "response": resp}


# ---------------------------------------------------------------- records of runs
def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def kamanu_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("kamanu")
    except (ImportError, PackageNotFoundError):
        import kamanu
        return str(getattr(kamanu, "__version__", "unknown"))
    except Exception:  # noqa: BLE001 - a broken metadata install still writes a record
        return "unknown"


def policy_shape(text: str | None) -> str:
    if not text:
        return "unknown"
    try:
        from kamanu.hunt.examples import classify_text
        c = classify_text(text)
    except Exception:  # noqa: BLE001 - the shape is descriptive; an unreadable policy has none
        return "unknown"
    return str(c.get("shape") or c.get("class") or "unknown")


def evidence_class(provenance) -> str:
    """The evidence class of a profile answer, from the provenance KAMANU recorded for it."""
    p = str(provenance or "").lower()
    if not p:
        return "not exercised"
    if "default" in p or "assum" in p or "pessimistic" in p:
        return "default"
    if "doc" in p:
        return "docs"
    if "probe" in p or "hunt" in p or "observ" in p or "trial" in p:
        return "probe"
    if "reference" in p or "kernel" in p or "white" in p:
        return "white-box"
    return p


def base(command: str, engine: dict, *, live: bool, policy_text: str | None, seed=None) -> dict:
    return {"schema": SCHEMA_ID, "command": command, "engine": engine, "date": now_utc(), "live": live,
            "probes": [], "profile": {"answers": []},
            "policy": {"text": policy_text, "shape": policy_shape(policy_text)},
            "scorecard": [], "fix": None, "kamanu_version": kamanu_version(),
            "calibration_version": None, "seed": seed, "notified": None}


def hunt_record(rep: dict, *, adapter: str, engine_version: str, policy_text: str, live: bool) -> dict:
    """The record of one `kamanu hunt`: its probes (every issue, verbatim as the hunt saw it),
    the inferred profile (each answer from the probes), the policy and five scorecard lines."""
    eng = {"name": "reference" if adapter == "reference" else adapter, "version": engine_version,
           "third_party": adapter != "reference"}
    rec = base("hunt", eng, live=live, policy_text=policy_text)
    for i, s in enumerate(rep.get("sessions", [])):
        for j, op in enumerate(s.get("ops", [])):
            if op.get("op") != "issue":
                continue
            rec["probes"].append({"id": f"s{i}.op{j}",
                                  "request": {"session": i, "purpose": s.get("purpose"), "op": j,
                                              "amount": op.get("amount")},
                                  "response": {k: v for k, v in op.items() if k not in ("op", "amount")},
                                  "verdict": str(op.get("verdict"))})
    answers = [{"question": q, "answer": a, "evidence_class": "probe",
                "basis": f"eliminated by {len(rep.get('probes', []))} probe session(s)"}
               for q, a in rep.get("inferred", {}).items()]
    at = rep.get("atomic")
    if isinstance(at, dict):
        answers.append({"question": "atomic", "answer": at.get("verdict"), "evidence_class": "probe",
                        "basis": at.get("statement", "")})
    for q in rep.get("no_claim", []):
        answers.append({"question": q, "answer": None, "evidence_class": "not exercised",
                        "basis": "the hunt makes no claim about it"})
    rec["profile"] = {"answers": answers, "remaining": rep.get("remaining", [])}
    tests = rep.get("tests", {})

    def tv(*names):
        vs = [f"{n} {tests[n]['verdict']}" for n in names if n in tests]
        return ", ".join(vs) or "not exercised"
    rem = rep.get("remaining", [])
    rec["scorecard"] = [
        "identified: " + ", ".join(f"{q}: {a}" for q, a in rep.get("inferred", {}).items()),
        "predictive: not computed (a hunt report holds no held-out split; R6's card reads a row)",
        "sound: " + tv("parallel", "ambiguous"),
        "tight: " + tv("over-ask", "freeze"),
        f"residual: {len(rem)} profile(s) remain" + ("" if rem else " (no profile explains every session)"),
    ]
    rec["findings"] = [{"property": f.get("property"), "session": f.get("session")} for f in rep.get("findings", [])]
    return rec


def check_record(verdict: dict, *, engine: dict, policy_text: str | None, lines: list[str],
                 exit_code: int) -> dict:
    """The record of one `kamanu check`: the profile it checked (each answer with its
    provenance's evidence class), the policy and the verdict lines. A check sends no probe."""
    name = str(verdict.get("engine") or engine.get("name") or "unknown")
    default_version = kamanu_version() if name == "reference" else "profile record"
    eng = {"name": name, "version": str(engine.get("version") or default_version),
           "third_party": name != "reference"}
    rec = base("check", eng, live=False, policy_text=policy_text)
    prof = {}
    for v in verdict.get("verdicts", []):
        prof = v.get("profile") or {}
        if prof:
            break
    rec["profile"] = {"answers": [{"question": q, "answer": a.get("value") if isinstance(a, dict) else a,
                                   "evidence_class": evidence_class(a.get("provenance") if isinstance(a, dict) else None),
                                   "basis": str(a.get("provenance") if isinstance(a, dict) else "")}
                                  for q, a in prof.items()]}
    rec["scorecard"] = list(lines)
    rec["check"] = {"cap": verdict.get("cap"), "quick": verdict.get("quick"), "exit": exit_code}
    return rec


def fix_record(report: dict, *, row: dict | None = None, exit_code: int | None = None) -> dict:
    """The record of one `kamanu fix`, from its report (R7's fix_row) alone; the row (engine,
    policy, profile) and the exit code are optional context.

    "fix" follows R10: {"proposed": [entry["repair"] for each entry of the report's "tried", in
    order] ([] when the report has no "tried", as a refused row's report does), "accepted": the
    report's "repair" (null when it is null), "judged": R7's status, "place", "exit"}. The record
    is local (no "license") and its command is "fix"."""
    row = row if isinstance(row, dict) else {}
    e = row.get("engine") if isinstance(row.get("engine"), dict) else {"name": str(row.get("engine") or "unknown")}
    name = str(e.get("name") or "unknown")
    eng = {"name": name, "version": str(e.get("version") or "unknown"), "third_party": name != "reference"}
    pol = row.get("policy")
    text = pol.get("text") if isinstance(pol, dict) else (pol if isinstance(pol, str) else None)
    rec = base("fix", eng, live=False, policy_text=text)
    prof = row.get("profile") if isinstance(row.get("profile"), dict) else {}
    rec["profile"] = {"answers": [{"question": q, "answer": a, "evidence_class": "probe",
                                   "basis": "the hunt row's inferred profile"} for q, a in prof.items()]}
    rec["scorecard"] = [str(report.get("text", ""))]
    tried = report.get("tried") if isinstance(report.get("tried"), list) else []
    rec["fix"] = {"proposed": [copy.deepcopy(t.get("repair")) for t in tried if isinstance(t, dict)],
                  "accepted": copy.deepcopy(report.get("repair")), "judged": report.get("status"),
                  "place": report.get("place"), "exit": exit_code}
    return rec
