# FROZEN — vintage 2026-11-16

This project stopped collecting on **16 November 2026**. The data it holds is dated, complete for
the days it covers, and no longer moving. Nothing below is a promise about the present.

- Schedule: **disabled** on 2026-11-16, before that day's scheduled fire (`daily`, workflow id
  410978489, state `disabled_manually`). Re-enable with `gh workflow enable 410978489`.
- Last data collected: **2026-11-15**. Prices scraped 12:22 UTC, NAFDAC register 11:28 UTC.
- Repository state at freeze: `1001d45`, with uncommitted changes described in PROGRESS.md.

## Why it stops

A nightly pipeline is a standing promise, and one that runs unwatched on free tiers ends by
publishing stale numbers with nobody's name on the failure. The measurements at the end made the
choice obvious: 5 to 42 prices changed per night against 2,800 on the shelf, and the weekly
price-change view had produced three products. Continuing would have cost 68 minutes a night to
record that nothing happened.

## What is frozen

`vintage/2026-11-16/`, 12,284,353 bytes over 10 files. Gitignored, because it is above the 5 MB
repository rule; the published copy belongs on Hugging Face Datasets.

| file | what it is |
|---|---|
| `drug_match_rules.csv`, `nafdac_registrations.csv`, `nafdac_status_snapshots.csv`, `pharmacies.csv`, `pharmacy_listings.csv`, `price_history.csv`, `products.csv`, `scrape_runs.csv` | every base table, as `COPY ... CSV` with a header |
| `schema-record.txt` | columns and types, keys, constraints, indexes, extensions, and the full definition of every view and materialised view |
| `naijadrugwatch.dump` | `pg_dump` custom format, for an exact restore |
| `MANIFEST.json` | row count, column count, bytes and sha256 per file, plus how it was made |

**8 tables, 36,936 rows.** Views and materialised views are deliberately **not** exported as rows:
they are derived, and a second copy of a derived number is how a vintage drifts. Their definitions
are in `schema-record.txt`.

## How the freeze was made

```powershell
gh workflow disable 410978489                    # schedule off
.venv\Scripts\python.exe -X utf8 scripts\export_vintage.py 2026-11-16
.venv\Scripts\python.exe -X utf8 scripts\build_site.py
.venv\Scripts\python.exe -X utf8 scripts\build_verify_desk.py
```

The materialised index was refreshed immediately before the export: 428 rows before, 428 after,
newest day 2026-11-13. The export opens the connection read-only twice over, so it cannot write to
the source.

## Verified at freeze

- **Export:** every CSV's data-row count equals the database count. 0 mismatches out of 8.
- **Dump:** `pg_restore --list` reads it and shows 8 `TABLE DATA` entries, 5 views, 1 materialised
  view.
- **Public page:** build exit 0, **3,526 numbers checked, 0 unexplained**; 44 comparison rows and 217
  single-shop rows; 105,796 bytes.
- **About page:** 14,247 bytes, built only from sourced facts, refuses to render an unsourced date.
- **Verification desk:** build exit 0, **2,402 checks passed, 0 failed**; 86 licence cards and 44 pack
  cards; 414,852 bytes.
- **Sample:** 20 of 86 licence cards and 20 of 44 pack cards, seed `20261114`, no shortfall, drawn
  before any card was judged. The same ids came out of two consecutive builds. The sample file records
  the minute it was built, so rebuilding the desk rewrites that one line; the ids never move, which is
  the property that matters.
- **Independent re-check** by the secretary, 16 assertions, all pass: sample valid UTF-8, 40 unique
  ids, every id present in the built desk, desk population equal to the database (44 comparisons,
  86 products, 154 rows), page numbers equal to the database (2,800 listings, 559 attached).
- **The page says it is frozen.** `freeze.json` carries the dates; the page reads that file, prints a
  frozen-snapshot stamp, and measures every source's age to the freeze moment instead of to the wall
  clock. Proven by falsification rather than assumed: the same row reports `stale` at 127.5 hours
  against the wall clock and `reporting` at 13.5 hours against the freeze.

## Checked after the freeze — and what the check can prove

Run on 16 November, after collection stopped, against the live sources. Recorded here because it is
the only evidence about whether the numbers are right, and because its limits are easy to overstate.

| what | how | outcome |
|---|---|---|
| 20 sampled licence records | pages re-read; status, expiry, approval, name, strength, number compared | **20 of 20 matched**, no nulls |
| 18 of those 20 | a person answered all five lines against the live page | 18 pass, 0 fail, 0 cannot tell |
| 44 comparisons, 88 pages | every shop page re-read and compared with the stored price | **88 reads, 0 differences** |
| author's own review | all 44 comparisons looked at; 17 pack cards reviewed but **not** recorded line by line | no disagreement reported |

