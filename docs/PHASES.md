# Phases — execution plan and gates

Updated **2026-11-07**. This is the *sequenced* plan: what runs in what order, what proves each
phase done, and who does it. It does not restate research — every source figure traces to
`research/2026-11-06-feasibility-probes.md` and the source inventory in `PLAN.md` §2.

**State lives in `PROGRESS.md`, not here.** When a phase closes, the gate output goes into
`PROGRESS.md`; this file only records the plan and what is still blocked.

Gate rule from the global invariants: *no number without an artifact*. A phase is closed only when
the command under **Gate** has been run and its real output recorded.

---

## Status at a glance

| Phase | Scope | Status |
|---|---|---|
| **P0** | Environment, Neon database, schema | **closed** |
| **P1** | Seed catalogue (products + match rules) | **closed** |
| **P2** | NAFDAC Greenbook index (10,906 NRNs) | **closed** 2026-11-07 |
| **P3** | NAFDAC Greenbook detail pages | **partial** — 572 registrations at the 0.50 scope |
| **P4** | Pharmacy scrapers (HealthPlus, Drugstore.ng, MedPlus) | **all three built** — open only on `unit_price` (52.7% vs the 85% gate) |
| **P5** | Two-stage matcher (pgvector → rules) | **closed** 2026-11-07 |
| **P6** | Views proven on real rows | **partial** — 6 `is_comparison` cells; `v_price_change_7d` needs 2026-11-14 |
| **P7** | Prefect daily flow, 7 green runs | **not started** — needs a scheduler credential before the gate is reachable |
| **P8** | Streamlit dashboard + read-only API | **partial** — dashboard renders on live data, **axe gate passes 0 violations**; API and deployment not built |
| **P9** | Publish: disclosure, attribution, v1 tag | blocked on P8 |

P4 has no dependency on P2/P3 and can run **in parallel** with them. That is the first genuine
split, and the point at which work fans out to subagents.

---

## P0 — Environment and schema · closed

**Delivered.** Neon project `orange-pond-32200905` (PG 17.11, `aws-eu-central-1`); `schema/001`–`004`
executed in order; 8 tables, 5 views, 1 materialised view; pinned venv at
`.venv\Scripts\python.exe` (CPython 3.12.13, `psycopg 3.2.13` from `requirements.txt`).

**Two defects found only by executing:** `count(distinct …) over (…)` in
`v_cheapest_per_product_state`, and `l.state` on a table that has no state column in
`mv_drug_price_index`. Both fixed in `298cc5b`.

**Gate.** `psql … -c "refresh materialized view concurrently mv_drug_price_index;"` → exit 0.
Recorded in `PROGRESS.md`.

---

## P1 — Seed catalogue · closed

**Delivered.** `python scripts/load_seed.py` → `products=1074 match_rules=1074 skipped=0
statements=6`. 597 distinct canonical names, 0 rows with an NRN, 0 embeddings. Re-running leaves
both tables at 1,074, so the loader is idempotent.

**Deliberately not loaded:** `nafdac_registrations` (the CSV has no NRN, status or expiry) and
`price_history` (the CSV `price` is a unit reference, 0.0007–1877 across mixed units — loading it
would poison every "cheapest" claim).

**Gate.** `select count(*) from products` = 1074 **and** from `drug_match_rules` = 1074, after two
consecutive runs. Recorded in `PROGRESS.md`.

---

## P2 — Greenbook index scraper · closed 2026-11-07

**Why it matters.** This is the regulatory half of the join. Without it every listing is
"unverified", and `v_suspicious_listings` can never return a row.

**Scope.** `scrapers/nafdac_index.py`: 6 category pages → ~10,895 registration numbers, plus name,
form, strength. HTML only — the Greenbook has **no JSON API and no mirror**.

**Constraints.** robots.txt per domain; ≤1 request / 2 s; custom User-Agent naming the project;
write a `scrape_runs` row on success *and* failure; archive a dated full dump to disk each run so a
block costs freshness, not history.

