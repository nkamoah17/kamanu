"""Refund agent: an approval-gated refund with reconciliation, as an explicit state machine.

Written for KAMANU gate E4 from gate E1's refund_agent: the same approval step, timeout and
ledger, with the control state kept in one variable. No external source.
"""
import asyncio

LIMIT = 100


async def next_event(source, state):
    """Wait for what happens next: the model's choice, the approver, or the gateway."""
    return await asyncio.wait_for(source.get(state), timeout=30)


async def run(source, gateway, ledger, refund):
    state = "idle"
    receipt = None
    while state not in ("done", "closed"):
        event = await next_event(source, state)
        if state == "idle" and event == "request_approval":
            await source.ask_approver(refund)
            state = "awaiting"
        elif state == "awaiting" and event == "granted":
            state = "approved"
        elif state == "awaiting" and event == "approval_timeout":
            state = "escalated"
        elif state == "approved" and event == "pay":
            await gateway.pay(refund.order, refund.amount)
            state = "paying"
        elif state == "paying" and event == "paid":
            receipt = source.last_receipt()
            state = "settled"
        elif state == "paying" and event == "declined":
            state = "approved"
        elif state == "paying" and event == "pay_error":
            state = "reconciling"
        elif state == "reconciling" and event == "confirmed":
            state = "settled"
        elif state == "reconciling" and event == "refunded":
            state = "approved"
        elif state == "settled" and event == "close":
            await ledger.add(refund.order, refund.amount, receipt)
            state = "done"
        elif state == "escalated" and event == "hand_off":
            await source.page_human(refund)
            state = "closed"
    return state == "done"
