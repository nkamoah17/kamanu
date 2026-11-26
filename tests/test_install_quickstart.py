"""H11: the bundled Dogwood example, the reference adapter and the `kamanu` entry point."""
from __future__ import annotations

import io
import json
import tomllib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from kamanu import examples
from kamanu.hunt import PROFILES, Policy, hunt, pkey, predict
from kamanu.hunt import cli as hunt_cli
from kamanu.hunt.reference import PROFILES_DIR, ReferenceEngine, hunt_profile

ROOT = Path(__file__).resolve().parents[1]
DOGWOOD = {"reflexive": True, "deny_marks": ["request"]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = hunt_cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_example_files_ship_inside_the_package():
    policy, schema = examples.files("dogwood")
    pkg = Path(examples.__file__).resolve().parent
    assert policy.parent.parent == pkg and schema.parent.parent == pkg
    assert "appliesTo" in schema.read_text(encoding="utf-8")
    pol = Policy(policy.read_text(encoding="utf-8"))
    assert (pol.cap, pol.window, pol.tool, pol.namespace) == (100, 86400, "Pay", "Kamanu")


def test_bundled_profile_is_the_repository_profile():
    shipped = json.loads((PROFILES_DIR / "dogwood-1.1.1.json").read_text(encoding="utf-8"))
    repo = json.loads((ROOT / "profiles" / "dogwood-1.1.1.json").read_text(encoding="utf-8"))
    assert shipped == repo
    assert hunt_profile(shipped["constants"]) == DOGWOOD


def test_reference_engine_is_the_dogwood_profile_model():
    text = examples.files("dogwood")[0].read_text(encoding="utf-8")
    rep = hunt(ReferenceEngine(text), text)
    pol = Policy(text)
    plain = [s for s in rep["sessions"] if not any(o.get("moved") for o in s["ops"])]
    assert plain
    for s in plain:     # every session is what the dogwood-1.1.1 profile's model does
        scenario_ops = s["ops"]

        def replay(sess, ops=scenario_ops):
            for o in ops:
                if o["op"] == "issue":
                    sess.issue(o["amount"])
                elif o["op"] == "wait":
                    sess.wait(o["seconds"])
                else:
                    getattr(sess, o["op"])(o["call"])
        assert predict(DOGWOOD, pol, replay) == [{k: v for k, v in o.items() if k != "moved"}
                                                   for o in scenario_ops]
    assert pkey(DOGWOOD) in {pkey(p) for p in rep["remaining"]}
    assert all(p["reflexive"] and "request" in p["deny_marks"] for p in rep["remaining"])
    assert {"over-ask", "freeze"} <= {f["property"] for f in rep["findings"]}


def test_other_profiles_give_other_sessions():
    """The adapter's decisions depend on the profile: a non-reflexive one admits more."""
    text = examples.files("dogwood")[0].read_text(encoding="utf-8")
    pol = Policy(text)

    def overask(s):
        s.issue(60); s.settle(0); s.wait(1); s.issue(60); s.wait(1); s.issue(30)
    seen = {json.dumps(predict(p, pol, overask)) for p in PROFILES}
    assert len(seen) > 1


def test_kamanu_hunt_example_text():
    rc, out, err = run(["hunt", "--example", "dogwood"])
    assert rc == 0, err
    low = out.lower()
    assert "profile" in low and "probe" in low
    assert "over-ask" in low and "freeze" in low
    assert "confirmed findings: none" not in low


def test_kamanu_hunt_example_json():
    rc, out, err = run(["hunt", "--example", "dogwood", "--json"])
    assert rc == 0, err
    rep = json.loads(out)
    assert rep["adapter"] == "reference" and rep["example"] == "dogwood"
    assert rep["policy"] == {"cap": 100, "window_s": 86400, "action": "Pay"}
    for f in rep["findings"]:
        assert rep["sessions"][f["session"]]["purpose"] == "confirm"


def test_unknown_example_and_other_commands():
    assert run(["hunt", "--example", "nope"])[0] == 3
    rc, _, err = run([])
    assert rc == 3 and "usage" in err          # kamanu.cli's usage: everything else is unchanged
    rc, _, err = run(["hunt"])
    assert rc == 3                             # H1's hunt, which needs its own arguments


def test_dogwood_adapter_without_binary_is_an_error(monkeypatch):
    monkeypatch.delenv("DOGWOOD_BIN", raising=False)
    rc, _, err = run(["hunt", "--example", "dogwood", "--adapter", "dogwood"])
    assert rc == 3 and "DOGWOOD_BIN" in err


def test_pyproject_entry_point_and_package_data():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert cfg["project"]["scripts"]["kamanu"] == "kamanu.hunt.cli:main"
    data = cfg["tool"]["setuptools"]["package-data"]
    pkg = Path(examples.__file__).resolve().parent
    for pattern in data["kamanu.examples"]:
        assert list(pkg.glob(pattern))
    assert list(PROFILES_DIR.glob(data["kamanu.hunt"][0].split("/", 1)[1]))
