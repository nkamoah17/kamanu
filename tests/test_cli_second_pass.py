"""kamanu.cli second pass (P1d): policy reading, the request-sum test, the printed notes. No TLC."""
from pathlib import Path

from kamanu import cli

ROOT = Path(__file__).resolve().parent.parent
ACT4 = ROOT / "demo3" / "policies" / "act4"


def text(name, window="24h"):
    return (ACT4 / f"{name}-24h.dw").read_text(encoding="utf-8").replace("within 24h", f"within {window}")


def test_a_narrow_window_is_read():
    permit, window, lossy = cli.read_policy(text("request-sum", "1h"))
    assert lossy == [] and window == 3600
    permit, window, lossy = cli.read_policy(text("request-sum"))
    assert lossy == [] and window is None


def test_two_windows_are_lossy():
    t = text("requests-minus-errors").replace("within 24h", "within 1m", 1).replace("within 24h", "within 2m", 1)
    _, window, lossy = cli.read_policy(t)
    assert window is None and lossy and "different lengths" in lossy[0]["reason"]


def test_other_lossy_constructs_stay_lossy():
    u = (ROOT / "fixtures" / "dogwood" / "U2_since.dw").read_text(encoding="utf-8")
    _, _, lossy = cli.read_policy(u)
    assert lossy


def test_request_sum_shape():
    for name, want in (("request-sum", True), ("settled-plus-current", False), ("requests-minus-errors", False)):
        for window in ("24h", "1m"):
            permit, _, _ = cli.read_policy(text(name, window))
            assert cli.request_sum_cap(permit, 100) is want, (name, window)
    permit, _, _ = cli.read_policy(text("request-sum"))
    assert cli.request_sum_cap(permit, 99) is False          # the cap must be the policy's own


def test_fixture_request_sums():
    for name, want in (("PReqBasis", True), ("PRespBasis", False), ("PRefundOnError", False)):
        permit, _, _ = cli.read_policy((ROOT / "fixtures" / "dogwood" / f"{name}.dw").read_text(encoding="utf-8"))
        assert cli.request_sum_cap(permit, 100) is want, name


def test_undetermined_points_at_k6():
    s = cli.unmodelled_text([{"outcome": "UNDETERMINED", "code": -32005, "note": "long"}, "other"])
    assert "-32005" in s and "K6" in s and "long" not in s and s.endswith("other")


def test_scope_key():
    assert "not a budget" in cli.scope_key({"profile": {"Scope": "ScopeSession"}})
    assert cli.scope_key({"profile": {"Scope": "ScopeGlobal"}}).startswith("ScopeGlobal")


def test_marks_text():
    dm = {"request": "INVARIANT", "request+error": "INVARIANT", cli.FRESH_MARKS: "PASS"}
    s = cli.marks_text(dm)
    assert "if a denial also writes an error event: INVARIANT" in s and "PASS if" in s
