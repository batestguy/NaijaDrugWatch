# T5 report - a blip no longer kills the night, a block no longer passes as one

Ticket: `.agent/T5-brief.md`. Two defects, one file. Both proved with an injected failure, not a
real block. Site traffic this session: **12 requests to medplusnig.com** (limit was 40), all via
`RateLimitedClient` at 2 s spacing. No sweep was run.

## Changed

`scrapers/medplus.py` only (plus this report and the progress file).

| Where | What |
|---|---|
| `scrapers/medplus.py:60` | `import http.client` - `IncompleteRead` lives there. |
| `scrapers/medplus.py:98-116` | The two judgement constants: `MAX_FAILED_SHARE = 0.10`, `MIN_RECORDS_FULL_SWEEP = 1000`, each with a comment saying it is a judgement and where the numbers came from. |
| `scrapers/medplus.py:118-128` | `TRANSIENT_ERRORS`: `TimeoutError`, `ConnectionResetError`, `http.client.HTTPException`, `urllib.error.URLError`, `OSError`. |
| `scrapers/medplus.py:131-144` | `class Blocked(Exception)` - a refusal, carrying the URL and the status code. Deliberately not an `HTTPError`. |
| `scrapers/medplus.py:289-327` | `_get()` - one retry policy for every request: 2 retries, 5 s then 10 s (exactly what `fetch_product()` already used); 403/429 raise `Blocked` at once; other 4xx raise at once; `PermissionError` (a robots.txt refusal) is not retried. |
| `scrapers/medplus.py:330-389` | `_walk()` now fetches through `_get()`. Retries exhausted -> raises `RuntimeError` naming the page, the exception and the count found so far. 403/429 -> `Blocked`, logged, and re-raised. Other HTTP statuses still stop the route as before. |
| `scrapers/medplus.py:434-441` | `fetch_product()` is now a two-line call to `_get()`, so discovery and product fetching cannot drift apart again. |
| `scrapers/medplus.py:575-581` | Product loop: `except Blocked` re-raises *before* the per-page handler, printing the position and how many URLs were left unrequested. |
| `scrapers/medplus.py:596-616` | The thin-night test: share of failed product pages, and the records floor when the run is a full sweep (no `--limit`, drugs route, full page budget, page 1). |
| `scrapers/medplus.py:633-646` | Dry run: prints `THIN NIGHT:` to stderr, exits 1. Real run: stores what was genuinely observed, then `finish_run(status="failed", record_count=..., error="thin night: ...")`, exits 1. |

No changes to `common.py`, the other scrapers, `scripts/`, `schema/` or `.github/`. The stub
harness lives outside the repo, in `%TEMP%\opencode\t5_stub.py` and `t5_ledger.py`.

## Verified

### 1. A transient blip is survived, and the walk completes

```
=== 1 transient blip on discovery page 3 ===
argv           ['--discover-only']
exit code      0
http requests  7 total, 0 product pages
  out| drugs route page 3: IncompleteRead on attempt 1/3, retrying in 5 s
  out| drugs route page 3: +20 products, cumulative 60
  out| drugs route page 5: +20 products, cumulative 100
  out| drugs route page 6: no product links on the page, stopping this route
  out| route drugs: 100 products
  CHECK walk completed: PASS - exit 0, expected 100 products over 5 pages
  CHECK retried and only then proceeded: PASS - retry line present
  CHECK request count 7 = 6 distinct pages, page 3 asked twice: PASS - 7 requests, pages [1, 2, 3, 4, 5, 6]
```

7 requests = 6 distinct pages plus one extra attempt at page 3. Not a hang: the walk finished in
5.0 s, which is the retry sleep and nothing else.

### 2. A persistent transport failure ends the walk loudly

```
=== 2 persistent IncompleteRead from discovery page 3 ===
exit code      1
http requests  5 total, 0 product pages
  out| drugs route page 3: IncompleteRead on attempt 1/3, retrying in 5 s
  out| drugs route page 3: IncompleteRead on attempt 2/3, retrying in 10 s
  err| FAILED: RuntimeError: drugs route page 3: IncompleteRead on all 3 attempts, abandoning
       the walk with 40 products found: IncompleteRead(0 bytes read, 4096 more expected)
  CHECK non-zero exit: PASS - exit 1
  CHECK message names page and exception: PASS
  CHECK 5 requests = pages 1-2 plus 3 attempts at page 3, nothing after: PASS - pages [1, 2, 3]
```

It fails rather than returning a short list, because a short list is what the run used to grade as
a complete sweep.

### 3. 429 (and 403) at discovery: stop, zero further requests, exit 1

