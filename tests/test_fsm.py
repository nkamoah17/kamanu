"""Own tests for kamanu.evidence.fsm: extraction shapes, refusals, and agreement."""
import hashlib
import textwrap

import pytest

from kamanu.evidence.fsm import agree, extract, live_labels

CFG = {"MaxReq": 2, "MaxFails": 1, "Cap": 100, "Faults": {"clean"}, "HasReconcile": False,
       "Reflexive": True, "DenyRecord": "deny", "Atomic": True, "Lag": 0,
       "Templates": [{"tool": "pay", "amt": 60, "key": "s1"}], "Permit": "PReqBasis",
       "Scope": "ScopeSession", "GoalTemplate": {"tool": "pay", "amt": 60, "key": "s1"},
       "NeedsApproval": False, "ApproverFair": False, "AgentFair": False, "HasTimeout": True,
       "MaskDeadlock": False}


def write(tmp_path, src, name="h.py"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src), encoding="utf-8")
    return p


def triples(m):
    return [(t["from"], t["event"], t["to"], t["line"]) for t in m["transitions"]]


NESTED = '''\
def go(src):
    where = "a"
    while where not in ("z",):
        what = src.next()
        if where == "a":
            if what == "x":
                for i in range(3):
                    if i:
                        break
                where = "b"
            elif what == "y":
                where = "z"
        elif "b" == where:
            if what == "x":
                where = "z"
    return where
'''


def test_nested_shape_and_inner_break(tmp_path):
    p = write(tmp_path, NESTED)
    m = extract(p)
    assert triples(m) == [("a", "x", "b", 10), ("a", "y", "z", 12), ("b", "x", "z", 15)]
    assert m["start"] == "a" and m["terminal"] == ["z"] and m["states"] == ["a", "b", "z"]
    assert m["source_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_match_on_state_then_event(tmp_path):
    p = write(tmp_path, '''\
        END = {"z"}
        async def go(src):
            s = "a"
            while s not in END:
                e = await src.next()
                match s:
                    case "a":
                        match e:
                            case "x":
                                s = "z"
                            case _:
                                pass
                    case _:
                        pass
        ''')
    assert triples(extract(p)) == [("a", "x", "z", 10)]


def test_table_repeated_key_reads_both(tmp_path):
    p = write(tmp_path, '''\
        T = {
            ("a", "x"): "b",
            ("a", "x"): "c",
        }
        def go(src):
            s = "a"
            while s != "c":
                e = src.next()
                s = T.get((s, e), s)
        ''')
    assert triples(extract(p)) == [("a", "x", "b", 2), ("a", "x", "c", 3)]


@pytest.mark.parametrize("old,new", [
    ('                where = "b"\n', '                where = "b"\n                return 1\n'),
    ('        what = src.next()\n', '        what = src.next()\n        where = "b"\n'),
    ('                where = "b"\n', '                where = what\n'),
    ('            elif what == "y":\n                where = "z"\n',
     '            else:\n                where = "z"\n'),
    ('    where = "a"\n', '    where = "a"\n    def f():\n        nonlocal where\n'),
    ('                        break\n', '                        pass\n                break\n'),
])
def test_refusals(tmp_path, old, new):
    assert NESTED.count(old) == 1
    p = write(tmp_path, NESTED.replace(old, new))
    with pytest.raises(ValueError):
        extract(p)


def mach(rows, start, terminal):
    trans = [dict(zip(("from", "event", "to"), r.split()), line=1) for r in rows]
    return {"start": start, "terminal": terminal, "transitions": trans}


def keys(found):
    return {(d["direction"], d.get("from"), d.get("event"), d.get("to"), d.get("action"))
            for d in found}


def test_agree_clean_and_cuts():
    rows = ["r w b", "b ok g", "b no r", "b deny r", "g end d", "r late e", "e end d"]
    man = {"w": "Work", "ok": "Succeed", "no": "Fail", "deny": "Deny", "end": "Finish",
           "late": "Timeout"}
    assert agree(mach(rows, "r", ["d"]), man, CFG) == []
    assert live_labels(CFG) == {"Work", "Timeout", "Finish", "Succeed", "Fail", "Deny"}
    # an event the manifest forgot, and the only Fail carrier cut. With no retry after a failure
    # the second request, which the policy denies, never comes: the deny branch waits for nothing.
    got = keys(agree(mach(rows, "r", ["d"]), {k: v for k, v in man.items() if k != "no"}, CFG))
    assert got == {("code_only", "b", "no", "r", None), ("model_only", None, None, None, "Fail"),
                   ("code_only", "b", "deny", "r", None)}


def test_timeout_twice_is_not_the_models():
    rows = ["r w b", "b ok g", "b no r", "b deny r", "g end d", "r late e", "e late2 f"]
    man = {"w": "Work", "ok": "Succeed", "no": "Fail", "deny": "Deny", "end": "Finish",
           "late": "Timeout", "late2": "Timeout"}
    assert keys(agree(mach(rows, "r", ["d", "f"]), man, CFG)) == {
        ("code_only", "e", "late2", "f", None)}


def test_agree_refuses_unknown_label_and_is_pure():
    m = mach(["r w b"], "r", ["b"])
    with pytest.raises(ValueError):
        agree(m, {"w": "Issue"}, CFG)
    before = repr(m)
    agree(m, {"w": "Work"}, CFG)
    assert repr(m) == before
