"""kamanu.hunt.row: rows from hunts on small engines written here, and check_row."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kamanu.hunt.row import check_row, hunt_row, read_policy
from test_hunt_scope import with_scope

# R14d: the toy engines here are hunted under the tests' own scope file (tests/test_hunt_scope.py)
hunt_row = with_scope(hunt_row)

ROOT = Path(__file__).resolve().parents[1]
ABOUT = {"name": "toy", "version": "0.1.0", "obtained": {"kind": "git-rev", "value": "ab" * 20}}


def policy(cap: int, window: str = "1m", count: bool = False) -> str:
    agg = ("count for (t: Timepoint). where (\n        formerly within {w} "
           "(Bank::Action::\"Pay\"::request{{ input.amount: * }} && tp(t))\n    )") if count else \
          ("sum a for (a: Long), (t: Timepoint). where (\n        formerly within {w} "
           "(Bank::Action::\"Pay\"::request{{ input.amount: a }} && tp(t))\n    )")
    return ("@id(\"pay_cap\")\npermit (\n    principal,\n    action == Bank::Action::\"Pay\",\n    resource\n)\n"
            f"when temporal {{\n    ({agg.format(w=window)}) <= {cap}\n}};\n")


class Toy:
    """A request-sum engine: every request is kept (allowed or not); the current request
    counts. `fixed` buckets the clock by the window from `phase`; `forever` forgets nothing."""

    def __init__(self, cap, w, kind="sliding", phase=0, unit=None):
        self.cap, self.w, self.kind, self.phase = cap, w, kind, phase
        if unit:
            self.unit = unit
        self.log = []

    def open(self):
        toy = self
        ops = []
        toy.log.append(ops)

        class S:
            now, events, calls = 0, [], []

            def __init__(self):
                self.events, self.calls = [], []

            def _in(self, t):
                if toy.kind == "sliding":
                    return self.now - t <= toy.w
                if toy.kind == "fixed":
                    return (t + toy.phase) // toy.w == (self.now + toy.phase) // toy.w
                return True

            def issue(self, amount):
                a = 1 if getattr(toy, "unit", None) == "call" else amount
                self.events.append((self.now, a))
                ok = sum(x for t, x in self.events if self._in(t)) <= toy.cap
                self.calls.append(ok)
                ops.append({"op": "issue", "amount": amount, "verdict": "ALLOW" if ok else "DENY"})
                return "ALLOW" if ok else "DENY"

            def settle(self, call):
                ops.append({"op": "settle", "call": call})

            def fail(self, call):
                ops.append({"op": "fail", "call": call})

            def wait(self, seconds):
                self.now += seconds
                ops.append({"op": "wait", "seconds": seconds})
        return S()


def test_read_policy_sum_and_count():
    assert read_policy(policy(100), "amount")["shape"] == "request-sum"
    p = read_policy(policy(5, "10m", count=True), "call")
    assert (p["shape"], p["cap"], p["window_s"]) == ("request-count", 5, 600)


@pytest.mark.parametrize("kind,phase", [("sliding", 0), ("fixed", 0), ("fixed", 17), ("fixed", 59)])
def test_window_kind_and_profile(kind, phase):
    eng = Toy(100, 60, kind, phase)
    row = hunt_row(eng, policy(100), ABOUT)
    assert check_row(row) == []
    prof = row["profile"]
    assert prof["window_kind"]["value"] == kind
    assert prof["reflexive"]["values"] == [True]
    assert all("request" in m for m in prof["deny_marks"]["values"])
    assert prof["atomic"]["value"] == "not refuted"
    assert [[{k: v for k, v in o.items() if k != "moved"} for o in s["ops"]] for s in row["sessions"]] == eng.log
    assert all(row["cells"][n]["verdict"] in ("fails", "passes") for n in row["cells"])


def test_forever_is_unknown_never_forced():
    row = hunt_row(Toy(100, 60, "forever"), policy(100), ABOUT)
    assert check_row(row) == []
    wk = row["profile"]["window_kind"]
    assert wk["value"] == "unknown" and wk["sessions"]
    assert all(c["verdict"] == "untested" and c["reason"] for c in row["cells"].values())


def test_call_engine_issues_ones_and_reads_calls():
    eng = Toy(4, 60, unit="call")
    row = hunt_row(eng, policy(4, count=True), ABOUT)
    assert check_row(row) == []
    assert row["policy"]["unit"] == "call" and row["policy"]["cap"] == 4
    assert {o["amount"] for ops in eng.log for o in ops if o["op"] == "issue"} == {1}
    assert row["profile"]["window_kind"]["value"] == "sliding"


@pytest.fixture(scope="module")
def row():
    return hunt_row(Toy(100, 60), policy(100), ABOUT)


def _tested(r):
    return [n for n, c in r["cells"].items() if c["verdict"] != "untested"]


def test_check_row_rejects_hand_edits(row):
    assert check_row(row) == []
    for edit in ("trace", "version", "date", "flip", "cell-version"):
        r = copy.deepcopy(row)
        name = _tested(r)[0]
        if edit == "trace":
            del r["cells"][name]["trace"]
        elif edit == "version":
            r["engine"]["version"] = " "
        elif edit == "date":
            del r["cells"][name]["date"]
        elif edit == "cell-version":
            r["cells"][name]["version"] = "9.9.9"
        else:
            for n in _tested(r):
                c = r["cells"][n]
                c["verdict"] = "passes" if c["verdict"] == "fails" else "fails"
        assert check_row(r), f"check_row accepts a row with its {edit} edited"


def test_cli_check_row(row, tmp_path):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(row), encoding="utf-8")
    r = copy.deepcopy(row)
    r["engine"]["version"] = ""
    bad.write_text(json.dumps(r), encoding="utf-8")
    run = [sys.executable, "-m", "kamanu.hunt", "--check-row"]
    assert subprocess.run(run + [str(good)], cwd=ROOT, capture_output=True).returncode == 0
    assert subprocess.run(run + [str(bad)], cwd=ROOT, capture_output=True).returncode != 0


def test_committed_dogwood_row_checks():
    r = json.loads((ROOT / "profiles" / "rows" / "dogwood-1.1.1.json").read_text(encoding="utf-8"))
    assert check_row(r) == []
    assert r["engine"]["name"] == "dogwood" and r["engine"]["obtained"]["kind"] == "binary-sha256"
    assert r["profile"]["window_kind"]["value"] == "sliding"
