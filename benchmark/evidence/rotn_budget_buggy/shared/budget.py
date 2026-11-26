"""Shared budget: two agents spend against one cap, and the cap holds across both.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "budget", rule no runaway budget across agents: the buggy twin. Each agent reads its
own spend, checks it, and writes it back, so neither sees the other's spend and two agents that
read together both pass the cap. No external source.
"""
CAP = 100
SHARED = "budget:shared"


def spend(budget, agent, amount):
    spent = int(budget.get(agent) or 0)
    if spent + amount > CAP:
        return False
    budget.set(agent, spent + amount)
    return True
