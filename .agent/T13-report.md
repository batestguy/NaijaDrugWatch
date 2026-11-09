# T13 report — *written by the secretary, not the agent*

The `builder` reached its 35-call cap with the tool built, two defects found and fixed, and the dry run
**not** re-run after those fixes. It wrote neither `.agent/T13-report.md` nor the final progress lines.
Everything below was re-run by me on 2026-11-09 between 07:40Z and 08:20Z, after the user authorised
the write and the skip.

## 1. Changed

| File | Change |
|---|---|
| `scripts/expand_catalogue.py` | **New**, 38 KB. Dry-run by default; `--apply` additionally requires `--i-know-this-writes`. |
| `scripts/expand_catalogue.py:373-386` | **My edit**: a proposal whose name and strength match an existing product in the same form family is now *skipped* rather than reported-and-created. The user chose skip; the register says `Tablet` where the seed says `tab-cap`, so the raw-string unique index does not catch it. |
| `PROGRESS.md` | New handoff at the top; the 2026-11-09 expansion section. |
| Database | 359 products, 359 match rules, 355 listing links. `scrape_runs` 29 and 30. |

## 2. Verified — commands and real output

**The guard, before anything was written:**

```
$ python scripts/expand_catalogue.py --apply
refused: --apply needs --i-know-this-writes. Inserting products is a catalogue change
the user authorises, not a default. Run without flags to see the dry-run report.
EXIT=2
```

**Dry run after the two fixes and my skip (exit 0):** 4,128 pairs considered, rejection table summed to
4,128, 597 accepted pairs, 360 distinct triples, **359 new** — `SKIPPED 1 … Meloxicam 7.5 mg Tablet`.
Full text: `.agent/T13-dryrun.txt`.

**Apply:**

```
scrape_runs id=29 status=running source=expand_catalogue
products inserted          359 (catalogue 1,074 -> 1,433)
rules inserted             359
scrape_runs id=29 status=success record_count=359
```

**Matcher, real run:** `matched 355 (10.4%)` of 3,428 unmatched; `scrape_runs id=30 status=success
record_count=355`. Sample assignments are plausible (`Adalat LA 30 mg X 30 → Adalat LA`,
`Diabond Metformin 500mg x84 → METFORMIN TABLETS 500MG`, `Zestril 5mg x 28 → Zestril 5 mg Tablet`).

**Before → after, measured on the live database:**

| Object | Before | After |
|---|---|---|
| `products` / `drug_match_rules` | 1,074 / 1,074 | **1,433 / 1,433** |
| `v_latest_listings` matched | 342 | **580** |
| Distinct products a shop cites | 158 | **338** |
| `v_cheapest_per_product_state` rows | 118 | **260** |
| …`is_comparison` | **24** | **44** |
| `v_suspicious_listings` | 127 | 132 |
| `mv_drug_price_index` | 139 | 340 |

**Integrity checks after the write:** duplicate (name, strength, form) triples = **0**; new products
without a registration number = **0**; all 44 comparisons are Lagos; `mv` refreshed concurrently, exit 0.

## 3. Deviations

1. **A near-duplicate is now skipped, not warned about.** The tool's design was "report, never merge
   silently"; the user decided to skip. One row affected.
2. **The brief said `drug_match_rules` had only a primary key.** Wrong — both `products` and
   `drug_match_rules` carry a unique index on `(name, coalesce(strength,''), coalesce(form,''))`. The
   builder caught this; code-level dedupe remains as a belt.
3. **The builder's first-run numbers (204 products, 277 listings) were stale.** Post-fix: 359 products,
   355 listing rows. The 204 was measured before the two parsing fixes.

## 4. Unproven

- **Shelf reality.** Each new product is backed by a registration row and a real shop title, but no
  human has confirmed a pharmacy stocks that exact pack.
- **The 44 comparisons.** Computed, never checked against two live shop pages.
- **`expand_catalogue.py` under a different register vintage.** It has run against one database state.

## 5. Found while running it, not fixed

The rejection list is dominated by pairs that are obviously the same drug — `AMATEM 20/120MG`,
`MAXITROL EYE DROP 5ML`, `PANADOL EXTRA *20 CAPLETS`, `ZENTEL SUSPENSION 20ML` — refused as "strength
disagrees" because a slash strength parses as one token where the register writes two. 610 pairs.
This is the same defect already recorded for `parse_pack` on Drugstore.ng, now measurably excluding
first-line antimalarials. Next ticket.
