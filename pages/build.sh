#!/usr/bin/env bash
# pages/build.sh OUT: assemble the site. pages/index.html is the front door; registry/ (the signed records and
# their verifier) is served at /record/. Nothing is generated here: every figure on the site was written by
# `kamanu assay`, and pages/index.html carries the record's figures as struck.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:?usage: pages/build.sh OUT}"
rm -rf "$OUT"
mkdir -p "$OUT/record"
cp pages/index.html "$OUT/index.html"
cp -R registry/. "$OUT/record/"
touch "$OUT/.nojekyll"
echo "site in $OUT: $(find "$OUT" -type f | wc -l) files"
