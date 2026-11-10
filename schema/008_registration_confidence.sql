-- 008_registration_confidence.sql
-- Make the licence behind a published price visible, without hiding the price and without turning an
-- unread status into a negative finding.
--
-- THE DEFECT (measured 2026-11-10). v_cheapest_per_product_state (schema/006_stock_confidence.sql:89)
-- names a "cheapest" for a product and says nothing about whether the product's NAFDAC registration is
-- allowed to be sold. It is not a small corner: 159 listings in v_suspicious_listings carry a
-- registration that is not Active or is past its expiry, and 12 of those products still appear in this
-- view as a two-pharmacy comparison. So the table currently picks a winner among prices for medicines
-- whose registration is marked inactive or expired, and the reader has no way to know.
--
-- The finding is the point of the project, so it is not filtered out and not removed. It is labelled.
-- The user decided this on 2026-11-10: label it, do not hide it, do not leave it silent.
--
-- THE RULE THIS REPEATS, from schema/003_views.sql:163-167 and schema/006:32-35: an unknown reading is
-- not a negative finding. `nafdac_registrations.status` is NULL when no detail page was ever fetched for
-- that registration. v_suspicious_listings already refuses to call that suspicious (`r.status is not
-- null`); this file must refuse in the same way. Labelling a drug unregistered because we never read its
-- record would be the same error as calling an unread shelf empty.
--
-- THE MEASUREMENT (live 2026-11-10, PG 17.11, over the 735 products that carry a registration number):
--
--   | state of the registration        | products |
--   |----------------------------------|----------|
--   | status = 'Active', not expired   |    393   |
--   | status not Active, or expired    |    235   |   (136 Inactive, 99 Expired)
--   | NRN present but status never read|    107   |
--   | no registration number at all    |    698 of 1,433 products
--
-- Applied to the 260 cells of the view: 70 cells are flagged (`registration_flagged = true`), and those
-- 70 are exactly the products in v_suspicious_listings that the view prices — 58 single-pharmacy cells
-- and 12 comparisons. The 48 cells whose product has a registration number but no status stay unflagged
-- and carry `registration_status = NULL`; the number of those whose product has no registration number
-- at all is 142. Neither group is called suspicious by this file.
-- (The brief for this ticket predicted "12 distinct products flagged" as the cross-check. 12 is the
-- comparison subset; the whole view returns 70. Both numbers are reproduced below and in the report.)
--
-- WHY A BOOLEAN ALONE WOULD BE A LIE. `registration_flagged = false` covers two different worlds: a
-- licence we read and found active, and a licence we never read. A dashboard printing the boolean would
-- render the second as "no", which is the substitution this file exists to prevent. So the raw status is
-- appended beside the flag, and the rendering layer has three labels — active, not active, not read —
-- never a blank. The boolean exists because it is the condition that is safe to filter or count on.
--
-- WHY THE CONDITION IS COPIED FROM v_suspicious_listings RATHER THAN INVENTED. `v_suspicious_listings`
-- (:192-193) is the project's one definition of a flagged registration:
--
--   r.status is not null and (r.status <> 'Active' or r.expiry_date < current_date)
--
-- Both halves are needed: the source contains registrations published as `Expired` with a future expiry
-- date, so `status` alone misses them, and `expiry_date` alone misses the Inactive ones. A second,
-- slightly different definition here would be a second truth, and the two would drift.
--
-- NOTHING ELSE CHANGES. No filter moves, no ranking moves, no row is added or removed: the row count is
-- 260 and the comparison count 45 before and after (verified, and repeated in the report). In
-- particular:
--   * `is_comparison` stays `pharmacy_count >= 2` — the user decided to keep it as it is.
--   * `in_stock is not false` stays — a licence problem is not a stock problem.
--   * The two-pharmacy cells that carry a flagged licence stay in the view. Excluding them would delete
--     the finding; that is the option that was rejected.
--
-- COLUMN CONTRACT. Everything that existed keeps its name, position and type: the 23 columns of the
-- 2026-11-10 view, then exactly two appended at the END:
--
--   registration_status  text     nafdac_registrations.status for the product's registration;
--                                 NULL when the product has no registration number, or when no status
--                                 was ever read. NULL means "not read", never "not active".
--   registration_flagged boolean  TRUE only when a status was read AND it is not Active or its expiry
--                                 has passed. FALSE covers both "active" and "never read", which is why
--                                 the raw status column is required alongside it. Never NULL.
--
-- THE JOIN CANNOT CHANGE THE ROW SET. `nafdac_registrations.registration_number` is unique (0 duplicates
-- among 10,912 measured 2026-11-10), and `products.nafdac_registration_number` holds one NRN per product,
-- so the left join is at most one row per cell. Measured after the change: 260 rows, still 260 cells.
--
-- NOT COVERED HERE, deliberately:
--   * mv_drug_price_index is untouched. It aggregates a product-day-state market figure and names no
--     winner, so it has no "cheapest" claim to disclaim. If that view ever gains a winner column, this
--     reasoning stops applying.
--   * The 698 products with no registration number are not labelled unregistered. No NRN means the
--     linker found no candidate, which is a statement about our matching, not about the product.
--   * A product can have several registrations in reality (brand and generic). `products` holds one NRN
--     per product, so only that one is labelled. A product flagged here would be un-flagged if the
--     linker attaches it to an active registration instead — a data question, not a view question.

