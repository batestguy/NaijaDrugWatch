-- 009_index_price_floor.sql
-- The price index gets the same floor the views already have.
--
-- THE DEFECT, closed here. `004_materialized.sql` averages `price_history` with no price floor, while
-- `005_suspect_prices.sql` flags sub-20-naira listings and every view that ranks on price excludes them.
-- `005` recorded the gap in its own comments and deferred it to a separate ticket; this is that ticket.
-- Measured on the frozen vintage (2026-11-21): of 428 index rows, ONE had a minimum below 20 naira -
-- 10.99, the sentinel cluster `005` describes. Nothing else changed: 0 rows had their average, minimum,
-- maximum or pharmacy count moved by the floor. The single affected row disappears rather than being
-- rewritten, because after the floor it has no surviving price.
--
-- WHY IT MATTERS. The index is the only table that reads like an average of the market. A minimum of
-- 10.99 naira in a market average is the same claim `005` was written to prevent, so leaving it out of
-- this one table was an inconsistency rather than a decision.
--
-- WHY DROP AND RECREATE. A materialised view cannot be altered in place; changing its definition means
-- dropping it. The unique index from `004` goes with it and is recreated below, because
-- `refresh ... concurrently` needs it. The window in which the index is missing is the length of this
-- file, which is why it runs as one transaction.
--
-- IDEMPOTENT. Running it again drops and rebuilds the same definition, so a rebuild that runs
-- 001 -> 009 lands on the same result as running 009 alone. `004` is deliberately left as written: this
-- repo corrects views by appending a later file, the same way `005`, `006` and `008` correct `003`.

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
    avg(case when h.in_stock then 1.0 else 0.0 end)::numeric(5, 4) as stock_rate
from price_history h
join pharmacy_listings l on l.id = h.listing_id
join pharmacies        ph on ph.id = l.pharmacy_id
join products           p on p.id = l.product_id
where p.canonical_name is not null
  -- The floor. Both tests, because the flag can decay (a row inserted after 005 ran is unflagged)
  -- and the threshold is the durable half of the rule.
  and h.price_ngn >= 20
  and not l.price_suspect
group by 1, 2, 3;

create unique index if not exists mv_drug_price_index_day_product_state_idx
    on mv_drug_price_index (day, canonical_name, state);

comment on materialized view mv_drug_price_index is
    'Daily average, minimum and maximum price per medicine and state. Prices below 20 naira and rows '
    'flagged price_suspect are excluded, matching the floor in 005_suspect_prices.sql. Added 2026-11-21 '
    '(009): one row of 428 had a minimum of 10.99 naira before the floor.';

commit;

-- Verify after applying:
--   select count(*)                                   as rows,
--          count(*) filter (where min_price_ngn < 20) as rows_with_min_under_20,
--          min(min_price_ngn)                        as lowest_min
--     from mv_drug_price_index;
--   -- expected on the 2026-11-16 vintage: 427 rows, 0, 50.00
