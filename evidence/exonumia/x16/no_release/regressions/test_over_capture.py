"""Regression: capture above the hold, then reversal (over_capture), from sprint run seed 1 against demo.sprint.handlers:NoRelease.

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
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/x1\",\"kind\":\"capture\",\"t\":1771549181},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/x2\",\"kind\":\"capture\",\"t\":1771549180},\"prev\":\"d3961ec12b1b7fa80e63014c8571a55ba4e47076c0079d3f5d7ef5b5a6ff7a59\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/x3\",\"kind\":\"capture\",\"t\":1771549179},\"prev\":\"5e3231658fdf7463e25d8471d208b40cbd527d659d08f50b656a25a69ee3f9c6\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/x4\",\"kind\":\"capture\",\"t\":1771549178},\"prev\":\"872fbce5bc74c44e6554550cef7fcf0a6935598a1c4099e5eea1bf0b8b83c304\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/x5\",\"kind\":\"capture\",\"t\":1771549177},\"prev\":\"5402c11e9cd62cc7e01e1c6a592c9b1d7d6662ab374848efd30aed4bac94af4f\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":110,\"auth\":\"over_capture/0/a1\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a1:request\",\"kind\":\"request\",\"t\":1771549202},\"prev\":\"33212973961fc152ad9d62eff30a0ec5ee6a59802b44d2aafae05d4f5800b9fd\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771549202001,\"approved\":true,\"auth\":\"over_capture/0/a1\",\"id\":\"tee:over_capture/0/a1:request\",\"kind\":\"answer\",\"t\":1771549202},\"prev\":\"d8506425a274a546f30ead0e848d5c457fa6eebcd948e0cca29267a68ed3f0dc\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":110,\"approved\":true,\"auth\":\"over_capture/0/a1\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771549202},\"prev\":\"bbf89f3e17ea7c046661bedfbe3f2995d23302f651280ccd7defb91496aac437\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":116,\"auth\":\"over_capture/0/a1\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/0/a1:capture@1771549207\",\"kind\":\"capture\",\"t\":1771549207},\"prev\":\"e2574cbe4fc3dac9e91a0346f17d7fa00186f8fa2a4207e63acc953d40f92f85\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":71,\"auth\":\"over_capture/0/a2\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a2:request\",\"kind\":\"request\",\"t\":1771549208},\"prev\":\"e87810b626615aadb7e7666b2422589d5dbc9b4e6bfdc21321580e262c7fa8bd\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771549208001,\"approved\":true,\"auth\":\"over_capture/0/a2\",\"id\":\"tee:over_capture/0/a2:request\",\"kind\":\"answer\",\"t\":1771549208},\"prev\":\"ff0bf29c0d2f39f0e70e154c8842bf618ab68c3c053b4a8e336190b336e2d62d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":71,\"approved\":true,\"auth\":\"over_capture/0/a2\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771549208},\"prev\":\"51d5d721020d4b845498b2d12e6f0741c71af22e780eff2b0588aa7927ac60c7\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":null,\"auth\":\"over_capture/0/a2\",\"currency\":\"usd\",\"id\":\"over_capture/0/a2:reverse@1771549210\",\"kind\":\"reverse\",\"t\":1771549210},\"prev\":\"e61272ef58c85876dc5eb6da40055923a2a48f140228e526b0843acec857a99a\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":211,\"auth\":\"over_capture/0/a3\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a3:request\",\"kind\":\"request\",\"t\":1771549222},\"prev\":\"afc795cad2c2dafd954f24d42177cce73b2c5c1c9a8e4c9bacc2f483822e4eb9\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771549222001,\"approved\":false,\"auth\":\"over_capture/0/a3\",\"id\":\"tee:over_capture/0/a3:request\",\"kind\":\"answer\",\"t\":1771549222},\"prev\":\"5229e1e24342a5e936f43aef1114c7e99a3ee551a4ca90e5b699f7acd1ca04de\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":211,\"approved\":false,\"auth\":\"over_capture/0/a3\",\"card\":\"ic_over_capture_0_1\",\"cardholder\":\"ich_over_capture_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/0/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_declined\",\"t\":1771549222},\"prev\":\"82482cf0d7d9b608d1228543c567c9156911e206544dfd0390f0db4afce5a5bf\",\"received\":\"accepted\"}"
]


def test_over_capture():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
