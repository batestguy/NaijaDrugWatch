# T3 report — `v_cheapest_per_product_state` now answers both questions

Vintage discipline: this ticket writes no `registry/` vintage. The change is a `create or replace`
view definition plus its documentation; the database state it produces is reproducible by re-running
`schema/003_views.sql`.

## Changed

- `schema/003_views.sql:41-156` — the `v_cheapest_per_product_state` block.
  - `:49-63` header comment records the measurement, the two answer groups and the NULL rule.
  - `:76` `l.pack_size` added to the `base` CTE (needed for the pack-size columns).
  - `:94-104` `ranked_pack` — former `ranked`, same ordering (`price_ngn asc, pharmacy_id asc`).
  - `:106-115` `ranked_unit` — `unit_price asc nulls last, price_ngn asc, pharmacy_id asc`.
  - `:118-137` existing ten columns emitted unchanged from the `ranked_pack` row.
  - `:128-132` `cheapest_pack_*` group (same row as the legacy columns).
  - `:137-141` `best_unit_*` group, each column individually guarded by `case when u.unit_price is
    not null … end`, so a NULL price can never sit beside a non-NULL pharmacy or URL.
- `docs/views.md:10` — contract cell now says the view carries both answers.
- `docs/views.md:28-56` — new section: the two groups, their rankings, the measurement behind the
  change, and an explicit instruction that `best_unit_unit_price IS NULL` must render as "cost per
  unit not known", never as the sticker price.
- `.agent/T3-progress.md`, `.agent/T3-report.md`.

`dashboard/app.py` untouched, as instructed.

## Verified

Pre-change baseline, captured before any write:

```
{"rows": 85, "comparisons": 6, "latest_listings": 1530,
 "cipro_before": [["Ciprofloxacin","Lagos","HealthPlus","5180.00","518.0000",
   "https://healthplusnigeria.com/products/ciprotab-ciprofloxacin-500mg-tabs-x10"]]}
```

Candidate rows the two worked examples were chosen from:

```
(218,'Ciprofloxacin',5180.00,pack 10 tab, 518.0000)
(218,'Ciprofloxacin',7060.00,pack 14 tab, 504.2857)
(165,'Cefixime',   4100.00,pack 60 ml,  68.3333)
(165,'Cefixime',   5160.00,pack 100 ml, 51.6000)
(164,'Cefixime',   7820.00,pack 10,     unit_price NULL)
```

### Gate 1 — `select count(*) from v_cheapest_per_product_state`

```
85
```

### Gate 2 — `select count(*) filter (where is_comparison) from v_cheapest_per_product_state`

```
6
```

Column list after the change — ten original columns at their original ordinal positions, five plus
five appended, no rename and no retype:

```
(1,'product_id','bigint')                 (11,'cheapest_pack_price','numeric')
(2,'canonical_name','text')               (12,'cheapest_pack_pack_size','integer')
(3,'state','text')                        (13,'cheapest_pack_pharmacy_id','bigint')
(4,'cheapest_pharmacy_id','bigint')       (14,'cheapest_pack_pharmacy','text')
(5,'cheapest_pharmacy','text')            (15,'cheapest_pack_url','text')
(6,'price_ngn','numeric')                 (16,'best_unit_unit_price','numeric')
(7,'unit_price','numeric')                (17,'best_unit_pack_size','integer')
(8,'url','text')                          (18,'best_unit_pharmacy_id','bigint')
(9,'pharmacy_count','bigint')             (19,'best_unit_pharmacy','text')
(10,'is_comparison','boolean')            (20,'best_unit_url','text')
```

### Gate 3 — Ciprofloxacin and Cefixime, Lagos, both answer groups

```
('Ciprofloxacin','Lagos',
 pack 5180.00 / size 10 / HealthPlus,
 best 504.2857 / size 14 / HealthPlus,
 sizes_differ=True, pack price/unit=518.0000, best_is_cheaper_per_unit=True,
 best_unit_url=…ciprotab-ciprofloxacin-500mg-tabs-x14)

('Cefixime','Lagos',   -- product 164, 400mg x10, the ONLY listing, unit_price NULL
 pack 7820.00 / size 10 / HealthPlus,
 best None / None / None,
 sizes_differ=True, pack price/unit=782.0000, best_is_cheaper_per_unit=None,
 best_unit_url=None)

('Cefixime','Lagos',   -- product 165, suspension
 pack 4100.00 / size 60 / HealthPlus,
 best 51.6000 / size 100 / HealthPlus,
 sizes_differ=True, pack price/unit=68.3333, best_is_cheaper_per_unit=True,
 best_unit_url=…ocefix-cefixime-100mg5ml-suspension-100ml)
```

