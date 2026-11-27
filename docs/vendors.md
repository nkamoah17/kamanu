# Working with KAMANU: one page for vendors

This is what we do, and do not do, when we check a limit on your system.

## What we touch

- **Only your sandbox or test mode.** We never ask for, accept or use production credentials, and we never
  move live funds. Payment tests run on test networks or in test mode, with test money.
- **One authorization path that we agree with you in writing,** before the first call. Anything outside it
  is not tested.
- **No production systems, no customer data.** If a test would need either, we stop and ask.
- **A stated volume.** The battery's call count and pace are agreed beforehand: each test runs 99 trials.
  We stay inside your sandbox's published rate limits.

## Your test keys

- You create keys for the test and scope them to the agreed path, with the least access the test needs.
- They are kept outside any code repository, on one machine, and given to the test run as environment
  variables. Before every commit, the tree is checked against their values, so a key never reaches git.
- They are not shared with anyone else, and they are not written into any report or record.
- When the check ends, revoke them. We delete our copy the same day and tell you when it is gone.

## What you get, and what is published

- The result comes to you first, privately. Nothing about your system is published before you have seen
  it.
- A result is published only with your written consent, pass or fail, or 30 days after you were told if
  you do not answer. Passes are published as readily as failures.
- A fee never changes a verdict or its timing.
- Every number carries its level (proved, measured, assumed) and the hypotheses it rests on. We never
  call a system "certified" or "safe".

## If we find something

A limit that can be exceeded is a security matter for you. We tell you first, give you the shortest
sequence of events that shows it, and agree a date with you before anything is said in public. See
[SECURITY.md](../SECURITY.md) for how to reach us.

## Who you are dealing with

KAMANU, run by Kenneth Amoah Nyame. Write to jerenyame@gmail.com.
