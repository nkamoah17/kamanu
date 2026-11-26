"""R14e: what changed between the calibration table R11b published and the republished one.

    python evidence/ladder/r14e/make.py      writes evidence/ladder/r14e/changed.json

The old table is read from git (OLD_REV, R11b's commit, before R14c and R14d); the new one is the
committed evidence/ladder/r6b/calibration.json. Reported classes are read with each table's own
classes (kamanu.ladder.calibrate.class_index / reported_class). Nothing here runs the judge.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from kamanu.ladder import calibrate as C  # noqa: E402
from kamanu.ladder import scorecard as SC  # noqa: E402

OLD_REV = "40b0bb5"
TABLE = "evidence/ladder/r6b/calibration.json"
OUT = ROOT / "evidence" / "ladder" / "r14e" / "changed.json"

# One sentence per kind of difference: which change of R14c or R14d explains it.
WHY = {
    "planted": (
        "R14c changed what the hunt sends before the judge's probes (lag probed first, with a filler event "
        "between a refusal and the decision that reads it, then a consistency replay and a conformance suite "
        "to depth 4), so a planted trial runs more and other sessions and fewer profiles explain them all: "
        "every planted difference is the same reported class with fewer profiles in it (no trial changed "
        "class, all 96 stay right); R14d only meters the same sessions (a bundled simulated engine is "
        "admitted without a scope), so it changes none."),
    "stranger": (
        "R14c's hunt sends other sessions to a stranger (lag first, the conformance suite), and a stranger's "
        "residual is the number of sessions no best-fitting profile explains, so it moves with what was sent "
        "(every stranger still has a residual and no reported profile); R14d's ceilings are never reached by "
        "a bundled engine and change nothing here."),
    "noise": (
        "Under noise R14c's hunt sends other sessions (lag first, the conformance suite), so the dropped or "
        "delayed responses land on other calls and the reported profiles and residual move both ways, and "
        "R14c also changed how the hunt reaches its atomic claim (its own race trials, none when no window "
        "fits, a row that names no profile carries none), so not_refuted ['atomic'] appears or goes even at "
        "p=0; R14d meters the same sessions and changes none."),
}


def load_old() -> dict:
    out = subprocess.run(["git", "show", f"{OLD_REV}:{TABLE}"], cwd=ROOT, capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def load_new() -> dict:
    return json.loads((ROOT / TABLE).read_text(encoding="utf-8"))


def confusion(t: dict) -> dict:
    out: dict = {}
    for c in t["confusion"]:
        out.setdefault(str(c["policy"]), []).append({"true": c["true"], "reported": c["reported"], "count": c["count"]})
    return out


def counts(t: dict) -> dict:
    return {"planted": len(t["planted"]), "strangers": len(t["strangers"]),
            "noise": len(t["noise_table"]), "noise_runs": sum(len(n["runs"]) for n in t["noise_table"])}


def _rc(t: dict, cls: dict, pi: int, reported: list):
    return C.reported_class(pi, reported, cls)


def _key(p: dict) -> str:
    return C._name(p)


def differences(old: dict, new: dict) -> list:
    co, cn = C.class_index(old["classes"]), C.class_index(new["classes"])
    out = []

    def cmp(kind, who, pi, eo, en):
        d = {}
        a, b = _rc(old, co, pi, eo["reported"]), _rc(new, cn, pi, en["reported"])
        if a != b or {SC.pkey(x) for x in eo["reported"]} != {SC.pkey(x) for x in en["reported"]}:
            d["reported_class"] = {"old": a, "new": b,
                                   "old_profiles": len(eo["reported"]), "new_profiles": len(en["reported"])}
        if eo["residual"] != en["residual"]:
            d["residual"] = {"old": eo["residual"], "new": en["residual"]}
        if eo.get("not_refuted") != en.get("not_refuted"):
            d["not_refuted"] = {"old": eo.get("not_refuted"), "new": en.get("not_refuted")}
        if d:
            out.append({"kind": kind, **who, **d})

    po = {(e["policy"], SC.pkey(e["profile"])): e for e in old["planted"]}
    for e in new["planted"]:
        o = po[(e["policy"], SC.pkey(e["profile"]))]
        cmp("planted", {"policy": e["policy"], "profile": _key(e["profile"]), "seed": e["seed"]}, e["policy"], o, e)
    so = {(e["policy"], e["name"]): e for e in old["strangers"]}
    for e in new["strangers"]:
        cmp("stranger", {"policy": e["policy"], "name": e["name"], "seed": e["seed"]}, e["policy"],
            so[(e["policy"], e["name"])], e)
    no = {(SC.pkey(n["profile"]), n["mode"]): n for n in old["noise_table"]}
    for n in new["noise_table"]:
        o = no[(SC.pkey(n["profile"]), n["mode"])]
        ro = {r["p"]: r for r in o["runs"]}
        for r in n["runs"]:
            cmp("noise", {"policy": 0, "profile": _key(n["profile"]), "mode": n["mode"], "p": r["p"],
                          "seed": r["seed"]}, 0, ro[r["p"]], r)
    return out


def silent_list(t: dict) -> list:
    return [{"profile": _key(f["profile"]), "mode": f["mode"], "p": f["p"]} for f in t["findings"]]


def first_change(n: dict) -> dict:
    return {"smallest": n["smallest"], "change": n["change"], "announced": n["announced"]}


def main() -> int:
    old, new = load_old(), load_new()
    before = {(SC.pkey(f["profile"]), f["mode"]) for f in old["findings"]}
    no = {(SC.pkey(n["profile"]), n["mode"]): n for n in old["noise_table"]}
    nn = {(SC.pkey(n["profile"]), n["mode"]): n for n in new["noise_table"]}
    sil = {(SC.pkey(s["profile"]), s["mode"]): s for s in new["silent"]}
    new_ones = []
    for f in new["findings"]:
        k = (SC.pkey(f["profile"]), f["mode"])
        if k in before:
            continue
        s = sil[k]
        o = no[k]
        run_o = next(r for r in o["runs"] if r["p"] == f["p"])
        new_ones.append({"profile": _key(f["profile"]), "mode": f["mode"], "p": f["p"],
                         "trace": s.get("trace"), "reason": s["reason"],
                         "old_row": first_change(o),
                         "old_run_at_p": {"residual": run_o["residual"], "not_refuted": run_o["not_refuted"],
                                          "changed": C._change(o["runs"][0], run_o)},
                         # the old row's first change was announced (at whatever p it came)
                         "announced_before_r14c": bool(o["announced"]),
                         "announced_before_r14c_at_this_p": bool(o["announced"]) and o["smallest"] == f["p"]})
    gone = []
    for f in old["findings"]:
        k = (SC.pkey(f["profile"]), f["mode"])
        if any((SC.pkey(g["profile"]), g["mode"]) == k for g in new["findings"]):
            continue
        gone.append({"profile": _key(f["profile"]), "mode": f["mode"], "p": f["p"],
                     "now": first_change(nn[k]), "entry": sil.get(k, {}).get("status")})
    diffs = differences(old, new)
    kinds = sorted({d["kind"] for d in diffs})
    doc = {
        "about": "R14e: the calibration table R11b published (old, git " + OLD_REV + ", before R14c and R14d) "
                 "against the republished one (new, " + TABLE + "). Reported classes are read with each "
                 "table's own classes; 'reported_class' is listed when the class or the set of reported "
                 "profiles differs.",
        "old": {"rev": OLD_REV, "confusion": confusion(old), **counts(old),
                "right": sum(e["right"] for e in old["planted"])},
        "new": {"confusion": confusion(new), **counts(new), "right": sum(e["right"] for e in new["planted"])},
        "silent": {"before": silent_list(old), "after": silent_list(new), "new": new_ones, "gone": gone},
        "differences": diffs,
        "count_by_kind": {k: sum(1 for d in diffs if d["kind"] == k) for k in kinds},
        "why": {k: WHY[k] for k in kinds},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"[r14e] wrote {OUT.relative_to(ROOT)}: {len(diffs)} differences {doc['count_by_kind']}, "
          f"silent {len(old['findings'])} -> {len(new['findings'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
