"""R14b: fix judges every policy proposal on the closed machine, on every reading, without TLC here."""
import json
from pathlib import Path

from kamanu.fast import machine as MC
from kamanu.ladder import fix as F

ROOT = Path(__file__).resolve().parents[1]


def sit(**kw):
    s = {"policy": ["PReqBasis"], "refusal_leaves": ["none"], "rung": "R2",
         "profile": {"atomic": [True], "own_writes": [True], "other_lag": [0]}, "gaps": [],
         "scope": "global", "workers": 1, "settings": {}, "refuses": False,
         "bounds": {"cap": 100, "amounts": [30, 60], "max_req": 3}}
    s.update(kw)
    return s


def kong():
    return sit(refusal_leaves=["error", "none", "request"], bounds={"cap": 2, "amounts": [1], "max_req": 3})


def by_mark(cl):
    return {r["refusal_leaves"]: r for r in cl["readings"]}


def test_readings_are_every_open_value_once():
    s = sit(refusal_leaves=["deny", "request"],
            profile={"atomic": [True, False], "own_writes": [True, False], "other_lag": [0, 1, 2]})
    rds = F.readings(s)
    assert len(rds) == 8 and len(set(rds)) == 8          # other_lag is no reading
    cl = F.closed(s, "PReqBasis")
    assert cl["requests"] == "any" and (cl["in_flight"], cl["failures"]) == (2, 1)
    assert [(r["refusal_leaves"], r["atomic"], r["own_writes"]) for r in cl["readings"]] == rds


def test_the_kong_trap_shows_only_beyond_three_requests():
    s = kong()
    cl = by_mark(F.closed(s, "PRefundOnReconcile"))
    for m in ("error", "none"):
        assert F.reading_verdict(cl[m]) == "holds" and cl[m]["Tight"]["trace"] is None
    bad = cl["request"]
    assert bad["Sound"]["status"] == "holds" and bad["Tight"]["status"] == "FAILS"
    tr = bad["Tight"]["trace"]
    assert sum(st["step"] == "issue" for st in tr) > s["bounds"]["max_req"]     # a fourth request
    last = tr[-1]
    assert last["step"] == "decide" and last["outcome"] == "deny"
    before = tr[-2]
    assert before["held"] + before["spent"] + before["doubt"] + last["amount"] <= s["bounds"]["cap"]
    # within three requests the same machine finds nothing: the bounded answer key's trap
    st = F.closed_setting(s, "PRefundOnReconcile", ("request", True, True), in_flight=3)
    m = MC.Machine(st)
    m.N = 3
    run = m.explore()
    assert run["sound"] is None and run["tight"] is None and not run["cut"]


def test_labels():
    assert F.label_of(["holds", "holds"], "holds") == "repair"
    assert F.label_of(["holds", "holds"], "FAILS") == "fails"
    assert F.label_of(["holds", "holds"], "VACUOUS") == "fails"
    assert F.label_of(["holds", "FAILS"], None) == "trade-off"
    assert F.label_of(["FAILS", "open"], None) == "fails"
    assert F.label_of(["FAILS"], None) == "fails"
    assert F.label_of(["holds", "open"], None) == "open"      # open is never a repair
    assert F.label_of(["open"], None) == "open"


def test_entry_takes_the_certificate_only_when_every_reading_holds():
    s = kong()
    p = {"move": "refund-on-reconcile", "place": "policy", "slots": {"policy": "PRefundOnReconcile"}}
    j = {"verdict": "holds"}                 # TLC at three requests passes the trap
    e = F.closed_entry(s, p, j)
    assert e["label"] == "trade-off" and e["tlc"] is None
    t = dict(e, repair=p, verdict="holds", cell=None, check=None, trace=None)
    words = F._tried_words(t, s)
    assert "trade-off" in words and "any number of requests" in words and "3 requests" in words
    assert "refusal leaves request" in words and "Tight FAILS" in words
    s2 = sit(refusal_leaves=["error", "none"], bounds={"cap": 2, "amounts": [1], "max_req": 3})
    e2 = F.closed_entry(s2, p, j)
    assert e2["label"] == "repair"
    assert e2["tlc"] == {"verdict": "holds", "bounds": {"max_req": 3, "max_fails": 1, "cap": 2, "amounts": [1]}}
    assert F.closed_entry(s2, p, {"verdict": "FAILS"})["label"] == "fails"


