"""Approval desk: an irreversible wire transfer runs only under a granted approval.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "approval", rule NoUnapprovedIrreversible: the buggy twin. A wire whose outcome is
unknown is sent again without asking, so one approval can cover two irreversible transfers.
No external source.
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
                continue
        return "escalated"
