# T6 report — implausible prices are refused at the door

**Written by the secretary.** The agent hit its step cap after applying all five code changes and
passing gates 1, 3, 4, 5 and 6, but before the behavioural test for Part B, before `docs/views.md`, and
before this file. The secretary wrote the missing test, ran it, and completed the documentation.

## Answer

Yes, on both halves — and the behavioural half is now proven rather than assumed.

## Part A — one shared bound, enforced in all three scrapers

`scrapers/common.py`: `MIN_PRICE_NGN = 20`, `ABSURD_PRICE_NGN = 500000`, and `price_bounds_error()`
returning `non-positive` / `below-min` / `above-max`. Strict comparisons, so exactly ₦20.00 and exactly
₦500,000.00 are accepted.

`healthplus.build_record:307`, `medplus.parse_product` and `drugstore.parse_product` all call it and
print `AUDIT_REJECT <reason> url=… price=…` on refusal. `ABSURD_PRICE_NGN` is still importable from
`healthplus` because `medplus` and `drugstore` import it from there.

**Boundary table re-run by the secretary against the real functions, 24/24 as expected:**

| price | result |
|---|---|
| `1.00`, `10.98`, `19.99`, `19.999` | reject — `below-min` |
| `20.00`, `20.001` | **accept** |
| `500000.00` | **accept** |
| `500000.01`, `500000.001` | reject — `above-max` |
| `0`, `-5` | reject — `non-positive` |

`AUDIT_REJECT` printed exactly on the rejections and on none of the accepts, in all three scrapers.

## Part B — `v_price_change_7d` respects the flag

`and not l.price_suspect` in `latest`, `and not o.price_suspect` in `prior`. It reads the base table, so
it had to apply the flag itself.

**Proof the agent could not produce** — its falsification query failed with `column "url" does not
exist`, so only compilation had been shown. Rolled-back test with a throwaway pharmacy:

| Case | Expected | Got |
|---|---|---|
| Control: real → real, 8 days apart | 1 row | **1** |
| Newest row suspect (₦1.00 vs real) | 0 rows | **0** |
| Prior row suspect (real vs ₦1.00) | 0 rows | **0** |
| Real → real, second URL | 1 row | **1** |

Rollback verified clean: 0 throwaway pharmacy rows, `v_price_change_7d` back to 0 rows.

## Operational warning, added to `schema/003_views.sql`

Re-running `003` **on its own** reverts `v_latest_listings` to its pre-flag definition, and the 14 hidden
rows come back (2,599 → 2,613). A full rebuild is safe because `005` sorts after `003`. The agent
noticed this and applied only the `v_price_change_7d` block; a warning comment now sits at the top of
the block in `003` so the next person does not have to notice it.

## Deviations

- `drugstore.py` dropped its now-unused `ABSURD_PRICE_NGN` import rather than re-exporting it. The name
  is still importable from `healthplus`. Reasonable, and recorded rather than silently accepted.
- The agent did not edit `docs/views.md`; the secretary did. Two of the three limits documented for T5
  are now closed and the doc says so.

## Unproven

- **`mv_drug_price_index` is still unprotected.** It reads `price_history`; it is clean only because no
  matched product has a `price_history` row under ₦20. Changing it needs drop + create + index rebuild
  + refresh, which is its own ticket.
- No scraper was run end to end, by design. The guard is proven at the function boundary, not against a
  live page that returns a ₦1.00 price.
