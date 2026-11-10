# Progress

Single state file for NaijaDrugWatch. Last updated **2026-11-10 06:50Z**.

## Handoff — state at close, 2026-11-10

Read this block only. Everything below it is history; the 2026-11-09 and 2026-11-08 snapshots are
superseded by the table here.

### Where it stands

**The schedule has now fired on its own, twice, and behaved correctly both times.** That was the
project's biggest open risk and it is closed:

| run | fired | gate said | what happened |
|---|---|---|---|
| 42604737743 | 2026-11-09 10:54Z (≈8 h late) | `stale` — 5 of 6 sources missing | ran the whole pipeline, 1 h 33 m, all steps `success` (`scrape_runs` 31-37) |
| 42658950671 | 2026-11-09 16:51Z | `fresh` — all 6 inside the window | **skipped the pipeline in 7 s**, nothing re-scraped |

Both halves of the anti-drop design are now proven against the real event: it runs when the day is
missing, and it stands down when the day is already there. GitHub delivers these fires with a
multi-hour delay — 03:00Z arrived at 10:54Z — so "4am" is the intent, not the schedule.

**The day's real discovery: a parser blind spot was being reported as an empty shelf.** MedPlus
rebuilt its product page on 2026-11-09. `scrapers/medplus.py` looked for an `<input class="input-number">`
that no longer exists, so all 128 rows that run wrote carried `in_stock = null` — 108 of them had been
`true` the day before. Because `v_cheapest_per_product_state` filtered `in_stock is true`, those rows
vanished: 18 cells and 2 comparisons. Nothing complained. It was found by eye the next morning.

### One authoritative snapshot (re-queried 2026-11-10, after these fixes)

| Object | Value |
|---|---|
| `products` / `drug_match_rules` | **1,433 / 1,433** |
| `pharmacy_listings` (latest) | **2,792** — MedPlus 1,391, HealthPlus 1,201, Drugstore.ng 200 |
| …of those, matched to a product | **575**; distinct products cited **338**. Down 5 from 580 because 43 rows from today's re-scrape have not been through the matcher yet |
| `nafdac_registrations` / with status | **10,912 / 1,848 (16.9%)** — the 2026-11-09 detail sweep raised it from 581 |
| `v_cheapest_per_product_state` | **260 cells, 45 `is_comparison`**, 18 with an unconfirmed winner — all Lagos |
| `v_suspicious_listings` | **159** — all one reason, `inactive_registration` (88 Inactive, 72 Expired); 12 of those products still form a two-pharmacy comparison |
| `mv_drug_price_index` | **403 rows over 3 days**; 23 groups have no readable stock, so their `stock_rate` is NULL rather than a false zero |
| `v_price_change_7d` | 0 rows — expected until 2026-11-14 |
| `scrape_runs` last ids | 41 (`medplus`, 25) on 2026-11-10; 31-37 the first automatic run |

### What changed today, file by file

| File | State | Why |
|---|---|---|
| `schema/006_stock_confidence.sql` | **new, applied live, committed `1c7b422`** | Base filter becomes `in_stock is not false`; ranking prefers a confirmed-in-stock row over a cheaper unconfirmed one; three columns appended (`cheapest_pack_stock_confirmed`, `best_unit_stock_confirmed`, `confirmed_pharmacy_count`). 242→264 cells, 42→45 comparisons when applied. Idempotent (re-applied four times). |
| `scrapers/medplus.py` | **modified, committed `1c7b422`** | Stock read from the add-to-cart form's hidden `name="quantity"` `max` (0 on unavailable pages, 145/194 on available ones), instead of the vanished `input-number` selector. The old selector is kept as a fallback consulted only when the new one finds nothing. |
| `scripts/stock_signal_watch.py` | **new, committed `1c7b422`** | Alarms when a source's share of unknown-stock rows jumps. Baseline is "this source has at least one prior clean day", not the median — the median version silenced its own alarm on the fourth broken day (proven with synthetic series). Read-only, enforced by `options="-c default_transaction_read_only=on"`. |
| `.github/workflows/daily.yml` | **modified, committed `1c7b422`** | One new last step (`continue-on-error`, `if: always()`), three job outputs, one notify branch. The three crons and the gate's `REQUIRED_SOURCES` are untouched. |
| `docs/views.md` | **modified, committed `1c7b422`** | Documents the new contract, the three columns, and why an unknown reading is counted rather than dropped. |
| `.agent/T14-report.md`, `T15-report.md`, `T16-report.md`, `T16-review-findings.md` | new | T15 and T16 reports are written by the secretary; both agents hit their step limits before writing one. |
| `schema/007_index_stock_confidence.sql` | **new, applied live, committed `2a16c29`** | Rebuilds `mv_drug_price_index` in one transaction. `stock_rate` no longer averages an unreadable row in as zero; a fully unreadable group returns NULL; `stock_read_rate` appended so the denominator is visible. 23 groups that previously published a false 0% now return NULL, 3 partial groups corrected, 377 unchanged. |
| `dashboard/app.py` | **modified, committed `2a16c29`** | Index tab shows the read rate and stops calling the figure a plain "In stock"; cheapest tab shows `Stock confirmed` ("not read" where we could not read it) and `Confirmed pharmacies`, with the caveat in the caption. Two edits, no redesign. |
| `scripts/envfile.py`, `scripts/dbq.py` | **new, committed `5d8fa0d`** | Make a reviewer able to run the project: scripts load `DATABASE_URL` from `.env`, and `dbq.py` runs one read-only query in one command (server-side `default_transaction_read_only`). |

### The process problem this exposed, which is bigger than the bug

**No independent execution-based review exists for today's work.** Two reviewer sessions were launched.
The first ran out of steps reading files and executed nothing — but did find two real defects (the
self-silencing alarm and stale documentation), both fixed. The second was **blocked from running any
program at all**: every non-git command, including `.venv\Scripts\python.exe -V`, was rejected with
`permission.rejected: shell`.

**Cause, found and fixed the same day.** Not a platform bug: the reviewer had `steps: 12` and a shell
allowlist that admitted `python *` but not the pinned interpreter path, while every command in this repo
needs a variable set first (`$env:DATABASE_URL = ...; python ...`). The permission matcher tests one
command against one pattern, so the two-part command was refused as a whole.

The fix has three parts:

- `scripts/envfile.py` — scripts load `DATABASE_URL` from `.env` when it is not already set, so no
  command needs a variable prefix. An already-set variable always wins, so a workflow secret is never
  overridden by a file.
- `scripts/dbq.py` — one command that runs a single read-only query. Guarded twice: it refuses anything
  that is not `select`/`with`, and the connection carries `default_transaction_read_only=on`, so the
  server refuses a write even inside a `with` (`ReadOnlySqlTransaction`, verified with a
  `with ... (delete ...) select`).
- The reviewer agent now has `steps: 30`, the pinned interpreter in its allowlist, and a section
  telling it to use `dbq.py` instead of chaining commands.

**Verified by spawning a reviewer with three commands**: it ran the query (`260 / 45`), `git log`
(`1c7b422`) and the watch script (ALARM + exit 1), all permitted, and answered "can you run this
project's code — yes". So the next review in this repo can be an audit rather than a read-through.

That fix is tooling, not verification. **The audit was then run properly** (`.agent/T17-findings.md`):
it executed every check, reproduced 260/45, proved the read-only connection blocks a `with`-wrapped
delete server-side, re-ran the alarm on synthetic series and closed 4 of 4 parser pages. Verdict: **no
blocking defects, ship with fixes** — the two it raised (a stale docstring, the dashboard not showing
the new columns) were fixed the same day.

**Still unaudited:** `2a16c29` (the index rebuild) and `683e266` (the licence labels). Both were verified
by the secretary only. Aim the next review at those two.

### State at pause — 2026-11-10 06:50Z

- **Two files on disk, uncommitted and deliberate:** `scripts/crosscheck_pages.py` (works; its first
  pass was cut short by a 429) and `.agent/eyeball-sheet.md` (**superseded — do not use it**).
- **2026-11-10's scheduled fire had not arrived** by 06:50Z. It was due 03:00Z; 2026-11-09's first fire
  arrived 7 h 54 m late, so this is within the observed range and not yet a fault.
- **The rate limit is the live risk, not a curiosity.** HealthPlus returns `429` to this machine after
  today's probing. If the nightly job runs while that holds, `healthplus` fails, and by the gate's own
  rule a day where one source fails does not count as done.
- Last verified database reading: 260 cells / 45 comparisons / 159 suspicious / 403 index rows.

### Open, in priority order

1. **Slash strengths still refuse real drugs.** `AMATEM 20/120MG`, `COARTEM 80/480` parse as one token
   while the register writes `20 mg; 120 mg`: 610 pairs rejected as "strength disagrees". The rejection
   list is dominated by first-line antimalarials. Cheapest next win, unchanged from yesterday.
2. **Most of MedPlus's catalogue still carries the 2026-11-09 null reading** — 43 of 1,405 rows
   re-read. The nightly run fixes it by collecting; nothing needs repairing by hand.
3. **`mv_drug_price_index` is still unprotected from suspect prices**, and is an index of *new* prices
   per day, not of the market. Its stock figure was fixed on 2026-11-10 (`schema/007`): unreadable rows
   are no longer averaged in as zero and a fully unreadable group now returns NULL. The price columns
   still have no `price_suspect` filter. Must not be published as a market average without a relabel.
