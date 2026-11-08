# Progress

Single state file for NaijaDrugWatch. Last updated **2026-11-08 (mid-session, after the VPN fix)**.

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

## Handoff — start here tomorrow

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
