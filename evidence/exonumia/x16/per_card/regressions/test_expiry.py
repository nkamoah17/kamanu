"""Regression: an uncaptured hold that expires, and two limits on one purchase (expiry), from sprint run seed 1 against demo.sprint.handlers:PerCard.

The shortest trace of the finding, replayed against the handler: each request asked again, the processor's other
events told in the journal's order, and the answers judged by the reference ledger (exonumia.ledger). The test
fails while the finding stands. KAMANU_SPRINT_HANDLER=module:Name (or a URL) replays it against another handler.
The processor was simulated; nothing here is a statement about a processor's system.
"""
import json
import os

from exonumia.sprint import regress

HANDLER = 'demo.sprint.handlers:PerCard'
SECRET = 'whsec_demo_sprint_not_a_real_signing_secret'
LIMITS = json.loads('[{"amount": 2000, "id": "cardholder-daily", "interval": "daily", "scope": "cardholder"}, {"amount": 350, "id": "card-per-authorization", "interval": "per_authorization", "scope": "card"}, {"amount": 20000, "id": "cards-monthly", "interval": "monthly", "scope": "cardholder"}]')
PROFILE = json.loads('{"constants": {"expiry_days": {"status": "assumed", "value": 7}, "force_post": {"status": "assumed", "value": 0}, "over_capture": {"status": "assumed", "value": 20}, "refund_restores": {"status": "assumed", "value": false}}, "currency": "usd", "ledger": "shadow-v1"}')
TRACE = [
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/x1\",\"kind\":\"capture\",\"t\":1786238382},\"prev\":\"91cf18b483be3995a81c68a440f5ff49b9e9b95f9c67993f9cfb3d2c56bac1aa\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/x2\",\"kind\":\"capture\",\"t\":1786238381},\"prev\":\"f7891a41072e1ec6d12cf70c92fc57f9f7644088f0cf946dffbc5b8616c24511\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/x3\",\"kind\":\"capture\",\"t\":1786238380},\"prev\":\"3a7630de76512e6af45bedea992e2223e2e8e47bc9425f143394f76497bbadf3\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/x4\",\"kind\":\"capture\",\"t\":1786238379},\"prev\":\"cbf6a03a8663e16f9198583e4d0e1d2da21613d9be430d12541999f33b065d54\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/x5\",\"kind\":\"capture\",\"t\":1786238378},\"prev\":\"734c275623d76239d8af634ac8f0e3065aa4355225bb2205971c19cb8185f609\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":213,\"auth\":\"expiry/2/a1\",\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a1:request\",\"kind\":\"request\",\"t\":1786238403},\"prev\":\"9eb21e628f4e9435abf360402f925802bc810b2a729ae43815955117b787bfa5\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786238403001,\"approved\":true,\"auth\":\"expiry/2/a1\",\"id\":\"tee:expiry/2/a1:request\",\"kind\":\"answer\",\"t\":1786238403},\"prev\":\"c5587f5f4156f622896cda611e4f046a7ee7e6cb180dc8729599b6156449d15c\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":213,\"approved\":true,\"auth\":\"expiry/2/a1\",\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1786238403},\"prev\":\"73a7b5db483ea925dc6755237ad4181f16a515f6ae447d82223afae2c5bee352\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":25,\"auth\":\"expiry/2/a2\",\"card\":\"ic_expiry_2_2\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a2:request\",\"kind\":\"request\",\"t\":1786238408},\"prev\":\"23c5383e17356ae6e0e6e15109cc0a443b01482160c76ed9765cf15c72fba5ea\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786238408001,\"approved\":true,\"auth\":\"expiry/2/a2\",\"id\":\"tee:expiry/2/a2:request\",\"kind\":\"answer\",\"t\":1786238408},\"prev\":\"4e864fd29fc38f68df38575ba05b157eb2807ca7de281fd1ee8bf60569ce3fab\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":25,\"approved\":true,\"auth\":\"expiry/2/a2\",\"card\":\"ic_expiry_2_2\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1786238408},\"prev\":\"b5b23a308a235c5d38fb10a19ac1c4ba4842c6ff0d45ff7e09d17fded28cea61\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":25,\"auth\":\"expiry/2/a2\",\"card\":\"ic_expiry_2_2\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/2/a2:capture@1786238409\",\"kind\":\"capture\",\"t\":1786238409},\"prev\":\"94484ccef4b5d261e06b162d074a2ee6e649b935f4dac03bf099f5c8c8d6e134\",\"received\":\"accepted\"}",
 "{\"event\":{\"auth\":\"expiry/2/a1\",\"currency\":\"usd\",\"id\":\"expiry/2/a1:expire@1786238703\",\"kind\":\"expire\",\"t\":1786238703},\"prev\":\"d1d05631427136b32eb15c9d4aa117dc6d02a8c9162ee5b378a45cac078dfcc3\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":342,\"auth\":\"expiry/2/a3\",\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a3:request\",\"kind\":\"request\",\"t\":1786238713},\"prev\":\"c248e3370815685f51f49e3da5ac87d748398a80378d30f104652afb680331b6\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786238713001,\"approved\":true,\"auth\":\"expiry/2/a3\",\"id\":\"tee:expiry/2/a3:request\",\"kind\":\"answer\",\"t\":1786238713},\"prev\":\"e5af32eb8b0ddb3b2fa35c7f3bd861667ac4b0b538e771dbf8951c70024a6beb\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":342,\"approved\":true,\"auth\":\"expiry/2/a3\",\"card\":\"ic_expiry_2_1\",\"cardholder\":\"ich_expiry_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/2/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1786238713},\"prev\":\"37e4a002871a31b3cc68f3bf3ff975378e1e5a85624114c6297019690ad1ac56\",\"received\":\"accepted\"}"
]


def test_expiry():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