Ciprofloxacin: ₦5,180/10-pack is the cheapest pack, ₦7,060/14-pack is the best value — different
rows, and the best-value unit price is below the pack's. Cefixime product 165: ₦4,100/60 ml is the
cheapest pack, ₦5,160/100 ml is the best value. Cefixime product 164 is the NULL case: one listing,
no `unit_price`, so its whole `best_unit_*` group is NULL rather than a repeat of ₦7,820.

### Gate 4 — NULL rule

```
cells: 85
best_unit_unit_price is null: 36
VIOLATION cells (null price but any other best_unit_* non-null): 0
VIOLATION cells (price non-null but pharmacy/url null): 0
cells where unit_price column (cheapest-pack row) is null: 45
cells where best_unit row differs from cheapest-pack row: 12
pack columns disagree with legacy columns (must be 0): 0
```

36 of 85 (42%) answer "not known" for best value. That is expected: `unit_price` coverage is ~53%,
and a cell can be NULL even when `unit_price` is populated for the cheapest-pack row, because the
best-value ranking considers every listing in the cell.

### Gate 5 — `003_views.sql` applied twice, same result

```
before apply: ('c0ac92d99c14bec72281e16df2990533', 85)
applied schema/003_views.sql
after  apply: ('c0ac92d99c14bec72281e16df2990533', 85)
comparisons: 6
IDEMPOTENT: True
```

Command: `.venv\Scripts\python.exe -X utf8 "$env:TEMP\opencode\t3_idem.py"` (checksum of
`md5(string_agg(t::text, '|' order by product_id, state))`, apply, checksum again).

### Gate 6 — unchanged rows vs an independent query on `v_latest_listings`

The independent query uses `distinct on (product_id, state) … order by price_ngn asc, pharmacy_id
asc` — a different mechanism from the view's `row_number()`, so it can disagree.

```
rows compared: 85
MISMATCHES vs independent recompute: 0

5 sampled rows (canonical_name, state, view price, recomputed price, url equal,
                view pharmacy, recomputed pharmacy, is_comparison):
('Clotrimazole','Lagos', 2720.00, 2720.00, True, 'HealthPlus','HealthPlus', False)
('Clotrimazole','Lagos', 34920.00, 34920.00, True, 'HealthPlus','HealthPlus', False)
('Condoms (Lubricated)','Lagos', 4750.00, 4750.00, True, 'HealthPlus','HealthPlus', False)
('Diclofenac','Lagos', 300.00, 300.00, True, 'MedPlus','MedPlus', False)
('Diclofenac','Lagos', 38150.00, 38150.00, True, 'HealthPlus','HealthPlus', False)
```

All 85 rows agree, not just the sample. Also `pack columns disagree with legacy columns: 0`, i.e.
`cheapest_pack_price`/`_pharmacy`/`_url` are bit-identical to `price_ngn`/`cheapest_pharmacy`/`url`
on every row.

## Deviations

- The first apply script failed twice on psycopg-3 API differences (`cursor_factory` is not a
  `Connection.cursor()` kwarg; `Connection` has no `.notices`). Both failures were in the script, not
  the SQL: the first died before sending anything, the second sent and committed the file and then
  died printing notices. Net effect — the view has been created by this definition three times, and
  the checksum gate above was run afterwards on a clean apply.
- The first progress line lost `₦` to the console codepage (`?5,180`). Later lines were written with
  `Add-Content -Encoding utf8`. `schema/003_views.sql` and `docs/views.md` are UTF-8 and were not
  affected; the `₦` in the new SQL comment reads correctly.
- `docs/views.md` says 12 cells pick a different row for the two answers, while T2 reported 9 cells
  "not the best per unit". Both are true and they measure different things: T2 counted multi-pack
  cells where the pack pick is not per-unit-optimal (9 of 15); 12 is the count of cells where the
  best-value row is a different row from the cheapest-pack row, including pharmacy/URL differences
  and cells whose pack sizes tie.

## Left alone

- `.gitignore` shows as modified (`M`) in `git status`; that edit (ignoring `.agent/*-brief.md` and
  `*-progress.md`) predates this ticket. Not touched.
- `dashboard/app.py` still shows only the sticker answer. Separate ticket, as instructed — the view
  now has the data for a second column.
- `healthplus.py:parse_pack` still lacks the slash-strength guard. Out of scope here; T2 measured the
  live exposure at zero rows.

## Unproven

- Whether the 12 divergent cells are genuinely one product (the Atorvastatin 13× spread in T2 is
  still unresolved, and it feeds both rankings). No shop page was opened.
- That 36 NULL best-value answers is the steady state: `unit_price` coverage moves with every
  HealthPlus scrape, and the count moves with it.
- That nothing was reading `v_cheapest_per_product_state`'s column order positionally. `SELECT *`
  consumers would see five extra columns; Postgres allows the replace because the columns were
  appended, and `dashboard/app.py` names its columns.
- The row count is 85 as of this run; a scrape writing to `pharmacy_listings` concurrently could move
  it. No scrape was run by this ticket and no table was modified.
