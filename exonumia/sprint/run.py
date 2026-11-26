"""`python -m exonumia.sprint run`: the whole sprint on one authorization path, as one command.

Steps (each timed into DIR/run.json): the scope; the battery, one family at a time, each into its journal; the
ledger's report of each journal; the shortest traces and regression tests; the model (kamanu scan --card, a
receipt per limit); the cabinet (the ledger reports ingested); the report.

Exit 0: every family ran, no finding, no part UNKNOWN; 1: a family has a finding; 2: a part UNKNOWN and no
finding; 3: a scope or a TARGET that cannot be read (nothing is written).
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from exonumia.sprint import DEFAULT_SEED, DEFAULT_TRIALS, FAMILIES, KEYS, WORDS, sentence
from exonumia.sprint import battery, measure, model, report, scope, target


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")


def _shown(path: Path) -> str:
    """A path as the record keeps it: relative to the tree's root when inside it, else absolute."""
    p = path.resolve()
    try:
        return p.relative_to(scope.TREE.resolve()).as_posix()
    except ValueError:
        return str(p)


class Clock:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.steps: list = []

    def step(self, name: str, since: float) -> None:
        self.steps.append({"step": name, "seconds": round(time.perf_counter() - since, 3)})

    def total(self) -> float:
        return round(time.perf_counter() - self.t0, 3)


