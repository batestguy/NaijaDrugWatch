-- 005_suspect_prices.sql
-- Keep implausibly cheap prices out of the views, WITHOUT deleting or rewriting an observation.
--
-- THE DEFECT (measured 2026-11-08). Three MedPlus listings are priced NGN 1.00, marked in stock, on
-- ordinary products (SUPRALIP 160MG *30TAB LACER, STILBESTROL 5MG x2). The scrapers reject
-- `price <= 0` and `price > 500000`, so 1.00 passes. A 1.00 row wins every min()-based view. They do
-- not reach v_cheapest_per_product_state today only because the matcher has not matched them, and
-- the matcher decides on title similarity and never looks at price - that is luck, not design. A
-- second cluster at 10.97-11.00 (tourniquet, eyewash, emergency blanket, first-aid box, kidney dish,
-- ...) is out of stock, so `in_stock is true` already excludes it from the comparison view, but
-- nothing excludes it from v_latest_listings.
--
-- THE THRESHOLD, and why 20 is safe. Measured distribution over all 3,821 listings: 3 rows below 5.00,
-- 11 rows at 10.97-11.00, then NOTHING AT ALL until 50.00. The gap is wide enough that 20.00 cleanly
-- separates the sentinels from anything plausibly real. 14 rows are affected in total (see the
-- progress log; the brief predicted 15 and the live table holds 14).
--
-- WHY A FLAG AND NOT A DELETE. pharmacy_listings is append-only: it is the observation ledger, and
-- nafdac_status_snapshots set the precedent that history is never rewritten in place. v_latest_listings
-- takes the newest row per (pharmacy, url), so deleting a row - or rejecting the price at build time
-- and storing nothing - leaves the *previous* bad row as the newest row for that URL forever. The
-- observation is kept and marked; only the view filters it. Nothing here drops a row, truncates a
-- table, or rewrites price_ngn.
--
-- WHY THIS FILE REDEFINES A VIEW THAT 003 ALREADY DEFINES. The numbered files are applied in order,
-- and `create or replace view` is legal for an identically-shaped view, so 005 sorts after 003 and the
-- definition below wins. 003 is deliberately left as it stands: it is the record of what it said on
-- 2026-11-08, and a rebuild that runs 001 -> 005 in order lands on this definition. Do not back-port
-- this change into 003 - the two would then drift with nothing to say which is authoritative.
--
-- THE VIEW'S COLUMN LIST IS UNCHANGED: same 15 columns, same names, same order, same types. Nothing
-- that reads v_latest_listings has to change.
--
-- THE FLAG DECAYS, and that is the one weakness here. price_suspect defaults to false, so a sub-20
-- row inserted after this file runs is NOT flagged until 005 is re-run - which is cheap and safe
-- because every statement is idempotent, but it is a manual step, not a guarantee. The durable fix
-- is build-time rejection in the scrapers (separate ticket). Until then, re-run this file after any
-- scrape that adds MedPlus rows.
--
-- NOT COVERED HERE, deliberately:
--   * mv_drug_price_index reads price_history directly, not v_latest_listings, so this flag does not
--     protect it. It is clean as of 2026-11-08: min(min_price_ngn) is 140.00 and 0 price_history rows
--     under 20 have a matched product. Changing a materialised view means drop + create + rebuild the
--     unique index + refresh, and a failure in between leaves the dashboard's Price index tab broken.
--     Separate ticket.
--   * v_price_change_7d also reads pharmacy_listings directly, so it is NOT covered either. It
--     returns 0 rows until 2026-11-14, which is why it is invisible today. Recorded in docs/views.md.
--   * Build-time rejection in the scrapers. Separate ticket. This file is defence in depth for rows
--     already stored.

-- ---------------------------------------------------------------- the flag
-- `add column ... not null default false` is metadata-only on PG 11+, so this does not rewrite the
-- 3,821-row table.

alter table pharmacy_listings
    add column if not exists price_suspect boolean not null default false;

comment on column pharmacy_listings.price_suspect is
    'True when price_ngn is implausibly low and must not reach a view that ranks on price. '
    'Threshold 20 NGN, because the measured distribution has a 14-row cluster at 1.00-11.00 and then '
    'nothing until 50.00 (all 3,821 listings, 2026-11-08), so 20 separates the sentinels from '
    'anything plausibly real. The row is kept, not deleted: pharmacy_listings is append-only and '
    'v_latest_listings takes the newest row per URL, so discarding a price would leave the previous '
    'bad row as the latest forever. Set by schema/005_suspect_prices.sql, which must be re-run after '
    'a scrape that inserts new rows; build-time rejection in the scrapers is the durable fix.';

-- ------------------------------------------------------------- the backfill
-- Existing rows only. No history is rewritten: price_ngn, in_stock and every other column keep their
-- values, and the predicate is false for rows already flagged, so a re-run updates 0 rows.
-- price_ngn is nullable and NULL < 20 is NULL, so an unpriced listing is never flagged.

update pharmacy_listings set price_suspect = true
 where price_ngn < 20 and price_suspect = false;

-- ------------------------------------------------------- v_latest_listings
-- Identical to schema/003_views.sql:10-39 except for the last predicate. rn = 1 is still computed
-- over every stored row, so a URL whose newest observation is suspect drops out of the view entirely
-- rather than silently falling back to an older, stale price. Falling back would present a stale
-- number as the current one; a missing row says "we have no trustworthy current price", which is
-- what the project's NULL-means-unknown rule asks for.

create or replace view v_latest_listings as
with ranked as (
    select
        pl.*,
        row_number() over (
            partition by pl.pharmacy_id, pl.url
            order by pl.scraped_at desc, pl.id desc
        ) as rn
    from pharmacy_listings pl
)
select
    r.id                as listing_id,
    r.pharmacy_id,
    ph.name             as pharmacy_name,
    ph.state,
    ph.city,
    r.product_id,
    p.canonical_name,
    r.raw_title,
    r.url,
    r.price_ngn,
    r.in_stock,
    r.pack_size,
    r.pack_unit,
    r.unit_price,
    r.scraped_at
from ranked r
join pharmacies ph on ph.id = r.pharmacy_id
left join products  p on p.id = r.product_id
where r.rn = 1
  and not r.price_suspect;   -- 2026-11-08: keep sentinel prices out of every downstream view

comment on view v_latest_listings is
    'One row per (pharmacy, url), newest scraped_at wins. Rows flagged price_suspect (price_ngn below '
    '20 NGN) are excluded: they are kept in pharmacy_listings but must not be ranked on.';
