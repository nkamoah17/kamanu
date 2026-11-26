"""Two agents pass a task between them until one completes it, or the harness escalates.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "livelock", rule TaskEndsOrEscalates: the fixed twin. The handoffs are counted and
bounded, so a task the agents keep passing back ends in escalation. No external source.
"""
MAX_HANDOFFS = 6
TURN_TIMEOUT = 15


def run(agents, task):
    handoffs = 0
    while handoffs < MAX_HANDOFFS:
        reply = agents.turn(task, timeout=TURN_TIMEOUT)
        if reply == "complete":
            return "done"
        handoffs += 1
    return "escalated"
