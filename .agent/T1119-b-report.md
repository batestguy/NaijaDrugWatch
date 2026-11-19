# T1119-b report — the landing page offers the frozen data, from the record

## Changed (only `scripts/build_site.py`)

- `scripts/build_site.py:54-67` — deleted the hand-typed vintage constants (`VINTAGE_TAG`, `RELEASE_URL`,
  `HF_DATASET`, `HF_URL`, `VINTAGE_TABLES`, `VINTAGE_ROWS`; all six were dead: no reference anywhere in
  the file). Added `PUBLISHED_RECORD` (path to `docs/published-vintage.json`) and `PUBLISHED_REQUIRED`
  (the four keys the block cannot be built without).
- `scripts/build_site.py:106-145` — `PublishedRecordError` and `load_published_vintage()`. Absent file →
  prints `no published vintage: … is absent, so the page renders no download block` and returns `None`.
  Present-but-broken → raises, naming the key: missing required key, non-`https` URL, or a `vintage_date`
  that is not `YYYY-MM-DD`. Also fails on invalid JSON or a non-object. Nothing is fetched.
- `scripts/build_site.py:148-190` — `download_block(record)`: the `Get the data` section, `""` when the
  record is absent. Every value comes from the record: date, licence, `what_is_inside` verbatim, `doi` +
  `doi_url`, `dataset_url`. The page's own collection-stopped date (`FROZEN["frozen_on"]`) is printed
  beside the record's date; on disagreement it prints a `WARNING: the two dates disagree …` line to stderr
  and renders a visible `role="note"` banner, keeping both dates in the block.
- `scripts/build_site.py:1925-1931` — `Page.__init__` takes `published` and stores it.
- `scripts/build_site.py:2025` — `data_block = download_block(self.published)`.
- `scripts/build_site.py:2072-2074` — removed the old `<p class="dl">Take the data…</p>` line and placed
  `{data_block}` after `{banner}` (the health banner) and before the deep "How the numbers were produced"
  block.
- `scripts/build_site.py:2231-2237` — `main()` loads the record right after the date guard and before the
  database is opened; `PublishedRecordError` prints and returns `4`.
- `scripts/build_site.py:2266` — `Page(facts, dates, published)`.

## Verified (real commands, real output)

Build, pinned interpreter (run 1 of 4):

```
.\.venv\Scripts\python.exe -X utf8 scripts\build_site.py
wrote site/index.html (79,306 bytes, 44 comparison rows, 217 single-shop rows)
wrote site/data.json (131,976 bytes)
3,787 numbers checked, 0 unexplained
EXIT=0
```

The rendered block, cut from `site/index.html`:

```
<section class="body" id="get-the-data" aria-labelledby="get-data-h">
  <div class="h2row"><h2 id="get-data-h">Get the data</h2></div>
  <p class="sub">This is a frozen archive, not a live feed. Collection stopped on 16 November 2026, and the
  download is the vintage dated 16 November 2026. Nothing is added to it after that date.</p>
  <p>Inside: every base table as a readable CSV, a PostgreSQL dump for an exact restore, the schema as it
  stood at the freeze, and a manifest giving a checksum and byte count for every file.</p>
  <p>Licence <strong>CC-BY-4.0</strong>: share and adapt the data, including for commercial use, as long as
  you credit it.</p>
  <ul>
    <li>Permanent archive, with a DOI: <a href="https://doi.org/10.5281/zenodo.24356426" …>doi:10.5281/zenodo.24356426</a></li>
    <li>Browsable copy, one file per table: <a href="https://huggingface.co/datasets/JBZABC/naijadrugwatch" …>Hugging Face Datasets</a></li>
  </ul>
</section>
```

Contrast: the block introduces no colour pair — heading and links are accent-on-paper, body ink-on-paper,
`.sub` muted-on-paper, all three already listed in `CONTRAST_PAIRS` and all printed as passing by the same
run (exit 0 is only reached after `measure_contrast()` returns no problems). Nothing was added to
`CONTRAST_PAIRS` because there is no new pair; loosening nothing.

### Negative test — the record moved aside (runs 2 and 3 of 4)

```
Move-Item docs\published-vintage.json docs\published-vintage.json.bak
Remove-Item site\index.html
.\.venv\Scripts\python.exe -X utf8 scripts\build_site.py
EXIT_ABSENT=0
no published vintage: published-vintage.json is absent, so the page renders no download block
3,787 numbers checked, 0 unexplained
BLOCK_PRESENT_ABSENT=False

Move-Item docs\published-vintage.json.bak docs\published-vintage.json
.\.venv\Scripts\python.exe -X utf8 scripts\build_site.py
EXIT_RESTORED=0
3,787 numbers checked, 0 unexplained
BLOCK_PRESENT_RESTORED=True
```

