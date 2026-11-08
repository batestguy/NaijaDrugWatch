# T4 report — dashboard shows both answers

**Written by the secretary**, from the agent's evidence plus independent checks. The agent hit its
step cap before writing this file; it had completed the code and four of five gates.

## Answer

The "Cheapest by state" tab now shows both answers, and the label that would have been false is gone.

| Column | Meaning |
|---|---|
| `Product`, `State` | as before |
| `Cheapest`, `Pack price` | pharmacy and sticker price of the cheapest pack |
| `Cheapest pack per unit` | that pack's cost per unit, or `unknown` |
| `Lowest known unit price` | lowest cost per unit among rows whose pack size parsed, or `unknown` |
| `Lowest unit price from`, `Pharmacies` | pharmacy and pharmacy count |

**"Best value" appears nowhere in the rendered page.** Verified by reading the DOM
(`document.body.innerText.includes('Best value')` → `false`), not by trusting the source.

## Verified

- `py_compile dashboard/app.py` → exit 0 (agent).
- Headless server answers `HTTP 200` (agent).
- **axe-core 4.10.2, WCAG 2.0/2.1/2.2 A+AA on the changed tab → 0 violations, 28 passes.** Re-run by
  the secretary after the change, because a new table plus new captions is exactly where the earlier
  contrast fix could regress.
- Rendered at 1400 px: eight columns, both answers visible, `unknown` shown where the pack size could
  not be read.
- Rendered at 430 px: **no page-level horizontal overflow** (`documentElement.scrollWidth` equals the
  viewport). The dataframe scrolls inside its own container — 398 px visible, 407 px content. The tab
  bar also scrolls ("Pipel >"), which is Streamlit's default behaviour and does not clip content.
- Caption arithmetic checked against the database, not taken from the agent:
  `select count(*), count(*) filter (where is_comparison), count(*) filter (where best_unit_unit_price is null)`
  → **115, 24, 37**. So 78 known, 22 of 24 comparisons and 56 of 91 single-pharmacy cells — exactly
  what the caption states.

## Deviations

- **Ciprofloxacin/Lagos no longer diverges.** After the MedPlus expansion its cheapest pack is
  ₦2,000/10 = ₦200.00/unit and both answers agree. The brief's worked example went stale between
  writing and execution. The live divergence is Aciclovir/Lagos: cheapest ₦14,040 with unit `unknown`,
  lowest known ₦266.96 from MedPlus. Ibuprofen/Lagos still shows the exact hazard the brief describes
  (₦1,130 bottle of unknown volume against ₦25.00/ml for a 60 ml bottle at ₦1,500).
- The agent's final progress line and this report file were not written by it.

## Unproven

- **The table was not visually inspected at 430 px.** The internal scroll and the absence of page
  overflow are measured facts; the legibility of eight columns in a 398 px container is not, and the
  attempt to scroll Streamlit's container into view did not take. Worth a human eye before release.
- Keyboard operation of the new table was not re-tested — axe cannot check it, and the earlier
  keyboard pass was never done.
