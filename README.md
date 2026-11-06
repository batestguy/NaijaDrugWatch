# NaijaDrugWatch

An open, daily-refreshed database that joins **NAFDAC drug registration status** to **live
Nigerian pharmacy prices** — so a patient, pharmacist or researcher can answer: *is this drug
genuine, is it in stock, and where is it cheapest?*

Status: **scaffold only.** The schema, the seed loader and the docs exist. No scraper has run,
no database has been loaded, and no published number exists yet. Do not cite this repo as a
data source until `v_pipeline_health` reports seven consecutive green days.

## What is verified, and what is not

The data sources were probed live on 2026-11-06; the evidence is in
[`research/2026-11-06-feasibility-probes.md`](research/2026-11-06-feasibility-probes.md).

| Source | Access | Verified |
|---|---|---|
| NAFDAC Greenbook | HTML, `robots.txt` allows all | 10,895 registrations across 6 category pages; status + expiry on detail pages |
| Drugstore.ng | Nuxt SSR | 13,202 product URLs, 37 states; **one price per product, not per pharmacy** |
| HealthPlus | Shopify `/products.json` | 1,197 SKUs, NGN |
| Nett Pharmacy | Shopify `/products.json` | NGN; catalogue size unverified |
| MedPlus | server-rendered HTML | price present in raw HTML; catalogue size unverified |
| #FixMedPrices CSV | openAFRICA, CC-BY-4.0 | 1,074 rows / 597 drug names; **no registration numbers** |

Two consequences worth knowing before you read the views:

- A single pharmacy quoting a product in a state is **not** a comparison.
  `v_cheapest_per_product_state` therefore carries `pharmacy_count` and `is_comparison`, and is
  only a "cheapest" claim when at least two independent pharmacies quote the product there.
- ~77% of sampled NAFDAC registrations were `Expired` or `Inactive`, so
  `v_suspicious_listings` has real rows — but the register is maintained, not frozen (latest
  approval date observed: 2026-03-31).

## Layout

```
schema/     numbered, idempotent .sql — run in order against an empty database
scripts/    Python loaders (seed now; scrapers to follow)
seed/       vendored #FixMedPrices CSV (CC-BY-4.0)
docs/       schema, views and seed-data reference
research/   the live probe log behind every volume and status claim
PLAN.md     project map: sources, pipeline, risks, build order, open decisions
```

## Quickstart

```bash
git clone https://github.com/<owner>/NaijaDrugWatch
cd NaijaDrugWatch
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # then paste the Neon connection string into DATABASE_URL

psql "$DATABASE_URL" -f schema/001_extensions.sql
psql "$DATABASE_URL" -f schema/002_tables.sql
psql "$DATABASE_URL" -f schema/003_views.sql
psql "$DATABASE_URL" -f schema/004_materialized.sql

python scripts/load_seed.py --dry-run   # inspect the SQL, no database needed
python scripts/load_seed.py             # upsert products + drug_match_rules
```

`001_extensions.sql` must run first: the `vector` type has to exist before a table uses it.

## Data sourcing disclosure

This project reads **publicly listed product and price data** from Nigerian pharmacy websites
and the publicly published NAFDAC Greenbook. Specifically:

- It collects product names, prices, pack sizes, stock status, pharmacy location at city/state
  level, and NAFDAC registration number, status and dates.
- It does **not** collect personal data, customer reviews, prescription information, or anything
  behind a login. The NDP Act 2023 governs personal data; none is processed here.
- `robots.txt` is honoured per domain, requests are limited to **one every two seconds per
  domain**, and the User-Agent identifies the project.
- No attempt is made to circumvent a block, rate limit or access control. If a source blocks
  access, this project reports the source as stale rather than working around it.

## Attribution and licence

- **Code:** MIT — see [`LICENSE`](LICENSE).
- **Data:** CC-BY-4.0, respecting each upstream licence.
- **#FixMedPrices** (Code for Nigeria, via openAFRICA) is CC-BY-4.0 and must be credited
  wherever its data appears.
- NAFDAC Greenbook data is published by the National Agency for Food and Drug Administration
  and Control. This project is independent and is not endorsed by NAFDAC.

## Limitations

Prices are observed, not guaranteed: a listing is what a website displayed at scrape time, and
stock can change before purchase. Pack sizes are parsed from listing titles, so `unit_price` is
an estimate with a known parse-failure rate. Registration status reflects the last successful
scrape of the Greenbook, not NAFDAC's live state.
