# `kamanu admit`: admission before a rule goes live

A generated rule matters most just before it becomes active, not at the pull request. `kamanu admit`
runs lint on that moment and gives one answer, on one line:

```
kamanu admit POLICY|- --engine ENGINE [--level error|warning|note] [--allow-outside] [--honour-suppressions]
```

It writes exactly one JSON line on standard output, `{"admitted", "reason", "command", "level", "policy",
"failing"}`, and exits 0 exactly when the rule is admitted (1 otherwise). A rule is admitted only when:

- lint gives a verdict: the policy is inside the fast path and every verdict holds (none open, none
  failing);
- no finding at or above `--level` fails (an error is above a warning, a warning above a note; the
  default level is `warning`). A failing Sound or Tight verdict is a finding of level error.

Besides that:

- a policy **outside** the fast path is not admitted unless `--allow-outside`; the line's `"command"` is
  the `kamanu check ...` command that decides it;
- an inline suppression (`// kamanu-ignore RULE: reason`) is **ignored** unless `--honour-suppressions`:
  a comment in the rule does not silence the gate. There is no ignore file;
- a policy file it cannot read, or an engine it cannot load, is not admitted (the one line all the same).

`POLICY` is a file, or `-` for standard input. The command is the same call as the library function a
gateway uses in process, answer for answer:

```python
from kamanu.admit import admit

answer = admit(policy_text, "profiles/dogwood-1.1.1.json")      # path=None: standard input
if not answer["admitted"]:
    raise PermissionError(answer["reason"])
```

## As an agent hook

An agent that writes rules runs the admission before it activates one. A hook in the agent's
configuration (here a Claude Code `PreToolUse` hook on the tool that activates a rule) pipes the rule's
text to `kamanu admit -`; a non-zero exit blocks the activation and the JSON line says why:

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "activate_rule",
       "hooks": [{"type": "command",
                  "command": "jq -r .tool_input.policy | kamanu admit - --engine profiles/dogwood-1.1.1.json"}]}
    ]
  }
}
```

While it writes the rule the agent can read the same findings through the lint MCP server
(`kamanu-lint-mcp`, tool `lint`): each finding carries a one-sentence claim, its trace, a fix as an edit
and the command that re-checks it.

## As a pre-commit entry

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: kamanu-admit
        name: kamanu admit
        entry: kamanu admit --engine profiles/dogwood-1.1.1.json
        language: system
        files: \.dw$
```

pre-commit passes each changed `.dw` file; the commit is refused when one is not admitted.

## As the Action step

The action runs `kamanu check` and, beside it, a `kamanu lint` step that annotates each changed policy
with its findings (claim, fix, re-check). Admission runs as a step of its own, before deployment:

```yaml
jobs:
  policies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: nkamoah17/kamanu@v1
        with:
          engine: profiles/dogwood-1.1.1.json
      - name: kamanu admit before deploy
        run: |
          for p in policies/*.dw; do
            kamanu admit "$p" --engine profiles/dogwood-1.1.1.json || exit 1
          done
```

## Fixing what blocks admission

`kamanu lint POLICY --engine ENGINE --json` gives every finding its fix where lint knows one (KAM001's
`::request` to `::response`; for a failing verdict, the repaired comparison `kamanu fix` finds) and
`kamanu lint POLICY --engine ENGINE --fix` applies them and lints again. evidence/ladder/r16g/ holds a
recorded run of an agent with no model that takes ten planted broken policies to passing ones using
only the JSON.