```
=== 3 HTTP 429 on discovery page 3 ===
exit code      1
http requests  3 total, 0 product pages
  out| drugs route page 3: HTTP 429 - BLOCKED, stopping this run. No retry, no workaround: ...
  err| FAILED: Blocked: drugs route page 3: HTTP 429 - the site refused this client
  CHECK non-zero exit: PASS - exit 1
  CHECK stopped at page 3: PASS - 3 requests
  CHECK BLOCKED message: PASS - printed
  CHECK no page 4 request: PASS - absent

=== 3b HTTP 403 on discovery page 2 ===
  CHECK non-zero exit: PASS - exit 1, 2 requests
```

3 requests for 3 pages: no retry, no page 4.

### 4. 429 while fetching products: 5 of 10 requested, then nothing

```
=== 4 HTTP 429 on product page 5 of 10 ===
argv           ['--dry-run', '--limit', '10']
exit code      1
http requests  7 total, 5 product pages
  out| BLOCKED at product 5/10: https://medplusnig.com/product/p1-4: HTTP 429 - the site refused this client
  out| stopping: 5 URLs left unrequested
  err| FAILED: Blocked: https://medplusnig.com/product/p1-4: HTTP 429
  CHECK non-zero exit: PASS - exit 1
  CHECK only 5 product pages requested of 10: PASS - 5 product pages
  CHECK says how many were left: PASS - printed
  CHECK no fetch of products 6-10: PASS - absent
```

The stub answers listing page 1 and 2 (2 requests) and product pages 1-5 (5 requests). Counting is
of requests actually made, not of intended ones.

### 5. The ledger row says failed - real rows, real database

`max(id)` before: **55**. After: **57**.

```
before: max(id)=55 rows=53
  row: id=55 source=match_listings status=success record_count=0 error=None
  row: id=54 source=drugstore status=success record_count=178 error=None
  row: id=53 source=medplus status=success record_count=128 error=None

blocked run: exit=1 http_requests=4 product_pages=2
  | BLOCKED at product 2/3: https://medplusnig.com/product/p1-1: HTTP 429 - the site refused this client
  | stopping: 1 URLs left unrequested
  | scrape_runs id=56 status=failed

thin run: exit=1 http_requests=22 (floor patched to 100 for this proof; store() stubbed)
  | records              20
  | scrape_runs id=57 status=failed record_count=20 pharmacy_id=-1 - thin night: 20 records from a full sweep (floor 100)

after: max(id)=57 rows=55
  row: id=57 source=medplus status=failed record_count=20 error='thin night: 20 records from a full sweep (floor 100)'
  row: id=56 source=medplus status=failed record_count=None error='Blocked: https://medplusnig.com/product/p1-1: HTTP 429 - the site refused this client'
```

Two disclosures about these rows:

- The client was stubbed for both, so **no HTTP request reached medplusnig.com** for either run;
  the throttle and the ledger are real. Ids 56 and 57 are therefore rows about stub runs, not
  about the market, and a future reader should not read them as a medplus outage.
- Id 57's floor was patched to 100 and `store()` was stubbed, because reaching the real floor
  (1,000) would have meant inserting about 900 invented listings into `pharmacy_listings`. The
  branch under test - `finish_run(status="failed", record_count=..., error=...)` - is the real
  line in the file, unmodified.

### 6. A normal short run still succeeds

```
$ .\.venv\Scripts\python.exe -X utf8 scrapers\medplus.py --dry-run --limit 5 --max-pages 2
  drugs route page 1: +20 products, cumulative 20
  drugs route page 2: +20 products, cumulative 40
route drugs: 40 products
product URLs: 5
--- dry run ---
products fetched     5
records              5
failed               0
price NGN min/median/max 50.00 / 450.00 / 850.00
absurd prices        0
in stock             5
pack parsed          3
unit_price set       1
archive              medplus-2026-11-12-03.jsonl.gz sha256=c997db3c3f4bda93
dry run: no database rows written
EXIT=0
```

And the legacy route still exits 0, so the floor does not punish a deliberate small walk:

```
$ ... scrapers\medplus.py --dry-run --limit 2 --max-pages 1 --route category
dry run: no database rows written
EXIT=0
```

**Which path the floor sits on, and why.** Both thresholds are checked on every completed run that
reaches the product loop, dry or real; the **records floor only applies when the run is a full
sweep** (`--limit` absent, `--route drugs`, `--max-pages >= 70`, `--start-page 1`). A sample is not
a thin night: `--limit 5` asks for five products and got five, which is complete for what was
asked. The failed-share test does apply at any size, because "more than one page in ten is broken"
means the same thing at 5 pages as at 1,396.

