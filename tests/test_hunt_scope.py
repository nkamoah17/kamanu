"""The scope file (R14d, kamanu.hunt.scope): refusal before the first request, the ceilings, the
transcript. Also the scope the other hunt tests run their toy engines under (with_scope, scopes)."""
from __future__ import annotations

import datetime
import functools
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from kamanu.hunt import Model, Policy, hunt
from kamanu.hunt import scope as S
from kamanu.hunt.row import check_row, hunt_row

ROOT = Path(__file__).resolve().parents[1]
TARGET = {"adapter": "tests", "address": "in-process toy engine"}
ABOUT = {"name": "toy", "version": "0.1.0", "obtained": {"kind": "git-rev", "value": "abc123"}}
BIG = {"requests": 10 ** 6, "money": 10 ** 12}
_DIR: list = []


def day(delta: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=delta)).isoformat()


def scope_doc(target=None, **over) -> dict:
    doc = {"target": dict(target or TARGET), "owner": "the tests", "basis": {"kind": "own-instance"},
           "ceilings": dict(BIG), "expires": day(30)}
    doc.update(over)
    return doc


def write_scope(doc) -> str:
    if not _DIR:
        _DIR.append(Path(tempfile.mkdtemp(prefix="kamanu-test-scope-")))
    text = doc if isinstance(doc, str) else json.dumps(doc, indent=1, sort_keys=True)
    f = _DIR[0] / f"scope-{hashlib.sha256(text.encode()).hexdigest()[:16]}.json"
    f.write_text(text, encoding="utf-8")
    return str(f)


def scopes(engine) -> str:
    """The scope file of a toy engine of the tests (what a rebuild's `scopes` returns): the engine is
    given the tests' target when it declares none."""
    if not S.is_target(getattr(engine, "target", None)):
        engine.target = dict(TARGET)
    return write_scope(scope_doc(engine.target))


def with_scope(fn):
    """fn (hunt or hunt_row) with scope= filled in for the tests' toy engines."""
    @functools.wraps(fn)
    def run(engine, *a, **kw):
        if "scope" not in kw and S.in_process(engine) is None:
            kw["scope"] = scopes(engine)
        return fn(engine, *a, **kw)
    return run


def policy(cap: int = 100, window: str = "1m") -> str:
    return (f'permit (principal, action == Bank::Action::"Pay", resource)\n'
            f"when temporal {{ (sum a for (a: Long), (t: Timepoint). where (formerly within {window} "
            f'(Bank::Action::"Pay"::request{{ input.amount: a }} && tp(t)))) <= {cap} }};\n')


TEXT = policy()


class Counted:
    """A toy engine (the hunt's own model of one profile) that counts what reaches it."""

    def __init__(self, target=TARGET, version=None, profile=None):
        self.p = Policy(TEXT)
        self.profile = profile or {"reflexive": True, "deny_marks": ["request"]}
        self.sessions = self.requests = self.money = 0
        if target is not None:
            self.target = dict(target)
        if version is not None:
            self.version = version

    def open(self):
        eng, inner = self, Model(self.profile, self.p)
        self.sessions += 1

        class Session:
            def issue(self, amount):
                eng.requests += 1
                eng.money += amount
                return inner.issue(amount)

            def settle(self, call):
                inner.settle(call)

            def fail(self, call):
                inner.fail(call)

            def wait(self, seconds):
                inner.wait(seconds)
        return Session()


def both(eng, **kw):
    return [("hunt", lambda e=eng: hunt(e, TEXT, **kw)), ("row", lambda e=eng: hunt_row(e, TEXT, ABOUT, **kw))]


# ---------------------------------------------------------------- the file
def test_problems_names_each_defect():
    good = scope_doc()
    assert S.problems(good) == []
    assert S.problems(scope_doc(basis={"kind": "published-statement", "url": "https://vendor.example/scope"})) == []
    for bad in ({**good, "owner": " "}, {**good, "target": {"adapter": "tests"}},
                {**good, "target": {**TARGET, "binary": "/x"}}, {**good, "basis": {"kind": "published-statement"}},
                {**good, "basis": {"kind": "assumed"}}, {**good, "ceilings": {"requests": 5}},
                {**good, "ceilings": {"requests": True, "money": 1}}, {**good, "ceilings": {"requests": -1, "money": 1}},
                {**good, "expires": "2026-13-40"}, {**good, "expires": "soon"}, [good], "x"):
        assert S.problems(bad), bad


def test_schema_file_says_what_problems_says():
    schema = json.loads((ROOT / "schema" / "scope.schema.json").read_text(encoding="utf-8"))
    assert schema["required"] == ["target", "owner", "basis", "ceilings", "expires"]
    assert set(schema["properties"]["target"]["properties"]) == {"adapter", *S.KINDS}
    kinds = [b["properties"]["kind"]["const"] for b in schema["properties"]["basis"]["oneOf"]]
    assert kinds == list(S.BASES)