4. **`v_pipeline_health` cannot see a source that never ran** — zero rows means zero output, not
   `STALE`. The gate works around it; the view is still wrong for anyone else.
5. **The dashboard is not deployed** and there is no public interface. Two of the four
   definition-of-done items.
6. **`unit_price` coverage is 52.7%** on HealthPlus against an 85% gate.

### Decisions taken 2026-11-10 — do not re-open without a new reason

| Decision | What was chosen | Why, and what it cost |
|---|---|---|
| What "comparison" means | **Keep it as it is**: two pharmacies publishing a price for the same product. 45 entries. | 3 of the 45 rest on one shop we can see holding the item and one we cannot. Tightening to "two confirmed shops" would give 42 and would make the comparison count hostage to the other shop's page markup — the failure mode that cost two comparisons on 2026-11-09. The caveat is on screen instead. |
| Drugs whose NAFDAC registration is inactive or expired | **Label them**, in the price table and on the dashboard. Do not hide them, do not leave them silent. | 159 listings; 12 of their products still form two-shop comparisons. The finding is the point of the project, so it stays — but a reader must be able to see it. Implemented as `schema/008` with three states: active / not active / not read. |
| Eyeballing real pharmacy pages | **Last thing**, and **automate the mechanical part**. | The 20-minute manual sheet was withdrawn: fetching a page and comparing a pack size is work a machine should do. `scripts/crosscheck_pages.py` reads each shop by a different route from the scraper — HealthPlus through its storefront JSON rather than HTML. **But MedPlus has no second server-side source**: its page carries exactly one price, in the same `data-product-price` attribute the scraper reads, so an automated re-read there catches drift, not a parsing error. A rendered browser is the only independent read for that shop. The human part is reduced to reading the mismatch list. |

### Before anything is published

- **Run the cross-check over all 45 comparisons** (`scripts/crosscheck_pages.py --all`) and read the
  mismatch list. As of the pause it has only reached 5 MedPlus pages — all agreeing — because
  HealthPlus was returning **429 Too Many Requests** to this machine after too much ad-hoc probing.
  A completed pass, not a page-by-page tick, is the evidence bar.
- Compare one suspicious listing against a rendered NAFDAC record. **159 rows, none checked.**
- View the cheapest-per-state table at 430 px. Measured for overflow, never looked at.
- Say "cheapest among the online pharmacies that publish prices — Lagos, two shops". Never
  "cheapest in Lagos".
- Disclose that only 16.9% of the register has a status, so "suspicious" describes a fraction.

### Resume commands and gotchas

Unchanged from 2026-11-09 — the ordered command list and the environment traps (VPN, cp1252 console,
`%%` in psycopg, expired Greenbook TLS) are in the block below and are still correct. Two additions:

- `scripts/stock_signal_watch.py` runs **after** `REFRESH MATERIALIZED VIEW`, last, and must never be
  moved into the gate's required sources.
- `schema/006_stock_confidence.sql` is safe to re-run at any time; it is `create or replace view` in a
  transaction and was applied four times on 2026-11-10 with identical results.

### Unproven

- **GitHub Actions has never executed today's changes.** `continue-on-error` keeping the job green is
  documented behaviour, not observed. The first night it matters is its first test.
- **The page cross-check has not completed a pass.** Five MedPlus pages agreed exactly; HealthPlus
  refused the rest with `429`. Until a full run finishes, every "cheapest" claim is still arithmetic.
- **MedPlus has no independent server-side source.** Its page carries one price, in the same field the
  scraper reads. Only a rendered browser can give that shop a genuinely second opinion.
- **`2a16c29` and `683e266` have had no independent audit** — secretary verification only.
- **The alarm threshold** (10% / 25% / 50 rows) is a judgement fitted to one real event.
- **The magnitude of the stock count is not interpreted** — zero versus non-zero only. A template that
  used `max` as a per-order cap would read as a confident "in stock" and the monitor would not see it.
- **2,217 of 2,792 latest listings are unmatched** — no product to attach them to. The register cannot
  resolve all of them at all; the slash-strength rule is what is blocking the antimalarials.

---

## Handoff — state at close, 2026-11-09 (historical)

The figures tabulated here on 2026-11-09 have been **deleted rather than corrected** — a second copy of
a moving number is how this file drifted twice. What that day established is in the prose below; the
live set is in the block above.

### Where it stands

The pipeline works end to end, the catalogue is a third bigger than yesterday, and the daily job has
been rebuilt to survive a dropped trigger — but **it has still never fired on its own.** One green
run exists (42464123751, 2026-11-08, manual, 1 h 32 m). Zero `schedule` events in the repo's history.

### One authoritative snapshot — **deleted, see the 2026-11-10 block above**

The 2026-11-09 table held 2,779 listings / 260 cells / 44 comparisons / 132 suspicious / 340 index
rows. All of those numbers have moved. They are recorded here as prose rather than as a table so they
cannot be quoted as current.


### What changed today, file by file

| File | State | Why |
|---|---|---|
| `.github/workflows/daily.yml` | **committed `bf07881`**, +116 −0 | Three fires (03:00, 04:17, 06:43 UTC); `freshness` gate job; `pipeline` gated on it; `notify` job on `always()` opening one deduplicated issue per reason. |
| `scripts/freshness_gate.py` | **new, committed `bf07881`** | Decides from `scrape_runs` (never `v_pipeline_health`) whether the day has run. Requires a success from **all six** steps inside the 03:00 window. Exit 2 when it cannot decide. |
| `scripts/match_listings.py` | committed `bf07881` | Writes a `scrape_runs` row (success/failure). Body re-indented inside `try`; logic unchanged. Dry runs write nothing. |
| `scripts/link_product_nrn.py` | committed `bf07881` | Same ledger row, same reason. |
| `scripts/expand_catalogue.py` | **new, committed `bf00c2d`** | Turns unmatched shop titles into products, using the NAFDAC register as the authority. Dry-run default; `--apply` needs `--i-know-this-writes`. |
| `PROGRESS.md` | committed | This file. |
| `.agent/T10-evidence.md`, `T10-report.md`, `T10-review-findings.md` | committed | The schedule fix: evidence, verification, the reviewer's two findings (both fixed as T12). |
| `.agent/T13-dryrun.txt` | committed | The full pre-write expansion report the user approved. |

`*‑brief.md` and `*‑progress.md` under `.agent/` are gitignored by design.

### The three things that matter tomorrow

1. **04:00Z is the first scheduled fire in the project's life.** If it lands, check that the gate
   reasoned correctly and that `scrape_runs` gained rows for all six steps. If it does not land,
   check 05:17Z and 07:43Z before concluding anything — that is what they are there for.
2. **If all three are dropped, nothing reports.** The notifier only speaks when the workflow runs.
   Closing that gap needs an external heartbeat hitting `workflow_dispatch`, which is a new
   third-party dependency and a token: the user's decision, not a default.
3. **The 44 comparisons have never been checked by eye.** Open two pharmacy pages, confirm the same
   pack is priced. This is the credibility gate for every "cheapest" claim and no agent can do it.

### Open, in priority order

1. **Slash strengths refuse real drugs.** `AMATEM 20/120MG`, `COARTEM 80/480` parse as one token while
   the register writes `20 mg; 120 mg`, so 610 pairs are rejected as "strength disagrees" that are the
   same drug — including two first-line antimalarials. Same defect already logged for `parse_pack` on
   Drugstore.ng. Fixing it is the cheapest next win.
2. **`mv_drug_price_index` is unprotected** from suspect prices and, separately, is an index of *new*
   prices per day (83 cells on day 1, 56 on day 2, from 2,709 and 1,293 price rows). It must not be
   published as a market average without a relabel or a recompute from `v_latest_listings`.
3. **`v_pipeline_health` cannot see a source that never ran** — zero rows means zero output, not
   `STALE`. The new gate works around it by reading `scrape_runs` directly; the view itself is still
   wrong for anyone else who reads it.
4. **The dashboard is not deployed and there is no public interface.** Two of the four
   definition-of-done items.
5. **`unit_price` coverage is 52.7%** on HealthPlus (631/1,197) against an 85% gate.

### Before anything is published

- Open two pharmacy pages and confirm the same pack. **44 comparison cells, none checked.**
- Compare one suspicious listing against a rendered NAFDAC record. **132 rows, none checked.**
- View the cheapest-per-state table at 430 px. Measured for overflow, never looked at.
- **Describe the state honestly.** The `state` column is the pharmacy's own location, not a price
  dimension: all three sources publish exactly one price per product and none of them carries a state
  input (evidence in the decisions table, 2026-11-09). Say "cheapest among the online pharmacies that
  publish prices", scope Lagos. Do not imply a national or state-by-state comparison exists.
- State the scale honestly: **Lagos, two pharmacies, 44 products.** That is a demonstration, not a
  national price index.

### Resume commands, in dependency order

```powershell
$env:DATABASE_URL = ((Select-String -Path .env -Pattern '^DATABASE_URL=').Line).Substring(13).Trim()
$env:PYTHONIOENCODING = 'utf-8'
```

