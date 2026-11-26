---- MODULE ProgressOffDown ----
\* Progress (K7) with the seed's untimed timer (Fixed = FALSE), reduced to the seed task
\* harness: Elapse moves only the clock.
EXTENDS Progress
T == INSTANCE MCTask
====
