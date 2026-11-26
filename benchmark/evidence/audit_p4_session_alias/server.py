import uuid

def new_session():
    session_key = uuid.uuid4().hex
    return session_key

def handle(request, ledger):
    sid = request.headers["X-Session"]    # the key actually used comes from the caller
    ledger.charge(sid, 1)
