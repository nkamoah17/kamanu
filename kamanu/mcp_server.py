"""Product 1's agent-facing surface: a stateless MCP server (protocol 2026-07-28).

    handle(request) -> response   one JSON-RPC 2.0 request object in, its response object
                                  out; None for a notification (a request without "id").
    main()                        a stdio loop around handle: one JSON message per line on
                                  stdin, one response per line on stdout.
    serve()                       the installed `kamanu-mcp` command: main() around
                                  handle_with_hunt, which is handle plus a fifth tool, hunt
                                  (`kamanu hunt <options> --json`'s report, H13).

The server adds no semantics of its own. Every tool result is a fixed function of a
reference that is already checked elsewhere:

    "the run" of (policy, path, engine, cap)
        python -m kamanu.cli check <path> --engine <reference | record file> --cap <cap>
        --out <dir>, in a fresh working directory holding the policy text at <path> and the
        profile record (when engine is not "reference") in a file.
    kamanu.intent.questions.questions(config, check, candidates)   (I4)

Tools:
    verify_policy(policy, engine, cap?, path?)   {"exit", "verdict": verdict.json, "sarif"}
    diff_engines(policy, engine_a, engine_b, cap?, path?)
        {"exit_a", "exit_b", "differ": [{"rung", "check", "a": record, "b": record}]}, one
        entry per (rung, check) present in both runs whose result.status differs, in
        engine_a's order. Whole verdict records, never a bare status word.
    explain(policy, engine, rung, check, cap?, path?)
        {"exit", "record": the run's whole verdict record for (rung, check), or null}
    questions(config, check, candidates)        {"questions": I4's result}

Protocol. No initialize handshake and no session: handle keeps no state between calls, so
a result never depends on earlier requests. Every request carries
params._meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28", else -32022.
Unknown method -32601; unknown tool or arguments outside the inputSchema -32602. A run
that exits 3 (kamanu check could not judge the input) is a result with "isError": true and
a text message, never a partial result.

Wire encoding: everything is JSON; a set is a list sorted by json.dumps(x, sort_keys=True).
Set-valued config keys (Faults) arrive as lists and are read as sets.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

VERSION = "2026-07-28"
META_KEY = "io.modelcontextprotocol/protocolVersion"
PACKAGE_PARENT = Path(__file__).resolve().parents[1]
RUNGS = ["R0", "R1", "R2"]
CHECKS = ["safety", "deadlock", "liveness"]
SET_KEYS = {"Faults"}
DEFAULT_CAP = 100
DEFAULT_PATH = "policy.dw"
RUN_TIMEOUT = 900          # seconds; a run normally takes 5 to 20 s
TLC_DIED = "TLC output has no conclusion"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
UNSUPPORTED_VERSION = -32022


# ---------------------------------------------------------------- tool definitions
_ENGINE = {"description": '"reference", or a profile record as in profiles/ ({"id", "constants", ...})',
           "anyOf": [{"type": "string", "enum": ["reference"]},
                     {"type": "object", "required": ["constants"],
                      "properties": {"id": {"type": "string"}, "constants": {"type": "object"}}}]}
_POLICY = {"type": "string", "description": "the text of a Dogwood .dw file"}
_CAP = {"type": "integer", "minimum": 0, "default": DEFAULT_CAP,
        "description": "the spending cap the run checks against (kamanu check --cap)"}
_PATH = {"type": "string", "minLength": 1, "default": DEFAULT_PATH,
         "description": "the relative path the policy text is reported under"}
_RECORD = {"type": "object", "required": ["rung", "check", "result"],
           "description": "one whole verdict record of verdict.json: result, trace, bounds, "
                          "rests_on_default, class and unmodelled",
           "properties": {"rung": {"type": "string", "enum": RUNGS},
                          "check": {"type": "string", "enum": CHECKS},
                          "result": {"type": "object", "required": ["status"]}}}
_EXIT = {"type": "integer", "enum": [0, 1, 2],
         "description": "kamanu check's exit code: 0 all pass, 1 some check fails, 2 lossy policy"}
_CHECK = {"type": "string", "enum": CHECKS}

TOOLS = [
    {"name": "verify_policy",
     "title": "Verify a Dogwood policy",
     "description": "Run `kamanu check` on a Dogwood policy under one engine (\"reference\" or a "
                    "profile record) and return its exit code, its verdict.json and its SARIF log. "
                    "Every verdict comes with its ledger: bounds, rests on default, class.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["policy", "engine"],
                     "properties": {"policy": _POLICY, "engine": _ENGINE, "cap": _CAP, "path": _PATH}},
     "outputSchema": {"type": "object", "required": ["exit", "verdict", "sarif"],
                      "properties": {"exit": _EXIT,
                                     "verdict": {"type": "object", "required": ["verdicts"],
                                                 "properties": {"verdicts": {"type": "array",
                                                                             "items": _RECORD}}},
                                     "sarif": {"type": "object"}}}},
    {"name": "diff_engines",
     "title": "Compare two engines on one policy",
     "description": "Run `kamanu check` on the same policy text under two engines and list every "
                    "(rung, check) whose status differs, with both whole verdict records: the "
                    "engine-profile mismatch finding. An empty list means the engines agree.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["policy", "engine_a", "engine_b"],
                     "properties": {"policy": _POLICY, "engine_a": _ENGINE, "engine_b": _ENGINE,
                                    "cap": _CAP, "path": _PATH}},
     "outputSchema": {"type": "object", "required": ["exit_a", "exit_b", "differ"],
                      "properties": {"exit_a": _EXIT, "exit_b": _EXIT,
                                     "differ": {"type": "array", "items": {
                                         "type": "object", "required": ["rung", "check", "a", "b"],
                                         "properties": {"rung": {"type": "string", "enum": RUNGS},
                                                        "check": _CHECK, "a": _RECORD, "b": _RECORD}}}}}},
    {"name": "explain",
     "title": "Explain one verdict",
     "description": "Run `kamanu check` and return the whole verdict record for one rung (R0, R1, "
                    "R2) and check (safety, deadlock, liveness): result, counterexample trace, "
                    "bounds, rests on default, class and unmodelled outcomes. null when the run "
                    "has no such record (a lossy policy).",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["policy", "engine", "rung", "check"],
                     "properties": {"policy": _POLICY, "engine": _ENGINE,
                                    "rung": {"type": "string", "enum": RUNGS}, "check": _CHECK,
                                    "cap": _CAP, "path": _PATH}},
     "outputSchema": {"type": "object", "required": ["exit", "record"],
                      "properties": {"exit": _EXIT, "record": {"anyOf": [{"type": "null"}, _RECORD]}}}},
    {"name": "questions",
     "title": "Questions that settle an ambiguity",
     "description": "Given a kernel config (README's Config contract), a check and exactly two "
                    "candidate substitutions, return the questions whose answers decide between "
                    "them, each with TLC's counterexample that separates the answers; [] when both "
                    "candidates get the same verdict. Sets are sent as sorted lists.",
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "required": ["config", "check", "candidates"],
                     "properties": {"config": {"type": "object"}, "check": _CHECK,
                                    "candidates": {"type": "array", "minItems": 2, "maxItems": 2,
                                                   "items": {"type": "object"}}}},
     "outputSchema": {"type": "object", "required": ["questions"],
                      "properties": {"questions": {"type": "array", "items": {"type": "object"}}}}},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class RunFailed(Exception):
    """kamanu check could not judge the input (exit 3): the tool answers isError."""


def encode(x):
    """The wire encoding: JSON, with a set as a list sorted by its elements' canonical text."""
    if isinstance(x, dict):
        return {(k if isinstance(k, str) else json.dumps(encode(k), sort_keys=True)): encode(v)
                for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [encode(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((encode(v) for v in x), key=lambda e: json.dumps(e, sort_keys=True))
    return x


# ---------------------------------------------------------------- arguments
def _bad(message: str):
    raise RpcError(INVALID_PARAMS, message)


def _only(args: dict, tool: str):
    allowed = TOOLS[TOOL_NAMES.index(tool)]["inputSchema"]["properties"]
    extra = sorted(set(args) - set(allowed))
    if extra:
        _bad(f"{tool}: unknown arguments {extra}")


def _engine(args: dict, key: str):
    if key not in args:
        _bad(f"missing argument {key}")
    v = args[key]
    if v == "reference" and isinstance(v, str):
        return v
    if isinstance(v, dict) and isinstance(v.get("constants"), dict) and isinstance(v.get("id", ""), str):
        return v
    _bad(f'{key} must be "reference" or a profile record with "constants"')


def _run_args(args: dict, tool: str, engines: list) -> tuple:
    _only(args, tool)
    if "policy" not in args:
        _bad("missing argument policy")
    if not isinstance(args["policy"], str):
        _bad("policy must be a string (the text of a .dw file)")
    engs = [_engine(args, k) for k in engines]
    cap = args.get("cap", DEFAULT_CAP)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
        _bad("cap must be an integer >= 0")
    path = args.get("path", DEFAULT_PATH)
    if not isinstance(path, str) or not path:
        _bad("path must be a non-empty string")
    if (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
            or PureWindowsPath(path).drive or ".." in PureWindowsPath(path).parts):
        _bad("path must be relative and stay inside the working directory")
    return args["policy"], path, engs, cap


# ---------------------------------------------------------------- the run
def _kill_tree(p: subprocess.Popen):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    p.kill()


def _run_once(policy: str, path: str, engine, cap: int) -> tuple:
    """(exit code, verdict.json or None, kamanu.sarif or None, stderr)."""
    d = Path(tempfile.mkdtemp(prefix="kamanu-mcp-"))
    try:
        work, tmp = d / "work", d / "tmp"
        tmp.mkdir(parents=True)
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(policy, encoding="utf-8")
        eng = "reference"
        if engine != "reference":
            (work / "engine-record.json").write_text(json.dumps(engine), encoding="utf-8")
            eng = "engine-record.json"
        pp = [str(PACKAGE_PARENT)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
        env = dict(os.environ, TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp), PYTHONIOENCODING="utf-8",
                   PYTHONPATH=os.pathsep.join(pp))
        p = subprocess.Popen([sys.executable, "-m", "kamanu.cli", "check", path, "--engine", eng,
                              "--cap", str(cap), "--out", "out"],
                             cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                             start_new_session=(os.name != "nt"))
        try:
            _, err = p.communicate(timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            p.communicate()
            raise
        out = work / "out"
        load = lambda f: json.loads(f.read_text(encoding="utf-8")) if f.exists() else None  # noqa: E731
        return p.returncode, load(out / "verdict.json"), load(out / "kamanu.sarif"), err
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run(policy: str, path: str, engine, cap: int) -> tuple:
    """The run: (exit, verdict, sarif). Raises RunFailed when kamanu check exits 3 (or
    otherwise gives no verdict). A run whose TLC died or hung is repeated once: the run is a
    function of its input, so a repeat changes nothing but the luck of the machine."""
    try:
        r = _run_once(policy, path, engine, cap)
    except subprocess.TimeoutExpired:
        try:
            r = _run_once(policy, path, engine, cap)
        except subprocess.TimeoutExpired:
            raise RunFailed(f"kamanu check did not finish in {RUN_TIMEOUT} s") from None
    else:
        if r[0] == 3 and TLC_DIED in r[3]:
            r = _run_once(policy, path, engine, cap)
    code, verdict, sarif, err = r
    if code not in (0, 1, 2) or verdict is None or sarif is None:
        msg = err.strip()[-2000:] or f"kamanu check exited {code} without a verdict"
        raise RunFailed(f"kamanu check exited {code}: {msg}")
    return code, verdict, sarif


# ---------------------------------------------------------------- tools
def verify_policy(args: dict) -> dict:
    policy, path, (engine,), cap = _run_args(args, "verify_policy", ["engine"])
    code, verdict, sarif = run(policy, path, engine, cap)
    return {"exit": code, "verdict": verdict, "sarif": sarif}


def diff_engines(args: dict) -> dict:
    policy, path, (ea, eb), cap = _run_args(args, "diff_engines", ["engine_a", "engine_b"])
    xa, va, _ = run(policy, path, ea, cap)
    xb, vb, _ = run(policy, path, eb, cap)
    other = {(v["rung"], v["check"]): v for v in vb["verdicts"]}
    differ = []
    for v in va["verdicts"]:
        w = other.get((v["rung"], v["check"]))
        if w is not None and w["result"]["status"] != v["result"]["status"]:
            differ.append({"rung": v["rung"], "check": v["check"], "a": v, "b": w})
    return {"exit_a": xa, "exit_b": xb, "differ": differ}


def explain(args: dict) -> dict:
    policy, path, (engine,), cap = _run_args(args, "explain", ["engine"])
    rung, check = args.get("rung"), args.get("check")
    if not (isinstance(rung, str) and rung in RUNGS):
        _bad(f"rung must be one of {RUNGS}")
    if not (isinstance(check, str) and check in CHECKS):
        _bad(f"check must be one of {CHECKS}")
    code, verdict, _ = run(policy, path, engine, cap)
    record = next((v for v in verdict["verdicts"] if v["rung"] == rung and v["check"] == check), None)
    return {"exit": code, "record": record}


def _decode(d: dict) -> dict:
    return {k: (set(map(_hashable, v)) if k in SET_KEYS and isinstance(v, list) else v) for k, v in d.items()}


def _hashable(x):
    if isinstance(x, list):
        _bad("a set element must be a scalar")
    if isinstance(x, dict):
        _bad("a set element must be a scalar")
    return x


def questions(args: dict) -> dict:
    _only(args, "questions")
    for k in ("config", "check", "candidates"):
        if k not in args:
            _bad(f"missing argument {k}")
    config, check, candidates = args["config"], args["check"], args["candidates"]
    if not isinstance(config, dict):
        _bad("config must be an object (README's Config contract)")
    if not (isinstance(check, str) and check in CHECKS):
        _bad(f"check must be one of {CHECKS}")
    if not (isinstance(candidates, list) and len(candidates) == 2 and all(isinstance(c, dict) for c in candidates)):
        _bad("candidates must be exactly two substitution objects")
    from kamanu.intent.questions import questions as i4_questions
    cfg = _decode(copy.deepcopy(config))
    cands = [_decode(copy.deepcopy(c)) for c in candidates]
    try:
        result = i4_questions(cfg, check, cands)
    except (ValueError, KeyError, TypeError) as exc:
        _bad(f"questions: {exc}")
    return {"questions": encode(result)}


_IMPL = {"verify_policy": verify_policy, "diff_engines": diff_engines, "explain": explain,
         "questions": questions}


# ---------------------------------------------------------------- protocol
def _tools_call(params: dict) -> dict:
    name = params.get("name")
    if not (isinstance(name, str) and name in _IMPL):
        _bad(f"unknown tool {name!r}; the tools are {TOOL_NAMES}")
    args = params.get("arguments", {})
    if not isinstance(args, dict):
        _bad("arguments must be an object")
    try:
        r = encode(_IMPL[name](args))
    except RunFailed as exc:
        return {"resultType": "complete", "isError": True,
                "content": [{"type": "text", "text": str(exc)}]}
    return {"resultType": "complete", "structuredContent": r,
            "content": [{"type": "text", "text": json.dumps(r, sort_keys=True)}], "isError": False}


def _discover() -> dict:
    return {"supportedVersions": [VERSION], "protocolVersion": VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "kamanu", "title": "KAMANU policy verifier", "version": "0.1.1"},
            "instructions": "Stateless: no initialize, no session. Send params._meta"
                            f"[\"{META_KEY}\"] = \"{VERSION}\" on every request."}


def _tools_list() -> dict:
    return {"tools": copy.deepcopy(TOOLS), "ttlMs": 3_600_000, "cacheScope": "public"}


METHODS = {"server/discover": lambda params: _discover(),
           "tools/list": lambda params: _tools_list(),
           "tools/call": _tools_call}


def _result(method, params):
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise RpcError(INVALID_PARAMS, "params must be an object")
    meta = params.get("_meta")
    version = meta.get(META_KEY) if isinstance(meta, dict) else None
    if not (isinstance(version, str) and version == VERSION):
        raise RpcError(UNSUPPORTED_VERSION,
                       f"unsupported protocol version {version!r}: this server speaks {VERSION} "
                       f"(set params._meta[\"{META_KEY}\"])")
    if method not in METHODS:
        raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")
    return METHODS[method](params)


def handle(request):
    """One JSON-RPC 2.0 request object -> its response object (None for a notification)."""
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "invalid request"}}
    notification = "id" not in request
    rid = request.get("id")
    method = request.get("method")
    try:
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            raise RpcError(INVALID_REQUEST, "invalid request: want jsonrpc \"2.0\" and a method")
        result = _result(method, request.get("params"))
    except RpcError as e:
        response = {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}
    except Exception as exc:  # noqa: BLE001 - a server error is an answer, not a crash
        response = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": f"internal error: {type(exc).__name__}: {exc}"}}
    else:
        response = {"jsonrpc": "2.0", "id": rid, "result": result}
    return None if notification else response


def main():
    out = sys.stdout
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "parse error"}}
        else:
            resp = handle(req)
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


