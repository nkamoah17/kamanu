"""`kamanu assay --claims FILE --root DIR --out PAGE` (X1c): every sentence said in public, checked against the
tree it is said of, and written as one page.

The claims file (claims/claims.yaml) is {"claims": [claim, ...]}. A claim:

    id          its row in the source's table (1 to 9)
    sentence    what is said in public
    level       a level (T2's: MODEL_PROVEN ... UNKNOWN), or "commitment" for a promise that is not a level
    scope       optional: what the level is for ("for the design")
    backing     what stands behind it, each item one of
                  {theorem: NAME}            MODEL_PROVEN when lean/Audit.lean audits NAME (a `#print axioms` line,
                                             up to a namespace an `open` line opens) and a file under lean/ declares
                                             it (`theorem` or `lemma`); not resolved otherwise
                  {record: PATH, sha256: H}  a file of the tree whose sha256 is H (CRLF read as LF also counts);
                                             its level is its own top-level "level" when it is JSON with one,
                                             else TESTED: a record is a fact about a run. Optional "quote": dotted
                                             paths into the JSON whose values the page prints (computed, never typed)
                  {link: NAME}               a link of evidence/levels/links.json: MODEL_PROVEN when it is proved,
                                             names theorems all declared under lean/, and its lean_sha256 is the
                                             tree's (T1's hash of lean/); TESTED otherwise
                  {run: [kamanu, ARG...], exit: N, shows: [S...]}
                                             `kamanu ARGS` run from the tree's root exits N and prints every S
                                             (stdout and stderr); TESTED
    numbers     optional runs whose figures the page shows (they do not count for the level)
    travels     what must travel with it: [{name, status: proved | measured | assumed | stated, value, and for
                measured: trials and date}]
    neighbour   a backing item that is not one of its own, plus "drops": the hypothesis whose dropping makes the
                claim fail (every claim but a commitment)
    cites       optional https addresses
    counsel     optional: a file the owner adds ({read: YYYY-MM-DD, by}); until it exists the page says
                "terms pending"
    waits       optional {file, says}: the claim is worded for a tree where FILE is absent (a card not yet
                accepted). The page prints SAYS; once FILE exists the claim fails until its entry is rewritten

A claim resolves when every item of its backing, numbers and neighbour resolves and its level is not above the
weakest level of its backing. The check prints one FAIL line per problem, each naming its claim ("claim N"),
exits 1 and writes no page; when every claim resolves it writes PAGE (the same bytes for the same tree: nothing
in it depends on the time, the directory or the run's own timings) and exits 0. An unreadable FILE exits 3.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

LEVELS = ("MODEL_PROVEN", "EXHAUSTIVE_FINITE_PASS", "BOUNDED_PASS", "TESTED", "ASSUMED", "REFUTED", "UNKNOWN")
COMMITMENT = "commitment"
TRAVEL = ("proved", "measured", "assumed", "stated")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SRC = Path(__file__).resolve().parents[2]          # the tree this kamanu runs from (a RUN uses its code)
RUN_TIMEOUT = 1800


class Unreadable(Exception):
    pass


def weakest(levels) -> str:
    return max(levels, key=LEVELS.index)


def stronger(a: str, b: str) -> bool:
    return LEVELS.index(a) < LEVELS.index(b)


# ---------------------------------------------------------------- Lean: the audit's list and the declarations
def _strip_comments(text: str) -> str:
    return re.sub(r"/-.*?-/", " ", text, flags=re.S)


def audit_list(root: Path) -> tuple[list[str], set[str]]:
    """(the names lean/Audit.lean's `#print axioms` lines give, as written; the namespaces its `open` lines open)."""
    try:
        text = (root / "lean" / "Audit.lean").read_text(encoding="utf-8")
    except OSError:
        return [], set()
    prints, opens = [], set()
    for line in _strip_comments(text).splitlines():
        s = line.split("--", 1)[0].strip()
        if s.startswith("open "):
            opens.update(w for w in s.split()[1:] if re.match(r"^[A-Za-z_][\w.']*$", w))
        m = re.match(r"^#print\s+axioms\s+(\S+)", s)
        if m:
            prints.append(m.group(1))
    return prints, opens


def audited(name: str, prints: list[str], opens: set[str]) -> bool:
    for m in prints:
        if m == name or any(name == f"{o}.{m}" or m == f"{o}.{name}" for o in opens):
            return True
    return False


DECL = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable)\s+)*(?:theorem|lemma)\s+"
                  r"([^\s:(\[{]+)", re.M)


