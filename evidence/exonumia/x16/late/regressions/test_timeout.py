"""Regression: time-out with an ambiguous outcome, then retry (timeout), from sprint run seed 1 against demo.sprint.handlers:Late.

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
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"timeout/0/x1\",\"kind\":\"capture\",\"t\":1775782788},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"timeout/0/x2\",\"kind\":\"capture\",\"t\":1775782787},\"prev\":\"a3961dad16a40d3b0bf41955ac2517b8d27a1ba23bb3ce9309da77bfc37c333b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"timeout/0/x3\",\"kind\":\"capture\",\"t\":1775782786},\"prev\":\"a8a3517cecfae0049b2dfdfeaff4e9ca9c9bfa4b0a64ba9ca3ef02505ab1062c\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"timeout/0/x4\",\"kind\":\"capture\",\"t\":1775782785},\"prev\":\"0d73fb2818a34140117746928211d0b53d42e43a7ad35d17deb4f78b5c79ddc3\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"timeout/0/x5\",\"kind\":\"capture\",\"t\":1775782784},\"prev\":\"5f1b0581e7547e85ebe022e9265ca6fc23e784517e92c70dd23eff0c16a860b4\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":343,\"auth\":\"timeout/0/a1\",\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"timeout/0/a1:request\",\"kind\":\"request\",\"t\":1775782809},\"prev\":\"667f13202f92b23b3873b40902b409ebbe36c6485c3ee854739be41984f3d9ef\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1775782809001,\"approved\":true,\"auth\":\"timeout/0/a1\",\"id\":\"tee:timeout/0/a1:request\",\"kind\":\"answer\",\"t\":1775782809},\"prev\":\"d9289c695e117af4a806e8f71c71b1daf6096e1666ce52f935ae6d9c96ac072f\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":343,\"approved\":true,\"auth\":\"timeout/0/a1\",\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"timeout/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1775782809},\"prev\":\"11b9a5c6b573377e218ca01bb640607405b26361f000d45ab593abcd4a8be757\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":343,\"auth\":\"timeout/0/a2\",\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"timeout/0/a2:request\",\"kind\":\"request\",\"t\":1775782812},\"prev\":\"3968b5300dc034c1cb83d19b5fb04bf1461622628b4b829568107150ce11cf96\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1775782812001,\"approved\":true,\"auth\":\"timeout/0/a2\",\"id\":\"tee:timeout/0/a2:request\",\"kind\":\"answer\",\"t\":1775782812},\"prev\":\"c882f7698e4724667fdae570c6f9ab7eddfb868633de5434ff2a64ac3a517927\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":343,\"approved\":true,\"auth\":\"timeout/0/a2\",\"card\":\"ic_timeout_0_1\",\"cardholder\":\"ich_timeout_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"timeout/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1775782812},\"prev\":\"60c8638160b58b890efa0c15be2c07dc27d2ae34cbbf84796b2c586cc2810025\",\"received\":\"accepted\"}"
]


def test_timeout():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
