# Progress

Single state file for NaijaDrugWatch. Last updated **2026-11-06**.

## Where we are

**M1 — scaffold: complete and pushed.** No database, no scrapers, no CI. Nothing has executed
against a real Neon instance, so treat every SQL file as unproven until it runs.

## Done and verified

| Item | Evidence |
|---|---|
| Schema written — 8 tables, 5 views, 1 materialised view | `schema/001_extensions.sql` … `004_materialized.sql` |
| Seed loader | `python scripts/load_seed.py --dry-run` → exit 0, `products=1074 match_rules=1074 skipped=0 statements=6`, 2,160 SQL lines |
| Repo public, pushed | `github.com/batestguy/NaijaDrugWatch`, `main`, commit `e25e208` |
| No secrets committed | `.env` absent from tree; only `.env.example` |
| Source rights probed | `research/2026-11-06-feasibility-probes.md` |

## Not done — in order

1. **Create the Neon project** (free). Put the connection string in `.env` as `DATABASE_URL`.
   This is the only blocker on the critical path and it needs a human account.
2. **Execute `schema/001-004` in order.** This is the first real test of the views; expect at
   least one column-name fix. Record the exact `psql` output in this file when it passes.
3. **Greenbook index scraper** (`scrapers/nafdac_index.py`) — 6 category pages → 10,895 NRNs.
4. **Greenbook detail scraper** — 11,754 pages, shard across runs, retry the ~10% that 500.
5. **Drugstore.ng scraper** — national spine, 13,202 products.
6. **HealthPlus + MedPlus scrapers** — the only sources offering state-level price variation.
7. Views verified against real rows, then `flows/daily.py`, then dashboard.

## Decisions, dated

| Date | Decision |
|---|---|
| 2026-11-06 | **Reporting policy B**: `v_cheapest_per_product_state` only claims "cheapest" when `pharmacy_count >= 2`. A single-pharmacy cell is a national price, not a comparison. |
| 2026-11-06 | Add `pack_size`, `pack_unit`, `unit_price` to `pharmacy_listings` — additive, not a rename. |
| 2026-11-06 | Seed CSV loads `products` + `drug_match_rules` only. It has no NRN/status/expiry, and its `price` is not NGN. |
| 2026-11-06 | `vector(384)` is a placeholder pending the embedding model. |
| 2026-11-06 | Pharmacy set: HealthPlus, Drugstore.ng, MedPlus; nettpharmacy.com (Shopify, NGN confirmed) available as a fourth. |

## Known risks

- **The SQL is unexecuted.** Highest-probability defect in the repo.
- **`v_suspicious_listings` needs matches.** 77% of sampled registrations are non-Active, but a
  row only appears if a *listing* matches a product that has a registration number. The matcher
  is the gate, not the data.
- **State variation is thin.** Drugstore exposes one national price; only HealthPlus and MedPlus
  carry per-pharmacy pricing, and both are Lagos.
- **~10% of Greenbook detail pages returned HTTP 500** during sampling. The scraper needs
  backoff and a resumable ID cursor.
- **No NAFDAC mirror exists.** If the Greenbook blocks, history stops growing. Archive a dated
  full dump each run.

## Reproducing the verified state

```bash
python scripts/load_seed.py --dry-run        # must exit 0
git log --oneline -1                         # must match origin/main
```
