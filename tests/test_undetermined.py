"""The Undetermined extension (K6): a refusal to decide, only under contention."""
from pathlib import Path

import pytest

from kamanu.unbounded import run

EXT = Path(__file__).resolve().parent.parent / "spec" / "ext"

BASE = """SPECIFICATION USpec
CONSTANTS
  MaxReq = 3
  MaxFails = 0
  Cap = 100
  Faults = {}
  HasReconcile = FALSE
  Reflexive = TRUE
  DenyRecord = "none"
  Atomic = TRUE
  Lag = 0
  Templates <- TOne
  Permit <- PReqBasis
  Scope <- ScopeGlobal
  RefuseRecord = %s
  InFlightGuard = TRUE
INVARIANTS TypeOK UTypeOK RealSpendOK
CHECK_DEADLOCK FALSE
"""


@pytest.mark.parametrize("rr", ["TRUE", "FALSE"])
def test_safety_harness_with_refusals_is_safe_and_typed(rr):
    r = run("UndeterminedSafety", BASE % rr)
    assert r["status"] == "PASS", r


def test_modules_say_what_they_add():
    text = (EXT / "Undetermined.tla").read_text(encoding="utf-8")
    assert "InFlightGuard => Contended(i)" in text
    assert "RefuseRecord" in text
