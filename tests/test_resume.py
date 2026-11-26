"""Checkpointed runs (card X9): exonumia.rails.journal on a toy rail. A run killed between pieces,
inside a piece and during a resume's cleanup, then resumed, gives the uncut run's record; a journal
of another day, scope, adapter or seed, or whose pieces overlap, is refused and left as it was."""
import json
import subprocess
import sys

import pytest

from exonumia.rails import journal as JN

SECRET = "0xAbCdEf0123456789aBcDeF0123456789AbCdEf01"


class Refused(Exception):
    def __init__(self, reason, text):
        super().__init__(f"refused ({reason}): {text}")
        self.reason = reason


class Killed(BaseException):
    pass


class Service:
    """A toy rail: charges with ids, a clock, holds that stay open until released."""

    def __init__(self):
        self.t, self.n, self.held, self.charges = 1000.0, 0, [], []
        self.private = [SECRET]

    def now(self):
        return self.t

    def advance(self, s):
        self.t += s

    def charge(self, amount, hold=False):
        self.t += 1
        self.n += 1
        cid = f"c{self.n}"
        self.charges.append((cid, amount))
        if hold:
            self.held.append(cid)
        return {"id": cid, "ok": amount <= 50, "from": SECRET}

    def release(self, cid):
        self.held.remove(cid)

    def holds(self):
        return list(self.held)


class Cut:
    """The service, with the process killed at its k-th charge or release (before it is done)."""

    def __init__(self, svc, at=None):
        self.svc, self.at, self.k, self.dead = svc, at, 0, False

    def __getattr__(self, name):
        v = getattr(self.svc, name)
        if name not in ("charge", "release"):
            return v

        def call(*a, **kw):
            if self.dead:
                raise Killed()
            self.k += 1
            if self.at is not None and self.k == self.at:
                self.dead = True
                raise Killed()
            return v(*a, **kw)
        return call


class Engine:
    def __init__(self, port):
        self.port, self.sessions, self.money = port, [], 0

    def new(self, test):
        JN.boundary(self)
        s = {"id": f"{test}-{len(self.sessions)}", "test": test, "charges": []}
        self.sessions.append(s)
        return s

    def pay(self, s, amount, hold=False):
        if self.money + amount > self.doc_money:
            raise Refused("ceiling", "past ceilings.money")
        self.money += amount
        r = self.port.charge(amount, hold)
        s["charges"].append({"amount": amount, "ok": r["ok"], "id": r["id"], "from": r["from"]})
        if hold:
            self.port.release(r["id"])


def redact(text, private):
    for p in private:
        text = text.replace(p, "<REDACTED>").replace(p.lower(), "<REDACTED>")
    return text


def cleanup(port, note):
    for cid in port.holds():
        port.release(cid)
        note({"released": cid})


def body(scope, j, out, money):
    e = Engine(j.port)
    e.doc_money = money
    j.begin(e)
    for i in range(6):
        s = e.new("trial")
        for a in (10, 20 + i, 60):
            e.pay(s, a, hold=(a == 60))
    j.boundary()
    lp = out / "evidence" / "rails" / "toy" / j.day / "run.json"
    lp.write_text(redact(json.dumps({"date": JN.stamp(j.start), "sessions": [dict(s) for s in e.sessions]}),
                         [SECRET]), encoding="utf-8")
    return {"run": str(lp)}


def run(scope, port, out, resume=False, money=10 ** 6, adapter="toy-1", seed=7):
    return JN.journaled_run(lambda j: body(scope, j, out, money), rail="toy", version=adapter, scope=scope,
                            port=port, out=out, evidence="evidence/rails/toy", seed=seed, resume=resume,
                            refused=Refused, private=[SECRET], export=lambda s: s, redact=redact,
                            record=("charge", "release", "now", "advance"), cleanup=cleanup)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def segment(svc, scope, out, at, resume):
    port = Cut(svc, at)
    try:
        run(scope, port, out, resume=resume)
        return "done"
    except Killed:
        return "killed"


@pytest.fixture
def scope(tmp_path):
    p = tmp_path / "scope.json"
    p.write_text('{"toy": true}', encoding="utf-8")
    return p


def projected(out):
    lp = next(out.glob("evidence/rails/toy/*/run.json"))
    return [[(c["amount"], c["ok"]) for c in s["charges"]] for s in json.loads(lp.read_text())["sessions"]]


def uncut(tmp_path, scope):
    out = tmp_path / "uncut"
    out.mkdir()
    assert segment(Service(), scope, out, None, False) == "done"
    return out


def test_uncut_writes_one_segment_and_the_pieces(tmp_path, scope):
    out = uncut(tmp_path, scope)
    d = next(out.glob("evidence/rails/toy/*"))
    segs = json.loads((d / "segments.json").read_text())["segments"]
    assert len(segs) == 1 and segs[0]["before"] is None and segs[0]["cleanup"] == []
    lines, _ = JN.read_lines(d / "run.journal.jsonl")
    pieces = [o for o in lines if "piece" in o]
    run_ = json.loads((d / "run.json").read_text())
    assert [s for p in pieces for s in p["sessions"]] == run_["sessions"]
    text = (d / "run.journal.jsonl").read_text()
    assert SECRET[2:].lower() not in text.lower()


