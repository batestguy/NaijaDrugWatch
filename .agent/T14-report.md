# T14 report — stock unknown now counts (and is labelled), it does not mean unavailable

Vintage/state: nothing frozen touched; one view redefined in the live Neon database
(`orange-pond-32200905`, PG 17.11). Nothing committed — tree left dirty for the secretary.

## Changed

| Path | Lines | What |
|---|---|---|
| `schema/006_stock_confidence.sql` | **new, 232 lines** | Header comment `:1-82` (defect, three-way measurement, why 003 is not edited, why unknown ranks below confirmed, column contract). `begin;` `:87`. Base filter `where l.in_stock is not false` `:104`, carries `l.in_stock` `:100`. `confirmed_pharmacy_counts` CTE `:118-127`. Stock-first ordering in `ranked_pack` `:139` and `ranked_unit` `:152`. 20 unchanged columns `:158-185`, then the three appended `:190`, `:193-194`, `:196`. `left join confirmed_pharmacy_counts` `:206-208`. Comments on view + 3 columns `:212-231`. `commit;` `:232`. |
| `.agent/T14-progress.md` | appended | 5 progress lines. |
| `.agent/T14-report.md` | new | This file. |

Nothing else was written. `git status --short` → `?? schema/006_stock_confidence.sql` (only).

## Verified

All from the live database, pinned interpreter `.venv\Scripts\python.exe -X utf8`, `DATABASE_URL` from `.env`.

**Before (the defect, reproduced and re-measured today):**

```
pg PostgreSQL 17.11 (9045acd) on aarch64-un
BEFORE_cells 242   BEFORE_cmp 42
susp 160   mv 403   latest 2792
stock_null 141   stock_true 1882   stock_false 769
```

