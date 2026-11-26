"""Regression: an uncaptured hold that expires, and two limits on one purchase (expiry), from sprint run seed 1 against demo.sprint.handlers:Late.

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
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/x1\",\"kind\":\"capture\",\"t\":1786237184},\"prev\":\"0000000000000000000000000000000000000000000000000000000000000000\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/x2\",\"kind\":\"capture\",\"t\":1786237183},\"prev\":\"b84555c3dd6d82bfe7594b2dbe9e10a926d3b5e2076eacfdee3ae3c6826b125d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/x3\",\"kind\":\"capture\",\"t\":1786237182},\"prev\":\"6b6614e5de27b0feb41256dd5dc23e1af8017abed3d62cadb4e26844ca339d21\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/x4\",\"kind\":\"capture\",\"t\":1786237181},\"prev\":\"fdef8a052b0597beff40ed52c9a9632382e4d1657acfb475da818e929b589efe\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/x5\",\"kind\":\"capture\",\"t\":1786237180},\"prev\":\"f347e809fe3f4578b18d8cb93782e33c34553f25fb9b92ffc222950141c67446\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":196,\"auth\":\"expiry/0/a1\",\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a1:request\",\"kind\":\"request\",\"t\":1786237205},\"prev\":\"de00352e2868c01188c13497dfb599a334916e167423e292a01821375917462b\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786237205001,\"approved\":true,\"auth\":\"expiry/0/a1\",\"id\":\"tee:expiry/0/a1:request\",\"kind\":\"answer\",\"t\":1786237205},\"prev\":\"e4c08ab3bf36bf27d2f6e025a3e46ef88c9036f75af34d42126caff0f3214ae2\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":196,\"approved\":true,\"auth\":\"expiry/0/a1\",\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1786237205},\"prev\":\"56466ba509107bbc108458a1e36da287f29ceff42ebb12528fb42195346145ea\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":32,\"auth\":\"expiry/0/a2\",\"card\":\"ic_expiry_0_2\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a2:request\",\"kind\":\"request\",\"t\":1786237210},\"prev\":\"2c63914841397dbe748416b904bdc0275862521a1d1b11672be0e21d1dce1a9f\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786237210001,\"approved\":true,\"auth\":\"expiry/0/a2\",\"id\":\"tee:expiry/0/a2:request\",\"kind\":\"answer\",\"t\":1786237210},\"prev\":\"3234d63cef5844d810fc1ba389dc6ea2dcc170515a4e4d937f08cd2d810cf268\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":32,\"approved\":true,\"auth\":\"expiry/0/a2\",\"card\":\"ic_expiry_0_2\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1786237210},\"prev\":\"3bbf988c50098dc33a4ade0eb4a7f6fe51c82c68bd544b465e1b52489800ddfc\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":32,\"auth\":\"expiry/0/a2\",\"card\":\"ic_expiry_0_2\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"expiry/0/a2:capture@1786237211\",\"kind\":\"capture\",\"t\":1786237211},\"prev\":\"7dac8f50cdc8bffedfa501ac5ee9cb47374636aa7d90a2c39510843c1089bddf\",\"received\":\"accepted\"}",
 "{\"event\":{\"auth\":\"expiry/0/a1\",\"currency\":\"usd\",\"id\":\"expiry/0/a1:expire@1786237505\",\"kind\":\"expire\",\"t\":1786237505},\"prev\":\"3a9b2c336b48e6b0e7c7789d2fe5409c4c4fcfeab9b7d39b6fc808110b74e1ea\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":290,\"auth\":\"expiry/0/a3\",\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a3:request\",\"kind\":\"request\",\"t\":1786237515},\"prev\":\"f0ae571c8e15c99c2e546b36cc81c4ffa7cc1bea7cce246284865c7bde6e2119\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1786237515001,\"approved\":false,\"auth\":\"expiry/0/a3\",\"id\":\"tee:expiry/0/a3:request\",\"kind\":\"answer\",\"t\":1786237515},\"prev\":\"1c4c6cc3f682ab2381d4d23cee6dd93a25e6b17cd7839009773a2b66cd7aa53e\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":290,\"approved\":false,\"auth\":\"expiry/0/a3\",\"card\":\"ic_expiry_0_1\",\"cardholder\":\"ich_expiry_0\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"expiry/0/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_declined\",\"t\":1786237515},\"prev\":\"36d4822069ce8644117f7aae14f01ee71a5df5080224e551a2bc395f2aa86b84\",\"received\":\"accepted\"}"
]


def test_expiry():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
