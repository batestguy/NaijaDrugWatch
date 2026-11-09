# T12 report — the two freshness-gate holes are closed

Brief: `.agent/T12-brief.md`. Both should-fix items from `.agent/T10-review.md` are closed. Nothing
in `.github/workflows/daily.yml` was touched, and nothing was committed, pushed or dispatched.

## Changed

| File | Line | What |
|---|---|---|
| `scripts/freshness_gate.py` | 79-90 | `REQUIRED_SOURCES` — the 6 sources a day must report: `nafdac_greenbook`, `nafdac_details`, `healthplus`, `medplus`, `drugstore`, `match_listings`. Comment states the rule for adding one and why a typo makes the gate permanently stale. |
| | 91-97 | `LAST_SUCCESS_SQL` — one grouped-by-source aggregate (`group by source`), replacing the single `max(...) filter`. One query answers both questions. |
| | 129-134 | `query_last_success` returns `{source: datetime}` instead of one timestamp. |
| | 136-188 | `evaluate` — a required source counts only if its success finished at or after the window start; `fresh = not missing`. Every source's timestamp is normalised to UTC. Returns `missing_sources` and `required_sources`. `missed` is unchanged in meaning: a whole UTC day with no success by *any* source. |
| | 190-208 | `render` — appends "N of 6 required sources have no success inside the window: …" (or "all 6 …"). |
| | 222 | `missing_sources` added to the step outputs for the issue body. Additive; the job declares only the four outputs it already used, so this is not wired and needs no workflow edit. |
| | 23-31 | Docstring rule rewritten, and the defect it replaces recorded in-place (index finishes 3-5 min in, so "any success" graded a dead night fresh). |
| `scripts/match_listings.py` | 59-64 | `SOURCE = "match_listings"`, with a comment that `REQUIRED_SOURCES` names this string. |
| | 51 | imports `ensure_connection`, `finish_run`, `start_run` from `scrapers/common` — the existing convention, not a second one. |
| | 194-213 | `main` wrapped: connect → `start_run` → body, all inside `try`. Model load moved inside the `try` so a download failure is a recorded failure. |
| | 249, 274-281 | `record_count = len(assignments)` (listings matched this run); `finish_run(success)` after `ensure_connection`. |
| | 283-295 | Failure path: `finish_run(failed, error=message)`, retried on a fresh connection before giving up — the same shape as `drugstore.py:389-405`. |
| `scripts/link_product_nrn.py` | 53-61 | imports + `SOURCE = "link_product_nrn"`. |
| | 197-213 | Same `start_run` inside `try`; `linked`/`unmatched` hoisted so the failure path can report them. |
| | 256-263, 265-277 | `record_count = products linked` on success; `failed` + `error_message` on the way out. |
| `.agent/T12-progress.md` | — | Unit log. |

`git diff -w` on the two tracked scripts shows no logic change: only the ledger calls, the `try`
indentation, and the docstrings. The 8 pipeline steps in `daily.yml` keep their order and arguments.

## Verified

**1. Stubbed, no database** — `C:\Users\TOSHIBA\AppData\Local\Temp\opencode\t12_stub_gate.py`,
run with the pinned interpreter. Five states; the three acceptance cases first:

```
[A only nafdac_greenbook succeeded today]
  decision=stale run=true missed=false | last successful run 2026-11-09T03:20:00Z (1.92 h ago, diagnostic window 26 h) | gate window opened 2026-11-09T03:00:00Z | 5 of 6 required sources have no success inside the window: nafdac_details, healthplus, medplus, drugstore, match_listings
[B all six required succeeded today]
  decision=fresh run=false missed=false | ... | all 6 required sources succeeded inside the window
[C four of six succeeded today]
  decision=stale run=true missed=false | ... | 2 of 6 required sources have no success inside the window: drugstore, match_listings
[D nothing has ever succeeded]
  decision=stale run=true missed=true | ... | 6 of 6 required sources have no success inside the window: ...
[E all six today, but not a scheduled fire]
  decision=forced run=true missed=false | ... | all 6 required sources succeeded inside the window
```

Case A is the exact hole: the old rule read `2026-11-09T03:20Z` and answered `fresh`. D proves
`missed` still fires. E proves a non-scheduled event still forces and still exits 0.

**2. Live, read-only** — `.venv\Scripts\python.exe scripts\freshness_gate.py --event schedule`
with `DATABASE_URL` from `.env`:

```
decision=stale run=true missed=false | last successful run 2026-11-08T10:15:13Z (19.49 h ago,
diagnostic window 26 h) | gate window opened 2026-11-09T03:00:00Z | 6 of 6 required sources have
no success inside the window: nafdac_greenbook, nafdac_details, healthplus, medplus, drugstore,
match_listings
exit=0
```

Before and after give the same **decision** today, and that must not be read as "nothing changed":
nothing has run since 2026-11-08, so both rules say stale. The old rule's input, queried directly,
is `2026-11-08 10:15:13.85+00`, identical to the new `last_success`. What changed is the reason text
and the discrimination above it. Per-source probe (read-only):

```
drugstore 2026-11-08 10:15:13.85+00 | healthplus 2026-11-08 09:07:36.15+00
medplus 2026-11-08 10:07:49.19+00 | nafdac_details 2026-11-08 09:03:50.88+00
nafdac_greenbook 2026-11-08 08:44:09.66+00
rows since 2026-11-09T03:00Z: (none)
match_listings / link_product_nrn rows: []
```

