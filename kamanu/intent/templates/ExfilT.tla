-------------------------------- MODULE ExfilT --------------------------------
(* T1 template: no exfiltration after a private read.                        *)
(* An agent works for one principal across sessions it opens itself. A read *)
(* of private data taints; a send to an external sink after any private     *)
(* read by that principal leaks. Planted: the taint lives in the session,   *)
(* so read in s1 and send in s2. Fixed: the taint lives on the principal.   *)
EXTENDS Naturals

CONSTANT Fixed
CONSTANT Sessions

VARIABLES taint, readAny, sends, leaked
vars == <<taint, readAny, sends, leaked>>

MaxSends == 2

\* The one switch: the label scope a send is checked against.
Tainted(s) == IF Fixed THEN readAny ELSE taint[s]

Init == taint = [s \in Sessions |-> FALSE] /\ readAny = FALSE /\ sends = 0 /\ leaked = FALSE

ReadPrivate(s) == /\ ~taint[s]
                  /\ taint' = [taint EXCEPT ![s] = TRUE] /\ readAny' = TRUE
                  /\ UNCHANGED <<sends, leaked>>

SendExternal(s) == /\ sends < MaxSends /\ ~Tainted(s)
                   /\ sends' = sends + 1 /\ leaked' = (leaked \/ readAny)
                   /\ UNCHANGED <<taint, readAny>>

Next == \E s \in Sessions : ReadPrivate(s) \/ SendExternal(s)

Spec == Init /\ [][Next]_vars

NoExfil  == ~leaked
NeverSent == sends = 0
=============================================================================
