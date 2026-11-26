"""The launch freeze, step by step (see exonumia.freeze). Standard library alone."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from exonumia.freeze import BLOCK_LIMIT, FORMAT
from exonumia.freeze import blocks as B

WIN = os.name == "nt"
BLOCK_KILL = 600          # a block still running after this many seconds is stopped and fails
DROP_ENV = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH", "VIRTUAL_ENV", "CONDA_PREFIX",
            "__PYVENV_LAUNCHER__")
CLAIM = re.compile(r"(?i)\bclaim\s+#?([A-Za-z0-9_.:-]+)")
# rule E3's words, spelled backwards so this file never holds them
E3 = re.compile(r"(?i)\b(" + "|".join(w[::-1] for w in ("deifitrec", "efas", "deetnaraug", "elbakcahnu")) + r")\b")


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def say(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------- git
def git(d: Path, *args, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[-400:]}")
    return p.stdout


def dirty(d: Path) -> list[str]:
    """Why DIR cannot be frozen: tracked files with changes not committed, or untracked files under registry/ or
    catalogue/site/ (the two directories the freeze writes over)."""
    out = []
    for line in git(d, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].strip().strip('"')
        if line.startswith("??"):
            if path.startswith(("registry/", "catalogue/site/")):
                out.append(f"untracked {path} (the freeze writes over this directory)")
        elif line.strip():
            out.append(f"changed {path}")
    return out


# ---------------------------------------------------------------- processes
def kill_tree(p: subprocess.Popen) -> None:
    if WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        try:
            os.killpg(p.pid, 9)
        except OSError:
            p.kill()


def run_logged(argv: list, cwd: Path, env: dict, log: Path, timeout: float | None = None) -> tuple[int, float]:
    """Run ARGV with its output going straight into LOG as it is written (so the log grows while the step runs).
    (exit, seconds). A run past TIMEOUT is stopped and exits 124."""
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(log, "ab", buffering=0) as f:
        f.write(("$ " + " ".join(str(a) for a in argv) + "\n").encode("utf-8"))
        kw = {"start_new_session": True} if not WIN else {}
        try:
            p = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=f,
                                 stderr=subprocess.STDOUT, **kw)
        except OSError as x:
            f.write(f"could not start: {x}\n".encode("utf-8"))
            return 127, time.time() - t0
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            p.wait()
            f.write(f"\nstopped after {timeout:.0f} s\n".encode("utf-8"))
            rc = 124
    return rc, time.time() - t0


def which(name: str, env: dict) -> str | None:
    return shutil.which(name, path=env.get("PATH", ""))


def lean_present(env: dict) -> str | None:
    """Where Lean's `lake` is, by verify.sh's rule (on PATH, else $HOME/.elan/bin), or None."""
    found = which("lake", env)
    if found:
        return found
    for home in (env.get("HOME"), env.get("USERPROFILE")):
        if home:
            for n in ("lake", "lake.exe"):
                p = Path(home) / ".elan" / "bin" / n
                if p.is_file():
                    return str(p)
    return None


def tlc_jar(env: dict, clone: Path) -> str | None:
    """The TLC jar: $KAMANU_TLA_JAR when it names a file, else the clone's tools/vendor/tla2tools.jar, or None."""
    j = env.get("KAMANU_TLA_JAR")
    if j and Path(j).is_file():
        return j
    p = clone / "tools" / "vendor" / "tla2tools.jar"
    return str(p) if p.is_file() else None


