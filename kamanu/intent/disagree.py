"""Intent by disagreement (I3): an LLM reads the operator's prose, TLC checks what it proposes.

    extract(document, backend=None) -> [template name]   what the document requires
    check(policy, proposals) -> {name: TLC verdict}      each proposal on the deployed design
    evaluate(triples, extractor) -> {"recall", "precision", "proposals", "rows"}
    backend() -> "anthropic" | "claude-cli" | None        the LLM access available here

The vocabulary is the T1 template catalog (kamanu.intent.templates). A policy says, per
template, whether the deployed design is the fixed twin (True) or the planted violation
(False). A proposal that TLC finds violated is a disagreement between what the document
asks for and what the policy does.

LLM access, in this order:
    KAMANU_LLM=anthropic or KAMANU_LLM=claude-cli forces one;
    otherwise ANTHROPIC_API_KEY set: the Messages API, over HTTPS, temperature 0;
    otherwise a `claude` executable on PATH: Claude Code in print mode, which runs on the
    user's Claude subscription. Its CLI has no temperature flag, so its runs record
    "temperature": "cli-default".
The model is MODEL for both. PROMPT_SHA256 is the hash of the exact system prompt and
user-message template, so a recorded run says which prompt produced it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request

from kamanu.intent import templates as T

MODEL = "claude-sonnet-5-5"
TEMPERATURE = 0
API_URL = "https://api.anthropic.com/v1/messages"
TIMEOUT = 300

DESCRIPTIONS = {
    "spend-cap": "real spending stays within a stated budget or cap, even if the agent is manipulated or compromised",
    "no-exfiltration": "after the agent reads private or confidential data, it must not send anything to an external destination",
    "approval-before-irreversible": "an irreversible action happens only after a human approved that exact action",
    "mandate-used-once": "a single-use authorization, token, voucher or mandate is redeemed at most once, even under concurrency",
    "task-ends": "every task the agent is given actually reaches its goal (it is completed, not abandoned)",
    "escalates-only-when-stuck": "the agent hands a task to a human only after it has genuinely attempted it",
    "no-starvation": "every agent waiting for a shared resource is eventually served; none waits forever",
    "deletion-honored": "data deleted on request stays deleted; replicas, syncs or restores never bring it back",
}

SYSTEM = ("You extract formal requirements from an operator's description of an AI agent deployment. "
          "You answer with a JSON array and nothing else.")
USER = ("Here are the properties a deployment can be required to satisfy:\n{catalog}\n\n"
        "Operator's description:\n\"\"\"\n{document}\n\"\"\"\n\n"
        "Which of these properties does the description require? Include a property only when the "
        "description states it or clearly requires it; do not include properties that are merely "
        "plausible. Answer with a JSON array of property names, for example [\"spend-cap\"].")
PROMPT_SHA256 = hashlib.sha256((SYSTEM + "\n---\n" + USER + "\n---\n" + json.dumps(DESCRIPTIONS, sort_keys=True))
                               .encode("utf-8")).hexdigest()


def backend() -> str | None:
    forced = os.environ.get("KAMANU_LLM")
    if forced in ("anthropic", "claude-cli"):
        return forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if shutil.which("claude"):
        return "claude-cli"
    return None


def prompt(document: str) -> str:
    catalog = "\n".join(f"- {name}: {text}" for name, text in DESCRIPTIONS.items())
    return USER.format(catalog=catalog, document=document)


def _ask_api(text: str) -> str:
    body = json.dumps({"model": MODEL, "max_tokens": 200, "temperature": TEMPERATURE, "system": SYSTEM,
                       "messages": [{"role": "user", "content": text}]}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(block.get("text", "") for block in data.get("content", []))


def _ask_cli(text: str) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("no claude executable on PATH")
    p = subprocess.run([exe, "-p", "--model", MODEL, "--output-format", "json", "--no-session-persistence",
                        "--system-prompt", SYSTEM], input=text, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError(f"claude -p exited {p.returncode}: {p.stderr[-500:]}")
    out = json.loads(p.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude -p: {out.get('result')}")
    return out.get("result", "")


def parse(answer: str) -> list[str]:
    """The catalog names in the first JSON array of the answer, in order, each once."""
    m = re.search(r"\[.*?\]", answer, flags=re.S)
    try:
        names = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        names = []
    return list(dict.fromkeys(n for n in names if isinstance(n, str) and n in T.TEMPLATES))


def extract(document: str, which: str | None = None) -> list[str]:
    which = which or backend()
    if which is None:
        raise RuntimeError("no LLM access: set ANTHROPIC_API_KEY, or install Claude Code and log in")
    ask = _ask_api if which == "anthropic" else _ask_cli
    return parse(ask(prompt(document)))


_VERDICTS: dict = {}


def check(policy: dict, proposals) -> dict:
    """TLC's verdict for each proposed template on the deployed design."""
    out = {}
    for name in proposals:
        key = (name, bool(policy[name]))
        if key not in _VERDICTS:
            _VERDICTS[key] = T.check(name, bool(policy[name]))["verdict"]
        out[name] = _VERDICTS[key]
    return out


def evaluate(triples, extractor) -> dict:
    rows, found, right, total = [], 0, 0, 0
    for t in triples:
        proposals = list(extractor(t["document"]))
        verdicts = check(t["policy"], proposals)
        disagreements = [n for n, v in verdicts.items() if v != "PASS"]
        hit = t["planted"] in disagreements
        found += hit
        right += sum(n in t["implied"] for n in proposals)
        total += len(proposals)
        rows.append({"id": t["id"], "proposals": proposals, "disagreements": disagreements, "found_planted": hit})
    return {"recall": found / len(triples), "precision": (right / total) if total else 0.0,
            "proposals": total, "rows": rows}
