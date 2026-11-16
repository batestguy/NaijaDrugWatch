# T1114-a — the 20 + 20 sample: report

**Written by the secretary, not the agent.** The builder ran out of steps with the code half-wired:
the sampling functions and the page-side reporting existed, but nothing called them, no build had been
run, and no report or progress file was written. It said so plainly rather than claiming delivery,
which is the right call and is why this file can be trusted as a record.

## 1. What changed

All in `scripts/build_verify_desk.py`.

| where | change | by |
|---|---|---|
| `:101-107` | `SAMPLE_SEED = 20261114`, `SAMPLE_SIZE = 20`, the canonical and fixture sample paths | builder |
| `:738-811` | `sample_label`, `draw_sample` (sorted ids, `random.Random(seed + stream)`, sorted output), `sample_payload` (asked/drawn/shortfall/items), `write_sample` | builder |
| `:813-822` | `verify_written_sample` — reads the artifact back and compares | secretary |
| `:1156-1197` | page JS: `sampleOf`, `sampleRank`, `sampleIndexOf`, `ordered` — sample cards first, whole worklist still reachable | builder |
| `:1509-1599` | page JS: `wilsonBounds`, `share`, `sampleCounts`, `reportBlock`, `renderSampleReport`, `sampleBanner` | builder |
| `:2107` | `<div id="sample-report">`, and the five-sentence reading instructions above it | builder |
| `:2374-2404` | `self_check` assertions: drawn count, no duplicate ids, unknown ids, shortfall arithmetic, **determinism by drawing again**, embedded sample equal to drawn sample | secretary |
| `:2475-2509` | `write_fixture` wired: draw, attach to meta, render, check, write, read back | secretary |
| `:2600-2620` | `main` wired the same way for the live build | secretary |

Generated: `site/verify/demo.html` (68,159 bytes), `.agent/verify-sample-2026-11-14.fixture.json`.
The canonical `.agent/verify-sample-2026-11-14.json` is written by the **live** build, which has not run
yet — see §5.

## 2. Verified — the command and its real output

```
> .venv\Scripts\python.exe -X utf8 scripts\build_verify_desk.py --fixture site/verify/demo.html
fixture: sample drawn - 1 licence, 1 pack, seed 20261114, written
  .agent/verify-sample-2026-11-14.fixture.json and read back
fixture: wrote site/verify/demo.html (68,159 bytes)
fixture: licence card flag -> HealthPlus: title says 800 mg, product says 400 mg
fixture: pack card line 5 -> Fail - both rows are HealthPlus
fixture: pack card line 4 -> 20 tablet vs 25 tablet - differs
fixture: 64 checks passed, 0 failed
```

**Determinism.** Two consecutive fixture builds, sample file hashed each time:

```
run1 65F2D9FD83CEC149B9E52A6CD36C6CE5BB0E899141A616525527B8A368318390
run2 65F2D9FD83CEC149B9E52A6CD36C6CE5BB0E899141A616525527B8A368318390
DETERMINISTIC: bytes identical
```

**Exactly twenty, and the shortfall arithmetic.** Called in-process on synthetic worklists:

```
long:  asked 20 drawn 20 shortfall 0
same draw twice: True
short: drawn 7 shortfall 13
short note: The licence worklist holds 7 items, fewer than the 20 the pre-registration asks for. All 7 ...
pack short: drawn 3 shortfall 17
exact 20: drawn 20 shortfall 0
```

**The interval is the real function from the page, run under node** (extracted from the built JS, not
re-implemented):

```
0/20   ->  0.0% to 16.1%
10/20  ->  29.9% to 70.1%
20/20  ->  83.9% to 100.0%
1/20   ->  0.9% to 23.6%
```

These match published Wilson bounds. The first line is the one that matters: **twenty cards all passing
is still compatible with a 16% failure rate**, and the page prints that rather than a bare percentage.

**No network reference** outside the data block continues to be asserted by `self_check` — the fixture
passes it at 64 checks.

## 3. Deviations

- The builder's brief said to prove the long-worklist case by an in-memory call; it never got there. I
  did it, using synthetic items, because the live worklist is mid-scrape.
- The fixture writes `.agent/verify-sample-2026-11-14.fixture.json` as a second file, which the brief
  permitted for the determinism proof. It is named `.fixture.json` so it cannot be mistaken for the
  canonical selection.
- `sample_label` uses a nested `item["state"]` inside an f-string, which needs Python 3.12. The pinned
  interpreter is 3.12.13, so this is fine here and would break on 3.11. Left as the builder wrote it.

## 4. Open risks a reviewer should check hardest