def short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def declarations(root: Path) -> dict[str, list[str]]:
    """{last dotted component: [file, ...]} of every theorem and lemma under lean/ (lean/.lake left out)."""
    lean = root / "lean"
    out: dict[str, list[str]] = {}
    if not lean.is_dir():
        return out
    for p in sorted(lean.rglob("*.lean")):
        if ".lake" in p.relative_to(lean).parts:
            continue
        text = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for d in DECL.findall(text):
            out.setdefault(short(d), []).append(p.relative_to(root).as_posix())
    return out


def lean_hash(root: Path) -> str | None:
    if not (root / "lean").is_dir():
        return None
    from kamanu.levels import lean_sha256
    return lean_sha256(root / "lean")


# ---------------------------------------------------------------- the tree a claims file is checked against
class Tree:
    def __init__(self, root: Path):
        self.root = root
        self.prints, self.opens = audit_list(root)
        self.decl = declarations(root)
        self._links = None
        self._lean = None
        self._runs: dict = {}

    def links(self) -> dict:
        if self._links is None:
            try:
                d = json.loads((self.root / "evidence" / "levels" / "links.json").read_text(encoding="utf-8"))
                self._links = d.get("links", {}) if isinstance(d, dict) and isinstance(d.get("links"), dict) else {}
            except (OSError, ValueError):
                self._links = {}
        return self._links

    def lean(self) -> str | None:
        if self._lean is None:
            self._lean = lean_hash(self.root) or ""
        return self._lean or None

    def run(self, argv: list[str]) -> tuple[int, str]:
        """`kamanu ARGS` from this kamanu's own source, in the tree's root: (exit code, stdout and stderr)."""
        key = json.dumps(argv)
        if key not in self._runs:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            code = "import sys; sys.argv[0] = 'kamanu'; from kamanu.hunt.cli import main; sys.exit(main())"
            try:
                p = subprocess.run([sys.executable, "-c", code, *argv[1:]], cwd=self.root, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=RUN_TIMEOUT, env=env)
                self._runs[key] = (p.returncode, p.stdout + p.stderr)
            except (OSError, subprocess.SubprocessError) as e:
                self._runs[key] = (-1, f"could not run: {e}")
        return self._runs[key]


