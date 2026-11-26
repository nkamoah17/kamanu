"""reproduce/headline.py: the post's number comes from the table, and the post's commands are the script's."""
import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("headline", ROOT / "reproduce" / "headline.py")
headline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(headline)


def _rec():
    return json.loads(headline.TABLE.read_text(encoding="utf-8"))


def _last_number(rec):
    return int(re.findall(r"\d+", headline.lines(rec)[-1])[-1])


def test_last_line_is_failing_cells():
    rec = _rec()
    s = headline.summary(rec)
    assert _last_number(rec) == s["failing_cells"]
    assert s["cells"] == 4 * len(rec["table"])


def test_number_moves_with_the_table():
    rec = _rec()
    before = _last_number(rec)
    row = copy.deepcopy(rec["table"][0])
    row["bundle"] = "another_cap"
    for c in row["tests"].values():
        c["verdict"] = "fails"
    rec["table"].append(row)
    rec["denominator"] += 1
    assert _last_number(rec) == before + 4


def test_post_states_the_number_and_matches_the_script():
    post = (ROOT / "post" / "flagship.md").read_text(encoding="utf-8")
    marks = re.findall(r"<!--\s*number\s*:\s*(\S+?)\s*-->", post)
    assert marks == [str(_last_number(_rec()))]
    section = post.split("## How to reproduce", 1)[1]
    block = re.findall(r"```(?:bash|sh)?\n(.*?)```", section, re.S)
    keep = lambda ls: [l.strip() for l in ls if l.strip() and not l.strip().startswith("#")
                       and not re.match(r"set\s+[-+]", l.strip())]
    post_cmds = keep("\n".join(block).splitlines())
    script = (ROOT / "reproduce" / "flagship.sh").read_text(encoding="utf-8").splitlines()
    assert post_cmds == keep(script)
