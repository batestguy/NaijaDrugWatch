# T2 report — `unit_price` defect scope

**Written by the secretary, not the agent.** `data-explorer` hit its **20-step** cap (raised from 8
earlier the same session) after establishing the headline number but before writing this file. Every
figure below was re-run by the secretary; the agent's own claims are marked where they were confirmed
or corrected.

## Answer

**No stored HealthPlus listing carries a wrong `unit_price` from slash-strength parsing. The count is
zero, and it is a real zero, not a vacuous one.**

| Measure | Value |
|---|---|
| HealthPlus latest listings | 1,197 (2,396 rows all-time) |
| Titles containing a slash pair `\d+/\d+` | **31** |
| Of those, stored `(pack_size, pack_unit)` differs from the guarded parse | **0** |
| Of those, where the stored pack is non-null | 30 of 31 |
| Slash-titled rows reaching `v_cheapest_per_product_state` | **1** |
| Of those, `is_comparison = true` | **0** |

The reason is in the titles themselves. HealthPlus writes strengths with the unit attached —
`80/480Mg`, `500/125mg`, `150/5mg` — and `parse_pack` then takes the explicit pack count instead:
`Atacand Plus 16/12.5mg x28 Tablets` → `(28, tab)` both with and without the guard. The bug fires on
the *other* shape, `80/480 Tablets` (space, then a form word, no count), which HealthPlus does not
appear to use. Proven synthetic case: `Coartem 80/480 Tablets x6` → `(480, tab)` unguarded,
`(6, tab)` guarded.

**Verdict: not a publication blocker today.** The guard is still worth adding to `healthplus.py`
eventually, because the vulnerability is live for the next title that uses the bare form.

## The finding that matters more

The scan surfaced a defect that is **already live in the published claim**, and it is not the one the
ticket was about.

`schema/003_views.sql:78-83` ranks with `order by b.price_ngn asc` — it compares **sticker price**,
not `unit_price`. `PLAN.md:70` states the pack columns exist so the view does not "compare a 12-tablet
pack to a 500-tablet jar". They exist and are selected, but the ranking never uses them.

| Measure | Value |
|---|---|
| Cells in `v_cheapest_per_product_state` | 85 |
| Cells where the product has more than one pack size in-stock | **15** |
| Of those, the chosen row is **not** the best per unit | **9** |

Two unambiguous cases, both Lagos, both single-pharmacy:

- **Ciprofloxacin** — chosen `₦5,180` for a **10**-pack (`₦518.00`/unit). A **14**-pack at `₦7,060`
  is `₦504.29`/unit, i.e. cheaper per tablet. The view calls the 10-pack cheapest.
- **Cefixime** — chosen `₦4,100` for a **60**-pack (`₦68.33`/unit). A **100**-pack at `₦5,160` is
  `₦51.60`/unit. Same error, larger.

A related data-quality signal fell out of the same query: **Atorvastatin, Lagos** has nine in-stock
listings at two pack sizes with prices from `₦2,760` to `₦35,460` for what the catalogue treats as
one product — a 13× spread. Either the matching is over-merging distinct strengths, or the listings
include different products. Not investigated here.

## Verified

```powershell
# 31 slash-titled latest HealthPlus rows, stored vs guarded, one by one
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -X utf8 "$env:TEMP\opencode\verify_t2.py"
# -> slash-titled latest HealthPlus rows: 31
#    stored pack non-null: 30 of 31
#    stored != guarded: 0
#    slash-titled rows reaching v_cheapest_per_product_state: 1, of which comparisons: 0

# pack-size-blindness of the ranking
.venv\Scripts\python.exe -X utf8 "$env:TEMP\opencode\arenax_check.py"
# -> cells: 85 | cells with >1 pack size: 15 | of those, chosen row is NOT the best per-unit: 9
```

Read directly: `schema/003_views.sql:80` — `order by b.price_ngn asc, b.pharmacy_id asc`.

## Deviations

- The agent did not write this report; it hit its 20-step cap at the falsification check. Its progress
  file (`.agent/T2-progress.md`) worked as designed — four lines, and it named the exact gap it had
  left rather than claiming completion.
- The agent's provisional verdict ("not a blocker today, guard still required") was **correct**, and
  its reading of the ranking column was **correct** — `PLAN.md:70` is the document that is wrong.

## Unproven

- Whether any HealthPlus title in the *catalogue* (not the latest 1,197) uses the bare `80/480 Tablets`
  form. Only the latest set was scanned.
- Whether ranking on `unit_price` is even viable: `unit_price` is populated on 52.7% of HealthPlus
  listings, and several cheapest cells have `unit_price IS NULL`.
- The Atorvastatin price spread — over-merged product, or genuinely different items.