# ---------------------------------------------------------------- the kamanu-mcp entry point (H13)
# handle() above stays P1b's four tools. The installed `kamanu-mcp` command serves those four
# plus hunt, whose result is `kamanu hunt <options> --json` run by this same package.
HUNT_OPTIONS = ["example", "adapter", "policy", "policy_schema", "scope", "seed"]
HUNT_TIMEOUT = 1800
HUNT_TOOL = {
    "name": "hunt",
    "title": "Hunt an engine's stateful semantics",
    "description": "Runs `kamanu hunt <options> --json` and returns its report. Each argument is a "
                   "`kamanu hunt` long option with dashes written as underscores, its value the string "
                   "the option takes: example (a shipped example, e.g. \"dogwood\"), adapter "
                   "(\"reference\" or \"dogwood\"; dogwood runs DOGWOOD_BIN), policy and policy_schema "
                   "(file paths, relative to the server's working directory), scope (the path of the "
                   "scope file that names the target the hunt may reach, its owner, its ceilings and its "
                   "expiry: every adapter but reference needs one, and without one that covers the target "
                   "nothing is sent), seed (an integer, as a string, written into the report). A run the "
                   "CLI refuses is a result with isError true and the CLI's message.",
    "inputSchema": {"type": "object", "additionalProperties": False,
                    "properties": {k: {"type": "string", "minLength": 1} for k in HUNT_OPTIONS}},
    "outputSchema": {"type": "object",
                     "required": ["policy", "inferred", "remaining", "probes", "sessions", "findings",
                                  "unconfirmed", "no_claim", "adapter"],
                     "properties": {"policy": {"type": "object"}, "inferred": {"type": "object"},
                                    "remaining": {"type": "array"}, "probes": {"type": "array"},
                                    "sessions": {"type": "array"}, "findings": {"type": "array"},
                                    "unconfirmed": {"type": "array"}, "no_claim": {"type": "array"},
                                    "adapter": {"type": "string"}, "example": {"type": "string"}}},
}


