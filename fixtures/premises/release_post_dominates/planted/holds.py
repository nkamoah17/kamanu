"""Holds on an order, with a planted defect: leaving the with does not release the lock when the tool fails.

Written for KAMANU task T5. A with on a lock is the pattern of release_post_dominates. This lock's
__exit__ releases only when nothing was raised, so one failing tool holds the order for good.
"""


class OrderLock:
    def __init__(self):
        self.taken = False

    def __enter__(self):
        if self.taken:
            raise BlockingIOError("the order is held")
        self.taken = True
        return self

    def __exit__(self, kind, value, trace):
        if kind is None:
            self.taken = False
        return False


order_lock = OrderLock()


def reserve(tool):
    with order_lock:
        return tool.reserve()
