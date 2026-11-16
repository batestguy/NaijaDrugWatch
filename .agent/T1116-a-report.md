# T1116-a — the 44 comparisons, machine re-read

**Written by the secretary.** The builder ran out of steps with the evidence file complete and the
report not written; the account below is its findings, and every number in it was re-checked here
against the database before it was accepted.

## What this is, and what it is not

A second read of both shop pages behind each of the 44 two-shop price comparisons, compared with the
price, pack and availability stored in the frozen 2026-11-16 vintage.

It is **not** a human verification, and it is **not** an independent parse for either shop. Both
matters are explained below rather than buried.

## Result

| shop | page reads | agree with the stored price |
|---|---|---|
| MedPlus | 44 of 44 | 44 |
| HealthPlus | 44 of 44 | 44 |

**88 page reads, 0 mismatches.** No price moved, no product was withdrawn, no page had disappeared
between the collection on 2026-11-15 12:22 UTC and the re-read.

## The channel problem, which is the honest limit of this check

- **MedPlus** was read through `data-product-price` — the same attribute the scraper reads. This
  catches drift and nothing else. MedPlus has no second server-side source; a genuinely independent
  read there needs a rendered browser.
- **HealthPlus** was meant to be read through `<product-url>.js`, the storefront JSON, which is a
  different channel from the scraper. That endpoint answered `429 local_rate_limited` on every
  attempt: at 2.5-second spacing, at 60-second spacing, and again after a ten-minute quiet period.
  One request slipped through and answered 200 before the next two were refused. The fallback was
  the `/products.json` catalogue feed — **which `scrapers/healthplus.py` itself reads**. So both
  shops were re-read from the source the scraper used.

Consequence, stated plainly: **this shows the pages have not drifted. It cannot show that our parser
read them correctly.** Nothing in the 44 comparisons has today been confirmed by a channel
independent of the scraper, and nothing has been confirmed by a person.

## Evidence that the check was not vacuous

A rotation break-test: every stored price compared against the *next* product's page price. That
produced 0 false agreements for HealthPlus and 1 for MedPlus out of 44 — so the comparison does
discriminate, rather than agreeing with anything.

## Structural findings

1. **44 comparison rows sit on 42 distinct name-and-state pairs.** "Amlodipine, Lagos" appears twice
   (5 mg 28-tablet pack at ₦950 and a 10 mg 10-strip at ₦400) and "Vitamin B Complex, Lagos" twice
   (a 100 ml syrup at ₦1,250 and a 1,000-tablet pack at ₦2,300). Two genuinely different products,
   the same name on the page, at very different prices. A reader will read the second as a price cut.
2. **18 of the 88 comparison listings carry a pack size with no unit.** Nine MedPlus rows say pack 10
   where the reality is a strip of ten; nine HealthPlus rows carry counts with no unit recorded.
3. **One published unit price is priced per millilitre.** The Vitamin B Complex syrup carries
   `pack_size` 100 with no unit, so the view computes ₦12.50 per "pack unit" — per millilitre —
   under a column headed *Price per pack unit*, immediately above a row of ₦2.30 per tablet. Of the
   30 comparison cells carrying a unit price, 26 are tablets, 3 capsules and **1 is millilitres**.

## Verified by the secretary, not taken on trust

The agent's evidence file was checked against the live database:

```
reads in the file: 88
matched to a live listing: 88 of 88 distinct urls
file says our price == page price in 88 of 88 reads
stored price differs from the database in 0 read(s)
stored pack differs from the database in 0 read(s)
product name differs in 0 read(s)
reads whose url is not a live listing: 0
```

The 44-comparisons-over-42-pairs figure was re-queried independently and matches. So does the
millilitre row (`product_id` 1037, unit price 12.5000) and the split of 26/3/1.

## Requests and blocks

About 65 of the 100 permitted, most of them spent establishing that the HealthPlus JSON endpoint was
refusing us rather than retrying blind.

## Unproven

- Whether our parsers read either shop correctly. Neither shop was read through a channel the scraper
  does not use.
- Whether the register's own records are accurate, as distinct from being faithfully copied.
- The human check. 18 of 20 licence cards and 3 of 20 pack cards are answered; the sample is not
  complete and no agent output changes that.
- Whether the two name collisions matter to a reader in practice; nobody has looked at the page with
  them in mind.
