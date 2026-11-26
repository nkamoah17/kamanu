# Learning KAMANU, one rung at a time

This page teaches KAMANU in the order the ladder climbs: first what a spend cap means with
nothing else around it, then the guard that is supposed to keep it, then the features real
engines add, then what a real engine is observed to do. Each rung adds one thing and is
checked against the rung below it. You do not need to know TLA+ to read it: every trace
KAMANU prints is told as a story (see the last section).

## 1. The ledger: what a cap means

Before any engine, policy or history, a spend cap is three numbers:

- **held**: money reserved for calls that were let through and have not finished;
- **spent**: money that really moved;
- **doubt**: money from calls that failed without moving money and that nobody has checked
  with the provider yet.

Four moves change them, each by one amount `a`: reserve (let a call through, only if
`held + spent + a` stays within the cap), commit (a call finished and the money moved),
release (a call failed cleanly: its money goes from held to doubt) and clear (the provider
confirmed nothing moved: the doubt goes away). The cap is kept when `held + spent` never goes
above it, and that stays true after every move, because only reserve raises `held + spent`
and it checks first.

Here are the ledger's 24 lines as `spec/ladder/Ledger.tla` states them (everything after its
opening comment). Read `==` as "is defined as", `/\` as "and", `\/` as "or", a primed name
such as `held'` as "held after the move", and `\* @type:` lines as type notes for Apalache:

```tla
EXTENDS Naturals

CONSTANTS
    \* @type: Int;
    Cap,
    \* @type: Set(Int);
    Amts

VARIABLES
    \* @type: Int;
    held,
    \* @type: Int;
    spent,
    \* @type: Int;
    doubt

\* @type: <<Int, Int, Int>>;
lvars == <<held, spent, doubt>>

LInit == held = 0 /\ spent = 0 /\ doubt = 0

Reserve(a) == held + spent + a <= Cap /\ held' = held + a /\ UNCHANGED <<spent, doubt>>
Commit(a)  == held >= a /\ held' = held - a /\ spent' = spent + a /\ UNCHANGED doubt
Release(a) == held >= a /\ held' = held - a /\ doubt' = doubt + a /\ UNCHANGED spent
Clear(a)   == doubt >= a /\ doubt' = doubt - a /\ UNCHANGED <<held, spent>>

LNext == \E a \in Amts : Reserve(a) \/ Commit(a) \/ Release(a) \/ Clear(a)

LSpec == LInit /\ [][LNext]_lvars

WithinCap == held + spent <= Cap
====
```

`lvars` names the three numbers; `LInit` starts them at zero; `Reserve`, `Commit`,
`Release` and `Clear` are the four moves; `LNext` is "any one move, with any amount";
`LSpec` is "start at zero, then make moves"; `WithinCap` is the promise.

## 2. The kernel: a guard over a history

A real guard does not see held and spent. It sees a **history** of events (requests,
responses, errors, refunds), and a **policy** counts that history. The kernel models one
guard: an agent asks to pay, the engine decides from its count and writes events into its
history, the tool runs the call (it can succeed, fail cleanly or fail ambiguously), and a
harness later asks the provider what really happened.

The kernel is joined to the ledger by a mapping: held is the total of calls let through and
not finished, spent is the money that really moved, doubt is the total of failed calls with
no effect that were not reconciled. The kernel is right when every run, seen through the
mapping, is a run of the ledger, and when the engine's count always sits between the
ledger's two lines:

- **sound**: the count is at least `held + spent` (it never forgets money that is out);
- **tight**: the count is at most `held + spent + doubt` (it never counts money that is not).

Both are checked on every view the engine may read, not only on the full history.

## 3. Features: what engines differ on

Engines differ in a handful of choices, and each is a coordinate of R1's grid:

- the **policy**: what it counts (responses, requests, requests minus errors, requests minus
  refunds);
- what a **refusal leaves** in the history (nothing, a deny event, an error, a request, or a
  request and an error);
- the **engine**: atomic (deciding and writing are one move), not atomic (two calls can be
  let through on the same count) or a stale view (the count may miss the latest event);
- the **fault rung**: no faults, or clean and ambiguous failures.

Every cell of the grid is checked against the ledger by TLC, and every verdict carries a
witness: a run that shows the property was really exercised (R2).

## 4. Reality: what a real engine does

The hunt probes a real engine with sequences of calls, finds the cell of the grid it behaves
like, and replays every finding against the engine before reporting it. What an actor cannot
observe (see `observers.md`) is printed as an assumption, never as a fact.

## Reading a story

`kamanu story FILE --cell CELL_JSON [--itf OUT]` prints a trace as a story: one line per
step, who took it (the harness, the engine or the tool), what happened in plain words, and
beside it the two ledgers: what the engine counted (one number per view it may read) and
held, spent, doubt. The first step where a count leaves the band
`held + spent <= count <= held + spent + doubt` is marked "the invariant broke": that is
where the engine stopped telling the truth about the money. `--itf` writes the same trace in
Apalache's Informal Trace Format, and reading that file back gives the same story.
`evidence/ladder/r8/stories.json` holds worked examples: a story whose ledgers never part,
one that parts at its last state, one that parts earlier, and one with money in doubt.
