"""kamanu assay (X1): a limit's face value, its assayed ceiling, fineness and stranded budget as one signed
hallmark that verifies from a clean machine.

    kamanu assay POLICY --engine ENGINE [--cap N] [--in-flight C] [--failures F] [--amounts A,B]
                 [--key PRIVATE] [--out RECORD] [--third-party] [--notified YYYY-MM-DD]
    kamanu assay --verify RECORD --key PUBLIC [--recompute]

    fineness(face, ceiling) -> str      face / ceiling to three decimals, never rounded up; ".000" when the
                                        ceiling is "unbounded"
    main(argv) -> int                   the command (kamanu.assay.cli)

Nothing here is new semantics. The ceiling is lint's exposure (kamanu.fast.exposure, through `kamanu lint
--exposure --json`): the worst "spent" of the scope ledger's Sound FAILS verdicts over the rungs, "unbounded"
when any is, the cap when none fails. The stranded budget is the worst "stranded" of its Tight FAILS verdicts
(kamanu.ladder.stranded), 0 when none fails. The levels are the ones lint's verdicts carry (T2, T8b). An open or
UNKNOWN answer issues no hallmark.

The record (schema/hallmark.schema.json, hallmark-v1) is signed with Ed25519 (kamanu.assay.ed25519, standard
library only): "signature" holds the SHA-256 of the canonical JSON of every other top-level field and a signature
of the canonical JSON of those digests, so a changed field fails by its name. The signing key is never in the
repository: --key names its file, else $KAMANU_ASSAY_KEY does (a file of 64 hex digits, the 32-byte seed).

This module imports nothing at load time, so `import kamanu.assay.ed25519` loads the standard library alone.
"""
from __future__ import annotations


def fineness(face: int, ceiling) -> str:
    """face / ceiling written with exactly three decimals and never rounded up: floor(1000 face / ceiling) / 1000.
    ".000" for an unbounded ceiling; "1.000" only when the ceiling is the face (or below it)."""
    if ceiling == "unbounded":
        return ".000"
    if isinstance(face, bool) or isinstance(ceiling, bool) or not isinstance(face, int) or not isinstance(ceiling, int):
        raise ValueError(f"fineness takes an integer face and an integer or 'unbounded' ceiling, not {face!r}, {ceiling!r}")
    if face < 0 or ceiling <= 0:
        raise ValueError(f"fineness needs a face of 0 or more and a ceiling above 0, not {face}, {ceiling}")
    milli = (1000 * face) // ceiling
    whole, frac = divmod(milli, 1000)
    return f"{whole}.{frac:03d}" if whole else f".{frac:03d}"


def main(argv=None) -> int:
    from kamanu.assay.cli import main as run
    return run(argv)
