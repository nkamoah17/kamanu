"""exonumia.sprint (X16): the Authorization Assurance Sprint as one command.

    python -m exonumia.sprint run --scope FILE --handler TARGET --out DIR [--trials N] [--seed S] [--key K]
                                  [--live FILE] [--cabinet DIR]
    python -m exonumia.sprint verify DIR --key PUBLIC

One authorization path, three parts kept apart:

    Model        `kamanu scan --card` on the scope's card profile, once per limit (the limit's amount as the face):
                 Sound and Tight with their levels, every constant measured or assumed, Tight's trace, and which
                 window each limit has. A receipt per limit goes into the cabinet.
    Measurement  the battery: eight families of seeded processor scripts played against the handler on a simulated
                 processor with its own clock, every event through exonumia.ledger (the journal, as X11's shadow
                 mode takes it: the processor's events and the handler's teed answers), and the figures read from
                 `python -m exonumia.ledger report --json --orders` of each family's journal. Every figure is a count
                 of this run, TESTED.
    Deployment   the scope beside a live configuration (--live), field by field; without one, nothing connects the
                 tested configuration to a live one.

The processor is simulated: nothing here is a statement about a processor's system. This package never holds,
moves or issues money and speaks to no payment rail (rule E6): a URL handler is the program's own endpoint, sent
simulated events signed with the scope's test signing secret.

The handler (TARGET):
    module:Name   Name(limits) with the ledger's limits; .authorize(request) -> {"approved": bool}, request a port
                  request event, called from up to K threads at once; .observe(event) for every outcome, reverse,
                  expire, capture and refund the processor records, in the processor's order.
    http(s)://... each ask POSTed as an issuing_authorization.request event in the shape of Stripe's (signed with
                  the scope's signing_secret in a Stripe-Signature header); the answer is the response's "approved".

Trial ids: every event of trial n of family f has an authorization id (or, with none, an id) "f/n/...". Trials share
no bucket: each has its own cardholder and cards.
"""
from __future__ import annotations

FORMAT = "sprint-v1"
REPORT = "sprint-report-v1"
FAMILIES = [
    ("single", "single asks below, at and above the limit"),
    ("parallel", "parallel asks"),
    ("cards", "several cards under one cardholder"),
    ("partial_capture", "authorization then partial capture"),
    ("over_capture", "capture above the hold, then reversal"),
    ("timeout", "time-out with an ambiguous outcome, then retry"),
    ("reset", "reset at the interval's boundary"),
    ("expiry", "an uncaptured hold that expires, and two limits on one purchase"),
]
KEYS = [k for k, _ in FAMILIES]
WORDS = dict(FAMILIES)
RACY = ("parallel", "cards", "timeout")        # a family with a race runs N trials
POSITIONS = ("below", "at", "above")            # the others run once per amount position
DEFAULT_TRIALS = 99                             # trials_for(0.03, 0.05)
DEFAULT_K = 8
DEFAULT_SEED = 1
MISSED_AT_MOST = 5                              # q, percent
CALENDAR = ("daily", "weekly", "monthly", "yearly")
INTERVALS = ("per_authorization", "daily", "weekly", "monthly", "yearly", "all_time")

SIMULATED = "the processor was simulated"
NOT_A_STATEMENT = "nothing here is a statement about a processor's system"
NOTHING_CONNECTS = "nothing connects the tested configuration to a live one"


def trials_for(family: str, n: int) -> int:
    return n if family in RACY else len(POSITIONS)


def rate(n: int) -> float:
    """p in percent, one decimal, rounded up: the least rate of a race that n clean trials miss with probability at
    most q = 5% ((1 - p)^n <= 0.05)."""
    import math
    p = 1 - (MISSED_AT_MOST / 100) ** (1 / n)
    return math.ceil(p * 1000 - 1e-9) / 10


def sentence(n: int) -> str:
    """What n clean trials say, computed from n."""
    return (f"{n} clean trials bound how often a race can occur and do not show that it cannot; a race that occurs "
            f"{rate(n):.1f}% of the time or more would be missed with probability at most {MISSED_AT_MOST}%; a rarer "
            f"one can still be there.")


def trial_of(event: dict):
    """(family, trial) of an event: its authorization id, or its own id less a "tee:", read as <family>/<n>/..."""
    s = event.get("auth") or event.get("id") or ""
    if s.startswith("tee:"):
        s = s[4:]
    parts = s.split("/")
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1])
