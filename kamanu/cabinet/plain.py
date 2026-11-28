"""Plain words for a scan's text output (X27): the first time a coin word appears in one stream, its line carries
what it means.

    gloss_line(line, seen) -> line   the line, with the meaning of each coin word it holds for the first time added
                                     at its end (a line that already says what the word means is left as it is)
    Glossed(stream)                  a text stream that writes each line through gloss_line, one `seen` per stream

The words stay where they were (a line that starts with "cabinet" still does; "struck: N" still reads N) and the
glossary itself, kamanu.assay.mint TABLE and docs/mint.md, is not changed: these are the scan's own plain words.
--json output, --help and --show are never glossed.
"""
from __future__ import annotations

import io
import re

MOST_SPENT = r"\bmost\b.*\bspent\b"

# (word, how it is found, what it means, how a line that already says so is recognised: every pattern of one group)
WORDS = [
    ("face value", r"\bface\b", "face value means the limit", [[r"\blimit\b"]]),
    ("ceiling", r"\bceilings?\b", "ceiling means the most that can be spent", [[MOST_SPENT]]),
    ("fineness", r"\bfineness\b",
     "fineness means the limit divided by the most that can be spent; 1.000 means it cannot be overspent",
     [[r"\blimit\b", r"\bdivided\b", MOST_SPENT, r"1\.000", r"over-?spent"]]),
    ("stranded budget", r"\bstranded\b", "stranded budget means the most budget a refusal can leave unspent",
     [[r"refus", r"unspent|unused|not spent"]]),
    ("die", r"\bdies?\b", "a die is a failure fingerprint", [[r"fingerprint"]]),
    ("cabinet", r"\bcabinets?\b", "the cabinet is the local receipt log", [[r"\blog\b", r"receipt"]]),
    ("census", r"\bcensus(?:es)?\b", "a census is a count of the receipts kept here", [[r"\bcounts?\b", r"receipt"]]),
    ("plate", r"\bplates?\b", "a plate is a saved scan that can be replayed",
     [[r"\bsaved\b|\bkept\b|\bstored\b", r"replay"]]),
    ("struck", r"\bstruck\b", None, [[r"\bday\b", r"\bsigned\b"], [r"receipt", r"how many|\bcount|\bnumber"]]),
]
STRUCK_COUNT = re.compile(r"(?i)\bstruck:\s*\d")


def _meaning(word: str, text: str, line: str) -> str:
    if word != "struck":
        return text
    if STRUCK_COUNT.search(line):
        return "struck N counts the receipts here that hold that fingerprint"
    return "struck means the day it was signed"


def _says(line: str, groups: list) -> bool:
    n = re.sub(r"\s+", " ", line.lower().replace("’", "'"))
    return any(all(re.search(p, n) for p in g) for g in groups)


def gloss_line(line: str, seen: set) -> str:
    adds = []
    for word, pat, text, already in WORDS:
        if word in seen or not re.search(pat, line, re.I):
            continue
        seen.add(word)
        if not _says(line, already):
            adds.append(_meaning(word, text, line))
    if not adds:
        return line
    return f"{line.rstrip()} ({'; '.join(adds)})"


class Glossed(io.TextIOBase):
    """A text stream over another, glossing each whole line as it is written."""

    def __init__(self, inner):
        self.inner = inner
        self.seen: set = set()
        self.part = ""

    def writable(self) -> bool:
        return True

    @property
    def encoding(self):
        return getattr(self.inner, "encoding", "utf-8")

    def isatty(self) -> bool:
        return bool(getattr(self.inner, "isatty", lambda: False)())

    def write(self, s: str) -> int:
        self.part += s
        while "\n" in self.part:
            line, self.part = self.part.split("\n", 1)
            self.inner.write(gloss_line(line, self.seen) + "\n")
        return len(s)

    def flush(self) -> None:
        self.inner.flush()

    def finish(self) -> None:
        if self.part:
            self.inner.write(gloss_line(self.part, self.seen))
            self.part = ""
        self.inner.flush()
