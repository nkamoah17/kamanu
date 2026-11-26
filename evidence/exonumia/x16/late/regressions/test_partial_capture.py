"""Regression: authorization then partial capture (partial_capture), from sprint run seed 1 against demo.sprint.handlers:Late.

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
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/2/x1\",\"kind\":\"capture\",\"t\":1782868784},\"prev\":\"0982eb564100c2f9e1f27d1b69b5ac74a60fb1bfbf2c5a449dc22954c6fe252d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/2/x2\",\"kind\":\"capture\",\"t\":1782868783},\"prev\":\"453e359c085fa188e51db947b54e0aedfd359b6f5aa756f38bc49d0a3545afd7\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/2/x3\",\"kind\":\"capture\",\"t\":1782868782},\"prev\":\"c19999f045d65f958fb00295ac770faf542f039ce84dca252f634ed0e088e341\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/2/x4\",\"kind\":\"capture\",\"t\":1782868781},\"prev\":\"92405d17c629bedabf4a9e288b5b370e7bcbe1097fdad4a41d952f20d75e9615\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"partial_capture/2/x5\",\"kind\":\"capture\",\"t\":1782868780},\"prev\":\"41bcb729eea264032843df0c467b63a2ae5749835117271db36a2a834788a9f0\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":275,\"auth\":\"partial_capture/2/a1\",\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/2/a1:request\",\"kind\":\"request\",\"t\":1782868805},\"prev\":\"25502b220a39b65ce7cfdd9c33bee4bcd77bfcb239203a78a7a1b6f62f2ab7c9\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1782868805001,\"approved\":true,\"auth\":\"partial_capture/2/a1\",\"id\":\"tee:partial_capture/2/a1:request\",\"kind\":\"answer\",\"t\":1782868805},\"prev\":\"5bbb00d558a921682f677d4ceba90aa04be8347a8f82e16c263a4411d2dd29d6\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":275,\"approved\":true,\"auth\":\"partial_capture/2/a1\",\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/2/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1782868805},\"prev\":\"5e9318809748cec541332a1b19b1485d61eecce899d3d52ba1acbfa4eb385ad5\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":100,\"auth\":\"partial_capture/2/a1\",\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":false,\"id\":\"partial_capture/2/a1:capture@1782868810\",\"kind\":\"capture\",\"t\":1782868810},\"prev\":\"4178706c2fe89dbae4c7b0ac714afc1dc5ddbb53558ace38eca0af7ea1da40f0\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":null,\"auth\":\"partial_capture/2/a1\",\"currency\":\"usd\",\"id\":\"partial_capture/2/a1:reverse@1782868811\",\"kind\":\"reverse\",\"t\":1782868811},\"prev\":\"0610862f5c3f1d3260db7a47c446022a483480ad4c21295782e7133bcd25c4b4\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":264,\"auth\":\"partial_capture/2/a2\",\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/2/a2:request\",\"kind\":\"request\",\"t\":1782868825},\"prev\":\"f0f30bc763aab3157c6a79cacda8e983f77c43c873779614e0ad2eb0a5f5353d\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1782868825001,\"approved\":true,\"auth\":\"partial_capture/2/a2\",\"id\":\"tee:partial_capture/2/a2:request\",\"kind\":\"answer\",\"t\":1782868825},\"prev\":\"bf79f9dfe36a3bbdb70ab26c797821688c5897b6779ddfec6922ada3cb019989\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":264,\"approved\":true,\"auth\":\"partial_capture/2/a2\",\"card\":\"ic_partial_capture_2_1\",\"cardholder\":\"ich_partial_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"partial_capture/2/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1782868825},\"prev\":\"d1c73e1819c6fb00ff9299935b14887e693e0f637bfd876b1af7806e04576559\",\"received\":\"accepted\"}"
]


def test_partial_capture():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
