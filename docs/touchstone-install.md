# Install one Touchstone hook in a sandbox, from nothing

This installs the x402 hook, `exonumia/touchstone/x402.py`, in front of a client in a sandbox (a testnet
and a simulated 402 answer). Nothing here moves money: Touchstone only answers.

1. Get the code and its one dependency (kamanu itself):

   ```sh
   git clone <this repository> kamanu && cd kamanu
   python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -e .
   ```

2. The hook is one file, `exonumia/touchstone/x402.py`, with the package beside it
   (`exonumia/touchstone/`). `exonumia/` is not in the kamanu wheel, so run from the root of the clone
   (or put the clone on `PYTHONPATH`); to use it in another project, copy `exonumia/` next to that
   project's code.

3. Put the hook between the 402 answer and the signature. In a sandbox (a testnet, here Base Sepolia,
   `eip155:84532`), this script runs as is:

   ```python
   import json, time
   from pathlib import Path
   from exonumia.touchstone import Touchstone
   from exonumia.touchstone.x402 import Hook

   policy = '''@id("base") permit (principal, action == Bank::Action::"Pay", resource);
   @id("cap") forbid (principal, action == Bank::Action::"Pay", resource)
   when temporal { sum_within(a, 1m, Bank::Action::"Pay"::request{ input.amount: a }) > 1000 };
   '''
   profile = json.loads(Path("demo/assay/proved-cell.json").read_text())
   hook = Hook(Touchstone(policy, profile, meter="sandbox-touchstone.jsonl"), key="sandbox-agent")

   def answer_402(price):          # what a sandbox merchant answers: the price in minor units
       return {"x402Version": 1, "error": "X-PAYMENT header is required",
               "accepts": [{"scheme": "exact", "network": "eip155:84532",
                            "maxAmountRequired": str(price), "resource": "https://sandbox.example/item",
                            "payTo": "0x0000000000000000000000000000000000000001", "asset": "0x0"}]}

   now = int(time.time())
   for price in (600, 300, 400):
       a = hook(answer_402(price), now)
       print(price, "sign and pay" if a["fits"] else f"refused: {a['max_allowed_now']} fits now, "
                                                     f"all of it at {a['earliest_time']}")
   ```

   The third ask is refused: 600 + 300 are in the minute's window, so 100 fits now and 400 fits when the
   first payment leaves the window. Your client signs only when `a["fits"]`.

4. See what was checked:

   ```sh
   python -m exonumia.touchstone usage --log sandbox-touchstone.jsonl --from 2026-01-01 --to 2026-12-31
   ```

The AgentCore hook (`exonumia/touchstone/agentcore.py`, before ProcessPayment, keyed by the payment
session) and the card hook (`exonumia/touchstone/card.py`, before a Stripe Issuing authorization is created;
use Stripe's test mode for a sandbox) install the same way. Stripe Issuing is the card API because it is
the one this repository's card ledger already reads (X2b, X4) and its test mode gives a sandbox card.
