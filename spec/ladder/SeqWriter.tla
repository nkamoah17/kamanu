---- MODULE SeqWriter ----
(***************************************************************************)
(* R4: the single-writer result (the kit's e14) on Staleness.              *)
(*                                                                          *)
(* One sequential writer per key: key k's writer issues its next pay call  *)
(* only when every earlier call of k is settled and reconciled, and keeps  *)
(* spending (it asks again whatever the verdict). The engine decides on    *)
(* Staleness's views; every other step is the seed harness's.              *)
(*                                                                          *)
(*   PerKeyOK    every key's real spend is at most Cap                      *)
(*   SeqWitness  every key pays once and its next request is refused or    *)
(*               paid within cap (never "a key pays twice", which is       *)
(*               vacuous where the cap leaves room for one call only)       *)
(*                                                                          *)
(* Safe exactly when OwnWrites holds (evidence/ladder/r4/seqwriter.json).  *)
(***************************************************************************)
EXTENDS Staleness, FiniteSets

CONSTANTS Keys, Amts

SeqTemplates == {[tool |-> "pay", amt |-> a, key |-> k] : a \in Amts, k \in Keys}

\* every earlier call of key k is settled and reconciled
KeyQuiet(k) == \A i \in Ids : rq[i].key = k => (Settled(i) /\ ~Unreconciled(i))

SeqNext == \/ \E t \in SeqTemplates : (KeyQuiet(t.key) /\ Issue(t))
           \/ \E i \in Ids : SStep(i)
           \/ (Exhausted /\ UNCHANGED kvars)

SeqSpec == KInit /\ [][SeqNext]_kvars

KeySpend(k) == SumIds({i \in eff : rq[i].key = k})

PerKeyOK == \A k \in Keys : KeySpend(k) <= Cap

\* j is key k's next request after i
NextOf(k, i, j) == /\ i < j /\ rq[i].key = k /\ rq[j].key = k
                   /\ ~\E m \in Ids : i < m /\ m < j /\ rq[m].key = k

SeqWitness == \A k \in Keys : \E i, j \in Ids :
                  /\ NextOf(k, i, j)
                  /\ i \in eff
                  /\ (st[j] = "denied" \/ (j \in eff /\ KeySpend(k) <= Cap))
====
