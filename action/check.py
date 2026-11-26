"""The action's check step: `kamanu check` on the .dw files a pull request changes.

The changed files come from git, not the GitHub API: the pull request's own changes are
`git diff <base.sha>...<head.sha>` (three dots: against the merge base, so commits that land on
the base branch after the pull request branched are not the pull request's). Deleted files are
not checked. Each changed policy is checked against the engine the workflow names
(KAMANU_ENGINE: a profile JSON's path in the repository, or a built-in profile name), from the
workspace, so its SARIF names it by its repository path.

The per-policy SARIF files are merged into one file with one run (code scanning refuses an
upload where two runs share a tool and category), each result's uri made relative to the
workspace. The step itself succeeds whenever it could run check; it reports check's exit code
(the largest over the changed policies, 0 when none) as the output `exit-code`, and the
action's last step fails with it after the upload.

Outputs (GITHUB_OUTPUT): exit-code, sarif (the merged file's path), policies (one per line).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


# ---------------------------------------------------------------- changed files
def git(ws: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=ws, capture_output=True,
                          check=check)


def have_commit(ws: Path, sha: str) -> bool:
    return git(ws, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0


def ensure_commits(ws: Path, *shas: str) -> None:
    """Fetch what a shallow checkout lacks (actions/checkout's default depth is 1)."""
    missing = [s for s in shas if s and not have_commit(ws, s)]
    if missing:
        git(ws, "fetch", "--no-tags", "--quiet", "origin", *missing, check=False)
    if git(ws, "rev-parse", "--is-shallow-repository", check=False).stdout.strip() == b"true" and shas[0]:
        # three-dot diffs need the merge base
        if git(ws, "merge-base", *[s for s in shas if s], check=False).returncode != 0:
            git(ws, "fetch", "--no-tags", "--quiet", "--unshallow", "origin", check=False)


def changed_files(ws: Path, base: str, head: str) -> list[str]:
    """Repository paths (posix) that head adds, modifies, renames or copies relative to its merge
    base with base."""
    ensure_commits(ws, base, head)
    p = git(ws, "diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", f"{base}...{head}")
    return [f for f in p.stdout.decode("utf-8").split("\0") if f]


def revisions(event: dict) -> tuple[str, str] | None:
    """(base, head) for the event, or None when the event names no comparison."""
    pr = event.get("pull_request")
    if isinstance(pr, dict):
        base = ((pr.get("base") or {}).get("sha")) or ""
        head = ((pr.get("head") or {}).get("sha")) or ""
        if base and head:
            return base, head
    before, after = event.get("before"), event.get("after")
    if before and after and set(before) != {"0"}:
        return before, after
    return None


def policies(ws: Path, event: dict) -> list[str]:
    revs = revisions(event)
    if revs is None:
        print("::warning::the event names no base and head to compare; no policy checked", flush=True)
        return []
    return sorted(f for f in changed_files(ws, *revs)
                  if f.lower().endswith(".dw") and (ws / f).is_file())


# ---------------------------------------------------------------- SARIF
def relative_uri(uri: str, ws: Path) -> str:
    """uri relative to the workspace (posix) when it names a file inside it, else uri."""
    u = uri
    if u.lower().startswith("file:"):
        from urllib.parse import unquote, urlparse
        u = unquote(urlparse(u).path)
        if len(u) > 2 and u[0] == "/" and u[2] == ":":
            u = u[1:]
    p = Path(u)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(ws.resolve()).as_posix()
        except ValueError:
            return uri
    s = u.replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return str(PurePosixPath(s))


def empty_sarif(driver: dict | None = None) -> dict:
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0",
            "runs": [{"tool": {"driver": driver or {"name": "kamanu", "rules": []}}, "results": []}]}


