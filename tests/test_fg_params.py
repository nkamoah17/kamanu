"""Unit tests for kamanu/fg/params.py (F3): lag and skew as intervals, never verdicts."""
from __future__ import annotations

import math
import random

import pytest

from kamanu.fg import params as P


def make_trace(rng, n_p, n_w, lag, skew, sd, sw, delay=0.05):
    pings, writes, t = [], [], 100.0
    for _ in range(n_p):
        t += rng.uniform(0.5, 2.0)
        t2 = t + skew + rng.gauss(delay, sd)
        t3 = t2 + rng.uniform(0, 0.1)
        pings.append([t, t2, t3, t3 - skew + rng.gauss(delay, sd)])
    for _ in range(n_w):
        t += rng.uniform(0.5, 2.0)
        writes.append([t, t + skew + lag + rng.gauss(0, sw)])
    return {"pings": pings, "writes": writes}


@pytest.mark.parametrize("p,df,want", [(0.95, 1, 6.3138), (0.95, 10, 1.8125),
                                       (0.975, 5, 2.5706), (0.95, 1e7, 1.6449)])
def test_t_quantile(p, df, want):
    assert P.t_quantile(p, df) == pytest.approx(want, abs=1e-4)


def test_shape_is_an_interval_never_a_verdict():
    est = P.estimate(make_trace(random.Random(1), 5, 5, 0.3, 0.7, 0.01, 0.01))
    assert set(est) == {"lag", "skew"}
    for iv in est.values():
        assert set(iv) == {"low", "high", "level", "status"}
        assert iv["status"] == "interval" and iv["level"] == 0.9
        assert math.isfinite(iv["low"]) and iv["low"] < iv["high"]
    rec = P.record(est)
    assert set(rec) == {"Lag", "Skew"}
    for k, name in (("lag", "Lag"), ("skew", "Skew")):
        assert rec[name] == {"status": "interval", "value": None,
                             "interval": [est[k]["low"], est[k]["high"]], "level": 0.9}


def test_noise_free_trace_is_still_an_interval():
    tr = make_trace(random.Random(2), 3, 3, 0.25, -0.75, 0.0, 0.0)
    est = P.estimate(tr)
    for k, true in (("lag", 0.25), ("skew", -0.75)):
        lo, hi = est[k]["low"], est[k]["high"]
        assert lo < hi and hi - lo < 1e-9 and lo - 1e-9 < true < hi + 1e-9


def test_lag_clipped_at_zero_but_never_a_point():
    est = P.estimate(make_trace(random.Random(3), 2, 2, 0.001, 0.0, 0.2, 0.2))
    assert est["lag"]["low"] >= 0.0 and est["lag"]["low"] < est["lag"]["high"]


def test_level_is_honoured():
    tr = make_trace(random.Random(4), 6, 6, 0.5, 0.1, 0.05, 0.05)
    w90 = P.estimate(tr)["skew"]
    w99 = P.estimate(tr, level=0.99)["skew"]
    assert w99["level"] == 0.99
    assert w99["high"] - w99["low"] > w90["high"] - w90["low"]


def test_too_few_observations_raise():
    tr = make_trace(random.Random(5), 1, 3, 0.5, 0.1, 0.05, 0.05)
    with pytest.raises(ValueError):
        P.estimate(tr)


@pytest.mark.parametrize("n", [2, 10])
def test_coverage_near_nominal(n):
    rng = random.Random(f"cov{n}")
    hits = {"lag": 0, "skew": 0}
    trials = 2000
    for _ in range(trials):
        lag, skew = rng.uniform(0.01, 2), rng.uniform(-2, 2)
        sd, sw = 10 ** rng.uniform(-6, -0.5), 10 ** rng.uniform(-6, -0.5)
        est = P.estimate(make_trace(rng, n, n, lag, skew, sd, sw))
        for k, true in (("lag", lag), ("skew", skew)):
            hits[k] += est[k]["low"] <= true <= est[k]["high"]
    for k, h in hits.items():
        assert 0.86 <= h / trials <= 0.95, (k, h / trials)
