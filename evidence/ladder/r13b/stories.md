# R13b: the fast path's claims, one two-ledger story each

Each story is a trace from lint's machine, one line per kernel step: its actor, then the engine's count (counted) and the ledger (held, spent, doubt). The gate replays such traces in TLC.

## Exposure: a race on a not-atomic engine

request-sum cap 100, not atomic, 3 calls in flight: the worst real spend is 110 over the cap, measured (the fitted (c-1) x A gives 120; fitted, not a bound).

```
the trace that reaches the exposure:
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [engine] the engine admits the call for 60 | counted 0 | held 60 | spent 0 | doubt 0
   3. [harness] the harness issues a call for 60 | counted 0 | held 60 | spent 0 | doubt 0
   4. [engine] the engine admits the call for 60 | counted 0 | held 120 | spent 0 | doubt 0
   5. [harness] the harness issues a call for 30 | counted 0 | held 120 | spent 0 | doubt 0
   6. [engine] the engine admits the call for 30 | counted 0 | held 150 | spent 0 | doubt 0
   7. [engine] the engine writes the call for 30 into its history | counted 30 | held 150 | spent 0 | doubt 0
   8. [tool] the tool runs the call for 30 and the money moves | counted 30 | held 120 | spent 30 | doubt 0
   9. [harness] the harness issues a call for 30 | counted 30 | held 120 | spent 30 | doubt 0
  10. [engine] the engine admits the call for 30 | counted 30 | held 150 | spent 30 | doubt 0
  11. [engine] the engine writes the call for 30 into its history | counted 60 | held 150 | spent 30 | doubt 0
  12. [tool] the tool runs the call for 30 and the money moves | counted 60 | held 120 | spent 60 | doubt 0
  13. [harness] the harness issues a call for 30 | counted 60 | held 120 | spent 60 | doubt 0
  14. [engine] the engine admits the call for 30 | counted 60 | held 150 | spent 60 | doubt 0
  15. [engine] the engine writes the call for 60 into its history | counted 120 | held 150 | spent 60 | doubt 0
  16. [tool] the tool runs the call for 60 and the money moves | counted 120 | held 90 | spent 120 | doubt 0
  17. [engine] the engine writes the call for 60 into its history | counted 180 | held 90 | spent 120 | doubt 0
  18. [tool] the tool runs the call for 60 and the money moves | counted 180 | held 30 | spent 180 | doubt 0
  19. [engine] the engine writes the call for 30 into its history | counted 210 | held 30 | spent 180 | doubt 0
  20. [tool] the tool runs the call for 30 and the money moves | counted 210 | held 0 | spent 210 | doubt 0
```

## Exposure: refund-on-error at R2

requests minus errors, atomic: Sound holds at R0 and R1 and FAILS at R2, where an ambiguous failure moves money and still writes an error; the worst spend is 50 over the cap.

```
the trace that reaches the exposure:
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   3. [harness] the harness issues a call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   4. [tool] the tool reports an error on the call for 60, yet the money moves | counted 0 | held 0 | spent 60 | doubt 0
   5. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 60 | doubt 0
   6. [harness] the harness issues a call for 30 | counted 60 | held 60 | spent 60 | doubt 0
   7. [engine] the engine admits the call for 30 | counted 90 | held 90 | spent 60 | doubt 0
   8. [tool] the tool runs the call for 60 and the money moves | counted 90 | held 30 | spent 120 | doubt 0
   9. [tool] the tool runs the call for 30 and the money moves | counted 90 | held 0 | spent 150 | doubt 0
  10. [harness] the harness reconciles the call for 60: the money moved, so it stands | counted 90 | held 0 | spent 150 | doubt 0
```

## Exposure: a policy that never counts what it spends

errors plus the current amount: the exposure is unbounded; steps 3 to 5 repeat and every repetition moves more money.

```
the trace and its repeated part:
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [engine] the engine admits the call for 60 | counted 0 | held 60 | spent 0 | doubt 0
   3. [tool] the tool runs the call for 60 and the money moves | counted 0 | held 0 | spent 60 | doubt 0
   4. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 60 | doubt 0
   5. [engine] the engine admits the call for 60 | counted 0 | held 60 | spent 60 | doubt 0
```

## Exposure: the caller's ledger grows with every session

request-sum on a session-scoped engine whose keys are the caller's: 80 over with 2 sessions, 170 over with 3 sessions.

