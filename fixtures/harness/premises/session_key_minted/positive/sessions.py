"""Sessions: the server mints every key, and the caller's name is only stored.

Written for KAMANU gate E2. No external source.
"""
import secrets
import uuid


def open_session(request):
    owner = request.get("user")
    session_key = secrets.token_urlsafe(32)
    return dict(owner=owner, session_key=session_key)["session_key"]


def open_trial(request):
    session_id = "trial-" + uuid.uuid4().hex
    return session_id
