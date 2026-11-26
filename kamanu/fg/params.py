"""Continuous parameters (lag, clock skew) as intervals, never verdicts (F3).

A trace holds round-trip pings and write/visibility pairs:

    pings  [[t1, t2, t3, t4], ...]   t1, t4 on the client clock; t2, t3 on the engine clock
    writes [[w, v], ...]             w on the client clock; v on the engine clock

The engine clock reads the client clock plus `skew`. Each ping gives one offset sample
((t2 - t1) + (t3 - t4)) / 2, which is skew plus symmetric, noisy network delay; each write
gives v - w, which is skew + lag plus noise. Both noise scales are unknown, so:

    skew  Student-t interval on the mean of the ping offsets (n_p - 1 degrees of freedom);
    lag   Welch interval on mean(v - w) - mean(offsets), with Welch-Satterthwaite degrees
          of freedom, so the lag interval carries the skew estimate's uncertainty.

An interval is reported as an interval however narrow it is: no point value, no verdict.
The lag interval is clipped at 0 (true lag is positive) when that leaves it non-empty.
"""
from __future__ import annotations

import math

PARAMETERS = ("lag", "skew")
RECORD_NAMES = {"lag": "Lag", "skew": "Skew"}


# ---------------------------------------------------------------- Student t quantiles

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
           + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """P(T <= t) for Student's t with df > 0 degrees of freedom (df need not be whole)."""
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p: float, df: float) -> float:
    """The p-quantile of Student's t, for 0.5 <= p < 1, by bisection on t_cdf."""
    if not 0.5 <= p < 1.0:
        raise ValueError(f"p must be in [0.5, 1), got {p}")
    if not df > 0:
        raise ValueError(f"df must be positive, got {df}")
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * hi:
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------- estimation

def _mean_var(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    m = math.fsum(xs) / n
    return m, math.fsum((x - m) ** 2 for x in xs) / (n - 1)


def _floor(*scales: float) -> float:
    """The smallest half-width that is not rounding noise on these magnitudes."""
    return 64 * math.ulp(max(1.0, *(abs(s) for s in scales)))


def _check(trace: dict) -> tuple[list[list[float]], list[list[float]]]:
    if not isinstance(trace, dict):
        raise TypeError("trace must be a dict with 'pings' and 'writes'")
    pings, writes = trace.get("pings"), trace.get("writes")
    if not isinstance(pings, list) or not isinstance(writes, list):
        raise TypeError("trace needs lists 'pings' and 'writes'")
    if len(pings) < 2 or len(writes) < 2:
        raise ValueError("a trace needs at least two pings and two writes")
    for p in pings:
        if len(p) != 4 or not all(math.isfinite(float(x)) for x in p):
            raise ValueError(f"ping {p!r} is not four finite times")
    for w in writes:
        if len(w) != 2 or not all(math.isfinite(float(x)) for x in w):
            raise ValueError(f"write {w!r} is not two finite times")
    return pings, writes


def _interval(low: float, high: float, level: float) -> dict:
    return {"low": float(low), "high": float(high), "level": level, "status": "interval"}


def estimate(trace: dict, level: float = 0.9) -> dict:
    """{"lag": interval, "skew": interval} at the given confidence level."""
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level}")
    pings, writes = _check(trace)
    p = 0.5 + level / 2.0
    times = [float(x) for row in pings + writes for x in row]
    floor = _floor(*times)

    offsets = [((float(t2) - float(t1)) + (float(t3) - float(t4))) / 2.0
               for t1, t2, t3, t4 in pings]
    gaps = [float(v) - float(w) for w, v in writes]
    n_o, n_g = len(offsets), len(gaps)
    m_o, v_o = _mean_var(offsets)
    m_g, v_g = _mean_var(gaps)

    se_o2 = v_o / n_o
    se_g2 = v_g / n_g

    skew_hw = max(t_quantile(p, n_o - 1) * math.sqrt(se_o2), floor)

    se_l2 = se_o2 + se_g2
    if se_l2 > 0:
        df = se_l2 ** 2 / ((se_o2 ** 2) / (n_o - 1) + (se_g2 ** 2) / (n_g - 1))
        df = max(df, float(min(n_o, n_g) - 1))
        lag_hw = t_quantile(p, df) * math.sqrt(se_l2)
    else:
        lag_hw = 0.0
    lag_hw = max(lag_hw, floor)

    lag_c = m_g - m_o
    lag_lo, lag_hi = lag_c - lag_hw, lag_c + lag_hw
    if lag_hi > 0.0:
        lag_lo = max(lag_lo, 0.0)

    return {"lag": _interval(lag_lo, lag_hi, level),
            "skew": _interval(m_o - skew_hw, m_o + skew_hw, level)}


def record(estimates: dict) -> dict:
    """The estimates in the shape of a profile record: interval entries, never values."""
    out = {}
    for k, name in RECORD_NAMES.items():
        iv = estimates[k]
        out[name] = {"status": "interval", "value": None,
                     "interval": [iv["low"], iv["high"]], "level": iv["level"]}
    return out
