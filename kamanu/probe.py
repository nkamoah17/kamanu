"""Probe designer: TLC designs the shortest experiment that tells two engine profiles apart.

    design(profile_a, profile_b, probe_policy, max_len) -> dict or None

It generates a KamanuProbe instance and runs TLC on it. The two profiles take the same probe
in lockstep and the invariant Agree says they decide alike, so a counterexample is a probe
that separates them. One worker keeps TLC strictly breadth-first, which makes that
counterexample a shortest one.

profile_a, b    {"reflexive": bool, "denyRecord": bool, "scope": "session" | "global"}.
                Nothing else is accepted. KamanuProbe cannot spell the kernel's
                DenyRecord = "error" or Scope = "ScopeGlobal", and letting them through
                would answer for a different profile.
probe_policy    a TLA+ Boolean expression over v (the view) and r (the request), with what
                MCProbe defines in scope: "AtMostOne(v, r)", "Lockout(v, r)", CountKind.
max_len         the longest probe to consider.

Returns {"probe": steps, "decisions_a": bools, "decisions_b": bools}, or None when TLC
searched every probe up to max_len and none separates the pair. None is that claim and
nothing weaker: a run that does not conclude raises, whatever stopped it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from kamanu.verdict import read_result, read_trace

ROOT = Path(__file__).resolve().parent.parent
SPECS = ("KamanuProbe.tla", "MCProbe.tla")
MODULE = "ProbeInstance"
AMT = 60
SESSIONS = ("s1", "s2")
SCOPES = ("session", "global")
PROFILE_FLAGS = ("reflexive", "denyRecord")
TIMEOUT = 900


def _check_profile(name: str, profile) -> None:
    if not isinstance(profile, dict) or set(profile) != {*PROFILE_FLAGS, "scope"}:
        raise ValueError(f"{name} needs exactly reflexive, denyRecord, scope: {profile!r}")
    for flag in PROFILE_FLAGS:
        if not isinstance(profile[flag], bool):
            raise ValueError(f"{name}.{flag} must be a bool: {profile[flag]!r}")
    if profile["scope"] not in SCOPES:
        raise ValueError(f"{name}.scope must be one of {SCOPES}: {profile['scope']!r}")


def _check_args(profile_a, profile_b, probe_policy, max_len) -> None:
    _check_profile("profile_a", profile_a)
    _check_profile("profile_b", profile_b)
    if not isinstance(probe_policy, str) or not probe_policy.strip():
        raise ValueError(f"probe_policy must be a TLA+ expression: {probe_policy!r}")
    if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len < 0:
        raise ValueError(f"max_len must be an int >= 0: {max_len!r}")


def _tla_profile(profile: dict) -> str:
    flags = ", ".join("TRUE" if profile[f] else "FALSE" for f in PROFILE_FLAGS)
    return f'P({flags}, "{profile["scope"]}")'


def instance(profile_a: dict, profile_b: dict, probe_policy: str) -> str:
    """The module TLC checks. The policy comes last, where a stray end of module costs nothing."""
    return (f"---- MODULE {MODULE} ----\nEXTENDS MCProbe\n"
            f"InstanceA == {_tla_profile(profile_a)}\n"
            f"InstanceB == {_tla_profile(profile_b)}\n"
            f"InstancePermit(v, r) == {probe_policy}\n====\n")


def config(max_len: int) -> str:
    sessions = ", ".join(f'"{s}"' for s in SESSIONS)
    return ("SPECIFICATION Spec\nCONSTANTS\n"
            f"  L = {max_len}\n  Amt = {AMT}\n  Sessions = {{{sessions}}}\n"
            "  ProfA <- InstanceA\n  ProfB <- InstanceB\n  Permit <- InstancePermit\n"
            "INVARIANT Agree\nCHECK_DEADLOCK FALSE\n")


def jar_path() -> Path:
    env = os.environ.get("KAMANU_TLA_JAR")
    jar = Path(env) if env else ROOT / "tools" / "vendor" / "tla2tools.jar"
    if not jar.is_file():
        raise RuntimeError(f"TLC jar not found at {jar}: set KAMANU_TLA_JAR")
    return jar


def run_tlc(module_text: str, cfg: str) -> subprocess.CompletedProcess:
    """One TLC run in a directory of its own, TEMP included: TLC unpacks the standard modules
    into TEMP, and concurrent runs would otherwise collide there."""
    jar = jar_path()
    with tempfile.TemporaryDirectory(prefix="kamanu-probe-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        for name in SPECS:
            shutil.copy(ROOT / "spec" / name, work / name)
        (work / f"{MODULE}.tla").write_text(module_text, encoding="utf-8")
        (work / "MC.cfg").write_text(cfg, encoding="ascii")
        env = {**os.environ, "TEMP": tmp, "TMP": tmp}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={tmp}", "-cp", str(jar),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(work / "meta"),
               "-config", "MC.cfg", MODULE]
        return subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT)


def read_design(output: str, returncode: int, max_len: int) -> dict | None:
    """The answer in what TLC printed. Anything but a finished search or a real separation
    raises: read_result refuses output with no conclusion, and the rest is checked here."""
    try:
        result, _ = read_result(output)
    except ValueError as err:
        raise RuntimeError(f"TLC run proved nothing: {err}\n{output[-1500:]}") from err
    if result["status"] == "PASS":
        if returncode != 0 or result["distinct_states"] < 1:
            raise RuntimeError(f"TLC run proved nothing (exit {returncode}, "
                               f"{result['distinct_states']} states)\n{output[-1500:]}")
        return None
    if (result["status"], result["violated"]) != ("INVARIANT", "Agree"):
        raise RuntimeError(f"not a separating trace: {result}\n{output[-1500:]}")
    last = read_trace(output.replace("\r\n", "\n"))["steps"][-1]["state"]
    probe, da, db = last["probe"], last["da"], last["db"]
    if da == db or not 1 <= len(probe) <= max_len:
        raise RuntimeError(f"not a separating trace within {max_len}: {last}")
    return {"probe": probe, "decisions_a": da, "decisions_b": db}


def design(profile_a, profile_b, probe_policy, max_len):
    _check_args(profile_a, profile_b, probe_policy, max_len)
    done = run_tlc(instance(profile_a, profile_b, probe_policy), config(max_len))
    return read_design(done.stdout + done.stderr, done.returncode, max_len)
