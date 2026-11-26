# The contracted path was decided (no part UNKNOWN); 6 of 8 families have a finding; the processor was simulated, and nothing here is a statement about a processor's system.

handler demo.sprint.handlers:Late; scope demo/sprint/scope.json; seed 1; trials 99 in each family with a race; 8 asks at once

The three parts below are kept apart: a figure of one part is not printed in another.

# Model

- What the model answers for the scope's card profile, once per limit (kamanu scan --card on profiles/<id>.json, the limit's amount as the face). A check's level is the model's own.

## limit cardholder-daily (daily, amount 2000)

- cardholder-daily: face 2000, ceiling 2000, fineness 1.000; level ASSUMED

- Sound: VACUOUS, level ASSUMED

- Tight: holds, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: daily: one fixed calendar window, the UTC day (it resets at midnight UTC); the card model checks the bucket of one such window, and the ledger keeps one bucket per window; a sliding window is not what was checked

- profile profiles/cardholder-daily.json; receipt receipts/cardholder-daily.json

- Tight's trace: none (Tight does not fail)

## limit card-per-authorization (per_authorization, amount 350)

- card-per-authorization: face 350, ceiling 350, fineness 1.000; level ASSUMED

- Sound: VACUOUS, level ASSUMED

- Tight: holds, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: per_authorization: no calendar window; the bucket is the authorization itself (its hold and captures)

- profile profiles/card-per-authorization.json; receipt receipts/card-per-authorization.json

- Tight's trace: none (Tight does not fail)

## limit cards-monthly (monthly, amount 20000)

- cards-monthly: face 20000, ceiling 24000, fineness .833; level ASSUMED

- Sound: FAILS, level REFUTED

- Tight: VACUOUS, level ASSUMED

- constant Atomic = false (assumed)

- constant Lag = 1 (assumed)

- constant OverCapture = 20 (assumed)

- window: monthly: one fixed calendar window, the UTC calendar month; the card model checks the bucket of one such window, and the ledger keeps one bucket per window; a sliding window is not what was checked

- profile profiles/cards-monthly.json; receipt receipts/cards-monthly.json

- Tight's trace: none (Tight does not fail)

# Measurement

- Every count below is a count of this run's journals, level TESTED: the battery played against the handler on a simulated processor, read by python -m exonumia.ledger report --json --orders (seed 1, 8 asks at once in the parallel family; TESTED).

## single asks below, at and above the limit

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/single.jsonl; ledger report ledger/single.json

## parallel asks

- trials: 99 (TESTED)

- approvals that did not fit: 99 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 211 (TESTED)

- finding: yes, TESTED on this run

- journal journals/parallel.jsonl; ledger report ledger/parallel.json

the shortest trace of the finding (24 journal lines, TESTED):

