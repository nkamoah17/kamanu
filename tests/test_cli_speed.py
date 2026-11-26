"""kamanu.cli speed (P1e): width, cache location, cache key. No TLC."""
from kamanu import cli


def test_workers(monkeypatch):
    monkeypatch.setenv("KAMANU_WORKERS", "3")
    assert cli.workers() == 3
    monkeypatch.setenv("KAMANU_WORKERS", "0")
    assert cli.workers() == 1
    monkeypatch.delenv("KAMANU_WORKERS")
    assert 1 <= cli.workers() <= 24


def test_cache_dir(monkeypatch, tmp_path):
    for off in ("off", "0", "no", "False"):
        monkeypatch.setenv("KAMANU_CACHE", off)
        assert cli.cache_dir() is None
    monkeypatch.setenv("KAMANU_CACHE", str(tmp_path))
    assert cli.cache_dir() == tmp_path
    monkeypatch.delenv("KAMANU_CACHE")
    assert cli.cache_dir().parts[-2:] == ("kamanu", "tlc")


def test_cached_output_is_returned_without_running(monkeypatch, tmp_path):
    monkeypatch.setenv("KAMANU_CACHE", str(tmp_path))
    monkeypatch.setattr(cli, "_fingerprint", lambda: "fp")
    calls = []
    monkeypatch.setattr(cli, "_run_tlc", lambda module, text, cfg: calls.append(cfg) or f"out {cfg}")
    cli.STATS.update(tlc_runs=0, cache_hits=0)
    assert cli.tlc("D", "safety", "c1") == "out c1"
    assert cli.tlc("D", "safety", "c1") == "out c1"
    assert cli.tlc("D2", "safety", "c1") == "out c1" and len(calls) == 2      # other defs: another key
    assert cli.STATS == {"tlc_runs": 2, "cache_hits": 1}


def test_quick_skips_are_named():
    assert "deadlock" in cli.QUICK_SKIPS and "storm" in cli.QUICK_SKIPS
    assert cli.QUICK_GRID == ("safety",) and cli.QUICK_MORE == ("false-denial",)