**Gate.** A `scrape_runs` row with `status='success'` and `record_count >= 10500`, plus
`select count(*) from nafdac_registrations` matching the archive row count.

**Result (2026-11-07).** Runs 4, 5 and 10: `success`, `record_count=10906`. Table holds 10,906 rows,
10,906 distinct NRNs, 0 with `status`/`expiry`/`approval` (P3 owns those), 0 written to
`nafdac_status_snapshots`. Idempotent: a rerun reports `inserted=0 updated=10906`. Live per-category
counts were within drift of the 6 Nov probe (11,762 cards vs 11,759 labels). Parse rate 99.91% of
cards carry a usable NRN; **89.34%** carry name+form+strength — the rest genuinely publish `NA`,
which is stored as NULL, not as the string. Archive: three dated dumps, each sha256-checked.

**Owner.** `builder`. **Review.** `ship-reviewer` on the diff, because robots/rate-limit compliance
is a claim that must be verified against the code, not asserted.

---

## P3 — Greenbook detail pages · blocked on P2

**Scope.** ~11,754 detail pages → status, approval date, expiry. **~10% returned HTTP 500** during
sampling, so this needs exponential backoff and a resumable ID cursor; never restart the range.

**Budget.** Full sweep ≈ 6.5 h at 2 s/page, over the 6 h Actions job cap. Either shard 3 × ~2 h, or
restrict to NRNs that match the 50-drug MVP scope (~500–1,500 pages, 17–50 min). **Decision
needed** — sharding is the default because it also bounds the cost of a block.

**Gate.** ≥95% of targeted pages have non-null `status` and `expiry_date`; the shortfall is
explained by retried 500s, not by silent skips.

**Result — restricted sweep (2026-11-07).** 572 registrations snapshotted at `--min-similarity
0.50`: **100% carry a status, 99.8% an expiry, 0 pages failed** after retries. Of the 572,
**204 Active (35.7%)**, 215 Expired, 153 Inactive — **64.3% not Active**, with 363 expiry dates
already in the past. That is a publishable finding on its own, and it is *partial coverage*: the
scope is the catalogue we price, not the register.

The full sweep is **not** done and is not cheap: the measured rate is ~0.22 pages/s (the server
takes ~2.5 s on top of the 2 s floor), so 10,906 pages is ~14 h across several days.

Three failures happened on the way, all fixed and recorded in `PROGRESS.md`: a dropped connection
rollback (batch commits), a 22-minute socket hang (`urllib` timeouts are per-read, so a wall-clock
deadline was added), and a wrong time estimate in this very document.

**Owner.** `builder`. **QA.** `data-explorer` on the populated status distribution before P5 —
77% non-Active is expected, but not from a parsing bug.

---

## P4 — Pharmacy scrapers · blocked on P1 only, runs parallel to P2/P3

**Order by expected yield, not by preference.**

| Source | Access | Volume | Pricing signal |
|---|---|---|---|
| HealthPlus | Shopify `/products.json` | 1,197 SKUs, NGN | per-pharmacy |
| Drugstore.ng | Nuxt SSR `__NUXT__` | 13,202 URLs, 37 states | **one national price** — not a marketplace |
| MedPlus | custom PHP HTML | ~1,400–2,800, unverified | per-pharmacy |
| nettpharmacy | Shopify `/products.json` | unknown, NGN | optional fourth |

`medecify.com` answered WooCommerce but prices in **EUR** — excluded until a currency check passes.

**Constraints.** API-first, Playwright only where neither API exists. Store `raw_title` verbatim and
never overwrite it; `unit_price` requires parsing pack size from the title (90.4% parse rate
measured). `source_hash` is the cross-run dedupe handle — the `(pharmacy, url, scraped_at)` key
cannot dedupe because the timestamp moves.

