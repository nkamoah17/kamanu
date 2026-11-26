"""Regression: capture above the hold, then reversal (over_capture), from sprint run seed 1 against demo.sprint.handlers:Late.

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
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/x1\",\"kind\":\"capture\",\"t\":1771550386},\"prev\":\"e025e244bd0ef668976660b4b2b14509a0eb28f2bd024af0c1ad29f94576f0c9\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/x2\",\"kind\":\"capture\",\"t\":1771550385},\"prev\":\"a90c2859807b64690e01fb4c1a58b412b3d849689774b074e1d5b21516f74cf8\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/x3\",\"kind\":\"capture\",\"t\":1771550384},\"prev\":\"e8f7d3c4efc7e345e8aa5f43bc12846c363dc9100ccd0cb30956471a11044a61\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":350,\"auth\":null,\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/x4\",\"kind\":\"capture\",\"t\":1771550383},\"prev\":\"eba69d6f63f50baf105f853b3ecbeb1538b3d6f7da6a62d4ff5342ec55e4b0f6\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":250,\"auth\":null,\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/x5\",\"kind\":\"capture\",\"t\":1771550382},\"prev\":\"0dccaef8d06638b10fbdc424626bcc37c5e8d59615f2c997a8fbdd683f6396ad\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":116,\"auth\":\"over_capture/2/a1\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a1:request\",\"kind\":\"request\",\"t\":1771550407},\"prev\":\"af2a748c064f98b261ccdadbaddb15cd9525b7614871e475b1d970ca36a02925\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771550407001,\"approved\":true,\"auth\":\"over_capture/2/a1\",\"id\":\"tee:over_capture/2/a1:request\",\"kind\":\"answer\",\"t\":1771550407},\"prev\":\"dfa94ff83d6c1d95df0e1e12f85d7b17b15661e45c9685ca2a38a4d5c926c710\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":116,\"approved\":true,\"auth\":\"over_capture/2/a1\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a1:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771550407},\"prev\":\"69313d352abe5f62a71fcd9cc8b2162a9e3a058d4ee809e4e11e15b59ce02bf4\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":136,\"auth\":\"over_capture/2/a1\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"final\":true,\"id\":\"over_capture/2/a1:capture@1771550412\",\"kind\":\"capture\",\"t\":1771550412},\"prev\":\"59a231406fc023457e2488bffc4c147cf592c643b3628cd0e69c0ff223c7c571\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":115,\"auth\":\"over_capture/2/a2\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a2:request\",\"kind\":\"request\",\"t\":1771550413},\"prev\":\"95ff86371ebc3edb72ef7c10f9df8022e1c67b2223f7e291649c0fdf339b70ec\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771550413001,\"approved\":true,\"auth\":\"over_capture/2/a2\",\"id\":\"tee:over_capture/2/a2:request\",\"kind\":\"answer\",\"t\":1771550413},\"prev\":\"158fc38c806baa7643aff58db82f5378de5cb99cbe8c3444b7888710a42e98e9\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":115,\"approved\":true,\"auth\":\"over_capture/2/a2\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a2:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771550413},\"prev\":\"390aab84bfcc7ddc4d0f82ddf791c29db733b956f2277525a9da3715c397540d\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":null,\"auth\":\"over_capture/2/a2\",\"currency\":\"usd\",\"id\":\"over_capture/2/a2:reverse@1771550415\",\"kind\":\"reverse\",\"t\":1771550415},\"prev\":\"67a9a66257f8544f92796f23ec00d7266c2df779a7f792d107ba5ab0726286cf\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":228,\"auth\":\"over_capture/2/a3\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a3:request\",\"kind\":\"request\",\"t\":1771550427},\"prev\":\"997dfac725bf53ab175cb8b15a30b18f12df5512d065fabb90410061eaa4d1bd\",\"received\":\"accepted\"}",
 "{\"event\":{\"answered_ms\":1771550427001,\"approved\":true,\"auth\":\"over_capture/2/a3\",\"id\":\"tee:over_capture/2/a3:request\",\"kind\":\"answer\",\"t\":1771550427},\"prev\":\"084c4434c3fc06fca8afca084f5199fce08fbe237adba9550f6d54eb2faa101b\",\"received\":\"accepted\"}",
 "{\"event\":{\"amount\":228,\"approved\":true,\"auth\":\"over_capture/2/a3\",\"card\":\"ic_over_capture_2_1\",\"cardholder\":\"ich_over_capture_2\",\"category\":\"5734\",\"currency\":\"usd\",\"id\":\"over_capture/2/a3:outcome\",\"kind\":\"outcome\",\"reason\":\"webhook_approved\",\"t\":1771550427},\"prev\":\"bdd91be78898954fe2795484db1b4608b90ec41946f6a4012be4290af75560a4\",\"received\":\"accepted\"}"
]


def test_over_capture():
    target = os.environ.get("KAMANU_SPRINT_HANDLER") or HANDLER
    got = regress.replay(target, LIMITS, PROFILE, TRACE, SECRET)
    assert not got["finding"], got["text"]
