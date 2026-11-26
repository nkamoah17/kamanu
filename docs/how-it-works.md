# How KAMANU works, and what a result means

This page holds what the repository's README carried before 25 November 2026 and no longer does: how the
pieces fit, the commands in more detail, how to read a result, and where things live. The specification
itself (the ledger, the kernel, the five policies and the config contract) stays in the README's
Reference section, which task cards cite by name.

## How it works

```
policy text ──adapter──▶ Permit(view, r) ─┐
engine profile ─────────▶ constants ──────┼──▶ TLA+ model ──TLC──▶ verdict record ──▶ JSON, SARIF,
harness (adversary, task) ────────────────┘    per fault level                        plain-steps trace
```

1. **The kernel** (`spec/KamanuKernel.tla`) models one guard over an event history: requests
   are issued, decided, recorded, succeed or fail, and are reconciled. A ghost variable
   tracks which payments really happened, so "spent" never depends on what the engine
   believes. The full semantics is in the Reference section of the repository's README.
2. **An engine profile** (`profiles/*.json`) fills in what differs between engines: does the
   view include the current request, what a refusal leaves behind, are decisions atomic, how
   stale the view can be, what the session key is, how windows work. Every value carries its
   source (a documentation quote, a probe, a replay) and a confidence. A value nobody has
   measured takes its pessimistic default, and the verdict says that it rests on it.
3. **An adapter** reads the policy itself and compiles it to the kernel's `Permit`. Dogwood
   policies feed `kamanu check`; the Rego adapter compiles Rego for the Python API and reads
   staleness from OPA's bundle config; the Redis adapter reads limiter scripts (Lua or Python)
   and says whether they are atomic, and on which line. Anything an adapter cannot translate exactly
   is listed line by line and the verdict is UNKNOWN, never a guess.
4. **Harnesses** say who is calling. The adversary harness is a compromised model that issues
   any request, in parallel (safety). The task harness is one honest task with an approval
   gate, a timer and explicit fairness (deadlock and liveness). Extensions add the refused
   over-ask, the hostile request in the same scope, the policy update and the retry storm.
5. **TLC** explores every state within the stated bounds and returns the shortest trace that
   breaks a property. `kamanu/story.py` turns it into plain steps: "ask 60: allowed; paid 60;
   ask 60: denied". A stuck verdict is classified as a real deadlock or a livelock that only
   the bound causes.
6. **Second opinions.** A Python mirror of the kernel, written from the prose in the repository's README
   and never from the TLA+, and a fair-cycle checker built on it, must agree with TLC, and
   Apalache gives a third answer on bounded safety. Two implementations that are wrong the same way is the failure
   this guards against.

Around that core: a probe designer that uses TLC to find the shortest experiment telling two
profiles apart; trace validation that asks whether the kernel can produce a recorded engine
log; and code evidence that reads an agent's source with Joern (Python and JavaScript) to
justify the premises a model may assume, such as "the server mints the session key".

## Use it, in more detail

**Check a policy before you deploy it**

```
kamanu check policy.dw --engine profiles/dogwood-1.1.1.json --out out/
```

The cap is read from the policy (or `--cap N`), and the honest request is 60% of it. For each
fault level the checks are safety, deadlock and liveness, then false denial, a hostile request
in the same scope, and a policy update (reported, never counted: no policy text can prevent
it). Writes `out/verdict.json` (schema in `schema/verdict.schema.json`) and `out/kamanu.sarif`,
which points at the line of the cap clause. Exit code 0 means every counted check passed, 1 a
check failed, 2 UNKNOWN, 3 an error. Use `--engine reference` for the textbook engine.

**Coach an agent at runtime**

`kamanu/coach.py` answers three questions before each call: would this be permitted now, what
is the most that would be, and when will the full amount fit. On an engine that keeps refused
requests, that is the difference between waiting and freezing the budget.
`kamanu/coach_middleware.py` wraps any Python callable an agent framework exposes as a tool and
refuses a doomed call before it reaches the engine. `python -m kamanu.coach_mcp` serves the
same answers over MCP (`advise`, `max_allowed_now`, `earliest_time`).

**From a coding agent**

`python -m kamanu.mcp_server` exposes `verify_policy`, `diff_engines` (every check whose
verdict differs between two engines on the same policy), `explain` and `questions` (the
questions that settle an ambiguity, each with the trace that separates the answers), so the
agent that writes a policy can check it in the same session.

