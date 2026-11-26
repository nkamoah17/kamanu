"""The transfer flow: the approval first, then the wire.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "approval". No external source.
"""
from wire.desk import Desk


async def transfer(approver, bank, order):
    desk = Desk(approver, bank)
    if not await desk.approved(order):
        return "denied"
    return await desk.send(order)
