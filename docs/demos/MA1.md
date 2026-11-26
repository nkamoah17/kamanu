# MA1: Second-order recruitment

An attacker who may only file tickets writes instructions into one. Later the owner
starts an agent session. A benign helper reads the ticket, cannot tell data from
instructions, and delegates the request to a privileged worker. No agent is compromised,
and each does its job. The worker acts with the owner's privileges, because agents run
as whoever started the session, not as whoever wrote the text.

AppOmni reported this pattern with prompt injection protection enabled: Aaron Costello,
["When AI Turns on Its Team: Exploiting Agent-to-Agent Discovery via Prompt
Injection"](https://appomni.com/ao-labs/ai-agent-to-agent-discovery-prompt-injection/),
AO Labs, 19 November 2025. `spec/demos/Recruit.tla` is a generic abstraction of it, not
a model of any product.

## Buggy trace

TLC's counterexample to `NoPrivilegeWidening`:

| Step | Effect |
| --- | --- |
| `PlantText` | attacker posts text asking for `read` |
| `ReadContent` | helper reads it in the owner's session |
| `Delegate` | worker gets `grant = {"read"}`, `origin = "attacker"` |
| `Act` | worker uses `read`, which `Priv["attacker"]` lacks |

## The fix

One operator, `Delegate`, changes whose privileges bound the grant:

```tla
grant |-> Post[i].ask \cap Priv[IF Fixed THEN Post[i].author ELSE Session]
```

Provenance travels with the request, so delegation can only narrow. The owner's task
still completes. The planted request is narrowed: any part the author holds runs, and
one narrowed to nothing is refused and escalated. So planted text can still interrupt
a task, which is the fix's cost. It can no longer borrow authority.

AppOmni's own mitigations are operational, such as supervised execution and separating
agent teams. This fix is this model's own, not one of those.