def _sha(path: Path) -> set[str]:
    b = path.read_bytes()
    return {hashlib.sha256(b).hexdigest(), hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def at(obj, dotted: str):
    """The value at a dotted path of a JSON object, or a KeyError."""
    for part in dotted.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            raise KeyError(dotted)
    return obj


def is_run(item) -> bool:
    return isinstance(item, dict) and "run" in item


def label(item) -> str:
    if not isinstance(item, dict):
        return repr(item)
    for k in ("theorem", "record", "link"):
        if k in item:
            return str(item[k])
    if is_run(item) and isinstance(item["run"], list):
        return " ".join(map(str, item["run"]))
    return repr(item)


def resolve(tree: Tree, item) -> tuple[str | None, list[str], dict]:
    """(the item's level or None, every way it does not resolve, what the page says of it)."""
    if not isinstance(item, dict):
        return None, [f"{item!r} is not a mapping"], {}
    if "theorem" in item:
        n = item["theorem"]
        if not (isinstance(n, str) and n.strip()):
            return None, [f"theorem {n!r} is not a name"], {}
        p = []
        if not audited(n, tree.prints, tree.opens):
            p.append(f"theorem {n} is not audited: lean/Audit.lean has no `#print axioms` line for it")
        files = tree.decl.get(short(n), [])
        if not files:
            p.append(f"theorem {n} is declared in no file under lean/")
        return "MODEL_PROVEN", p, {"kind": "theorem", "files": files}
    if "record" in item:
        path, h = item.get("record"), item.get("sha256")
        if not (isinstance(path, str) and path.strip()):
            return None, [f"record {path!r} is not a path"], {}
        f = tree.root / path
        try:
            f.resolve().relative_to(tree.root.resolve())
        except ValueError:
            return None, [f"record {path} is outside the tree"], {}
        if not f.is_file():
            return None, [f"record {path} does not exist"], {}
        if not (isinstance(h, str) and h.lower() in _sha(f)):
            return None, [f"record {path}: sha256 {h!r} is not the file's hash"], {}
        d = _read_json(f) if f.suffix == ".json" else None
        lv = d.get("level") if isinstance(d, dict) and d.get("level") in LEVELS else "TESTED"
        quoted, p = [], []
        for q in item.get("quote") or []:
            try:
                quoted.append((q, at(d, q)))
            except (KeyError, TypeError):
                p.append(f"record {path} has no field {q!r} to quote")
        return lv, p, {"kind": "record", "quoted": quoted}
    if "link" in item:
        n = item["link"]
        ln = tree.links().get(n) if isinstance(n, str) else None
        if not isinstance(ln, dict):
            return None, [f"link {n!r} is not in evidence/levels/links.json"], {}
        why = []
        if ln.get("status") != "proved":
            why.append(f"its status is {ln.get('status')!r}")
        ths = ln.get("theorems") if isinstance(ln.get("theorems"), list) else []
        if not ths:
            why.append("it names no theorem")
        why += [f"{t} is declared nowhere under lean/" for t in ths if short(str(t)) not in tree.decl]
        if ln.get("lean_sha256") != tree.lean():
            why.append("its lean_sha256 is not the hash of this tree's lean/")
        return ("TESTED" if why else "MODEL_PROVEN"), [], {"kind": "link", "why": why, "theorems": ths}
    if is_run(item):
        argv, ex, shows = item.get("run"), item.get("exit"), item.get("shows")
        if not (isinstance(argv, list) and len(argv) >= 2 and argv[0] == "kamanu" and all(isinstance(a, str) for a in argv)):
            return None, [f"run {argv!r} is not [kamanu, ARG, ...]"], {}
        if not (isinstance(ex, int) and not isinstance(ex, bool) and isinstance(shows, list) and shows
                and all(isinstance(s, str) and s.strip() for s in shows)):
            return None, [f"run {' '.join(argv)}: exit {ex!r} or shows {shows!r} is not an integer and strings"], {}
        rc, text = tree.run(argv)
        p = []
        if rc != ex:
            p.append(f"run `{' '.join(argv)}` exits {rc}, not {ex}")
        p += [f"run `{' '.join(argv)}` does not print {s!r}" for s in shows if s not in text]
        return "TESTED", p, {"kind": "run"}
    return None, [f"{item!r} is none of theorem, record, link or run"], {}


def check_claim(tree: Tree, c) -> tuple[list[str], dict]:
    """(every way claim c does not resolve, what the page says of it)."""
    if not isinstance(c, dict):
        return [f"{c!r} is not a mapping"], {}
    p, view = [], {"backing": [], "numbers": [], "neighbour": None}
    s = c.get("sentence")
    if not (isinstance(s, str) and len(s.split()) >= 4):
        p.append(f"its sentence {s!r} is not a sentence")
    lv = c.get("level")
    commitment = lv == COMMITMENT
    if not commitment and lv not in LEVELS:
        p.append(f"its level {lv!r} is neither one of {', '.join(LEVELS)} nor {COMMITMENT!r}")
    backing = c.get("backing") or []
    if not isinstance(backing, list):
        p.append("its backing is not a list")
        backing = []
    if commitment and backing:
        p.append("a commitment is not a level, so nothing may stand behind it as backing")
    if not commitment and not backing:
        p.append("nothing stands behind it (backing is empty)")
    levels = []
    for it in backing:
        l, q, v = resolve(tree, it)
        p += [f"backing: {x}" for x in q]
        if l:
            levels.append(l)
        view["backing"].append((it, l, v))
    if lv in LEVELS and levels and stronger(lv, weakest(levels)):
        p.append(f"its level {lv} is above the weakest level of its backing, {weakest(levels)}")
    for it in c.get("numbers") or []:
        if not is_run(it):
            p.append(f"numbers: {it!r} is not a run")
            continue
        p += [f"numbers: {x}" for x in resolve(tree, it)[1]]
        view["numbers"].append(it)
    tr = c.get("travels")
    if not (isinstance(tr, list) and tr):
        p.append("nothing travels with it (travels is empty)")
    else:
        for t in tr:
            if not (isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
                    and t.get("status") in TRAVEL):
                p.append(f"travels: {t!r} is not {{name, status: {' | '.join(TRAVEL)}}}")
            elif t["status"] == "measured" and not (isinstance(t.get("trials"), int) and t["trials"] > 0
                                                    and isinstance(t.get("date"), str) and DAY.match(t["date"])):
                p.append(f"travels: {t['name']} is measured without its trial count and date")
    nb = c.get("neighbour")
    if commitment:
        if nb is not None:
            p.append("a commitment has no hypotheses to drop, so it has no neighbour")
    elif not isinstance(nb, dict):
        p.append("it has no failing neighbour")
    else:
        if not (isinstance(nb.get("drops"), str) and nb["drops"].strip()):
            p.append("its neighbour does not say which hypothesis it drops")
        base = {k: v for k, v in nb.items() if k != "drops"}
        l, q, v = resolve(tree, base)
        p += [f"neighbour: {x}" for x in q]
        if any(isinstance(b, dict) and label(b) == label(base) for b in backing):
            p.append("its neighbour is one of its own backing items")
        view["neighbour"] = (nb, l, v)
    for u in c.get("cites") or []:
        if not (isinstance(u, str) and re.match(r"^https://\S+$", u)):
            p.append(f"cites: {u!r} is not an https address")
    counsel = c.get("counsel")
    if counsel is not None:
        if not isinstance(counsel, str):
            p.append(f"counsel {counsel!r} is not a path")
        else:
            f = tree.root / counsel
            view["counsel"] = None
            if f.exists():
                d = _read_yaml(f)
                if not (isinstance(d, dict) and isinstance(d.get("read"), str) and DAY.match(d["read"]) and d.get("by")):
                    p.append(f"{counsel} is not {{read: YYYY-MM-DD, by}}")
                else:
                    view["counsel"] = d
    waits = c.get("waits")
    if waits is not None:
        if not (isinstance(waits, dict) and isinstance(waits.get("file"), str) and isinstance(waits.get("says"), str)):
            p.append(f"waits {waits!r} is not {{file, says}}")
        elif (tree.root / waits["file"]).exists():
            p.append(f"it waits for {waits['file']}, which now exists: rewrite its entry for what that card proves")
    return p, view


def _read_yaml(p: Path):
    import yaml
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, yaml.YAMLError):
        return None