**Gate.** Each source has a `scrape_runs` row with success and a non-zero count; prices are NGN and
`price_ngn >= 0`; `unit_price` populated on ≥85% of HealthPlus listings.

**Result — HealthPlus only (2026-11-07).** Runs 2, 3, 6 and 9: `success`. 1,197 distinct product
URLs, 0 null or negative prices, NGN proven from the storefront's own
`Shopify.currency = {"active":"NGN"}` rather than assumed. `v_latest_listings` returns 1,197 rows
after two overlapping runs inserted 2,396 — the append-only ledger plus `source_hash` dedupe is why
the views are unaffected.

**Gate NOT met on `unit_price`: 52.7%** (631 of 1,197), against an ≥85% target. Cause is the
source, not the parser: 428 titles state a count with no form word (`Adalat LA 30 mg X 30`), and
`product_type` is a therapeutic category (`Hypertension`), not a dosage form. Assigning a unit by
guess would corrupt the exact comparison `unit_price` exists to make. Drugstore.ng remains unbuilt,
so P4 is open on two counts. MedPlus was built later the same day and took comparisons from 0 to 6.

**Two parsing defects found and fixed** while measuring: `7-18kg x46` on a nappy title was read as
18,000 g (the baby's weight range became the pack), and a zero-price variant would have been
accepted and become the "cheapest" row in every min()-based view. Both now rejected; see
`PROGRESS.md`.

**Owner.** `builder` per source. These three are genuinely independent — one subagent per source is
justified, capped at three concurrent.

---

## P5 — Two-stage matcher · blocked on P3 + P4

**Non-negotiable shape.** pgvector top-10 cosine candidates, then deterministic filtering through
`drug_match_rules` on strength, form and active ingredient. Similarity-only or pg_trgm-only matching
is the explicitly rejected failure mode.

**Blocker — resolved 2026-11-07.** `products.embedding` is `vector(384)`, and the model was chosen to
fit it: `BAAI/bge-small-en-v1.5` via fastembed (ONNX, CPU, no torch), 384 dims, so no migration was
needed. The table still said "embedding model undecided" after the decision was made; that is why
this paragraph is historical rather than a live blocker.

**Result (2026-11-07).** Stage one and two both built in `scripts/match_listings.py`:
BAAI/bge-small-en-v1.5 (ONNX, 384 dims, matching `vector(384)` exactly, so no migration), top-10
cosine candidates, then `drug_match_rules` on name tokens, strength tokens and dosage-form family.
Similarity alone assigns nothing. On 2,396 listing rows: **456 matched (19.0%)**, 228 of 1,197 latest
listings, and `v_suspicious_listings` returns **90 rows** for the first time.

Precision check (the check that could have falsified it): all 40 flagged products were re-run
through the selection logic and **0 have an Active candidate** that satisfies strength and form.
A name-only test had suggested 14, which is why the gates matter.

The 81% unmatched is not a failure: HealthPlus's catalogue is largely supplements and devices that
are not in the 597-name seed at all.

**Owner.** `builder` for the pipeline, `data-explorer` for the precision sample. **Review.**
`ship-reviewer` — a matcher that over-matches manufactures the headline claim.

---

## P6 — Views proven on real rows · partial

All six objects already execute; none has seen real data. This phase is about *numbers*, not
compilation: `v_cheapest_per_product_state` must show `is_comparison = true` somewhere (Lagos/FCT
are the only plausible cells), and `v_price_change_7d` needs ≥8 days of price history before it can
return anything at all.

**Gate.** `v_cheapest_per_product_state` returns rows with `pharmacy_count >= 2`, `v_latest_listings`
count matches the sum of per-source success counts, and `mv_drug_price_index` refreshes
`CONCURRENTLY` without error after a real load.

**Owner.** `data-explorer`. **Review.** `ship-reviewer` on reporting policy B: a single-pharmacy cell
must never be labelled "cheapest".

---

## P7 — Prefect daily flow · not started

**One deployment**, not one per source or view — Prefect Hobby allows 5 and the budget assumes 1.
Writes `scrape_runs` on every path including failure, then refreshes the matview.

**Open defect to resolve first.** `v_pipeline_health` groups `scrape_runs`, so a source with zero
runs produces zero rows — dark, not `STALE`. Either list known sources inside the view or seed one
placeholder run per source. Decision needed before this gate can be trusted.

**Gate.** 7 consecutive days of green runs, and `v_pipeline_health` reports `OK` for every source.

**Owner.** `builder`.

---

## P8 — Dashboard and API · blocked on P7

Streamlit Community Cloud (2.7 GB per app), reading the pooled connection string. Neon Data API
**only if it exists on the Free plan** — unverified, and the fallback is a thin read-only service.

**Gate.** Dashboard renders the state-by-drug index; API answers cheapest-product-per-state;
zero axe violations on audited views (WCAG 2.2 AA is a release gate, not a nice-to-have).

**Result (2026-11-08) — accessibility half satisfied, API half open.** axe-core 4.10.2 over WCAG
2.0/2.1/2.2 A+AA on a live dashboard: **0 violations on all five tabs**. The one real violation was a
contrast failure caused by Streamlit's `opacity: 0.6` on captions, fixed in `dashboard/app.py`
(≈12.6:1 now). The dashboard is still **not deployed** and the read-only API does not exist.

**Owner.** `builder`. **Review.** `ship-reviewer` for the accessibility gate.

---

## P9 — Publish · blocked on P8

Data-sourcing disclosure, per-source attribution, #FixMedPrices credited (CC-BY-4.0), limitations
stated. Code MIT, data CC-BY-4.0.

**Gate.** Definition of Done in `AGENTS.md` §"Definition of done" all true, with an artifact behind
each.

**Owner.** `writer` for the disclosure prose, `ship-reviewer` last.

---

## How work is delegated

The user talks to one agent; subagents are an implementation detail. Routing:

| Work | Agent | Why |
|---|---|---|
| Scrapers, flow, dashboard, repo code | `builder` | owns ingestion and app code |
| Data quality, coverage, leakage, parse rates | `data-explorer` | read-only profiling before a number is trusted |
| Unknown terrain, library/API recon, "where is X" | `scout` | read-only, cites sources |
| Break an ambiguous phase into acceptance criteria | `planner` | no edits, decides only |
| Anything about to be published or committed | `ship-reviewer` | read-only audit on **glm-5.3-flash**, a different model family from the deepseek builders — same-family review is a plausibility check, not an audit |
| Disclosure, README, limitations prose | `writer` | grounded in artifacts, not memory |

Rules that keep this safe: at most **three** subagents at once, **five** per task; two agents never
write the same path (separate directories or a worktree); no fan-out over ingestion runs, model
fitting, or anything touching the shared database; launch long work in the background so the
conversation stays open.

**What this session has actually done so far:** everything single-threaded, because every step was
one command or one file — P0 and P1 were not parallelisable by construction. Fan-out begins at
**P2 + P4**, the first pair with no dependency between them, and not before.

---

## Open decisions that block a phase

| Decision | Blocks | Default if nobody decides |
|---|---|---|
| ~~Embedding model and dimension~~ | ~~P5~~ | **resolved 2026-11-07** — `BAAI/bge-small-en-v1.5`, 384 dims |
| **Who writes `price_history`** | **resolved 2026-11-07** | `common.record_price_history()` — one row per new listing, idempotent |
| `unit_price` target: accept ~53% or add form-word detection | P4 | P4 stays open |
| Shard vs 50-drug scope for detail pages | P3 | shard 3 × ~2 h |
| `v_pipeline_health` handling of never-run sources | P7 | view stays blind to dark sources |
| Neon Data API on Free | P8 | thin read-only service |
| Whether to add nettpharmacy as a fourth source | P4 | three sources |
