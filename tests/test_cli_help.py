"""R12d: `kamanu` describes every command and every option it accepts.

Walks the dispatcher (kamanu.hunt.cli.DISPATCH): every subcommand it runs is in the usage with a
purpose line; every option string of every argparse parser that parses a command's arguments is in
that command's help; and every option the help names is accepted by the command in the mode the
help gives it (no help names an option the command rejects). Runs in-process; no TLC, no Java:
every probe ends in an unknown option, so the command's parser stops it before it runs anything.
"""
from __future__ import annotations

import argparse
import re

import pytest

from kamanu.hunt import cli

UNKNOWN = "--zz-cli-help-walk"
OPTION = re.compile(r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9-]*)")
HELP = {"-h", "--help"}

# What goes before an option when the walk asks whether the command accepts it: the command's
# positionals and required options (files that need not exist), one list per mode of the command.
MODES = {
    "check": [["policy.dw", "--engine", "reference"]],
    "hunt": [["--example", "dogwood"], ["--adapter", "dogwood", "--policy", "p.dw", "--policy-schema", "s.json"]],
    "fix": [["row.json"], ["policy.dw", "--engine", "reference"]],
    "story": [["trace.txt", "--cell", "{}"]],
    "coach": [["--policy", "p.dw", "--profile", "f.json", "--tool", "Pay", "--t", "0", "--amount", "1"]],
    "invariants": [["PReqBasis"]],
    "matrix": [[], ["--rebuild"]],
    "share": [["record.json"]],
    "lint": [["p.dw", "--engine", "reference"]],
    "admit": [["p.dw", "--engine", "reference"]],
    "assay": [["p.dw", "--engine", "e.json"], ["--verify", "r.json", "--key", "k.pub"]],
    "connector": [["assess", "--tenants", "t.json", "--out", "o"]],
    "scan": [["--card", "p.json"], ["p.dw", "--engine", "e.json"]],
    "mcp": [["lint"], ["coach"], ["serve"]],
}


def names(text: str, word: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", text) is not None


def run(argv, capsys, monkeypatch):
    """main(argv): (exit code, stdout + stderr, the option strings of every parser that parsed)."""
    seen = []
    real = argparse.ArgumentParser.parse_known_args

    def watch(self, args=None, namespace=None):
        seen.append([s for act in self._actions for s in act.option_strings])
        return real(self, args, namespace)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_known_args", watch)
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:
        rc = e.code
    finally:
        monkeypatch.setattr(argparse.ArgumentParser, "parse_known_args", real)
    out = capsys.readouterr()
    return rc, out.out + out.err, {o for opts in seen for o in opts} - HELP


def test_usage_names_every_dispatched_command(capsys, monkeypatch):
    assert set(cli.PURPOSES) == set(cli.DISPATCH) == set(MODES)
    rc, usage, _ = run(["--help"], capsys, monkeypatch)
    assert rc == 0
    for form in ([], ["-h"], ["help"]):
        _, text, _ = run(form, capsys, monkeypatch)
        assert usage in text, form
    for cmd in cli.DISPATCH:
        lines = [ln for ln in usage.splitlines() if names(ln, cmd)]
        assert any(len(re.findall(r"[A-Za-z]{3,}", ln)) >= 4 for ln in lines), f"{cmd} has no purpose line"
    assert names(usage, "--version") and names(usage, "--example")
    tail = usage[usage.lower().index("exit"):]
    assert re.search(r"check .*\b1\b", tail) and re.search(r"share .*\b0 shared.*\b1 not confirmed.*\b2 refused.*\b3 error", tail)


def test_unknown_command_is_refused(capsys, monkeypatch):
    rc, text, _ = run(["no-such-command", "--help"], capsys, monkeypatch)
    assert rc != 0 and "kamanu no-such-command" not in text


@pytest.mark.parametrize("cmd", sorted(MODES))
def test_help_lists_every_option_its_parsers_accept(cmd, capsys, monkeypatch):
    rc, help_text, _ = run([cmd, "--help"], capsys, monkeypatch)
    assert rc == 0, help_text
    assert re.search(rf"\bkamanu {cmd}\b", help_text)
    declared = set()
    for prefix in [[]] + MODES[cmd]:
        _, _, opts = run([cmd, *prefix, UNKNOWN], capsys, monkeypatch)
        declared |= opts
    missing = sorted(o for o in declared if not names(help_text, o))
    assert not missing, f"`kamanu {cmd} --help` does not list {missing}:\n{help_text}"


@pytest.mark.parametrize("cmd", sorted(MODES))
def test_help_names_no_option_the_command_rejects(cmd, capsys, monkeypatch):
    _, help_text, _ = run([cmd, "--help"], capsys, monkeypatch)
    rejected = []
    for opt in dict.fromkeys(m.group(1) for m in OPTION.finditer(help_text)):
        if opt in HELP:
            continue
        verdicts = []
        for prefix in MODES[cmd]:
            rc, text, _ = run([cmd, *prefix, opt, UNKNOWN], capsys, monkeypatch)
            assert rc not in (0, None), f"`kamanu {cmd} {' '.join(prefix)} {opt} {UNKNOWN}` was not refused:\n{text}"
            verdicts.append(any(names(ln, opt) and re.search(r"unrecogni[sz]ed|unknown", ln, re.I)
                                for ln in text.splitlines()))
        if all(verdicts):
            rejected.append(opt)
    assert not rejected, f"`kamanu {cmd} --help` names {rejected}, which every mode of {cmd} rejects"