def load(path: Path) -> list:
    import yaml
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise Unreadable(f"cannot read {path}: {e}")
    if not (isinstance(doc, dict) and isinstance(doc.get("claims"), list)):
        raise Unreadable(f"{path} is not {{claims: [...]}}")
    return doc["claims"]


# ---------------------------------------------------------------- the page
E = lambda s: html.escape(str(s), quote=True)


def _num(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return f"{v} ({v:,})" if abs(v) >= 10000 else str(v)
    return str(v)


def _item_html(item, lv, view) -> str:
    kind = view.get("kind")
    if kind == "theorem":
        where = ", ".join(view["files"]) or "nowhere"
        return (f"<li><span class=\"kind\">theorem</span> <code>{E(item['theorem'])}</code>"
                f"<span class=\"note\">audited in lean/Audit.lean, declared in {E(where)}; {E(lv)}</span></li>")
    if kind == "record":
        quoted = "".join(f"<li><code>{E(k)}</code> <span>{E(_num(v))}</span></li>" for k, v in view["quoted"])
        return (f"<li><span class=\"kind\">record</span> <code>{E(item['record'])}</code>"
                f"<span class=\"note\">sha256</span> <code>{E(item['sha256'])}</code><span class=\"note\">{E(lv)}"
                f"</span>{'<ul>' + quoted + '</ul>' if quoted else ''}</li>")
    if kind == "link":
        why = "" if not view["why"] else " (" + "; ".join(view["why"]) + ")"
        return (f"<li><span class=\"kind\">link</span> <code>{E(item['link'])}</code>"
                f"<span class=\"note\">evidence/levels/links.json; {E(lv)}{E(why)}</span></li>")
    if is_run(item):
        shows = "".join(f"<li><samp>{E(s)}</samp></li>" for s in item["shows"])
        return (f"<li><span class=\"kind\">run</span> <code>{E(' '.join(item['run']))}</code>"
                f"<span class=\"note\">exit {E(item['exit'])}; {E(lv or 'TESTED')}; it prints</span><ul>{shows}</ul></li>")
    return f"<li>{E(label(item))}</li>"


def _travel_html(t) -> str:
    extra = ""
    if "value" in t:
        extra += f" <span>{E(_num(t['value']))}</span>"
    if t.get("status") == "measured":
        extra += f" <span>{E(t['trials'])}</span> trials, <span>{E(t['date'])}</span>"
    return f"<li><span>{E(t['name'])}</span> <span class=\"st\">{E(t['status'])}</span>{extra}</li>"


def claim_html(c: dict, view: dict) -> str:
    lv = c["level"]
    scope = c.get("scope")
    lvtext = "A commitment, not a level" if lv == COMMITMENT else lv
    L = [f"<section class=\"claim\" id=\"claim-{E(c['id'])}\" data-claim=\"{E(c['id'])}\" data-level=\"{E(lv)}\">",
         f"<h2>Claim {E(c['id'])}</h2>",
         f"<p class=\"sentence\">{E(c['sentence'])}</p>",
         f"<p class=\"level\"><span class=\"lv\">{E(lvtext)}</span>"
         + (f" <span class=\"scope\">{E(scope)}</span>" if scope else "") + "</p>"]
    if view["backing"]:
        L.append("<h3>What stands behind it</h3><ul class=\"backing\">")
        L += [_item_html(it, l, v) for it, l, v in view["backing"]]
        L.append("</ul>")
    if view["numbers"]:
        L.append("<h3>The run that gives its numbers</h3><ul class=\"numbers\">")
        L += [_item_html(it, "TESTED", {"kind": "run"}) for it in view["numbers"]]
        L.append("</ul>")
    L.append("<h3>What travels with it</h3><ul class=\"travels\">")
    L += [_travel_html(t) for t in c["travels"]]
    L.append("</ul>")
    if view["neighbour"]:
        nb, l, v = view["neighbour"]
        base = {k: x for k, x in nb.items() if k != "drops"}
        L.append("<h3>Its failing neighbour</h3><ul class=\"neighbour\">")
        L.append(_item_html(base, l, v))
        L.append(f"<li>It drops: <span>{E(nb['drops'])}</span></li></ul>")
    if "counsel" in view:
        d = view["counsel"]
        if d is None:
            L.append(f"<p class=\"terms\">Terms pending: no file from counsel ({E(c['counsel'])}) says the written "
                     f"terms have been read yet.</p>")
        else:
            L.append(f"<p class=\"terms\">Counsel read the written terms on <span>{E(d['read'])}</span> "
                     f"(<span>{E(d['by'])}</span>).</p>")
    if c.get("waits"):
        L.append(f"<p class=\"waits\">{E(c['waits']['says'])}</p>")
    if c.get("note"):
        L.append(f"<p class=\"note\">{E(c['note'])}</p>")
    if c.get("cites"):
        L.append("<p class=\"cites\">Sources: " + ", ".join(f"<a href=\"{E(u)}\">{E(u)}</a>" for u in c["cites"]) + "</p>")
    L.append("</section>")
    return "\n".join(L)


STYLE = """body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1d1d1f}
.claim{border-top:1px solid #ccc;padding:.5rem 0 1rem}.sentence{font-size:1.25rem;font-weight:600}
.lv{font-family:monospace;background:#eef;padding:0 .3rem}.note{color:#555;margin-left:.4rem}
.kind{font-variant:small-caps;margin-right:.3rem}code,samp{font-size:.9em}h3{font-size:1rem;margin:.6rem 0 .2rem}"""


def page(claims: list, views: list) -> str:
    body = "\n".join(claim_html(c, v) for c, v in zip(claims, views))
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>KAMANU: the claims</title>\n"
            f"<style>{STYLE}</style>\n</head>\n<body>\n<h1>The claims</h1>\n"
            "<p>Each sentence below is said in public only with what stands behind it, its level, what must travel "
            "with it and a failing neighbour: the same claim with one hypothesis dropped, which fails. The page is "
            "written by <code>kamanu assay --claims</code>, which checks every item against the tree and writes "
            "nothing when one does not resolve. Levels, strongest first: MODEL_PROVEN, EXHAUSTIVE_FINITE_PASS, "
            "BOUNDED_PASS, TESTED, ASSUMED. A claim never stands above the weakest level of what is behind it.</p>\n"
            f"{body}\n</body>\n</html>\n")


