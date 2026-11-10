-- 006_stock_confidence.sql
-- Stop "we could not read the stock level" from being published as "not available".
--
-- THE DEFECT (measured 2026-11-10). v_cheapest_per_product_state (schema/003_views.sql:70-156) built
-- its base relation with `where l.in_stock is true`. `in_stock` has THREE states, not two: true, false,
-- and NULL, where NULL means the reader could not find a stock signal on the page at all. The filter
-- silently collapsed the third state into the second, so a parser blind spot was published as a
-- market fact.
--
-- How it fired. On 2026-11-09 MedPlus changed its product-page markup and the reader stopped finding
-- the quantity input that carries the only stock signal the site exposes (documented in PROGRESS.md,
-- 2026-11-07: `in_stock = max > 0`, and NULL when no signal exists). 128 rows were written that day
-- with in_stock = null; 108 of them had been true the day before. Every one of them disappeared from
-- the comparison view. On 2026-11-10 the table holds 141 such rows, all of them MedPlus.
--
-- THE MEASUREMENT, same data, three base filters (re-run live 2026-11-10, PG 17.11):
--
--   | base filter on in_stock      | cells | two-pharmacy cells |
--   |------------------------------|-------|--------------------|
--   | `is true`        (before)    |  242  |         42         |
--   | `is not false`   (this file) |  264  |         45         |
--   | ignored entirely             |  346  |         73         |
--
-- So the old filter discarded 22 cells and 3 comparisons that the data contains, and the loosest
-- possible filter adds another 82 cells that are explicitly out of stock. `is not false` is the line
-- that keeps measurements and drops refusals.
--
-- This is not a market movement. Lyrica 150 mg is the proof: MedPlus quoted NGN 32,200 on both days and
-- only the stock reading changed between them. A price that did not move left the view because a
-- parser stopped recognising a <input> tag.
--
-- THE RULE THIS ENFORCES, from schema/003_views.sql:63-66: a NULL means "not known", and a substituted
-- answer is a lie. "We could not read it" must never be expressed as "not available", and equally must
-- never be expressed as "confirmed in stock". The fix therefore does both halves: count the row, and
-- label it.
--
-- WHY UNKNOWN IS RANKED BELOW CONFIRMED AND NOT EXCLUDED. Two candidate fixes existed. Excluding NULL
-- reproduces the bug in different clothes. Ranking NULL equally with true lets the "cheapest" claim name
-- an item we cannot see is available — worst of all a cheap one, which is exactly the item a buyer would
-- chase. So: stock still decides *who may win*, availability marks *how much the answer is worth*.
-- A confirmed row beats a cheaper unconfirmed one (ordering below); the winner's own confidence is then
-- exposed as a boolean column, and the cell's count of confirmed pharmacies alongside it. The label is
-- `cheapest_pack_stock_confirmed`, not `in_stock`, because it reports on the ROW THAT WON, not on the
-- cell.
--
-- WHY THIS FILE REDEFINES A VIEW RATHER THAN EDITING 003. Same convention as schema/005: the numbered
-- files are applied in order, `create or replace view` is legal for an append-only change, and 003 stays
-- as the record of what it said on 2026-11-08. A rebuild that runs 001 -> 006 in order lands on the
-- definition at the bottom of this file. Back-porting into 003 would leave two copies of one definition
-- with nothing to say which is authoritative — the drift 005 already warned about at :25-29.
--
-- `is_comparison` IS DELIBERATELY UNCHANGED (`pharmacy_count >= 2`). A second pharmacy whose stock we
-- cannot read is still a second price, and dropping it would understate how much competition exists.
-- The caveat is made visible instead of being made to disappear: `confirmed_pharmacy_count` says how
-- many of those pharmacies we can actually see holding the item, so a reader can tell a cell backed by
-- two confirmed stocks from one backed by a confirmed stock and an unknown one.
--
-- COLUMN CONTRACT. Everything that existed keeps its name, its position and its type: 20 columns, then
-- exactly three appended at the END (Postgres allows appending, and refuses a rename or a reorder of an
-- existing column of a view):
--
--   cheapest_pack_stock_confirmed  boolean  true, or NULL when the winning row's stock is unknown
--   best_unit_stock_confirmed      boolean  same rule; NULL whenever the whole best_unit_* group is NULL
--   confirmed_pharmacy_count       bigint   distinct pharmacies in the cell with in_stock = true
--
-- The dashboard selects these columns by name (dashboard/app.py, "Cheapest per state" tab), so appending
-- does not touch it. Anything that does `select *` and counts columns must be re-read; nothing in this
-- repo does.
--
-- VALUE CHANGES THAT ARE INTENDED. Where a cell holds both a confirmed row and a cheaper unknown-stock
-- row, the confirmed row now wins `cheapest_pack_*` and `best_unit_*`. That is the decision: a price we
-- cannot see is available does not get to call itself the cheapest. Rows that already were the cheapest
-- confirmed price do not move.
--
-- NOT COVERED HERE, deliberately:
--   * v_latest_listings is untouched. It is the observation layer and already carries in_stock verbatim;
--     this is a ranking decision, not a data-quality flag, so it does not belong there.
--   * The MedPlus reader is not fixed. Until the parser reads the new markup those rows stay NULL and
--     every MedPlus cell keeps saying "unconfirmed". That is the honest rendering, not a fix.
--   * No build-time guard. A scraper that writes in_stock = null for a genuinely unavailable product is
--     indistinguishable from a parser miss at this layer. Only the source can tell them apart.