```
{"event":{"amount":273,"auth":"parallel/0/a1","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a1:request","kind":"request","t":1790643606},"prev":"0000000000000000000000000000000000000000000000000000000000000000","received":"accepted"}
{"event":{"amount":281,"auth":"parallel/0/a2","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a2:request","kind":"request","t":1790643606},"prev":"e250ec5c782b531e0f6bc59fd9a8741bae7d04a8a58d0914f51ad63cad3c5deb","received":"accepted"}
{"event":{"amount":253,"auth":"parallel/0/a3","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a3:request","kind":"request","t":1790643606},"prev":"12d11d2cb02540e1d04ac8cb160747c5047720dd862812b8b1509fd344b74ab7","received":"accepted"}
{"event":{"amount":279,"auth":"parallel/0/a4","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a4:request","kind":"request","t":1790643606},"prev":"9586fa744cf45d7fe20c9add37a2a555d25716788b9ce3cd882be65ea1eddec0","received":"accepted"}
{"event":{"amount":253,"auth":"parallel/0/a5","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a5:request","kind":"request","t":1790643606},"prev":"9e9c4cf59ad88e36c1618390fbbf360565885990f10228099ec5ee42d42bb08e","received":"accepted"}
{"event":{"amount":285,"auth":"parallel/0/a6","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a6:request","kind":"request","t":1790643606},"prev":"af82c494f5eb568dfd0a96832c31d2e7cd4450220227511db3b51d5375694e89","received":"accepted"}
{"event":{"amount":266,"auth":"parallel/0/a7","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a7:request","kind":"request","t":1790643606},"prev":"024a2a19f6407e202bb940cdfa76130e3b25365a6e1694d1a0d4780144fa4bf9","received":"accepted"}
{"event":{"amount":255,"auth":"parallel/0/a8","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a8:request","kind":"request","t":1790643606},"prev":"58e10f39a7b12b3623a8a75cc86822fedb40f93326ef0fb0b247dbfa8f8cd45d","received":"accepted"}
{"event":{"answered_ms":1790643606001,"approved":true,"auth":"parallel/0/a8","id":"tee:parallel/0/a8:request","kind":"answer","t":1790643606},"prev":"18d5f940e89860a814535229edf440eeacbac057f40699c5d957ad390e7a8a87","received":"accepted"}
{"event":{"answered_ms":1790643606002,"approved":true,"auth":"parallel/0/a1","id":"tee:parallel/0/a1:request","kind":"answer","t":1790643606},"prev":"ae342bcb29e8913698e1d1ff491a2de04003129c50b5836c2637adb71ba86948","received":"accepted"}
{"event":{"answered_ms":1790643606003,"approved":true,"auth":"parallel/0/a2","id":"tee:parallel/0/a2:request","kind":"answer","t":1790643606},"prev":"cb9c3da611a81e0c2a6f51d8399aee736536f13267550be1e6e669d4d2b06588","received":"accepted"}
{"event":{"answered_ms":1790643606004,"approved":true,"auth":"parallel/0/a3","id":"tee:parallel/0/a3:request","kind":"answer","t":1790643606},"prev":"2a00944e7537a8c09f429c5dabcd059091b593d13a7aa8ba29907f1e1e8a36d3","received":"accepted"}
{"event":{"answered_ms":1790643606005,"approved":true,"auth":"parallel/0/a4","id":"tee:parallel/0/a4:request","kind":"answer","t":1790643606},"prev":"a5fecba633e85788385a0d40eb364a5b74344c6d5a5bf68ce00bf137067b74c0","received":"accepted"}
{"event":{"answered_ms":1790643606006,"approved":true,"auth":"parallel/0/a5","id":"tee:parallel/0/a5:request","kind":"answer","t":1790643606},"prev":"8ba9a1b53f872bb78513dec7451b464367dd56fb3d98b348545e7645fdda88b9","received":"accepted"}
{"event":{"answered_ms":1790643606007,"approved":true,"auth":"parallel/0/a6","id":"tee:parallel/0/a6:request","kind":"answer","t":1790643606},"prev":"a159371e118299a9e8353de15cc063f4f76c923d2accab71e8730b6add6214ad","received":"accepted"}
{"event":{"answered_ms":1790643606008,"approved":true,"auth":"parallel/0/a7","id":"tee:parallel/0/a7:request","kind":"answer","t":1790643606},"prev":"3dc84b6ab0290bc3a5d4667c4a4f41c82592e9d20418bd9d150b07e57cad1e3b","received":"accepted"}
{"event":{"amount":255,"approved":true,"auth":"parallel/0/a8","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a8:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"62a94b8458b9839e26e8ec79f7b0fa3f45febd89f3706dd17a72a4376085f199","received":"accepted"}
{"event":{"amount":273,"approved":true,"auth":"parallel/0/a1","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"d5ae001cf6c8b49558c7f2dd4082b770d2672ce481148cd016defdf24a7e38a8","received":"accepted"}
{"event":{"amount":281,"approved":true,"auth":"parallel/0/a2","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"1002936453f6bb02667ed7d3f274c438f20be6c21d81d156c70e52229e649b1b","received":"accepted"}
{"event":{"amount":253,"approved":true,"auth":"parallel/0/a3","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a3:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"23f6ee64476fa1f46b26aeb9c4ab1ba91e1a3277459a29fdc526c265daf25bb4","received":"accepted"}
{"event":{"amount":279,"approved":true,"auth":"parallel/0/a4","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a4:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"70a407926cdfce2990ba78953727c518313a70f27ad7dabcfc7ff8420440627b","received":"accepted"}
{"event":{"amount":253,"approved":true,"auth":"parallel/0/a5","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a5:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"1b3b92049634aa7fa2efdd9e884612caa9240c5302af489230950cba0a42d64e","received":"accepted"}
{"event":{"amount":285,"approved":true,"auth":"parallel/0/a6","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a6:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"670e7e1e8f6c14e264e6cba5caa8b701956b21f6d824b2147b007d325dfdb0b4","received":"accepted"}
{"event":{"amount":266,"approved":true,"auth":"parallel/0/a7","card":"ic_parallel_0_1","cardholder":"ich_parallel_0","category":"5734","currency":"usd","id":"parallel/0/a7:outcome","kind":"outcome","reason":"webhook_approved","t":1790643606},"prev":"aff153e2162ad8c1c9cce6ebad2102835c34c5b66ac32dfc6621a5dd7c0cd6fe","received":"accepted"}
```

