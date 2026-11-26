#!/usr/bin/env bash
# The gate for the Lean proofs. Usage: bash lean/check.sh [--strict] [repository]   (from anywhere;
# on Windows under Git Bash). In this repository: bash lean/check.sh --strict .
#   1. build every module from clean
#   2. audit: no `sorry`, no axiom beyond Lean's three standard ones
#   3. re-check the compiled proofs outside the kernel that built them: leanchecker, then
#      leanexport's export of the library checked by con-leche, con-ron and nanoda
#      (lean/tools.lock pins each; lean/install-tools.sh installs and verifies them)
#   4. (with a repo path) run the Lean machine against kamanu/fast/machine.py
#
# A tool is found when it is on PATH or in the Lean toolchain's own bin/ (`lean --print-prefix`).
# Without --strict a tool that is not found is skipped, and the line says so. With --strict
# (the first argument) a missing exporter or checker is a failure: the script says which,
# exits 1 and never prints ALL CHECKS PASSED. A checker that does not report its acceptance
# fails in either mode.
#
# KAMANU_CHECKERS_RECORD=<file> writes the run of step 3 there as JSON (the shape of
# evidence/exonumia/x3/checkers.json, without lean_sha256, which the caller adds).
set -euo pipefail

STRICT=0
if [ "${1:-}" = "--strict" ]; then
  STRICT=1
  shift
fi

# The repository is named relative to the caller's directory: resolve it before leaving it.
REPO=""
if [ "${1:-}" != "" ]; then
  REPO="$(cd "$1" && pwd)"
fi
cd "$(dirname "$0")"

if ! command -v lake >/dev/null; then
  PATH="$HOME/.elan/bin:$PATH"
fi

# python3 or python, whichever runs (Windows may have a python3 that only opens the Store).
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null && "$c" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
    PY="$c"
    break
  fi
done

now() { date +%s%N; }
secs() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", (b - a) / 1e9 }'; }

# The toolchain's bin/: where Lean ships its own exporter and checkers.
TCBIN=""
if PREFIX="$(lake env lean --print-prefix 2>/dev/null | tr -d '\r')" && [ -n "$PREFIX" ]; then
  if command -v cygpath >/dev/null; then PREFIX="$(cygpath -u "$PREFIX")"; fi
  if [ -d "$PREFIX/bin" ]; then TCBIN="$PREFIX/bin"; fi
fi

# find_tool NAME... : the path of the first NAME on PATH or in the toolchain's bin/, or nothing.
find_tool() {
  local n ext
  for n in "$@"; do
    if command -v "$n" >/dev/null 2>&1; then command -v "$n"; return 0; fi
    if [ -n "$TCBIN" ]; then
      for ext in "" ".exe"; do
        if [ -f "$TCBIN/$n$ext" ]; then echo "$TCBIN/$n$ext"; return 0; fi
      done
    fi
  done
  return 1
}

# pinned TOOL : the version lean/tools.lock pins for TOOL (its second field).
pinned() { awk -v t="$1" '$1 == t { print $2; exit }' tools.lock 2>/dev/null || true; }

LEANEXPORT="$(find_tool leanexport || true)"
CON_LECHE="$(find_tool con-leche || true)"
CON_RON="$(find_tool con-ron || true)"
NANODA="$(find_tool nanoda nanoda_bin || true)"

MISSING=""
[ -n "$LEANEXPORT" ] || MISSING="$MISSING leanexport"
[ -n "$CON_LECHE" ] || MISSING="$MISSING con-leche"
[ -n "$CON_RON" ] || MISSING="$MISSING con-ron"
[ -n "$NANODA" ] || MISSING="$MISSING nanoda"
if [ "$STRICT" = 1 ] && [ -n "$MISSING" ]; then
  for t in $MISSING; do
    echo "FAIL (--strict): $t not found, neither on PATH nor in the toolchain's bin/ (${TCBIN:-no toolchain found})"
  done
  echo "FAIL: --strict needs leanexport, con-leche, con-ron and nanoda; install them with lean/install-tools.sh"
  exit 1
fi

echo "== 1. build"
rm -rf .lake/build
lake build

echo "== 2. axiom audit"
if grep -rnw --include='*.lean' -e sorry Kamanu Kamanu.lean; then
  echo "FAIL: sorry in source"; exit 1
fi
lake env lean Audit.lean > audit.out
cat audit.out
if grep -v "depends on axioms: \[propext, Classical.choice, Quot.sound\]$" audit.out \
   | grep -v "depends on axioms: \[propext, Quot.sound\]$" \
   | grep -v "depends on axioms: \[propext\]$" \
   | grep -v "does not depend on any axioms$" | grep -q .; then
  echo "FAIL: unexpected axiom"; exit 1
fi
echo "audit ok: $(wc -l < audit.out) theorems, standard axioms only"
rm -f audit.out

echo "== 3. independent checkers"
LEANCHECKER="$(find_tool leanchecker || true)"
if [ -n "$LEANCHECKER" ]; then
  lake env "$LEANCHECKER" Kamanu && echo "leanchecker: every module replayed through the kernel"
elif [ "$STRICT" = 1 ]; then
  echo "FAIL (--strict): leanchecker not found"; exit 1
else
  echo "leanchecker: not found, skipped"