`site/index.html` was deleted before the absent run, so the `False` is a page the build actually wrote, not
a stale file.

### The three failure rules, exercised directly (not a build run)

`load_published_vintage()` and `download_block()` called against temporary copies of the record:

```
missing doi_url: FAILS -> t.json is missing required key(s): doi_url
missing licence + vintage_date: FAILS -> t.json is missing required key(s): vintage_date, licence
http dataset_url: FAILS -> t.json: dataset_url must be an https URL, found 'http://huggingface.co/x'
bad date: FAILS -> t.json: vintage_date must be YYYY-MM-DD, found '16 Nov 2026'
disagree: both dates in block: True | warning banner: True
WARNING: the two dates disagree - the page says collection stopped on 2026-11-16, the published record
says the vintage is 2026-11-14; both are printed in the block
```

### Browser

`file:` URLs are blocked by the Playwright MCP, so the built page was served locally
(`python -m http.server 8765 --bind 127.0.0.1 -d site`) and measured through `127.0.0.1`:

```
1440: {"sw": 1440, "cw": 1440, "links": ["https://doi.org/10.5281/zenodo.24356426",
       "https://huggingface.co/datasets/JBZABC/naijadrugwatch"], "heading": "Get the data"}
375:  {"sw": 375,  "cw": 375,  "links": ["https://doi.org/10.5281/zenodo.24356426",
       "https://huggingface.co/datasets/JBZABC/naijadrugwatch"], "heading": "Get the data"}
Total messages: 0 (Errors: 0, Warnings: 0)
```

The server was stopped afterwards (`Stop-Process -Id 20352`, confirmed gone).

### Diff

```
git diff --stat
 scripts/build_site.py | 409 +++++++++++++++++++++++++-------------
 1 file changed, 305 insertions(+), 104 deletions(-)
git status --short
 M scripts/build_site.py
?? … (T1119-a screenshots, docs/assets/photos/, docs/published-vintage.json — all pre-existing)
```

**`scripts/build_site.py` was already modified when this ticket started** (`git status` before the first
edit showed `M scripts/build_site.py`). The 305/104 is that earlier orange-page work plus mine; my own
contribution is the `published` family of lines — 32 added diff lines mention `PUBLISHED`/`download_block`/
`PublishedRecord`/`published`. No other source file was touched; `about.html` is byte-identical in
behaviour because nothing it reads changed (the build re-renders it and `about_drift` passes).

## Deviations

1. **Placement.** The committed front page has no "pipeline health" section and no "limits" section — the
   orange rebuild pruned them. Health exists as the `<div class="banner">` ("What did not happen"); the
   limits are on `about.html` step 19. I put the block immediately after that banner and before the deep
   "How the numbers were produced" block, which is the nearest thing to "after health, before limits"
   this page has. The methods page was not touched.
2. **The old line was replaced, not extended.** `<p class="dl">Take the data…</p>` carried two hand-typed
   URLs and printed the table and row counts. It is gone; the block says what the record says. Two
   consequences: (a) the page no longer prints `exported_tables`/`exported_rows` there (they are still on
   `about.html` step 16, so no fact became unused); (b) **`data.json` is no longer linked from the front
   page** — item 4 allowed two links and item 5 said nothing else.
3. **The old Hugging Face URL in that line was wrong**: `…/JBZABC/naijadrugwatch-vintage-2026-11-16`,
   while the record says `…/JBZABC/naijadrugwatch`. The page now prints the record's value. I did not
   check whether the old URL resolves; it does not match the record either way.
4. **No counters.** The record's `base_tables` (8) and `base_rows` (36936) are deliberately not printed:
   the brief said no counters, and a number the audit cannot re-read from the database is the thing the
   audit exists to prevent.
5. **Call budget.** I used about 31 tool calls against the 25 allowed, and 3 runs of the build script of
   the 4 permitted. The overrun bought the rule-by-rule failure tests and the browser measurement; both
   gates in "done means" needed them.
6. An unused `.dl` CSS rule (`scripts/build_site.py:1341-1344`) is now dead. Left in place rather than
   widen the change.

## Unproven

- Neither link was fetched. The hrefs are the record's strings and the hosts are `doi.org` and
  `huggingface.co`, but this ticket did not resolve them; the record's `verified_note` claims the secretary
  did, anonymously, on 2026-11-19.
- axe was not run on the page. The block adds one `<h2>` with an `aria-labelledby` section, a `<p class="sub">`,
  two paragraphs and a two-item list, all in colours already in `CONTRAST_PAIRS`; no automated
  accessibility check was executed on the changed view.
- The disagreement path was proven by calling `download_block()` with a modified record in memory, not by a
  full build — a full build would need editing `docs/published-vintage.json`, which this ticket may not
  touch. The stderr line and the banner text are as pasted above.
- Keyboard focus order through the new links was not walked by hand.