## What a result means

- **PASS** means no trace breaks the property within the stated bounds (by default three
  requests and one failure), under the stated engine profile. Every verdict prints its bounds
  and the profile values it rests on. It is a bounded result, not a proof for all sizes.
- **A failing verdict comes with the shortest trace** that breaks the property.
- **UNKNOWN** means part of the policy was outside what the adapter understands. It is listed
  line by line.
- **Out of scope:** whether the model judged well. KAMANU checks who may do what, in which
  order and within which limits. It cannot tell you the agent computed the right amount.

**What "right" means.** An engine running a policy conforms when, at the decision boundary, it
is a two-way refinement of the ledger ("Ledger semantics in prose", in the README's Reference section). The hunt finds
which kernel profile the engine is. Model checking that profile against the ledger gives the
verdict, in two directions:

- **Sound:** it never admits what the ledger could not reserve. Failing this is overspend.
- **Tight:** it never refuses what the ledger would have to admit. Failing this is a "no"
  that costs money.

An engine that refuses to decide (for example when calls run at once) gives a third answer,
**undetermined**. It takes no ledger step, so it costs neither direction; it is paid for in
availability, which is reported on its own line. No internal state of the engine is
observed.

Every verdict KAMANU prints follows eight rules:

1. It is judged at the interface only.
2. It reports both directions.
3. A pass carries a witness that the interesting thing can happen in that cell, and a failing
   neighbour one change away.
4. "Not exercised" is a result, never a pass.
5. Each level reduces to the one above with its feature off, and that is checked, not
   commented.
6. A new idea is stated at the highest level where it can be stated.
7. Every profile question and probe is calibrated on planted engines.
8. Each actor states what it can observe, and a component that assumes more says so.

**How each result was established.** No verdict is a bare PASS. Each one also carries a
proof level, and a verdict takes the weakest level on the chain it rests on:

| Level | What it establishes | Example |
| --- | --- | --- |
| MODEL_PROVEN | A machine-checked theorem holds for the stated model and hypotheses | R9's cell refines the ledger; the fast path's clip is a bisimulation (`lean/`) |
| EXHAUSTIVE_FINITE_PASS | A complete finite state space was explored | a closed `kamanu lint` run with every profile constant stated |
| BOUNDED_PASS | No violation within the stated bounds | `kamanu check` PASS, by default three requests and one failure |
| TESTED | Observed runs passed | live runs, replays on an engine's binary, differential tests |
| ASSUMED | A premise nobody established | a profile constant left at its default; a code premise found only as a pattern |
| REFUTED | A counterexample exists | FAILS, INVARIANT, DEADLOCK, LIVENESS, with the shortest trace |
| UNKNOWN | The semantics or the evidence cannot decide | a construct outside the adapter; an exploration cut at its budget |

A failing verdict is REFUTED whatever else holds. A passing one is as strong as the weaker of
its method and its premises: a closed lint run on a measured profile whose Atomic and Lag are
defaults is ASSUMED, not EXHAUSTIVE_FINITE_PASS, and lint still prints both conditional
answers. Each verdict lists what it rests on (`rests_on`), so the weakest link is named. The
proved links, their Lean theorems and their hypotheses are in `evidence/levels/links.json`.
A theorem about a model says nothing about a deployment: whether a real engine is atomic is
measured or assumed, and the level says which.

## Repository

| Path | What it is |
| --- | --- |
| `spec/` | The kernel, the policy library, the harnesses, extensions and multi-agent demos |
| `kamanu/` | The checker and CLI, the independent mirror, the coach, adapters, MCP servers, code evidence |
| `profiles/` | Measured engine profiles |
| `fixtures/` | Example policies (Dogwood, Rego), Redis limiters and agent harnesses |
| `schema/` | JSON schemas for verdicts and code facts |
| `lean/`, `verify.sh` | The Lean proofs and the script that checks them from clean |
| `registry/` | The signed records cleared for publication, and their offline verifier |
| `exonumia/` | The rail harness with its simulators, the shadow ledger and the payment hooks |
| `oracle/toolchain.json` | The pinned TLA+ tools and engines, by URL and hash |

How the repository is built, one task card at a time against gates written first, is in `CONTRIBUTING.md`.
