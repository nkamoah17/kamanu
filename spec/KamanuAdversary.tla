--------------------------- MODULE KamanuAdversary ---------------------------
(***************************************************************************)
(* Safety harness: a fully compromised model. At any step it may issue    *)
(* ANY template, in parallel with requests already in flight. Only the    *)
(* policy and the engine profile stand between it and the world.          *)
(* "Safety despite a malicious model."                                    *)
(***************************************************************************)
EXTENDS KamanuKernel

AllQuiet  == \A i \in Ids : Settled(i) /\ ~Unreconciled(i)
Exhausted == n = MaxReq /\ AllQuiet

\* The terminal stutter is enabled ONLY at the end of the bounded run, so
\* TLC's deadlock check still reports any other state with no successor.
Next == \/ \E t \in Templates : Issue(t)
        \/ EngineStep
        \/ (Exhausted /\ UNCHANGED kvars)

Spec == KInit /\ [][Next]_kvars
=============================================================================
