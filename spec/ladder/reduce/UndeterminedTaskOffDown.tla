---- MODULE UndeterminedTaskOffDown ----
\* K6's task USpec (the seed task harness with Refuse) with Refuse disabled, reduced to the
\* seed task harness. The configuration overrides Refuse: Refuse <- NoRefuse.
EXTENDS UndeterminedTask
NoRefuse(i) == FALSE
T == INSTANCE MCTask
====