-- ------------------------------------------------------------------ the view
-- `begin`/`commit` so a failure leaves the previous definition in place: `create or replace view` takes
-- an ACCESS EXCLUSIVE lock, and a half-applied multi-statement file would be worse than either version.

begin;

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
        l.in_stock,
        l.url
    from v_latest_listings l
    -- 2026-11-10: `is not false` admits true AND null. `is true` treated "no signal" as "no stock".
    where l.in_stock is not false
      and l.price_ngn is not null
      and l.product_id is not null
),
-- count(distinct ...) is NOT supported as a window function in Postgres
-- ("DISTINCT is not implemented for window functions"), so both per-cell counts are aggregated in
-- their own CTE and joined back on the same partition key.
pharmacy_counts as (
    select
        b.product_id,
        b.state,
        count(distinct b.pharmacy_id) as pharmacy_count
    from base b
    group by b.product_id, b.state
),
-- How many of those pharmacies can actually be seen holding it. Zero is a real, publishable answer
-- (every quote in the cell is from a page whose stock we could not read), so this is coalesced below
-- rather than left NULL.
confirmed_pharmacy_counts as (
    select
        b.product_id,
        b.state,
        count(distinct b.pharmacy_id) as confirmed_pharmacy_count
    from base b
    where b.in_stock is true
    group by b.product_id, b.state
),
-- Answer 1: cheapest pack, stock-confirmed first. The leading `case` is the whole point of this file:
-- a confirmed row outranks a cheaper unconfirmed one. Price then pharmacy_id keep the pick
-- deterministic and, among equally-confirmed rows, identical to the pre-2026-11-10 view.
ranked_pack as (
    select
        b.*,
        row_number() over (
            partition by b.product_id, b.state
            order by case when b.in_stock is true then 0 else 1 end asc,
                     b.price_ngn asc,
                     b.pharmacy_id asc
        ) as rn
    from base b
),
-- Answer 2: best value per unit, same stock preference, then `nulls last` so a row with an unknown
-- unit_price cannot win, then the price/pharmacy tiebreak.
ranked_unit as (
    select
        b.*,
        row_number() over (
            partition by b.product_id, b.state
            order by case when b.in_stock is true then 0 else 1 end asc,
                     b.unit_price asc nulls last,
                     b.price_ngn asc,
                     b.pharmacy_id asc
        ) as rn
    from base b
)
select
    -- ---- unchanged columns, unchanged names, positions and types -----------
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
    -- ---- cheapest pack, now named ------------------------------------------
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
    case when u.unit_price is not null then u.url end                 as best_unit_url,
    -- ---- appended 2026-11-10: how much the answer is worth ----------------
    -- `case ... then true end` and not `c.in_stock is true`: the plain test returns FALSE for an unknown
    -- stock, and FALSE would assert "we know it is not available" — the exact substitution this file
    -- exists to prevent. TRUE or NULL only.
    case when c.in_stock is true then true end                        as cheapest_pack_stock_confirmed,
    -- NULL whenever the whole best_unit_* group is NULL, so the existing null rule still holds; otherwise
    -- TRUE only if that winning row's stock was read.
    case when u.unit_price is not null and u.in_stock is true then true end
                                                                     as best_unit_stock_confirmed,
    -- Left join + coalesce: a cell where no pharmacy's stock was readable has 0 confirmed, not no answer.
    coalesce(cc.confirmed_pharmacy_count, 0)                          as confirmed_pharmacy_count
from ranked_pack c
join pharmacy_counts pc
    on pc.product_id = c.product_id
   and pc.state      = c.state
join ranked_unit u
    on u.product_id = c.product_id
   and u.state      = c.state
   and u.rn         = 1
left join confirmed_pharmacy_counts cc
    on cc.product_id = c.product_id
   and cc.state      = c.state
where c.rn = 1;

comment on view v_cheapest_per_product_state is
    'Cheapest price per canonical product per state, answered two ways (cheapest_pack_*, lowest sticker; '
    'best_unit_*, lowest price per unit where the pack size parsed). Base filter is in_stock is not '
    'false: a row whose stock could not be read is counted, ranked below every confirmed row, and '
    'labelled by cheapest_pack_stock_confirmed / best_unit_stock_confirmed. NULL in those columns means '
    'the winning row''s stock is unknown, never that it is unavailable. is_comparison is unchanged '
    '(pharmacy_count >= 2); confirmed_pharmacy_count says how many of those pharmacies were seen '
    'holding it. Defined in schema/006_stock_confidence.sql, which supersedes 003.';

comment on column v_cheapest_per_product_state.cheapest_pack_stock_confirmed is
    'TRUE when the row that won cheapest_pack_* was observed in stock; NULL when its stock could not be '
    'read. Never FALSE: a row known to be out of stock is excluded from this view entirely.';

comment on column v_cheapest_per_product_state.best_unit_stock_confirmed is
    'TRUE when the row that won best_unit_* was observed in stock; NULL when its stock was unreadable OR '
    'when the whole best_unit_* group is NULL because no competing row had a parsed unit price.';

comment on column v_cheapest_per_product_state.confirmed_pharmacy_count is
    'Distinct pharmacies in this cell observed with in_stock = true. 0 means every quote in the cell '
    'came from a page whose stock signal could not be read - the cell is still a real price comparison, '
    'just not a confirmed-availability one.';

commit;