1. **The page has never been opened in a browser.** Everything above is build-time and node-level. The
   banner, the ordering of sample cards, the report table updating as cards are ticked, and the shortfall
   note have not been seen rendered. That is the first thing to look at.
2. **`self_check` cannot tell a working sample block from an inert one** if `meta["sample"]` is absent —
   the sample assertions are skipped when `sample is None`. Both callers now pass it, but a future caller
   could silently omit it and every check would still pass.
3. **The report counts only what is ticked in that browser.** A person who ticks ten cards, exports, and
   reloads elsewhere gets a report over ten. There is no guard against a partial run being read as the
   whole sample — the page says "judged 10 of 20", which is the only defence.
4. **`cannot tell` is excluded from the denominator**, which is the pre-registered rule, but it means a
   sample where most cards are unjudgeable produces a confident-looking rate over a handful.

## 5. Unproven

- The **live build**, and therefore the canonical sample file, the real drawn ids, and the real shortfall
  (if any). It waits for tonight's MedPlus step to finish; a build taken mid-scrape would embed
  half-written state.
- Whether twenty is even available on the licence list after tonight's run.
- Any rendering behaviour in a real browser, including keyboard navigation through sample cards.

---

# Closed later the same day — live build and a browser

The nightly job (`43582402843`) finished green at 11:56 UTC, and the desk was rebuilt from the finished
data. Everything in §5 that could be closed, now is.

## Live build, unedited output

```
wrote site/verify/index.html (416,975 bytes)
licence cards embedded: 87 products, 155 shop listings, 5 questions each
pack cards embedded:    44 cells, 124 shop rows, 6 questions each
computed warnings: 1 licence cards and 1 pack cards carry a strength disagreement; 0 pack cards have both rows from one shop
data as of: 2026-11-14 10:54 UTC (prices 2026-11-14 11:48 UTC, register 2026-11-14 10:54 UTC)
sample drawn: 20 of 87 licence cards, 20 of 44 pack cards, seed 20261114, written to .agent/verify-sample-2026-11-14.json and read back
2,419 checks passed, 0 failed
```

So the shortfall did not arise: both lists hold more than twenty, and exactly twenty were drawn from
each.

## The artifact, checked against the page

Read back from `.agent/verify-sample-2026-11-14.json` and compared with the data block embedded in the
built page:

```
licence: asked 20, drawn 20, shortfall 0, items 20
  ids not present in the embedded licence list: 0
  distinct ids: 20
pack:    asked 20, drawn 20, shortfall 0, items 20
  ids not present in the embedded pack list: 0
  distinct ids: 20
embedded sample == file sample: True
```

First three licence picks: `Carvedilol · 6.25 mg · A11-0682`, `Albendazole · 100 mg/5 ml · A4-3157`,
`Libre Tizanidine Tablets · 2 mg · C4-0141`.

## Browser check

The page was served from a local read-only server (the browser refuses `file://`) and driven through a
real browser.

- The first card renders under **"In the sample · Sample card 1 of 20"** with the seed line beneath it.
- The report region renders above it with both tables, and its caption reads: *"Sample only, from the
  cards ticked in this browser. Seed 20261114; selection in .agent/verify-sample-2026-11-14.json."*
- Ticking one line changed nothing in the counts (`0 of 20 judged`) — correct, because a card is judged
  only when every line is answered.
- Ticking all five lines of the first card moved the report to **`1 of 20`**, and the share line to
  **`1 of 1 = 100.0% (95% Wilson 20.7% to 100.0%)`** — so the report does update live, and the interval
  is the real one, not a placeholder.

Screenshot: `.agent/verify-desk-sample-report.png`.

## Still unproven, precisely

- **Keyboard operation** of the sample cards was not exercised. The page advertises ↑ ↓ p f u, and that
  claim is untested by me.
- **No axe run** on this page, before or after.
- The **"Outside the sample"** banner on card 21 and beyond was not seen; it was only read in the source.
- **One card ticked by me, in a test browser, as a mechanics check** — it is not a verification result,
  it is not in the sample file, and the desk's report in a fresh browser starts at zero.

## Files at the end of this ticket

- Tracked and modified: `scripts/build_verify_desk.py`
- New, untracked, and intended to be committed: `.agent/verify-preregistration-2026-11-14.md`,
  `.agent/verify-sample-2026-11-14.json`, `.agent/T1114-a-report.md`
- Generated build output, ignored by git (`site/` is ignored on purpose): `site/verify/index.html`,
  `site/verify/demo.html`
- Scratch: `.agent/verify-sample-2026-11-14.fixture.json` (fixture selection, kept for the determinism
  proof)
