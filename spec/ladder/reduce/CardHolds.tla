---- MODULE CardHolds ----
(***************************************************************************)
(* The ledger with holds (X4): spec/ladder/Ledger.tla's held, spent and    *)
(* doubt, each reserve made for a hold with an identity, and nothing that  *)
(* commits more than it reserved. It is the card ledger                    *)
(* (spec/ledgers/Card.tla) with over-capture and force-post off, written   *)
(* without them: the target of the reduction CardOff.                     *)
(*                                                                         *)
(*   Authorize(h, a)  an atomic engine decides and reserves at once: the   *)
(*                    ledger's Reserve(a), checked against the issuer's    *)
(*                    view (held + spent less the last Lag events).        *)
(*   Decide(h, a)     a non-atomic engine decides first ...                *)
(*   Reserve(h)       ... and reserves later (another decision between).   *)
(*   Capture(h, c)    c at most the hold: commits c, releases the rest     *)
(*                    with nothing in doubt (the issuer knows no money     *)
(*                    moved for it).                                       *)
(*   Reverse(h, r)    releases r of the hold, nothing in doubt.            *)
(*                                                                         *)
(* Every step that changes held or spent is a ledger event; the view lags  *)
(* the truth by the last Lag of them.                                      *)
(***************************************************************************)
EXTENDS Ledger, Integers, Sequences

CONSTANTS Holds, Partial, Reversal, Lag, Atomic

VARIABLES hs, ha, buf

cvars == <<hs, ha, held, spent, doubt, buf>>
HIds == 1..Holds

CInit == LInit /\ hs = [h \in HIds |-> "none"] /\ ha = [h \in HIds |-> 0] /\ buf = <<>>

\* One ledger event (dheld, dspent): the view forgets the last Lag of them.
Event(dh, ds) == buf' = IF Lag = 0 THEN <<>>
                        ELSE IF Len(buf) < Lag THEN Append(buf, <<dh, ds>>)
                        ELSE Append(Tail(buf), <<dh, ds>>)
RECURSIVE Unseen(_)
Unseen(s) == IF s = <<>> THEN 0 ELSE Head(s)[1] + Head(s)[2] + Unseen(Tail(s))
View == held + spent - Unseen(buf)
Fits(a) == View + a <= Cap

SetHold(h, s, a) == hs' = [hs EXCEPT ![h] = s] /\ ha' = [ha EXCEPT ![h] = a]

Refuse(h, a) == SetHold(h, "refused", a) /\ UNCHANGED <<held, spent, doubt, buf>>

Authorize(h, a) == Atomic /\ hs[h] = "none" /\
    IF Fits(a) THEN SetHold(h, "open", a) /\ held' = held + a /\ Event(a, 0) /\ UNCHANGED <<spent, doubt>>
    ELSE Refuse(h, a)
Decide(h, a) == ~Atomic /\ hs[h] = "none" /\
    IF Fits(a) THEN SetHold(h, "approved", a) /\ UNCHANGED <<held, spent, doubt, buf>>
    ELSE Refuse(h, a)
ReserveHold(h) == hs[h] = "approved" /\ SetHold(h, "open", ha[h]) /\ held' = held + ha[h] /\ Event(ha[h], 0)
               /\ UNCHANGED <<spent, doubt>>

CaptureAmts(a) == {a} \cup (IF Partial THEN {x \in Amts : x < a} ELSE {})
Capture(h, c) == hs[h] = "open" /\ c \in CaptureAmts(ha[h]) /\ SetHold(h, "captured", c)
                 /\ held' = held - ha[h] /\ spent' = spent + c /\ Event(-ha[h], c) /\ UNCHANGED doubt

ReverseAmts(a) == {x \in Amts : x <= a} \cup {a}
Reverse(h, r) == Reversal /\ hs[h] = "open" /\ r >= 1 /\ r \in ReverseAmts(ha[h])
                 /\ SetHold(h, IF r = ha[h] THEN "reversed" ELSE "open", ha[h] - r)
                 /\ held' = held - r /\ Event(-r, 0) /\ UNCHANGED <<spent, doubt>>

CNext == \E h \in HIds :
           \/ \E a \in Amts : Authorize(h, a) \/ Decide(h, a)
           \/ ReserveHold(h)
           \/ \E c \in CaptureAmts(ha[h]) : Capture(h, c)
           \/ \E r \in ReverseAmts(ha[h]) : Reverse(h, r)

HSpec == CInit /\ [][CNext]_cvars
====
