"""Regression: several cards under one cardholder (cards), from sprint run seed 1 against demo.sprint.handlers:Late.

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
 "{\"event\":{\"amount\":350,\"auth\":\"cards/0/a1\",\"card\":\"ic_cards_0_1\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a1:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":338,\"auth\":\"cards/0/a2\",\"card\":\"ic_cards_0_2\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a2:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"094f23a39d10b67a614166f58d93aaf5408dabd4261fb57f7ecab537a76bd89d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":340,\"auth\":\"cards/0/a3\",\"card\":\"ic_cards_0_3\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a3:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"2144a59640023ac236def43cc0fc5d290bfac508c0e3a8f14950de29f22889b5\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":336,\"auth\":\"cards/0/a4\",\"card\":\"ic_cards_0_4\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a4:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"ed06b4360442728897a76a68a4ef1dadeb6c29e2281bfb4916a5689a61d060dd\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":334,\"auth\":\"cards/0/a5\",\"card\":\"ic_cards_0_5\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a5:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"54ca6784e0aa532576283fc21e81603bb23e309eb879c9b9d7547f9020bc24fa\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":347,\"auth\":\"cards/0/a6\",\"card\":\"ic_cards_0_6\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a6:request\",\"kind\":\"request\",\"t\":1771894805},\"prev\":\"7c5c72b6800490d11cc8961eb4028cf51adcc4612f00782cba2536976c251c61\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805001,\"approved\":true,\"auth\":\"cards/0/a6\",\"id\":\"tee:cards/0/a6:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"ebcab709637d4cb53b4be62c28a32acaada7693c59f60fb4e33bc962a77b7cd5\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805002,\"approved\":true,\"auth\":\"cards/0/a4\",\"id\":\"tee:cards/0/a4:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"0f550df2363e9f152ce2aeb2551255c9fc6cf5ae4005345c0d6047059379f285\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805003,\"approved\":true,\"auth\":\"cards/0/a1\",\"id\":\"tee:cards/0/a1:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"b931c2e07296fed6090a402673662cd713a7846c7c0ffc2fd84f463a21982f6e\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805004,\"approved\":true,\"auth\":\"cards/0/a2\",\"id\":\"tee:cards/0/a2:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"8f50f9b090a361ef325cb283eb9dd9ed38e838982234a2ca27628bdd6003171b\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805005,\"approved\":true,\"auth\":\"cards/0/a3\",\"id\":\"tee:cards/0/a3:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"e1bd176aa8c16f3c1dfd173db244cb0aa7836374fee05a6956b2d13597d6fd88\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771894805006,\"approved\":true,\"auth\":\"cards/0/a5\",\"id\":\"tee:cards/0/a5:request\",\"kind\":\"answer\",\"t\":1771894805},\"prev\":\"73bbd2ba63e9d64c4f49d3e64704647cd5c8c8f2f480439e1d8838c3d86f59fb\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":347,\"approved\":true,\"auth\":\"cards/0/a6\",\"card\":\"ic_cards_0_6\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a6:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"46dafd3f038c6b303a107a707e45436919731e958143e2e4106222e17ca5b142\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":336,\"approved\":true,\"auth\":\"cards/0/a4\",\"card\":\"ic_cards_0_4\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a4:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"c653e55bd817d4dbb88362ef939aeb6d54b1de1fe7fe298033e5fac429cc2803\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"approved\":true,\"auth\":\"cards/0/a1\",\"card\":\"ic_cards_0_1\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"f028ba0d4cae43eb36722935693b7b4d97bc2d21f9c8564617ed1ae60bc6cc77\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":338,\"approved\":true,\"auth\":\"cards/0/a2\",\"card\":\"ic_cards_0_2\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"585359d02308157836b4b1a456c0d25f67a851c3b4f84af1f6a0ebb67767b82d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":340,\"approved\":true,\"auth\":\"cards/0/a3\",\"card\":\"ic_cards_0_3\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"e25f9f06311b77a9e901a065517a41cd81f1357440a5061476b6de7ba4053e49\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":334,\"approved\":true,\"auth\":\"cards/0/a5\",\"card\":\"ic_cards_0_5\",\"cardholder\":\"ich_cards_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"cards/0/a5:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771894805},\"prev\":\"fad01236fbaf8171afc3c390f81a918dc782a048252280c8a16f4eca5aa5f637\",\"received\":\"accepted\"}"
]


def test_cards():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
