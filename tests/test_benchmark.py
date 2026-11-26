"""The false_proven benchmark's own tests, beyond gate E5.

benchmark/evidence/ is gate E5's benchmark, copied unchanged: 35 repositories and labels.json. These
tests need no Joern. They check that the copy is whole and self-consistent (each label names lines
that exist and say what the label quotes), and that progress/E5.facts.json, the record of the last
live run, still answers for the queries and runner on disk, with no fact on a premise labelled
"fails". A change to kamanu/evidence/queries/ or joern.py fails here until the benchmark is rerun
live and the record re-committed, which is the point: a query change is not done until it has been
run against the benchmark.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark" / "evidence"
QUERIES = ROOT / "kamanu" / "evidence" / "queries"
RUNNER = ROOT / "kamanu" / "evidence" / "joern.py"
RECORD = ROOT / "progress" / "E5.facts.json"
PREMISES = ("session_key_minted", "check_act_atomic", "release_post_dominates", "await_has_timeout",
            "retry_bounded", "status_before_retry")
GROUPS = {"rotn_": 12, "a4_": 5, "e1_": 2, "e4_": 9, "audit_p": 7}
NO_SITE = "no site of this premise in the repository, and absence is never evidence"
BAD_SITE = re.compile(r"a bad site, reached by a run that fails: (?P<file>[\w/.]+\.py):(?P<line>\d+) (?P<code>.+)")
GOOD_SITES = re.compile(r"every site holds when run \((?P<n>\d+)\): (?P<sites>.+)")
SITE = re.compile(r"(?P<file>[\w/.]+\.py):(?P<line>\d+)")

LABELS = json.loads((BENCH / "labels.json").read_text(encoding="utf-8"))
REPOS = sorted(LABELS)


def lines_of(repo, rel):
    path = BENCH / repo / rel
    assert path.is_file(), f"{repo}: {rel} is not in the repository"
    return path.read_text(encoding="utf-8").splitlines()


def py_files(repo):
    return sorted(p for p in (BENCH / repo).rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_the_benchmark_has_its_five_groups():
    dirs = sorted(p.name for p in BENCH.iterdir() if p.is_dir() and p.name != "__pycache__")
    assert dirs == REPOS
    for prefix, count in GROUPS.items():
        assert sum(r.startswith(prefix) for r in REPOS) == count, prefix
    assert len(REPOS) == sum(GROUPS.values())


@pytest.mark.parametrize("repo", REPOS)
def test_each_repository_is_python_that_compiles(repo):
    files = py_files(repo)
    assert files, f"{repo} is empty"
    for path in files:
        assert path.suffix == ".py", path
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("repo", REPOS)
def test_each_label_names_lines_that_exist(repo):
    entry = LABELS[repo]
    assert entry["source"].strip()
    assert sorted(entry["premises"]) == sorted(PREMISES)
    for premise, lab in entry["premises"].items():
        why = lab["why"]
        if lab["label"] == "fails":
            if why == NO_SITE:
                continue
            m = BAD_SITE.fullmatch(why)
            assert m, f"{repo} {premise}: {why!r}"
            text = lines_of(repo, m["file"])
            line = int(m["line"])
            assert 1 <= line <= len(text), f"{repo} {premise}: {m['file']}:{line} is past the end"
            assert text[line - 1].strip().startswith(m["code"].strip()), \
                f"{repo} {premise}: {m['file']}:{line} reads {text[line - 1].strip()!r}, the label quotes {m['code']!r}"
        else:
            assert lab["label"] == "holds", f"{repo} {premise}: {lab['label']!r}"
            m = GOOD_SITES.fullmatch(why)
            assert m, f"{repo} {premise}: {why!r}"
            sites = SITE.findall(m["sites"])
            assert sites, f"{repo} {premise}: a holds label with no site"
            for rel, line in sites:
                text = lines_of(repo, rel)
                assert 1 <= int(line) <= len(text) and text[int(line) - 1].strip(), \
                    f"{repo} {premise}: {rel}:{line} is not a line of code"


TWINS = sorted({r.rsplit("_", 1)[0] for r in REPOS if r.startswith("rotn_")})


@pytest.mark.parametrize("model", TWINS)
def test_the_rotn_twins_differ_in_one_premise_only(model):
    fixed, buggy = LABELS[f"{model}_fixed"]["premises"], LABELS[f"{model}_buggy"]["premises"]
    differ = [p for p in PREMISES if fixed[p]["label"] != buggy[p]["label"]]
    assert len(differ) == 1, f"{model}: the twins differ in {differ}"
    assert fixed[differ[0]]["label"] == "holds" and buggy[differ[0]]["label"] == "fails"


def test_the_benchmark_cannot_pass_vacuously():
    """There are "holds" labels for every premise, so recall means something, and "fails" labels
    with a real bad site for every premise, so a query that proves everything is caught."""
    for premise in PREMISES:
        labs = [LABELS[r]["premises"][premise] for r in REPOS]
        assert any(l["label"] == "holds" for l in labs), f"no repository where {premise} holds"
        assert any(l["label"] == "fails" and l["why"] != NO_SITE for l in labs), f"no bad site of {premise}"


# ---------------- the record of the last live run ----------------
def norm(path):
    return Path(path).read_bytes().replace(b"\r\n", b"\n")


def current_code():
    files = sorted(p for p in QUERIES.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    out = {p.relative_to(QUERIES).as_posix(): hashlib.sha256(norm(p)).hexdigest() for p in files}
    out["joern.py"] = hashlib.sha256(norm(RUNNER)).hexdigest()
    return out


@pytest.fixture(scope="module")
def record():
    assert RECORD.is_file(), "progress/E5.facts.json is missing: run gate E5 with JOERN_HOME set"
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_the_record_is_of_the_queries_on_disk(record):
    assert record["joern_version"] == "4.0.676"
    assert record["code_sha256"] == current_code(), \
        "kamanu/evidence/queries/ or joern.py changed after the benchmark ran: rerun gate E5 live and commit the record"


def test_the_record_covers_the_benchmark(record):
    results = record["repositories"]
    assert sorted(results) == REPOS
    for repo in REPOS:
        assert sorted(results[repo]) == sorted(PREMISES), repo


def test_the_record_holds_no_false_proof(record):
    bad = {}
    for repo in REPOS:
        for premise in PREMISES:
            facts = record["repositories"][repo][premise]
            if LABELS[repo]["premises"][premise]["label"] == "fails" and facts:
                bad[f"{repo} {premise}"] = sorted((f["file"], f["line"]) for f in facts)
    assert not bad, f"FALSE PROOF on the benchmark: {bad}"


def test_each_recorded_fact_names_a_line_of_its_repository(record):
    for repo in REPOS:
        hashes = set()
        for premise in PREMISES:
            for fact in record["repositories"][repo][premise]:
                assert fact["query_id"] == premise, f"{repo}: a {fact['query_id']} fact filed under {premise}"
                text = lines_of(repo, fact["file"])
                assert type(fact["line"]) is int and 1 <= fact["line"] <= len(text), f"{repo}: {fact}"
                hashes.add(fact["graph_hash"])
        assert len(hashes) <= 1, f"{repo}: facts from more than one graph"


def test_the_recorded_recall_is_its_facts(record):
    results = record["repositories"]
    expect = {}
    for premise in PREMISES:
        holding = [r for r in REPOS if LABELS[r]["premises"][premise]["label"] == "holds"]
        expect[premise] = [sum(bool(results[r][premise]) for r in holding), len(holding)]
    expect["all"] = [sum(a for a, _ in expect.values()), sum(b for _, b in expect.values())]
    assert record["recall"] == expect
