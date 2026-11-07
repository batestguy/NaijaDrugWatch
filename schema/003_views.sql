-- 003_views.sql
-- The five plain views. They are the public contract: the dashboard and the Neon Data API
-- read these names, so do not rename them.
--
-- Everything here is CREATE OR REPLACE, so re-running the file is safe.

-- ------------------------------------------------------- v_latest_listings
-- Current state of every pharmacy listing: one row per (pharmacy, url), newest scrape wins.

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
-- Cheapest in-stock pharmacy per canonical product per state.
--
-- IMPORTANT (product decision, 2026-11-06): a single pharmacy quoting a product in a state is
-- not a comparison. `is_comparison` is only true when two or more independent pharmacies quote
-- it there. Consumers must not label a single-pharmacy cell "cheapest".

create or replace view v_cheapest_per_product_state as
with base as (
    select
        l.product_id,
        l.canonical_name,
        l.state,
        l.pharmacy_id,
        l.pharmacy_name,
        l.price_ngn,
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
ranked as (
    select
        b.*,
        row_number() over (
            partition by b.product_id, b.state
            order by b.price_ngn asc, b.pharmacy_id asc
        ) as rn
    from base b
)
select
    r.product_id,
    r.canonical_name,
    r.state,
    r.pharmacy_id   as cheapest_pharmacy_id,
    r.pharmacy_name as cheapest_pharmacy,
    r.price_ngn,
    r.unit_price,
    r.url,
    pc.pharmacy_count,
    (pc.pharmacy_count >= 2) as is_comparison
from ranked r
join pharmacy_counts pc
    on pc.product_id = r.product_id
   and pc.state      = r.state
where r.rn = 1;

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
    where l.price_ngn is not null
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
