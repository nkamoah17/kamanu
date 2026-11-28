"""`kamanu scan --example` (X27): the examples bundled in the package, and the scan's plain words.

What is held here:
  the copies     each budget file under kamanu/examples/scan/ is byte for byte (CRLF read as LF) the tree's file it
                 comes from: change either and this fails
  the card       the per-charge example is a Stripe Card object whose id is plainly an example's and whose only
                 limits are per_authorization
  the scan       `--example NAME` answers as the scan of its files by path does, with one first line naming it;
                 `--example` alone lists the examples; an unknown NAME exits 3 naming them; --show prints the files
  plain words    each coin word's first appearance in a stream carries its meaning, and "struck: N" still reads N
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from kamanu.cabinet import cli as SC
from kamanu.cabinet import examples as EX
from kamanu.cabinet import plain as PW

ROOT = Path(__file__).resolve().parents[1]


def lf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


@pytest.mark.parametrize("name", [n for n, e in EX.EXAMPLES.items() if e.source])
def test_example_copies_are_the_tree_files(name):
    ex = EX.EXAMPLES[name]
    for f, src in zip(EX.files(name), ex.source):
        assert lf(f.read_bytes()) == lf((ROOT / src).read_bytes()), \
            f"the package's example copy {f.name} is no longer {src} byte for byte: copy it again"


def test_per_charge_card():
    (f,) = EX.files("per-charge")
    card = json.loads(f.read_text(encoding="utf-8"))
    assert card["object"] == "issuing.card"
    assert re.search(r"example", card["id"])
    lims = card["spending_controls"]["spending_limits"]
    assert lims and all(x["interval"] == "per_authorization" for x in lims)


def run(argv, capsys):
    rc = SC.main([str(a) for a in argv])
    got = capsys.readouterr()
    return rc, got.out + got.err


def normalized(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = re.sub(r"\b[0-9a-f]{64}\b", "<H>", line)
        line = re.sub(r"\S*[\\/]\S*|\S+\.(?:json|dw)\b", "<PATH>", line).rstrip()
        if line.strip():
            out.append(line)
    return out


def test_list_and_unknown(tmp_path, capsys):
    rc, out = run(["--example"], capsys)
    assert rc == 0
    for n in EX.EXAMPLES:
        assert len([l for l in out.splitlines() if re.search(rf"(?<![\w-]){n}(?![\w-])", l)]) == 1
    rc, out = run(["--example", "nosuch", "--cabinet", tmp_path / "c"], capsys)
    assert rc == 3 and all(n in out for n in EX.EXAMPLES)
    assert not (tmp_path / "c" / "receipts.jsonl").exists()


def test_show_prints_the_files(capsys):
    rc, out = run(["--example", "budget", "--show"], capsys)
    assert rc == 0
    for f in EX.files("budget"):
        assert lf(f.read_bytes()).decode("utf-8").strip() in out.replace("\r\n", "\n")


def test_budget_example_is_the_path_scan(tmp_path, capsys):
    rc_e, out_e = run(["--example", "budget", "--cabinet", tmp_path / "e", "--label", "b"], capsys)
    pol, eng, cap, _ = EX.scan_args("budget")
    rc_p, out_p = run([pol, "--engine", eng, "--cap", cap, "--cabinet", tmp_path / "p", "--label", "b"], capsys)
    assert rc_e == rc_p == 1
    assert "budget" in out_e.splitlines()[0]
    assert normalized(out_e)[1:] == normalized(out_p)
    a, b = ((tmp_path / d / "receipts.jsonl").read_text(encoding="utf-8").splitlines() for d in ("e", "p"))
    assert len(a) == len(b) == 1
    drop = lambda r: {k: v for k, v in json.loads(r).items() if k not in ("replay", "signature")}
    assert drop(a[0]) == drop(b[0])


def test_per_charge_example(tmp_path, capsys):
    rc, out = run(["--example", "per-charge", "--cabinet", tmp_path / "c"], capsys)
    assert rc == 2
    assert not (tmp_path / "c" / "receipts.jsonl").exists()
    line = [l for l in out.splitlines() if "per_authorization" in l and "UNKNOWN" in l][0]
    assert "each" in line and "total" in line and "4 x 5000 = 20000" in line


def test_gloss_first_appearance_only():
    seen = set()
    first = PW.gloss_line("  Sound holds die D: struck: 3 (receipts)", seen)
    assert "fingerprint" in first and "counts the receipts" in first
    assert re.search(r"struck:\s*(\d+)", first).group(1) == "3"
    assert PW.gloss_line("  Tight FAILS die E: struck: 1", seen) == "  Tight FAILS die E: struck: 1"
    assert PW.gloss_line("cabinet: x", set()).startswith("cabinet: x (")
    said = "  ceiling 10 (the most that can be spent)"
    assert PW.gloss_line(said, set()) == said


def test_glossed_stream_keeps_partial_lines():
    buf = io.StringIO()
    g = PW.Glossed(buf)
    g.write("a plate ")
    g.write("here\nplate again\nend")
    g.finish()
    lines = buf.getvalue().splitlines()
    assert "saved scan" in lines[0] and lines[1] == "plate again" and lines[2] == "end"
