---- MODULE ProgressOffUp ----
\* The seed task harness lifted to Progress: the clock stays at 0.
EXTENDS MCTask
CONSTANTS Fixed, Deadline
F == INSTANCE Progress WITH clock <- 0
====
