# Pre-registration — the 20 + 20 human check

Written **2026-11-14, before any card has been judged.** Its purpose is to make the number this check
produces publishable, by fixing the sampling rule, the scoring rule and the reporting rule before anyone
has seen a result. If any of the three is changed after a verdict exists, the change and the reason are
published beside the result.

Author of this document: the secretary. The rule is the user's to veto until the first card is ticked.

## What each list actually measures — precision, not prevalence

Neither list is a sample of all pharmacy prices. Both are samples of **our own claims**, so what they
measure is how often a claim we already make survives a human reading the real page.

| list | population | the claim being tested |
|---|---|---|
| Licence | one item per **product** that `v_suspicious_listings` flags — its NAFDAC registration is not Active, or the expiry has passed | that this product really does rest on a lapsed or inactive registration |
| Pack | one item per `v_cheapest_per_product_state` cell with `is_comparison` — two different pharmacies publish a price for the same product | that the two shops really are pricing the same pack of the same medicine |

Consequence, to be stated wherever the result is published: **"of the flagged findings we checked, N were
right"** — never "N% of Nigerian drug prices are wrong", and never "N% of listings". A precision check
cannot answer a prevalence question and must not be written up as one.

## Sampling

1. **Size.** 20 licence items and 20 pack items. Not 19, not 25, not "as many as fit".
2. **Method.** Simple random sample without replacement, drawn separately from each list, by a seeded
   generator. The seed is recorded. No stratification, no judgement, no convenience selection, no
   "pick a few interesting ones".
3. **Fixed before judging.** The chosen item ids and the seed are written to
   `.agent/verify-sample-2026-11-14.json` at build time, so the selection exists as an artifact before
   any verdict does. The page marks exactly those items, and the full list stays reachable underneath.
4. **No substitution.** If a chosen card cannot be judged, it stays in the sample and is recorded as
   *cannot tell*. A card is never swapped out for a friendlier one.
5. **No redrawing.** The sample is not drawn again after a result is seen. If it ever is, both samples
   and the reason are published.

## Scoring

Each card is a fixed list of questions (five for licence, six for pack) answered Pass / Fail / Cannot
tell, with nothing pre-selected. Where the question shows an answer computed from our own rows, it is
labelled as such and the reader still confirms it by eye.

The card's outcome is computed from its own ticks and is never asked for separately:

- any Fail → the card **fails**
- every question Pass → the card **passes**
- otherwise → **cannot tell**

## Reporting

Published for each list, as a sentence and a table:

- the count that passed, the count that failed, the count that could not be told;
- **the denominator is 20 minus the cannot-tell count**, and both numbers are stated;
- a **95% Wilson interval** beside each proportion, because 20 is small and the interval is most of the
  story. With 20 judged and 0 failures the upper bound is still about 16%, and that will be printed
  rather than left for a reader to assume otherwise;
- the seed and the sample file path, so a stranger can re-draw the same twenty.

## What makes this a real check rather than a formality

If most cards fail, the result is that **our own screens are unreliable**, and it is published in the
same words and the same place as a good result would be. The check is not allowed to be abandoned
because it went badly.
