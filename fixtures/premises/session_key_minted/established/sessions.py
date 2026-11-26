"""Sessions: the key is a local of the function that mints it, and nothing of the request's reaches it.

Written for KAMANU task T5. The construct is library_mint_in_local.
"""
import secrets


def open_session(request):
    owner = {"fields": dict(request)}
    session_key = secrets.token_urlsafe(32)
    owner["opened"] = True
    return session_key
