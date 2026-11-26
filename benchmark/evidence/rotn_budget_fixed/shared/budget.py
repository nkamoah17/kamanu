"""Shared budget: two agents spend against one cap, and the cap holds across both.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "budget", rule no runaway budget across agents: the fixed twin. Each spend is one
atomic increment of the shared total, and the check reads the total that increment answers.
No external source.
"""
CAP = 100
SHARED = "budget:shared"


def spend(budget, agent, amount):
    total = budget.incrby(SHARED, amount)
    if total > CAP:
        budget.decrby(SHARED, amount)
        return False
    return True
