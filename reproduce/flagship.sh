#!/usr/bin/env bash
# The commands of post/flagship.md's "How to reproduce" section, exactly. Run it in an empty
# directory: it clones the repository, installs it and prints the post's headline number.
set -euo pipefail

git clone https://github.com/nkamoah17/kamanu.git kamanu
cd kamanu
pip install .
python reproduce/headline.py
