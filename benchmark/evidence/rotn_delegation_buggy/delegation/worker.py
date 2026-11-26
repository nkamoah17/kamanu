"""The delegatee: one action, run only under a grant.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "delegation". No external source.
"""
from delegation.grants import allowed

TOOL_TIMEOUT = 10


def act(tools, token, action):
    if not allowed(token, action):
        return "refused"
    return tools.run(action, timeout=TOOL_TIMEOUT)