```powershell
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_index.py
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_details.py --min-similarity 0.50
.venv\Scripts\python.exe -X utf8 scripts\link_product_nrn.py --refresh --min-similarity 0.35
.venv\Scripts\python.exe -X utf8 scrapers\healthplus.py
.venv\Scripts\python.exe -X utf8 scrapers\medplus.py --categories 12,31,32,50,57,58
.venv\Scripts\python.exe -X utf8 scrapers\drugstore.py --limit 200
.venv\Scripts\python.exe -X utf8 scripts\expand_catalogue.py            # dry run; add --apply --i-know-this-writes
.venv\Scripts\python.exe -X utf8 scripts\match_listings.py
.venv\Scripts\python.exe -X utf8 -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'],autocommit=True).execute('refresh materialized view concurrently mv_drug_price_index')"
```

Order is not optional. A scrape un-matches what it re-inserts, so skipping the matcher makes the views
shrink. `expand_catalogue.py` runs **before** the matcher: it inserts products, and the matcher is what
attaches listings to them.

### Unproven

- **The schedule.** Built, reviewed, verified by hand in eight states, and never once fired.
- **The 44 comparisons.** Computed, never eyeballed.
- **The 359 new products' shelf reality.** Each is backed by a registration and a shop title, but no
  human has confirmed that a pharmacy actually stocks that pack.
- **`mv_drug_price_index` as a market measure.** It counts what was newly observed, not what is live.

### Environment gotchas that still apply

- **VPN:** a Proton VPN tunnel resets Neon's 5432 inside it. Run the bogus-hostname control first if
  the database stops answering. This cost a session on 2026-11-08.
- **Console is cp1252:** always `-X utf8`, or `₦` raises.
- **This shell mangles embedded newlines:** put multi-line work in a file.
- **`percent` in psycopg:** no `%%` escaping is needed when the query has no parameters; `%%` becomes
  a literal operator error.
- **Greenbook TLS is expired:** `common.RateLimitedClient` falls back to HTTP per host and records the
  downgrade. Say so in the published limitations.

## 2026-11-09 — catalogue expanded by a third; comparisons nearly doubled

The product list was the binding constraint, not scraper volume: 88% of the 2,779 live prices had no
product to attach to, and the #FixMedPrices seed is a national **commodities** list (mosquito nets,
female condoms, an HIV test kit, Rituximab), not a pharmacy shelf list. It carried only 14 malaria
names, 9 hypertension, 8 diabetes and 12 antibiotics. Sampled unmatched shop titles — Crestor,
Tums, pyrantin, Simbrinza, orphenadrine — existed nowhere in it.

`scripts/expand_catalogue.py` (new) turns unmatched shop titles into products using the NAFDAC register
already on disk as the authority. A pair is accepted only when the name overlaps **and** the strength
agrees (or one side is silent) **and** the dosage form is compatible; the strength/name/form parsers
are imported from `link_product_nrn.py`, not re-written. Dry-run by default; `--apply` additionally
requires `--i-know-this-writes` and refuses before opening a connection otherwise.

**Measured, from the live database, before → after:**

| Object | Before | After |
|---|---|---|
| `products` / `drug_match_rules` | 1,074 / 1,074 | **1,433 / 1,433** |
| `v_latest_listings` matched | 342 (one in eight) | **580 (one in five)** |
| Distinct products cited by a shop | 158 | **338** |
| `v_cheapest_per_product_state` cells | 118 | **260** |
| …`is_comparison` (two pharmacies) | **24** | **44** |
| `v_suspicious_listings` | 127 | 132 |
| `mv_drug_price_index` | 139 | 340 |

Insert order was: apply (359 products + 359 rules) → `match_listings.py` (355 rows attached, 10.4% of
the 3,428 unmatched) → `REFRESH MATERIALIZED VIEW CONCURRENTLY`. `scrape_runs` id 29 (expand) and 30
(match) both `success`. Duplicate triples: **0**. New products without a registration number: **0**.
One near-duplicate was skipped by decision — Meloxicam 7.5 mg, already present as `tab-cap` where the
register says `Tablet`.

**What this does not fix, and now shows up as a measured cost.** The tool's own rejection list is
dominated by pairs that are obviously the same drug: `AMATEM 20/120MG * 12 SOFTGEL` against
`Amatem 20/120 Softgel`, `MAXITROL EYE DROP 5ML`, `PANADOL EXTRA *20 CAPLETS`, `ZENTEL SUSPENSION
20ML`. They are rejected as "strength disagrees" because a slash strength (`20/120MG`) parses as one
token while the register writes `20 mg; 120 mg`. This is the same slash-strength defect already
recorded for `parse_pack` in Drugstore.ng, now measurably excluding valid products — Amatem and
Coartem are first-line antimalarials.

**Known limitation, unchanged:** a brand and its generic are separate products (e.g. `Glucophage
500 mg` and `METFORMIN TABLETS 500MG`). Cells still compare only like with like, so no comparison is
false, but the product count counts a drug twice when the shop lists it both ways.

## 2026-11-09 — the cron has never fired on schedule, and the index thins on day 2

Re-queried against the live database (VPN disconnected, connection confirmed PG 17.11).

### `schedule` has produced zero runs, ever

`.github/workflows/daily.yml:18` is `cron: "0 3 * * *"`. `gh workflow list` reports `daily active`.
`gh run list --limit 10` returns **five runs, all `event=workflow_dispatch`** — there is no
`schedule`-triggered run in the project's history. At 05:10Z on 2026-11-09 the day's fire was
2 h 10 m overdue, and `select count(*) from scrape_runs where started_at >= '2026-11-09'` returned
**0**. So the seven-consecutive-days gate has not started: yesterday's green run
42464123751 was dispatched by hand.

GitHub documents cron delay under load as minutes-to-hours, so a single miss is not proof of a fault.
**The evidence that matters is the history: 0 schedule events, not 0 today.** Watch 2026-11-10 03:00Z
before concluding either way. A failure-notification step must not be mistaken for a fix — a notifier
on a schedule that never fires is silent in the same way.

### `mv_drug_price_index` is an index of *new* prices, not of the market

| Day | `price_history` rows | mv cells |
|---|---|---|
| 2026-11-07 | 2,709 | 83 |
| 2026-11-08 | 1,293 | 56 |

The definition (`pg_get_viewdef`) joins `price_history` → `pharmacy_listings` → `products` and groups
by Lagos-local day. `record_price_history()` writes one row **per new listing**, so a day's cells
count only what was newly observed that day, not what is live. Day 2 has 2,779 live listings and 118
cheapest-per-state cells, yet the index shows 56 — the label "daily price index" overstates what it
measures. Not proven to be misleading (no consumer has read it as market-wide), but it must not be
published as a market average without a relabel or a recompute from `v_latest_listings`.

### Live coverage, same query

| Pharmacy | `unit_price` known / latest | Share |
|---|---|---|
| HealthPlus | 631 / 1,197 | **52.7%** — still under the 85% gate |
| MedPlus | 1,008 / 1,382 | 72.9% |
| Drugstore.ng | 55 / 200 | 27.5% |

`select count(*) from pharmacy_listings where price_suspect=false and price_ngn < 20` → **0**, so the
suspect-price flag has not decayed yet: nothing has been scraped since `schema/005` was applied.
`v_price_change_7d` is still 0 rows, still expected until a second scrape ≥7 days after the first.

## Handoff — 2026-11-08 (historical; its numbers are superseded by the block at the top)

### Where it stood at session end

The pipeline works end to end. Three pharmacies are loaded, the matcher runs, and the dashboard shows
both a cheapest-pack and a lowest-known-unit-price answer per row.

`.github/workflows/daily.yml` is the scheduler. **Run `42464123751` completed green on 2026-11-08**
(dispatched 08:43 UTC, finished 10:15 UTC, 1 h 32 m) — the first successful execution, and still the
only one.

The figures formerly tabulated here (2,779 listings / 118 cells / 24 comparisons / 127 suspicious /
139 index rows) have been **deleted rather than corrected**, because a second copy of a moving number
is how this file drifted once already. The live set is in the handoff at the top of this file. What
that day established — what the run wrote, and why — is in the prose below.


### The daily run works — run 42464123751, green

First successful execution, 2026-11-08, **1 h 32 m**, every step `success`. What it wrote:

| Source | `scrape_runs` | Records |
|---|---|---|
| `nafdac_greenbook` | 24 | **10,912** (up from 10,906 — the register is alive) |
| `nafdac_details` | 25 | 576 |
| `healthplus` | 26 | 1,194 |
| `medplus` | 27 | **833** |
| `drugstore` | 28 | 200 |

`v_pipeline_health` reports **OK for all five sources**, and `mv_drug_price_index` now holds two days
(2026-11-07 and 2026-11-08), so the refresh step works from the runner. `v_cheapest_per_product_state`
is **118 cells / 24 comparisons**; `v_suspicious_listings` 127. Suspect prices stayed out:
0 rows under ₦20 in `v_latest_listings`, lowest price ₦50.

**A coverage caveat this exposed.** The workflow runs `medplus.py` with `MAX_PAGES = 40`, so it
discovers **833** products, against **1,395** in a manual run with `--max-pages 80`. The daily job is a
subset of the catalogue, which is why it finishes in 1 h 32 m rather than the ~3 h the missing
`--limit` suggested. That is a coverage decision to make deliberately, not a bug — but do not read
"green" as "whole catalogue".

