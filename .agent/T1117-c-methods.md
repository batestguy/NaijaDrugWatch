# How the NaijaDrugWatch price page was built

NaijaDrugWatch joins NAFDAC drug-registration status to prices listed by Nigerian pharmacies. It is an independent, $0/month project, not a shop or a price-comparison business. Neither NAFDAC nor any pharmacy represented in the data endorses it. The code is MIT-licensed; the data are CC-BY-4.0. NAFDAC maintains the register checked against the prices. Dora Akunyili's tribute remains on the front page.

The project is now frozen. This page records how the data and price page were built, what was checked, and what those checks cannot establish.

## The stages, in the order they happened

### 1. The register came first, and it had no API

The NAFDAC Greenbook has no JSON API. `/api/*`, `/sitemap.xml` and `/search?q=` return 404, and no mirror exists. The register was collected from HTML. Six category pages provide each entry's name, form, strength and registration number. Detail pages provide status and expiry.

At freeze, the register contained 10,967 registrations. Only 1,856 (16.9%) had a readable status, because status appears only on detail pages. A missing status does not mean that a registration is Active.

The site's certificate had expired. Pages were therefore fetched over plain HTTP. Locally kept checksums are the integrity check for stored files; the connection itself provided no such assurance.

### 2. The medicine list had to be built, then rebuilt

The starting catalogue was #FixMedPrices, a CC-BY-4.0 national commodities list of 1,074 products. It included herbal and reproductive-health items but almost none of the ordinary products on pharmacy shelves.

To extend it, a tool matched unmatched pharmacy titles against the register. A product was added only when the name overlapped, the strength agreed and the dosage form was compatible. The register, not the shop title, supplied the authority. This added 359 products and brought the catalogue to 1,433. At freeze, 335 of those products had a live price.

### 3. Scraping: API first, and polite

Each pharmacy was read through its product API where one existed and through HTML otherwise. Requests were limited to one every two seconds per host. The User-Agent named the project. Collection included product and price fields only, with no reviews or personal data.

The largest change came from finding the right MedPlus route. Its category pages repeated the same 20 links. The drugs route paginated correctly, with 20 products per page. Page 70 held 16 products; page 71 was empty. This raised collection from 128 to 1,396 products. It extended the nightly run from about 1 hour 50 minutes to about 2 hours 50 minutes.

A refusal counted as failure, not partial success. A 403 or 429 stopped the run and recorded a failed row. A full-sweep night also failed when more than 10% of pages failed or fewer than 1,000 records were returned. These thresholds were judgements, not measurements.

### 4. Matching is two-stage and deterministic

A pharmacy title is never attached to a product on similarity alone. First, the title is embedded; the ten nearest products become candidates. A deterministic rule then checks strength, dosage form and active ingredient. Similarity alone was rejected because a close title can refer to a different medicine.

At freeze, 559 of 2,800 listings were attached to a product and 2,241 were not. A strength guard cleared 54 wrong links across 22 products and left no contradictions under the strict check. It also removed 28 matched listings. One was a known false refusal. “Augmentin 1g” was rejected against an “875mg+125mg” product because the combined strength is 1,000 mg.

### 5. The answers are views, not prose

The page's reported prices and findings come from SQL views. They give the latest price per listing, the cheapest price per product and state, two-pharmacy comparisons, listings with non-Active or expired registrations, seven-day price changes, and a daily index that the pipeline refreshes.

At freeze, the published figures were 2,800 listings, 559 attached to products and 261 cheapest-price cells. Of those cells, 44 were two-pharmacy comparisons. The page also showed 154 listings tied to a registration that was not Active and 428 daily-index rows. The seven-day view returned 3 products. The project record describes the market as quiet.

### 6. The page proves its own numbers

The price page is generated from the database. Its build script runs each query twice. It renders the page, then re-reads the data and compares the printed values with the database. It writes nothing if the readings disagree.

At freeze, the final audit reported 3,787 numbers checked and 0 unexplained. A second generated page lists prices with filters. Each row links to the pharmacy page and the registration record behind it. The links make the sources inspectable, but do not show whether the scraper parsed them correctly.

