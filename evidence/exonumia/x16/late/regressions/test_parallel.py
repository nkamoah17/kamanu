"""Regression: parallel asks (parallel), from sprint run seed 1 against demo.sprint.handlers:Late.

The shortest trace of the finding, replayed against the handler: each request asked again, the processor's other
events told in the journal's order, and the answers judged by the reference ledger (exonumia.ledger). The test
fails while the finding stands. KAMANU_SPRINT_HANDLER=module:Name (or a URL) replays it against another handler.
The processor was simulated; nothing here is a statement about a processor's system.
"""
import json
import os

from exonumia.sprint import regress

HANDLER = 'demo.sprint.handlers:Late'
SECRET = 'whsec_demo_sprint_not_a_real_signing_secret'
LIMITS = json.loads('[{"amount": 2000, "id": "cardholder-daily", "interval": "daily", "scope": "cardholder"}, {"amount": 350, "id": "card-per-authorization", "interval": "per_authorization", "scope": "card"}, {"amount": 20000, "id": "cards-monthly", "interval": "monthly", "scope": "cardholder"}]')
PROFILE = json.loads('{"constants": {"expiry_days": {"status": "assumed", "value": 7}, "force_post": {"status": "assumed", "value": 0}, "over_capture": {"status": "assumed", "value": 20}, "refund_restores": {"status": "assumed", "value": false}}, "currency": "usd", "ledger": "shadow-v1"}')
TRACE = [
 "{\"event\":{\"amount\":273,\"auth\":\"parallel/0/a1\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a1:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":281,\"auth\":\"parallel/0/a2\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a2:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"e250ec5c782b531e0f6bc59fd9a8741bae7d04a8a58d0914f51ad63cad3c5deb\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":253,\"auth\":\"parallel/0/a3\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a3:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"12d11d2cb02540e1d04ac8cb160747c5047720dd862812b8b1509fd344b74ab7\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":279,\"auth\":\"parallel/0/a4\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a4:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"9586fa744cf45d7fe20c9add37a2a555d25716788b9ce3cd882be65ea1eddec0\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":253,\"auth\":\"parallel/0/a5\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a5:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"9e9c4cf59ad88e36c1618390fbbf360565885990f10228099ec5ee42d42bb08e\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":285,\"auth\":\"parallel/0/a6\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a6:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"af82c494f5eb568dfd0a96832c31d2e7cd4450220227511db3b51d5375694e89\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":266,\"auth\":\"parallel/0/a7\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a7:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"024a2a19f6407e202bb940cdfa76130e3b25365a6e1694d1a0d4780144fa4bf9\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":255,\"auth\":\"parallel/0/a8\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a8:request\",\"kind\":\"request\",\"t\":1790643606},\"prev\":\"58e10f39a7b12b3623a8a75cc86822fedb40f93326ef0fb0b247dbfa8f8cd45d\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606001,\"approved\":true,\"auth\":\"parallel/0/a8\",\"id\":\"tee:parallel/0/a8:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"18d5f940e89860a814535229edf440eeacbac057f40699c5d957ad390e7a8a87\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606002,\"approved\":true,\"auth\":\"parallel/0/a1\",\"id\":\"tee:parallel/0/a1:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"ae342bcb29e8913698e1d1ff491a2de04003129c50b5836c2637adb71ba86948\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606003,\"approved\":true,\"auth\":\"parallel/0/a2\",\"id\":\"tee:parallel/0/a2:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"cb9c3da611a81e0c2a6f51d8399aee736536f13267550be1e6e669d4d2b06588\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606004,\"approved\":true,\"auth\":\"parallel/0/a3\",\"id\":\"tee:parallel/0/a3:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"2a00944e7537a8c09f429c5dabcd059091b593d13a7aa8ba29907f1e1e8a36d3\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606005,\"approved\":true,\"auth\":\"parallel/0/a4\",\"id\":\"tee:parallel/0/a4:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"a5fecba633e85788385a0d40eb364a5b74344c6d5a5bf68ce00bf137067b74c0\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606006,\"approved\":true,\"auth\":\"parallel/0/a5\",\"id\":\"tee:parallel/0/a5:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"8ba9a1b53f872bb78513dec7451b464367dd56fb3d98b348545e7645fdda88b9\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606007,\"approved\":true,\"auth\":\"parallel/0/a6\",\"id\":\"tee:parallel/0/a6:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"a159371e118299a9e8353de15cc063f4f76c923d2accab71e8730b6add6214ad\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1790643606008,\"approved\":true,\"auth\":\"parallel/0/a7\",\"id\":\"tee:parallel/0/a7:request\",\"kind\":\"answer\",\"t\":1790643606},\"prev\":\"3dc84b6ab0290bc3a5d4667c4a4f41c82592e9d20418bd9d150b07e57cad1e3b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":255,\"approved\":true,\"auth\":\"parallel/0/a8\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a8:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"62a94b8458b9839e26e8ec79f7b0fa3f45febd89f3706dd17a72a4376085f199\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":273,\"approved\":true,\"auth\":\"parallel/0/a1\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"d5ae001cf6c8b49558c7f2dd4082b770d2672ce481148cd016defdf24a7e38a8\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":281,\"approved\":true,\"auth\":\"parallel/0/a2\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"1002936453f6bb02667ed7d3f274c438f20be6c21d81d156c70e52229e649b1b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":253,\"approved\":true,\"auth\":\"parallel/0/a3\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"23f6ee64476fa1f46b26aeb9c4ab1ba91e1a3277459a29fdc526c265daf25bb4\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":279,\"approved\":true,\"auth\":\"parallel/0/a4\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a4:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"70a407926cdfce2990ba78953727c518313a70f27ad7dabcfc7ff8420440627b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":253,\"approved\":true,\"auth\":\"parallel/0/a5\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a5:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"1b3b92049634aa7fa2efdd9e884612caa9240c5302af489230950cba0a42d64e\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":285,\"approved\":true,\"auth\":\"parallel/0/a6\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a6:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"670e7e1e8f6c14e264e6cba5caa8b701956b21f6d824b2147b007d325dfdb0b4\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":266,\"approved\":true,\"auth\":\"parallel/0/a7\",\"card\":\"ic_parallel_0_1\",\"cardholder\":\"ich_parallel_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"parallel/0/a7:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1790643606},\"prev\":\"aff153e2162ad8c1c9cce6ebad2102835c34c5b66ac32dfc6621a5dd7c0cd6fe\",\"received\":\"accepted\"}"
]


def test_parallel():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
