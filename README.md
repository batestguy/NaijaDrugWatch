# NaijaDrugWatch

An open, daily-refreshed database that joins **NAFDAC drug registration status** to **live
Nigerian pharmacy prices** — so a patient, pharmacist or researcher can answer: *is this drug
genuine, is it in stock, and where is it cheapest?*

**Status: it runs itself, and it has not been checked by eye.** The pipeline completes end to end and
the daily schedule has fired by itself for three nights running: three nights found the day missing
and ran the whole pipeline (1 h 33 m, 1 h 31 m, 1 h 49 m), and five later fires found the day already
done and stood down in seconds. What is **not** established: seven consecutive green days, any
comparison checked against a live pharmacy page, and any lapsed registration compared against a
rendered NAFDAC record. So **do not cite this as a price source yet** — and read
[`PROGRESS.md`](PROGRESS.md) before quoting any number here.

Every figure below is as of **2026-11-12** and moves on every scrape. Current state and row counts
live in [`PROGRESS.md`](PROGRESS.md), which is the single state file for this repo.

## What the data currently says

| Object | Value | Meaning |
|---|---|---|
| `pharmacy_listings` (latest per URL) | 2,792 | three pharmacies, all Lagos except Drugstore.ng |
| …matched to a product | 580 | 2,212 are unmatched: no product to attach them to |
| `nafdac_registrations` | 10,925 | the Greenbook index |
| …with a status scraped | 1,856 | **17% of the register** — still the restricted scope, not the full sweep |
| `v_cheapest_per_product_state` | 262 cells, **45 comparisons** | only 45 are genuine two-pharmacy comparisons |
| `v_suspicious_listings` | 163 | matched to a registration that is not Active, or has expired |
| `mv_drug_price_index` | 426 rows | refreshed by the pipeline, never by hand |


**A "cheapest" cell is only a comparison when `is_comparison` is true** — two or more independent
pharmacies quoting the same product in the same state. Every other cell is one pharmacy's price, and
the dashboard shows the two in separate tables for that reason.

Each row also carries **two answers**, because they differ once packs differ in size:

- `cheapest_pack_*` — the lowest sticker price.
- `best_unit_*` — the lowest **known** cost per unit.

The second is NULL wherever the pack size could not be parsed, and it ranks only the rows that could
be. It is therefore **not** "best value" and must never be labelled that way: where the cheapest pack
has an unknown size, the lowest *known* unit price can belong to a more expensive pack.

## Layout

```
schema/             numbered, idempotent .sql — run in order against an empty database
scrapers/           NAFDAC Greenbook (index + details) and three pharmacies
scripts/            seed loader, product→registration linker, two-stage matcher
seed/               vendored #FixMedPrices CSV (CC-BY-4.0)
dashboard/          Streamlit app over the contract views
.github/workflows/  the daily pipeline
docs/               schema, views, phases reference
research/           the live probe log behind every volume and status claim
.agent/             per-ticket brief, progress and report files
PLAN.md             project map: sources, pipeline, risks, build order, open decisions
PROGRESS.md         single state file — read this before anything else
```

## How it runs

`.github/workflows/daily.yml`, one job, at **03:00 UTC (04:00 Lagos)**:

```
nafdac_index → nafdac_details → link_product_nrn → healthplus → medplus → drugstore
             → match_listings → refresh mv_drug_price_index
```

Steps fail individually and the job still exits non-zero, because each scraper writes its own
`scrape_runs` row on success **and** failure — that row is what `v_pipeline_health` reads.

**A deliberate deviation from the specification:** the spec names `flows/` as a Prefect
deployment. This repo uses GitHub Actions cron instead — free and unlimited on a public repo, and no
second account or API key. The cost is real and belongs in the limitations: **no retry engine** (a
transient failure waits for tomorrow), run history only in the Actions UI, and **no backfill button**.

**Required secret:** `DATABASE_URL` in *Settings → Secrets and variables → Actions*. Use the
**direct** host, not the `-pooler` one: the scrapers take session-level advisory locks and the
pipeline runs `REFRESH MATERIALIZED VIEW CONCURRENTLY`, and both break under PgBouncer transaction
pooling.

**Durations, measured 2026-11-08 and updated 2026-11-12:** index ~20 s, details (restricted) ~45 min,
healthplus ~1 min, drugstore ~1 min, and medplus now walks its whole drug catalogue — 1,396 products
over 70 pages, about 68 minutes, where six category pages used to yield 128 rows. A full run is
therefore ~2 h 50 m, inside the 6-hour job cap. The complete Greenbook sweep (~14 h) does **not** fit
and must be sharded across days. GitHub delivers scheduled fires hours late: 03:00Z has arrived
between 10:21Z and 10:54Z, which is why the workflow fires three times and lets a gate decide.

