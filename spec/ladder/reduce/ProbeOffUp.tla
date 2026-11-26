---- MODULE ProbeOffUp ----
\* Two kernel instances in lockstep, lifted to the probe; the profiles and the probe
\* policy are MCProbe's own, read through the instance.
EXTENDS ProbeKernels
F == INSTANCE MCProbe
Reference    == F!Reference
NonReflexive == F!NonReflexive
DenyLogged   == F!DenyLogged
GlobalScope  == F!GlobalScope
AtMostOne(v, r) == F!AtMostOne(v, r)
Lockout(v, r)   == F!Lockout(v, r)
====
