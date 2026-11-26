"""Ticket agent, planted missing model action: a refused call has no branch.

Written for KAMANU gate E4 from gate E1's ticket_agent: the model proposes a tool call, the
harness runs it, and when the turns are spent the harness escalates instead of looping on.
No external source.
"""
MAX_TURNS = 8


def summarize(history):
    if history and history[-1] == "final":
        return "nothing to add"
    return "\n".join(str(h) for h in history)


def run(model, tools, inbox, prompt):
    history = [prompt]
    phase = "planning"
    while phase != "finished":
        signal = inbox.next(phase)
        match (phase, signal):
            case ("planning", "call_tool"):
                tools.start(model.complete(history))
                phase = "waiting"
            case ("waiting", "tool_result"):
                history.append(inbox.result())
                phase = "answering"
            case ("waiting", "tool_error"):
                history.append("error")
                phase = "planning"
            case ("planning", "turns_exhausted"):
                phase = "escalating"
            case ("answering", "summarize"):
                history.append(summarize(history))
                phase = "replying"
            case ("replying", "final_answer"):
                inbox.reply(history[-1])
                phase = "finished"
            case ("escalating", "notify_human"):
                inbox.page(history)
                phase = "finished"
            case _:
                history.append(f"ignored {signal}")
    return history
