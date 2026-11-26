"""Unit tests for kamanu.hunt.matrix (H10; R2's rules L3 and L4: no bare pass)."""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.hunt import matrix as M

ROOT = Path(__file__).resolve().parents[1]
ROWS = sorted((ROOT / "profiles" / "rows").glob("*.json"))


def _rows():
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in ROWS}


def _first_tested(row):
    return next(t for t in M.TESTS if row["cells"][t]["verdict"] in M.TESTED)


def _tested_row():
    """The first committed row with a tested cell (a row the freeze could not re-run has none)."""
    return next((n, r) for n, r in _rows().items() if any(r["cells"][t]["verdict"] in M.TESTED for t in M.TESTS))


def _withdrawn(cell):
    """A cell the freeze (H15) withdrew: untested, with the freeze's diff."""
    return cell["verdict"] == "untested" and isinstance(cell.get("diff"), dict)


def _known(row):
    return row["profile"]["window_kind"]["value"] != "unknown"


def test_committed_rows_all_traced():
    """Every committed row with a known window is fully traced. A row whose window is unknown
    (H4 (6): no sliding and no fixed window fits) has every cell untested, which is its honest
    result, and no trace files."""
    rows = _rows()
    twin, files = M.matrix(rows)
    assert len(twin["rows"]) == len(ROWS)
    traced = 0
    for n, r in rows.items():
        cells = [r["cells"][t] for t in M.TESTS]
        if not _known(r):
            assert all(c["verdict"] == "untested" for c in cells), n
        else:
            assert all(c["verdict"] in M.TESTED or _withdrawn(c) for c in cells), n
        traced += all(c["verdict"] in M.TESTED for c in cells)
    assert twin["traced"] == traced
    assert len(files) == sum(r["cells"][t]["verdict"] in M.TESTED for r in rows.values() for t in M.TESTS)


def test_committed_site_is_regenerated(tmp_path):
    (tmp_path / "profiles" / "rows").mkdir(parents=True)
    for p in ROWS:
        (tmp_path / "profiles" / "rows" / p.name).write_bytes(p.read_bytes())
    M.build(tmp_path, tmp_path / "site")
    fresh = {p.relative_to(tmp_path / "site").as_posix(): p.read_bytes()
             for p in (tmp_path / "site").rglob("*") if p.is_file()}
    old = {p.relative_to(ROOT / "site").as_posix(): p.read_bytes().replace(b"\r\n", b"\n")
           for p in (ROOT / "site").rglob("*") if p.is_file()}
    assert fresh == old


def test_tampered_cell_is_untested_others_kept():
    name, row = _tested_row()
    t = _first_tested(row)
    row["cells"][t]["verdict"] = "passes" if row["cells"][t]["verdict"] == "fails" else "fails"
    twin, _ = M.matrix({name: row})
    cells = twin["rows"][0]["cells"]
    assert cells[t]["verdict"] == "untested" and cells[t]["trace"] is None and cells[t]["reason"]
    for x in M.TESTS:
        if x != t:
            rec = row["cells"][x]["verdict"]
            want = M.rendered(row["cells"][x]) if rec == "passes" else rec
            assert cells[x]["verdict"] == want
    assert twin["traced"] == 0


def _passing():
    """A committed row with a recorded passes cell (witnessed or not: R6 re-records rows with
    R2's witness and neighbour fields)."""
    for n, r in _rows().items():
        for t in M.TESTS:
            if r["cells"][t]["verdict"] == "passes" and not M.cell_problems(r, t):
                return n, r, t
    raise AssertionError("no committed row with a valid passes cell")


def test_pass_without_witness_is_unwitnessed_and_linked():
    """Rule L3: a passes cell without a witness renders unwitnessed, never passes, and keeps its
    trace. Every cell of the row loses its witness and neighbour (a row recorded before R2), so
    no cell of it may render passes; the row's other passes cells may carry witnesses since R6."""
    name, row, t = _passing()
    for x in M.TESTS:
        for k in ("witness", "neighbour"):
            row["cells"][x].pop(k, None)
    twin, files = M.matrix({name: row})
    c = twin["rows"][0]["cells"][t]
    assert c["verdict"] == "unwitnessed" and c["recorded"] == "passes"
    assert c["trace"] in files and c["witness"] is None and c["neighbour"] is None
    for x in M.TESTS:
        if row["cells"][x]["verdict"] == "passes":
            assert twin["rows"][0]["cells"][x]["verdict"] == "unwitnessed", x
    html = M.render_html(twin)
    assert 'data-verdict="unwitnessed"' in html and 'data-verdict="passes"' not in html


def test_witness_and_neighbour_words():
    """passes with an exercised witness and a neighbour; not exercised (rule L4); a witness
    without a neighbour is still unwitnessed. Every cell carries both fields."""
    name, row, t = _passing()
    cases = [({"exercised": True, "trace": row["cells"][t]["trace"]},
              {"text": "no failing neighbour within one step"}, "passes"),
             ({"exercised": True, "trace": row["cells"][t]["trace"]},
              {"coordinate": "window_kind", "engine": "other"}, "passes"),
             ({"exercised": False}, {"text": "no failing neighbour within one step"}, "not exercised"),
             ({"exercised": True, "trace": row["cells"][t]["trace"]}, None, "unwitnessed")]
    for w, n, want in cases:
        r = json.loads(json.dumps(row))
        r["cells"][t]["witness"] = w
        if n is None:
            r["cells"][t].pop("neighbour", None)
        else:
            r["cells"][t]["neighbour"] = n
        twin, _ = M.matrix({name: r})
        c = twin["rows"][0]["cells"][t]
        assert c["verdict"] == want, (w, n, c["verdict"])
        assert c["witness"] == w and c["neighbour"] == n
        assert c["trace"] is not None
        for x in M.TESTS:
            assert "witness" in twin["rows"][0]["cells"][x] and "neighbour" in twin["rows"][0]["cells"][x]


def test_committed_site_has_no_bare_pass():
    twin = json.loads((ROOT / "site" / "matrix.json").read_text(encoding="utf-8"))
    for r in twin["rows"]:
        for t, c in r["cells"].items():
            assert "witness" in c and "neighbour" in c
            if c["verdict"] == "passes":
                assert (c["witness"] or {}).get("exercised") is True and isinstance(c["neighbour"], dict)


def test_removed_trace_and_wrong_version_are_untested():
    for how in ("trace", "version"):
        name, row = _tested_row()
        t = _first_tested(row)
        if how == "trace":
            del row["cells"][t]["trace"]
        else:
            row["cells"][t]["version"] += ".1"
        twin, _ = M.matrix({name: row})
        assert twin["rows"][0]["cells"][t]["verdict"] == "untested"


def test_duplicate_shows_later():
    name, row = next(iter(_rows().items()))
    later = json.loads(json.dumps(row))
    later["date"] = "2099-01-01T00:00:00Z"
    for t in M.TESTS:
        later["cells"][t]["date"] = later["date"]
    twin, _ = M.matrix({"a.json": later, "b.json": row})
    assert len(twin["rows"]) == 1 and twin["rows"][0]["date"] == later["date"]


def test_check_writes_nothing(tmp_path, capsys, monkeypatch):
    (tmp_path / "profiles" / "rows").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert M.main(["--check"]) == 0
    assert capsys.readouterr().out.strip() == "rows with every cell traced: 0"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["profiles"]