### What this session produced, and what to trust

| Item | Evidence |
|---|---|
| `scrapers/drugstore.py` | run 21 success, 20 records, gate verified against the DB |
| MedPlus category 12 | run 23 success, 1,391 records, 1,092 inserted, 64 → 24 comparisons after matching |
| View carries two answers | `schema/003_views.sql`, verified: 20 columns, 0 NULL-rule leaks, 0 recompute diffs |
| Dashboard shows both | axe 0 violations on all five tabs, both answers rendered |
| Suspect prices flagged | `schema/005_suspect_prices.sql`, 14 rows, `v_latest_listings` 2,613 → 2,599 |
| Prices refused at the door | `price_bounds_error()`, 24/24 boundary cases across three scrapers |
| Daily workflow | `.github/workflows/daily.yml`, first run dispatched |

**Do not trust a subagent's summary without re-running its check.** Four of the six tickets this
session hit their step cap mid-gate and the secretary finished the verification. Where a number
matters, the artifact is in `.agent/T<n>-report.md`.

### The failure that cost the most time

Four dispatches failed before the workflow got past preflight. The cause was **not** the database: the
`DATABASE_URL` secret held a 28-character string starting with `t` and containing no `://`, against the
real value's 120 characters. Two of the four runs were avoidable — one was a *re-run*, which replays
the old commit and cannot pick up a newer workflow file, and one added a normalisation step before
anyone looked at what the value actually was. **If a connection string misbehaves, fingerprint it
first** (length, `://` present, sha256 prefix) before adding tolerance for how it might be mangled.

### Resume commands, in dependency order

```powershell
$env:DATABASE_URL = ((Select-String -Path .env -Pattern '^DATABASE_URL=').Line).Substring(13).Trim()
$env:PYTHONIOENCODING = 'utf-8'
```

```powershell
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_index.py
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_details.py --min-similarity 0.50
.venv\Scripts\python.exe -X utf8 scripts\link_product_nrn.py --refresh --min-similarity 0.35
.venv\Scripts\python.exe -X utf8 scrapers\healthplus.py
.venv\Scripts\python.exe -X utf8 scrapers\medplus.py --categories 12,31,32,50,57,58 --limit 250
.venv\Scripts\python.exe -X utf8 scrapers\drugstore.py --limit 200
.venv\Scripts\python.exe -X utf8 scripts\match_listings.py
.venv\Scripts\python.exe -X utf8 -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'],autocommit=True).execute('refresh materialized view concurrently mv_drug_price_index')"
```

Order is not optional. **A scrape un-matches what it re-inserts** — new rows have `product_id` NULL
and `v_latest_listings` takes the newest per URL — so skipping the matcher makes the views shrink.

### Open, in priority order

1. **`mv_drug_price_index` is unprotected** from suspect prices. It reads `price_history`; a filter
   needs drop + create + rebuild the unique index + refresh, in one transaction.
2. **`v_pipeline_health` cannot see a source that never ran** — zero rows means zero output, not
   `STALE`. P7's gate cannot be trusted until this is fixed.
3. **The dashboard is not deployed and there is no API.** Two of the four definition-of-done items.
4. **The daily run is ~3 h 15** because `medplus.py` has no `--limit`; the rate limit sets the floor
   every night. Freshness-versus-cost decision, not a bug.
5. **`unit_price` coverage is 52.7%** on HealthPlus against an 85% gate; P4 is open on that alone.

### Human-only, before anything is published

- Open two pharmacy pages and confirm the same pack is being priced. 24 comparison cells, none checked.
- Compare one suspicious listing against a rendered NAFDAC record. 124 rows, none checked.
- Look at the cheapest-per-state table at 430 px — measured for overflow, never seen.

### Next three actions

1. Read run `42464123751`'s outcome and fix or confirm it.
2. Add a `if: failure()` step that opens an issue, so a 03:00 failure is not silent.
3. Deploy the dashboard, then build the read-only API.

## 2026-11-08 — VPN outage, Drugstore.ng added, accessibility gate closed

### Afternoon: MedPlus expanded, the matcher restored, and the view answers two questions

Run against a working database, in this order: MedPlus expansion → matcher → matview refresh → T3.

| Object | Before | After |
|---|---|---|
| `pharmacy_listings` (latest) | 1,530 | **2,613** |
| HealthPlus matched / latest | — | **228 / 1,197** |
| MedPlus matched / latest | 20 / 313 | **110 / 1,396** |
| `v_cheapest_per_product_state` | 83 rows, 6 comparisons | **115 rows, 24 comparisons** |
| `mv_drug_price_index` | 83 | **135** |

**MedPlus category 12: 1,395 fetched, 1,391 records, 4 parse failures.** `scrape_runs id=23
success record_count=1391`, `inserted=1092 unchanged=299 price_history+=1092`, archive
`medplus-2026-11-08.jsonl.gz` sha256 `635cd866eacdace1`. Pack parsed 1,070 (77%), `unit_price` 1,007
(72%) — better coverage than HealthPlus's 53%.

**Comparisons went 6 → 24 after `scripts/match_listings.py`.** Matching is therefore the gate on the
headline metric, not the catalogue size: the 1,092 new listings were worthless until matched.

**A scrape silently un-matches what it re-inserts.** A changed URL gets a new `pharmacy_listings` row
with `product_id` NULL, and `v_latest_listings` takes the newest row — so the previously matched row
stops counting until the matcher runs again. This is the most likely explanation for
`v_cheapest_per_product_state` falling 85 → 83 across the MedPlus run while the view was provably
complete (independent expected cells 83, view rows 83, 0 missing). It means **scrape → match is one
step, and skipping the match step degrades the views.** P7 is what would make that automatic.

**Defect: ₦1.00 prices pass the guard.** Three MedPlus listings are priced ₦1.00, marked in stock, and
are ordinary products (`SUPRALIP 160MG *30TAB`, `STILBESTROL 5MG` ×2). The scraper rejects `price <= 0`
and `> 500000`, so ₦1.00 is accepted. A ₦1 row wins every `min()`-based view. They do **not** reach
`v_cheapest_per_product_state` only because they are unmatched — luck, not design. A second cluster at
₦10.97–10.99 (tourniquet, eyewash, emergency blanket) is `in_stock = false`, so the view's `in_stock
is true` filter excludes it. **Open.**

### T3 — the view now answers both questions (additive, verified)

`schema/003_views.sql:41-156`. The original 10 columns are unchanged in name, type and position; two
groups are appended: `cheapest_pack_*` (lowest `price_ngn`, the old answer now named) and `best_unit_*`
(lowest `unit_price`, every column NULL together where the unit price is unknown).

Verified by the secretary, not taken from the agent's report: 20 columns in the expected order, **0**
legacy-vs-`cheapest_pack_*` mismatches, **0** NULL-rule leaks in either direction, **0** differing rows
against an independent `distinct on` recompute.

The agent reported the row count as 85. **It is 83**, and the view is complete — see the un-matching
note above. Recorded because a passing gate reported against a stale baseline is how a wrong number
gets adopted.

**Open design defect the view exposes: `best_unit` can be worse value than the cheapest pack.** It
ranks only rows whose pack size parsed, so where the cheapest pack has an unknown unit the "best value"
column surfaces a pricier row instead of saying it does not know. Ibuprofen (suspension), Lagos:
cheapest pack ₦1,130 for a bottle of unknown volume, "best value" ₦25.00/ml for a 60 ml bottle at
₦1,500 — if the ₦1,130 bottle is also 60 ml it is ₦18.83/ml, better and invisible. **23 of 115 cells**
mix known and unknown pack units, so this is not a corner case. The label must not claim "best value"
on that basis.

Checked and **not** a problem: the matcher does not merge dosage forms. **0 cells mix `ml` with `tab`**;
`product_id` separates suspensions from tablets correctly.

### T5 — suspect prices are flagged, not deleted

`schema/005_suspect_prices.sql`: `pharmacy_listings.price_suspect` (`NOT NULL DEFAULT false`), every
stored row under **₦20** flagged (**14** rows: three at ₦1.00, eleven at ₦10.97–11.00), and
`v_latest_listings` redefined to exclude flagged rows. Nothing deleted, no price rewritten — all 14 rows
are still in the table.

| Gate | Value |
|---|---|
| `v_latest_listings` | 2,613 → **2,599** (delta 14) |
| Lowest price in it | **₦50.00**, 0 rows under ₦20 |
| `v_cheapest_per_product_state` | **115 / 24 comparisons** — unchanged |
| `mv_drug_price_index` | 135 rows, min ₦140 — untouched |

₦20 is the threshold because the data has an empty band: nothing between ₦11 and **₦50**.

**Three limits, all deliberate:**

1. **The flag decays.** New rows default `false`, so a future ₦1 listing is stored *unflagged* and
   stays visible until `005` is re-run. **T5 fixes what is stored, not the next scrape.** Build-time
   rejection in the three scrapers is the durable fix and is not built.
2. **`v_price_change_7d` is unprotected** — it selects `from pharmacy_listings` directly
   (`schema/003_views.sql`), not from `v_latest_listings`. It returns 0 rows today, which hides it.
3. **`mv_drug_price_index` is unprotected** — it reads `price_history`. Clean today only because 0
   `price_history` rows under ₦20 have a matched product.

**Also found:** `healthplus.py:304` rejects only `price <= 0` on the insert path. `ABSURD_PRICE_NGN`
is computed at `:509` **for the report only** and never enforced, so a ₦900,000 typo would be stored.
The earlier audit fixed the zero-price case; the upper bound has never been enforced.

### P7 — the daily workflow exists, and has never run

Scheduler is **GitHub Actions cron**, not Prefect (decision 2026-11-08). `.github/workflows/daily.yml`
runs the whole pipeline in one job in dependency order: index → details → link → healthplus → medplus →
drugstore → match → refresh. Steps fail individually so one source cannot stop the rest; the job still
exits non-zero if anything failed. The embedding model is cached across runs, and archives go up as a
14-day artifact because they are gitignored.

Recorded as a **spec deviation** in `AGENTS.md`: the spec names `flows/` as a Prefect deliverable and
that file does not exist. Cost of the swap — no retry engine, no run history beyond the Actions UI, no
backfill button — is to be stated in the published limitations.

**Unproven: it has never executed.** It parses (7 steps; `schedule` and `workflow_dispatch`), and every
flag it calls was checked against the scripts' argparse. Run `42464123751` (2026-11-08) is the first to
get past preflight and was still inside `Pipeline` at shutdown; its outcome is recorded by the next
session, not here.

**Four failed dispatches before it, and the cause was the secret, not the workflow.** The first run
failed all eight steps in 74 seconds. A preflight step was added to say why; it reported that
`DATABASE_URL` was set but `urlsplit` found no scheme. A fingerprint step then showed the stored secret
was **28 characters starting with `t`, with no `://`**, against the real value's **120 characters** —
a different string entirely. Fixed by `gh secret set DATABASE_URL` from the local `.env`. Two of those
four runs were wasted: one was a *re-run*, which replays the old commit and cannot pick up a new
workflow file, and one added a normalisation step before checking what the value actually was.

