# The offer as one source

`offer/offer.yaml` (offer-v1) is the owner's source for the launch page, the one-page offer and the engagement
letter. Change a term there and rebuild:

```
python -m exonumia.offer build --out offer/site
```

This writes `offer/site/index.html` (one self-contained page), `offer/offer.md` and `offer/engagement-letter.md`
(`--docs DIR` puts the two Markdown files elsewhere; `--offer FILE` reads another source). Nothing in the outputs is
typed in the code:

- the terms (name, value proposition, prices, slots, working days, payment, refund, founding terms, never list,
  scope) come from the offer file; the slots left are `slots.founding - slots.taken`, and at none the founding offer
  reads closed and only the list price is shown;
- the booking contact is the first e-mail address in the section of README.md headed "contact", read at build;
- the method's families and the report's parts come from `exonumia.sprint`, and the letter's sentence on clean trials
  is `exonumia.sprint.sentence` at `trials_for(0.03, 0.05)`;
- the example is a `kamanu assay` of the reference design on `demo/assay/proved-cell.json`, run at build and signed
  with a throwaway key; every figure stands beside its Sound and Tight levels, followed by the hypotheses.

A file that cannot be read, is not offer-v1, lacks a key, has more slots taken than slots or payment shares that do
not add to 100 exits 2 and writes nothing. The engagement letter is a draft for counsel, not legal advice.