### 7. Somebody checked it, and recorded how little

Before any verdict, a sampling rule was written down and committed. It selected 20 licence records and 20 pack comparisons by a seeded draw, allowed no substitutions, and specified that an interval be reported with the result. The seed was recorded.

Of the licence cards, 18 of 20 have recorded line-by-line judgements against the live register page. All 18 pass. Of the pack cards, 3 of 20 have recorded line-by-line judgements. The author reviewed the remaining pack cards but did not mark them, so they are not counted as verified.

The sources were also re-read by machine. All 20 register records matched on status, expiry, approval date, name and strength. All 44 price comparisons matched across 88 page reads, with no differences.

That machine check has a narrow reach. Both shops were re-read through the same channels used by the scrapers. One refused its independent endpoint with repeated rate limits; the other has no second server-side source. The re-read shows that the pages had not drifted. It cannot show that the parsers read them correctly. The 44 comparisons therefore rest on a machine re-read plus a small recorded human sample, not a full human audit.

### 8. Then it was frozen, and the freeze was tested

A nightly collection creates an ongoing promise to keep data fresh. Between 12 and 15 November, 5 to 42 prices changed per night, out of 2,800 listings. Collection stopped on 16 November 2026. The schedule was disabled rather than left running without someone responsible for its failures.

Before collection stopped, the data were exported as a PostgreSQL dump, a CSV for each table, a schema record and a manifest with a checksum for every file. The export contains 8 tables and 36,936 rows. It is published as a code-repository release and as a Hugging Face dataset. Both copies are compared with the manifest on every push.

The export is restored into an empty PostgreSQL 17 database on every push. The checks compare restored tables and published figures against the manifest. They include confirming that the 1,433 embeddings return as 384-dimension vectors, not text. A successful restore shows that the archive can be used again. It does not show that the original source pages or their parsing were correct.

## Decisions worth naming, with their cost

| decision | what was chosen | what it cost |
|---|---|---|
| Scheduler | GitHub Actions cron, not Prefect | Free and unlimited on a public repository, but no retry engine and no run history beyond the workflow page |
| Database | Neon, not Supabase | The free tier does not pause after idle days, but it does suspend on inactivity; that is why the export exists |
| MedPlus coverage | Full sweep every night, not a rotating window | About 68 minutes each night to cover the whole catalogue instead of a quarter of it |
| What a comparison means | Two pharmacies publishing a price for the same product | A shop with unconfirmed stock can still count; the page shows that caveat rather than narrowing the count |
| Inactive licences | Labelled, not hidden | The finding stays visible, and readers can see the registration status behind it |
| What was not built | No warehouse layer, ORM or API | The project uses SQL files and scripts; a rebuild means running those files again |

## What it does not claim

- This is not a market index or a national price survey. It covers Lagos, three online pharmacies and 335 medicines with prices at freeze.
- Only 16.9% of the register has a readable status. A “flagged” result describes a fraction of a fraction, not the full register.
- A lapsed licence is not evidence of a fake drug. No product was bought, tested or inspected.
- The price data include supplements and pharmacy sundries that are not medicines.
- One published unit price is per millilitre for a 100 ml syrup, beside prices stated per tablet. The page prints the unit beside every unit price.
- The 44 comparisons have a machine re-read and a small recorded human sample, not a complete human audit.
- Nothing is deployed. The project is available as a repository, a dated export and a generated page, not as a live service.

## Reproducing this

1. Use the repository's pinned Python environment in `.venv` and install the dependencies from `requirements.txt`. Do not substitute a different system interpreter.
2. Apply the SQL files in `schema/` in their numbered order. Then follow the scripts and dependency order in the repository's README to load the seed, collect listings, link registrations, match products and build the pages.
3. With Docker running, verify the frozen export with `.venv\Scripts\python.exe -X utf8 scripts\verify_restore.py`. It restores the dump into a temporary PostgreSQL 17 database, checks the tables and published figures, and removes the container.
