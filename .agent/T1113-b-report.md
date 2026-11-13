# T1113-b report - the strength guard, and the repair it justified

**Written by the secretary on 2026-11-13.** The builder reached its 25-step cap with the work done and
the database changed, but no report file and no progress lines. This is its account, re-checked
against the database by me. Sections marked **[secretary]** are my own verification.

## What the guard does

A listing may not be attached to a product whose stated strength it contradicts. The rule compares
the mass strength in the listing's own title with the mass strength of the product: mg, mcg, g, iu
and percent, with grams and micrograms converted to milligrams so `1 g` equals `1000 mg`. Millilitres
are ignored, because in these titles they are bottle or pack volume far more often than strength. A
title that states no strength is attached exactly as before, because silence is not a contradiction.
The parser is `strength_tokens` from `scripts/link_product_nrn.py`, reused, not duplicated.

## The repair, and what it cost

The builder ran the repair pass once, as the brief authorised. It found **54 listings** across **22
products** whose title contradicted the product they were attached to, and cleared that link on all
54. Nothing was deleted. No price was rewritten. No materialised view was refreshed.

| measure | before | after |
|---|---|---|
| matched listings (latest) | 580 | **552** |
| matched rows including history | 1,031 | 977 |
| price cells | 262 | **258** |
| two-shop comparison cells | 45 | **43** |

**[secretary] Verified by my own queries, not taken on report:** `v_latest_listings` 2,793 with 552
matched; `v_cheapest_per_product_state` 258 cells and **43** comparisons.

**[secretary] Verified the outcome:** the strict contradiction check re-run over every matched listing
returns **0 contradictions**. Before the repair it returned 27 by the conservative rule; the guard's
own rule found 54, because it also catches cases the conservative check had classified as a total
versus a component list. All matched listings that state a strength now agree with their product.

## Proof the guard refuses without writing

Over every currently unattached listing, with no write at all, the matcher refused **57** would-be
attachments. All 57 were read: `ACICLOVIR 800MG` under a 400 mg product, `Cataflam 50mg` under 100 mg,
`Chloramphenicol Eye Ointment 5g` under 1 g, and the two-ingredient brands the brief worried about,
`Co-Diovan`, `Douodart`, `Glucovance`, `Exforge HCT`, under one-ingredient products.

**The brief's main worry did not materialise.** It said a two-ingredient brand under a one-ingredient
product might slip through because the numbers happen to be present. It does not: the comparison is
exact, not a shares-a-number test.

## Deviations

- Report and progress lines not written by the builder. This file is the secretary's.
- **28 matched listings were lost, not the 27 predicted.** The extra one is a true positive, not
  collateral: the guard's rule is slightly wider than the conservative check used to size the job.
- The two-verdict side-by-side demonstration (a contradicting title refused, an agreeing title
  attached) was prepared as a scratch script and never run. The 57 measured refusals plus the repair's
  effect are the equivalent evidence.

## Open risks - what a reviewer should attack first

1. **`Augmentin 1g Tabs` is now refused against the `875mg+125mg` product.** 1,000 mg is the sum of
   the two ingredients, so it is arguably the same tablet. This is 1 title, 2 of the 57 refusals. It
   is a real cost of an exact rule, and the fix is a "sum of the parts" clause, not a looser rule.
2. **The price index was not refreshed, by instruction.** Clearing old history rows leaves
   `mv_drug_price_index` still counting them until the next nightly run. The index is a stored summary,
   so the page's index figure is stale relative to the repair.
3. **The nightly matcher will now print about 57 refusals every night.** That is the guard working,
   but it is noise a human must learn to read as normal rather than as a fault.
4. **The guard trusts the product's strength column.** If a product's own strength is wrong, the
   guard defends the wrong answer consistently.

## Unproven

- Whether the 54 cleared listings were *all* genuinely wrong. They were cleared on a rule, not read by
  a person. The rule is defensible; the rows are not individually audited.
- Whether any of the 28 lost matches would have been useful to a reader despite contradicting strength.
- The two-ingredient coverage beyond the five brands named here.

## Files

`scripts/match_listings.py` - the guard and the `--repair` mode. Uncommitted until this report's
commit. `.agent/strength-contradictions-2026-11-12.json` - the 27-row worklist from the conservative
check, kept as the record of what was found before the repair, **not** overwritten by the re-run.
