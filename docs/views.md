# Views reference

Five views plus one materialised view, defined in
[`../schema/003_views.sql`](../schema/003_views.sql) and
[`../schema/004_materialized.sql`](../schema/004_materialized.sql).

| View | Reads | Refresh | Contract |
|---|---|---|---|
| `v_latest_listings` | listings, pharmacies, products | live | one row per (pharmacy, url), newest scraped_at |
| `v_cheapest_per_product_state` | `v_latest_listings` | live | **claims "cheapest" only when `is_comparison`**; carries both a cheapest-pack and a best-value-per-unit answer |
| `v_suspicious_listings` | latest + products + registrations | live | status ≠ Active **OR** expiry < today |
| `v_price_change_7d` | price_history | live | current vs ≥7 days older |
| `v_pipeline_health` | scrape_runs | live | STALE after 48 h without success |
| `mv_drug_price_index` | price_history + listings + products | daily, `CONCURRENTLY` | unique on (day, canonical_name, state) |

## `v_cheapest_per_product_state` — read this before using it

It returns `pharmacy_count` and `is_comparison`, and `is_comparison` is only true when **two or
more independent pharmacies** quote the product in that state.

This exists because of what the data actually contains: Drugstore.ng exposes one national price
per product, not a per-pharmacy price. Without the guard, every state would show the same
number and the dashboard would present a national price as a local comparison. A single-pharmacy
cell means "this is the national price, observed once here", not "this is the cheapest here".

Consumers must filter on `is_comparison` before labelling anything "cheapest per state".

### Two answers in one row, and why one of them can be NULL

The view originally ranked on `price_ngn` alone — lowest **sticker price** — which is not the
lowest **cost per tablet** when a product is sold in several pack sizes. Measured on the 85 cells
that existed on 2026-11-08: 15 cells had more than one pack size in stock, and in 9 of those the
chosen row was not the cheapest per unit. Ciprofloxacin, Lagos: the view chose ₦5,180 for a
10-pack (₦518.00/unit) while a 14-pack at ₦7,060 was ₦504.29/unit.

Both answers now ride in the same row, appended to the original columns:

| Group | Meaning | Ranking |
|---|---|---|
| `cheapest_pack_price`, `cheapest_pack_pack_size`, `cheapest_pack_pharmacy_id`, `cheapest_pack_pharmacy`, `cheapest_pack_url` | lowest sticker price — the pre-2026-11-08 answer, now named | `price_ngn asc, pharmacy_id asc` |
| `best_unit_unit_price`, `best_unit_pack_size`, `best_unit_pharmacy_id`, `best_unit_pharmacy`, `best_unit_url` | lowest cost per unit | `unit_price asc nulls last, price_ngn asc, pharmacy_id asc` |

The pre-existing columns (`price_ngn`, `url`, `cheapest_pharmacy`, `cheapest_pharmacy_id`,
`unit_price`, `pharmacy_count`, `is_comparison`) are unchanged and refer to the cheapest-pack row.

**`unit_price` is populated on only ~53% of HealthPlus listings. When the best-value row has no
`unit_price`, every `best_unit_*` column is NULL.** That is deliberate and it is the whole point of
the column group: a consumer seeing `best_unit_unit_price IS NULL` must render "cost per unit not
known", never the sticker price. Substituting the sticker price there would relabel "cheapest pack"
as "best value" — the same defect one layer down. 36 of the first 85 cells are NULL for this
reason.

`is_comparison` and `pharmacy_count` are not affected by either ranking: they still count distinct
pharmacies quoting the product in the state, and the best-value row may be the same pharmacy as the
cheapest-pack row (it usually is — 12 of 85 cells currently pick a different row).

## `v_suspicious_listings` — two conditions, not one

```sql
where r.status is distinct from 'Active'
   or r.expiry_date < current_date
```

Both are needed. The source data contains registrations marked `Expired` whose expiry date is
in the future, so reading either field alone under-reports. `suspicion_reason` tells you which
condition fired.

## `mv_drug_price_index`

Aggregates by **Africa/Lagos** day, canonical name and state: avg/min/max price, distinct
pharmacy count, and stock rate. Refresh it in the daily flow with
`refresh materialized view concurrently mv_drug_price_index;`.

The unique index on `(day, canonical_name, state)` is what makes `CONCURRENTLY` legal — without
it Postgres raises "cannot refresh materialized view concurrently". Do not drop it.
