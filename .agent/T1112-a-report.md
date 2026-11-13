# T1112-a report - the verification workbench

**Written by the secretary on 2026-11-12.** The builder (`ses_e317c4f66ffeqfPs7X6R39gnjN`) reached its
30-step cap with the generator written and exercised but no report file and its test server still
running. This is its account plus my own checks. **Secretary** marks mine.

## What it is

`scripts/build_verify_desk.py` reads the database read-only and writes **one self-contained file**,
`site/verify/index.html` (177,290 bytes). Open it by double-click; no server, no network of its own.
The data is embedded as a JSON block, because a `file://` page cannot fetch a sibling file.

Two worklists, one item at a time:

| list | items | what one item is |
|---|---|---|
| licence | **89 products** (163 listings) | a medicine matched to a registration that is not Active or is past expiry, with the register page link and every shop selling it |
| pack | **45 products** (132 shop rows) | a medicine two or more shops price, with each shop's price, pack size and page link |

One item is one **product**, not one listing, so the same drug is never judged twice. The builder's
count of 132 pack rows against my 92 is a real difference and it is right: a shop that publishes
three pack sizes for one product has three rows.

## Verified - by the secretary

**The build.** Counts are read from the database at build time and checked against a second query;
585 self-checks run and must all pass, or nothing is written.

**Every external URL is inside the data block.** 384 `http` occurrences in the file, all 384 inside
the JSON block; **zero** `src=` or `href="http…"` attributes in the markup. So the page loads no
external CSS, script, font or image.

**It opens and works.** In a browser at 1280 px: title "Verification workbench - licence and pack
worklists", "of 89 overall" in the progress line, the explanatory banner renders. Pressing `1`
stored a verdict against `licence-2225` (`agrees`, timestamped) and advanced the position. Console:
**0 errors, 0 warnings**. The builder separately proved `j`/`k`/`1`/`2`/`3`/`n`/`o`/`Esc`, that a
note survives a reload, that both lists keep their own position, and that the export parses as JSON
with keys `generated_utc`, `data_as_of`, `licence`, `pack`.

**The register links resolve, and the claim behind them is real.** This is the check nobody had done
and the one the whole tool depends on. Two registrations from the flagged list, fetched by hand at the
project's 2 s spacing:

| registration | page | our stored status | live page |
|---|---|---|---|
| `04-6233` | HTTP 200, 14,775 bytes | Expired, approved 2018-04-04, expired 2023-04-03 | **Status Expired**, Approval 2018-04-04, Expiry 2023-04-03 |
| `B4-4408` | HTTP 200, 14,424 bytes | Inactive, approved 2020-11-30, expires 2025-11-29 | **Status Inactive**, Approval 2020-11-30, Expiry 2025-11-29 |

The registration number appears on both pages. So: **the links are real and point at the right
record, and for the first two items the status we store matches what NAFDAC publishes.** Two is not
89, and it is the difference between a plausible list and a checked one.

## Deviations

- Report not written by the builder (step cap); this is the secretary's.
- Progress file has two lines rather than one per unit.
- The builder could not exercise `o` against real sources because the brief forbade pharmacy and
  NAFDAC requests from the page. I did not press it either; instead I fetched two register pages
  myself, which is the same evidence without opening 89 tabs.
- The builder's attempts to print a final filter-count table and an accessibility audit failed on its
  own helper script. The clicks ran in the browser; only the printed table is missing.
- Five screenshots the builder left in the repo root and two test servers (ports 8811 and 8823) were
  removed by the secretary.

## Open risks

1. **A stale export.** `data_as_of` is the older of the price reading and the register reading, so an
   export can never look fresher than its stalest source. Keep that; it is the right choice.
2. **The `o` button opens several tabs.** A popup blocker may refuse the second and later ones. The
   page must keep the counts visible so a missing tab is noticed rather than assumed.
3. **A judgement recorded here is not in the database.** Folding verdicts back into the database is a
   separate, deliberate act: it needs a table and a decision about what a contradiction does to a
   published claim.
4. **No axe run.** Accessibility is structural: real buttons, labelled fields, live regions, 44 px
   targets, the key list printed on the page. It has not been machine-audited.

## Unproven

- **Whether a person can work at speed with it.** Only someone working through 89 items will know
  whether one card at a time is the right shape, and whether 89 is an afternoon or a week.
- **The other 87 licence items and all 45 pack items.** Two licence checks passed; the rest are
  untouched.
- **Whether the two lists overlap in a way that makes the work confusing** - a product can appear in
  both, and the same person may judge it twice from two angles.