# ---------------------------------------------------------------- refusal
@pytest.mark.parametrize("how", ["hunt", "row"])
def test_refused_before_any_session(how):
    cases = [(None, "missing"),
             (write_scope(scope_doc(expires=day(-3))), "expired"),
             (write_scope(scope_doc({**TARGET, "address": "elsewhere"})), "target"),
             (write_scope(scope_doc({**TARGET, "adapter": "other"})), "target"),
             (write_scope(scope_doc({"adapter": "tests", "binary": TARGET["address"]})), "target"),
             (write_scope("not json"), "invalid"),
             (write_scope({**scope_doc(), "owner": ""}), "invalid"),
             (str(Path(tempfile.gettempdir()) / "kamanu-no-such-scope.json"), "invalid")]
    for scope, reason in cases:
        eng = Counted()
        with pytest.raises(S.ScopeRefused) as e:
            dict(both(eng, scope=scope))[how]()
        assert e.value.reason == reason and "scope" in str(e.value)
        assert eng.sessions == 0 and eng.requests == 0


def test_an_engine_that_declares_no_target_is_refused():
    eng = Counted(target=None)
    with pytest.raises(S.ScopeRefused) as e:
        hunt(eng, TEXT, scope=write_scope(scope_doc()))
    assert e.value.reason == "target" and eng.sessions == 0


def test_the_expiry_day_itself_still_holds():
    eng = Counted()
    rep = hunt(eng, TEXT, scope=Path(write_scope(scope_doc(expires=day(0)))))
    assert rep["hunt_scope"]["used"]["requests"] == eng.requests > 0


def test_bundled_engines_need_no_scope():
    from kamanu.hunt.reference import ReferenceEngine
    from kamanu.ladder import sim
    rep = hunt(ReferenceEngine(TEXT), TEXT)
    b = rep["hunt_scope"]
    assert b["sha256"] is None and b["adapter"] == "reference" and b["target"] is None and b["stopped"] is None
    assert b["used"]["requests"] == sum(o["op"] == "issue" for s in rep["sessions"] for o in s["ops"])
    eng = sim.engine({"window_kind": "sliding", "reflexive": True, "deny_marks": [], "atomic": True},
                     {"shape": "request-sum", "cap": 100, "window_s": 60}, 1)
    assert hunt_row(eng, TEXT, ABOUT)["hunt_scope"]["adapter"] == "simulated"

    class Mine(ReferenceEngine):        # recognised by its class and nothing else
        pass
    with pytest.raises(S.ScopeRefused):
        hunt(Mine(TEXT), TEXT)