def test_an_open_reading_is_never_a_repair():
    s = sit()
    cl = F.closed(s, "PRefundOnReconcile", budget=5)
    assert all(F.reading_verdict(r) == "open" for r in cl["readings"])
    assert all(r[p]["trace"] is None for r in cl["readings"] for p in F.PROPS)
    assert F.label_of([F.reading_verdict(r) for r in cl["readings"]], None) == "open"


def test_a_session_cap_is_judged_on_the_callers_ledger():
    s = sit(scope="session")
    r = F.closed(s, "PRefundOnReconcile")["readings"][0]
    assert r["Sound"]["status"] == "FAILS" and r["Sound"].get("ledger") == "caller"
    assert r["Sound"]["trace"][-1]["caller"] > s["bounds"]["cap"]
    g = F.closed(sit(), "PRefundOnReconcile")["readings"][0]
    assert g["Sound"]["status"] == "holds" and "ledger" not in g["Sound"]


def test_rows_before_and_after():
    p = {"move": "refund-on-reconcile", "place": "policy", "slots": {"policy": "PRefundOnReconcile"}}
    s = kong()
    entry = dict(F.closed_entry(s, p, {"verdict": "holds"}), repair=p, verdict="holds")
    rows = [{"path": "profiles/rows/x.json",
             "report": {"status": "no-repair", "repair": None, "tried": [entry]}}]
    fixes = {"rows": [{"path": "profiles/rows/x.json",
                       "report": {"status": "repair", "repair": p, "tried": [{"repair": p, "verdict": "holds"}]}}]}
    before = F.before_doc(fixes, "abc")
    doc = F.r14b_rows(rows, before)
    assert doc["before"] == {"commit": "abc"}
    (r,) = doc["rows"]
    assert r["before"] == {"status": "repair", "repair": {"move": p["move"], "slots": p["slots"]}}
    assert r["after"] == {"status": "no-repair", "repair": None}
    (c,) = r["changed"]
    assert (c["before"], c["after"], c["property"]) == ("holds", "trade-off", "Tight")
    assert c["reading"] == {"refusal_leaves": "request", "atomic": True, "own_writes": True} and c["trace"]


def test_published_evidence_is_in_step():
    fixes = json.loads((ROOT / "evidence/ladder/r7/fixes.json").read_text(encoding="utf-8"))
    before = json.loads((ROOT / "evidence/ladder/r14b/before.json").read_text(encoding="utf-8"))
    rows = json.loads((ROOT / "evidence/ladder/r14b/rows.json").read_text(encoding="utf-8"))
    assert rows == F.r14b_rows(fixes["rows"], before)
    for e in fixes["rows"]:
        rep = e["report"]
        for t in rep["tried"]:
            if t["repair"]["move"] in F.POLICY_MOVES:
                vs = [F.reading_verdict(r) for r in t["closed"]["readings"]]
                assert t["label"] == F.label_of(vs, (t["tlc"] or {}).get("verdict"))
                assert (t["tlc"] is not None) == all(v == "holds" for v in vs)
        r = rep.get("repair")
        if r and r["move"] in F.POLICY_MOVES:
            assert rep["tried"][-1]["label"] == "repair" and rep["certificate"]["any_requests"] == "closed"
    kong_rep = next(e["report"] for e in fixes["rows"] if e["path"].endswith("kong-rate-limiting.json"))
    assert not (kong_rep.get("repair") and kong_rep["repair"]["move"] in F.POLICY_MOVES)
