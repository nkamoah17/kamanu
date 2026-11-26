---- MODULE CardOffDown ----
\* The card ledger (X4) reduced to the ledger with holds: the feature's side. The two share every
\* variable (hs, ha, held, spent, doubt, buf), so nothing is mapped.
EXTENDS Card
T == INSTANCE CardHolds
====
