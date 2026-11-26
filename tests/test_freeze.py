"""exonumia.freeze: which blocks run and what each command must exit (no clone, no install)."""
from exonumia.freeze import blocks as B

README = """# P

## Install

```sh
kamanu exit 9 outside
```

## See it in a minute

```
kamanu echo a
cd sub  # exits 0
kamanu exit 3 x  # exits 3 (a check fails)
```

```
KAMANU hallmark output
```

```text
kamanu echo output
```

### Still inside

```bash
# a comment line
kamanu echo b \\
    c
```

## Next

```sh
kamanu exit 9 after
```
"""


def test_section_shell_blocks():
    bl = B.readme_blocks(README)
    assert len(bl) == 2
    assert bl[0][0] == "kamanu echo a"
    assert "kamanu echo b \\" in bl[1]


def test_commands_and_exits():
    bl = B.readme_blocks(README)
    c = B.commands(bl[0])
    assert [x["expect"] for x in c] == [0, 0, 3]
    c = B.commands(bl[1])
    assert len(c) == 1 and c[0]["text"].splitlines()[-1].strip() == "c" and c[0]["expect"] == 0


def test_comment_names_exit():
    assert B.exit_named("kamanu echo t  # exit 4") == 4
    assert B.exit_named("kamanu echo exits 4") == 0


def test_recipe_is_first_block():
    assert B.recipe_block("# S\n\n```\nkamanu scan --verify\n```\n\n```\nkamanu x\n```\n") == ["kamanu scan --verify"]
    assert B.recipe_block("no block") is None


def test_heading_inside_fence_is_not_a_heading():
    text = "## See it in a minute\n\n```\n## Next\n```\n\n```sh\nkamanu echo z\n```\n"
    assert [b for _, b, inside in B.fenced(text) if inside] == [["## Next"], ["kamanu echo z"]]
    assert B.readme_blocks(text) == [["kamanu echo z"]]


# ---------------------------------------------------------------- the Apalache jar (X23)
import hashlib  # noqa: E402
import json  # noqa: E402

from exonumia.freeze import run as R  # noqa: E402


def _setup(tmp_path, good: bytes):
    repo, clone = tmp_path / "repo", tmp_path / "clone"
    (clone / "tools" / "vendor").mkdir(parents=True)
    (repo / "tools" / "vendor").mkdir(parents=True)
    pin = {"version": "x", "jar_sha256": hashlib.sha256(good).hexdigest()}
    (clone / "tools" / "vendor" / "apalache.json").write_text(json.dumps(pin), encoding="utf-8")
    return repo, clone, clone / "tools" / "vendor" / "apalache.jar"


def test_apalache_from_env_over_dir(tmp_path):
    good = b"PK\x03\x04good\r\n\x00"
    repo, clone, dest = _setup(tmp_path, good)
    (repo / "tools" / "vendor" / "apalache.jar").write_bytes(b"other")
    given = tmp_path / "given.jar"
    given.write_bytes(good)
    s = R.apalache_jar({"KAMANU_APALACHE_JAR": str(given)}, repo, clone)
    assert s["status"] == "passed" and dest.read_bytes() == good
    assert hashlib.sha256(good).hexdigest() in s["note"] and "KAMANU_APALACHE_JAR" in s["note"]
    assert (repo / "tools" / "vendor" / "apalache.jar").read_bytes() == b"other"


def test_apalache_from_dir_when_env_names_no_file(tmp_path):
    good = b"PK\x03\x04good"
    repo, clone, dest = _setup(tmp_path, good)
    (repo / "tools" / "vendor" / "apalache.jar").write_bytes(good)
    s = R.apalache_jar({"KAMANU_APALACHE_JAR": str(tmp_path / "nope.jar")}, repo, clone)
    assert s["status"] == "passed" and dest.read_bytes() == good and "tools/vendor/apalache.jar" in s["note"]


def test_apalache_mismatch_is_not_copied(tmp_path):
    repo, clone, dest = _setup(tmp_path, b"good")
    (repo / "tools" / "vendor" / "apalache.jar").write_bytes(b"bad")
    s = R.apalache_jar({}, repo, clone)
    assert s["status"] == "not run" and not dest.exists()
    assert hashlib.sha256(b"bad").hexdigest() in s["note"]


def test_apalache_missing_and_no_pin(tmp_path):
    repo, clone, dest = _setup(tmp_path, b"good")
    s = R.apalache_jar({}, repo, clone)
    assert s["status"] == "not run" and "apalache" in s["note"].lower() and not dest.exists()
    (clone / "tools" / "vendor" / "apalache.json").unlink()
    (repo / "tools" / "vendor" / "apalache.jar").write_bytes(b"good")
    assert R.apalache_jar({}, repo, clone)["status"] == "not run" and not dest.exists()


def test_ladder_failures(tmp_path):
    log = tmp_path / "pytest.log"
    log.write_text("$ python -m pytest tests -q\n..F.F\n"
                   "FAILED tests/test_ladder_proof.py::test_the_first_blocker_reproduces - AssertionError: x\n"
                   "FAILED tests/test_other.py::test_y - AssertionError\n", encoding="utf-8")
    assert R.ladder_failures(log) == ["tests/test_ladder_proof.py::test_the_first_blocker_reproduces"]
