"""The cabinet: every scan leaves a receipt, and the next scan reads what the receipts add up to.

    kamanu scan --card PROFILE                     scan a card profile (card-v1)
    kamanu scan POLICY --engine ENGINE             scan a policy as `kamanu assay` reads it
    kamanu scan CONTROLS.yaml --frontend issuing --engine ENGINE
    kamanu scan --ingest FILE|DIR                  deposit what is already there (hallmarks, hunt and rail rows,
                                                   reference-ledger reports of a program's own handler)
    kamanu scan --census | --verify | --replay | --export PACK | --import PACK

What is kept, and grows with every scan:

    receipts   one receipt-v1 per answer, appended to receipts.jsonl (kamanu.cabinet.chain). Each line carries the
               SHA-256 of the line before it, so a changed, dropped, moved or torn receipt breaks the chain at a
               named line. A receipt is signed with X1's scheme when a key is given (kamanu.assay.record.sign).
    types      the ledger, the count's shape, the window kind and the engine's constants, with no amount or name.
    dies       a type, a check, its status and its shortest failing trace's signature, amounts read only as below,
               at or above the face value. Two findings struck from one die are the same failure on two limits.
    plates     the first receipt of each die that holds a replay, kept as plates/DIE.json with what it expects.
               `kamanu scan --replay` runs every plate on the code as it is now and names each that drifted.

THE RULE. A verdict, a figure and a level are computed by the machine that already computes them
(kamanu.assay.card, kamanu.assay.hallmark over lint), and the cabinet never changes one: the same input gives
the same figures, checks, level and hypotheses on an empty cabinet and on a full one, and a constant measured
elsewhere in the cabinet never changes a hypothesis's status or a level. What a scan is told (kamanu.cabinet.
census.told), after its answer and apart from it, is what no single run can know: the type's population
(distinct subjects), whether each die is new or how often it was struck, how the fineness stands, drift, what
changed since the last receipt of the same label, what a receipt of an engine of the same name holds measured
of a constant the scan assumes, how many constants are assumed, and the repairs seen. Each line is a count of
this cabinet's receipts with its dates: a census of what was scanned here, never a statement about a market.

WHERE. --cabinet DIR, else $KAMANU_CABINET, else ~/.kamanu/cabinet. Only `kamanu scan` writes there: `kamanu
lint` starts no process and writes nothing (R13), and `kamanu assay` is unchanged. Nothing is uploaded. An
export pack (census-v1) holds types, dies and measured engine constants with their counts and no subject hash,
label, policy text, profile, trace, replay or receipt id; a third party's receipt still held on the export day
(rule E5) and a private receipt are left out of it in every form, counts included.

Standard library only (and PyYAML, which the wheel already depends on, to split an issuing configuration).
"""
from __future__ import annotations

import os
from pathlib import Path

ENV = "KAMANU_CABINET"


def home(arg: str | None = None) -> Path:
    """The cabinet's directory: ARG, else $KAMANU_CABINET, else ~/.kamanu/cabinet."""
    if arg:
        return Path(arg)
    env = os.environ.get(ENV)
    if env and env.strip():
        return Path(env)
    return Path.home() / ".kamanu" / "cabinet"
