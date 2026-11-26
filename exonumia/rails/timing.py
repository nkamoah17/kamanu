"""Card X10's timing.json: each test's wall time in a run, read from the run's own journal.

    python -m exonumia.rails.timing X10_JOURNAL X8_RUN3_JOURNAL OUT

A test's seconds are the span of its pieces on the port's clock: the latest end of a piece holding a
session of that test, less the earliest start of one. Hunt sessions are no test's.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def spans(journal: Path) -> dict:
    pieces = []
    data = journal.read_bytes()
    for raw in data[:data.rfind(b"\n") + 1].split(b"\n"):
        try:
            o = json.loads(raw.decode("utf-8")) if raw.strip() else None
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(o, dict) and "piece" in o:
            pieces.append(o)
    out: dict = {}
    for p in pieces:
        for t in {s.get("test") for s in p.get("sessions") or [] if s.get("test") not in ("hunt", None)}:
            a, b = out.get(t, (p["start"], p["end"]))
            out[t] = (min(a, p["start"]), max(b, p["end"]))
    return {t: round(b - a, 1) for t, (a, b) in out.items()}


def main(argv) -> int:
    x10, x8, dst = (Path(a) for a in argv)
    doc = {"x10": spans(x10), "x8_run3": spans(x8),
           "how": "each test's seconds: the span of its pieces in the run's journal (latest end less earliest start, "
                  "on the port's clock); x10 from " + x10.as_posix() + ", x8_run3 from " + x8.as_posix()}
    dst.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
