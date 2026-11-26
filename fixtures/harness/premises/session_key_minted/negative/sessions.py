"""Sessions: one path mints a key, and the other takes the one the caller sent.

Written for KAMANU gate E2. No external source.
"""
import secrets


def open_session(request):
    session_key = request.headers.get("x-session") or secrets.token_urlsafe(32)
    return session_key


def open_trial(request):
    session_id = secrets.token_hex(16)
    return session_id
