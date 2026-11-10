-- 007_index_stock_confidence.sql
-- Stop "we could not read the stock level" from being published, in the daily price index, as
-- "out of stock".
--
-- THE DEFECT (found by the independent audit T17 and confirmed here, 2026-11-10).
-- mv_drug_price_index (schema/004_materialized.sql:17) computed
--
--     avg(case when h.in_stock then 1.0 else 0.0 end)::numeric(5, 4) as stock_rate
--
-- `in_stock` has THREE states, not two (schema/006_stock_confidence.sql:5-8): true, false, and NULL,
-- where NULL means the reader found no stock signal on the page at all. A two-branch CASE routes NULL
-- into the ELSE branch, so every unreadable row was averaged in as 0.0. A parser blind spot was
-- therefore published as a market fact: "nothing was in stock that day".
--
-- HOW IT FIRED. On 2026-11-09 MedPlus changed its product-page markup and the reader stopped finding
-- the only stock signal the site exposes. That run wrote 128 rows with in_stock = null, 108 of which
-- had been true the day before. Those 128 rows entered this index as zeros.
--
-- BEFORE (measured 2026-11-10, PG 17.11, pinned interpreter, scripts/dbq.py):
--
--   select count(*), count(*) filter (where stock_rate is null), min(stock_rate), max(stock_rate)
--   from mv_drug_price_index;
--   ->  403 | 0 | 0.0000 | 1.0000
--
--   Grouped by day the same table held no NULL at all: 2026-11-07 n=209 avg 0.5692, 2026-11-08 n=131
--   avg 0.8466, 2026-11-09 n=63 avg 0.4167. Nothing in that column distinguished a measured zero from
--   a row we never read.
--
--   The same underlying rows, counted at the source instead of through the broken average:
--
--   | day        | groups | entirely unreadable | partly unreadable | unknown price rows / all |
--   |------------|--------|---------------------|-------------------|--------------------------|
--   | 2026-11-07 |   209  |          0          |         0         |       0 / 750            |
--   | 2026-11-08 |   131  |          2          |         3         |       3 / 179            |
--   | 2026-11-09 |    63  |         21          |        23         |      29 /  73            |
--
--   21 groups on 2026-11-09 had NO readable stock signal at all. Each of them was published as a
--   0% stock day. That is the population this file turns into NULL.
--
-- THE FIX, both halves. `stock_rate` is now computed over rows we could read, and the denominator is
-- published beside it:
--
--   stock_rate       avg over non-NULL readings only:
--                    avg(case when h.in_stock is true then 1.0
--                             when h.in_stock is false then 0.0 end)
--                    -> NULL (not 0) on a day where nothing was readable, because avg() ignores NULL
--                       inputs and returns NULL when every input is NULL. No coalesce anywhere.
--   stock_read_rate  share of that day's rows whose in_stock is not null: the fraction of the group the
--                    rate above is actually based on. Cast numeric(5, 4) like its sibling.
--
-- A reader can now tell the three cases apart in one row: stock_rate NULL means we read nothing;
-- stock_rate 0.0 with stock_read_rate 1.0 means everything we read was out of stock; a high rate with
-- a low stock_read_rate means the number rests on a thin sample of the group.
--
-- WHY NULL SURVIVES HERE AND WHY THAT IS CORRECT. The alternative was to exclude unreadable rows from
-- the group entirely, which hides that anything went missing — the same substitution one layer down.
-- schema/003_views.sql:63-66 states the rule this file applies: a NULL means "not known", and a
-- substituted answer is a lie. Zero is an answer about the shop; NULL is an answer about our reading of
-- the shop. Only the second one is true when the parser found nothing.
--
-- AFTER (measured immediately after applying this file, same query, same session):
--
--   count 403 | count(stock_rate is null) 23 | min(stock_rate) 0.0000 | max(stock_rate) 1.0000
--
--   Per day, with both formulas computed from price_history on the same rows in one query:
--
--   | day        | groups | stock_rate NULL | avg before | avg after | groups whose rate moved |
--   |------------|--------|-----------------|------------|-----------|-------------------------|
--   | 2026-11-07 |   209  |        0        |   0.5692   |   0.5692  |            0            |
--   | 2026-11-08 |   131  |        2        |   0.8466   |   0.8636  |            3            |
--   | 2026-11-09 |    63  |       21        |   0.4167   |   0.6548  |           23            |
--
--   The 23 NULL rows are exactly the 23 groups the source count above called entirely unreadable
--   (2 + 21), so the view and the ledger agree. The row count is unchanged at 403: nothing was dropped,
--   only the arithmetic changed. 2026-11-09 moved most, +0.2381, because 29 unreadable rows had been
--   pulling its average down and the 21 fully unread groups are now NULL instead of 0.0000. 2026-11-07,
--   where every row was readable, is unchanged to four decimals — that is the control, and it is the
--   check that says this file changed the unread rows and nothing else. Do not quote these numbers
--   without re-running the query: the pipeline moves nightly.
--
-- A CONSUMER WEIGHTING OR SUMMING stock_rate ACROSS DAYS MUST SKIP NULLS. `avg(stock_rate)`,
-- `sum(stock_rate) / count(*)`, and most BI tools' default "average of a column" all do the exact
-- substitution this file removes: they either drop the NULL (silently changing the denominator) or
-- coalesce it to zero (restoring the bug). Write `avg(stock_rate) filter (where stock_rate is not null)`
-- and report the count of NULL days beside it. A trend built from this column without that filter is
-- not a trend, it is a parser-uptime series wearing a price label.
--
-- COLUMN CONTRACT. The eight existing columns keep their name, order and type; exactly ONE is appended
-- AT THE END (Postgres allows appending to a materialised view's select list; it does not allow a rename
-- or a reorder):
--
--   day, canonical_name, state, avg_price_ngn, min_price_ngn, max_price_ngn, pharmacy_count,
--   stock_rate,
--   stock_read_rate   numeric(5, 4)
--
-- dashboard/app.py selects these by name, so appending does not break it. Anything doing `select *` and
-- counting columns must be re-read; nothing in this repo does.
--
-- WHY DROP + CREATE RATHER THAN `create or replace`. A materialised view cannot be replaced in place;
-- changing its definition requires a drop. That is unsafe done statement by statement: between the drop
-- and the recreated unique index there is a window in which `refresh materialized view concurrently`
-- fails and the dashboard's Price index tab is empty. Postgres DDL is transactional, so the whole file
-- runs inside one `begin`/`commit`: if the create or the index fails, the drop is rolled back and the
-- previous definition — populated, indexed, correct for what it said — is still there.
--
-- THE UNIQUE INDEX IS NOT OPTIONAL (schema/004_materialized.sql:5-6): `refresh ... concurrently` raises
-- "cannot refresh materialized view concurrently" without it. The nightly job
-- (.github/workflows/daily.yml) refreshes this view, so a committed state without the index would break
-- the pipeline every night, silently from the job's point of view. It is recreated below, in the same
-- transaction, on the same columns as before.
--
-- NOT COVERED HERE, deliberately:
--   * price_suspect is still not filtered. mv_drug_price_index reads price_history, not
--     v_latest_listings, so schema/005's flag does not protect it. Known, separate ticket; adding that
--     filter would change every price column in the same file as a stock fix, which makes the
--     measurement unattributable.
--   * The MedPlus parser is not fixed here. Until it is, MedPlus cells keep reporting what was readable
--     and the NULLs keep saying so. That is the honest rendering, not a fix.
--   * The index remains an index of *newly observed* prices per day, not of the live market
--     (PROGRESS.md, 2026-11-09). This file changes nothing about that; it only stops the stock column
--     from inventing a reading.
--   * Nothing is backfilled. `price_history` is the observation ledger and is not rewritten; the view is
--     recomputed from it, which is the whole reason the defect is repairable at all.