# ---------------------------------------------------------------- the command
def main(claims_file: str, root: str | None, out: str | None) -> int:
    try:
        return _main(claims_file, root, out)
    except Unreadable as e:
        print(f"kamanu assay --claims: {e}", file=sys.stderr)
        return 3
    except Exception as e:                       # the check must never end in a traceback
        print(f"FAIL kamanu assay --claims: the check stopped: {type(e).__name__}: {e}")
        return 1


def _main(claims_file: str, root: str | None, out: str | None) -> int:
    rootp = Path(root) if root else Path.cwd()
    if not rootp.is_dir():
        raise Unreadable(f"--root {rootp} is not a directory")
    claims = load(Path(claims_file))
    tree = Tree(rootp.resolve())
    bad, views, seen = [], [], set()
    for i, c in enumerate(claims):
        cid = c.get("id") if isinstance(c, dict) else None
        who = f"claim {cid}" if isinstance(cid, int) else f"claim #{i + 1} (entry {i + 1}, no integer id)"
        probs, view = check_claim(tree, c)
        if isinstance(cid, int) and cid in seen:
            probs.append("its id is given twice")
        seen.add(cid)
        bad += [f"FAIL {who}: {x}" for x in probs]
        views.append(view)
    if bad:
        print("\n".join(bad))
        print(f"kamanu assay --claims: {len({b.split(':')[0] for b in bad})} claim(s) do not resolve; no page written")
        return 1
    text = page(claims, views)
    dst = Path(out) if out else rootp / "claims" / "index.html"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(text.encode("utf-8"))
    except OSError as e:
        raise Unreadable(f"cannot write {dst}: {e}")
    for c in claims:
        print(f"ok claim {c['id']}: {c['level']}")
    print(f"wrote {dst}")
    return 0
