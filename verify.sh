#!/usr/bin/env bash
# verify.sh: check KAMANU's Lean proofs from a clean clone, as a stranger would (docs/verify.md).
#
#   bash verify.sh            (Linux, macOS, or Git Bash on Windows; needs elan's Lean, as
#                              lean/lean-toolchain names it, and Python 3.9+ with pytest)
#
# It runs, in order, and prints one table with each step's result and time, then the total:
#   1 tools       lean/install-tools.sh: the exporter and the three outside checkers lean/tools.lock pins
#   2 check       lean/check.sh --strict .: build from clean, the axiom audit, leanchecker, leanexport's
#                 export checked by con-leche, con-ron and nanoda (a missing one fails), and the Lean
#                 machine against kamanu/fast/machine.py
#   3 audit       lean/Audit.lean once more, counted: every theorem a link of evidence/levels/links.json
#                 names, standard axioms only
#   4 diff tests  tests/test_lean*.py: each executable Lean step against the Python it models
# Exit 0 only when every step passes.
set -uo pipefail
cd "$(dirname "$0")"
START=$SECONDS

if ! command -v lake >/dev/null; then PATH="$HOME/.elan/bin:$PATH"; fi
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null && "$c" -c "import sys, pytest; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

LOG="$(mktemp -d)"
NAMES=()
RESULTS=()
TIMES=()
FAILED=0

step() {
  local name="$1" t0=$SECONDS rc
  shift
  echo "== $name: $*"
  "$@" > "$LOG/$name.log" 2>&1
  rc=$?
  tail -n 8 "$LOG/$name.log"
  NAMES+=("$name")
  TIMES+=($((SECONDS - t0)))
  if [ "$rc" = 0 ]; then RESULTS+=("passed"); else RESULTS+=("FAILED (exit $rc; log $LOG/$name.log)"); FAILED=1; fi
}

audit() {
  local out bad
  out="$(cd lean && lake env lean Audit.lean)" || return 1
  bad="$(printf '%s\n' "$out" | grep -v -E "depends on axioms: \[(propext(, Classical\.choice)?(, Quot\.sound)?)\]$|does not depend on any axioms$" || true)"
  echo "$(printf '%s\n' "$out" | grep -c "axioms") theorems audited"
  [ -z "$bad" ] || { echo "beyond the standard axioms:"; echo "$bad"; return 1; }
}

difftests() {
  [ -n "$PY" ] || { echo "no python3 or python 3.9+ with pytest"; return 1; }
  "$PY" -m pytest -q -p no:cacheprovider tests/test_lean*.py
}

step tools bash lean/install-tools.sh
step check bash lean/check.sh --strict .
step audit audit
step difftests difftests

TOTAL=$((SECONDS - START))
echo
printf '%-10s  %-8s  %s\n' "step" "seconds" "result"
printf '%-10s  %-8s  %s\n' "----" "-------" "------"
for i in "${!NAMES[@]}"; do
  printf '%-10s  %-8s  %s\n' "${NAMES[$i]}" "${TIMES[$i]}" "${RESULTS[$i]}"
done
printf '%-10s  %-8s  %s\n' "total" "$TOTAL" "$([ "$FAILED" = 0 ] && echo "every step passed" || echo "a step FAILED")"
echo "verify.sh took $((TOTAL / 60)) min $((TOTAL % 60)) s on $(uname -s) $(uname -m), $(date -u +%Y-%m-%d)"
exit "$FAILED"
