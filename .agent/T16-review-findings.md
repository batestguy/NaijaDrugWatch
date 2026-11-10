# Review findings — two attempts, one partial verdict

**Written by the secretary.** Both reviewer sessions ended at their step limit; the second could not
run a single non-git command. This file records what each attempt established, what it found, and what
remains unproven. It is not a clean audit, and it should not be read as one.

## Attempt 1 — static review only, no execution

Read the three reports, `schema/006_stock_confidence.sql`, `scrapers/medplus.py`,
`scripts/stock_signal_watch.py`, `.github/workflows/daily.yml`, `dashboard/app.py:220-279`,
`docs/views.md`. Ran no commands.

**Findings, and their status:**

| # | Finding | Status |
|---|---|---|
| 1 | All three "Verified" sections were unverified claims | **Correct at the time**, and correct about its own work. The secretary had verified them; the reviewer had not. |
| 2 | No findings file written | Correct — that became this file. |
| 3 | **The alarm fires once and then silences itself during a sustained outage** | **Real. Confirmed and fixed.** See below. |
| 4 | `docs/views.md` still documents the pre-006 contract; the file says `integer` where the column is `bigint` | **Real. Both fixed.** |
| 5 | `is_comparison` now counts pharmacies whose stock we could not read as competitors | **Real, disclosed, deliberate.** Documented in `docs/views.md`. |

**Structural questions it cleared by inspection** (no execution): appending columns cannot break the
dashboard, which selects by name (`app.py:173`, `:238-243`); the parser's old selector is consulted
only when the new one finds nothing, so a fallback cannot overwrite a good reading
(`medplus.py:144-163`); the `continue-on-error` / `stock_outcome` wiring in `daily.yml:86-89`,
`:276-280`, `:326` is structurally correct.

## Attempt 2 — blocked by tool permissions, nothing executed

Check 1 passed: the dirty tree is exactly the expected files —

```
M .github/workflows/daily.yml   +48
M docs/views.md                 +28
M scrapers/medplus.py           +133 -24
?? schema/006_stock_confidence.sql
?? scripts/stock_signal_watch.py
?? .agent/T14-report.md  .agent/T15-report.md  .agent/T16-report.md  .agent/T16-review-brief-2.md
```

Checks 2-6 were never run. Every non-git command — including `.venv\Scripts\python.exe -V` and
`Get-ChildItem` — was rejected by the permission system with `permission.rejected: shell`. This is an
environment limitation of the reviewer session, not a logic or scope failure. **The same interpreter
runs fine in the parent session**, so the blocker is how subagent shell permissions are set up here,
and a third reviewer without fixing that would fail identically. That is why there was no third
attempt.

**Consequence, stated plainly: no independent execution-based audit exists for these three changes.**
Every number below was produced by the secretary, who also wrote two of the three reports. The
builders' own claims were re-run by the secretary, and the static reviewer's two real defects were
fixed — but a same-party check is a plausibility check, not an audit.

## Defect 3, confirmed and fixed

The alarm compared the latest day against the **median** of prior days. Fed synthetic series
(three clean days, then N fully-unknown days):

| broken days | verdict before fix | after fix |
|---|---|---|
| 1 | alarm | alarm |
| 2 | alarm | alarm |
| 3 | alarm | alarm |
| 4 | **ok** | alarm |
| 8 | **ok** | alarm |

With the median as the baseline, a permanent break became the new normal on day four and silenced its
own alarm. The baseline is now "at least one prior day below the clean threshold"
(`stock_signal_watch.py:131-152`), so a break alarms every day until a human resolves it; the notify
job's one-issue-per-title dedup turns that into one issue with comments.

Cost of the change: a source that legitimately stops carrying stock for months will alarm nightly
until someone closes the issue. That is judged correct — an unresolved alarm should stay visible.

## Re-verified by the secretary, with real output

```
stock_signal_watch.py                       -> ALARM MedPlus 0.6% -> 100.0% (2026-11-09)  EXIT=1
stock_signal_watch.py --as-of 2026-11-08    -> ok: no source lost its stock signal          EXIT=0
read-only probe (autocommit + options):     -> on; UPDATE/DELETE/INSERT all ReadOnlySqlTransaction
006 applied a 4th time                      -> cells 264 / comparisons 45, unchanged
view column contract                        -> 23 columns, three new ones last
MedPlus pages (2 unavailable, 2 available)  -> hidden max 0, 0, 145, 194; visible max 50 on all four
MedPlus rows written today                  -> 39 in stock, 4 out of stock, 0 unknown
```

## Still unproven — the honest list

1. **GitHub Actions has never run any of this.** That `continue-on-error` keeps the `pipeline` job
   green while the step's outcome becomes `failure` is documented behaviour, not observed here.
2. **Independent execution-based review does not exist.** See above.
3. **The threshold is a judgement, not a measurement.** 10% / 25% / 50 rows fits the one real event.
4. **Most of MedPlus's catalogue still carries the 2026-11-09 null reading** — 43 of 1,405 rows have
   been re-read. The nightly run fixes the rest by collecting, not by repairing.
5. **The magnitude of `max` is not interpreted.** Zero versus non-zero only. If some template uses
   `max` as a per-order cap, it would read as a confident "in stock" and the monitor would not see it.
