------------------------------- MODULE Labels -------------------------------
(***************************************************************************)
(* Information-flow labels: how far the taint of a private read reaches.   *)
(*                                                                         *)
(* An agent acts for a principal, and it opens sessions as it likes: the   *)
(* key on a request is the caller's choice, so a session is no boundary    *)
(* against the caller. LabelPermit is the same flow rule in both models:   *)
(* a send is denied once a private read is in its label scope. Requests    *)
(* are counted, not responses, so a read that failed ambiguously still     *)
(* taints, and so does one that failed cleanly: the guard cannot tell them *)
(* apart.                                                                  *)
(*                                                                         *)
(* The single switch is LabelScope, the kernel's Scope, which decides      *)
(* which reads share a label with the send:                                *)
(*   Fixed = FALSE: the label lives in the session. Read in s1, send in    *)
(*     s2, and the guard never compares the two.                           *)
(*   Fixed = TRUE: the label lives on the principal, across all of its     *)
(*     sessions. Another principal's reads do not taint it, so s3 can      *)
(*     still send after s1 reads.                                          *)
(*                                                                         *)
(* NoExfil orders events by request id, which is issue order, but the      *)
(* engine may decide pending requests in any order. A read still pending   *)
(* is in no view yet, so a send decided ahead of it would see no taint,    *)
(* and the read could then run. The guard therefore also refuses a send    *)
(* while a read in its scope is undecided. It fails closed and does not    *)
(* wait: the send may be denied though the read is younger.                *)
(*                                                                         *)
(* The engine is atomic with no lag: this model is about label scope, and  *)
(* a guard that misses an admitted read is a different defect.             *)
(***************************************************************************)
EXTENDS KamanuKernel

CONSTANT Fixed

Sessions == {"s1", "s2", "s3"}

PrincipalOf == [s \in Sessions |-> IF s = "s3" THEN "bob" ELSE "alice"]

LabelTemplates == {[tool |-> t, amt |-> 0, key |-> s] :
                       t \in {"read_private", "send"}, s \in Sessions}

\* The one switch between the buggy and the fixed model.
LabelScope(x) == IF Fixed THEN PrincipalOf[x.key] ELSE x.key

Tainting(e) == e.kind = "request" /\ e.tool = "read_private"

ReadUndecided(r) ==
    \E j \in Ids : st[j] = "pending" /\ rq[j].tool = "read_private"
                  /\ Scope(rq[j]) = Scope(r)

LabelPermit(v, r) ==
    r.tool = "send" => /\ \A j \in 1..Len(v) : ~Tainting(v[j])
                       /\ ~ReadUndecided(r)

Leaked == \E i, j \in eff : rq[j].tool = "read_private" /\ rq[i].tool = "send"
                            /\ j < i /\ PrincipalOf[rq[i].key] = PrincipalOf[rq[j].key]

NoExfil == ~Leaked

Goal == \E i \in Ids : st[i] = "done" /\ rq[i].tool = "send"

GoalNeverReached == ~Goal

\* The terminal stutter is enabled only at the end of the bounded run, so
\* TLC's deadlock check still reports any other state with no successor.
Finished == n = MaxReq /\ \A i \in Ids : Settled(i)

\* The kernel's actions stay unwrapped, so TLC labels the trace with their names.
Next ==
    \/ \E t \in Templates : Issue(t)
    \/ \E i \in Ids : Decide(i)
    \/ \E i \in Ids : Record(i)
    \/ \E i \in Ids : Settle(i)
    \/ (Finished /\ UNCHANGED kvars)

Spec == KInit /\ [][Next]_kvars
=============================================================================
