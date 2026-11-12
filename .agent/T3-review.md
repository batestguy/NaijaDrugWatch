# T3 review - the three uncommitted changes (2026-11-12)

Reviewer: T3, read-only. Commands below were run by me with the pinned interpreter. HTTP: 8 requests to medplusnig.com of 12 allowed, all 2 s apart via RateLimitedClient.

## Verdicts

- scrapers/medplus.py - SHIP WITH TWO NAMED FIXES (discovery transport errors; 429 behaviour in the product loop)
- scripts/link_product_nrn.py - SHIP. The dangerous direction is closed at code level, verified.
- .github/workflows/daily.yml - SHIP. Edit is complete for the workflow; README and PROGRESS docs are now stale.

## Q1 - does the drugs route over-collect? No, on the evidence I have

Ran --discover-only --route drugs --max-pages 1 --print-urls (medplus.py:465-474). All 20 page-1 URLs are medicines or pharmacy products (amatem, coartem, panadol, postinor, zentel). The two borderline items are Shaltoux lozenges and an adhesive plaster - OTC or device, not groceries. Nothing plainly non-medicine. Consistent with the T1 finding that the 9 groceries (bottled water, soft drink, cotton pads) live on the category page and are absent from the drugs route. One page checked, not all 70; the T1 caveat stands.

## Q2 - can the walk silently skip products?

Yes, transiently, and it self-heals. The route is page-ordered; an insert or delete mid-walk shifts later pages by one, so a boundary product can be missed for that night. Duplicates are deduped in-walk (medplus.py:269-271) and store() is hash-guarded (medplus.py:382), so the cost is a one-night absence, corrected the next night. Minor for a daily run.

The residual silent risk is different: MAX_PAGES = 70 is a hard cap (medplus.py:89). If the catalogue grows past 70 pages, page 71 onward is never fetched and the walk ends normally at the cap - no warning, tail silently stale forever. A cap-day where page 70 is still full should print a warning. Optional fix.

## Q3 - does the strength fix widen matching where it should not? No

- --self-test: 18/18 strength fixtures, 4/4 choose() fixtures, exit 0. Run by me, real output.
- Code check, choose() at link_product_nrn.py:269: mismatch rejects only when BOTH sides have tokens and the sets differ, so 80/480MG against a component-only 480 mg register row is rejected, and a fixture asserts it. The dangerous direction (a combination matching a one-component register row) is closed in both fixtures and code.
- Slash-free strings cannot be affected: both old and new regexes require a number followed by a unit; the new pattern only adds slash-chains. The 308-string sweep claim is structurally plausible; I did not re-run the sweep (throwaway script outside the repo).
- Ladder strings (Cefuxime 125/250/500 Tablets, HIV 1/2 Test Kit, 10 percent Dextrose 500/1000 mL) now carry more junk tokens, as T2 disclosed. They can only coincide with other same-number strings, bounded by the similarity floor and the form gate. Known, bounded, accepted.

## Q4 - is the workflow edit complete? Yes, with two gaps nearby

- No other use of --categories in daily.yml. The gate REQUIRED_SOURCES includes medplus (freshness_gate.py:83) and medplus.py:84 SOURCE = medplus matches, so a medplus success still satisfies the gate.
- Runtime: timeout-minutes: 300 (daily.yml:85), header claims about 2 h 50 m. Fits with headroom, but the 68 min medplus figure is an extrapolation from 10 discovery plus 5 product pages (T1 admits this).
- 429 at product 700: THE DAY STILL COUNTS AS DONE. Discovery stops loudly on 403/429 (medplus.py:256-259), but the product loop does not: fetch_product raises on 4xx without retry (medplus.py:338-340), the loop counts one failure and moves on (medplus.py:479-484), so a mid-sweep block means every remaining page is still requested (about 30 min of requests to a site that said stop), then finish_run writes status=success with a partial record_count (medplus.py:511-512), and the gate grades the day fresh. A fully blocked night with 0 records also grades success. This predates the change but now carries about 10x the request volume (about 1,466 per night vs 134).
- README.md:112 and PROGRESS.md still show --categories 12,31,32,50,57,58, which under the new code silently does the FULL 70-page sweep (one printed note, then a full walk). Stale docs; fix before someone follows them.

## Q5 - do the two changes interact? No

medplus.py imports parse_pack, source_hash, unit_price_of, ABSURD_PRICE_NGN from healthplus only (medplus.py:82). Nothing imports the strength parser; no external callers of the restructured product_urls or drug_urls (grep: only medplus.py itself; drugstore.py has an unrelated same-named function). Independent.

## NEW finding neither report covers - a transient error kills the whole walk

My first --discover-only --max-pages 2 run died with FAILED: IncompleteRead(0 bytes read), exit 1. _walk catches only urllib.error.HTTPError (medplus.py:255-260); a transport error at any of the 70 discovery pages aborts the entire run - no retry, no partial list. Product pages already retry transport errors (fetch_product, medplus.py:331-346); discovery does not. In the nightly this fails the step and the whole pipeline re-runs on the next fire. My retry succeeded (40/40 products, no repeats), so it is transient, not a block. FIX: give _walk the same transport-retry fetch_product already has. The offline unit check (6/6) did not include a transport-error case.

## What the reports overstate

1. T2 open risk 4 is wrong for the nightly. It says existing links are not recomputed except via --refresh. But daily.yml:214 runs link_product_nrn.py --refresh every scheduled night, so the first nightly run re-decides EVERY existing link, including the new narrowing direction (a combination no longer matching a component-only register row). The exposure is not opt-in; it lands on the next scheduled run.
2. The daily.yml header states 68 min and 2 h 50 m as measured; they are extrapolations (T1 says so in its own text).
3. The T2 rescue count of 610 is unmeasured - T2 says so; do not cite it as verified.
4. Neither report tested a mid-walk transport failure; it is the one failure mode I actually hit.

## What I did not do

- No database connection (per brief).
- Did not fetch pages 3-70 or any product page; the full sweep is untested end to end.
- Did not re-run the 14,788-string archive sweep or measure false-positive links.

## Human check before trusting the first unattended night

Run the pipeline once via workflow_dispatch, then read the medplus scrape_runs row and its step log: confirm status and record_count are sane (about 1,396 attempted, failed count small) and that the gate still reports all six required sources inside the window.