**Cost note for the daily schedule:** `medplus.py --categories 12,31,32,50,57,58` has no `--limit`, and
category 12 alone is 1,395 products at a 2 s rate limit, so the step is ~2 h10 and the whole run ~3 h15
— inside the 5 h job cap, but it means MedPlus's rate limit sets the floor for every daily run. Bounding
it (a `--limit` with rotating categories, or weekly full sweeps) is a freshness-versus-cost decision,
not a bug.

### T2 — the `unit_price` slash-strength defect does not affect stored data

31 latest HealthPlus rows contain a slash pair; **0** have a stored pack differing from the guarded
parse; 30 of 31 have a non-null pack. HealthPlus writes strengths with the unit attached (`80/480Mg`),
so `parse_pack` takes the explicit `x28` instead. The bug fires on `80/480 Tablets` — space, then a
form word — which HealthPlus does not use. Not a publication blocker today; the guard is still worth
adding to `healthplus.py`. Full evidence: `.agent/T2-report.md`.


**RESOLVED — cause was the local Proton VPN, not Neon.** Both connection strings failed identically
(`ConnectionTimeout`, preceded by "server closed the connection unexpectedly") while DNS resolved and
the console showed the project healthy. The finding that settled it was a **control experiment**: a
deliberately impossible hostname (`ep-zzzzzzzz-000000.c-7…`) failed in exactly the same way — same
wildcard DNS, same TCP accept, same TLS reset — so nothing endpoint-specific was involved.
`Find-NetRoute` then showed all three Neon edge IPs routing via **`ProTUN`** (Proton VPN). Neon's TLS
on port 5432 is reset inside that tunnel. Disconnecting the VPN restored both hosts immediately.

Cost: most of a session. The misleading signals were all real — console healthy, status page
operational, port 5432 open, 45 MB of data intact, quota at 1.22/100 CU-h. **Next time this shape
appears, run the bogus-hostname control first**; it takes one call and rules the database out.

Two jobs died during the outage and **neither wrote anything**:

| Job | Outcome |
|---|---|
| `scrapers/medplus.py --categories 12 --max-pages 80` | Failed at `db_connect` before the first category fetch. No `scrape_runs` row (the handler requires `run_id`), no archive, no listings. `medplus_expand.log` holds only the failure |
| `dashboard/app.py` axe audit | Not possible while down. The dashboard did render a **clean error state** ("Database unavailable: OperationalError…") rather than a traceback — new evidence for the empty-state gap below |

**Drugstore.ng: price does NOT vary by state route — verified by hand, not from the agent's report.**
Fetched `https://drugstore.ng/product/coartem-80480-tablets-artemether-lumefantrine` and the same
URL with `?state=kano`: **byte-identical**, sha256 `1A33F0288D445538…`, 93,435 bytes / 93,295 chars.
The 908 state/LGA URLs are delivery landing pages carrying no prices. This closes
`PLAN.md` §12's first open question.

Two things the probe also produced, both of which matter more than the answer:

1. **Currency is provable from the payload.** A JSON-LD block carries
   `"priceCurrency":"NGN","price":9350,"availability":"…InStock"` — the same class of structured
   evidence as HealthPlus's `Shopify.currency`, so no currency needs to be assumed.
2. **Each product page is one named seller with its own state:**
   `company:{company_name:…, state:"Lagos", pcn_license_…}`. So drugstore.ng is a marketplace with a
   per-offer seller, not "one national price". It still cannot create `is_comparison` cells — one
   seller per page — but the seller carries a real state, which is a modelling choice, not a fact.

**Decided 2026-11-08.** One `pharmacies` row for `Drugstore.ng` with `state = 'National'`; the seller
name and seller state are kept in the JSONL archive only. Rationale: sellers multiply pharmacy rows
and the `is_comparison` semantics before we know whether any two sellers duplicate a drug. Revisit
after measuring seller density — if two sellers carry the same product, seller-as-pharmacy becomes a
genuine comparison source and earns the schema change.

**Agent-reported, NOT independently verified** (`builder`, `ses_e46ce33f4ffeAki7ESf0q1TA0q`, step
budget exhausted): the live sitemap holds 16,241 `<loc>` entries — 11,157 `/product/`, 1,182
`/medicines/`, 908 state/LGA — which makes `PLAN.md` §2's "13,202 product URLs" wrong. I verified
only the two product pages above; the sitemap counts are one fetch away from being settled.
`scrapers/drugstore.py` was never written.

**Doc drift corrected:** `docs/PHASES.md` still called P2 "next", P5 "blocked on the embedding model"
(decided 2026-11-07), P6 "blocked on P5", and P4 "2 sources left" with MedPlus unbuilt. Fixed today —
the status table now reads P5 **closed**, P6 **partial**, P7 **not started**.

### `scrapers/drugstore.py` written — dry-run only, DB gate still open

Built against the JSON-LD `Product` block rather than the `__NUXT__` payload, because the payload is
minified to variable references (`company_name:h`) and JSON-LD is a published contract:

```json
{"@type":"Product","name":"Coartem 80/480 Tablets (...)","sku":3953,
 "offers":{"priceCurrency":"NGN","price":9350,"availability":".../InStock"}}
```

**Gate met 2026-11-08, after the VPN was disconnected.** `drugstore.py --limit 20` →
`scrape_runs id=21 status=success record_count=20`, `listings: inserted=20 unchanged=0
price_history+=20`, `pharmacy_id=10`. Verified against the database, not the printout:

| Check | Result |
|---|---|
| `pharmacies` | `(3, HealthPlus, Lagos)`, `(8, MedPlus, Lagos)`, `(10, Drugstore.ng, National)` |
| listings per pharmacy | 2,396 / 313 / **20** |
| listings with null or `<= 0` price | **0** |
| `v_latest_listings` | 1,510 → **1,530** |
| `v_cheapest_per_product_state` | 85 rows, **6 comparisons — unchanged** |

The unchanged comparison count is the prediction from the design note above: one seller per page
cannot create an `is_comparison` cell. Drugstore adds breadth and suspicious-listing evidence, nothing
more. Prices ₦1,440–₦308,000, all NGN from JSON-LD.

Earlier, while the DB was down, `--dry-run --limit 5` proved the parser without it:
`products fetched 5 / records 5 / failed 0`, archive
`archives/drugstore/drugstore-2026-11-08.jsonl.gz` sha256 `9dfeb8058d2f69a5…`.

**Accessibility gate closed 2026-11-08.** axe-core 4.10.2, WCAG 2.0/2.1/2.2 A+AA, against a live
dashboard: **0 violations on all five tabs** (Price index, Cheapest by state, Suspicious
registrations, Pipeline health, Limits). One violation existed and was fixed; the cause is worth
recording because the first two fixes were wrong:

- Reported: `color-contrast`, serious, 4 nodes, `#828180` on white = **3.88:1**, needed 4.5:1.
- Changing the caption colour did **nothing** — the rendered grey was identical, and
  `getComputedStyle` even reported the new dark colour while the screen stayed grey.
- Cause: Streamlit sets **`opacity: 0.6`** on `[data-testid="stCaptionContainer"]`. `#2f2d2b` at 60%
  over white blends to ≈`#828180`. The opacity was the defect, not the colour.
- Fix in `dashboard/app.py`, once: `opacity: 1` plus the body colour. Now ~12.6:1. Hierarchy comes
  from the smaller font size.