- regression test regressions/test_parallel.py (it fails while the finding stands)

## several cards under one cardholder

- trials: 99 (TESTED)

- approvals that did not fit: 99 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 81 (TESTED)

- finding: yes, TESTED on this run

- journal journals/cards.jsonl; ledger report ledger/cards.json

the shortest trace of the finding (18 journal lines, TESTED):

```
{"event":{"amount":350,"auth":"cards/0/a1","card":"ic_cards_0_1","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a1:request","kind":"request","t":1771894805},"prev":"0000000000000000000000000000000000000000000000000000000000000000","received":"accepted"}
{"event":{"amount":338,"auth":"cards/0/a2","card":"ic_cards_0_2","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a2:request","kind":"request","t":1771894805},"prev":"094f23a39d10b67a614166f58d93aaf5408dabd4261fb57f7ecab537a76bd89d","received":"accepted"}
{"event":{"amount":340,"auth":"cards/0/a3","card":"ic_cards_0_3","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a3:request","kind":"request","t":1771894805},"prev":"2144a59640023ac236def43cc0fc5d290bfac508c0e3a8f14950de29f22889b5","received":"accepted"}
{"event":{"amount":336,"auth":"cards/0/a4","card":"ic_cards_0_4","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a4:request","kind":"request","t":1771894805},"prev":"ed06b4360442728897a76a68a4ef1dadeb6c29e2281bfb4916a5689a61d060dd","received":"accepted"}
{"event":{"amount":334,"auth":"cards/0/a5","card":"ic_cards_0_5","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a5:request","kind":"request","t":1771894805},"prev":"54ca6784e0aa532576283fc21e81603bb23e309eb879c9b9d7547f9020bc24fa","received":"accepted"}
{"event":{"amount":347,"auth":"cards/0/a6","card":"ic_cards_0_6","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a6:request","kind":"request","t":1771894805},"prev":"7c5c72b6800490d11cc8961eb4028cf51adcc4612f00782cba2536976c251c61","received":"accepted"}
{"event":{"answered_ms":1771894805001,"approved":true,"auth":"cards/0/a6","id":"tee:cards/0/a6:request","kind":"answer","t":1771894805},"prev":"ebcab709637d4cb53b4be62c28a32acaada7693c59f60fb4e33bc962a77b7cd5","received":"accepted"}
{"event":{"answered_ms":1771894805002,"approved":true,"auth":"cards/0/a4","id":"tee:cards/0/a4:request","kind":"answer","t":1771894805},"prev":"0f550df2363e9f152ce2aeb2551255c9fc6cf5ae4005345c0d6047059379f285","received":"accepted"}
{"event":{"answered_ms":1771894805003,"approved":true,"auth":"cards/0/a1","id":"tee:cards/0/a1:request","kind":"answer","t":1771894805},"prev":"b931c2e07296fed6090a402673662cd713a7846c7c0ffc2fd84f463a21982f6e","received":"accepted"}
{"event":{"answered_ms":1771894805004,"approved":true,"auth":"cards/0/a2","id":"tee:cards/0/a2:request","kind":"answer","t":1771894805},"prev":"8f50f9b090a361ef325cb283eb9dd9ed38e838982234a2ca27628bdd6003171b","received":"accepted"}
{"event":{"answered_ms":1771894805005,"approved":true,"auth":"cards/0/a3","id":"tee:cards/0/a3:request","kind":"answer","t":1771894805},"prev":"e1bd176aa8c16f3c1dfd173db244cb0aa7836374fee05a6956b2d13597d6fd88","received":"accepted"}
{"event":{"answered_ms":1771894805006,"approved":true,"auth":"cards/0/a5","id":"tee:cards/0/a5:request","kind":"answer","t":1771894805},"prev":"73bbd2ba63e9d64c4f49d3e64704647cd5c8c8f2f480439e1d8838c3d86f59fb","received":"accepted"}
{"event":{"amount":347,"approved":true,"auth":"cards/0/a6","card":"ic_cards_0_6","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a6:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"46dafd3f038c6b303a107a707e45436919731e958143e2e4106222e17ca5b142","received":"accepted"}
{"event":{"amount":336,"approved":true,"auth":"cards/0/a4","card":"ic_cards_0_4","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a4:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"c653e55bd817d4dbb88362ef939aeb6d54b1de1fe7fe298033e5fac429cc2803","received":"accepted"}
{"event":{"amount":350,"approved":true,"auth":"cards/0/a1","card":"ic_cards_0_1","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"f028ba0d4cae43eb36722935693b7b4d97bc2d21f9c8564617ed1ae60bc6cc77","received":"accepted"}
{"event":{"amount":338,"approved":true,"auth":"cards/0/a2","card":"ic_cards_0_2","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"585359d02308157836b4b1a456c0d25f67a851c3b4f84af1f6a0ebb67767b82d","received":"accepted"}
{"event":{"amount":340,"approved":true,"auth":"cards/0/a3","card":"ic_cards_0_3","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a3:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"e25f9f06311b77a9e901a065517a41cd81f1357440a5061476b6de7ba4053e49","received":"accepted"}
{"event":{"amount":334,"approved":true,"auth":"cards/0/a5","card":"ic_cards_0_5","cardholder":"ich_cards_0","category":"5734","currency":"usd","id":"cards/0/a5:outcome","kind":"outcome","reason":"webhook_approved","t":1771894805},"prev":"fad01236fbaf8171afc3c390f81a918dc782a048252280c8a16f4eca5aa5f637","received":"accepted"}
```

