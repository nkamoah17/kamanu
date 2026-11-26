"""Two agents share a stock table and a ledger, each behind its own lock.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "deadlock", rule TaskEndsOrEscalates with no stuck state: the buggy twin. One agent
takes stock then ledger, the other ledger then stock, so each can hold one lock while it waits
on the other for good: a deadlock. No external source.
"""
import threading

TOOL_TIMEOUT = 5

stock_lock = threading.Lock()
ledger_lock = threading.Lock()


def reserve(tools, sku):
    with stock_lock:
        with ledger_lock:
            return tools.reserve(sku, timeout=TOOL_TIMEOUT)


def restock(tools, sku):
    with ledger_lock:
        with stock_lock:
            return tools.restock(sku, timeout=TOOL_TIMEOUT)