Method note: control elements with known colours confirmed axe itself was right while the DOM
inspector was misleading. Screenshot at 2.2× zoom is what settled it — `getComputedStyle` cannot see
a blend.

**Defect found by running it, and it is not only mine.** `parse_pack()` reads a slash strength as a
pack count: `Coartem 80/480 Tablets` became **`pack_size=480, pack_unit=tab`**, i.e.
**₦19.48/tablet** — a drug that looks almost free per tablet and wins every unit-price comparison.
`80/480` is artemether 80 mg / lumefantrine 480 mg. Fixed in `drugstore.py` only, by stripping
`\d+/\d+` before pack parsing (`STRENGTH_PAIR_RE`); the raw title is still stored verbatim. Proven:

| Title | `parse_pack` today | with the guard |
|---|---|---|
| `Coartem 80/480 Tablets` | (480, tab) **wrong** | (None, None) |
| `Coartem 80/480 Tablets x6` | (480, tab) **wrong** | (6, tab) |
| `Amlodipine Sandoz 10mg Tablets x28` | (28, tab) | (28, tab) — unchanged |
| `Lonart 80/480mg x6` | (6, None) | (6, None) — unchanged |

**HealthPlus is still exposed.** It calls the same `parse_pack`, so any listing titled with a slash
strength already carries a wrong `unit_price`, and that feeds `v_cheapest_per_product_state`. The fix
is the same one line, but changing shared parsing re-derives many rows at once and needs its own
measurement — the same reason the `2019's`/`strips` issues were left open (see below). Not fixed.

**Sampling caveat for the gate run:** the sitemap is ordered by SKU id, so the first records are
devices — `Fine Test Auto Coding Blood Glucose Machine`, two `First Aid Box`, an Omron BP monitor, a
test-strip refill. `--limit N` therefore samples the head of the catalogue, not a representative
slice, and `pack parsed 0/5` on that sample says nothing about medicine coverage.

## Handoff — 2026-11-07 (superseded by the block at the top)

Everything below is reproducible from the repo plus `.env`. Nothing depends on a running process;
all background jobs finished before close.

### Snapshot at close (2026-11-07)

| Object | Rows |
|---|---|
| `products` (all embedded, 384-d) | 1,074 |
| `nafdac_registrations` / with status | 10,906 / **572** |
| `nafdac_status_snapshots` | 572 |
| `products.nafdac_registration_number` set | 376 |
| `pharmacy_listings` (all) / latest per URL | 2,709 / **1,510** |
| Listings matched to a product | **251** |
| `price_history` | 2,709 |
| Pharmacies | **2** (HealthPlus, MedPlus — both Lagos) |
| `v_cheapest_per_product_state` / comparisons | 85 / **6** |
| `v_suspicious_listings` | **96** |
| `mv_drug_price_index` | 83 |
| `v_price_change_7d` | 0 (arithmetic — see below) |
| `scrape_runs` | 18 |

These numbers move on every scrape. Treat them as "as of 2026-11-07", never as constants.

### Resume commands, in dependency order

```powershell
# environment (one per machine)
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
# DATABASE_URL comes from .env (direct host). Never read .env inside a script.
$env:DATABASE_URL = ((Select-String -Path .env -Pattern '^DATABASE_URL=').Line).Substring(13).Trim()
$env:PYTHONIOENCODING = 'utf-8'   # the console is cp1252 and cannot print ₦
```

```powershell
# 1. regulatory index (~8 requests, 20 s)
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_index.py
# 2. regulatory status, restricted scope (~45 min at the measured 0.22 pages/s)
.venv\Scripts\python.exe -X utf8 scrapers\nafdac_details.py --min-similarity 0.50
# 3. prices (~1 min and ~25 min respectively)
.venv\Scripts\python.exe -X utf8 scrapers\healthplus.py
.venv\Scripts\python.exe -X utf8 scrapers\medplus.py --categories 12,31,32,50,57,58 --limit 250
# 4. link products to registrations (seconds; needs the trigram index)
.venv\Scripts\python.exe -X utf8 scripts\link_product_nrn.py --refresh --min-similarity 0.35
# 5. match listings to products (seconds; loads products+rules once, cosine in numpy)
.venv\Scripts\python.exe -X utf8 scripts\match_listings.py
# 6. the materialised index is NOT refreshed by anything yet — call it explicitly
psql $env:DATABASE_URL -c "refresh materialized view concurrently mv_drug_price_index;"
# 7. dashboard
.venv\Scripts\streamlit.exe run dashboard\app.py
```

Order matters: index → details → link → match → refresh. Matching before linking gives the
suspicious view nothing to join against, and the matview shows yesterday's prices until refreshed.

### What is knowingly broken or unfinished

| Item | State | Consequence |
|---|---|---|
| `v_price_change_7d` | empty | Cannot return a row before **2026-11-14**: it needs a second scrape ≥7 days after the first. Arithmetic, not a bug |
| `unit_price` coverage | 52.7% of HealthPlus listings | Below the 85% gate. Titles like `Adalat LA 30 mg X 30` state no form; guessing one would corrupt the comparison |
| `v_pipeline_health` | blind to never-run sources | A source with zero `scrape_runs` rows produces no row, so it is invisible rather than STALE |
| `products.nafdac_registration_number` | one NRN per product | A drug has many registrations; the view flags a product only when **no** Active candidate exists |
| MedPlus stock on existing rows | written under the old heuristic | The parser now reads `max="<units>"`; the next MedPlus run corrects them |
| Scheduled refresh | none | P7 is unbuilt; `scrape_runs` and the matview only move when a human runs the commands above |
| Dashboard | local only | Not deployed; no API |

### Environment gotchas that cost time today

- **DNS drops out.** `getaddrinfo failed` for the Neon host three times in one session. `common.db_connect()` now retries 3× / 5 s; anything new should call it rather than `psycopg.connect`.
- **Neon kills idle sockets.** A ten-minute fetch ended with `AdminShutdown` and discarded a completed run. Call `common.ensure_connection()` before writing after a long fetch.
- **`greenbook.nafdac.gov.ng` has an expired TLS certificate.** `common.RateLimitedClient` falls back to HTTP per host and records the downgrade.
- **This shell mangles embedded newlines** in a single `shell` call — multi-line commands silently produce nothing. Use one-liners or a script file.
- **The console is cp1252.** `₦` raises `UnicodeEncodeError`; always pass `-X utf8`.

### Open decisions, with the default I would take

| Decision | Default |
|---|---|
| `unit_price` target: accept ~53% or add form-word detection | Try detection, re-measure, then accept |
| Full Greenbook sweep (10,906 pages, ~14 h, must shard) | Keep restricted; the views cannot consume the rest yet |
| `v_pipeline_health` handling of never-run sources | List known sources inside the view |
| Neon Data API on the free plan | Thin read-only service if unavailable |
| Add nettpharmacy as a fourth source | Only after Drugstore.ng |

### Claims that still need a human eye before publication

1. **The 6 comparisons.** Nobody has opened both shop pages to confirm the same pack is being
   priced. Do this before quoting "cheapest".
2. **Paracetamol appears twice** in the comparison set. Confirm they are genuinely different
   strength/pack products, not a duplicate in the seed catalogue.
3. **The 96 suspicious rows.** They survive the rules and the falsification test, but no page has
   been compared against the rendered NAFDAC record by hand.
4. **The dashboard's empty states.** Every render so far had data.
5. **Accessibility.** No axe run. WCAG 2.2 AA is a release gate in `AGENTS.md`.

### Next three actions

1. Human-verify two comparison rows (20 minutes, no code).
2. Expand MedPlus across the remaining ~1,350 category-12 products — the cheapest way to move
   6 comparisons toward a number worth showing.
3. Add Drugstore.ng for catalogue density and 37 states, then deploy the dashboard.


## Where we are

**M3 — two pharmacies, and real comparisons.** Neon project `orange-pond-32200905`
(PG 17.11) holds 8 tables, 5 views, 1 materialised view, 1,074 embedded products, 10,906 NAFDAC
registrations, 572 status snapshots, **1,510 latest listings from 2 pharmacies** (HealthPlus and
MedPlus, both Lagos), 376 product→registration links, 251 listing→product links and **2,709
`price_history` rows**. `v_cheapest_per_product_state` returns **85 rows, 6 of them
`is_comparison = true`** (Atenolol, Ibuprofen, Loratadine, Methyldopa, Paracetamol ×2 — all Lagos,
each quoted by both pharmacies). `v_suspicious_listings` returns **96 rows**;
`mv_drug_price_index` 83; `v_price_change_7d` still 0 until 2026-11-14. `dashboard/app.py` renders
all of this and was verified in a browser.

## Done and verified