**The limit.** The 88 page reads went through the same channels the scrapers use. HealthPlus refused
its independent storefront JSON endpoint with `429 local_rate_limited` throughout, so the fallback was
the catalogue feed `scrapers/healthplus.py` itself reads, and MedPlus has no second server-side source.
The check shows the pages did not drift between collection and re-read. It cannot show the parsers read
them correctly, and it is not a human verification. The scored sample is **18 of 20 licence cards and
3 of 20 pack cards**; the other 17 were reviewed but carry no recorded answers and are not counted.

## Defects that check found, deliberately not fixed

1. **One published unit price is per millilitre.** The Vitamin B Complex syrup (product 1037) carries
   pack size 100 with no unit, so it publishes ₦12.50 "per pack unit" directly above a
   ₦2.30-per-tablet row. Of 30 comparison rows with a unit price: 26 tablets, 3 capsules, 1 millilitre.
2. **Two names appear twice at very different prices** — Amlodipine 5 mg ₦950 and 10 mg ₦400; Vitamin B
   Complex syrup ₦1,250 and a 1,000-tablet pack ₦2,300.
3. **18 of the 88 comparison listings carry a pack count with no unit recorded.**

Fixing any of them means a new vintage, which is the rule this record exists to enforce.

## What this vintage holds

| object | value |
|---|---|
| latest price per listing | **2,800** |
| …attached to a named medicine | **559** |
| products in the catalogue | **1,433**, of which **335** carry a price |
| cheapest-per-state cells / two-shop comparisons | **261 / 44** |
| suspicious listings / distinct products | **154 / 86** |
| NAFDAC registrations / with a readable status | **10,967 / 1,856** (16.9%) |
| week-over-week price change | **3** products |
| daily index cells | **428**, newest 2026-11-13 |

## What it does not claim

- **Not a market average, and not a national price index.** Lagos only, three online pharmacies, and
  only the medicines two of them price.
- **The daily index counts newly observed prices, not the live market.** It must never be read as a
  price level.
- **"Suspicious" is a fraction of a fraction.** Only 16.9% of the register carries a status, so a
  listing not flagged means we could not read its licence, not that the licence is good.
- **Supplements and pharmacy sundries are in the price data** and are not medicines.
- **The 44 comparisons are backed by a 40-card sample, not a full pass.** No person has confirmed a
  comparison outside that sample.
- **A lapsed licence is not a fake drug.** The register reports administrative status; the page does
  not claim counterfeiting.

## Not done at freeze

- The verification cards are **not all ticked by a human**. 18 of the 20 licence cards carry recorded
  answers; 3 of the 20 pack cards do. The author reviewed the rest informally and reported no
  disagreement, which is recorded as their claim and not as a scored sample.
- **Nothing is deployed.** No public URL, no dashboard hosting, no API. Two of the four
  definition-of-done items are therefore unmet. The job that would publish the page to GitHub Pages is
  committed, but Pages was never enabled in the repository settings, so it has never run and would
  fail if the schedule were switched back on before Pages is turned on.
- **The accessibility audit has now been run, after the freeze.** axe-core 4.10.2, WCAG 2.0/2.1/2.2 A
  and AA. The public page and the About page: **0 violations** (44 and 29 rules passing). The
  verification desk: 3 violations, all from one cause — each question was an `<li>` carrying
  `role="group"`, which overrides `listitem` and left the parent list without list children — plus two
  landmarks both named "Keys". Fixed; re-run gives **0 violations** on both lists and at 400 px. One
  rule stays *incomplete* rather than failing: `color-contrast` on 13 cells whose background is
  obscured by a scroll container, so those colours were checked by hand (worst pairing 7.22:1 against
  a 4.5 requirement). The dashboard has not been audited since 8 November and is not deployed.
- The dump has been proven readable by `pg_restore --list`, but **never restored into a working
  database**, so restorability is proven to the level of listing, not to the level of a working copy.
  **This is the next task, written out in `PROGRESS.md`**: restore once by hand, then make it a
  committed script and a CI job so the proof can be re-run by anyone.
- Reproduction: the generated pages are not byte-identical between runs because they embed the build
  time to the minute. The sampled ids are stable across builds; the page hash is not.

## How to restore

1. Create an empty Postgres 17 database. Enable `pg_trgm`, `pgvector`, `unaccent` — `schema/001_extensions.sql`.
2. Either restore the dump: `pg_restore --dbname=<url> --no-owner --no-privileges naijadrugwatch.dump`,
   or load the CSVs by hand in dependency order: `pharmacies`, `products`, `drug_match_rules`,
   `nafdac_registrations`, `nafdac_status_snapshots`, `pharmacy_listings`, `price_history`,
   `scrape_runs`.
3. Re-apply `schema/003_views.sql`, `004_materialized.sql`, `005`, `006`, `007`, `008` in order, then
   `REFRESH MATERIALIZED VIEW mv_drug_price_index`.
4. `schema-record.txt` is the authority on what each object looked like at freeze; use it to check the
   restore, not the other way round.

## Re-running the project from this vintage

The deterministic scripts read the database, not the vintage folder: restore first, then
`scripts/build_site.py` and `scripts/build_verify_desk.py` reproduce the two pages. Both refuse to
emit a number they cannot re-derive.