- regression test regressions/test_cards.py (it fails while the finding stands)

## authorization then partial capture

- trials: 3 (TESTED)

- approvals that did not fit: 1 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 14 (TESTED)

- finding: yes, TESTED on this run

- journal journals/partial_capture.jsonl; ledger report ledger/partial_capture.json

the shortest trace of the finding (13 journal lines, TESTED):

```
{"event":{"amount":350,"auth":null,"card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":true,"id":"partial_capture/2/x1","kind":"capture","t":1782868784},"prev":"0982eb564100c2f9e1f27d1b69b5ac74a60fb1bfbf2c5a449dc22954c6fe252d","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":true,"id":"partial_capture/2/x2","kind":"capture","t":1782868783},"prev":"453e359c085fa188e51db947b54e0aedfd359b6f5aa756f38bc49d0a3545afd7","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":true,"id":"partial_capture/2/x3","kind":"capture","t":1782868782},"prev":"c19999f045d65f958fb00295ac770faf542f039ce84dca252f634ed0e088e341","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":true,"id":"partial_capture/2/x4","kind":"capture","t":1782868781},"prev":"92405d17c629bedabf4a9e288b5b370e7bcbe1097fdad4a41d952f20d75e9615","received":"accepted"}
{"event":{"amount":250,"auth":null,"card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":true,"id":"partial_capture/2/x5","kind":"capture","t":1782868780},"prev":"41bcb729eea264032843df0c467b63a2ae5749835117271db36a2a834788a9f0","received":"accepted"}
{"event":{"amount":275,"auth":"partial_capture/2/a1","card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","id":"partial_capture/2/a1:request","kind":"request","t":1782868805},"prev":"25502b220a39b65ce7cfdd9c33bee4bcd77bfcb239203a78a7a1b6f62f2ab7c9","received":"accepted"}
{"event":{"answered_ms":1782868805001,"approved":true,"auth":"partial_capture/2/a1","id":"tee:partial_capture/2/a1:request","kind":"answer","t":1782868805},"prev":"5bbb00d558a921682f677d4ceba90aa04be8347a8f82e16c263a4411d2dd29d6","received":"accepted"}
{"event":{"amount":275,"approved":true,"auth":"partial_capture/2/a1","card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","id":"partial_capture/2/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1782868805},"prev":"5e9318809748cec541332a1b19b1485d61eecce899d3d52ba1acbfa4eb385ad5","received":"accepted"}
{"event":{"amount":100,"auth":"partial_capture/2/a1","card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","final":false,"id":"partial_capture/2/a1:capture@1782868810","kind":"capture","t":1782868810},"prev":"4178706c2fe89dbae4c7b0ac714afc1dc5ddbb53558ace38eca0af7ea1da40f0","received":"accepted"}
{"event":{"amount":null,"auth":"partial_capture/2/a1","currency":"usd","id":"partial_capture/2/a1:reverse@1782868811","kind":"reverse","t":1782868811},"prev":"0610862f5c3f1d3260db7a47c446022a483480ad4c21295782e7133bcd25c4b4","received":"accepted"}
{"event":{"amount":264,"auth":"partial_capture/2/a2","card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","id":"partial_capture/2/a2:request","kind":"request","t":1782868825},"prev":"f0f30bc763aab3157c6a79cacda8e983f77c43c873779614e0ad2eb0a5f5353d","received":"accepted"}
{"event":{"answered_ms":1782868825001,"approved":true,"auth":"partial_capture/2/a2","id":"tee:partial_capture/2/a2:request","kind":"answer","t":1782868825},"prev":"bf79f9dfe36a3bbdb70ab26c797821688c5897b6779ddfec6922ada3cb019989","received":"accepted"}
{"event":{"amount":264,"approved":true,"auth":"partial_capture/2/a2","card":"ic_partial_capture_2_1","cardholder":"ich_partial_capture_2","category":"5734","currency":"usd","id":"partial_capture/2/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1782868825},"prev":"d1c73e1819c6fb00ff9299935b14887e693e0f637bfd876b1af7806e04576559","received":"accepted"}
```

