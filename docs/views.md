# Views reference

Five views plus one materialised view, defined in
[`../schema/003_views.sql`](../schema/003_views.sql) and
[`../schema/004_materialized.sql`](../schema/004_materialized.sql).

| View | Reads | Refresh | Contract |
|---|---|---|---|
| `v_latest_listings` | listings, pharmacies, products | live | one row per (pharmacy, url), newest scraped_at |
| `v_cheapest_per_product_state` | `v_latest_listings` | live | **claims "cheapest" only when `is_comparison`** |
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
