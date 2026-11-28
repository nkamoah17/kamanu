"""Rule L5 made total: each feature module reduces to the kernel with its feature off.

A reduction (one object in spec/ladder/ATTACHED.yaml) names a feature's spec, the module it
reduces to, and the constants that switch the feature off. Its files are

    spec/ladder/reduce/NDown.tla    EXTENDS the feature's module; T == INSTANCE <target>
    spec/ladder/reduce/NUp.tla      EXTENDS the target's module;  F == INSTANCE <feature>
    spec/ladder/reduce/N.constants  TLC CONSTANTS lines, shared by both directions

and check() runs TLC once per direction, a refinement each way:

    down   SPECIFICATION  the feature's Init /\\ [][Next]_vars        (in NDown, + history)
           PROPERTY       T!(the target's Init /\\ [][Next]_vars)
    up     SPECIFICATION  the target's Init /\\ [][Next]_vars         (in NUp, + history)
           PROPERTY       F!(the feature's Init /\\ [][Next]_vars)

Both formulas are built here from the spec operators of the modules themselves, with their
fairness conjuncts dropped (the safety part: the behaviours Init and Next allow). The
instance maps every variable the two share to itself, so a direction that holds says that
every behaviour of one side, projected on the shared variables, is a behaviour of the other.
A direction that FAILS returns TLC's counterexample. Verdicts of the two sides on some
invariant are never compared.

    python -m kamanu.ladder.reduce [--threads N] [--only NAME ...]

runs every reduction in spec/ladder/ATTACHED.yaml at its committed constants and writes
evidence/ladder/r3/reductions.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "ladder" / "r3"
STANDARD = {"Naturals", "Integers", "Sequences", "FiniteSets", "TLC", "Bags", "Reals"}


# ---------------------------------------------------------------- TLA+ text
def _uncomment(text: str) -> str:
    text = re.sub(r"\(\*.*?\*\)", " ", text, flags=re.S)
    return re.sub(r"\\\*[^\n]*", " ", text)


def _body(text: str) -> str:
    t = _uncomment(text)
    head = re.search(r"^-{4,}\s*MODULE\s+\w+\s*-{4,}\s*$", t, flags=re.M)
    if head:
        t = t[head.end():]
    end = re.search(r"^={4,}", t, flags=re.M)
    return t[:end.start()] if end else t


def _extends(text: str) -> list[str]:
    m = re.search(r"^\s*EXTENDS\s+([\w\s,]+?)\s*$", _body(text), flags=re.M)
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


_DEF = re.compile(r"^(?:LOCAL\s+)?(\w+)\s*(?:\([^)]*\))?\s*==", re.M)
_NEXT_UNIT = re.compile(r"^(?:\w+\s*(?:\([^)]*\))?\s*==|LOCAL\b|VARIABLES?\b|CONSTANTS?\b|ASSUME\b|"
                        r"RECURSIVE\b|INSTANCE\b|EXTENDS\b|THEOREM\b|={4,})", re.M)


def _definitions(text: str) -> dict[str, str]:
    """Column-0 definitions of one module: name -> body."""
    b = _body(text)
    out: dict[str, str] = {}
    for m in _DEF.finditer(b):
        rest = b[m.end():]
        stop = _NEXT_UNIT.search(rest)
        out.setdefault(m.group(1), rest[:stop.start()] if stop else rest)
    return out


def _declared(text: str, keyword: str) -> list[str]:
    b = _body(text)
    out: list[str] = []
    pat = (rf"^\s*{keyword}S?\b(.*?)(?=^\s*\w+\s*(\([^)]*\))?\s*==|"
           rf"^\s*(VARIABLES?|CONSTANTS?|ASSUME|LOCAL|INSTANCE|RECURSIVE|EXTENDS)\b|\Z)")
    for m in re.finditer(pat, b, flags=re.S | re.M):
        out += [re.sub(r"\s+", "", x) for x in re.findall(r"[A-Za-z_]\w*(?:\s*\([_,\s]*\))?", m.group(1))]
    return out


def _index(base: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted(base.rglob("*.tla")):
        if p.stem in out:
            raise ValueError(f"two modules named {p.stem} under {base}")
        out[p.stem] = p
    return out


def _closure(stem: str, index: dict[str, Path]) -> list[str]:
    seen: list[str] = []

    def go(s: str) -> None:
        if s in seen or s not in index:
            return
        seen.append(s)
        for e in _extends(index[s].read_text(encoding="utf-8")):
            go(e)
    go(stem)
    return seen


_SPEC = re.compile(r"^(?P<init>.*?)/\\\s*\[\]\s*\[(?P<next>.*?)\]_(?P<vars><<[^>]*>>|\w+)(?P<rest>.*)$", re.S)


def safety_part(stem: str, op: str, index: dict[str, Path]) -> dict:
    """Spec operator `op` of module `stem` (or a module it extends), as Init, Next and vars."""
    for s in _closure(stem, index):
        body = _definitions(index[s].read_text(encoding="utf-8")).get(op)
        if body is None:
            continue
        m = _SPEC.match(" ".join(body.split()))
        if not m:
            raise ValueError(f"{s}.{op} is not Init /\\ [][Next]_vars (/\\ fairness)")
        init = re.sub(r"^\s*/\\\s*", "", m.group("init").strip())
        return {"init": init, "next": m.group("next").strip(), "vars": m.group("vars").strip()}
    raise ValueError(f"no definition of {op} in {stem} or the modules it extends")


def read_constants(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\\\*.*$", "", raw).strip()
        if not line or line.upper() in ("CONSTANT", "CONSTANTS"):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s*(=|<-)\s*(.+)$", line)
        if not m:
            raise ValueError(f"{path.name}: not a constants line: {raw!r}")
        out[m.group(1)] = f"{m.group(2)} {m.group(3).strip()}"
    return out


def _history(text: str) -> list[str]:
    """History variables a Down/Up module declares (each set by HInit and HNext)."""
    hv = _declared(text, "VARIABLE")
    if hv:
        d = _definitions(text)
        missing = [x for x in ("HInit", "HNext") if x not in d]
        if missing:
            raise ValueError(f"history variables {hv} without {missing}")
    return hv


# ---------------------------------------------------------------- the harness
def _wrap(stem: str, side: dict) -> str:
    return (f"---- MODULE RSafe{stem} ----\nEXTENDS {stem}\n"
            f"RSafe == {side['init']} /\\ [][{side['next']}]_{side['vars']}\n====\n")


def _point(text: str, inst: str, target: str) -> str:
    pat = re.compile(rf"(^{inst}\s*==\s*INSTANCE\s+){target}\b", re.M)
    if not pat.search(text):
        raise ValueError(f"no `{inst} == INSTANCE {target}` at column 0")
    return pat.sub(rf"\g<1>RSafe{target}", text, count=1)


def direction_modules(red: dict, base: Path, direction: str) -> tuple[dict[str, str], str]:
    """The modules of one direction: (name -> text, the main module's name)."""
    index = _index(base)
    name = red["name"]
    feat_mod, targ_mod = Path(red["spec_module"]).stem, Path(red["target"]).stem
    feat = safety_part(feat_mod, red["spec"], index)
    targ = safety_part(targ_mod, red["target_spec"], index)
    rdir = base / "ladder" / "reduce"
    if direction == "down":
        mod, inst, other, spec, ref = f"{name}Down", "T", targ_mod, feat, targ
    else:
        mod, inst, other, spec, ref = f"{name}Up", "F", feat_mod, targ, feat
    text = (rdir / f"{mod}.tla").read_text(encoding="utf-8")
    hv = _history(text)
    if hv:
        hvars = "<<" + ", ".join(hv) + ">>"
        rspec = (f"RSpec == ({spec['init']}) /\\ HInit /\\ "
                 f"[][({spec['next']}) /\\ HNext]_<<{spec['vars']}, {hvars}>>")
    else:
        rspec = f"RSpec == {spec['init']} /\\ [][{spec['next']}]_{spec['vars']}"
    main = f"R{direction.capitalize()}{name}"
    files = {mod: _point(text, inst, other), f"RSafe{other}": _wrap(other, ref),
             main: f"---- MODULE {main} ----\nEXTENDS {mod}, TLC\n{rspec}\nRRef == {inst}!RSafe\n====\n"}
    return files, main


def jar_path() -> Path:
    from kamanu import tlajar
    return tlajar.path(ROOT)


def _cfg(consts: dict[str, str]) -> str:
    lines = ["SPECIFICATION RSpec", "PROPERTY RRef", "CONSTANTS"]
    lines += [f"  {k} {v}" for k, v in consts.items()]
    return "\n".join(lines + ["CHECK_DEADLOCK FALSE"]) + "\n"


def run_tlc(base: Path, files: dict[str, str], main: str, cfg: str, workdir: Path | None,
            timeout: int = 3600) -> dict:
    parent = Path(workdir) if workdir else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="reduce-", dir=parent))
    try:
        for p in base.rglob("*.tla"):
            shutil.copy(p, d / p.name)
        for n, t in files.items():
            (d / f"{n}.tla").write_text(t, encoding="utf-8")
        (d / "MC.cfg").write_text(cfg, encoding="utf-8")
        env = {**os.environ, "TEMP": str(d), "TMP": str(d)}
        cmd = ["java", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={d}", "-cp", str(jar_path()),
               "tlc2.TLC", "-workers", "1", "-nowarning", "-metadir", str(d / "meta"),
               "-config", "MC.cfg", main]
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", env=env)
        out = p.stdout + p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)
    found = re.findall(r"([\d,]+) distinct states found", out)
    states = int(found[-1].replace(",", "")) if found else 0
    if "Model checking completed. No error has been found" in out:
        return {"v": "holds", "states": states, "out": out}
    if re.search(r"^Error: .*(Invariant|Action property|Property|Temporal propert(y|ies)) .*(is|was|were) violated",
                 out, flags=re.M) and "State 1" in out:
        return {"v": "FAILS", "states": states, "out": out}
    raise RuntimeError(f"TLC reached no verdict on {main}:\n{out[-3000:]}")


