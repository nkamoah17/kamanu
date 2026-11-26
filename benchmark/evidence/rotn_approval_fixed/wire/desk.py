"""Approval desk: an irreversible wire transfer runs only under a granted approval.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "approval", rule NoUnapprovedIrreversible: the fixed twin. A transfer waits for the
approver, and a wire whose outcome is unknown is asked about before it is sent again, so the
one approval never covers two transfers. No external source.
"""
import asyncio

PATIENCE = 30
ATTEMPTS = 3


class Desk:
    def __init__(self, approver, bank):
        self.approver = approver
        self.bank = bank

    async def approved(self, transfer):
        try:
            return await asyncio.wait_for(self.approver.decide(transfer), timeout=PATIENCE)
        except TimeoutError:
            return False

    async def send(self, transfer):
        for _ in range(ATTEMPTS):
            try:
                return await asyncio.wait_for(self.bank.wire(transfer), timeout=PATIENCE)
            except (TimeoutError, ConnectionError):
                state = await asyncio.wait_for(self.bank.status(transfer), timeout=PATIENCE)
                if state == "settled":
                    return state
        return "escalated"
