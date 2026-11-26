"""Regression: authorization then partial capture (partial_capture), from sprint run seed 1 against demo.sprint.handlers:NoRelease.

The shortest trace of the finding, replayed against the handler: each request asked again, the processor's other
events told in the journal's order, and the answers judged by the reference ledger (exonumia.ledger). The test
fails while the finding stands. KAMANU_SPRINT_HANDLER=module:Name (or a URL) replays it against another handler.
The processor was simulated; nothing here is a statement about a processor's system.
"""
import json
import os

from exonumia.sprint import regress

HANDLER = 'demo.sprint.handlers:NoRelease'
SECRET = 'whsec_demo_sprint_not_a_real_signing_secret'
LIMITS = json.loads('[{"amount": 2000, "id": "cardholder-daily", "interval": "daily", "scope": "cardholder"}, {"amount": 350, "id": "card-per-authorization", "interval": "per_authorization", "scope": "card"}, {"amount": 20000, "id": "cards-monthly", "interval": "monthly", "scope": "cardholder"}]')
PROFILE = json.loads('{"constants": {"expiry_days": {"status": "assumed", "value": 7}, "force_post": {"status": "assumed", "value": 0}, "over_capture": {"status": "assumed", "value": 20}, "refund_restores": {"status": "assumed", "value": false}}, "currency": "usd", "ledger": "shadow-v1"}')
TRACE = [
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/0/x1\",\"kind\":\"capture\",\"t\":1782867579},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/0/x2\",\"kind\":\"capture\",\"t\":1782867578},\"prev\":\"4a9f8e5060674a347515fd558a95c68934b8688573d05140bba823fd20189f3d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/0/x3\",\"kind\":\"capture\",\"t\":1782867577},\"prev\":\"eb38a4216691878a2798a103cc400ac8a2d3c23689e23e15fc67f2b5b476c1ae\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/0/x4\",\"kind\":\"capture\",\"t\":1782867576},\"prev\":\"5d2c0c8cb552ee7be4a8e44cae12915f122de0b7bf1fb173eccb47181fce1f1f\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/0/x5\",\"kind\":\"capture\",\"t\":1782867575},\"prev\":\"e3832e0345b7b3144105d223cad5e64c0cf61b7c97a0c094c59321793afd587c\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":263,\"auth\":\"partial_capture/0/a1\",\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/0/a1:request\",\"kind\":\"request\",\"t\":1782867600},\"prev\":\"3a5fbb5785d3af50949bf65429aa32d76a959c95e8a24b768e09bd7d1c1bf05a\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1782867600001,\"approved\":true,\"auth\":\"partial_capture/0/a1\",\"id\":\"tee:partial_capture/0/a1:request\",\"kind\":\"answer\",\"t\":1782867600},\"prev\":\"1fb8f6b57b6853e9d980735f14b82a4941dc91356f8ce267fdfb13bda66bef7c\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":263,\"approved\":true,\"auth\":\"partial_capture/0/a1\",\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1782867600},\"prev\":\"0de3e61809c4dc519cf6955903e7032fed244b7698bd42c17399532d5e9a12d9\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":130,\"auth\":\"partial_capture/0/a1\",\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":false,\"id\":\"partial_capture/0/a1:capture@1782867605\",\"kind\":\"capture\",\"t\":1782867605},\"prev\":\"24729dc2d2de0a6ec6ac65d0868504ff6f39bafcdfbcd4b384d1dad94eca5e41\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":null,\"auth\":\"partial_capture/0/a1\",\"currency\":\"usd\",\"id\":\"partial_capture/0/a1:reverse@1782867606\",\"kind\":\"reverse\",\"t\":1782867606},\"prev\":\"adc8ce52f241c36ec4f94dbc966f0d9ad345f79a1509221fcff511f1ad73358e\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":206,\"auth\":\"partial_capture/0/a2\",\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/0/a2:request\",\"kind\":\"request\",\"t\":1782867620},\"prev\":\"ec3e636f31b7db5cc4914deda294280b81a2a78ba75f175c1c9bbe9c99236d26\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1782867620001,\"approved\":false,\"auth\":\"partial_capture/0/a2\",\"id\":\"tee:partial_capture/0/a2:request\",\"kind\":\"answer\",\"t\":1782867620},\"prev\":\"b2cd024f67ce73d1f65f6bef969b74b262fda5d5941834a03ebb270859e9720e\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":206,\"approved\":false,\"auth\":\"partial_capture/0/a2\",\"card\":\"ic_partial_capture_0_1\",\"cardholder\":\"ich_partial_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_declined\",\"t\":1782867620},\"prev\":\"26bb95131f8db3f5b22ac40b6bf33e889d623684512f1d441b302ed5bf8e2d58\",\"received\":\"accepted\"}"
]


def test_partial_capture():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
