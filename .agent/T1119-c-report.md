# T1119-c — report

The dashboard is rebuilt: six dataset figures, three inline SVG charts, and all 2,800 rows in a
ten-row window with a pinned header, four sortable columns, search, a live count line, a browser-built
CSV export and a print path. Build exits 0 at 808,632 bytes.

## Changed

- `scripts/build_dashboard.py` — rewritten end to end, 713 insertions / 124 deletions, 369 → ~940 lines.
  Nothing else in the repository is modified (`git diff --stat` prints this file alone).
  - `:36` `SQL` — unchanged shape; still the one query behind every row.
  - `:84` `LICENCE_STATES` — the four states, three in her colours and "never read" as a pattern.
  - `:126` `COUNT_SQL` / `:134` `RUNS_SQL` — the counts that cannot be read off the price rows, plus
    `scrape_runs` by night.
  - `:143` `CONTRAST_PAIRS` (23 pairs) and `:167` `DECORATIVE_PAIRS` (4, now carrying a floor).
  - `:196` `licence_state()` — four labels from the register's own words, reconciled in `main` against
    `v_suspicious_listings` (inactive + expired must equal the view's 154).
  - `:243` `figures()` — the six numbers, every one derived, none typed.
  - `:275` `chart_funnel`, `:299` `chart_licence`, `:330` `chart_runs` — inline SVG, `role="img"`,
    `aria-label` carrying the headline fact, every series labelled with its number in text.
  - `:380` `CSS` — cream paper, her three colours as categories, fixed 36 px rows, sticky header,
    `@media print` that removes the height cap with `!important` so the inline height cannot win.
  - `:470` `JS` — filter, sort, ten-row fit measured at runtime, count line, CSV, keyboard Home/End.
  - `:640` `audit_palette()` — reads the same colour constants back out of `build_site.py` and fails if
    the two have drifted.
  - `:672` `measure_contrast()` — prints every pair, fails under 4.5:1, holds boundaries to 3:1.
  - `:790` `page()` and `:855` `main()` — the page, the two-read audit, the weight print.

## Verified

**Build** (`.\.venv\Scripts\python.exe -X utf8 scripts\build_dashboard.py`), exit 0:

```
worst text pair: tag: inactive, on its own tint at 5.14:1
wrote site\dashboard.html (808,632 bytes, 2,800 rows, 0.77 MB)
2,865 rows and figures checked, 0 unexplained
```

Page weight **808,632 bytes = 0.77 MB**, under the 1.1 MB gate. Largest part is the row JSON, as before.

Every text-on-background pair, measured at build and printed (23 pairs, all ≥4.5:1; the worst is
`#7A5800` on `#EBE4D4` at **5.14:1**). Four non-text pairs also printed: a row tint 1.05:1 (a tint, no
floor), the table hairline 1.45:1 (no floor), a tag border 11.82:1 and the chart's empty track
**4.34:1**, both held to a 3:1 boundary floor.

**Geometry, measured in Chromium via Playwright against `http://127.0.0.1:8899/dashboard.html`**, at
1440×900 and again at 375×760, identical both times:

```
boxTop 2110.3, boxBottom 2508.3 (1440) / 2913.8..3311.8 (375)
rowHeight 36
fullyVisibleRows 10
tenthRow   [2472.3, 2508.3]  tenthInsideBox  true
eleventhRow[2508.3, 2544.3]  eleventhOutsideBox true
thTopBefore 2110.3, thTopAfter500 2110.3, scrolledTo 500, headerPinned true
rowsMovedUnderHeader true
docScrollWidth 1440 == docClientWidth 1440  (375 == 375)
```

Ten rows exactly, the tenth ending on the box edge and the eleventh starting at it, at both widths. The
column header keeps its position while `scrollTop` moves 500 px and the rows move underneath it.

**Count line** (read from the DOM after dispatching `input`):

| state | count line |
|---|---|
| at load | `10 of 2,800 — scroll, or narrow it` |
| typed "amoxicillin" | `10 of 11 — scroll, or narrow it` |
| typed "MedPlus" | `10 of 1,399 — scroll, or narrow it` |
| typed "zzzz" | `0 of 0` |
| cleared | `10 of 2,800 — scroll, or narrow it` |

**Console:** `Total messages: 0 (Errors: 0, Warnings: 0)`.

**Figures as built:** 2,800 prices over 9 nights · 288 medicines · 44 comparisons · 154 on a lapsed
licence of 452 that carry a readable status · 16.9% of 10,967 registrations · frozen 16 Nov 2026.
The licence bar: active 298, inactive 85, expired 69, never read 107 (298 + 85 + 69 + 107 = 559 =
the matched prices; 85 + 69 = 154 = `v_suspicious_listings`).

## Deviations

1. **Comparisons are 44, not 42, and there is no defensible 17.** The brief asked for `42` with
   `17 like for like`. The database says 44 comparison cells, all in Lagos. I tried four definitions
   that might produce the brief's numbers — `is_comparison` alone (44), both sides stock-confirmed (40 of
   44), every listed pack size agreeing (21 of 44), same pack size *and* a different rival price (23 of
   44) — and none gives 42 or 17. The page prints 44 and "same medicine, two shops" rather than a number
   I could not derive. `PROGRESS.md` also records 44 at the freeze.
2. **Three nights had failures, not one.** 83 runs over nine nights, 76 succeeded. Failures on 7, 8 and
   12 November (12 November: MedPlus HTTP 429, then a 20-record sweep refused by the 100-record floor).
   The chart shows every night's total against its successes and the caption names the three dates. The
   brief's "the one failed night" is not what the table says.
3. **The shop and licence dropdowns were kept.** The brief assigns "the dropdown query block" to the
   second ticket; the page already had shop and licence selects, and removing working filters to make
   room for a later ticket would have been a regression. Their licence options were widened to the four
   states.
4. **The table caption became a paragraph above the box.** A `<caption>` sits inside the scroll
   container and consumed 39.5 px of the ten-row window, which made the tenth row clip. The region
   keeps `aria-labelledby` pointing at that paragraph, and the table keeps its header row.
5. **Green is gone.** The old page used a green "active" tag and a red "not active" tag — a
   good-and-bad pair. Both are replaced by her navy, gold and red as categories with a legend, and the
   four-state vocabulary is spelled out in words as well as colour.
6. **`min-width:30rem` on the table**, so at 375 px the table scrolls inside its own box rather than
   squeezing six columns to illegibility. The *page* still does not scroll sideways (measured).

## Unproven

- **The CSV export and the print path were never exercised.** The code is there and the print rules are
  written (`height:auto!important`), but no test clicked Download or opened a print preview. A ten-row
  printout is a lie, and this one has not been looked at.
- **axe has not been run.** Structural accessibility was done by hand — roles, `aria-sort`, live region,
  focus ring, `aria-label` on each chart — and the colour pairs are measured, but that is not a scan.
- **Only Chromium was measured.** No Firefox, no Safari, no screen reader. `position:sticky` inside a
  scroll container and the `table-layout:fixed` ellipsis are both the kind of thing that differ.
- **"amoxicillin" finding 11 rows** was read as plausible, not checked against the data by hand.
- The database refused a connection once mid-session (`getaddrinfo failed`, DNS) and worked on retry;
  whether that was the resolver or the network was not established.
