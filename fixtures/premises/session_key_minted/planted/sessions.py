"""Sessions, with a planted defect: the key is minted, then the caller's fields are copied over it.

Written for KAMANU task T5. The minting line is the pattern of session_key_minted. A request that
carries a field of the key's name replaces it, so the caller chooses the key the budget is counted over.
"""
import secrets


class Session:
    pass


def open_session(request):
    session = Session()
    session.session_key = secrets.token_urlsafe(32)
    for name, value in request.items():
        setattr(session, name, value)
    return vars(session)["session_key"]