def check(reduction, spec_root=None, workdir=None, overrides=None) -> dict:
    """Both directions of one reduction, by TLC. See the module docstring."""
    base = Path(spec_root) if spec_root else ROOT / "spec"
    red = dict(reduction)
    consts = read_constants(base / "ladder" / "reduce" / f"{red['name']}.constants")
    consts.update(overrides or {})
    wd = Path(workdir) if workdir else None
    runs = {}
    for direction in ("down", "up"):
        files, main = direction_modules(red, base, direction)
        runs[direction] = run_tlc(base, files, main, _cfg(consts), wd)
    return {"down": runs["down"]["v"], "up": runs["up"]["v"],
            "states": {d: runs[d]["states"] for d in runs},
            "trace": {d: (runs[d]["out"] if runs[d]["v"] == "FAILS" else None) for d in runs}}


# ---------------------------------------------------------------- the full run
def reductions(attached: Path | None = None) -> dict[str, tuple[dict, list[str]]]:
    """name -> (reduction object, the module paths whose entries use it)."""
    import yaml
    doc = yaml.safe_load((attached or ROOT / "spec" / "ladder" / "ATTACHED.yaml").read_text(encoding="utf-8"))
    out: dict[str, tuple[dict, list[str]]] = {}
    for e in doc["modules"]:
        r = e.get("reduction")
        reds = [r] if isinstance(r, dict) else [x for x in r if isinstance(x, dict)] if isinstance(r, list) else []
        for x in reds:
            if x["name"] in out:
                if out[x["name"]][0] != x:
                    raise ValueError(f"two different reductions are named {x['name']}")
                out[x["name"]][1].append(e["module"])
            else:
                out[x["name"]] = (x, [e["module"]])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--only", nargs="*", help="run these reductions only (no evidence written)")
    a = ap.parse_args(argv)
    reds = reductions()
    names = sorted(a.only) if a.only else sorted(reds)

    def one(n):
        wd = Path(tempfile.mkdtemp(prefix="kamanu-reduce-"))
        try:
            return n, check(reds[n][0], None, wd), None
        except Exception as e:  # noqa: BLE001 - reported per reduction
            return n, None, str(e)
        finally:
            shutil.rmtree(wd, ignore_errors=True)
    rows, bad = [], 0
    with ThreadPoolExecutor(max(1, a.threads)) as ex:
        for n, got, err in ex.map(one, names):
            if err:
                bad += 1
                print(f"{n}: ERROR {err[-1500:]}", flush=True)
                continue
            print(f"{n}: down {got['down']} ({got['states']['down']}), up {got['up']} ({got['states']['up']})",
                  flush=True)
            for d in ("down", "up"):
                if got[d] == "FAILS":
                    bad += 1
                    print(got["trace"][d][-2500:])
            rows.append({"name": n, "modules": reds[n][1], "down": got["down"], "up": got["up"],
                         "states": got["states"]})
    if not a.only:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "reductions.json").write_text(json.dumps({"reductions": rows}, indent=2) + "\n",
                                                   encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
