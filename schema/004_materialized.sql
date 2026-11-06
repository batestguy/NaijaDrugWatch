-- 004_materialized.sql
-- The daily price index. Refresh from the Prefect flow, never by hand: a stale index is
-- indistinguishable from a quiet market.
--
-- CONCURRENTLY requires a UNIQUE index on the exact columns consumers filter by, which is why
-- the index below is created in the same file and is not optional.

create materialized view if not exists mv_drug_price_index as
select
    (ph.recorded_at at time zone 'Africa/Lagos')::date as day,
    p.canonical_name,
    l.state,
    avg(ph.price_ngn)::numeric(12, 2)                        as avg_price_ngn,
    min(ph.price_ngn)::numeric(12, 2)                        as min_price_ngn,
    max(ph.price_ngn)::numeric(12, 2)                        as max_price_ngn,
    count(distinct l.pharmacy_id)                            as pharmacy_count,
    avg(case when ph.in_stock then 1.0 else 0.0 end)::numeric(5, 4) as stock_rate
from price_history ph
join pharmacy_listings l on l.id = ph.listing_id
join products          p on p.id = l.product_id
where p.canonical_name is not null
group by 1, 2, 3;

create unique index if not exists mv_drug_price_index_day_product_state_idx
    on mv_drug_price_index (day, canonical_name, state);

-- Refresh helper. Called by flows/daily.py after the price and match steps.
--
--   refresh materialized view concurrently mv_drug_price_index;
--
-- CONCURRENTLY needs the unique index above; without it Postgres raises
-- "cannot refresh materialized view concurrently".