| Item | Evidence |
|---|---|
| Schema written — 8 tables, 5 views, 1 materialised view | `schema/001_extensions.sql` … `004_materialized.sql` |
| Seed loader | `python scripts/load_seed.py --dry-run` → exit 0, `products=1074 match_rules=1074 skipped=0 statements=6`, 2,160 SQL lines |
| Repo public, pushed | `github.com/batestguy/NaijaDrugWatch`, `main` |
| No secrets committed | `.env` absent from tree; only `.env.example` |
| Source rights probed | `research/2026-11-06-feasibility-probes.md` |
| **Neon project created** | `neonctl projects create` → `orange-pond-32200905`, PG 17.11, `aws-eu-central-1`, verified `select version()` |
| **`001` executed** | `CREATE EXTENSION` ×3 (pg_trgm, vector, unaccent), exit 0 |
| **`002` executed** | 8 `CREATE TABLE`, 9 indexes + comments, exit 0 |
| **`003` executed after fix** | 5 `CREATE VIEW`, exit 0 — see defect 1 |
| **`004` executed after fix** | `SELECT 0` + `CREATE INDEX`, exit 0 — see defect 2 |
| **`REFRESH … CONCURRENTLY` works** | `REFRESH MATERIALIZED VIEW` on `mv_drug_price_index`, exit 0 |
| **View logic proven** | rolled-back smoke test, 2 pharmacies / 2 products / 3 listings: cheapest = ₦450 across 2 pharmacies with `is_comparison = true`; single-pharmacy ₦300 with `is_comparison = false`; `pct_change_7d = -16.67`; all-failed source shows `STALE`; matview grouped 2 days correctly; `ROLLBACK` left 0 rows |
| **Seed loaded** | `.venv\Scripts\python.exe scripts/load_seed.py` → `loaded products=1074 match_rules=1074 skipped=0 statements=6`, exit 0; DB confirms `products=1074 match_rules=1074 distinct_names=597 with_nrn=0 with_embedding=0` |
| **Seed loader is idempotent** | second consecutive run → same counts, DB still `products=1074 rules=1074` |
| **Pinned environment** | `.venv\Scripts\python.exe`, CPython 3.12.13 via `uv venv --python 3.12`; `psycopg 3.2.13`. System Python 3.14 has no `psycopg[binary]` wheel — the first load attempt failed with `ModuleNotFoundError` |
| **Execution plan written** | `docs/PHASES.md` — P0–P9 with a gate command per phase and the delegation map |
| **P2 closed — Greenbook index scraped** | `scrapers/nafdac_index.py`; runs 4, 5, 10 `success`, `record_count=10906`; 10,906 rows / 10,906 distinct NRNs; idempotent (`inserted=0 updated=10906`); 99.91% of cards carry an NRN |
| **Greenbook coverage re-derived post-fix** | `name+form+strength set 9743 (89.34%)` from a live run, matching the manual correction exactly — so the number now regenerates instead of being hand-nulled |
| **P4 partial — HealthPlus scraped** | `scrapers/healthplus.py`; runs 9 `success record_count=1197`; 1,197 distinct URLs; 0 null/negative prices; NGN proven from `Shopify.currency` |
| **Duplicate listings proven harmless** | 2,396 raw rows after overlapping runs, `v_latest_listings` returns **1,197** |
| **Ledger failure path proven** | induced `NotNullViolation` mid-transaction → `finish_run` wrote `('failed', …, 'selftest: induced failure')`; without the rollback fix it left the row `running` |
| **P3 partial — 572 registrations with status** | `scrapers/nafdac_details.py --min-similarity 0.50`: 100% status, 99.8% expiry, 0 failed pages. **204 Active / 215 Expired / 153 Inactive = 64.3% not Active** |
| **Product → NRN linked** | `scripts/link_product_nrn.py`: 278 of 1,074 products linked (99 Active, 131 known non-Active, 48 to an unverified registration); 796 unmatched, 566 for lack of any candidate |
| **`v_suspicious_listings` NULL bug fixed** | `r.status is distinct from 'Active'` counted NULL as suspicious; now `status is not null and (status <> 'Active' or expiry < today)`. Proven in a rolled-back transaction: linking to `Expired` yields 1 row, adding an unverified link keeps it at 1 |
| **P5 matcher built — views finally return rows** | `scripts/match_listings.py`: bge-small-en-v1.5 (384), top-10 cosine + `drug_match_rules`. 456 of 2,396 rows matched; **`v_suspicious_listings` = 90 rows**, `v_cheapest_per_product_state` = 72 rows (0 comparisons) |
| **Suspicious rows falsification-tested** | all 40 flagged products re-run through selection logic: **0 have an Active candidate** passing strength and form (a name-only test had wrongly suggested 14) |
| **Missing index added** | `nafdac_registrations_name_trgm_idx`; without it every similarity lookup seq-scanned 10,906 rows and the linker timed out at 10 min |
| **`price_history` now populated** | `common.record_price_history()` writes one row per new listing (idempotent); backfill inserted **2,396** rows from existing listings. `mv_drug_price_index` refreshed concurrently → **79 rows** (e.g. Bicalutamide, Lagos, ₦144,780) |
| **`v_price_change_7d` rewritten** | It grouped by `listing_id`, which can never work: listings are immutable, so a price change creates a new id and no id ever holds two prices. Now compares per `(pharmacy_id, url)` across listings. Returns 0 rows because nothing is 7 days old — correct, not broken |
| **MedPlus scraper live** | `scrapers/medplus.py`, categories 31+32: 98 listings, 0 failed parses, ₦250–106,550, 0 absurd, `price_history+=98`, run 19 success. Pharmacy #2 in Lagos |
| **First genuine comparisons** | `v_cheapest_per_product_state`: 81 rows, **3 with `is_comparison = true`** — Ibuprofen (MedPlus ₦350) and Paracetamol (HealthPlus ₦1,000), both Lagos, both two-pharmacy |
| **Dashboard renders** | `dashboard/app.py`, verified in a real browser (Playwright, 1440px): metrics, all five tabs, price index populated. Comparison and single-pharmacy rows sit in separate columns and are never merged |
| **MedPlus expanded** | Categories 12+50+57+58, 250 products: 215 new listings, 0 failures, `price_history+=215`, run 20 success. Comparisons then went **3 → 6** (Atenolol, Ibuprofen, Loratadine, Methyldopa, Paracetamol ×2) |
| **MedPlus stock signal fixed** | Stock was inferred from an absent marker, giving 313/313 in stock. The real signal is the quantity input's `max="<units>"`; `in_stock = max > 0`, and NULL when no signal exists. Sample re-check: 8/8 in stock, so the earlier result was probably right — but it is now read, not assumed |
| **`db_connect` hardened** | This machine's DNS intermittently fails (`getaddrinfo failed`); connect now retries 3× / 5 s. `ensure_connection()` reconnects when Neon kills a socket during a long fetch (`AdminShutdown`), which had discarded a completed 98-product fetch |

## Defects found by executing the SQL (both fixed 2026-11-07)

1. **`v_cheapest_per_product_state` did not compile.** `count(distinct b.pharmacy_id) over (…)`
   → `ERROR: DISTINCT is not implemented for window functions`. The per-cell pharmacy count now
   comes from a grouped `pharmacy_counts` CTE joined on `(product_id, state)`; the partition is
   identical, so `pharmacy_count` and `is_comparison` semantics are unchanged.
   **This is the view the whole "cheapest" claim rests on**, and it had never run.
2. **`mv_drug_price_index` named a column that does not exist.** It selected `l.state` from
   `pharmacy_listings`, which carries no state; `ERROR: column l.state does not exist`. State lives
   on `pharmacies`, so the definition now joins `pharmacies` and takes `ph.state`. Aliases were
   renamed (`h`/`l`/`ph`/`p`) because the old `ph` meant `price_history` in one line and would have
   meant `pharmacies` in the next.

Both defects were syntactically invisible: the files were well-formed SQL that had simply never
been sent to a server.

## Defects found by auditing the scrapers (fixed 2026-11-07)

An independent read-only audit (different model family) ran after both scrapers were written. Every
finding below was reproduced and fixed the same day.

| Where | Defect | Fix |
|---|---|---|
| `common.finish_run` | The failure path wrote the ledger on an **aborted transaction**, so `InFailedSqlTransaction` was swallowed and the run stayed `running` forever — the exact state the ledger gate exists to prevent. No `rollback()` existed anywhere. | `clear_failed_transaction()` runs before the UPDATE in `finish_run`. Proven by inducing a `NotNullViolation` mid-transaction: the row still became `failed`. |
| `healthplus.main` | `db_connect`, the advisory lock and `start_run` sat **outside** `try`, so a failure there produced no `scrape_runs` row at all. | Moved inside the guarded block; the handler now also requires `run_id is not None`. |
| `healthplus.build_record` | A zero or missing price was **inserted** and only reported. A ₦0.00 row wins every `min()`-based view, i.e. becomes "cheapest". | Rejected at build time. |
| `healthplus.parse_pack` | `7-18kg x46` on a nappy title parsed as **18,000 g** — the baby's weight range became the pack — making the item look near-free per gram. | `MAX_PACK_MASS_G = 5000`; above it, an explicit count in the title wins. Now returns `(46, None)`. |
| `healthplus` docstring | Claimed "a `scrape_runs` row on success and on failure", but the advisory-lock skip path writes none. | Docstring corrected: a run that loses the lock attempted nothing, so it records nothing. |
| `common.existing_urls` | Dead code, and its `pharmacies.name = source` join was fragile. | Removed. |

**Corrected claim.** The index scraper reported `name+form+strength 10906 (100.00%)`. That was
false: 1,129 rows carried the literal string `NA` in `dosage_form` and 1,163 in `strength`. Storing
a sentinel as a value is worse than storing NULL, because the matcher filters on those columns.
`NA` now becomes NULL, and a live post-fix run reports **9,743 / 10,906 = 89.34%**.

