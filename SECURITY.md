# Security and disclosure

## Reporting a problem with KAMANU

If a proof, a record, the record verifier or the tools are wrong in a way that could make a limit look
stronger than it is, write to jerenyame@gmail.com. Please include the command, its output and the commit.
You will get a reply within three working days. Please do not open a public issue for a flaw that would
let a forged or stale record verify.

## Results about other people's systems

KAMANU's house rules apply to every result about a system it does not own:

- The owner of a system sees a result about it first, and has 30 days before anything is public. A
  result is published sooner only with the owner's written consent.
- Tests run only in our own accounts and sandboxes, or with written permission.
- A fee never changes a verdict or its timing, and passes are published as readily as failures.

If you used KAMANU and found that someone else's limit can be exceeded, tell them before you tell
anyone else. We are glad to help you word the report.

## The signing key

Records in [registry/](registry/) are signed with Ed25519. The public key is
[registry/registry.pub](registry/registry.pub) and is printed, with its fingerprint (the SHA-256 of its
32 bytes), on the registry's index. A record signed with any other key is not one of ours.