Three base filters over the same data, my own query (not the brief's numbers copied):

```
true       (242, 42)
not_false  (264, 45)
ignored    (346, 73)
null_by_ph [('MedPlus', 141)]
```

So the old filter hid 22 cells and 3 comparisons, and every unreadable stock row is MedPlus.

**After applying (single transaction, the file's own `begin; … commit;`):**

```
cells 264
cmp 45
pack_unconfirmed 22
unit_unconfirmed 88
zero_confirmed_cells 22
cmp_but_zero_confirmed 0
susp 160
mv 403
latest 2792
```

264 and 45 match the brief exactly. `v_suspicious_listings` (160) and `mv_drug_price_index` (403)
are **unchanged** by this ticket, as predicted: neither reads this view — `v_suspicious_listings`
reads `v_latest_listings` (`schema/003_views.sql:187`) and `004_materialized.sql` contains no
reference to `v_cheapest_per_product_state` (grep, 0 hits). Their values differ from `PROGRESS.md`
(132 / 340) because a scrape landed after that file was written, not because of this change.

**Column list — 23 columns, the three new ones last, all 20 old ones unchanged:**

```
1 product_id :: bigint          11 cheapest_pack_price :: numeric(12,2)      21 cheapest_pack_stock_confirmed :: boolean
2 canonical_name :: text        12 cheapest_pack_pack_size :: integer        22 best_unit_stock_confirmed :: boolean
3 state :: text                 13 cheapest_pack_pharmacy_id :: bigint      23 confirmed_pharmacy_count :: bigint
4 cheapest_pharmacy_id :: bigint 14 cheapest_pack_pharmacy :: text
5 cheapest_pharmacy :: text     15 cheapest_pack_url :: text
6 price_ngn :: numeric(12,2)    16 best_unit_unit_price :: numeric
7 unit_price :: numeric(12,4)   17 best_unit_pack_size :: integer
8 url :: text                   18 best_unit_pharmacy_id :: bigint
9 pharmacy_count :: bigint      19 best_unit_pharmacy :: text
10 is_comparison :: boolean     20 best_unit_url :: text
```

**Behavioural checks (`A`–`F`), all on the live view:**

```
A false_flags 0                     -- no FALSE anywhere: TRUE or NULL only
B null_vs_zero_mismatch 0           -- pack_stock_confirmed is null  <=>  confirmed_pharmacy_count = 0
C unit_nullrule_leak 0              -- best_unit_* group still all-NULL together
D demoted_cells 4                   -- cells where a cheaper unconfirmed row lost to a pricey confirmed one
E old_cells_price_changed 0         -- of the 242 previously visible cells, ZERO changed headline price
F confirmed_dist [(0, 22), (1, 200), (2, 42)]
```

`E` is the important one: the new ordering added 22 cells and moved no existing price. `242` cells
carry `cheapest_pack_stock_confirmed = true`, exactly the old cell count.

The rule does bite where it should — 4 cells now name a pricier confirmed row over a cheap
unreadable one:

```
('Flotac 75 mg Capsules',  'Lagos', 'HealthPlus', 15410.00, True, 1, 2, cell_min 14000.00)
('Ibuprofen',              'Lagos', 'MedPlus',      650.00, True, 2, 2, cell_min   350.00)
('Lyrica 150 mg Capsules', 'Lagos', 'HealthPlus', 34680.00, True, 1, 2, cell_min 32200.00)
('Sirdalud Tablet 4 mg',   'Lagos', 'MedPlus',    25900.00, True, 1, 1, cell_min 11900.00)
```

**Ranking keys actually stored** (`pg_get_viewdef`), both answer groups identical in the first key:

```
row_number() OVER (PARTITION BY b.product_id, b.state ORDER BY | CASE | WHEN (b.in_stock IS TRUE) THEN 0 …
```

**Idempotent:** the file was applied three times in total (1 + 2 re-runs) —

```
RERUN_TWICE cells 264 cmp 45 unconf 22 cols 23
```

`best_unit_stock_confirmed is null` = 88 = 72 (whole `best_unit_*` group NULL, unchanged rule)
+ 16 (unit price known, that row's stock unreadable).

**Consumer check:** `dashboard/app.py:238-243` selects an explicit column list
(`canonical_name, state, cheapest_pharmacy, cheapest_pack_price, unit_price, best_unit_unit_price,
best_unit_pharmacy, pharmacy_count, is_comparison`) — by name, so appending three columns cannot
move or break it. Nothing in the repo does `select *` on this view.

## Deviations

1. **`confirmed_pharmacy_count` is `bigint`, not `integer`.** `count()` returns bigint and the sibling
   `pharmacy_count` is bigint, so the natural expression was bigint. I tried the spec's type
   afterwards and Postgres refused it:

   ```
   psycopg.errors.InvalidTableDefinition: cannot change data type of view column
   "confirmed_pharmacy_count" from bigint to integer
   ```

   (tested as the file with `::int` inserted and `commit` swapped for `rollback`, so the live view is
   untouched by the attempt). Getting `integer` now needs a drop and recreate, which the brief
   forbids and which would break the dashboard's tab for the duration. Left as bigint. Same values,
   same meaning, one type name apart from the brief.

2. **Stock-ignored cells are 346 / 73, not 346 / 74.** I re-measured rather than copying the brief;
   my count of cells with `count(distinct pharmacy_id) >= 2` under no stock filter gives 73. The file
   and this report state the number I measured.

3. **`docs/views.md` still documents the old contract** — it does not mention the new filter or the
   three columns. Not edited: the ticket's write list excludes it. One-line follow-up.

## Left alone (found, not fixed)

- `dashboard/app.py` does not select the three new columns, so the app still shows no availability
  caveat. The caveat exists in the view and has not reached the only screen a reader sees.
- `PROGRESS.md` still carries 242/42-class figures and does not record this change.
- The MedPlus reader is still broken — 141 latest rows with `in_stock` NULL, 0 from any other source.
  Fixing the parser is a separate ticket and is what makes those 22 cells confirmed again.

## Unproven

- **Whether the 22 unconfirmed cells are genuinely available.** The view now says "we could not read
  the stock", which is true; it does not say the pack is on the shelf. No page was opened by a human.
- **The 45 comparisons are still not eyeballed**, and this change adds 3 to that unchecked set. The
  three new ones are single-confirmed-stock cells (`confirmed_pharmacy_count = 1` of 2), so they are
  the weakest comparisons in the table.
- **In a mixed cell the cheaper unconfirmed price is still not the headline** (4 cells above) — that
  is the specified rule, but the cheaper observation is now visible only in `v_latest_listings`, not
  anywhere an app user looks.
- **Nothing was tested in a browser**, because no UI changed.