-- ------------------------------------------------------------------ the view
-- `begin`/`commit` so a failure leaves the previous definition in place. This is the same definition as
-- schema/006 with two columns and one join appended; schema/006 remains the record of what the view said
-- before a licence reading was published beside the price.

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
    -- 2026-11-10 (006): `is not false` admits true AND null. `is true` treated "no signal" as "no stock".
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
-- Answer 1: cheapest pack, stock-confirmed first (schema/006, unchanged).
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
-- unit_price cannot win, then the price/pharmacy tiebreak (schema/006, unchanged).
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
    case when u.unit_price is not null then u.unit_price end          as best_unit_unit_price,
    case when u.unit_price is not null then u.pack_size end           as best_unit_pack_size,
    case when u.unit_price is not null then u.pharmacy_id end         as best_unit_pharmacy_id,
    case when u.unit_price is not null then u.pharmacy_name end       as best_unit_pharmacy,
    case when u.unit_price is not null then u.url end                 as best_unit_url,
    -- ---- appended 2026-11-10 (006): how much the price is worth -----------
    case when c.in_stock is true then true end                        as cheapest_pack_stock_confirmed,
    case when u.unit_price is not null and u.in_stock is true then true end
                                                                     as best_unit_stock_confirmed,
    coalesce(cc.confirmed_pharmacy_count, 0)                          as confirmed_pharmacy_count,
    -- ---- appended 2026-11-10 (008): what the licence says, if we read it --
    -- Raw status, NULL when there is no registration number or no status was ever read. Never
    -- substituted: a reader must be able to see "we hold nothing" as distinct from "not Active".
    r.status                                                          as registration_status,
    -- TRUE only where a status was read and it fails the v_suspicious_listings test. Written as
    -- `case ... then true else false end` so the column is boolean NOT NULL: FALSE means "not flagged",
    -- which is NOT the same as "active" -- see registration_status for that.
    case
        when r.status is not null
         and (r.status <> 'Active' or r.expiry_date < current_date) then true
        else false
    end                                                               as registration_flagged
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
-- Left joins: a product with no registration number, or whose registration has no row, keeps its price
-- and gets NULL status. A join that dropped it would hide prices to protect a claim about a licence.
left join products p
    on p.id = c.product_id
left join nafdac_registrations r
    on r.registration_number = p.nafdac_registration_number
where c.rn = 1;

comment on view v_cheapest_per_product_state is
    'Cheapest price per canonical product per state, answered two ways (cheapest_pack_*, lowest sticker; '
    'best_unit_*, lowest price per unit where the pack size parsed). Base filter is in_stock is not '
    'false: a row whose stock could not be read is counted, ranked below every confirmed row, and '
    'labelled by cheapest_pack_stock_confirmed / best_unit_stock_confirmed. NULL in those columns means '
    'the winning row''s stock is unknown, never that it is unavailable. is_comparison is unchanged '
    '(pharmacy_count >= 2); confirmed_pharmacy_count says how many of those pharmacies were seen '
    'holding it. registration_status carries the product''s raw NAFDAC status, NULL when none was read; '
    'registration_flagged is TRUE only where a status was read and it is not Active or has expired, so '
    'FALSE means "not flagged", not "active". Defined in schema/008_registration_confidence.sql, which '
    'supersedes 006, which supersedes 003.';

comment on column v_cheapest_per_product_state.registration_status is
    'Raw nafdac_registrations.status for the product''s registration number. NULL when the product has '
    'no registration number or when no detail page was ever read for it: NULL means "not read", never '
    '"not active". Render it, do not drop it.';

comment on column v_cheapest_per_product_state.registration_flagged is
    'TRUE only when a status was read AND (status <> ''Active'' OR expiry_date < current_date) - the '
    'same condition as v_suspicious_listings. FALSE covers both an active registration and one whose '
    'status was never read, so FALSE must not be rendered as "active". Never NULL.';

commit;
