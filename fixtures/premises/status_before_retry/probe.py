"""python probe.py DIR: is each order charged exactly once when the first answer is an error?

The service loses the first charge's answer after it was made, and, in another run, before it was
made. Its status answer is true to its books: that is the assumption the established fixture names.
Written for KAMANU task T5.
"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import payments  # noqa: E402


class Gateway:
    def __init__(self, made_before_the_error):
        self.made_before_the_error = made_before_the_error
        self.calls = 0
        self.charged = []

    def charge(self, order, amount):
        self.calls += 1
        if self.calls > 1 or self.made_before_the_error:
            self.charged.append((order, amount))
        if self.calls == 1:
            raise TimeoutError("no answer")
        return "settled"

    def status(self, order):
        return "settled" if any(o == order for o, _ in self.charged) else "unknown"


counts = []
for n, made in enumerate((True, False)):
    gateway = Gateway(made)
    payments.pay(gateway, f"order-{n}", 60)
    counts.append(len(gateway.charged))
print(json.dumps({"holds": counts == [1, 1]}))
