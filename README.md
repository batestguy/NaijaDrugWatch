# NaijaDrugWatch

An open, daily-refreshed database that joins **NAFDAC drug registration status** to **live
Nigerian pharmacy prices** — so a patient, pharmacist or researcher can answer: *is this drug
genuine, is it in stock, and where is it cheapest?*

**Status: frozen on 16 November 2026, and only a small part of it has been checked by eye.** The
schedule is disabled and the data is a dated vintage, not a live service. Before the freeze the
nightly job ran green on all six sources for seven consecutive days. Afterwards, 20 sampled register
records were re-read against the live register and all 20 matched on every field, and all 44
comparisons were re-read once — but through the same channels the scrapers use. That proves the pages
have not drifted; it cannot prove the parsers read them correctly. Per-line judgements exist for 18 of
20 licence cards and 3 of 20 pack cards. So **do not cite this as a price source**. Start with
[`FROZEN.md`](FROZEN.md), then [`PROGRESS.md`](PROGRESS.md); the numbers below are the frozen vintage's.

Every figure below is as of **2026-11-15**, the last collection, and does not move again.

## What the data says

| Object | Value | Meaning |
|---|---|---|
| `pharmacy_listings` (latest per URL) | 2,800 | three pharmacies, all Lagos except Drugstore.ng |
| …matched to a product | 559 | 2,241 are unmatched: no product to attach them to |
| `products` | 1,433 | of which **335** are cited by a live price; 1,097 never are |
| `nafdac_registrations` | 10,967 | the Greenbook index |
| …with a status scraped | 1,856 | **16.9% of the register** — the restricted scope, not the full sweep |
| `v_cheapest_per_product_state` | 261 cells, **44 comparisons** | only 44 are genuine two-pharmacy comparisons |
| `v_suspicious_listings` | 154 (86 products) | matched to a registration that is not Active, or has expired |
| `mv_drug_price_index` | 428 rows | refreshed by the pipeline, never by hand |
| price change over 7 days | 3 products | the feature works; the market was quiet |


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

**It no longer runs.** The `daily` workflow is disabled by hand (id 410978489); `gh workflow enable
410978489` would switch it back on, and the first night would find the day missing and run the whole
pipeline. The freeze record is [`FROZEN.md`](FROZEN.md).

`.github/workflows/daily.yml`, one job, at **03:00 UTC (04:00 Lagos)** while it was live:

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
  which is why `best_unit_*` is NULL so often. Two consequences are live in the published tables: 18 of
  the 88 listings behind a comparison row carry a pack count with no unit recorded, and **one published
  unit price is per millilitre** — the Vitamin B Complex syrup is stored with pack size 100 and no unit,
  so its ₦12.50 "per pack unit" is per millilitre and sits directly above a ₦2.30-per-tablet row. Of the
  30 comparison rows carrying a unit price, 26 are tablets, 3 capsules and 1 is millilitres.
- **Two product names appear twice each on the comparison table**, at very different prices, because
  they are different products: Amlodipine 5 mg (₦950) and 10 mg (₦400); a Vitamin B Complex 100 ml
  syrup (₦1,250) and a 1,000-tablet pack (₦2,300). Both are correct as separate rows and both will be
  read by a stranger as a price cut.
- **Registration coverage is 17%.** Status and expiry exist for 1,856 of 10,925 registrations — the
  scope matching the catalogue we price, not the register. A product with no status has *unknown*
  status, which `v_suspicious_listings` does not treat as suspicious, so the 163 rows it returns are
  a fraction of a fraction and not an estimate of the whole register.
- **Drugstore.ng carries a single national price**, not a per-state one, and is registered with
  `state = 'National'`. It can never create a comparison. Its product pages name one seller each.
- **The scheduler has no retries.** A transient failure loses that day's run.
- **What has been checked against the live sources, and what that check can prove.** On 16 November
  2026, before the vintage was frozen, the register pages behind the 20 sampled licence records were
  re-read from the live Greenbook and all 20 matched on status, expiry, approval
  date, name and strength; 18 of those 20 were also answered line by line by a person against the live
  page. The pages behind all 44 comparison rows were re-read the same day — 88 page reads, no
  differences — **but through the same channels the scrapers use**: HealthPlus refused its independent
  storefront JSON endpoint with repeated `429 local_rate_limited` over more than an hour of attempts,
  so the fallback was the catalogue feed `scrapers/healthplus.py` itself reads, and MedPlus has no
  second server-side source at all. That check therefore shows a page has not drifted since collection.
  It cannot show that the parser read the page correctly. The author also reviewed all 44 comparisons
  informally and reported no disagreement; 3 of the 20 scored pack cards carry recorded per-line
  answers and the other 17 were not marked, so the recorded pack sample is 3 cards and is not
  presented as 20.
- Registration status reflects the last successful scrape of the Greenbook, not NAFDAC's live state.
