"""Orchestration: agent A hands a task to agent B, B asks the approver, and the task ends or is
escalated.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "orchestration", rules no deadlock and TaskEndsOrEscalates: the fixed twin. The chain
A -> B -> approver has no edge back, every wait in it has a limit, and a wait that runs out
escalates the task. No external source.
"""
import asyncio

STEP = 20


async def agent_b(approver, task):
    try:
        granted = await asyncio.wait_for(approver.review(task), timeout=STEP)
    except TimeoutError:
        return "escalated"
    return "done" if granted else "refused"


async def agent_a(approver, task):
    try:
        return await asyncio.wait_for(agent_b(approver, task), timeout=STEP)
    except TimeoutError:
        return "escalated"
