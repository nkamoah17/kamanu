"""A process of `kamanu lint --jobs N` (R17): `python -m kamanu.fast.share` lints the chunks it is handed.

Protocol on its stdin and stdout (kamanu.fast.cli._bulk speaks the other side): one JSON line {"files", "opts",
"chunk"}; then, for each line holding a chunk index c (-1: no more), the chunk's files are linted
(kamanu.fast.cli.work) and the answer is one line "<bytes of output> <bytes of meta>" followed by the output (a
JSON line per file with --json, else its text) and the meta ({"codes", "sarif"} or {"error": one line}) as JSON.
It imports what lint needs and nothing of the command line's, and writes no file.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    job = json.loads(inp.readline())
    from kamanu.fast.cli import work
    opts = dict(job["opts"])
    if opts.get("amounts") is not None:
        opts["amounts"] = tuple(opts["amounts"])
    files, chunk = job["files"], int(job["chunk"])
    while True:
        line = inp.readline()
        if not line:
            break
        c = int(line)
        if c < 0:
            break
        body, meta = work(files[c * chunk:(c + 1) * chunk], opts)
        raw = json.dumps(meta).encode("utf-8")
        out.write(f"{len(body)} {len(raw)}\n".encode("ascii") + body + raw)
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
