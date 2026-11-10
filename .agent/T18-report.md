# T18 report — does any published stock number still count "unreadable" as "not in stock"?

**Answer after this ticket:** no, not in the two places the audit named. The daily price index now
publishes NULL for a group it could not read, with the readable share beside it. The dashboard's
"Price index" and "Cheapest by state" tabs both name the unreadable case instead of printing a zero.

Not covered, and still true: `price_suspect` filtering, the MedPlus parser, and the fact that the index
counts *newly observed* prices per day rather than the live market. Those are three separate open items
in `PROGRESS.md`, deliberately untouched (brief, "Do not touch" and "NOT COVERED").

## Changed

`schema/007_index_stock_confidence.sql` (new, 172 lines)

- `:1-39` header: the defect (`004:17`'s two-branch CASE), how it fired on 2026-11-09, before-measurement,
  and the per-day source count of entirely/partly unreadable groups.
- `:41-53` the fix, both halves, and why NULL rather than exclusion.
- `:55-72` **after**-measurement as a per-day before/after table, and the control day.
- `:74-79` the consumer rule: `avg(stock_rate)` across days must skip NULLs, with the clause to write.
- `:81-123` column contract, why drop+create, why the unique index is mandatory and recreated in the
  same transaction, and what is not covered.
- `:125-127` `begin;` then `drop materialized view if exists mv_drug_price_index;`.
- `:129-149` the new definition: `stock_rate` at `:141-142` = `avg(case when h.in_stock is true then 1.0
  when h.in_stock is false then 0.0 end)::numeric(5,4)`; the eight old columns unchanged in name, order
  and type; `stock_read_rate` at `:144` appended ninth as `numeric(5,4)`.
- `:152-155` `create unique index mv_drug_price_index_day_product_state_idx on (day, canonical_name,
  state);` then `commit;`.
- `:157-171` `comment on materialized view` plus column comments on `stock_rate` and `stock_read_rate`,
  so the NULL-means-unread contract travels with the object and not only with the repo.

`dashboard/app.py` (modified, +18 −4)

- `:201-209` Price index caption: the rate counts only readable prices, an unreadable one is left out
  rather than counted as out of stock, and a blank rate means nothing was readable that day.
- `:211-212` select gains `stock_read_rate`.
- `:231-232` labels: `"stock_rate": "In stock (of readable)"` (was `"In stock"`), and
  `"stock_read_rate": "Rows with a stock reading"`.
- `:155-161` `cheapest_table()` gains `Stock confirmed` (`yes` / `not read`, never a silent zero) and
  `Confirmed pharmacies`, so both the comparison and single-pharmacy tables carry them.
- `:249-252` Cheapest caption: a comparison whose `Confirmed pharmacies` is below two includes a price
  from a shop whose stock we could not read — the price is real, the availability is not confirmed.
- `:255-257` select gains `cheapest_pack_stock_confirmed` and `confirmed_pharmacy_count`.

`.agent/T18-progress.md` — four lines, appended as the work proceeded.

Untouched, as instructed: `schema/004_materialized.sql`, `schema/006_stock_confidence.sql`,
`v_cheapest_per_product_state`'s definition, `is_comparison`, every scraper,
`.github/workflows/daily.yml`. `git status --short` shows only `M dashboard/app.py` and
`?? schema/007_index_stock_confidence.sql` — nothing was committed.

## Verified

**1. Before (captured first, unmodified view).**

```
.venv\Scripts\python.exe -X utf8 scripts/dbq.py "select count(*), count(*) filter (where stock_rate is null), min(stock_rate), max(stock_rate) from mv_drug_price_index"
count	count	min	max
403	0	0.0000	1.0000
```

Per day: `2026-11-07 n=209 avg 0.5692 | 2026-11-08 n=131 avg 0.8466 | 2026-11-09 n=63 avg 0.4167`, no
NULL anywhere. The source rows behind those groups: 2026-11-07 0 unreadable; 2026-11-08 3 unreadable
(2 groups entirely); 2026-11-09 29 unreadable (21 groups entirely of 63).

**2. After, same query.**

```
count	count	min	max
403	23	0.0000	1.0000
```

Row count unchanged at 403. 23 NULL rows = 2 + 21, exactly the groups the source count called entirely
unreadable. Min stays 0.0000 because genuine `false` readings still exist and still average to zero.

Per day, both formulas computed on the same rows in one query (old = two-branch CASE, new = this file):

```
day	groups	null_now	avg_old	avg_new	changed
2026-11-07	209	0	0.5692	0.5692	0
2026-11-08	131	2	0.8466	0.8636	3
2026-11-09	63	21	0.4167	0.6548	23
```

**3. Column list of the rebuilt view** (`pg_attribute`, since `information_schema` omits matviews):

```
1 day date | 2 canonical_name text | 3 state text | 4 avg_price_ngn numeric(12,2)
5 min_price_ngn numeric(12,2) | 6 max_price_ngn numeric(12,2) | 7 pharmacy_count bigint
8 stock_rate numeric(5,4) | 9 stock_read_rate numeric(5,4)
```

Eight old columns identical in name, position and type; the new one is last.

**4. The index survived, and the drop is transactional.**

```
.venv\Scripts\python.exe -X utf8 <temp>\t18_apply.py
PHASE1 applied 007 as one batch
  rows: 403
  indexes: ['mv_drug_price_index_day_product_state_idx']
PHASE2 drop inside a transaction, then force a failure
  raised as designed: DivisionByZero division by zero
  after rollback, rows: 403
  after rollback, indexes: ['mv_drug_price_index_day_product_state_idx']
PHASE3 refresh concurrently
  refresh materialized view concurrently: ok
exit=0
```

Phase 2 is the check the brief asked for and it is not a claim about Postgres in general: the real
`drop materialized view if exists mv_drug_price_index` was executed inside a transaction, followed by a
deliberate `select 1/0`, and after the rollback the view was still there with 403 rows and its index.
Phase 3 then ran the exact statement the nightly job runs, successfully.

**5. Dashboard.**

```
.venv\Scripts\python.exe -m py_compile dashboard\app.py
py_compile exit=0
```

The labels are present in the file (`:204`, `:206`, `:231`, `:232`, `:249-250`, `:158`, `:161`), and both
selects were run against the live database so the column names are proven, not assumed:

```
... mv_drug_price_index ... limit 3
2026-11-07 Zoladex 3.6 mg Injection Lagos ... 1 1.0000 1.0000
2026-11-07 Bicalutamide Lagos ... 1 1.0000 1.0000
2026-11-09 Bicalutamide Lagos ... 1 1.0000 1.0000

... v_cheapest_per_product_state ... limit 3
Aciclovir Lagos MedPlus 3600.00 NULL NULL NULL 1 False True 1
Aciclovir Lagos MedPlus 4500.00 NULL 214.0000 MedPlus 1 False True 1
Aciclovir Lagos HealthPlus 14040.00 NULL 266.9643 MedPlus 2 True True 2
```

**6. Which day changed, and by how much.** 2026-11-09: day average `0.4167 → 0.6548` (+0.2381), 23 of 63
groups moved, 21 of them now NULL instead of 0.0000. 2026-11-08: `0.8466 → 0.8636` (+0.0170), 3 groups
moved, 2 now NULL. 2026-11-07: **unchanged to four decimals** — every row that day was readable, which
is the control proving the change touched the unread rows and nothing else. A group-level example of the
new NULL, which would previously have read 0.0000:

```
2026-11-08 Ivermectin 3 Tablets Lagos NULL 0.0000
2026-11-09 Allopurinol Lagos NULL 0.0000
```

## Deviations

1. **The unique index is created without `if not exists`.** The view is dropped in the same transaction,
   which drops the index with it, so the name cannot already exist; `if not exists` would have masked a
   mistake rather than been harmless.
2. **`comment on materialized view` plus two column comments were added** beyond the brief's DDL list.
   The brief requires the header to state that NULL means unread; a header is invisible to anyone
   querying the database, and 006 set the precedent of attaching the contract to the object.
3. **`cheapest_table()` was edited rather than the two call sites**, because both tables share it and
   the labels live there. The two new columns therefore appear on the single-pharmacy table as well as
   the comparison table — `Confirmed pharmacies` is 0 or 1 there, which is accurate.
4. `IN STOCK` → `In stock (of readable)` keeps the original word order so the existing screenshot-level
   reading of the tab does not change more than the brief asked.

## Left alone (found, deliberately not fixed)

- `mv_drug_price_index` still reads `price_history` directly, so `price_suspect` does not protect it
  (brief: separate known gap).
- The index is still an index of prices *newly observed* per day, not of the live market.
- MedPlus's 2026-11-09 rows still carry `in_stock = null`; the parser fix and the re-scrape are the
  nightly job's business, and this file renders them honestly in the meantime.
- `docs/views.md` describes the old `stock_rate` semantics and is now stale by one paragraph. It is
  outside the two files I was allowed to write; the next documentation ticket should carry it.
- `schema/004_materialized.sql:17` keeps the defective expression as the record of what it said;
  007 supersedes it and its header says so.

## Unproven

- **Nothing was rendered in a browser.** `py_compile` proves syntax, and the two queries were run
  against the live database, but the "Price index" tab has not been looked at: a NULL `stock_rate`
  shows as a blank cell in `st.dataframe`, and whether a reader finds a blank plus that caption clear
  enough is a judgement no test here settles. No axe/contrast run was made on the changed tabs; the
  strings are plain text in existing elements, so no new violation is expected, but that is an
  expectation, not a measurement.
- **The new `Stock confirmed` mapping was not exercised on a real frame** — the three-row query output
  shows the underlying `True`/`1` values, and the lambda is three lines, but the rendered table was not
  produced.
- **`refresh materialized view concurrently` was verified by hand, not from the workflow.** The nightly
  job's step is unchanged and the index exists at the path it expects; whether the next scheduled run
  is green is unobserved until it fires.
- The 23 NULL rows are inferred to be the 2 + 21 all-unreadable groups from a matching count, not from
  a row-by-row join of the two queries.