**3. Ledger rows, proven without a scrape** — `…\Temp\opencode\t12_ledger_proof.py`. Method: each
module's `db_connect` is monkeypatched to return a fake connection that records every statement and
answers the queries from canned rows; `fastembed` is replaced by a stub module in `sys.modules` that
returns 384-dim vectors. Nothing reaches Postgres — no INSERT is issued anywhere real, so there is
nothing to roll back. Six scenarios, `main()` called for real:

```
[match_listings --limit 1 (real run)]  main() -> 0
   insert into scrape_runs (source, status) values (%s, 'running') returning id
   params=('match_listings',)
   update scrape_runs set status = %s, record_count = %s, error_message = %s, finished_at = now() where id = %s
   params=('success', 1, None, 901)
   VERDICT: insert_rows=1 update_rows=1 -> ledger row written

[match_listings --limit 1 --dry-run]  main() -> 0
   VERDICT: insert_rows=0 update_rows=0 -> NO ledger row

[match_listings (listing query fails)]  main() -> 1
   params=('match_listings',)
   params=('failed', None, 'RuntimeError: simulated failure on: from pharmacy_listings', 903)
   VERDICT: insert_rows=1 update_rows=1 -> ledger row written

[link_product_nrn]  main() -> 0        params=('success', 1, None, 904)   -> ledger row written
[link_product_nrn --dry-run]  main() -> 0                                -> NO ledger row
[link_product_nrn (product query fails)]  main() -> 1
   params=('failed', None, 'RuntimeError: simulated failure on: select id, canonical_name, form, strength from products', 906)
   VERDICT: insert_rows=1 update_rows=1 -> ledger row written
```

The match case matched exactly 1 of 1 listing through the real `match_all`/`rule_accepts` path, so
`record_count=1` is a real count, not a constant.

**4. Syntax** — `.venv\Scripts\python.exe -m py_compile scripts\freshness_gate.py
scripts\match_listings.py scripts\link_product_nrn.py` → exit 0 (`compile: ok`).

**Not run, deliberately:** no real scrape, no pipeline dispatch, no `dbt`/SQL change, no write of any
kind to the database (the only statements sent were `select`s).

## Operational consequence — read this before the next fire

`scrape_runs` has **zero rows** for `match_listings` and `link_product_nrn` (`[]` above), so from
the moment this ships the gate will report the day as **unrun** until one full pipeline run under
the new code writes a `match_listings` success. That is the intended behaviour, not a regression:
the first scheduled fire after this lands will run the pipeline instead of skipping. Expect one
extra full-length run (~1.5 h) and one extra `daily:` issue-free run in the Actions list.

## Deviations

1. **`record_count = 0` is still `status='success'`.** A night where every scraper finds nothing new
   considers 0 listings and matches 0. Calling that `failed` would re-run the whole pipeline on every
   fire for a genuinely quiet catalogue; the row is honest because it ran and matched nothing, and
   `0` is visibly distinct from `1,234`. It is never written from a `finally` — an exception always
   yields `failed`. Say the word and it becomes `failed` on `considered == 0` in one line.
2. **`--dry-run` (and `--embed-only`) write no row.** The brief offered "a `--dry-run` path that
   still writes the row" as one way to prove the INSERT. I did the other one, because a dry run that
   wrote `success` would make the gate skip a night whose views are stale — the exact hole being
   closed. The proof is the monkeypatched call above.
3. **`link_product_nrn` writes a row but is not in `REQUIRED_SOURCES`.** The brief fixes the required
   set at five sources plus `match_listings`. A failed link step leaves the views correct, just with
   fewer suspicious rows, so it is not a reason to re-run a 1.5 h pipeline. The row exists so
   `v_pipeline_health` can see the step; it will now appear there as a real source and no fake
   marker was added.
4. **`missing_sources` is emitted but not consumed.** `daily.yml` is untouched; the reason text that
   the notify job already prints carries the same information.

## Left alone

- `.github/workflows/daily.yml` is already modified in the working tree by the previous session
  (`git status` shows it dirty at session start). I did not change it; no change was needed.
- `PROGRESS.md` untouched, as instructed.
- Pre-existing, unrelated: `match_listings.py` sets module-level caches (`WORDS_CACHE` etc.) via
  `global`, which makes two calls in one process unsafe. It never mattered for a one-shot script.

## Unproven

- **No real run of either script against the database.** The ledger row is proven issued, not
  proven accepted by Neon (column types, `record_count` as `int`, `error_message` truncation at
  2000 chars are read from `common.finish_run` and from the scrapers' working path, not exercised
  live here).
- **The `--embed-only` path** shares the dry-run condition but was not executed.
- **A failure before `start_run`** (bad credentials, `fastembed` import error) writes no row, so the
  gate stays stale and the next fire retries. That is the desired outcome but it is inference from
  the code, not a test.
- **The 6-source requirement has never been satisfied in production**, so `decision=fresh` on real
  data is untested. Cases B and E are the only evidence it can happen.
- Test harnesses live in `C:\Users\TOSHIBA\AppData\Local\Temp\opencode\t12_*.py`, outside the repo
  (the brief restricted repo writes). They are not committed; the commands above re-run them as-is.
