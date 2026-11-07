# AGENTS.md - NaijaDrugWatch

## State of the repo

- Repo is live at `github.com/batestguy/NaijaDrugWatch` (public, branch `main`). The M1 scaffold is committed: `schema/001-004.sql`, `scripts/load_seed.py`, `seed/medprices.csv`, `docs/`, `README.md`, `PLAN.md`, `research/`. `PROGRESS.md` is the single state file — read it before starting anything.
- **Pinned environment** (invariant 7): `D:\NaijaDrugWatch\.venv\Scripts\python.exe` — CPython 3.12.13, created 2026-11-07 with `uv venv --python 3.12 .venv`. System default Python is 3.14, which has **no `psycopg[binary]` wheel**; do not run the loader against it. Install with `uv pip install --python .venv\Scripts\python.exe -r requirements.txt`.
- **The database exists and the schema runs.** Neon project `orange-pond-32200905` (PG 17.11, free plan) has executed `schema/001`–`004`; 8 tables, 5 views, 1 matview, and `REFRESH … CONCURRENTLY` is proven. `products` and `drug_match_rules` hold 1,074 rows each. What does **not** exist: any scraper, any `nafdac_registrations` row, any listing, any embedding, any test suite, any CI. Do not describe the pipeline as working — only the schema and the seed are.
- The spec's filename starts with `#`, so it must be quoted in shell: `Get-Content '#SQL NaijaDrugwatch.txt'`, `git add '#SQL NaijaDrugwatch.txt'`. Unquoted it is a PowerShell comment or a glob.
- Open decisions live in `PLAN.md` §10 and `PROGRESS.md`, not here. The pharmacy set is chosen (HealthPlus, Drugstore.ng, MedPlus; nettpharmacy available as a fourth). Still genuinely undecided: the embedding model — `vector(384)` is a placeholder — and whether the Neon Data API works on the free plan. Do not invent answers.
- Measurements behind the constraints below: `research/2026-11-06-feasibility-probes.md` (live probes, 6 Nov 2026). Re-probe before trusting a source figure; NAFDAC and the pharmacies change.
- Deliverable names are fixed by the spec: `scrapers/` (Python), `flows/` (Prefect), `dashboard/` (Streamlit), plus schema / views / seed-data docs and a `README.md` carrying the data-sourcing disclosure.
- SQL-first on Neon Postgres: schema and views are plain `.sql` committed to the repo, run in numbered order, and idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE VIEW`) so a rebuild is re-running the files. No dbt, no warehouse layer, no ORM migration framework, even though the global AGENTS.md repo shape shows `dbt/`.

## Gates (hard constraints, not style)

- $0/month only: Neon Free (100 CU-h, 0.5-1 GB), Prefect Hobby (5 deployments, 500 serverless min/mo), Streamlit Community Cloud (2.7 GB RAM per app), GitHub Actions (free and unlimited on public repos, 6 h max per job), Resend (3,000 emails). No paid or metered service without explicit approval.
- Repo stays public, because GitHub Actions cron is free only on public repos. `DATABASE_URL` and `PREFECT_API_KEY` live in GitHub Actions secrets or a gitignored local `.env`, never in a tracked file.
- Prefect Hobby allows 5 deployments: build one daily flow covering all sources, not one deployment per pharmacy or per view refresh.
- Supabase Free is an explicit anti-choice (pauses after 7 idle days); the database is Neon. Do not swap it for convenience.
- Scrapers: honour robots.txt per domain, at most one request every 2 s per domain, custom User-Agent naming the project, product and price fields only. No reviews, no personal data (NDP Act 2023).
- The Greenbook has **no JSON API** (`/api/*`, `/sitemap.xml`, `/search?q=` all 404) and **no third-party mirror exists**. It is scraped as HTML: 6 category pages give name/form/strength/NRN for 10,899 registrations, and detail pages give status + expiry. With no fallback, archive a dated full dump each run so a block costs freshness, not history. No evasion — no proxy rotation, no headless tricks to defeat a block.
- API-first per site: WooCommerce Store API, then Shopify `/products.json`, Playwright only where neither exists.
- Matching is two-stage and non-negotiable: pgvector top-10 candidates by cosine similarity, then deterministic filtering through `drug_match_rules` on strength, form, and active ingredient. pg_trgm-only or similarity-only matching is the explicitly rejected failure mode.
- `price_history` at MVP scale (3 pharmacies x ~1,200 SKUs = ~3,600 rows/day) is roughly 0.1 GB/year with indexes, so the 90-day archive is a year-two problem, not a launch blocker. Keep every price row movable (timestamp + stable id) anyway.

## Fixed schema contract

- Tables, do not rename: `pharmacies`, `nafdac_registrations`, `nafdac_status_snapshots`, `products`, `drug_match_rules`, `pharmacy_listings`, `price_history`, `scrape_runs`.
- Views, do not rename: `v_latest_listings`, `v_cheapest_per_product_state`, `v_suspicious_listings`, `v_price_change_7d`, `mv_drug_price_index`, `v_pipeline_health`. The Neon Data API and the dashboard are built on these names; a rename breaks both.
- Extensions `pg_trgm`, `pgvector`, `unaccent` must be enabled in the first migration, before any table carrying a vector column.
- Two ledger rules carry the project: append a `nafdac_status_snapshots` row per observation instead of updating status in place (status history is the core value), and write a `scrape_runs` row on every run including failures, because `v_pipeline_health` flags a source STALE after 48 h without success.
- `pharmacy_listings` uniqueness is on (pharmacy, url, timestamp). That key cannot deduplicate across runs because the timestamp moves; `source_hash` is the handle that does. Keep both.
- `mv_drug_price_index` needs its unique index on (day, canonical name, state) before `REFRESH ... CONCURRENTLY` will work.

## Build order

Spec section 11 is the workflow; section 15 priorities win over convenience:

1. Neon schema, extensions, and the `.sql` file layout
2. Seed `products` and `drug_match_rules` from the #FixMedPrices CSV (name, strength, form, up to 88 brand aliases). It has **no NRN, status or expiry**, so it cannot seed `nafdac_registrations`
3. API-first scrapers (WooCommerce, then Shopify)
4. SQL views, then the materialised view
5. Two-stage matcher
6. Prefect daily deployment
7. Streamlit dashboard and Neon Data API

MVP scope guard: three pharmacies in Lagos/Abuja and roughly 50 common drugs across malaria, hypertension, diabetes, and antibiotics. Do not chase national coverage; SMS/USSD/WhatsApp/PWA are post-v1.

API availability is thinner than the spec assumes: of 13 hostnames probed (9 resolved), only HealthPlus (`healthplusnigeria.com`, Shopify, 1,197 SKUs, NGN) answered a product API with usable prices; `medecify.com` answered WooCommerce but prices in EUR. Expect HTML for the other two rather than forcing API-first.

## Verification (no harness exists yet)

- Nothing can be "tested" by a runner. Until a harness exists, verification means: apply the `.sql` files to a Neon branch and assert the view returns rows (`v_suspicious_listings`, `v_pipeline_health`), and confirm a scraper is done only when its `scrape_runs` row shows success with a non-zero record count.
- `mv_drug_price_index` refresh is part of the daily flow, not a manual step — a stale index is indistinguishable from a quiet market.

## Definition of done (spec section 15)

Daily scrape green for seven consecutive days; `v_suspicious_listings` returns at least one row; the dashboard renders the state-by-drug price index; the API answers cheapest-product-per-state.

## Licensing and disclosure

Code MIT, data CC-BY-4.0. Every publish keeps the data-sourcing disclosure and per-source attribution; #FixMedPrices is CC-BY-4.0 and must be credited.