**Left open deliberately:** pack-count selection is by regex class, not by position in the title
(`... 2019's` can yield `pack_size` 2019), and `strips` is not a known unit. Both would change many
parses at once and need their own measurement.

## Delegation log — what each agent produced, and what survived review

Recorded because "an agent built it" is not evidence. Every row was re-verified after handoff.

| Agent (model) | Session | Delivered | Re-verified | Changed after handoff |
|---|---|---|---|---|
| `builder` · deepseek | `ses_e4acea944ffeua1kWsbnh5GfRU` | `scrapers/healthplus.py` — 1,197 listings, 6 requests | yes, live DB | Audit fixes: ledger rollback, DB setup moved inside `try`, zero-price rejection, `7-18kg` pack bug, docstrings |
| `builder` · deepseek | `ses_e4acea946ffevFyvpzTw1kuM46` | **failed** — `prefill_cap_refused`, no output | — | Relaunched after confirming the tree was clean |
| `builder` · deepseek | `ses_e4ac95d29ffeY1GS6ObiAao6nh` | `scrapers/nafdac_index.py` — 10,906 registrations, 99.91% parse | yes, idempotency re-run | `NA` sentinel stored as a value → `text_or_none()`; coverage claim corrected from 100% to 89.34% |
| `ship-reviewer` · glm-5.3-flash | `ses_e4ab48c1affeEeL8deFqF6PEeZ` | Read-only audit: 6 defects + 3 overstated claims | each reproduced by hand | Its shell permission was revoked after two calls, so **none** of its DB claims were self-verified; two suspicions held, one was worse than it could see (`18000 g`) |

Everything after the audit — the detail scraper, the linker, the matcher, the dashboard, MedPlus —
was built and verified directly, because the agent channel kept failing on provider capacity and a
relaunch cost 15 minutes for no work.

## Not done — in order (phase ids match `docs/PHASES.md`)

1. **P3 remainder — full Greenbook sweep.** 10,906 pages at the measured 0.22 pages/s is ~14 h,
   over the 6 h job cap, so it must be sharded across days and run sequentially by ID range (never
   fanned out: one `nafdac_status_snapshots` table). The restricted 572 is already usable.
2. **P4 remainder — more MedPlus, then Drugstore.ng.** Category 12 alone holds ~1,600 products and
   only 250 were sampled; ~1,350 remain (~2 h) and are the cheapest source of new comparisons.
   Drugstore.ng adds 13,202 product URLs and 37 states but a single national price, so it adds rows,
   not comparisons. `unit_price` is still 52.7% against an ≥85% gate.
3. **P6 remainder — human verification before publication.** The 6 comparisons have not been
   checked against two live shop pages, and the 96 suspicious rows have never been compared to a
   rendered NAFDAC record by hand.
4. **P7 — `flows/daily.py`.** Prefect is not installed here; one deployment must cover every source
   (Hobby allows 5). `v_pipeline_health` still cannot see a source that never ran.
5. **P8 remainder — deploy the dashboard**, then the read-only API (Neon Data API availability on
   the free plan is still unverified).
6. **P9 — publish**: disclosure, per-source attribution, #FixMedPrices credit, limitations.

## Decisions, dated

| Date | Decision |
|---|---|
| 2026-11-07 | Neon project `orange-pond-32200905`, PG **17**, `aws-eu-central-1`. Free plan. The account's region list offers no af-south option; Frankfurt is the closest available to Lagos. |
| 2026-11-07 | Direct (non-pooled) connection string for DDL and seed loads; the `-pooler` host is reserved for Streamlit and the Data API, because PgBouncer transaction pooling does not run DDL reliably. |
| 2026-11-07 | **Seed loaded** via the pinned `.venv` (CPython 3.12.13). System Python 3.14 is rejected for this repo: no `psycopg[binary]` wheel exists, and the first attempt failed on it. |
| 2026-11-07 | Phase ids P0–P9 with per-phase gate commands live in `docs/PHASES.md`; `PROGRESS.md` remains the only state file. |
| 2026-11-07 | **Embedding model**: `BAAI/bge-small-en-v1.5`, 384 dims. Stage one is candidate generation only; `drug_match_rules` decides. |
| 2026-11-07 | `v_suspicious_listings` treats `status is null` as **unknown, not suspicious**. Counting NULL as inactive flagged every product whose registration was outside the scraped scope. |
| 2026-11-07 | `v_price_change_7d` compares across listings for the same `(pharmacy_id, url)`; it cannot compare within a `listing_id` because a listing is an immutable observation. |
| 2026-11-06 | **Reporting policy B**: `v_cheapest_per_product_state` only claims "cheapest" when `pharmacy_count >= 2`. A single-pharmacy cell is a national price, not a comparison. |
| 2026-11-06 | Add `pack_size`, `pack_unit`, `unit_price` to `pharmacy_listings` — additive, not a rename. |
| 2026-11-06 | Seed CSV loads `products` + `drug_match_rules` only. It has no NRN/status/expiry, and its `price` is not NGN. |
| 2026-11-06 | `vector(384)` is a placeholder pending the embedding model. **Resolved 2026-11-07: `BAAI/bge-small-en-v1.5` via fastembed (ONNX, CPU, no torch), 384 dims — no migration needed.** |
| 2026-11-06 | Pharmacy set: HealthPlus, Drugstore.ng, MedPlus; nettpharmacy.com (Shopify, NGN confirmed) available as a fourth. |
| 2026-11-08 | **Drugstore.ng is registered as one `pharmacies` row with `state = 'National'`.** Its price does not vary by state route (byte-identical pages), and each product page names only one seller, so it can never create a comparison. The per-offer seller is archived in JSONL, not stored. Revisit seller-as-pharmacy only after measuring whether two sellers carry the same product. |
| 2026-11-09 | **Scope is Lagos, and "state" is the shop's location, not a price dimension.** Probed 2026-11-09: `healthplusnigeria.com/products/zoladex-goserelin-36mg-injection.json` returns one variant at `266670.00` NGN with no location field anywhere in the payload; `medplusnig.com/product/nutravit-syrup-100ml-hTnxx4` shows one price (₦3,800.00) and "Nationwide Delivery" with no state selector that changes it; Drugstore.ng was already proven byte-identical with `?state=kano`. **No source in this project carries a per-state price.** The comparison we can honestly publish is shop-against-shop (`is_comparison`), and the fixed view name `v_cheapest_per_product_state` keeps the word "state" as a contract name — but no claim of state variation is made anywhere. Publishing language: "cheapest among the online pharmacies that publish prices", scope Lagos, two pharmacies. |

## Known risks

- **`v_price_change_7d` depends on time, not just data.** It now compares across listings per URL,
  which is correct under append-only semantics, but it cannot return a row until a second scrape
  happens at least seven days after the first. The first possible non-empty date is 2026-11-14.
- **The Greenbook's TLS certificate is expired** (probed 2026-11-07): `https://greenbook.nafdac.gov.ng`
  fails with `SEC_E_CERT_EXPIRED` / `SEC_E_CERT_EXPIRED (0x80090328)` while `http://` answers `200`
  and robots.txt still allows everything. `scrapers/common.py` therefore falls back per host and
  records the downgrade rather than disabling verification globally. Consequence: NAFDAC data
  currently crosses the wire unencrypted, so archive integrity rests on our own sha256 sidecars,
  not on transport. Re-probe before publishing; if it is still expired, say so in the limitations.
- **`v_pipeline_health` cannot see a source that never ran.** It groups `scrape_runs`, so zero rows
  for a source means zero output rows, not `STALE`. The smoke test only produced `STALE` because a
  *failed* run existed. At launch, with no runs at all, the health view is empty while three sources
  are silently dark. The view is a fixed contract name, so fixing this means either listing known
  sources inside the view or seeding one placeholder run per source — needs a decision.
- **`v_suspicious_listings` needs matches.** 77% of sampled registrations are non-Active, but a row
  only appears if a *listing* matches a product that has a registration number. The matcher is the
  gate, not the data.
- **State variation is thin.** Drugstore exposes one national price; only HealthPlus and MedPlus
  carry per-pharmacy pricing, and both are Lagos.
- **~10% of Greenbook detail pages returned HTTP 500** during sampling. The scraper needs backoff
  and a resumable ID cursor.
- **No NAFDAC mirror exists.** If the Greenbook blocks, history stops growing. Archive a dated
  full dump each run.
- **Low-risk, watched:** `v_pipeline_health` uses `round(extract(epoch …) / 3600.0, 1)`, which needs
  `extract` to return `numeric` (PG14+). It compiles on 17.11; it would break on PG13 or older.

## Rebuilding from an empty database

Full order, once, from nothing:

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv\Scripts\python.exe -r requirements.txt
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema/001_extensions.sql   # then 002, 003, 004 in order
.venv\Scripts\python.exe scripts/load_seed.py                          # products=1074 match_rules=1074
# then follow "Resume commands, in dependency order" at the top of this file:
#   index -> details -> link -> match -> refresh the matview
```

Every schema file is idempotent, so a full rebuild is re-running `001`→`004` in order. The
dependency-ordered scraper commands live in the handoff section rather than here, so there is one
copy that cannot drift.
