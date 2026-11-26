"""Holds on an order: the lock is threading's own, so leaving the with releases it on every path.

Written for KAMANU task T5. The construct is threading_lock_with.
"""
import threading

order_lock = threading.Lock()


def reserve(tool):
    with order_lock:
        return tool.reserve()
