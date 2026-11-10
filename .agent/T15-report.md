# T15 report — *written by the secretary, not the agent*

The `builder` reached its step limit with the fix written and a live run done, but before writing this
file or its last progress lines. Everything below was re-run by me on 2026-11-10 between 05:55Z and
06:40Z.

## 1. Changed

| Path | Change |
|---|---|
| `scrapers/medplus.py:22-33` | Docstring corrected: the visible quantity input is gone since the 2026-11-09 rebuild and its replacement carries a constant `max="50"`. |
| `scrapers/medplus.py:83-88` | `INPUT_TAG_RE` added; the old `input-number` selector is kept, demoted to a fallback that is consulted only when the cart form carries no count. |
| `scrapers/medplus.py:102-124` | New `cart_form_region()` and `cart_stock_quantity()`: scope to the add-to-cart form, then read `max` from its own `<input name="quantity">`. |
| `scrapers/medplus.py:146-162` | `parse_product` reads stock through the new helper; `null` still means "we could not read it". |

No other file touched. `git diff --stat`: `scrapers/medplus.py | 81 +++++---  (58 insertions, 23 deletions)`.

## 2. Verified — by me, not by the agent

**The signal, checked directly against pages whose answer we already knew** (four pages fetched live,
hidden cart input extracted):

| URL | what we recorded on 2026-11-08 | hidden `name="quantity"` max | visible `max` |
|---|---|---|---|
| acneaway-cream-20g | unavailable | **0** | 50 |
| acyvir-aciclovir-eye-ointment | unavailable | **0** | 50 |
| abf-3-cream-20g | available | **145** | 50 |
| abidec-multivitamin-drops-25ml | available | **194** | 50 |

The visible input reads 50 on all four, available and unavailable alike — so the agent's claim that it
is a per-order cap is correct, and `max="50"` would have been a false "in stock" for everything.

**The write path, exercised live.** Category 12 holds only 20 products, so the agent's `--limit 12`
run could never reach an unavailable one. I ran category 31 (`--limit 40`, 25 records) and the
database now holds, for 2026-11-10:

```
in_stock:  False 4   True 39   NULL 0
```

The four marked unavailable today:

```
P-ALAXIN SUSPENSION 80ML           2800.00   false
LEVER ARTESUNATE 60MG INJ          1300.00   false
AMATEM 20/120MG * 24 SOFTGEL       1200.00   false
CLARTEM 20/120 *6TABS. (ACT)        700.00   false
```

So the false path is proven through the database, not only on saved pages. `scrape_runs` ids 38
(12 records), 39 (20), 40 (20), 41 (25), all `success`.

**The price table after today's rows:** 260 cells, 45 two-pharmacy comparisons, 18 unconfirmed
winners. Cells fell from 264 because four products genuinely became unavailable today and known-
unavailable rows are still excluded — which is the correct behaviour, not a regression.

## 3. Deviations

1. **The agent's "second independent signal" is not what it claims.** It said unavailable pages
   render "Notify me" and available ones "Add to cart". Both strings (`openProductNotifyModal`,
   `addToCart(`) are present in the raw HTML of all four pages I fetched. They are probably
   conditional at render time, but that is not established. The hidden cart count is the only signal
   verified to discriminate. Nothing in the shipped code depends on the button.
2. **Category 12 is 20 products**, not the ~1,400 the brief assumed; the agent's limit of 12 sampled
   more than half of it. My category 31 run was needed to reach an unavailable item.
3. `stock_evidence` and `stock_quantity` are written to the JSONL archive only — `pharmacy_listings`
   has no columns for them. Unchanged by this ticket, worth knowing for audit.

## 4. Unproven

- **The full catalogue has not been re-scraped.** 43 MedPlus rows were written today against 1,405 in
  the table; the rest still carry their 2026-11-09 `null` until the next full run.
- **The magnitude is not interpreted.** `max` is read as zero vs non-zero only. Whether 145 means
  "145 units" or "145 available to this channel" is not established.
- **One control page had no cart form at all** and reads as "no record". Whether that is a delisted
  product or a page shape we do not handle is unknown.