### The full harness result

```
===== 0 failed checks: [] =====
```

(22 checks across 9 scenarios: transient, persistent, 429 discovery, 403 discovery, 429 products,
share gate, records floor, healthy 1,400-record sweep, sample of 5.)

## Deviations

1. **The blip test needed a second attempt to prove, not a first.** My first harness run reported
   nine failures; all nine were bugs in the harness (exception factories returning lambdas, and two
   request-count expectations that forgot the retried page is requested twice). The scraper was not
   changed to make them pass - the counts were corrected in the harness.
2. **`--dry-run --limit 5` was run with `--max-pages 2`.** Without the cap, discovery walks all 70
   pages before `--limit` truncates the list, which is 75 requests against a 40-request budget. The
   page cap changes nothing about the code path under test.
3. **Test 1's expected request count in the brief's wording ("the full page count") is 7, not 6** -
   the retried page is necessarily requested twice. Stated so a reader of the log is not surprised.
4. **`fetch_product()` lost its own body and calls `_get()`.** The alternative was two copies of the
   same retry loop, which is how discovery came to lack one in the first place.
5. **Nothing was written to `common.py`.** `TRANSIENT_ERRORS` and `Blocked` are local to medplus; if
   the other sources want the same policy it should be lifted deliberately, not as a side effect.

## Open risks

1. **The thresholds are a judgement, and a quiet night cannot trip them - but a changed catalogue
   can.** A normal night re-reads every product page, so `records` tracks the catalogue (~1,396),
   not the day's price changes; a quiet market does not move it. What *would* trip the floor is the
   catalogue legitimately shrinking below 1,000 products (70% of today's), or the drugs route
   re-paginating to fewer pages. Both are real changes that deserve a failed night and a human
   look, which is why the floor is where it is - but if MedPlus ever trims its catalogue, this
   scraper will fail every night until the constant is re-measured. That is the intended trade: a
   red step, not a silent one.
2. **The failed-share threshold has no measured baseline.** Nobody has recorded how many product
   pages fail on a healthy night with this code; 10% (139 pages) is deliberately generous so that
   template drift on a handful of pages does not fail a night. If the first unattended run reports
   a large `failed` count, read it before trusting the second.
3. **A non-403/429 HTTP status in the middle of a discovery walk still truncates the route**
   (logged, then `break`) - that is the pre-existing behaviour, kept to hold scope. The records
   floor is the only backstop, and only on a full sweep. A 404 past the real end of the catalogue
   is the benign case; a 500 at page 40 would silently cost the tail for one night.
4. **A failed step does fail the job.** `run_step` in `daily.yml` records the non-zero exit in
   `FAILED` and the Pipeline step ends with `exit 1`, so the job goes red and the notification
   path sees a failure - that is what the gate's rule wants. Two consequences worth naming: other
   sources still run (they are independent steps), and the freshness gate will report medplus
   stale for that day, which is correct for a blocked night.
5. **Stopping on 429 loses the products already fetched, for that night only.** A block raises
   before the archive is written and before `store()` runs, so the ~700 products fetched before the
   refusal are discarded. I judged that better than archiving a partial dump whose name would claim
   to be a full sweep. The cost is bounded: the next successful night re-reads the whole catalogue,
   and `price_history` keeps every earlier observation. If a run of blocked nights is expected, the
   right change is a separate `-partial` archive name, not a partial `success`.
6. **`HARD_TIMEOUT_S = 40` is still unused** (found, not touched - it was unused before this
   ticket).
7. **Two `scrape_runs` rows about stubbed runs now exist** (ids 56, 57). They say `failed`, so
   `v_pipeline_health` will show medplus as failed at those timestamps. Expect that; it is not an
   outage.

## Unproven

- **No full sweep was run**, so the 1,396-product path is proven only against a stub that produces
  1,400 links in the same shape. The real 70-page catalogue, its runtime under a real 2 s throttle,
  and the real per-night failure rate are all still unmeasured.
- **No real 403/429 was experienced**, by design. Whether Cloudflare answers 429 or 503 on this
  host, and whether the block arrives on a product page or only on discovery, is unknown.
- **The thin-night ledger branch was exercised with the floor patched and `store()` stubbed** (see
  above), so "a thin real run writes `failed` with the real counts" is argued from one real line of
  code plus one real stubbed row, not from a real thin run.
- **The workflow was not executed.** The claim that a non-zero exit turns the job red comes from
  reading `daily.yml:197-232`, which the brief instructed me not to edit.