@pytest.mark.parametrize("cuts", [(5,), (4, 1), (9, 2, 7), (17,)])
def test_killed_and_resumed_gives_the_uncut_record(tmp_path, scope, cuts):
    want = projected(uncut(tmp_path, scope))
    out = tmp_path / "cut"
    out.mkdir()
    svc = Service()
    outcomes = []
    for i, at in enumerate(list(cuts) + [None]):
        outcomes.append(segment(svc, scope, out, at, resume=i > 0))
        if outcomes[-1] == "killed" and i == 0:
            jp = next(out.glob("evidence/rails/toy/*/run.journal.jsonl"))
            with open(jp, "ab") as f:
                f.write(b'{"piece": 99, "start": 1')         # a power cut mid-line
    assert outcomes == ["killed"] * len(cuts) + ["done"]
    assert projected(out) == want
    d = next(out.glob("evidence/rails/toy/*"))
    segs = json.loads((d / "segments.json").read_text())["segments"]
    assert len(segs) == len(cuts) + 1
    assert all(s["before"] == JN.KILLED for s in segs[1:])
    assert not svc.held, "a hold the cut piece left open was never released"
    released = [c["released"] for s in segs for c in s["cleanup"]]
    assert len(released) == len(set(released))
    ids = {c["id"] for s in json.loads((d / "run.json").read_text())["sessions"] for c in s["charges"]}
    assert not (set(released) & ids), "a charge of a cut piece is in the record"


@pytest.mark.parametrize("slack,ends", [(-1, "refused"), (0, "done")])
def test_money_counts_what_lost_segments_asked(tmp_path, scope, slack, ends):
    """Killed at its 5th call (the second piece's first charge, 10, asked and never journaled): the
    resumed run asks the uncut run's 555 again, and the lost 10 counts too."""
    out = tmp_path / "m"
    out.mkdir()
    svc = Service()
    assert segment(svc, scope, out, 5, False) == "killed"
    try:
        run(scope, svc, out, resume=True, money=555 + 10 + slack)
        got = "done"
    except Refused as e:
        got = "refused" if e.reason == "ceiling" else str(e)
    assert got == ends


@pytest.mark.parametrize("change", ["day", "adapter", "seed", "twice", "clock", "scope"])
def test_a_foreign_journal_is_refused_and_left_alone(tmp_path, scope, change):
    out = tmp_path / "t"
    out.mkdir()
    svc = Service()
    assert segment(svc, scope, out, 13, False) == "killed"
    jp = next(out.glob("evidence/rails/toy/*/run.journal.jsonl"))
    raw = jp.read_bytes().split(b"\n")
    objs = [json.loads(r) if r.strip() else None for r in raw]
    kw = {}
    if change == "day":
        objs[0]["day"] = "2000-01-01"
    elif change == "adapter":
        kw["adapter"] = "toy-2"
    elif change == "seed":
        kw["seed"] = 8
    elif change == "scope":
        scope.write_text('{"toy": false}', encoding="utf-8")
    ks = [i for i, o in enumerate(objs) if o and "piece" in o]
    if change == "twice":
        objs.insert(len(objs) - 1, objs[ks[-1]])
    elif change == "clock":
        objs[ks[-1]]["start"] -= 3600
        objs[ks[-1]]["end"] -= 3600
    jp.write_bytes(b"\n".join(json.dumps(o).encode() if o else b"" for o in objs))
    before, n = jp.read_bytes(), len(svc.charges)
    with pytest.raises(Refused) as e:
        run(scope, svc, out, resume=True, **kw)
    assert e.value.reason == "journal"
    assert jp.read_bytes() == before and len(svc.charges) == n
    assert not list(out.glob("evidence/rails/toy/*/run.json"))


def test_private_values_round_trip_as_placeholders(tmp_path, scope):
    j = JN.Journal(rail="toy", version="toy-1", scope=scope, port=Service(), out=tmp_path, evidence="e", seed=1,
                   resume=False, refused=Refused, private=[SECRET], export=lambda s: s, redact=redact,
                   record=(), cleanup=cleanup)
    for form in (SECRET, SECRET.lower(), SECRET.upper(), SECRET[2:]):
        hidden = j._hide(json.dumps({"x": form}))
        assert SECRET[2:].lower() not in hidden.lower()
        assert json.loads(j._show(hidden))["x"] == form


def test_dead_asks_count_only_lost_pieces():
    lines = [{"segment": 0}, {"asked": 5, "of_piece": 0}, {"piece": 0}, {"asked": 7, "of_piece": 1},
             {"segment": 1}, {"asked": 7, "of_piece": 1}, {"piece": 1}, {"asked": 3, "of_piece": 2},
             {"segment": 2}]
    assert JN.dead_asks(lines) == 7 + 3


def test_hunt_help_names_resume():
    p = subprocess.run([sys.executable, "-m", "exonumia.rails", "hunt", "--help"], capture_output=True, text=True)
    assert p.returncode == 0 and "--resume" in p.stdout
