"""The bundled reference adapter (H11): the kernel's own decisions for an engine profile.

The sixty-second path needs no engine build and no download, so `kamanu hunt --example`
runs on this adapter by default. A ReferenceEngine decides each request as the kernel does
under the profile's constants:

    Reflexive    TRUE: the request under decision is in its own view
    DenyRecord   what a denial leaves in history ("none": nothing, "request": the request)

read from a profile JSON shipped with the package (kamanu/hunt/profiles/, a copy of the
repository's profiles/). Its sessions are the hunt's profile models (kamanu.hunt.Model),
which apply the policy's compiled Permit over timestamped events. The hunt itself is not
told any of this: it sees only issue/settle/fail/wait, as with a real engine.
"""
from __future__ import annotations

import json
from pathlib import Path

from kamanu.hunt import Model, Policy

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
DENY_MARKS = {"none": [], "request": ["request"]}


def profile_file(name: str) -> Path:
    f = PROFILES_DIR / f"{name}.json"
    if not f.is_file():
        known = sorted(p.stem for p in PROFILES_DIR.glob("*.json"))
        raise ValueError(f"no bundled profile {name!r}; bundled: {', '.join(known)}")
    return f


def hunt_profile(constants: dict) -> dict:
    """The kernel profile's constants as a profile of the hunt's space."""
    deny = constants["DenyRecord"]["value"]
    if deny not in DENY_MARKS:
        raise ValueError(f"DenyRecord {deny!r} is outside the reference adapter's space {sorted(DENY_MARKS)}")
    return {"reflexive": bool(constants["Reflexive"]["value"]), "deny_marks": list(DENY_MARKS[deny])}


class ReferenceEngine:
    name = "reference"

    def __init__(self, policy_text: str, profile: str = "dogwood-1.1.1"):
        data = json.loads(profile_file(profile).read_text(encoding="utf-8"))
        self.profile_id = data["id"]
        self.profile = hunt_profile(data["constants"])
        self.policy = Policy(policy_text)

    def open(self):
        return Model(self.profile, self.policy)