# ---------------------------------------------------------------- the transcript and the ceilings
@pytest.mark.parametrize("how", ["hunt", "row"])
def test_transcript_and_ceilings(how):
    path = write_scope(scope_doc())
    eng = Counted(version="9.9.9")
    doc = dict(both(eng, scope=path, seed=41))[how]()
    b = doc["hunt_scope"]
    assert b["sha256"] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert (b["target"], b["ceilings"], b["seed"], b["adapter"], b["engine_version"]) == \
        (TARGET, BIG, 41, "tests", "9.9.9")
    assert b["used"] == {"requests": eng.requests, "money": eng.money}
    assert b["stopped"] is None and b["not_run"] == [] and b["vendor_first"] is False and b["notice"] is None
    total, money = eng.requests, eng.money
    for which, limit in [("requests", n) for n in (0, 1, 2, 7, total - 1)] + \
                        [("money", m) for m in (0, 1, money // 3, money - 1)]:
        eng = Counted()
        capped = scope_doc(ceilings={**BIG, which: limit})
        b = dict(both(eng, scope=write_scope(capped), seed=41))[how]()["hunt_scope"]
        assert (eng.requests if which == "requests" else eng.money) <= limit
        assert b["used"] == {"requests": eng.requests, "money": eng.money}
        assert b["stopped"] == which and b["not_run"], (which, limit)
    eng = Counted()
    b = dict(both(eng, scope=write_scope(scope_doc(ceilings={"requests": total, "money": money})), seed=41))[how]()
    assert eng.requests == total and b["hunt_scope"]["stopped"] is None


def test_a_stopped_row_checks_and_names_no_profile():
    for n in (0, 1, 3, 5, 40):          # stopped before any probe, before the window is decided, before the trials
        row = hunt_row(Counted(), TEXT, ABOUT, scope=write_scope(scope_doc(ceilings={"requests": n, "money": 10 ** 9})))
        assert check_row(json.loads(json.dumps(row))) == [], n
    eng = Counted()
    row = hunt_row(eng, TEXT, ABOUT, scope=write_scope(scope_doc(ceilings={"requests": 9, "money": BIG["money"]})))
    assert check_row(json.loads(json.dumps(row))) == []
    assert row["identification"]["result"] == "out of budget" and row["identification"]["ceiling"] == "requests"
    assert all(c["verdict"] == "untested" and "ceiling" in c["reason"] for c in row["cells"].values())
    assert sum(o["op"] == "issue" for s in row["sessions"] for o in s["ops"]) == eng.requests <= 9


def test_no_seed_is_an_int_and_the_same_for_the_same_hunt():
    path = write_scope(scope_doc())
    a = hunt(Counted(), TEXT, scope=path)["hunt_scope"]["seed"]
    assert isinstance(a, int) and a == hunt(Counted(), TEXT, scope=path)["hunt_scope"]["seed"]
    with pytest.raises(ValueError):
        hunt(Counted(), TEXT, scope=path, seed="7")


def test_vendor_first_only_under_a_published_statement():
    url = "https://vendor.example/security/in-scope"
    prof = {"reflexive": False, "deny_marks": []}       # the engine does not count the request it decides
    pub = scope_doc(basis={"kind": "published-statement", "url": url})
    rep = hunt(Counted(profile=prof), TEXT, scope=write_scope(pub))
    fails = [n for n in S.SOUND if rep["tests"][n]["verdict"] == "fails"]
    b = rep["hunt_scope"]
    assert b["vendor_first"] is bool(fails)
    if fails:
        assert "vendor" in b["notice"] and url in b["notice"]
        assert any("vendor" in ln for ln in S.lines(b))
    own = hunt(Counted(profile=prof), TEXT, scope=write_scope(scope_doc()))["hunt_scope"]
    assert own["vendor_first"] is False and own["notice"] is None


def test_notice_wording():
    g = S.Grant("x", scope_doc(basis={"kind": "published-statement", "url": "https://v.example/s"}), "0" * 64)
    b = g.block(1, verdicts={"parallel": {"verdict": "fails"}, "ambiguous": {"verdict": "passes"}})
    assert b["vendor_first"] is True and "parallel" in b["notice"] and "https://v.example/s" in b["notice"]
    assert g.block(1, verdicts={"over-ask": {"verdict": "fails"}})["vendor_first"] is False


# ---------------------------------------------------------------- rows before the scope file
def test_a_row_without_a_scope_is_still_read(tmp_path):
    row = json.loads(json.dumps(hunt_row(Counted(), TEXT, ABOUT, scope=write_scope(scope_doc()))))
    old = {k: v for k, v in row.items() if k != "hunt_scope"}
    assert check_row(row) == [] and check_row(old) == []
    assert S.marked(row) and not S.marked(old)
    bad = json.loads(json.dumps(row))
    bad["hunt_scope"]["used"]["requests"] = BIG["requests"] + 1
    assert any("more than its scope" in p for p in check_row(bad))
    for name, doc, says in (("new.json", row, False), ("old.json", old, True)):
        (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")
        p = subprocess.run([sys.executable, "-m", "kamanu.hunt", "--check-row", str(tmp_path / name)],
                           capture_output=True, text=True, cwd=ROOT)
        assert p.returncode == 0 and ("no scope" in p.stdout) == says


# ---------------------------------------------------------------- the commands and the MCP tool
def _fake_binary(tmp_path) -> Path:
    b = tmp_path / "dogwood-never-started"
    b.write_text("not a program", encoding="utf-8")
    return b


def _files(tmp_path):
    from kamanu import examples
    pol, schema = examples.files("dogwood")
    return ["--adapter", "dogwood", "--policy", str(pol), "--policy-schema", str(schema)]


@pytest.mark.parametrize("module,head,tail", [("kamanu.hunt.cli", ["hunt"], []), ("kamanu.cli", ["hunt"], []),
                                              ("kamanu.hunt", [], ["--row", "ROW"])])
def test_commands_exit_with_the_scope_code(tmp_path, module, head, tail):
    b = _fake_binary(tmp_path)
    out_row = tmp_path / "row.json"
    tail = [str(out_row) if x == "ROW" else x for x in tail]
    env = {**os.environ, "DOGWOOD_BIN": str(b), "KAMANU_RECORDS_DIR": str(tmp_path / "records")}
    other = write_scope(scope_doc({"adapter": "dogwood", "binary": str(b) + ".other"}))
    for extra in ([], ["--scope", other], ["--scope", write_scope(scope_doc({"adapter": "dogwood", "binary": str(b)},
                                                                            expires=day(-2)))]):
        p = subprocess.run([sys.executable, "-m", module, *head, *_files(tmp_path), *tail, *extra],
                           capture_output=True, text=True, cwd=ROOT, env=env)
        assert p.returncode == S.SCOPE_REFUSED_EXIT, p.stderr
        assert "scope" in p.stderr and not out_row.exists()
    ok = write_scope(scope_doc({"adapter": "dogwood", "binary": str(b)}))
    p = subprocess.run([sys.executable, "-m", module, *head, *_files(tmp_path), *tail, "--scope", ok],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert p.returncode == 3            # admitted; the file is not a program, so the hunt itself fails


def test_mcp_hunt_tool_takes_the_scope(tmp_path):
    from kamanu import mcp_server as M
    assert "scope" in M.HUNT_TOOL["inputSchema"]["properties"]
    assert M.hunt_argv({"adapter": "dogwood", "scope": "s.json"}) == ["--adapter", "dogwood", "--scope", "s.json"]
    b = _fake_binary(tmp_path)
    args = dict(zip(("adapter", "policy", "policy_schema"), _files(tmp_path)[1::2]))
    old = os.environ.get("DOGWOOD_BIN")
    os.environ["DOGWOOD_BIN"] = str(b)
    try:
        r = M._hunt_call({"arguments": args})
    finally:
        if old is None:
            del os.environ["DOGWOOD_BIN"]
        else:
            os.environ["DOGWOOD_BIN"] = old
    assert r["isError"] is True and "scope" in r["content"][0]["text"]


# ---------------------------------------------------------------- the adapters, the freeze, the judge
def test_adapters_declare_their_targets(tmp_path):
    from kamanu import examples
    from kamanu.hunt.adapters import dogwood_local, kong, redis_sliding_log
    from kamanu.hunt.dogwood import DogwoodEngine
    pol, schema = examples.files("dogwood")
    p = Policy(pol.read_text(encoding="utf-8"))
    eng = DogwoodEngine("/opt/dogwood/bin/dogwood", pol, schema, p.namespace, p.tool)
    assert eng.target == {"adapter": "dogwood", "binary": "/opt/dogwood/bin/dogwood"}
    dl = dogwood_local.engine(["harness", "--stdio"], "p", "s")
    assert dl.target == {"adapter": "dogwood-local", "binary": "harness --stdio"}
    assert redis_sliding_log.engine("127.0.0.1:6379", 3, 60).target == \
        {"adapter": "redis-sliding-log", "address": "127.0.0.1:6379"}

    def launch(config):
        raise AssertionError("never launched")
    assert kong.launch_address(launch).startswith("launch:") and kong.launch_address(launch).endswith("launch")
    launch.address = "http://127.0.0.1:8000"
    assert kong.launch_address(launch) == "http://127.0.0.1:8000"
    for t in (eng.target, dl.target):
        assert S.is_target(t)


def test_the_freeze_refuses_without_scopes_and_writes_nothing(tmp_path):
    from kamanu.hunt import freeze as F
    rows = tmp_path / "profiles" / "rows"
    rows.mkdir(parents=True)
    row = hunt_row(Counted(), TEXT, ABOUT, scope=write_scope(scope_doc()))
    (rows / "a.json").write_text(json.dumps(row), encoding="utf-8")
    before = (rows / "a.json").read_bytes()
    made = []

    def engines(about, text):
        made.append(Counted())
        return made[-1]
    with pytest.raises(S.ScopeRefused):
        F.rebuild(tmp_path, engines)
    assert made[0].requests == 0 and (rows / "a.json").read_bytes() == before
    assert not (tmp_path / "evidence").exists() and not (tmp_path / "site").exists()
    rec = F.rebuild(tmp_path, engines, scopes=scopes)
    assert rec["rows"]["a.json"]["rerun"] and made[1].requests > 0


def test_the_judge_takes_the_engines_scope():
    from kamanu.ladder import calibrate as C
    pol = C.make_policy("request-sum", 100)
    eng = Counted()
    eng.p = Policy(pol["text"])
    with pytest.raises(S.ScopeRefused):
        C.judge(eng, pol, 1)
    assert eng.sessions == 0
    limit = 40
    rep = C.judge(eng, pol, 1, scope=write_scope(scope_doc(ceilings={"requests": limit, "money": BIG["money"]})))
    assert 0 < eng.requests <= limit
    assert sum(o["op"] == "issue" for s in rep["sessions"] for o in s) == eng.requests
    eng = Counted()
    eng.p = Policy(pol["text"])
    with pytest.raises(S.ScopeRefused):
        C.trial("label", pol, 1, engine=eng)
    assert C.trial("label", pol, 1, engine=eng, scope=scopes(eng))["sessions"]
