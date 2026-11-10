# Views reference

Five views plus one materialised view, defined in
[`../schema/003_views.sql`](../schema/003_views.sql) and
[`../schema/004_materialized.sql`](../schema/004_materialized.sql).

| View | Reads | Refresh | Contract |
|---|---|---|---|
| `v_latest_listings` | listings, pharmacies, products | live | one row per (pharmacy, url), newest scraped_at; **excludes `price_suspect` rows** |
| `v_cheapest_per_product_state` | `v_latest_listings` | live | **claims "cheapest" only when `is_comparison`**; carries both a cheapest-pack and a best-value-per-unit answer |
| `v_suspicious_listings` | latest + products + registrations | live | status ≠ Active **OR** expiry < today |
| `v_price_change_7d` | pharmacy_listings | live | current vs ≥7 days older, same url; **excludes `price_suspect`** |
| `v_pipeline_health` | scrape_runs | live | STALE after 48 h without success |
| `mv_drug_price_index` | price_history + listings + products | daily, `CONCURRENTLY` | unique on (day, canonical_name, state) |

## `price_suspect` — what it hides, and what it does not

`schema/005_suspect_prices.sql` adds `pharmacy_listings.price_suspect`, flags every stored row with
`price_ngn < 20`, and makes `v_latest_listings` exclude flagged rows. The row is **kept in
`pharmacy_listings`**; nothing is deleted or rewritten, because the table is append-only and
`v_latest_listings` takes the newest row per URL — deleting a rejected price would simply expose the
previous one.

The threshold is ₦20 because the measured data has a wide empty band: 14 rows sit below ₦11 (three at
₦1.00, eleven at ₦10.97–11.00), and the next real price is **₦50**. They are placeholders, not prices.

**Two limits remain, and one has been closed.**

1. ~~The flag decays.~~ **Closed 2026-11-08.** All three scrapers now call `common.price_bounds_error()`
   and refuse anything below ₦20 or above ₦500,000 before insert, printing an `AUDIT_REJECT` line so a
   refusal is distinguishable from a parse failure. The flag itself remains, for rows stored before
   that guard existed.
2. ~~`v_price_change_7d` is not protected.~~ **Closed 2026-11-08.** It reads `pharmacy_listings`
   directly, so it applies `not price_suspect` in both of its CTEs. Proven in a rolled-back test: a
   real-to-real pair eight days apart returns one row; a suspect *newest* row returns none; a suspect
   *prior* row returns none.
3. **`mv_drug_price_index` is not protected** — it reads `price_history`, and changing a materialised
   view means drop + create + rebuild the unique index + refresh. It is clean today only because no
   `price_history` row under ₦20 has a matched product. **Still open.**

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

### Since 2026-11-10 — stock we could not read is counted, and labelled

The view used to filter `in_stock is true`. On 2026-11-09 MedPlus rebuilt its product page, our reader
stopped finding the stock signal, and all 128 rows that run wrote carried `in_stock = null` — 108 of
which had been `true` the day before. They fell out of the view without a sound: 18 cells and two
comparisons disappeared because a parser blind spot was being expressed as "not available".

The filter is now `in_stock is not false`, so a null (unknown) row still counts, and three appended
columns say how much of the cell is confirmed:

| Column | Meaning |
|---|---|
| `cheapest_pack_stock_confirmed` | `true` when the winning row is confirmed in stock; NULL when its stock is unknown |
| `best_unit_stock_confirmed` | the same rule for the best-value row; NULL whenever the whole `best_unit_*` group is NULL |
| `confirmed_pharmacy_count` | distinct pharmacies in the cell whose stock is `true`. **0 is a real answer**, not a missing one |

Ranking now prefers a confirmed row over a cheaper unconfirmed one, because "cheapest" must not name
an item we cannot see is available. The change measured **242 → 264 cells and 42 → 45 comparisons** at
the moment it was applied; after that day's own scrape (four antimalarials went out of stock) the live
figures are 260 cells, 45 comparisons, 18 cells whose winner is unconfirmed.

`is_comparison` is unchanged (`pharmacy_count >= 2`) — a second pharmacy quoting a price is still a
second price. Read `confirmed_pharmacy_count` before calling a cell a clean comparison: 3 cells are
`is_comparison` with fewer than two confirmed pharmacies.

Known-unavailable rows (`in_stock = false`) are still excluded. A pharmacy telling us it has none is
information, not a gap.

### Since 2026-11-10 — the licence behind the price is labelled

The view named a "cheapest" and said nothing about whether the product's NAFDAC registration is allowed
to be sold. It mattered: 159 listings carry a registration that is not Active or is past its expiry, and
12 of those products still form a two-pharmacy comparison. The finding is the point of the project, so it
is labelled rather than filtered out. Two columns are appended at the end
([`../schema/008_registration_confidence.sql`](../schema/008_registration_confidence.sql)):

| Column | Meaning |
|---|---|
| `registration_status` | the raw `nafdac_registrations.status` for the product's registration. **NULL when the product has no registration number, or when no status was ever read** |
| `registration_flagged` | `true` only where a status was read **and** (`status <> 'Active'` or `expiry_date < current_date`) — the same condition `v_suspicious_listings` uses. Never NULL |

Read them together. Three states, and a reader must be able to tell them apart:

| `registration_status` | `registration_flagged` | Label to render | Count in the 260 cells (2026-11-10) |
|---|---|---|---|
| `'Active'`, not expired | `false` | `active` | 142 |
| not Active, or expired | `true` | `not active` | 70 |
| NULL | `false` | `not read` | 48 |

**`registration_flagged = false` does not mean the licence is active.** It means "not flagged", which is
true both for a licence we read and found active and for one we never read at all — 48 of the 190
unflagged cells are in the second group. Rendering the boolean alone would print those 48 as "no" and
call a medicine unregistered because our scraper never fetched its record, which is the same error as
calling an unread shelf empty. The dashboard shows `active` / `not active` / `not read` from both
columns and never a blank.

Nothing about the ranking, the row set or `is_comparison` changed: 260 cells and 45 comparisons before
and after, and all 23 pre-existing columns return identical values against an independent recomputation
of the previous definition. `mv_drug_price_index` is deliberately untouched — it aggregates a
product-day-state market figure and names no winner, so it has no "cheapest" claim to disclaim.

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
