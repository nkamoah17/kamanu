"""Ticket tools: reads and one write on a ticket store.

Written for KAMANU gate E1. No external source.
"""


def search(session, text):
    return session.store.find(text)


def update(session, ticket, status):
    row = session.store.get(ticket)
    if row is None:
        raise KeyError(ticket)
    session.store.put(ticket,
                      status)
    return row


TOOLS = {"search": search, "update": update}


def lookup(name):
    return TOOLS.get(name)