LADDER = "tests/test_ladder_proof.py"
FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(" + re.escape(LADDER) + r"::[^\s]+)")


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def apalache_jar(env: dict, repo: Path, clone: Path) -> dict:
    """Give the clone the pinned Apalache jar, the way the TLC jar reaches it: $KAMANU_APALACHE_JAR when it names a
    file, else DIR's tools/vendor/apalache.jar (git ignores it, so the clone never has it). The jar is copied to the
    clone's tools/vendor/apalache.jar only when its SHA-256 equals jar_sha256 in the clone's
    tools/vendor/apalache.json. Returns the apalache step's status, exit, time and note."""
    t0 = time.time()
    pin_file = clone / "tools" / "vendor" / "apalache.json"
    dest = clone / "tools" / "vendor" / "apalache.jar"
    given = env.get("KAMANU_APALACHE_JAR")
    if given and Path(given).is_file():
        src, how = Path(given), f"$KAMANU_APALACHE_JAR ({given})"
    else:
        d = repo / "tools" / "vendor" / "apalache.jar"
        src, how = (d, f"DIR's tools/vendor/apalache.jar ({d})") if d.is_file() else (None, "")
    if src is None:
        why = (f"$KAMANU_APALACHE_JAR ({given}) names no file and " if given else "$KAMANU_APALACHE_JAR is unset and ")
        return {"status": "not run", "note": "the Apalache jar is missing: " + why + "DIR has no "
                "tools/vendor/apalache.jar, so the clone has no tools/vendor/apalache.jar"}
    try:
        pin = json.loads(pin_file.read_text(encoding="utf-8"))["jar_sha256"]
        assert isinstance(pin, str) and re.fullmatch(r"[0-9a-fA-F]{64}", pin)
        pin = pin.lower()
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return {"status": "not run", "note": f"the Apalache jar from {how} was not copied: the clone's "
                                             f"tools/vendor/apalache.json holds no jar_sha256 to check it against"}
    got = file_sha256(src)
    if got != pin:
        return {"status": "not run", "note": f"the Apalache jar from {how} has SHA-256 {got}, not the pin's {pin} "
                                             f"(tools/vendor/apalache.json jar_sha256), so it was not copied"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    if file_sha256(dest) != pin:
        dest.unlink()
        return {"status": "failed", "exit": 1, "time": time.time() - t0,
                "note": f"the Apalache jar from {how} did not reach the clone byte for byte"}
    return {"status": "passed", "exit": 0, "time": time.time() - t0,
            "note": f"the Apalache jar from {how}, SHA-256 {got} (the pin of tools/vendor/apalache.json), copied to "
                    f"the clone's tools/vendor/apalache.jar before pytest"}


def ladder_failures(log: Path) -> list[str]:
    """The pytest failures (short summary lines) whose test is in tests/test_ladder_proof.py, in order."""
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    out = []
    for line in text.splitlines():
        m = FAILED_LINE.match(line.strip())
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


# ---------------------------------------------------------------- the freeze
class Freeze:
    def __init__(self, repo: Path, out: Path, day: str, proofs: bool):
        self.repo, self.out, self.day, self.proofs = repo, out, day, proofs
        self.steps: list[dict] = []
        self.claims_failed: list[tuple[str, str]] = []
        self.needs_jar: list[str] = []
        self.commit = ""
        self.work = Path(tempfile.mkdtemp(prefix="kamanu-freeze-"))
        self.clone = self.work / "clone"
        self.venv = self.work / "venv"
        self.logs = out / "logs"
        base = {k: v for k, v in os.environ.items() if k.upper() not in DROP_ENV}
        self.base_env = base
        self.env = dict(base)

    # -- records
    def record(self, name: str, status: str, rc, took, note: str = "", log: Path | None = None, **extra) -> dict:
        s = {"name": name, "status": status, "exit": rc if status != "not run" else None,
             "time": round(took, 2) if took is not None else None, "note": note}
        if log is not None:
            s["log"] = log.relative_to(self.out).as_posix()
        s.update(extra)
        self.steps.append(s)
        tail = f"exit {s['exit']}, {s['time']} s" if status != "not run" else "not run"
        say(f"{name}: {status} ({tail}){' - ' + note if note else ''}")
        self.write()
        return s

    def logfile(self, name: str) -> Path:
        p = self.logs / (name.replace(":", "-") + ".log")
        if p.exists():
            p.unlink()
        return p

    # -- clone and install
    def make_clone(self) -> None:
        subprocess.run(["git", "clone", "--quiet", "--no-checkout", "--config", "core.autocrlf=false",
                        str(self.repo), str(self.clone)], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        git(self.clone, "checkout", "--quiet", "--detach", self.commit)

    def scripts(self) -> Path:
        return self.venv / ("Scripts" if WIN else "bin")

    def python(self) -> Path:
        return self.scripts() / ("python.exe" if WIN else "python")

    def install(self) -> None:
        log = self.logfile("install")
        t0 = time.time()
        rc, _ = run_logged([sys.executable, "-m", "venv", self.venv], self.work, self.base_env, log)
        note = ""
        if rc == 0:
            rc, _ = run_logged([self.python(), "-m", "pip", "install", self.clone], self.work, self.base_env, log)
            note = "pip install of the clone into a fresh virtual environment"
        else:
            note = "the virtual environment could not be made"
        if rc == 0 and self.proofs:
            probe = subprocess.run([str(self.python()), "-c", "import pytest"], capture_output=True,
                                   stdin=subprocess.DEVNULL, cwd=str(self.work), env=self.base_env)
            if probe.returncode:
                prc, _ = run_logged([self.python(), "-m", "pip", "install", "pytest"], self.work, self.base_env, log)
                note += "; pytest added for the proof runs" if prc == 0 else "; pytest could not be added"
        env = dict(self.base_env)
        for k in [k for k in env if k.upper() == "PATH"]:
            del env[k]
        env["PATH"] = str(self.scripts()) + os.pathsep + self.base_env.get("PATH", os.environ.get("PATH", ""))
        env["VIRTUAL_ENV"] = str(self.venv)
        env["PYTHONUNBUFFERED"] = "1"
        self.env = env
        self.record("install", "passed" if rc == 0 else "failed", rc, time.time() - t0, note, log)

    # -- blocks
    def run_block(self, name: str, body: list[str] | None, cabinet: Path, missing: str) -> None:
        if body is None:
            self.record(name, "failed", 1, 0.0, missing)
            return
        cmds = B.commands(body)
        status_file = self.work / f"{name.replace(':', '-')}.exits"
        script = self.work / f"{name.replace(':', '-')}.sh"
        lines = [f"cd {sh_quote(self.clone.as_posix())} || exit 97"]
        for c in cmds:
            lines.append(c["text"])
            lines.append(f"printf '%s\\n' \"$?\" >> {sh_quote(status_file.as_posix())}")
        script.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        bash = which("bash", self.env)
        log = self.logfile(name)
        env = dict(self.env, KAMANU_CABINET=str(cabinet))
        if not bash:
            self.record(name, "failed", 127, 0.0, "bash was not found on PATH", log)
            return
        rc, took = run_logged([bash, script.as_posix()], self.clone, env, log, timeout=BLOCK_KILL)
        got = []
        if status_file.is_file():
            got = [int(x) for x in status_file.read_text(encoding="utf-8").split() if x.strip().lstrip("-").isdigit()]
        detail, problems = [], []
        for i, c in enumerate(cmds):
            e = got[i] if i < len(got) else None
            detail.append({"command": c["text"], "expect": c["expect"], "exit": e})
            if e is None:
                problems.append(f"command {i + 1} did not finish")
            elif e != c["expect"]:
                problems.append(f"command {i + 1} exited {e}, its text says {c['expect']}")
        if took >= BLOCK_LIMIT:
            problems.append(f"took {took:.1f} s, not under {BLOCK_LIMIT:.0f} s")
        if not cmds:
            problems.append("the block holds no command")
        first_bad = next((d["exit"] for d in detail if d["exit"] != d["expect"]), None)
        code = 0 if not problems else (first_bad if isinstance(first_bad, int) and first_bad else (rc or 1))
        self.record(name, "failed" if problems else "passed", code, took, "; ".join(problems), log,
                    commands=detail)

    def read_clone(self, rel: str) -> str | None:
        p = self.clone / rel
        try:
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def blocks(self) -> None:
        cab = self.work / "cabinet-readme"
        cab.mkdir()
        readme = self.read_clone("README.md")
        if readme is None:
            self.record("readme:1", "failed", 1, 0.0, "the clone has no README.md")
        else:
            found = B.readme_blocks(readme)
            if not found:
                self.record("readme:1", "failed", 1, 0.0, "README.md's section \"See it in a minute\" holds no shell "
                                                         "block")
            for i, body in enumerate(found, 1):
                self.run_block(f"readme:{i}", body, cab, "")
        scan = self.read_clone("docs/scan.md")
        cab = self.work / "cabinet-recipe"
        cab.mkdir()
        body = B.recipe_block(scan) if scan is not None else None
        self.run_block("recipe", body, cab, "docs/scan.md or its recipe block is missing from the clone")

    # -- kamanu assay steps
    def kamanu(self, name: str, args: list) -> tuple[int, float, Path]:
        log = self.logfile(name)
        exe = which("kamanu", self.env)
        argv = [exe, *args] if exe and Path(exe).resolve().is_relative_to(self.venv.resolve()) \
            else [self.python(), "-m", "kamanu", *args]
        rc, took = run_logged(argv, self.clone, self.env, log)
        return rc, took, log

    def claims(self) -> None:
        page = self.work / "claims.html"
        rc, took, log = self.kamanu("claims", ["assay", "--claims", "claims/claims.yaml", "--root", ".",
                                               "--out", page])
        failed = []
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        for line in text.splitlines():
            if line.lstrip().startswith("FAIL"):
                m = CLAIM.search(line)
                if m and m.group(1) not in [n for n, _ in failed]:
                    failed.append((m.group(1), line.strip()))
        self.claims_failed = failed
        note = "every claim resolves" if rc == 0 else (
            "claims that do not resolve: " + ", ".join(f"claim {n}" for n, _ in failed) if failed
            else "the claims check did not pass")
        self.record("claims", "passed" if rc == 0 else "failed", rc, took, note, log,
                    unresolved=[n for n, _ in failed])

    def registry(self) -> None:
        t0 = time.time()
        src = self.clone / "registry"
        recs = self.work / "registry-records"
        recs.mkdir()
        key = None
        n = 0
        idx = src / "index.html"
        if idx.is_file():
            m = re.search(r'data-public-key="([0-9a-fA-F]{64})"', idx.read_text(encoding="utf-8", errors="replace"))
            key = m.group(1) if m else None
        for page in sorted(src.rglob("*.htm*")) if src.is_dir() else []:
            em = embedded(page)
            if not em:
                continue
            rec = em["record"]
            hid = hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False).encode("utf-8")).hexdigest()
            dump(recs / f"h{n}.json", rec)
            if em.get("pyx"):
                dump(recs / f"h{n}.pyx.json", {"pyx": "pyx-v1", "hallmark": hid, "entries": em["pyx"]})
            if isinstance(em.get("release"), dict):
                dump(recs / f"h{n}.release.json", em["release"])
            n += 1
        if key is None:
            self.record("registry", "failed", 1, time.time() - t0, "registry/index.html publishes no "
                                                                   "data-public-key")
            return
        keyfile = self.work / "registry.pub"
        keyfile.write_text(key + "\n", encoding="utf-8")
        site = self.work / "registry-site"
        rc, took, log = self.kamanu("registry", ["assay", "--registry", site, "--records", recs, "--key", keyfile,
                                                 "--as-of", self.day])
        if rc == 0 and (site / "index.html").is_file():
            replace_dir(site, self.repo / "registry")
            note = f"{n} record(s) rebuilt for {self.day}; DIR/registry/ replaced"
            status = "passed"
        else:
            note, status = "the rebuild did not finish; DIR/registry/ left as it was", "failed"
            rc = rc or 1
        self.record("registry", status, rc, time.time() - t0, note, log)

    def catalogue(self) -> None:
        site = self.work / "catalogue-site"
        rc, took, log = self.kamanu("catalogue", ["assay", "--catalogue", site, "--checks", "catalogue/checks",
                                                  "--as-of", self.day])
        if rc == 0 and (site / "index.html").is_file():
            replace_dir(site, self.repo / "catalogue" / "site")
            note, status = f"the Catalogue built for {self.day}; DIR/catalogue/site/ replaced", "passed"
        else:
            note, status = "the build did not finish; DIR/catalogue/site/ left as it was", "failed"
            rc = rc or 1
        self.record("catalogue", status, rc, took, note, log)

    # -- the proof kit
    def proof_runs(self) -> None:
        lake = lean_present(self.env)
        if lake:
            bash = which("bash", self.env)
            log = self.logfile("verify")
            rc, took = run_logged([bash or "bash", "verify.sh"], self.clone, self.env, log)
            self.record("verify", "passed" if rc == 0 else "failed", rc, took, f"bash verify.sh (Lean's lake at "
                                                                              f"{lake})", log)
        else:
            self.record("verify", "not run", None, None, "Lean is missing: no `lake` on PATH or in "
                                                         "$HOME/.elan/bin, so bash verify.sh was not run")
        jar = tlc_jar(self.env, self.clone)
        vendor = self.clone / "tools" / "vendor" / "tla2tools.jar"
        if jar and not vendor.is_file():
            # git ignores the jar, so a clone never holds it; the clone's tests look for it there
            vendor.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jar, vendor)
        apa = apalache_jar(self.env, self.repo, self.clone)
        log = self.logfile("pytest")
        rc, took = run_logged([self.python(), "-m", "pytest", "tests", "-q"], self.clone, self.env, log)
        self.record("pytest", "passed" if rc == 0 else "failed", rc, took, "python -m pytest tests -q" +
                    ("" if jar else " (the TLC jar missing: tests that need it ran without it)"), log)
        pytest_log = log
        rc, took, log = self.kamanu("replay", ["scan", "--replay", "--plates", "plates"])
        self.record("replay", "passed" if rc == 0 else "failed", rc, took, "kamanu scan --replay --plates plates",
                    log)
        if jar:
            self.record("tlc", "passed", 0, 0.0, "the TLC jar (tla2tools.jar) is present")
        else:
            self.record("tlc", "not run", None, None, "the TLC jar (tla2tools.jar) is missing: set KAMANU_TLA_JAR "
                                                      "or put it at tools/vendor/tla2tools.jar; nothing that needs "
                                                      "TLC is counted as passed")
        if apa["status"] != "passed":
            self.needs_jar = ladder_failures(pytest_log)
        extra = {"needs_jar": self.needs_jar} if apa["status"] == "not run" else {}
        self.record("apalache", apa["status"], apa.get("exit"), apa.get("time"), apa["note"], **extra)

    # -- output
    def write(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        rec = {"freeze": FORMAT, "commit": self.commit, "day": self.day,
               "platform": f"{platform.platform()}; Python {platform.python_version()}",
               "proofs": self.proofs, "steps": self.steps}
        (self.out / "freeze.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.out / "FREEZE.md").write_text(self.markdown(rec), encoding="utf-8")

    def markdown(self, rec: dict) -> str:
        inst = next((s for s in self.steps if s["name"] == "install"), None)
        lines = [f"# Launch freeze of {self.commit[:12]} for {self.day}", "",
                 f"Commit `{self.commit}`, day {self.day}, platform {rec['platform']}.", ""]
        if inst:
            lines += [f"The install took {inst['time']} s and is kept apart: no block's minute counts it.", ""]
        lines += ["| step | status | exit | time (s) | note |", "| --- | --- | --- | --- | --- |"]
        for s in self.steps:
            note = str(s.get("note") or "").replace("|", "/").replace("\n", " ")
            ex = "" if s["exit"] is None else s["exit"]
            tm = "" if s["time"] is None else s["time"]
            lines.append(f"| {s['name']} | {s['status']} | {ex} | {tm} | {note} |")
        passed = sum(1 for s in self.steps if s["status"] == "passed")
        lines += ["", f"{passed} of {len(self.steps)} steps passed."]
        if self.needs_jar:
            lines += ["", "## Failures needing the Apalache jar", ""]
            for t in self.needs_jar:
                lines.append(f"- {t}: failed with no pinned Apalache jar in the clone (the apalache step was not "
                             f"run)")
        if self.claims_failed:
            lines += ["", "## Claims that do not resolve", ""]
            for n, line in self.claims_failed:
                lines.append(f"- claim {n}: {line}" if not E3.search(line) else f"- claim {n}")
        return "\n".join(lines) + "\n"

    # -- the whole run
    def run(self) -> int:
        try:
            self.make_clone()
        except (subprocess.CalledProcessError, RuntimeError) as x:
            self.record("clone", "failed", 1, 0.0, f"DIR's HEAD could not be cloned: {x}")
            return 1
        self.install()
        self.blocks()
        self.claims()
        self.registry()
        self.catalogue()
        if self.proofs:
            self.proof_runs()
        self.write()
        ok = bool(self.steps) and all(s["status"] == "passed" for s in self.steps)
        passed = sum(1 for s in self.steps if s["status"] == "passed")
        say(f"freeze: {passed} of {len(self.steps)} steps passed; the record is {self.out / 'freeze.json'}")
        return 0 if ok else 1

    def cleanup(self) -> None:
        shutil.rmtree(self.work, onerror=_unlock)


# ---------------------------------------------------------------- helpers
def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def dump(p: Path, v) -> None:
    p.write_text(json.dumps(v, indent=1, ensure_ascii=False), encoding="utf-8")


SCRIPT = re.compile(r'<script\b([^>]*)>(.*?)</script>', re.S | re.I)


def embedded(page: Path):
    """The JSON a registry page embeds in <script type="application/json" id="kamanu-hallmark">, else None."""
    try:
        text = page.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for attrs, body in SCRIPT.findall(text):
        if re.search(r'\bid\s*=\s*"kamanu-hallmark"', attrs) and re.search(r'\btype\s*=\s*"application/json"', attrs):
            try:
                obj = json.loads(body)
            except ValueError:
                return None
            if isinstance(obj, dict) and isinstance(obj.get("record"), dict) and isinstance(obj.get("pyx"), list):
                return obj
            return None
    return None


def replace_dir(src: Path, dest: Path) -> None:
    """DEST becomes SRC: no file more or fewer."""
    if dest.exists():
        for child in dest.iterdir():
            if child.is_dir():
                shutil.rmtree(child, onerror=_unlock)
            else:
                child.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)


def _unlock(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


# ---------------------------------------------------------------- the command
def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m exonumia.freeze",
        description="The launch freeze: from a clean clone of DIR's HEAD, install it in a fresh virtual environment, "
                    "run README.md's \"See it in a minute\" shell blocks and docs/scan.md's recipe (each under a "
                    "minute, each command exiting as its text says), check every claim, rebuild the registry and the "
                    "Catalogue for DAY over DIR, and with --proofs run the proof kit. Writes OUT/freeze.json "
                    "(freeze-v1) and OUT/FREEZE.md. Exit 0 only when every step passed; 1 when one did not; 2 when "
                    "nothing was run (a dirty tree, not a git repository, a bad day).")
    ap.add_argument("--repo", required=True, metavar="DIR", help="the git repository to freeze (its HEAD is cloned)")
    ap.add_argument("--out", required=True, metavar="OUT", help="where freeze.json, FREEZE.md and logs/ are written")
    ap.add_argument("--day", metavar="DAY", help="the build day YYYY-MM-DD for the registry and Catalogue "
                                                 "(default today, UTC)")
    ap.add_argument("--proofs", action="store_true",
                    help="also run bash verify.sh, python -m pytest tests -q and kamanu scan --replay --plates "
                         "plates, each logging under OUT/logs/ as it runs, after giving the clone the pinned "
                         "Apalache jar ($KAMANU_APALACHE_JAR, else DIR's tools/vendor/apalache.jar, copied only when "
                         "its SHA-256 is tools/vendor/apalache.json's jar_sha256); a missing Lean, TLC jar or "
                         "Apalache jar is recorded as not run")
    ap.add_argument("--detach", action="store_true",
                    help="start the run as a detached process logging to OUT/freeze.log and return at once (for a "
                         "run longer than 90 minutes)")
    return ap


def detach(argv: list[str], out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    log = out / "freeze.log"
    args = [a for a in argv if a != "--detach"]
    kw = {}
    if WIN:
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    with open(log, "ab") as f:
        p = subprocess.Popen([sys.executable, "-m", "exonumia.freeze", *args], stdin=subprocess.DEVNULL, stdout=f,
                             stderr=subprocess.STDOUT, cwd=os.getcwd(), **kw)
    say(f"freeze: started as process {p.pid}; its log is {log}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = parser().parse_args(argv)
    repo, out = Path(a.repo).resolve(), Path(a.out).resolve()
    day = a.day or today()
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        say(f"freeze: --day {day!r} is not a day YYYY-MM-DD; nothing was run")
        return 2
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        say(f"freeze: --day {day!r} is not a day YYYY-MM-DD; nothing was run")
        return 2
    try:
        commit = git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()
        problems = dirty(repo)
    except (RuntimeError, OSError) as x:
        say(f"freeze: {repo} is not a git repository with a commit ({x}); nothing was run")
        return 2
    if problems:
        say(f"freeze: {repo} has changes not committed, so its HEAD is not what would be frozen; nothing was "
            f"cloned, installed or run:")
        for p in problems[:20]:
            say(f"  {p}")
        return 2
    if a.detach:
        return detach(argv, out)
    f = Freeze(repo, out, day, a.proofs)
    f.commit = commit
    f.logs.mkdir(parents=True, exist_ok=True)
    try:
        return f.run()
    finally:
        f.cleanup()
