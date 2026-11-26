---- MODULE UndeterminedTaskOffUp ----
\* The seed task harness lifted to UndeterminedTask: und stays empty.
EXTENDS MCTask
CONSTANTS RefuseRecord, InFlightGuard
NoRefuse(i) == FALSE
F == INSTANCE UndeterminedTask WITH und <- {}
====
