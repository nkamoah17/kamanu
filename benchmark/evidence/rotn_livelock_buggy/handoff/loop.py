"""Two agents pass a task between them until one completes it, or the harness escalates.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "livelock", rule TaskEndsOrEscalates: the buggy twin. Nothing counts the handoffs,
so two agents that keep passing the task back make progress forever and never finish: a
livelock. No external source.
"""
MAX_HANDOFFS = 6
TURN_TIMEOUT = 15


def run(agents, task):
    while True:
        reply = agents.turn(task, timeout=TURN_TIMEOUT)
        if reply == "complete":
            return "done"
