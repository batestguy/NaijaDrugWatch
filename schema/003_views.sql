-- 003_views.sql
-- The five plain views. They are the public contract: the dashboard and the Neon Data API
-- read these names, so do not rename them.
--
-- Everything here is CREATE OR REPLACE, so re-running the file is safe.

-- ------------------------------------------------------- v_latest_listings
-- Current state of every pharmacy listing: one row per (pharmacy, url), newest scrape wins.
--
-- WARNING: this definition is SUPERSEDED by schema/005_suspect_prices.sql, which adds
-- `and not price_suspect`. Running 003 on its own after 005 silently reverts the exclusion and
-- brings the flagged sub-NGN-20 rows back (2,599 -> 2,613). A full rebuild is safe because 005
-- sorts after 003; a partial re-run of this file is not. Kept here rather than deleted so 003
-- remains a complete, runnable record of the schema at its time.

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
where r.rn = 1;

-- --------------------------------------------- v_cheapest_per_product_state
-- Cheapest in-stock pharmacy per canonical product per state, answered TWO ways in one row.
--
-- IMPORTANT (product decision, 2026-11-06): a single pharmacy quoting a product in a state is
-- not a comparison. `is_comparison` is only true when two or more independent pharmacies quote
-- it there. Consumers must not label a single-pharmacy cell "cheapest".
--
-- 2026-11-08, additive: the original view ranked on `price_ngn` alone, i.e. lowest STICKER price,
-- which is not lowest cost per tablet when a product is sold in several pack sizes. Measured on
-- 85 cells: 15 have more than one pack size in stock and 9 of those picked a row that is not the
-- cheapest per unit (Ciprofloxacin Lagos: ₦5,180/10-pack = ₦518/unit chosen over ₦7,060/14-pack =
-- ₦504/unit). Both answers now ride in the same row:
--
--   cheapest_pack_*  lowest `price_ngn`   — the pre-change answer, unchanged, now named
--   best_unit_*      lowest `unit_price`  — NULL when that row's `unit_price` is NULL
--
-- THE NULL RULE IS THE POINT: `unit_price` is populated on only ~53% of HealthPlus listings.
-- When the best-value row has no `unit_price`, every `best_unit_*` column is NULL. Falling back
-- to the sticker price there would relabel "cheapest pack" as "best value" — the defect this
-- column group exists to fix. A NULL answer means "not known"; a substituted one is a lie.
--
-- Existing columns are unchanged in name and value; this is an append-only change.

create or replace view v_cheapest_per_product_state as
with base as (
    select
        l.product_id,
        l.canonical_name,
        l.state,
        l.pharmacy_id,
        l.pharmacy_name,
        l.price_ngn,
        l.pack_size,
        l.unit_price,
        l.url
    from v_latest_listings l
    where l.in_stock is true
      and l.price_ngn is not null
      and l.product_id is not null
),
-- count(distinct ...) is NOT supported as a window function in Postgres
-- ("DISTINCT is not implemented for window functions"), so the per-cell pharmacy count is
-- aggregated in its own CTE and joined back on the same partition key.
pharmacy_counts as (
    select
        b.product_id,
        b.state,
        count(distinct b.pharmacy_id) as pharmacy_count
    from base b
    group by b.product_id, b.state
),
-- Answer 1: cheapest pack. Identical ordering to the pre-2026-11-08 view, so `price_ngn`,
-- `url` and `cheapest_pharmacy` keep exactly the values they had.
ranked_pack as (
    select
        b.*,
        row_number() over (
            partition by b.product_id, b.state
            order by b.price_ngn asc, b.pharmacy_id asc
        ) as rn
    from base b
),
-- Answer 2: best value per unit. `nulls last` keeps rows with an unknown unit_price from
-- winning; the price/pharmacy tiebreak keeps the pick deterministic and identical to
-- ranked_pack when no row in the cell has a unit_price at all.
ranked_unit as (
    select
        b.*,
        row_number() over (
            partition by b.product_id, b.state
            order by b.unit_price asc nulls last, b.price_ngn asc, b.pharmacy_id asc
        ) as rn
    from base b
)
select
    -- ---- unchanged columns, unchanged values --------------------------------
    c.product_id,
    c.canonical_name,
    c.state,
    c.pharmacy_id   as cheapest_pharmacy_id,
    c.pharmacy_name as cheapest_pharmacy,
    c.price_ngn,
    c.unit_price,
    c.url,
    pc.pharmacy_count,
    (pc.pharmacy_count >= 2) as is_comparison,
    -- ---- cheapest pack, now named (same row as above) ----------------------
    c.price_ngn     as cheapest_pack_price,
    c.pack_size     as cheapest_pack_pack_size,
    c.pharmacy_id   as cheapest_pack_pharmacy_id,
    c.pharmacy_name as cheapest_pack_pharmacy,
    c.url           as cheapest_pack_url,
    -- ---- best value per unit; every column NULL when unit_price is NULL ----
    -- The guard is written per column rather than relying on `u.unit_price is not null`
    -- inside a single case, so no consumer can read a pharmacy name beside a NULL price
    -- and treat it as a measured answer.
    case when u.unit_price is not null then u.unit_price end          as best_unit_unit_price,
    case when u.unit_price is not null then u.pack_size end           as best_unit_pack_size,
    case when u.unit_price is not null then u.pharmacy_id end         as best_unit_pharmacy_id,
    case when u.unit_price is not null then u.pharmacy_name end       as best_unit_pharmacy,
    case when u.unit_price is not null then u.url end                 as best_unit_url
