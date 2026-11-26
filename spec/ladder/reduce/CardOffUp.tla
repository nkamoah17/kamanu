---- MODULE CardOffUp ----
\* The ledger with holds lifted to the card ledger (X4): over-capture and force-post off, every step of
\* CardHolds is a step of Card. Nothing is mapped (no variable of Card's is missing here).
EXTENDS CardHolds
CONSTANTS OverCapture, ForcePost
F == INSTANCE Card
====
