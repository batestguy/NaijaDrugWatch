# T1120-e — the landing page's stamp now says when collection started

The stamp reads the collection range from the database. Neither date is typed, and both ends of the
range are audited the way every other stored timestamp on the page is audited: read once, rendered,
read again, compared at zero tolerance.

**Wording chosen: the owner's two sentences, not the one-sentence variant.**
`Collected 7 to 15 November 2026. Collection stopped on 16 November 2026.`
The brief quoted the second sentence word for word and the one-sentence variant lowercases it
("collection stopped"), so the two-sentence form is the one that keeps the owner's words intact.

## 1. Changed

`scripts/build_site.py` — the only source file touched (85 insertions, 5 deletions).

| where | what |
|---|---|
| `scripts/build_site.py:966` | `COLLECTION_RANGE_SQL` — `min(recorded_at)` and `max(recorded_at)` from `price_history`, plus the same two values read as Lagos calendar days (`at time zone 'Africa/Lagos'`) |
| `scripts/build_site.py:976` | `class MissingRange` — raised when the range cannot be read; a guessed date must never reach the page |
| `scripts/build_site.py:980` | `derive_collection_range` — the four audited leaves: the two stored timestamps rendered through `iso()`, and the two Lagos days |
| `scripts/build_site.py:1006` | `human_range` — two ISO days as the page's wording ("7 to 15 November 2026"); the shape changes with the span (two months, two years) |
| `scripts/build_site.py:1039` | the new `Spec("collection_range", …)`, appended only while `freeze.json` is present |
| `scripts/build_site.py:2040` | `Page.build()`: the frozen stamp is now `Collected {range}. Collection stopped on {frozen_on}.` |
| `scripts/build_site.py:2366` | `main()`: `read_facts` / `page.build()` wrapped so a missing range stops the build with a message instead of writing a page |

Build output (gitignored, rebuilt): `site/index.html`, `site/about.html`, `site/data.json`.

Two decisions worth stating plainly:

- **The spec is collected only while the page describes a frozen vintage.** The range is a statement
  about a period that has closed. While the pipeline is live the stamp already says when the newest
  price was recorded and how old it is, and the audit's "collected but never printed" rule would
  otherwise fail the live build. So the live page keeps its old wording, untouched.
- **Four leaves, not two.** The two stored timestamps are what the table holds and are compared on
  the re-read at zero tolerance; the two Lagos days are the same values read in the clock the rest of
  the page speaks in, and they are what the stamp prints. Keeping both means the page cannot print a
  day the stored timestamp does not support.

## 2. Verified

### 2.1 The build, before and after

```
.venv\Scripts\python.exe -X utf8 scripts\build_site.py
```

Before the change (baseline, `site/` rebuilt from the settled file):

```
3,787 numbers checked, 0 unexplained
```

After:

```
3,791 numbers checked, 0 unexplained
```

**The count rose by 4, and by exactly 4**: the four new audited leaves of `collection_range`
(`first_price_utc`, `last_price_utc`, `first_day_lagos`, `last_day_lagos`). Nothing else was added or
removed, so every other number on the page is audited exactly as before. `site/data.json` now carries
`{"numbers_checked":3791,"unexplained":0,…}`.

### 2.2 The rendered line, copied from `site/index.html` verbatim

```html
<p class="stamp">Collected 7 to 15 November 2026. Collection stopped on 16 November 2026.</p>
```

The days are the ones the database holds: `min(recorded_at) = 2026-11-07 09:03:55.099947+00` and
`max(recorded_at) = 2026-11-15 12:22:56.504507+00`, which are the same calendar days in Lagos time.
The `.stamp` element, its font size, its colour and its box are unchanged — only the words inside it
changed.

### 2.3 `about.html`, before and after

```
before: 51944D739207B299064790A2CA46B889665F5FFACB8995C4A43736A173560E78
after:  51944D739207B299064790A2CA46B889665F5FFACB8995C4A43736A173560E78   (identical)
```

(The methods page is byte-identical. See the open item in §3.1: the number it prints about the build
is now four behind the build itself.)

### 2.4 Falsification

**A — the query points at an empty table.** One line of the query changed to
`from price_history where recorded_at > now() + interval '100 years'`:

```
exit=5
the collection range is empty: price_history holds no price row, so the page cannot say when collection started.
nothing written: the page will not print a date it cannot derive.
```