def run(a) -> int:
    clock = Clock()
    t = time.perf_counter()
    try:
        sc = scope.read(a.scope)
    except scope.ScopeError as e:
        print(f"sprint: {e}", file=sys.stderr)
        return 3
    live_raw = None
    if a.live:
        try:
            live_raw = json.loads(Path(a.live).read_text(encoding="utf-8"))
            if not isinstance(live_raw, dict):
                raise ValueError("not a JSON object")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            print(f"sprint: cannot read the live configuration {a.live}: {e}", file=sys.stderr)
            return 3
    limits = sc["limits"]
    try:
        handler = target.load(a.handler, limits, sc["secret"])
    except target.TargetError as e:
        print(f"sprint: {e}", file=sys.stderr)
        return 3
    trials = a.trials if a.trials is not None else DEFAULT_TRIALS
    if trials < 1:
        print("sprint: --trials is at least 1", file=sys.stderr)
        return 3
    seed = a.seed if a.seed is not None else DEFAULT_SEED
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("journals", "ledger", "profiles", "receipts", "regressions"):
        if (out / sub).is_dir():
            shutil.rmtree(out / sub)
    for f in ("report.json", "report.md", "report.html", "run.json", "verify.txt"):
        if (out / f).exists():
            (out / f).unlink()
    cabinet = Path(a.cabinet) if a.cabinet else out / "cabinet"
    profile = scope.ledger_profile(sc["card"], sc["currency"])
    _dump(out / "ledger" / "limits.json", {"spending_limits": limits})
    _dump(out / "ledger" / "profile.json", profile)
    ctx = {"limits": limits, "profile": profile, "currency": sc["currency"], "category": battery.category(limits),
           "parallel": sc["parallel"]}
    clock.step("scope", t)

    # ---- the battery
    ran: dict = {}
    for k in KEYS:
        t = time.perf_counter()
        ran[k] = battery.run_family(handler, ctx, k, trials, seed, out / "journals" / f"{k}.jsonl")
        clock.step(f"battery: {WORDS[k]}", t)
        print(f"sprint: {WORDS[k]}: {ran[k]['trials']} trials played", flush=True)

    # ---- the ledger's report of each journal
    t = time.perf_counter()
    lf, pf = out / "ledger" / "limits.json", out / "ledger" / "profile.json"
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {k: pool.submit(measure.ledger_report, out / "journals" / f"{k}.jsonl", lf, pf, out / "ledger" / f"{k}.json")
                for k in KEYS}
        reps = {}
        for k, f in futs.items():
            try:
                reps[k] = f.result()
            except (RuntimeError, ValueError) as e:
                reps[k] = None
                ran[k]["errors"].append(str(e))
    clock.step("ledger reports", t)

    # ---- figures, shortest traces, regressions
    t = time.perf_counter()
    fams = []
    for k, words in FAMILIES:
        rep = reps[k]
        f = {"family": k, "name": words, "trials": ran[k]["trials"], "approvals_unfit": None, "wrongful_refusals": None,
             "order_dependent": None, "largest_over": None, "finding": False, "shortest": None,
             "journal": f"journals/{k}.jsonl", "report": f"ledger/{k}.json", "regression": None, "sentence": None,
             "level": "TESTED"}
        if rep is not None:
            f.update(measure.figures(rep, rep["orders"]))
            f["finding"] = measure.finding(f)
        if f["finding"]:
            f["shortest"] = measure.shortest(out / "journals" / f"{k}.jsonl", limits, profile)
            f["regression"] = f"regressions/test_{k}.py"
            measure.write_regression(out / f["regression"], k, words, seed, a.handler, sc["secret"], limits, profile,
                                     f["shortest"] or [])
        elif rep is not None:
            f["sentence"] = sentence(f["trials"])
        if ran[k]["errors"] or rep is None:
            f["status"] = "UNKNOWN"
            f["error"] = "; ".join(ran[k]["errors"][:3])
        fams.append(f)
    clock.step("findings and regressions", t)

    # ---- the model and the cabinet
    t = time.perf_counter()
    mlimits = []
    for lim in limits:
        prof_rel, rec_rel = f"profiles/{lim['id']}.json", f"receipts/{lim['id']}.json"
        _dump(out / prof_rel, scope.profile_for(sc["card"], lim))
        answer = model.assay(out / prof_rel)
        (out / "receipts").mkdir(parents=True, exist_ok=True)
        rc, so, se = model.scan_card(out / prof_rel, out / rec_rel, cabinet, a.key)
        receipt = None
        if rc in (0, 1, 2) and (out / rec_rel).is_file():
            receipt = json.loads((out / rec_rel).read_text(encoding="utf-8"))
        else:
            print(f"sprint: kamanu scan --card {prof_rel} exited {rc}: {(so + se)[-400:]}", file=sys.stderr)
        e = model.limit_entry(lim, scope.window(lim), prof_rel, rec_rel, answer, receipt)
        mlimits.append(e)
    clock.step("model: kamanu scan --card, a receipt per limit", t)
    t = time.perf_counter()
    rc, so, se = model.ingest(out / "ledger", cabinet, sc["consent"], a.key)
    if rc not in (0, 1):
        print(f"sprint: kamanu scan --ingest exited {rc}: {(so + se)[-400:]}", file=sys.stderr)
    clock.step("cabinet: kamanu scan --ingest of the ledger reports", t)

    # ---- the report
    t = time.perf_counter()
    decided = all(m.pop("decided") for m in mlimits) and not any(f.get("status") == "UNKNOWN" for f in fams)
    n_find = sum(1 for f in fams if f["finding"])
    rep = report.build(headline=report.headline(decided, n_find, len(fams)), decided=decided, simulated=True,
                       handler=a.handler, scope=_shown(Path(a.scope)), seed=seed, trials=trials,
                       parallel=sc["parallel"], model={"limits": mlimits},
                       measurement={"level": "TESTED", "families": fams},
                       deployment=report.deployment(sc["raw"], live_raw, a.live),
                       cabinet=_shown(cabinet), consent=sc["consent"])
    _dump(out / "report.json", rep)
    (out / "report.md").write_text(report.markdown(rep), encoding="utf-8")
    (out / "report.html").write_text(report.page(rep), encoding="utf-8")
    clock.step("report", t)
    total = clock.total()
    _dump(out / "run.json", {"handler": a.handler, "scope": _shown(Path(a.scope)), "seed": seed, "trials": trials,
                             "parallel": sc["parallel"], "steps": clock.steps, "total": total})
    print(rep["headline"])
    print(f"sprint: report {out / 'report.md'}; {total:.1f} s in all")
    if n_find:
        return 1
    return 0 if decided else 2