- regression test regressions/test_partial_capture.py (it fails while the finding stands)

## capture above the hold, then reversal

- trials: 3 (TESTED)

- approvals that did not fit: 1 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 14 (TESTED)

- finding: yes, TESTED on this run

- journal journals/over_capture.jsonl; ledger report ledger/over_capture.json

the shortest trace of the finding (16 journal lines, TESTED):

```
{"event":{"amount":350,"auth":null,"card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/x1","kind":"capture","t":1771550386},"prev":"e025e244bd0ef668976660b4b2b14509a0eb28f2bd024af0c1ad29f94576f0c9","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/x2","kind":"capture","t":1771550385},"prev":"a90c2859807b64690e01fb4c1a58b412b3d849689774b074e1d5b21516f74cf8","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/x3","kind":"capture","t":1771550384},"prev":"e8f7d3c4efc7e345e8aa5f43bc12846c363dc9100ccd0cb30956471a11044a61","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/x4","kind":"capture","t":1771550383},"prev":"eba69d6f63f50baf105f853b3ecbeb1538b3d6f7da6a62d4ff5342ec55e4b0f6","received":"accepted"}
{"event":{"amount":250,"auth":null,"card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/x5","kind":"capture","t":1771550382},"prev":"0dccaef8d06638b10fbdc424626bcc37c5e8d59615f2c997a8fbdd683f6396ad","received":"accepted"}
{"event":{"amount":116,"auth":"over_capture/2/a1","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a1:request","kind":"request","t":1771550407},"prev":"af2a748c064f98b261ccdadbaddb15cd9525b7614871e475b1d970ca36a02925","received":"accepted"}
{"event":{"answered_ms":1771550407001,"approved":true,"auth":"over_capture/2/a1","id":"tee:over_capture/2/a1:request","kind":"answer","t":1771550407},"prev":"dfa94ff83d6c1d95df0e1e12f85d7b17b15661e45c9685ca2a38a4d5c926c710","received":"accepted"}
{"event":{"amount":116,"approved":true,"auth":"over_capture/2/a1","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1771550407},"prev":"69313d352abe5f62a71fcd9cc8b2162a9e3a058d4ee809e4e11e15b59ce02bf4","received":"accepted"}
{"event":{"amount":136,"auth":"over_capture/2/a1","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","final":true,"id":"over_capture/2/a1:capture@1771550412","kind":"capture","t":1771550412},"prev":"59a231406fc023457e2488bffc4c147cf592c643b3628cd0e69c0ff223c7c571","received":"accepted"}
{"event":{"amount":115,"auth":"over_capture/2/a2","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a2:request","kind":"request","t":1771550413},"prev":"95ff86371ebc3edb72ef7c10f9df8022e1c67b2223f7e291649c0fdf339b70ec","received":"accepted"}
{"event":{"answered_ms":1771550413001,"approved":true,"auth":"over_capture/2/a2","id":"tee:over_capture/2/a2:request","kind":"answer","t":1771550413},"prev":"158fc38c806baa7643aff58db82f5378de5cb99cbe8c3444b7888710a42e98e9","received":"accepted"}
{"event":{"amount":115,"approved":true,"auth":"over_capture/2/a2","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1771550413},"prev":"390aab84bfcc7ddc4d0f82ddf791c29db733b956f2277525a9da3715c397540d","received":"accepted"}
{"event":{"amount":null,"auth":"over_capture/2/a2","currency":"usd","id":"over_capture/2/a2:reverse@1771550415","kind":"reverse","t":1771550415},"prev":"67a9a66257f8544f92796f23ec00d7266c2df779a7f792d107ba5ab0726286cf","received":"accepted"}
{"event":{"amount":228,"auth":"over_capture/2/a3","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a3:request","kind":"request","t":1771550427},"prev":"997dfac725bf53ab175cb8b15a30b18f12df5512d065fabb90410061eaa4d1bd","received":"accepted"}
{"event":{"answered_ms":1771550427001,"approved":true,"auth":"over_capture/2/a3","id":"tee:over_capture/2/a3:request","kind":"answer","t":1771550427},"prev":"084c4434c3fc06fca8afca084f5199fce08fbe237adba9550f6d54eb2faa101b","received":"accepted"}
{"event":{"amount":228,"approved":true,"auth":"over_capture/2/a3","card":"ic_over_capture_2_1","cardholder":"ich_over_capture_2","category":"5734","currency":"usd","id":"over_capture/2/a3:outcome","kind":"outcome","reason":"webhook_approved","t":1771550427},"prev":"bdd91be78898954fe2795484db1b4608b90ec41946f6a4012be4290af75560a4","received":"accepted"}
```