```
three sessions of one caller:
   1. [harness] the harness issues a call for 30 in session 3 | counted 0 | held 0 | spent 0 | doubt 0 | caller 0
   2. [engine] the engine admits the call for 30 in session 3 | counted 30 | held 30 | spent 0 | doubt 0 | caller 30
   3. [tool] the tool runs the call for 30 in session 3 and the money moves | counted 30 | held 0 | spent 30 | doubt 0 | caller 30
   4. [harness] the harness issues a call for 30 in session 3 | counted 30 | held 0 | spent 30 | doubt 0 | caller 30
   5. [harness] the harness issues a call for 30 in session 3 | counted 30 | held 0 | spent 30 | doubt 0 | caller 30
   6. [engine] the engine admits the call for 30 in session 3 | counted 60 | held 30 | spent 30 | doubt 0 | caller 60
   7. [engine] the engine admits the call for 30 in session 3 | counted 90 | held 60 | spent 30 | doubt 0 | caller 90
   8. [tool] the tool runs the call for 30 in session 3 and the money moves | counted 90 | held 30 | spent 60 | doubt 0 | caller 90
   9. [tool] the tool runs the call for 30 in session 3 and the money moves | counted 90 | held 0 | spent 90 | doubt 0 | caller 90
  10. [harness] the harness issues a call for 30 in session 2 | counted 0 | held 0 | spent 0 | doubt 0 | caller 90
  11. [harness] the harness issues a call for 30 in session 2 | counted 0 | held 0 | spent 0 | doubt 0 | caller 90
  12. [engine] the engine admits the call for 30 in session 2 | counted 30 | held 30 | spent 0 | doubt 0 | caller 120
  13. [tool] the tool runs the call for 30 in session 2 and the money moves | counted 30 | held 0 | spent 30 | doubt 0 | caller 120
  14. [harness] the harness issues a call for 30 in session 2 | counted 30 | held 0 | spent 30 | doubt 0 | caller 120
  15. [engine] the engine admits the call for 30 in session 2 | counted 60 | held 30 | spent 30 | doubt 0 | caller 150
  16. [engine] the engine admits the call for 30 in session 2 | counted 90 | held 60 | spent 30 | doubt 0 | caller 180
  17. [tool] the tool runs the call for 30 in session 2 and the money moves | counted 90 | held 30 | spent 60 | doubt 0 | caller 180
  18. [tool] the tool runs the call for 30 in session 2 and the money moves | counted 90 | held 0 | spent 90 | doubt 0 | caller 180
  19. [harness] the harness issues a call for 30 in session 1 | counted 0 | held 0 | spent 0 | doubt 0 | caller 180
  20. [harness] the harness issues a call for 30 in session 1 | counted 0 | held 0 | spent 0 | doubt 0 | caller 180
  21. [engine] the engine admits the call for 30 in session 1 | counted 30 | held 30 | spent 0 | doubt 0 | caller 210
  22. [tool] the tool runs the call for 30 in session 1 and the money moves | counted 30 | held 0 | spent 30 | doubt 0 | caller 210
  23. [harness] the harness issues a call for 30 in session 1 | counted 30 | held 0 | spent 30 | doubt 0 | caller 210
  24. [engine] the engine admits the call for 30 in session 1 | counted 60 | held 30 | spent 30 | doubt 0 | caller 240
  25. [engine] the engine admits the call for 30 in session 1 | counted 90 | held 60 | spent 30 | doubt 0 | caller 270
  26. [tool] the tool runs the call for 30 in session 1 and the money moves | counted 90 | held 30 | spent 60 | doubt 0 | caller 270
  27. [tool] the tool runs the call for 30 in session 1 and the money moves | counted 90 | held 0 | spent 90 | doubt 0 | caller 270
```

## Diff: the same text, a different engine

requests against requests minus denials are the same where refusals are not recorded and differ where they are recorded as denials (R0: the policy denies, the other permits).

```
the shortest schedule (the first policy's count):
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   3. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   4. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   5. [engine] the engine refuses the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   6. [engine] the engine refuses the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
```

## Diff: a difference that shows only at R2

requests minus refunds against requests minus refunds and confirms: same at R0 and R1, different at R2, where a confirm follows an ambiguous failure.

```
the shortest schedule:
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   3. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   4. [tool] the tool reports an error on the call for 60, yet the money moves | counted 60 | held 0 | spent 60 | doubt 0
   5. [harness] the harness reconciles the call for 60: the money moved, so it stands | counted 60 | held 0 | spent 60 | doubt 0
   6. [engine] the engine refuses the call for 60 | counted 60 | held 0 | spent 60 | doubt 0
```

## Conformance: the reference binary, and a control that must disagree

375 tests, 958 decisions, 0 disagreements between the machine and dogwood 1.1.1; the wrong-profile control (DenyRecord none on PReqBasis) disagrees 5 times. Its first disagreement: the machine permits the last call, the binary denies it, because the binary keeps each refusal as a request.

```
the control's machine (refusals not recorded):
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   3. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   4. [engine] the engine refuses the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   5. [harness] the harness issues a call for 30 | counted 60 | held 60 | spent 0 | doubt 0
   6. [engine] the engine admits the call for 30 | counted 90 | held 90 | spent 0 | doubt 0
```

## Shapes: 162 shapes on the current kernel

clean shapes on some profile: {'request': 1, 'response': 0, 'error': 0, 'refund': -1} + 0 x current; on request / atomic (refusals kept as requests) 0 shapes are clean and the shapes form 80 machines. The request sum is not Tight there (R0): a refusal is counted as a request, so a later call that fits is refused.

```
story (R0 Tight, the ledger, 6 steps, cap 100):
   1. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   2. [harness] the harness issues a call for 60 | counted 0 | held 0 | spent 0 | doubt 0
   3. [harness] the harness issues a call for 30 | counted 0 | held 0 | spent 0 | doubt 0
   4. [engine] the engine admits the call for 60 | counted 60 | held 60 | spent 0 | doubt 0
   5. [engine] the engine refuses the call for 60 | counted 120 | held 60 | spent 0 | doubt 0
   6. [engine] the engine refuses the call for 30 | counted 150 | held 60 | spent 0 | doubt 0   <- the invariant broke
```
