"""Delegation grants: what a delegatee may do, under a token the server mints.

Written for KAMANU gate E5 from rotn-research rotn_research/approval.py (commit bda0ca4),
sub-model "delegation", rule no privilege escalation through delegation: the fixed twin. The
token is minted here, so a caller cannot name a grant it was never given. No external source.
"""
import secrets

GRANTS = {}


def delegate(request, delegator_scopes, scopes):
    if not set(scopes) <= set(delegator_scopes):
        return None
    session_token = secrets.token_urlsafe(24)
    GRANTS[session_token] = tuple(scopes)
    return session_token


def allowed(token, action):
    return action in GRANTS.get(token, ())
