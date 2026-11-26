"""Reading the blocks the freeze runs: README.md's section and docs/scan.md's recipe (standard library alone)."""
from __future__ import annotations

import re

from exonumia.freeze import SECTION, SHELL_INFO

FENCE = re.compile(r"^ {0,3}(`{3,})\s*([^`]*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
EXPECT = re.compile(r"(?i)\bexits?\s+(\d+)\b")


def fenced(text: str) -> list[tuple[str, list[str], bool]]:
    """Every ``` fenced block of TEXT in order: (its info word, lowercased; its lines; whether it lies in the
    section). The section runs from a heading holding "See it in a minute" to the next heading of level 1 or 2;
    a line inside a fenced block is never a heading."""
    lines = text.splitlines()
    out, inside, i = [], False, 0
    while i < len(lines):
        f = FENCE.match(lines[i])
        if f:
            fence = f.group(1)
            words = f.group(2).strip().split()
            info = words[0].lower() if words else ""
            close = re.compile(r"^ {0,3}" + fence + r"`*\s*$")
            body, i = [], i + 1
            while i < len(lines) and not close.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            out.append((info, body, inside))
            continue
        h = HEADING.match(lines[i])
        if h:
            if SECTION in h.group(2).lower():
                inside = True
            elif len(h.group(1)) <= 2:
                inside = False
        i += 1
    return out


def is_shell(info: str, body: list[str]) -> bool:
    """A shell block: info string sh, bash, shell, console or zsh; with none, a first non-empty line starting with a
    lower-case letter (sample output such as "KAMANU hallmark ..." or "OK signature ..." starts with a capital)."""
    if info:
        return info in SHELL_INFO
    first = next((line.strip() for line in body if line.strip()), "")
    return bool(re.match(r"[a-z]", first))


def readme_blocks(text: str) -> list[list[str]]:
    """The shell blocks of README.md's section, in order."""
    return [body for info, body, inside in fenced(text) if inside and is_shell(info, body)]


def recipe_block(text: str) -> list[str] | None:
    """docs/scan.md's recipe: its first fenced block."""
    blocks = fenced(text)
    return blocks[0][1] if blocks else None


def comment_of(command: str) -> str:
    """The comment of a command's last line: the text after its first " #" (empty when none)."""
    last = command.splitlines()[-1] if command else ""
    k = last.find(" #")
    return last[k + 2:] if k >= 0 else ""


def exit_named(command: str) -> int:
    m = EXPECT.search(comment_of(command))
    return int(m.group(1)) if m else 0


def commands(body: list[str]) -> list[dict]:
    """The commands of a block: each non-empty line that is not a comment line, joined with the lines after it while
    it ends with a backslash. {"text": the lines as written, "expect": the exit its comment names, else 0}."""
    out, cur = [], []
    for line in body:
        if not cur:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
        cur.append(line)
        if line.rstrip().endswith("\\"):
            continue
        text = "\n".join(cur)
        out.append({"text": text, "expect": exit_named(text)})
        cur = []
    if cur:
        text = "\n".join(cur)
        out.append({"text": text, "expect": exit_named(text)})
    return out
