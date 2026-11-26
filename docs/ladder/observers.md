# Who observes what (R4, L8)

A claim about a run is only as good as what its maker could see. Each actor in a KAMANU run
sees a different slice of it. A statement that needs more than its actor sees is an
assumption, and it has to be printed as one.

| actor | observes | does not observe |
|---|---|---|
| agent | its own calls and verdicts: what it asked, what the engine said, what the tool returned to it | other writers' calls on the same key; the engine's view; whether an error had an effect |
| engine | its view: the history it reads when it decides (Staleness.tla's SViews: every in-flight call, and the completed calls its profile does not miss) | the truth of an ambiguous failure until it is reconciled; calls its view misses (OwnWrites FALSE, up to OtherLag of other keys) |
| tool | one call: the request it is executing and its own effect | every other call, the policy, the verdicts |
| harness | the truth after reconciliation: which calls really took effect (eff), every call of every key | nothing the model leaves out; it is the model checker's ghost, not a deployed component |
| coach | the agent's calls only: the log the agent hands it | other writers on the key, the engine's view, the engine's staleness |

What follows from it:

- The coach answers "permitted" from the agent's log. Another writer's calls on the same key are
  in the engine's view and not in that log, so every "permitted" rests on the agent being the
  only writer. `kamanu coach` prints "assumes it is the only writer for <key>" whenever its
  advice rests on it.
- The single-writer result (spec/ladder/SeqWriter.tla, evidence/ladder/r4/seqwriter.json): with
  one sequential writer per key that issues its next call only after the last one settled, the
  per-key cap holds exactly when the engine reads its own key's writes (OwnWrites). So the design
  recommendation is one key per sequential worker, with the budget partitioned across the keys.
- The hunt asks the engine two questions it cannot observe directly, through the single-writer
  probe: own_writes (does a sequential call see its own key's completed calls?) and other_lag
  (how many completed calls of other keys can it miss?). It answers each with determined, not
  refuted in n trials, or not exercised (L4).