## Quickstart

```bash
git clone https://github.com/batestguy/NaijaDrugWatch
cd NaijaDrugWatch
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt   # Windows
# POSIX: uv pip install --python .venv/bin/python -r requirements.txt

cp .env.example .env        # paste the Neon connection string into DATABASE_URL
```

Python **3.12** is required: `psycopg[binary]` has no wheel for 3.14.

```bash
for f in schema/001_extensions.sql schema/002_tables.sql schema/003_views.sql \
         schema/004_materialized.sql schema/005_suspect_prices.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done

python scripts/load_seed.py --dry-run   # inspect the SQL, no database needed
python scripts/load_seed.py             # upsert products + drug_match_rules
```

Then, in dependency order — details before linking, listings before matching:

```bash
python -X utf8 scrapers/nafdac_index.py
python -X utf8 scrapers/nafdac_details.py --min-similarity 0.50
python -X utf8 scripts/link_product_nrn.py --refresh --min-similarity 0.35
python -X utf8 scrapers/healthplus.py
python -X utf8 scrapers/medplus.py            # full drugs catalogue, ~1,396 products, ~68 min
python -X utf8 scrapers/drugstore.py --limit 200
python -X utf8 scripts/match_listings.py
python -X utf8 -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'],autocommit=True).execute('refresh materialized view concurrently mv_drug_price_index')"
```

Matching is not optional. A scrape inserts new rows with `product_id` NULL, and `v_latest_listings`
takes the newest row per URL — so **re-scraping silently un-matches what it re-inserts** until the
matcher runs again, and the views shrink.

`005_suspect_prices.sql` flags prices below ₦20 and keeps them out of the views. Re-running `003` on
its own reverts that exclusion; a full rebuild is safe because `005` sorts after `003`.

## Data sourcing disclosure

This project reads **publicly listed product and price data** from Nigerian pharmacy websites and the
publicly published NAFDAC Greenbook. Specifically:

- It collects product names, prices, pack sizes, stock status, pharmacy location at city/state level,
  and NAFDAC registration number, status and dates.
- It does **not** collect personal data, customer reviews, prescription information, or anything
  behind a login. The NDP Act 2023 governs personal data; none is processed here.
- `robots.txt` is honoured per domain, requests are limited to **one every two seconds per domain**,
  and the User-Agent identifies the project.
- No attempt is made to circumvent a block, rate limit or access control. If a source blocks access,
  it is reported stale rather than worked around.
- MedPlus and Drugstore.ng publish Cloudflare content signals (`ai-train=no`, `use=reference`). This
  project aggregates and cites; it does not train on the data.

## Attribution and licence

- **Code:** MIT — see [`LICENSE`](LICENSE).
- **Data:** CC-BY-4.0, respecting each upstream licence.
- **#FixMedPrices** (Code for Nigeria, via openAFRICA) is CC-BY-4.0 and must be credited wherever its
  data appears.
- NAFDAC Greenbook data is published by the National Agency for Food and Drug Administration and
  Control. This project is independent and is not endorsed by NAFDAC.

## Limitations

- **Prices are observed, not guaranteed.** A listing is what a website displayed at scrape time;
  stock can change before purchase.
- **`unit_price` is unknown for roughly half of the listings.** Pack sizes are parsed from titles, and
  many titles state a count with no unit (`* 10 STRIPS`). The parser returns NULL rather than guessing,
  which is why `best_unit_*` is NULL so often.
- **Registration coverage is 17%.** Status and expiry exist for 1,856 of 10,925 registrations — the
  scope matching the catalogue we price, not the register. A product with no status has *unknown*
  status, which `v_suspicious_listings` does not treat as suspicious, so the 163 rows it returns are
  a fraction of a fraction and not an estimate of the whole register.
- **Drugstore.ng carries a single national price**, not a per-state one, and is registered with
  `state = 'National'`. It can never create a comparison. Its product pages name one seller each.
- **The scheduler has no retries.** A transient failure loses that day's run.
- **No human has yet checked a comparison against a live pharmacy page**, and no suspicious listing has
  been compared against a rendered NAFDAC record. Both are required before any "cheapest" claim is
  published.
- Registration status reflects the last successful scrape of the Greenbook, not NAFDAC's live state.