from ranked_pack c
join pharmacy_counts pc
    on pc.product_id = c.product_id
   and pc.state      = c.state
join ranked_unit u
    on u.product_id = c.product_id
   and u.state      = c.state
   and u.rn         = 1
where c.rn = 1;

-- --------------------------------------------------- v_suspicious_listings
-- Listings whose registration is not Active, or whose registration has expired.
--
-- Two conditions, unioned, because the two fields disagree in the source data: at least one
-- registration is published as Expired with a 2030 expiry. Reading one field alone under-reports.
--
-- `status is null` means we have not scraped that registration's detail page yet, which is
-- UNKNOWN, not suspicious. The earlier `is distinct from 'Active'` silently counted NULL as
-- "inactive" and would have flagged every product whose registration fell outside the scraped
-- scope (fixed 2026-11-07).

create or replace view v_suspicious_listings as
select
    l.listing_id,
    l.pharmacy_name,
    l.state,
    l.raw_title,
    l.url,
    l.price_ngn,
    l.in_stock,
    l.product_id,
    l.canonical_name,
    r.registration_number,
    r.status     as nafdac_status,
    r.expiry_date,
    case
        when r.status <> 'Active' then 'inactive_registration'
        else 'expired_registration'
    end as suspicion_reason
from v_latest_listings l
join products p
    on p.id = l.product_id
join nafdac_registrations r
    on r.registration_number = p.nafdac_registration_number
where r.status is not null
  and (r.status <> 'Active' or r.expiry_date < current_date);

-- ------------------------------------------------------ v_price_change_7d
-- Current price versus the most recent price at least seven days older, FOR THE SAME URL.
--
-- The original version grouped by listing_id and joined price_history to itself. That can never
-- return a row: a listing is an immutable observation, so a price change creates a new listing_id
-- and no listing_id ever has two prices. The comparison has to be across listings for the same
-- (pharmacy_id, url), which is what this now does (fixed 2026-11-07). Column names are unchanged.

create or replace view v_price_change_7d as
with latest as (
    select distinct on (l.pharmacy_id, l.url)
        l.pharmacy_id,
        l.url,
        l.id        as listing_id,
        l.price_ngn,
        l.scraped_at
    from pharmacy_listings l
    -- Suspect rows are excluded on BOTH sides: an NGN 1.00 placeholder paired against a real price
    -- reports a 99% "drop" that never happened. schema/005_suspect_prices.sql flags them; this
    -- view reads the base table, so it has to apply the flag itself (fixed 2026-11-08).
    where l.price_ngn is not null
      and not l.price_suspect
    order by l.pharmacy_id, l.url, l.scraped_at desc, l.id desc
),
prior as (
    select distinct on (o.pharmacy_id, o.url)
        o.pharmacy_id,
        o.url,
        o.price_ngn as price_7d_ago
    from pharmacy_listings o
    join latest c
      on c.pharmacy_id = o.pharmacy_id
     and c.url = o.url
    where o.price_ngn is not null
      and not o.price_suspect
      and o.scraped_at <= c.scraped_at - interval '7 days'
    order by o.pharmacy_id, o.url, o.scraped_at desc, o.id desc
)
select
    c.listing_id,
    c.price_ngn   as current_price,
    p.price_7d_ago,
    c.scraped_at  as recorded_at,
    round(100 * (c.price_ngn - p.price_7d_ago) / nullif(p.price_7d_ago, 0), 2) as pct_change_7d
from latest c
join prior p
  on p.pharmacy_id = c.pharmacy_id
 and p.url = c.url;

-- ------------------------------------------------------- v_pipeline_health
-- Per source: last success, hours since, and STALE after 48 h. Reads scrape_runs only.

create or replace view v_pipeline_health as
with last_success as (
    select
        sr.source,
        max(sr.finished_at) filter (where sr.status = 'success') as last_success_at
    from scrape_runs sr
    group by sr.source
)
select
    source,
    last_success_at,
    round(extract(epoch from (now() - last_success_at)) / 3600.0, 1) as hours_since_success,
    case
        when last_success_at is null then 'STALE'
        when last_success_at < now() - interval '48 hours' then 'STALE'
        else 'OK'
    end as status
from last_success;
