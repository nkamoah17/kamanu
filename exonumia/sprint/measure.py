"""The measurement: each family's journal read by `python -m exonumia.ledger report --json --orders`, the figures
taken from that report, the shortest trace of a family with a finding, and its regression test.

    approvals_unfit     X13's approvals.unfit.count       (an approval that did not fit under every allowed order)
    wrongful_refusals   X13's declines.fitted.count       (the handler's decline of what fitted under every order)
    order_dependent     X13's approvals and declines whose answer turned on an order the ledger cannot know
    largest_over        the largest most_over.total of any limit (X11's report)
    finding             approvals_unfit > 0 or wrongful_refusals > 0

Every figure is a count of this run's journal: level TESTED.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from exonumia.ledger import orders as _orders
from exonumia.ledger import report as _report

from exonumia.sprint import trial_of


def ledger_report(journal: Path, limits_file: Path, profile_file: Path, out: Path) -> dict:
    """Runs the ledger's own report on the journal and keeps its bytes at OUT."""
    cmd = [sys.executable, "-m", "exonumia.ledger", "report", str(journal), "--limits", str(limits_file),
           "--profile", str(profile_file), "--json", "--orders"]
    p = subprocess.run(cmd, capture_output=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if p.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd[1:])}` exited {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-400:]}")
    out.write_bytes(p.stdout)
    return json.loads(p.stdout.decode("utf-8"))


def figures(rep: dict, od: dict) -> dict:
    return {"approvals_unfit": od["approvals"]["unfit"]["count"],
            "wrongful_refusals": od["declines"]["fitted"]["count"],
            "order_dependent": od["approvals"]["order_dependent"]["count"] + od["declines"]["order_dependent"]["count"],
            "largest_over": max([x["most_over"]["total"] for x in rep["limits"]] or [0])}


def finding(f: dict) -> bool:
    return f["approvals_unfit"] > 0 or f["wrongful_refusals"] > 0


def judge(limits: list, profile: dict, events: list) -> dict:
    """The figures of a set of events, as the ledger's report and order block give them."""
    return figures(_report.books_report(limits, profile, events), _orders.judge(limits, profile, events))


def journal_lines(path: Path) -> list:
    out = path.read_text(encoding="utf-8").split("\n")
    if out and out[-1] == "":
        out.pop()
    return out


def trials(path: Path) -> dict:
    """{(family, n): [(line text, event)]} of the journal's accepted lines."""
    by: dict = {}
    for text in journal_lines(path):
        obj = json.loads(text)
        if obj.get("received") != "accepted":
            continue
        by.setdefault(trial_of(obj["event"]), []).append((text, obj["event"]))
    return by


def shortest(path: Path, limits: list, profile: dict):
    """The lines of one trial that alone has a finding, no such trial having fewer; None when there is none."""
    best = None
    for key, items in sorted(trials(path).items(), key=lambda kv: (len(kv[1]), str(kv[0]))):
        if best is not None and len(items) > len(best):
            break
        if finding(judge(limits, profile, [e for _, e in items])):
            best = [t for t, _ in items]
            break
    return best


REGRESSION = '''"""Regression: {words} ({family}), from sprint run seed {seed} against {handler}.

The shortest trace of the finding, replayed against the handler: each request asked again, the processor's other
events told in the journal's order, and the answers judged by the reference ledger (exonumia.ledger). The test
fails while the finding stands. KAMANU_SPRINT_HANDLER=module:Name (or a URL) replays it against another handler.
The processor was simulated; nothing here is a statement about a processor's system.
"""
import json
import os

from exonumia.sprint import regress

HANDLER = {handler!r}
SECRET = {secret!r}
LIMITS = json.loads({limits!r})
PROFILE = json.loads({profile!r})
TRACE = {trace}


def test_{family}():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
'''


def write_regression(path: Path, family: str, words: str, seed, handler: str, secret: str, limits: list,
                     profile: dict, trace: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = REGRESSION.format(words=words, family=family, seed=seed, handler=handler, secret=secret,
                             limits=json.dumps(limits, sort_keys=True), profile=json.dumps(profile, sort_keys=True),
                             trace=json.dumps(trace, indent=1, ensure_ascii=True))
    path.write_text(text, encoding="utf-8")
