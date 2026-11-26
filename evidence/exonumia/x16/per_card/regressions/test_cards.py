"""Regression: several cards under one cardholder (cards), from sprint run seed 1 against demo.sprint.handlers:PerCard.

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
 "{\"event\":{\"amount\":350,\"auth\":\"cards/0/a1\",\"card\":\"ic_cards_0_1\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a1:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":338,\"auth\":\"cards/0/a2\",\"card\":\"ic_cards_0_2\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a2:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"094f23a39d10b67a614166f58d93aaf5408dabd4261fb57f7ecab537a76bd89d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":340,\"auth\":\"cards/0/a3\",\"card\":\"ic_cards_0_3\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a3:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"2144a59640023ac236def43cc0fc5d290bfac508c0e3a8f14950de29f22889b5\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":336,\"auth\":\"cards/0/a4\",\"card\":\"ic_cards_0_4\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a4:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"ed06b4360442728897a76a68a4ef1dadeb6c29e2281bfb4916a5689a61d060dd\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":334,\"auth\":\"cards/0/a5\",\"card\":\"ic_cards_0_5\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a5:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"54ca6784e0aa532576283fc21e81603bb23e309eb879c9b9d7547f9020bc24fa\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":347,\"auth\":\"cards/0/a6\",\"card\":\"ic_cards_0_6\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a6:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"7c5c72b6800490d11cc8961eb4028cf51adcc4612f00782cba2536976c251c61\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805001,\"approved\":true,\"auth\":\"cards/0/a6\",\"id\":\"tee:cards/0/a6:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"ebcab709637d4cb53b4be62c28a32acaada7693c59f60fb4e33bc962a77b7cd5\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805002,\"approved\":true,\"auth\":\"cards/0/a1\",\"id\":\"tee:cards/0/a1:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"0f550df2363e9f152ce2aeb2551255c9fc6cf5ae4005345c0d6047059379f285\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805003,\"approved\":true,\"auth\":\"cards/0/a2\",\"id\":\"tee:cards/0/a2:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"08a5192fb531b1976f5ca51a4d658a4382990c3958a707c2fe019ca986121842\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805004,\"approved\":true,\"auth\":\"cards/0/a4\",\"id\":\"tee:cards/0/a4:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"58483477d950bc6ea7ca7e29b6cf4f8418f3b305f496fd3ace7cbbe4b799981c\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805005,\"approved\":true,\"auth\":\"cards/0/a3\",\"id\":\"tee:cards/0/a3:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"ca44022a89e80a1247dde9ef66c021c380073ed8f59b1e99603ac4b66315d0b4\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805006,\"approved\":true,\"auth\":\"cards/0/a5\",\"id\":\"tee:cards/0/a5:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"8b840559a50e71a04ffbc1bfdc8a5b48a2cf7fb7c574c0ef58a8231fa9376989\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":347,\"approved\":true,\"auth\":\"cards/0/a6\",\"card\":\"ic_cards_0_6\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a6:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"800daeea9ddd80998f8979ce1214011444f0838a6aa98d350534703802e49ebf\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"approved\":true,\"auth\":\"cards/0/a1\",\"card\":\"ic_cards_0_1\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"d1d6270de75b4409f49532753e258b6e28eabe1559d8fa9f68946568a0ab9435\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":338,\"approved\":true,\"auth\":\"cards/0/a2\",\"card\":\"ic_cards_0_2\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"7d2b3b38d60a134d315de3383b283e8c9f168617aa89247300be5bf5a91a363b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":336,\"approved\":true,\"auth\":\"cards/0/a4\",\"card\":\"ic_cards_0_4\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a4:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"d98e2d95014b23475e5a9dc03eff95e042279e639774fcf944910527f1be1e0f\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":340,\"approved\":true,\"auth\":\"cards/0/a3\",\"card\":\"ic_cards_0_3\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"8362108c63e88ebc377b524b557fdd8a32d1c58aa164fddeb83516330a3e6774\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":334,\"approved\":true,\"auth\":\"cards/0/a5\",\"card\":\"ic_cards_0_5\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a5:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"0917b43814e981c8ad0bea6929d58f23bf50b65034478b1cde0840d47082d86a\",\"received\":\"accepted\"}"
]


def test_cards():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
