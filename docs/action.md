# The GitHub Action

`action.yml` at the root of this repository is a composite action. On a pull request it runs
`kamanu check` on every `.dw` policy the pull request adds or modifies (`git diff base...head`,
deletions left out), against the engine profile you name, uploads the findings to code scanning as
SARIF, and fails the job with check's largest exit code.

With `scan: 'true'` it also runs `kamanu scan` (docs/scan.md) on each changed policy and keeps the
receipts in a cabinet that is carried from run to run and verified before it is kept.

## Inputs and outputs

| input | default | what it does |
|---|---|---|
| `engine` | (required) | the engine profile: a profile JSON's path in your repository, or a built-in name such as `reference` |
| `setup-python` | `'true'` | set up Python 3.12 first |
| `category` | `kamanu` | the code scanning category |
| `upload` | `'true'` | upload the SARIF |
| `scan` | `'false'` | after check, scan each changed policy into the cabinet, verify it and keep it |
| `scan-fails` | `'false'` | fail the job with the largest scan exit when it is not 0 |
| `cabinet-key` | `kamanu-cabinet` | the stem of the cabinet's cache key |

| output | what it holds |
|---|---|
| `exit-code` | check's largest exit code (0 when no policy changed) |
| `sarif` | the merged SARIF file's path |
| `policies` | the policies checked, one per line |
| `scan-exit-code` | the largest exit `kamanu scan` gave (empty when `scan` is `'false'`) |

## What `scan: 'true'` adds

1. **Restore.** `actions/cache/restore` restores the cabinet to `$RUNNER_TEMP/kamanu-cabinet` under
   the key `<cabinet-key>-<run id>-<run attempt>`, with the restore key `<cabinet-key>-`: the newest
   cabinet saved on this pull request's branch (or else on the default branch, as GitHub scopes
   caches), so the chain carries over from the branch's last run.
2. **Scan.** `kamanu scan FILE --engine ENGINE --label FILE --cabinet $RUNNER_TEMP/kamanu-cabinet` for
   each changed policy, from the workspace: one receipt per changed policy, labelled with its
   repository path. A scan that finds a check that FAILS does not fail this step.
3. **Verify.** `kamanu scan --verify` on the cabinet. A chain that does not check (a receipt changed,
   a line removed) fails the job, and the cabinet is neither uploaded nor saved.
4. **Keep.** Only when the chain checks: `actions/upload-artifact` uploads the cabinet as the artifact
   `kamanu-cabinet`, and `actions/cache/save` saves it under the run's key. Both run whatever check
   concluded (a failing check does not stop the chain from carrying over to the next run). The save is
   a separate step because the combined `actions/cache` saves only when the job succeeds.
5. **Result.** The output `scan-exit-code` is the largest scan exit. The job's result stays check's
   unless `scan-fails` is `'true'`, in which case a scan exit other than 0 fails the job too.

The step summary holds one part per scanned policy, opened by a heading naming its path: the scan's
whole answer, where every figure (face value, ceiling, fineness, stranded budget) stands beside the
levels of the checks it rests on, the receipt's level and each hypothesis with its status (rule E1),
then the cabinet's lines (the census of this cabinet and the drift line). The `--verify` answer
closes the summary.

With `scan: 'false'` (the default) none of these steps runs: no cache, no artifact, no receipt.

## A workflow

```yaml
name: kamanu
on: pull_request
permissions:
  contents: read
  security-events: write
  actions: write
jobs:
  kamanu:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'
      - id: kamanu
        uses: nkamoah17/kamanu@v0.1
        with:
          engine: .kamanu/payments-engine.json
          scan: 'true'
          scan-fails: 'false'
          cabinet-key: kamanu-cabinet
      - if: always()
        run: echo "largest scan exit ${{ steps.kamanu.outputs.scan-exit-code }}"
```

`fetch-depth: 0` lets the action find the pull request's merge base without fetching again; the
action fetches what a shallow checkout lacks otherwise. Java is for `kamanu check`, which runs TLC;
`kamanu scan` does not need it. Download the cabinet from the run's artifacts and run
`kamanu scan --verify --cabinet DIR` on it to check its chain yourself.