- regression test regressions/test_over_capture.py (it fails while the finding stands)

## time-out with an ambiguous outcome, then retry

- trials: 99 (TESTED)

- approvals that did not fit: 76 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 350 (TESTED)

- finding: yes, TESTED on this run

- journal journals/timeout.jsonl; ledger report ledger/timeout.json

the shortest trace of the finding (11 journal lines, TESTED):

```
{"event":{"amount":350,"auth":null,"card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","final":true,"id":"timeout/0/x1","kind":"capture","t":1775782788},"prev":"0000000000000000000000000000000000000000000000000000000000000000","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","final":true,"id":"timeout/0/x2","kind":"capture","t":1775782787},"prev":"a3961dad16a40d3b0bf41955ac2517b8d27a1ba23bb3ce9309da77bfc37c333b","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","final":true,"id":"timeout/0/x3","kind":"capture","t":1775782786},"prev":"a8a3517cecfae0049b2dfdfeaff4e9ca9c9bfa4b0a64ba9ca3ef02505ab1062c","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","final":true,"id":"timeout/0/x4","kind":"capture","t":1775782785},"prev":"0d73fb2818a34140117746928211d0b53d42e43a7ad35d17deb4f78b5c79ddc3","received":"accepted"}
{"event":{"amount":250,"auth":null,"card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","final":true,"id":"timeout/0/x5","kind":"capture","t":1775782784},"prev":"5f1b0581e7547e85ebe022e9265ca6fc23e784517e92c70dd23eff0c16a860b4","received":"accepted"}
{"event":{"amount":343,"auth":"timeout/0/a1","card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","id":"timeout/0/a1:request","kind":"request","t":1775782809},"prev":"667f13202f92b23b3873b40902b409ebbe36c6485c3ee854739be41984f3d9ef","received":"accepted"}
{"event":{"answered_ms":1775782809001,"approved":true,"auth":"timeout/0/a1","id":"tee:timeout/0/a1:request","kind":"answer","t":1775782809},"prev":"d9289c695e117af4a806e8f71c71b1daf6096e1666ce52f935ae6d9c96ac072f","received":"accepted"}
{"event":{"amount":343,"approved":true,"auth":"timeout/0/a1","card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","id":"timeout/0/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1775782809},"prev":"11b9a5c6b573377e218ca01bb640607405b26361f000d45ab593abcd4a8be757","received":"accepted"}
{"event":{"amount":343,"auth":"timeout/0/a2","card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","id":"timeout/0/a2:request","kind":"request","t":1775782812},"prev":"3968b5300dc034c1cb83d19b5fb04bf1461622628b4b829568107150ce11cf96","received":"accepted"}
{"event":{"answered_ms":1775782812001,"approved":true,"auth":"timeout/0/a2","id":"tee:timeout/0/a2:request","kind":"answer","t":1775782812},"prev":"c882f7698e4724667fdae570c6f9ab7eddfb868633de5434ff2a64ac3a517927","received":"accepted"}
{"event":{"amount":343,"approved":true,"auth":"timeout/0/a2","card":"ic_timeout_0_1","cardholder":"ich_timeout_0","category":"5734","currency":"usd","id":"timeout/0/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1775782812},"prev":"60c8638160b58b890efa0c15be2c07dc27d2ae34cbbf84796b2c586cc2810025","received":"accepted"}
```