fi

# The record of this step, filled as the tools run.
EXPORT_JSON=""
declare -A CHECKER_JSON=()
skip_all() {
  local why="$1" c
  EXPORT_JSON="{\"reason\": \"$why\"}"
  for c in con-leche con-ron nanoda; do
    CHECKER_JSON[$c]="{\"verdict\": \"not run\", \"reason\": \"$why\"}"
  done
}

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
if [ -z "$LEANEXPORT" ]; then
  echo "leanexport: not found, skipped (and with it every checker of the export)"
  skip_all "leanexport not found on PATH or in the toolchain's bin/"
else
  EXPORT="$TMPD/export.ndjson"
  t0="$(now)"
  lake env "$LEANEXPORT" Kamanu > "$EXPORT"
  t1="$(now)"
  NDECL="$(grep -cE '^\{"(axiom|def|thm|opaque|quot|inductive)"' "$EXPORT" || true)"
  echo "leanexport $(pinned leanexport): exported $NDECL declarations in $(secs "$t0" "$t1") s"
  EXPORT_JSON="{\"tool\": \"leanexport\", \"version\": \"$(pinned leanexport)\", \"declarations\": $NDECL, \"seconds\": $(secs "$t0" "$t1")}"

  # run_checker NAME PATTERN CMD... : runs CMD, requires exit 0 and PATTERN's count in its output.
  run_checker() {
    local name="$1" pattern="$2" out n t0 t1 code
    shift 2
    t0="$(now)"
    set +e
    out="$("$@" 2>&1)"
    code=$?
    set -e
    t1="$(now)"
    printf '%s\n' "$out" | tail -n 5
    n="$(printf '%s\n' "$out" | sed -nE "s/.*$pattern.*/\1/p" | tail -n 1)"
    if [ "$code" != 0 ] || [ -z "$n" ]; then
      echo "FAIL: $name rejected the export or reported no count (exit $code)"
      exit 1
    fi
    echo "$name $(pinned "$name"): accepted $n declarations in $(secs "$t0" "$t1") s"
    CHECKER_JSON[$name]="{\"version\": \"$(pinned "$name")\", \"verdict\": \"accepted\", \"declarations\": $n, \"seconds\": $(secs "$t0" "$t1")}"
  }

  for c in con-leche con-ron; do
    if [ "$c" = con-leche ]; then exe="$CON_LECHE"; else exe="$CON_RON"; fi
    if [ -z "$exe" ]; then
      echo "$c: not found, skipped"
      CHECKER_JSON[$c]="{\"verdict\": \"not run\", \"reason\": \"$c not found on PATH or in the toolchain's bin/\"}"
    else
      run_checker "$c" "accepted ([0-9]+) declarations" "$exe" --verified "$EXPORT"
    fi
  done
  if [ -z "$NANODA" ]; then
    echo "nanoda: not found, skipped"
    CHECKER_JSON[nanoda]="{\"verdict\": \"not run\", \"reason\": \"nanoda not found on PATH or in the toolchain's bin/\"}"
  else
    CFG="$TMPD/nanoda.json"
    EXPORT_PATH="$EXPORT"
    if command -v cygpath >/dev/null; then EXPORT_PATH="$(cygpath -m "$EXPORT")"; fi
    printf '{"export_file_path": "%s", "permitted_axioms": ["propext", "Classical.choice", "Quot.sound"], "unpermitted_axiom_hard_error": false, "nat_extension": true, "string_extension": true, "print_success_message": true}' "$EXPORT_PATH" > "$CFG"
    CFG_PATH="$CFG"
    if command -v cygpath >/dev/null; then CFG_PATH="$(cygpath -m "$CFG")"; fi
    run_checker nanoda "Checked ([0-9]+) declarations with no typechecker errors" "$NANODA" "$CFG_PATH"
  fi
  rm -f "$EXPORT"
fi

if [ -n "${KAMANU_CHECKERS_RECORD:-}" ]; then
  {
    echo "{"
    echo "  \"date\": \"$(date -u +%Y-%m-%d)\","
    echo "  \"platform\": \"$(uname -s) $(uname -r) $(uname -m)\","
    echo "  \"strict\": $([ "$STRICT" = 1 ] && echo true || echo false),"
    echo "  \"export\": $EXPORT_JSON,"
    echo "  \"checkers\": {"
    echo "    \"con-leche\": ${CHECKER_JSON[con-leche]},"
    echo "    \"con-ron\": ${CHECKER_JSON[con-ron]},"
    echo "    \"nanoda\": ${CHECKER_JSON[nanoda]}"
    echo "  }"
    echo "}"
  } > "$KAMANU_CHECKERS_RECORD"
fi

if [ "$REPO" != "" ]; then
  echo "== 4. differential tests against $REPO"
  if [ "$PY" = "" ]; then
    echo "FAIL: no python3 or python for the differential tests"; exit 1
  fi
  "$PY" -I tests/diff_norm.py "$REPO" 200000 1
  "$PY" -I tests/diff_norm.py "$REPO" 200000 2
  "$PY" -I tests/diff_steps.py "$REPO" 4000 1
  "$PY" -I tests/diff_steps.py "$REPO" 4000 2
fi
echo "ALL CHECKS PASSED"
