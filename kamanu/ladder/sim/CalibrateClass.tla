---- MODULE CalibrateClass ----
\* R6b: is there a sequential probe within bounds that tells two frontier profiles apart?
\*
\* Two engines, profile A and profile B, run in lockstep under one policy (Shape, Cap, W) and
\* one probe. A sequential probe is up to MaxCalls steps; a step asks for an amount in Amounts,
\* and, when the call is admitted, settles or fails it one second later; then the clock moves on
\* by a gap in Gaps. One call is in flight at a time (in_flight 1), so whether an engine records
\* an admitted call when it admits it (Atomic) cannot change a verdict: Atomic is left out.
\*
\* An engine follows the kernel's rules as README states them: the view at `now` is the history
\* inside the window (sliding: an event at t counts while 0 <= now - t <= W; fixed: while it is in
\* now's bucket, (t + phase) \div W), plus the request under decision when reflexive; an admitted
\* request is recorded, a denial records the kinds in its deny marks, a settle a response and a
\* fail an error. Both engines share the phase, drawn from Phases at the start.
\*
\* Same: the two engines gave the same verdict at every step so far. TLC checking Same over every
\* probe and every phase finds no discriminating probe when Same holds: for every phase, A and B
\* give the same verdicts on every probe, so no probe within bounds can tell them apart.
EXTENDS Integers, Sequences

CONSTANTS Shape, Cap, W, Amounts, Gaps, MaxCalls, Phases,
          KindA, ReflA, MarksA, KindB, ReflB, MarksB

VARIABLES now, phase, n, ha, hb, same

vars == <<now, phase, n, ha, hb, same>>

Ev(t, k, a) == [t |-> t, kind |-> k, amt |-> a]

InView(kind, t) ==
    /\ t <= now
    /\ IF kind = "sliding" THEN now - t <= W
       ELSE (t + phase) \div W = (now + phase) \div W

RECURSIVE Sum(_, _, _)
Sum(h, kind, k) ==
    IF h = << >> THEN 0
    ELSE (IF Head(h).kind = k /\ InView(kind, Head(h).t) THEN Head(h).amt ELSE 0)
         + Sum(Tail(h), kind, k)

Left(h, kind, refl, a) ==
    LET req == Sum(h, kind, "request") + (IF refl THEN a ELSE 0) IN
    CASE Shape = "request-sum"           -> req
      [] Shape = "settled-plus-current"  -> Sum(h, kind, "response") + a
      [] Shape = "requests-minus-errors" -> req - Sum(h, kind, "error")

Permit(h, kind, refl, a) == Left(h, kind, refl, a) <= Cap

Marks(marks, a) ==
    (IF "request" \in marks THEN << Ev(now, "request", a) >> ELSE << >>)
    \o (IF "error" \in marks THEN << Ev(now, "error", a) >> ELSE << >>)

After(h, ok, marks, a, close) ==
    IF ok THEN h \o << Ev(now, "request", a), Ev(now + 1, close, a) >>
    ELSE h \o Marks(marks, a)

Init ==
    /\ now = 0
    /\ phase \in Phases
    /\ n = 0
    /\ ha = << >>
    /\ hb = << >>
    /\ same = TRUE

Step(a, close, g) ==
    LET va == Permit(ha, KindA, ReflA, a)
        vb == Permit(hb, KindB, ReflB, a)
    IN /\ same
       /\ n < MaxCalls
       /\ same' = (va = vb)
       /\ ha' = After(ha, va, MarksA, a, close)
       /\ hb' = After(hb, vb, MarksB, a, close)
       /\ now' = now + 1 + g
       /\ n' = n + 1
       /\ UNCHANGED phase

Next == \E a \in Amounts, close \in {"response", "error"}, g \in Gaps : Step(a, close, g)

Spec == Init /\ [][Next]_vars

Same == same
====