def merge(docs: list[dict], ws: Path) -> dict:
    """One SARIF document with one run holding every result of every run of docs: the first
    driver, the union of the rules (by id), result uris relative to the workspace."""
    driver, rules, index = None, [], {}
    results = []
    for doc in docs:
        for run in doc.get("runs") or []:
            d = ((run.get("tool") or {}).get("driver")) or {}
            if driver is None:
                driver = {k: v for k, v in d.items() if k != "rules"}
            remap = {}
            for i, rule in enumerate(d.get("rules") or []):
                rid = rule.get("id")
                if rid not in index:
                    index[rid] = len(rules)
                    rules.append(rule)
                remap[i] = index[rid]
            for r in run.get("results") or []:
                r = json.loads(json.dumps(r))
                if "ruleIndex" in r and r["ruleIndex"] in remap:
                    r["ruleIndex"] = remap[r["ruleIndex"]]
                elif "ruleIndex" in r:
                    del r["ruleIndex"]
                for loc in r.get("locations") or []:
                    art = (loc.get("physicalLocation") or {}).get("artifactLocation")
                    if isinstance(art, dict):
                        if "uriBaseId" in art:
                            base = ((run.get("originalUriBaseIds") or {}).get(art["uriBaseId"]) or {}).get("uri")
                            if base and "uri" in art:
                                art["uri"] = base + art["uri"]
                            del art["uriBaseId"]
                        if "index" in art and "uri" not in art:
                            arts = run.get("artifacts") or []
                            if 0 <= art["index"] < len(arts):
                                art["uri"] = ((arts[art["index"]] or {}).get("location") or {}).get("uri")
                        art.pop("index", None)
                        if art.get("uri"):
                            art["uri"] = relative_uri(art["uri"], ws)
                results.append(r)
    out = empty_sarif(dict(driver or {"name": "kamanu"}, rules=rules))
    out["runs"][0]["results"] = results
    return out


# ---------------------------------------------------------------- the step
def check_one(ws: Path, policy: str, engine: str, out: Path) -> tuple[int, dict | None]:
    cmd = [sys.executable, "-m", "kamanu.cli", "check", policy, "--engine", engine, "--out", str(out)]
    print(f"::group::kamanu check {policy} --engine {engine}", flush=True)
    p = subprocess.run(cmd, cwd=ws)
    print("::endgroup::", flush=True)
    print(f"kamanu check {policy}: exit {p.returncode}", flush=True)
    sarif = out / "kamanu.sarif"
    if not sarif.is_file():
        print(f"::error file={policy}::kamanu check wrote no SARIF (exit {p.returncode})", flush=True)
        return p.returncode, None
    return p.returncode, json.loads(sarif.read_text(encoding="utf-8"))


def write_outputs(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        for k, v in values.items():
            print(f"{k}={v}")
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in values.items():
            if "\n" in v:
                delim = f"KAMANU_{uuid.uuid4().hex}"
                f.write(f"{k}<<{delim}\n{v}\n{delim}\n")
            else:
                f.write(f"{k}={v}\n")


def summary(lines: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def main() -> int:
    ws = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    engine = (os.environ.get("KAMANU_ENGINE") or "").strip()
    if not engine:
        print("::error::the action's input `engine` is empty", flush=True)
        return 2
    ev_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(ev_path).read_text(encoding="utf-8")) if ev_path and Path(ev_path).is_file() else {}
    temp = Path(os.environ.get("RUNNER_TEMP") or ws / ".kamanu-tmp") / f"kamanu-{uuid.uuid4().hex[:8]}"
    temp.mkdir(parents=True, exist_ok=True)

    todo = policies(ws, event)
    print(f"changed policies: {todo or 'none'}", flush=True)
    codes, docs = [], []
    for i, pol in enumerate(todo):
        rc, doc = check_one(ws, pol, engine, temp / f"check-{i}")
        codes.append(rc)
        if doc is not None:
            docs.append(doc)
    merged = merge(docs, ws) if docs else empty_sarif()
    sarif_dir = temp / "sarif"
    sarif_dir.mkdir()
    sarif = sarif_dir / "kamanu.sarif"
    sarif.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    rc = max(codes, default=0)
    counted = sum(1 for r in merged["runs"][0]["results"] if r.get("level", "warning") not in ("note", "none"))
    summary([f"### kamanu check (engine `{engine}`)", "",
             *([", ".join(f"`{p}` exit {c}" for p, c in zip(todo, codes))] if todo else []),
             *([] if todo else ["No .dw policy changed."]), "",
             f"{counted} finding(s); exit code {rc}."])
    write_outputs({"exit-code": str(rc), "sarif": sarif.as_posix(), "policies": "\n".join(todo)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