begin;

drop materialized view if exists mv_drug_price_index;

create materialized view mv_drug_price_index as
select
    (h.recorded_at at time zone 'Africa/Lagos')::date as day,
    p.canonical_name,
    ph.state,
    avg(h.price_ngn)::numeric(12, 2)                        as avg_price_ngn,
    min(h.price_ngn)::numeric(12, 2)                        as min_price_ngn,
    max(h.price_ngn)::numeric(12, 2)                        as max_price_ngn,
    count(distinct l.pharmacy_id)                           as pharmacy_count,
    -- 2026-11-10: both branches test explicitly, so a NULL reading contributes to neither side of the
    -- average and a group with nothing readable yields NULL instead of 0.0. Do not rewrite this as
    -- `case when in_stock then 1.0 else 0.0 end`: that is the defect this file exists to remove.
    avg(case when h.in_stock is true then 1.0
             when h.in_stock is false then 0.0 end)::numeric(5, 4) as stock_rate,
    -- The denominator, in the same row: share of the group we could actually read.
    avg(case when h.in_stock is not null then 1.0 else 0.0 end)::numeric(5, 4) as stock_read_rate
from price_history h
join pharmacy_listings l on l.id = h.listing_id
join pharmacies        ph on ph.id = l.pharmacy_id   -- state lives here, not on the listing
join products           p on p.id = l.product_id
where p.canonical_name is not null
group by 1, 2, 3;

create unique index mv_drug_price_index_day_product_state_idx
    on mv_drug_price_index (day, canonical_name, state);

commit;

comment on materialized view mv_drug_price_index is
    'Average, minimum and maximum price per Lagos-local day, canonical product and state, from prices '
    'newly observed that day (price_history), not from the live market. stock_rate is averaged over rows '
    'whose stock reading is known; it is NULL when nothing in the group was readable, never 0 for an '
    'unread group. stock_read_rate is the share of the group that was readable. A consumer aggregating '
    'stock_rate across days must skip NULLs and report how many days it skipped. Defined in '
    'schema/007_index_stock_confidence.sql, which supersedes schema/004_materialized.sql.';

comment on column mv_drug_price_index.stock_rate is
    'Share of this day/product/state group observed in stock, averaged over readable rows only. NULL '
    'means no row in the group carried a stock reading at all - it does NOT mean out of stock. Read '
    'stock_read_rate for how much of the group this rate is based on.';

comment on column mv_drug_price_index.stock_read_rate is
    'Share of this group whose in_stock was not NULL, i.e. the fraction of the rate we could actually '
    'read. 1.0000 means every row contributed a stock reading; 0.0000 means stock_rate is NULL.';
