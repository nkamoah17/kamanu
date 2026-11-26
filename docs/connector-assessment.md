# Assessing an MCP connector for cross-tenant reads

The property: no user's agent reads another tenant's data through the connector. Two queries look for
it in the code, one harness looks for it in the running server, and one function types what they say.
The result is an independent assessment, not a certification. It can show a problem. It cannot show that
there is none.

## The queries

They need Joern 4.0.676 (`JOERN_HOME`) and read a Python or a JavaScript/TypeScript repository.

```python
from pathlib import Path
from kamanu.evidence.joern import run            # JavaScript: kamanu.evidence.joern_js.run_js, queries_js/

q = Path("kamanu/evidence/queries")
facts = run("path/to/connector", [q / "identity_provenance.sc", q / "tenant_sinks.sc"])
```

`identity_provenance` writes one fact for each pair of a tool and a data access it reaches (a database
statement, a file, an outbound request), with where the identity that scopes the access comes from:

| identity | the scoping value comes from |
|---|---|
| `session` | the transport: a field of the `Context` parameter (Python), `authInfo` of the handler's second parameter (JavaScript) |
| `argument` | a parameter of the tool, whatever it is called; the model supplies it |
| `constant` | a literal |
| `none` | nothing traced: the access is unscoped, or scoped by something the query does not follow |

`tenant_sinks` writes one for each such access that is not the session's and whose result reaches the
tool's answer (what it returns, or raises), with the path from the source to the access.

The scoping values are the bound parameters of a statement and the pieces of a path or URL. A name
decides nothing: a parameter called `user_id` is an argument in a tool and the session's where a tool
passes the session's. A helper that two tools call gives two facts.

## The harness

```python
from kamanu.connector.harness import play

report = play(target, "run.jsonl")
```

`target` starts the server over stdio as tenant A and says what was seeded for A and for B: identifiers
(what an agent may know) and records with marks (what must not come back). `fixtures/connectors/seed.py`
builds one for the fixture servers. The harness calls every tool with B's identifiers, pairs of
identifiers, wildcards, quotes and walks out of a directory, and reports every record of B's in any
answer, with the call that gives it again. `none_observed` is what these calls showed. It is `unknown`
when the server did not start, left a call unanswered, or gave back no record of A's.

Run a connector you did not write in a sandbox: the harness executes it.

## The assessment

```python
from kamanu.connector.assess import assess

result = assess(facts, report)
```

Each finding is typed. `observed`: the harness saw a leak of that tool. `established`: the fact is of a
construct in `kamanu.evidence.premises.IDENTITY` and names its assumptions, which a reader must check.
`pattern`: the query's shape matched and no more. The verdict is `finding`, `no_finding` (the two queries
and the harness all decided, and all said no) or `unknown`.

## What is not seen

- An access a framework makes for the connector, or a library the queries do not know (they know
  `execute`, `open`, `urlopen`, `requests` and `httpx` in Python, prepared statements, SQL text given to
  `query`, `all`, `get` or `run`, `readFileSync`, `fetch` and `axios` in JavaScript).
- Dynamic dispatch, inheritance, dependency injection, and low-level handlers that dispatch on a name.
- SQL text built by pasting: only bound parameters scope a statement, so a pasted value scopes nothing.
- A comparison of an argument with the session before its use. The query still says `argument`.
- An environment variable as identity. The query says `none`.
- A path under the session's directory with an argument joined on is `session`, and can still be walked
  out of. The harness tries that; the queries do not see it.
- A call that changes what a later call gives, and time.

Findings about somebody else's connector are private until the owner has handled disclosure.

## One command: `kamanu connector assess` (X5)

The harness, the queries and the isolation theorem, packaged. It runs from the installed wheel; no checkout
is needed.

```
kamanu connector assess --tenants tenants.json --out out/ [--facts facts.json] [--cwd DIR] [--timeout S] \
    -- python server.py
```

`tenants.json` is what you seeded for two tenants, as the harness's `target["tenants"]`:
`{"A": {"env", "identifiers", "records"}, "B": {"identifiers", "records"}}`. The command cannot seed a real
connector: you do, and say what you seeded. The server command after `--` runs in `--cwd` with A's `env`.
With `--facts` the queries' facts are read from the file; without it the queries run where `JOERN_HOME`
names Joern and the query scripts are present (a checkout), and are otherwise unknown.

It writes `out/assessment.json` and `out/transcript.jsonl`, and prints the same heading every record carries:
**independent assessment, not a certification**. Then one line for each of three links, and the level:

| link | from | level |
|---|---|---|
| contract | the theorem `Kamanu.Iso.isolation` (lean/Kamanu/Isolation.lean; the `isolation` link of evidence/levels/links.json) | MODEL_PROVEN when the link is proved, else TESTED; UNKNOWN when there is none |
| conformance | the queries' facts, typed by `assess` | REFUTED when an access is not the session's or one reaches an answer; UNKNOWN when they decided nothing (no facts, or no Joern); ASSUMED when an access is a pattern; EXHAUSTIVE_FINITE_PASS when every access is the session's and established |
| behaviour | the harness's report | REFUTED at a leak; UNKNOWN when it decided nothing, made no call, or no call was answered (never "none observed" then); else TESTED |

The level of the assessment is the weakest link: REFUTED when one is, else UNKNOWN when one is, else the
weakest passing level. So it is never above TESTED, and never MODEL_PROVEN because the theorem is.

### What the theorem says, and what it does not

The contract is **ScopedBySession**: every data access of every tool is scoped by the tenant its session was
bound to when it was authenticated. In the model (lean/Kamanu/IsolationSpec.lean, and spec/ext/Isolation.tla,
which TLC checks on small universes) tenants, principals, sessions and records are distinct kinds; a record has
one owning tenant and the tenants it is shared with; a session is bound once, to the directory's tenant of the
principal that signs in; a tool call carries arguments the adversary chooses freely, other tenants'
identifiers among them. The theorem: for a connector that meets the contract, for any number of calls,
sessions and arguments, every record given to a session is owned by or shared with that session's tenant.
Three failing neighbours are theorems too, each with a concrete trace to a leak: accesses scoped by an
argument (`argument_leaks`), unscoped accesses (`unscoped_leaks`), and reads scoped by the session with one
export scoped by an argument (`export_leaks`).

The theorem is about the model. A real connector meets the contract only as far as the queries establish its
accesses (a pattern is not a fact) and the harness observes its answers. That is why the assessment reports
all three links and takes the weakest, and why every record lists its limits.

### The records

`evidence/exonumia/x5/` holds the command's records for T9's six fixture servers (public: the argument and
unscoped ones REFUTED, the session ones a clean result at ASSUMED, since their accesses are patterns), one run
without facts (UNKNOWN), and the T9 connector at its pinned commit (private, as T9's record is).
`python evidence/exonumia/x5/run.py` writes them again.