- regression test regressions/test_timeout.py (it fails while the finding stands)

## reset at the interval's boundary

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 0 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: none, TESTED on this run

- 3 clean trials bound how often a race can occur and do not show that it cannot; a race that occurs 63.2% of the time or more would be missed with probability at most 5%; a rarer one can still be there.

- journal journals/reset.jsonl; ledger report ledger/reset.json

## an uncaptured hold that expires, and two limits on one purchase

- trials: 3 (TESTED)

- approvals that did not fit: 0 (TESTED)

- wrongful refusals: 2 (TESTED)

- order-dependent decisions: 0 (TESTED; never a finding)

- largest amount over a limit: 0 (TESTED)

- finding: yes, TESTED on this run

- journal journals/expiry.jsonl; ledger report ledger/expiry.json

the shortest trace of the finding (16 journal lines, TESTED):

```
{"event":{"amount":350,"auth":null,"card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/x1","kind":"capture","t":1786237184},"prev":"0000000000000000000000000000000000000000000000000000000000000000","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/x2","kind":"capture","t":1786237183},"prev":"b84555c3dd6d82bfe7594b2dbe9e10a926d3b5e2076eacfdee3ae3c6826b125d","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/x3","kind":"capture","t":1786237182},"prev":"6b6614e5de27b0feb41256dd5dc23e1af8017abed3d62cadb4e26844ca339d21","received":"accepted"}
{"event":{"amount":350,"auth":null,"card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/x4","kind":"capture","t":1786237181},"prev":"fdef8a052b0597beff40ed52c9a9632382e4d1657acfb475da818e929b589efe","received":"accepted"}
{"event":{"amount":250,"auth":null,"card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/x5","kind":"capture","t":1786237180},"prev":"f347e809fe3f4578b18d8cb93782e33c34553f25fb9b92ffc222950141c67446","received":"accepted"}
{"event":{"amount":196,"auth":"expiry/0/a1","card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a1:request","kind":"request","t":1786237205},"prev":"de00352e2868c01188c13497dfb599a334916e167423e292a01821375917462b","received":"accepted"}
{"event":{"answered_ms":1786237205001,"approved":true,"auth":"expiry/0/a1","id":"tee:expiry/0/a1:request","kind":"answer","t":1786237205},"prev":"e4c08ab3bf36bf27d2f6e025a3e46ef88c9036f75af34d42126caff0f3214ae2","received":"accepted"}
{"event":{"amount":196,"approved":true,"auth":"expiry/0/a1","card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a1:outcome","kind":"outcome","reason":"webhook_approved","t":1786237205},"prev":"56466ba509107bbc108458a1e36da287f29ceff42ebb12528fb42195346145ea","received":"accepted"}
{"event":{"amount":32,"auth":"expiry/0/a2","card":"ic_expiry_0_2","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a2:request","kind":"request","t":1786237210},"prev":"2c63914841397dbe748416b904bdc0275862521a1d1b11672be0e21d1dce1a9f","received":"accepted"}
{"event":{"answered_ms":1786237210001,"approved":true,"auth":"expiry/0/a2","id":"tee:expiry/0/a2:request","kind":"answer","t":1786237210},"prev":"3234d63cef5844d810fc1ba389dc6ea2dcc170515a4e4d937f08cd2d810cf268","received":"accepted"}
{"event":{"amount":32,"approved":true,"auth":"expiry/0/a2","card":"ic_expiry_0_2","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a2:outcome","kind":"outcome","reason":"webhook_approved","t":1786237210},"prev":"3bbf988c50098dc33a4ade0eb4a7f6fe51c82c68bd544b465e1b52489800ddfc","received":"accepted"}
{"event":{"amount":32,"auth":"expiry/0/a2","card":"ic_expiry_0_2","cardholder":"ich_expiry_0","category":"5734","currency":"usd","final":true,"id":"expiry/0/a2:capture@1786237211","kind":"capture","t":1786237211},"prev":"7dac8f50cdc8bffedfa501ac5ee9cb47374636aa7d90a2c39510843c1089bddf","received":"accepted"}
{"event":{"auth":"expiry/0/a1","currency":"usd","id":"expiry/0/a1:expire@1786237505","kind":"expire","t":1786237505},"prev":"3a9b2c336b48e6b0e7c7789d2fe5409c4c4fcfeab9b7d39b6fc808110b74e1ea","received":"accepted"}
{"event":{"amount":290,"auth":"expiry/0/a3","card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a3:request","kind":"request","t":1786237515},"prev":"f0ae571c8e15c99c2e546b36cc81c4ffa7cc1bea7cce246284865c7bde6e2119","received":"accepted"}
{"event":{"answered_ms":1786237515001,"approved":false,"auth":"expiry/0/a3","id":"tee:expiry/0/a3:request","kind":"answer","t":1786237515},"prev":"1c4c6cc3f682ab2381d4d23cee6dd93a25e6b17cd7839009773a2b66cd7aa53e","received":"accepted"}
{"event":{"amount":290,"approved":false,"auth":"expiry/0/a3","card":"ic_expiry_0_1","cardholder":"ich_expiry_0","category":"5734","currency":"usd","id":"expiry/0/a3:outcome","kind":"outcome","reason":"webhook_declined","t":1786237515},"prev":"36d4822069ce8644117f7aae14f01ee71a5df5080224e551a2bc395f2aa86b84","received":"accepted"}
```

- regression test regressions/test_expiry.py (it fails while the finding stands)

# Deployment

- No live configuration was given (--live): nothing connects the tested configuration to a live one.
