# T17 findings — independent audit of the stock fixes (`1c7b422`, `5d8fa0d`)

**Persisted by the secretary from the reviewer's own report.** The reviewer executed the checks but
could not write this file: its shell permission refused `Set-Content` and it had no file-writing tool.
Everything below is its account; the two items marked *(secretary)* were confirmed or closed by me.

## Verdict: ship with fixes — no blocking defects

Every falsifiable claim in the brief was reproduced against the live database, the live script, real
synthetic series and live product pages.

## Check 1 — view contract: pass

- `260` cells, `45` `is_comparison`. Matches.
- **23 columns**: the 20 old ones first with unchanged names and types, then
  `cheapest_pack_stock_confirmed:boolean`, `best_unit_stock_confirmed:boolean`,
  `confirmed_pharmacy_count:bigint`.
- Distribution: **18** cells with 0 confirmed pharmacies, **200** with 1, **42** with 2. Of the 200
  with one, 3 are `is_comparison` — the known caveat, correctly disclosed.
- `dashboard/app.py:238-241` selects by name, so appended columns cannot break it. **But the honesty
  signal exists only in SQL**: the caption at `app.py:230-237` still asserts "the comparison table is a
  real comparison: two or more pharmacies quote the same product in that state", and the three new
  columns are never read by the app.
- NULL is distinguishable from "no winner": every cell has a winner, so a NULL
  `cheapest_pack_stock_confirmed` means exactly "the winning row's stock was unreadable".

## Check 2 — blast radius: pass, one adjacent finding

- `v_suspicious_listings` reads `v_latest_listings ⋈ products ⋈ nafdac_registrations` — no dependency.
  Count `159`, unchanged.
- `mv_drug_price_index` (`schema/004_materialized.sql:8-23`) reads `price_history` and the base tables
  directly — no dependency. Count `403`, unchanged.
- `006` is `create or replace view` / `comment on` inside one transaction, so it is safe to re-run.
- **Should fix (not this ticket):** the same NULL-substituted-for-zero defect survives in
  `schema/004_materialized.sql:17` — `avg(case when h.in_stock then 1.0 else 0.0 end) as stock_rate` —
  which is published on the dashboard as "In stock" (`app.py:219`). An unreadable stock is counted
  there as not-in-stock, which is the same class of error this whole ticket exists to remove.

## Check 3 — read-only: pass

- `dbq.py` with a data-modifying CTE — `with doomed as (delete from pharmacy_listings where false
  returning id) select count(*) from doomed` — returned
  **`ReadOnlySqlTransaction: cannot execute SELECT in a read-only transaction`**. The server refuses the
  write even when the statement-level guard is bypassed. This is the defect that was found and fixed
  earlier in the day, re-tested by a second party.
- `stock_signal_watch.py:297-308` carries the same `options="-c default_transaction_read_only=on"`.

## Check 4 — alarm logic: pass

- Live: `exit 1`, `ALARM: MedPlus went from 0.6% to 100.0% unknown (day 2026-11-09, 128 rows written,
  128 unknown)`.
- `--as-of 2026-11-08`: `exit 0`, `ok: no source lost its stock signal`.
- Synthetic series, 3 clean days + k fully-unknown days:

  | k | verdict | prior median |
  |---|---|---|
  | 1 | alarm | 0.0% |
  | 3 | alarm | 0.0% |
  | 4 | **alarm** | **50.0%** |
  | 8 | **alarm** | **100.0%** |

  The medians show it directly: under the old median rule, k=4 and k=8 would have returned `ok`. The
  self-silencing bug is demonstrably fixed.
- **Fixed by the secretary after this report:** the module docstring still described the old median
  rule (the reviewer's "should fix"), and the constant is now `CLEAN_DAY_MAX_UNKNOWN_PCT` rather than
  `PRIOR_MEDIAN_MAX_UNKNOWN_PCT`, since it is the clean-day threshold, not a median test.
- **Threshold blind spots, accepted and worth stating:** a source whose normal day is already ≥10%
  unknown never has a "clean" day and so can never alarm; a source that drops under 50 rows a day is
  never judged (Drugstore.ng: 200 rows on 11-08, 2 on 11-09 → "one day"); and a parser that reads a
  *wrong* signal (all false rather than all NULL) is invisible to a monitor that only counts NULLs.

## Check 5 — live parser signal: 4 of 4 *(secretary closed the fourth)*

| page | known truth | hidden `name="quantity"` max | visible `max` |
|---|---|---|---|
| acneaway-cream-20g | unavailable | **0** | 50 |
| acyvir-aciclovir-eye-ointment | unavailable | **0** | 50 |
| abf-3-cream-20g | available | **145** | 50 |
| abidec-multivitamin-drops-25ml | available | **194** | 50 |

The reviewer read three and ran out of steps before the fourth; I read the fourth from the page it had
already saved (`max="194"`), and had independently fetched the same four pages earlier. The visible
`max="50"` is constant across all four, available and unavailable alike, which confirms it is a
per-order cap and not stock.

On "could `max` be a per-order cap somewhere": on these pages the `max=0` ones render "Notify me"
instead of "Add to cart", and the hidden count differs from the visible cap — so the hidden count
tracks stock. That rests on four pages from one template, not on the whole site.

## What the reviewer could not do

- `git show --stat 1c7b422` was refused by the shell permission (one attempt, not retried); it read the
  changed files directly instead, which is equivalent on a clean tree.
- Write this file.
