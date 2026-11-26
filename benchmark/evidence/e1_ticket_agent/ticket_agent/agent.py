"""Ticket agent: a synchronous harness loop.

Written for KAMANU gate E1. The model proposes one tool call per turn, the harness runs it,
and the loop ends on a final answer or when the turn budget is spent. No external source.
"""
from ticket_agent import tools

MAX_TURNS = 8


class Turn:
    def __init__(self, tool, args):
        self.tool = tool
        self.args = args


def plan(model, history):
    reply = model.complete(history)
    if reply.get("final"):
        return None
    return Turn(reply["tool"], reply.get("args", {}))


def run_tool(session, turn):
    handler = tools.lookup(turn.tool)
    if handler is None:
        raise KeyError(turn.tool)
    return handler(session, **turn.args)


def run(model, session, prompt):
    history = [prompt]
    for _ in range(MAX_TURNS):
        turn = plan(model, history)
        if turn is None:
            return history
        try:
            result = run_tool(session, turn)
        except KeyError as missing:
            history.append(str(missing))
            continue
        history.append(result)
    session.close()
    return history