`site/index.html` was unchanged afterwards (SHA-256 `9E8833DA…` before and after): nothing was
written. Without the query there is no date, and the build refuses rather than printing a guess.

**B — the range moves between the two reads.** The query was given a random start day, so the value
the page was rendered from and the value the audit re-read differ:

```
3791 numbers checked, 2 unexplained
  unexplained: collection_range.first_price_utc: printed '2026-11-07 09:03 UTC', re-read '2026-11-14 10:59 UTC'
  unexplained: collection_range.first_day_lagos: printed '2026-11-07', re-read '2026-11-14'
nothing written: a page whose numbers cannot be re-derived is not published.
```

exit code 1, and nothing written. This is the check that matters: the two new dates are inside the
audited tree and are named individually when they disagree with the database. The query was restored
byte-for-byte afterwards (source SHA-256 `0270B207FA74DFFBA1741957FCE089F16EAC3D0967D0D0A98437475991F03828`
before and after), and the final clean build printed `3,791 numbers checked, 0 unexplained`.

### 2.5 The picture

`.agent/T1120-e-shots/hero-1440.png` — viewport at 1440 px, navigated with a cache-busting query
string (`http://localhost:8080/index.html?v=20261120-t1120e-1`). The browser's own text search found
"Collected 7 to 15 November 2026" in the live DOM, so the shot is of the new page and not of a cached
one. The line wraps onto two lines inside the unchanged `.stamp` box.

## 3. Left alone

1. **The methods page's count is now four behind the build.** `about.html` says "Last line of the
   build: 3,787 numbers checked, 0 unexplained" and the build now prints 3,791. The brief required
   `about.html` to be byte-identical, so the literal `ABOUT["audit_numbers"] = 3787`
   (`scripts/build_site.py:1616`) was left alone. The honest fix is one line — set it to 3791 — but
   that changes `about.html` and is the owner's call, not mine. Until then the methods page
   understates the build by four.
2. **The live page prints no range.** A deliberate consequence of the decision in §1: the spec is
   collected only while `freeze.json` is present, so deleting that file returns the stamp to its old
   wording rather than adding a range with no end.
3. **The audit compares facts, not the sentence.** It proves that the values the page was rendered
   from can be re-derived from the database; it cannot prove that the printed words are those values.
   That guarantee comes from the code path — one function, `human_range`, reading one query — and not
   from the audit. Stated here so nobody reads more into §2.4 than it says.
4. **README.md** was not touched; another agent owns it.
5. **`scripts/build_dashboard.py` and the dashboard** were not touched; out of scope by the brief.

## 4. Unproven

- **The live-page branch was not exercised.** No build was run with `freeze.json` absent, because
  removing it is a change the brief did not ask for. The code path is small and its audit behaviour
  is reasoned, not measured.
- **The methods-page count.** Whether `about.html` should now say 3,791, and whether that one-line
  change is worth another `about.html` rebuild, is a decision for the owner.
- **A measurement hazard worth repeating.** Another agent was editing `scripts/build_site.py` while
  this ticket ran: my first baseline build died with a `SyntaxError` at line 1277, and one
  falsification run produced output from a different build (3,787 numbers, an 86,568-byte page —
  neither my baseline's 80,456 bytes nor mine's 80,489). Every number above was therefore taken from a
  run whose output was checked against the file's own "wrote site/index.html (… bytes)" line, and the
  falsification was re-run on a copy of the script with the patch verified in the file before the
  build. Anyone re-running this ticket in a shared working tree should expect the same hazard.
- **The UTC and Lagos calendar days coincide for this dataset** (7 and 15 November either way). The
  code reads the days in Lagos time; a collection that ran past 23:00 UTC would show the Lagos day,
  which is the clock the rest of the page uses.

## 5. Files

- `scripts/build_site.py` — the change.
- `site/index.html`, `site/about.html`, `site/data.json` — rebuilt output (gitignored).
- `.agent/T1120-e-report.md`, `.agent/T1120-e-progress.md`, `.agent/T1120-e-shots/hero-1440.png` —
  this ticket's papers.
- `.agent/T1120-e-baseline.txt`, `.agent/T1120-e-build.txt`, `.agent/T1120-e-falsify-a.txt`,
  `.agent/T1120-e-falsify-b.txt`, `.agent/T1120-e-final.txt` — the raw build logs quoted above.

No commit, no push.
