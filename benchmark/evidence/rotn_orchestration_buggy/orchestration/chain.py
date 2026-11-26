"""Orchestration: agent A hands a task to agent B, B asks the approver, and the task ends or is
escalated.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "orchestration", rules no deadlock and TaskEndsOrEscalates: the buggy twin. The
approver's review waits on agent A, which waits on B, which waits on the approver: a cycle, and
no wait in it has a limit, so the circular wait never ends. No external source.
"""


async def agent_b(approver, task):
    granted = await approver.review(task)
    return "done" if granted else "refused"


async def agent_a(approver, task):
    return await agent_b(approver, task)
