# T5 report ΓÇö suspect prices are flagged, not deleted

**Written by the secretary.** The agent hit its step cap after applying the SQL and running all seven
gates, but before updating `docs/views.md` and writing this file. The doc has been updated; every figure
below was re-run by the secretary.

## Answer

A `price_suspect` flag now exists on `pharmacy_listings`, 14 stored rows carry it, and
`v_latest_listings` excludes them. **Nothing was deleted and no price was rewritten** ΓÇö all 14 rows
are still in the table.

| Gate | Value |
|---|---|
| Column | `price_suspect boolean NOT NULL DEFAULT false` |
| Flag split | `false` 3,807 / **`true` 14** |
| Stored rows under Γéª20 | 14 (three at exactly Γéª1.00) ΓÇö still there |
| `v_latest_listings` | 2,613 ΓåÆ **2,599** (delta 14) |
| Lowest price in `v_latest_listings` | **Γéª50.00**, and **0** rows under Γéª20 |
| `v_cheapest_per_product_state` | **115 rows, 24 comparisons** ΓÇö unchanged |
| `mv_drug_price_index` | 135 rows, min `min_price_ngn` **Γéª140.00** ΓÇö untouched |
| Idempotence | applied three times; runs 2 and 3 both reported `UPDATE 0` |

**Correction to the brief: 14 rows, not 15.** The brief said "twelve more" at Γéª10.97ΓÇô11.00; the real
count is eleven. So the delta is 2,613 ΓåÆ 2,599, not 2,598.

## Four findings the brief did not cover

1. **The flag decays ΓÇö this is the important one.** `price_suspect` defaults to `false`, so a future
   Γéª1 listing is written *unflagged* and appears in the views until `005` is re-run. T5 fixes the rows
   already stored; it does not fix the next scrape. Build-time rejection in the scrapers is the durable
   fix and is not built.
2. **`v_price_change_7d` is unprotected.** Confirmed by reading `schema/003_views.sql`: its `latest` CTE
   selects `from pharmacy_listings l` directly, not from `v_latest_listings`. It returns 0 rows today,
   which hides the problem; once it returns rows a suspect price could pair with a real one.
3. **`mv_drug_price_index` is unprotected**, as designed for this ticket. It stays clean only because
   **0** `price_history` rows under Γéª20 have a matched product.
4. **`healthplus.py:304` rejects only `price <= 0` on the insert path.** The `ABSURD_PRICE_NGN`
   upper bound is computed at `:509` for the **report only** and never enforced before insert, so a
   Γéª900,000 typo would be stored. `PROGRESS.md` describes the zero-price rejection as fixed ΓÇö true ΓÇö
   but the upper bound has never been enforced.

## Deviation from the brief

The brief said 15 rows; the truth is 14. The agent caught it and reported it rather than adjusting the
number to match. That is the behaviour the brief asked for.

## Unproven

- Whether a future Γéª1 row is caught: it is **not**, until the scraper guard exists or `005` is re-run.
- Whether `v_price_change_7d` behaves once it returns rows.
- No guarantee for the materialised view beyond today's clean state.
