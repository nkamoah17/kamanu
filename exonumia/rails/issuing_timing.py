"""Card X12's timing.json: how long the Issuing run takes, stage by stage, read from runs' own journals.

    python -m exonumia.rails.issuing_timing OUT SIMULATOR RECOMMENDED K=JOURNAL [K=JOURNAL ...]

Each JOURNAL is the run.journal.jsonl of one whole run (exonumia.rails.issuing.run) at sessions = trials
= K, made on gate X2b's Stripe simulator (SIMULATOR names its file: its Stripe, behind a port whose clock
threads share), so the hours are the port's clock, not the machine's. A stage is the hunt (its sessions and their
confirmations) or one rail test; its hours run from the start of its first piece (in the plan's order)
to the start of the next stage's first piece, the last stage's to the run's end, so that the stages sum
to the run's total. bounds: the longest single wait any piece made, and the first midnight UTC the
reset trials waited for. Reads journals only.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

STAGES = ("hunt", "over-ask", "parallel", "over-capture", "force-capture", "reset")


def lines_of(journal: Path) -> list:
    data = journal.read_bytes()
    out = []
    for raw in data[:data.rfind(b"\n") + 1].split(b"\n"):
        try:
            o = json.loads(raw.decode("utf-8")) if raw.strip() else None
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def stages(journal: Path) -> dict:
    ls = lines_of(journal)
    pieces = sorted((o for o in ls if "piece" in o), key=lambda o: o["seq"])
    first: dict = {}
    for p in pieces:
        first.setdefault(p["test"], p["start"])
    end = max(p["end"] for p in pieces)
    order = [s for s in STAGES if s in first]
    out = {}
    for i, s in enumerate(order):
        nxt = first[order[i + 1]] if i + 1 < len(order) else end
        out[s] = round((nxt - first[s]) / 3600.0, 3)
    total = round((end - min(p["start"] for p in pieces)) / 3600.0, 3)
    waits = [float(o["until"]) - float(o["t"]) for o in ls if "until" in o and "t" in o]
    resets = [p for p in pieces if p["test"] == "reset"]
    night = None
    if resets:
        t0 = min(p["start"] for p in resets)
        night = dt.datetime.fromtimestamp((int(t0) // 86400 + 1) * 86400, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"stages": out, "total": total, "pieces": len(pieces), "longest_wait_s": max(waits, default=0.0),
            "first_midnight": night}


def main(argv) -> int:
    out, simulator, rec, *pairs = argv
    runs, longest, night = {}, 0.0, None
    for pair in pairs:
        k, _, path = pair.partition("=")
        st = stages(Path(path))
        runs[k] = {"stages": st["stages"], "total": st["total"], "pieces": st["pieces"]}
        longest = max(longest, st["longest_wait_s"])
        if k == "1":
            night = st["first_midnight"]
    doc = {"simulator": simulator, "recommended": int(rec), "runs": runs,
           "bounds": {"longest_wait_hours": round(longest / 3600.0, 3), "first_midnight": night}}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
