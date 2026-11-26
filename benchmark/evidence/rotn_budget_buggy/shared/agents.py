"""Two agents buy against the one budget.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "budget". No external source.
"""
import asyncio

from shared.budget import spend

BUY_TIMEOUT = 15


async def run_agent(budget, tools, name, orders):
    bought = []
    for sku, price in orders:
        if not spend(budget, name, price):
            break
        bought.append(await asyncio.wait_for(tools.buy(sku), timeout=BUY_TIMEOUT))
    return bought


async def run_both(budget, tools, a_orders, b_orders):
    return await asyncio.gather(run_agent(budget, tools, "a", a_orders), run_agent(budget, tools, "b", b_orders))
