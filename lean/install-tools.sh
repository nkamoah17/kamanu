#!/usr/bin/env bash
# Installs and verifies the outside checkers lean/tools.lock pins. Usage: bash lean/install-tools.sh
#
# Every tool in tools.lock ships in the bin/ of the Lean toolchain lean/lean-toolchain names, so the
# install is the toolchain's: elan installs it (when it is not there), then each tool is looked up in
# that bin/, its version checked where it reports one, and its binary hashed against tools.lock (the
# hashes are of the Windows x86_64 binaries; on another platform a differing hash is printed, not
# fatal, because the lock has no hash for that platform). A tool that is missing is reported with
# where tools.lock says it comes from, and the script exits 1: lean/check.sh --strict would fail.
set -euo pipefail
cd "$(dirname "$0")"
LOCK=tools.lock
[ -f "$LOCK" ] || { echo "FAIL: no $LOCK"; exit 1; }

if ! command -v lake >/dev/null; then PATH="$HOME/.elan/bin:$PATH"; fi
TOOLCHAIN="$(tr -d '\r\n' < lean-toolchain)"
if ! command -v elan >/dev/null; then
  echo "FAIL: elan is not installed (https://github.com/leanprover/elan); it installs $TOOLCHAIN"; exit 1
fi
elan toolchain install "$TOOLCHAIN" >/dev/null 2>&1 || true
PREFIX="$(lake env lean --print-prefix | tr -d '\r')"
if command -v cygpath >/dev/null; then PREFIX="$(cygpath -u "$PREFIX")"; fi
BIN="$PREFIX/bin"
WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WINDOWS=1 ;; esac

bad=0
while read -r tool version exe sha rest; do
  case "$tool" in ''|'#'*) continue ;; esac
  path=""
  for ext in "" ".exe"; do
    if [ -f "$BIN/$exe$ext" ]; then path="$BIN/$exe$ext"; break; fi
  done
  if [ -z "$path" ]; then
    echo "MISSING $tool ($exe) is not in $BIN: $rest"
    bad=1
    continue
  fi
  got="$(sha256sum "$path" | cut -d' ' -f1)"
  if [ "$got" != "$sha" ]; then
    if [ "$WINDOWS" = 1 ]; then
      echo "MISMATCH $tool: $path hashes to $got, tools.lock pins $sha"; bad=1; continue
    fi
    echo "note: $tool: $path hashes to $got (tools.lock holds the Windows binary's hash)"
  fi
  case "$tool" in
    leanexport)
      reported="$("$path" --version 2>/dev/null | head -n 1 | sed -nE 's/.*"exporter":\{"name":"lean4export","version":"([^"]+)".*/\1/p')"
      if [ "$reported" != "$version" ]; then echo "MISMATCH $tool: reports version '$reported', tools.lock pins $version"; bad=1; continue; fi ;;
    nanoda)
      reported="$("$path" --help 2>&1 | sed -nE 's/^nanoda_bin ([0-9.]+).*/\1/p' | head -n 1)"
      if [ "$reported" != "$version" ]; then echo "MISMATCH $tool: reports version '$reported', tools.lock pins $version"; bad=1; continue; fi ;;
  esac
  echo "ok $tool $version: $path"
done < "$LOCK"
exit "$bad"
