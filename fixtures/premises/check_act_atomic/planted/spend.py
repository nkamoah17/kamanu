"""Spend limit, with a planted defect: the increment is a read and a write of a file two workers share.

Written for KAMANU task T5. The call of incr is the pattern of check_act_atomic: one write that answers
with the count. Inside it the count is read and then written, with no await between them and no lock, so
two worker processes can read the same count, and both are let through.
"""
import os
from pathlib import Path

LIMIT = 100


class SharedCount:
    def __init__(self, path):
        self.path = Path(path)

    def incr(self, key, amount):
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else "0"
        after = int(text) + amount
        self.path.write_text(str(after), encoding="utf-8")
        return after


counter = SharedCount(os.environ["SPEND_COUNT_FILE"])


def spend(order, amount):
    total = counter.incr(order, amount)
    if total > LIMIT:
        return False
    return True