def hunt_argv(args: dict) -> list:
    """The hunt tool's arguments as `kamanu hunt` options (after -32602 checks)."""
    extra = sorted(set(args) - set(HUNT_OPTIONS))
    if extra:
        _bad(f"hunt: unknown arguments {extra}; the options are {HUNT_OPTIONS}")
    argv = []
    for k, v in args.items():
        if not isinstance(v, str) or not v:
            _bad(f"hunt: {k} must be a non-empty string")
        argv += ["--" + k.replace("_", "-"), v]
    return argv


def hunt(args: dict) -> dict:
    """`kamanu hunt <options> --json` in a child process of this interpreter (the same package,
    working directory and environment); its report, or RunFailed with its message."""
    cmd = [sys.executable, "-m", "kamanu.hunt.cli", "hunt", *hunt_argv(args), "--json"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=HUNT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RunFailed(f"kamanu hunt did not finish in {HUNT_TIMEOUT} s")
    try:
        rep = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        rep = None
    if not isinstance(rep, dict):
        msg = (p.stderr.strip() or p.stdout.strip() or "no output")[-2000:]
        raise RunFailed(f"kamanu hunt exits {p.returncode}: {msg}")
    return rep


def _tools_list_with_hunt() -> dict:
    r = _tools_list()
    r["tools"].append(copy.deepcopy(HUNT_TOOL))
    return r


def _hunt_call(params: dict) -> dict:
    args = params.get("arguments", {})
    if not isinstance(args, dict):
        _bad("arguments must be an object")
    try:
        r = hunt(args)
    except RunFailed as exc:
        return {"resultType": "complete", "isError": True, "content": [{"type": "text", "text": str(exc)}]}
    return {"resultType": "complete", "structuredContent": r,
            "content": [{"type": "text", "text": json.dumps(r, sort_keys=True)}], "isError": False}


def handle_with_hunt(request):
    """handle(), with hunt added to tools/list and tools/call: the kamanu-mcp command's server."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return handle(request)
    method, params = request.get("method"), request.get("params")
    if method == "tools/list" or (method == "tools/call" and isinstance(params, dict)
                                  and params.get("name") == "hunt"):
        notification = "id" not in request
        rid = request.get("id")
        try:
            _result("server/discover", params)          # the protocol checks (version, params)
            result = _tools_list_with_hunt() if method == "tools/list" else _hunt_call(params)
        except RpcError as e:
            response = {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}
        except Exception as exc:  # noqa: BLE001
            response = {"jsonrpc": "2.0", "id": rid,
                        "error": {"code": -32603, "message": f"internal error: {type(exc).__name__}: {exc}"}}
        else:
            response = {"jsonrpc": "2.0", "id": rid, "result": result}
        return None if notification else response
    return handle(request)


def serve():
    """The `kamanu-mcp` console entry point: the stdio loop around handle_with_hunt."""
    out = sys.stdout
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "parse error"}}
        else:
            resp = handle_with_hunt(req)
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
