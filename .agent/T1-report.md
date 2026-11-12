# T1 report - MedPlus discovery moved onto the route that paginates

**Written by the secretary on 2026-11-12.** The builder (session `ses_e3245178fffeh0UZokidJBbSkc`)
reached its 30-step cap with the code and all the measurements done but no report file, so this is
its account, re-checked. Sections marked **[secretary]** are my own runs, not the agent's.

## The answer

Yes. MedPlus discovery now walks the site's drugs catalogue instead of six category pages.

The catalogue is **1,396 products over 70 pages** - not the 3,163 the site advertises. Page 70 holds
16 links and page 71 carries none, so 69 x 20 + 16 = 1,396. The advertised 3,163 is a site-wide
result count, not this route's product count; the earlier 3,163 figure in the brief was the
advertisement and it was wrong.

## Changed

`scrapers/medplus.py` - discovery only; parsing, stock and store paths untouched.

| line | change |
|---|---|
| 15 | module docstring documents both routes and which one paginates |
| 64 | usage examples: discover-only, dry run, full sweep, legacy category route |
| 89 | `MAX_PAGES = 70` (was 40), with the measurement that makes it a full sweep |
| 95 | `DRUGS_URL` carrying both `page_no` (0-based) and `page` (1-based) |
| 227 | `page_product_links()` - strips query strings, drops the notify form target |
| 240 | `_walk()` - one paginator for both routes; stops on empty page, on no-new-link, on 403/429 |
| 287 | `product_urls()` kept, now delegating to `_walk` (used by `--route category`) |
| 314 | `drug_urls()` |
| 414 | `main()` - `--route {drugs,category}` default `drugs`, `--start-page`, `--discover-only`, `--print-urls` |
| 467 | **[secretary]** the printed discovery rate divided by seconds but was labelled per minute; now multiplied by 60 |

## Verified

**Builder's runs** (pasted from its account, not re-typed):

```
drugs route page 1: +20 products, cumulative 20
... every page +20 ...
drugs route page 10: +20 products, cumulative 200
discover-only: 200 distinct product URLs in 29.1 s
drugs route page 68: +20   page 69: +20   page 70: +16
drugs route page 71: no product links on the page, stopping this route
dry run, page 1, 5 products: records 5, failed 0, price NGN 50.00/450.00/850.00, in stock 5/5
offline unit check: 6/6 (stop-on-repeat, stop-on-429, page_no=n-1, max_pages cap, start_page)
~79 of 80 permitted HTTP requests; no 403, no 429, no challenge
```

**[secretary] re-run, independent, 2026-11-12:**

```
$ scrapers\medplus.py --discover-only --route drugs --max-pages 2
  drugs route page 1: +20 products, cumulative 20
  drugs route page 2: +20 products, cumulative 40
  route drugs: 40 products           (8.1 s)

$ scrapers\medplus.py --discover-only --route drugs --start-page 69 --max-pages 4
  drugs route page 69: +20 products, cumulative 20
  drugs route page 70: +16 products, cumulative 36
  drugs route page 71: no product links on the page, stopping this route
  route drugs: 36 products           (10.1 s)

$ scrapers\medplus.py --discover-only --route drugs --max-pages 1
  20 distinct product URLs in 4.8 s (248 URLs/min)      <- after the rate-label fix
```

So the end of the catalogue and the absence of repeats are confirmed by me, on a different run, not
taken from the agent's log. 69 x 20 + 16 = 1,396 is arithmetic on those two numbers.

**Cost.** 70 discovery pages x ~2.9-4.8 s + 1,396 product pages x ~2.78 s is **about 68-90 minutes**.
Expected nightly: **1 h 49 m -> roughly 2 h 51 m**, against a 6 h job cap.

## The scope trap the brief asked about

Category 12 page 1 is **not** a subset of the drugs route: 20 links, 11 found in the first 200
drugs-route products, **9 missing**. All nine are groceries or confectionery - bottled water, a soft
drink, cotton pads, lozenges. They are rows the nightly writes today and will stop writing. That is
correct for a drug price index and it is a deliberate change in what the database holds, not a
silent loss of drugs.

## Deviations

- Report file not written by the agent (step cap). This file is the secretary's.
- One offline unit fixture failed first, because the fixture itself was wrong, not the code. The
  corrected run passes. That failure is evidence the stop-on-repeat guard is real.
- A throwaway check script was left at `%TEMP%\opencode\t1_discovery_check.py`, outside the repo.
- `scrapers/healthplus.py`'s own `MAX_PAGES = 40` and the stale `--categories` argument in
  `.github/workflows/daily.yml` were left alone: out of scope, and the workflow is a user decision.

## Open risks

1. **The workflow still passes `--categories 12,31,32,50,57,58`.** On the new default that argument is
   ignored and prints a warning, so the nightly changes behaviour without anyone editing the
   workflow. This is the intended fix, but it is a production change that was not typed by hand.
2. **68 minutes is an extrapolation** from 10 discovery pages and 5 product pages. A 1,396-page walk
   may differ.
3. **The request volume is untested.** ~1,466 requests a night against MedPlus, where today is ~134.
   HealthPlus returned 429 after far less probing on a different day. The 403/429 stop is built, so
   a block fails loudly rather than pressuring the site - but the first night is its first test.
4. **A fixed cap is the wrong shape here**: the route is ordered, so `--max-pages 40` would refresh
   the first 800 products forever and never touch the other 596. The bounded alternative is a
   rotating window (`--max-pages 20 --start-page R`, ~19 min a night, full coverage every 4 nights),
   which needs a workflow edit and a rotation counter.
5. Nightly runtime rises by about an hour inside a free-tier job cap that is also shared with the
   other five sources.

## Unproven

- The full sweep has never been run end to end. The catalogue end was reached by skipping to page 69.
- Pages 31-43, 45-55, 57-69 were never fetched by anyone.
- Whether the 9 grocery links appear anywhere in the full drugs route is untested.
- Nothing touched the database (correct per the brief), so no `scrape_runs` row exists for any of
  this, and the effect on stored rows is unmeasured.
