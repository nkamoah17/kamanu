------------------------------ MODULE StarvationT ------------------------------
(* T1 template: no starvation.                                               *)
(* Agents share one resource (a lock, a budget slot, a rate-limit token).    *)
(* They ask, are granted, release, and ask again. The scheduler is weakly    *)
(* fair: it always grants someone. Planted: it grants any waiting agent, so  *)
(* one agent can be passed over for ever. Fixed: it grants in arrival order. *)
EXTENDS Naturals, Sequences

CONSTANT Fixed
CONSTANT Agents

VARIABLES queue, holder
vars == <<queue, holder>>

None == "none"
Waiting(a) == \E i \in 1..Len(queue) : queue[i] = a

\* The one switch: who may be granted next.
Grantable == IF Fixed THEN {Head(queue)} ELSE {queue[i] : i \in 1..Len(queue)}

Remove(s, a) == SelectSeq(s, LAMBDA x : x # a)

Init == queue = << >> /\ holder = None

Ask(a)  == a # holder /\ ~Waiting(a) /\ queue' = Append(queue, a) /\ UNCHANGED holder
Grant   == holder = None /\ queue # << >>
           /\ \E a \in Grantable : holder' = a /\ queue' = Remove(queue, a)
Release == holder # None /\ holder' = None /\ UNCHANGED queue

Next == (\E a \in Agents : Ask(a)) \/ Grant \/ Release

Spec == Init /\ [][Next]_vars /\ WF_vars(Grant) /\ WF_vars(Release) /\ \A a \in Agents : WF_vars(Ask(a))

NoStarvation == \A a \in Agents : Waiting(a) ~> (holder = a)
NeverGranted == holder = None
=============================================================================
