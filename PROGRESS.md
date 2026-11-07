# Progress

Single state file for NaijaDrugWatch. Last updated **2026-11-07**.

## Where we are

**M2 — schema executed and catalogue seeded against a real Neon database.** The 8 tables, 5 views
and 1 materialised view all exist on project `orange-pond-32200905` (PG 17.11, `aws-eu-central-1`),
`products` and `drug_match_rules` hold 1,074 rows each, and a rolled-back smoke test proves the view
logic returns the right rows. No scrapers, no CI, no regulatory data, no listings, no embeddings.

## Done and verified

| Item | Evidence |
|---|---|
| Schema written — 8 tables, 5 views, 1 materialised view | `schema/001_extensions.sql` … `004_materialized.sql` |
| Seed loader | `python scripts/load_seed.py --dry-run` → exit 0, `products=1074 match_rules=1074 skipped=0 statements=6`, 2,160 SQL lines |
| Repo public, pushed | `github.com/batestguy/NaijaDrugWatch`, `main` |
| No secrets committed | `.env` absent from tree; only `.env.example` |
| Source rights probed | `research/2026-11-06-feasibility-probes.md` |
| **Neon project created** | `neonctl projects create` → `orange-pond-32200905`, PG 17.11, `aws-eu-central-1`, verified `select version()` |
| **`001` executed** | `CREATE EXTENSION` ×3 (pg_trgm, vector, unaccent), exit 0 |
| **`002` executed** | 8 `CREATE TABLE`, 9 indexes + comments, exit 0 |
| **`003` executed after fix** | 5 `CREATE VIEW`, exit 0 — see defect 1 |
| **`004` executed after fix** | `SELECT 0` + `CREATE INDEX`, exit 0 — see defect 2 |
| **`REFRESH … CONCURRENTLY` works** | `REFRESH MATERIALIZED VIEW` on `mv_drug_price_index`, exit 0 |
| **View logic proven** | rolled-back smoke test, 2 pharmacies / 2 products / 3 listings: cheapest = ₦450 across 2 pharmacies with `is_comparison = true`; single-pharmacy ₦300 with `is_comparison = false`; `pct_change_7d = -16.67`; all-failed source shows `STALE`; matview grouped 2 days correctly; `ROLLBACK` left 0 rows |
| **Seed loaded** | `.venv\Scripts\python.exe scripts/load_seed.py` → `loaded products=1074 match_rules=1074 skipped=0 statements=6`, exit 0; DB confirms `products=1074 match_rules=1074 distinct_names=597 with_nrn=0 with_embedding=0` |
| **Seed loader is idempotent** | second consecutive run → same counts, DB still `products=1074 rules=1074` |
| **Pinned environment** | `.venv\Scripts\python.exe`, CPython 3.12.13 via `uv venv --python 3.12`; `psycopg 3.2.13`. System Python 3.14 has no `psycopg[binary]` wheel — the first load attempt failed with `ModuleNotFoundError` |
| **Execution plan written** | `docs/PHASES.md` — P0–P9 with a gate command per phase and the delegation map |

## Defects found by executing the SQL (both fixed 2026-11-07)

1. **`v_cheapest_per_product_state` did not compile.** `count(distinct b.pharmacy_id) over (…)`
   → `ERROR: DISTINCT is not implemented for window functions`. The per-cell pharmacy count now
   comes from a grouped `pharmacy_counts` CTE joined on `(product_id, state)`; the partition is
   identical, so `pharmacy_count` and `is_comparison` semantics are unchanged.
   **This is the view the whole "cheapest" claim rests on**, and it had never run.
2. **`mv_drug_price_index` named a column that does not exist.** It selected `l.state` from
   `pharmacy_listings`, which carries no state; `ERROR: column l.state does not exist`. State lives
   on `pharmacies`, so the definition now joins `pharmacies` and takes `ph.state`. Aliases were
   renamed (`h`/`l`/`ph`/`p`) because the old `ph` meant `price_history` in one line and would have
   meant `pharmacies` in the next.

Both defects were syntactically invisible: the files were well-formed SQL that had simply never
been sent to a server.

## Not done — in order (phase ids match `docs/PHASES.md`)

1. **P2 — Greenbook index scraper** (`scrapers/nafdac_index.py`) — 6 category pages → ~10,895 NRNs.
   Gate: a `scrape_runs` row with `status='success'` and `record_count >= 10500`.
2. **P3 — Greenbook detail scraper** — ~11,754 pages, sharded, retry the ~10% that 500.
3. **P4 — pharmacy scrapers** (independent of P2/P3, so it can run in parallel): HealthPlus
   (Shopify API, 1,197 SKUs), Drugstore.ng (13,202 URLs, one national price), MedPlus.
4. **P5 — two-stage matcher**, blocked on the embedding-model decision (`vector(384)` is a placeholder).
5. **P6 — views proven on real rows**; **P7 — `flows/daily.py`**; **P8 — dashboard + API**.

## Decisions, dated

| Date | Decision |
|---|---|
| 2026-11-07 | Neon project `orange-pond-32200905`, PG **17**, `aws-eu-central-1`. Free plan. The account's region list offers no af-south option; Frankfurt is the closest available to Lagos. |
| 2026-11-07 | Direct (non-pooled) connection string for DDL and seed loads; the `-pooler` host is reserved for Streamlit and the Data API, because PgBouncer transaction pooling does not run DDL reliably. |
| 2026-11-07 | **Seed loaded** via the pinned `.venv` (CPython 3.12.13). System Python 3.14 is rejected for this repo: no `psycopg[binary]` wheel exists, and the first attempt failed on it. |
| 2026-11-07 | Phase ids P0–P9 with per-phase gate commands live in `docs/PHASES.md`; `PROGRESS.md` remains the only state file. |
| 2026-11-06 | **Reporting policy B**: `v_cheapest_per_product_state` only claims "cheapest" when `pharmacy_count >= 2`. A single-pharmacy cell is a national price, not a comparison. |
| 2026-11-06 | Add `pack_size`, `pack_unit`, `unit_price` to `pharmacy_listings` — additive, not a rename. |
| 2026-11-06 | Seed CSV loads `products` + `drug_match_rules` only. It has no NRN/status/expiry, and its `price` is not NGN. |
| 2026-11-06 | `vector(384)` is a placeholder pending the embedding model. |
| 2026-11-06 | Pharmacy set: HealthPlus, Drugstore.ng, MedPlus; nettpharmacy.com (Shopify, NGN confirmed) available as a fourth. |

## Known risks

- **The Greenbook's TLS certificate is expired** (probed 2026-11-07): `https://greenbook.nafdac.gov.ng`
  fails with `SEC_E_CERT_EXPIRED` / `SEC_E_CERT_EXPIRED (0x80090328)` while `http://` answers `200`
  and robots.txt still allows everything. `scrapers/common.py` therefore falls back per host and
  records the downgrade rather than disabling verification globally. Consequence: NAFDAC data
  currently crosses the wire unencrypted, so archive integrity rests on our own sha256 sidecars,
  not on transport. Re-probe before publishing; if it is still expired, say so in the limitations.
- **`v_pipeline_health` cannot see a source that never ran.** It groups `scrape_runs`, so zero rows
  for a source means zero output rows, not `STALE`. The smoke test only produced `STALE` because a
  *failed* run existed. At launch, with no runs at all, the health view is empty while three sources
  are silently dark. The view is a fixed contract name, so fixing this means either listing known
  sources inside the view or seeding one placeholder run per source — needs a decision.
- **`v_suspicious_listings` needs matches.** 77% of sampled registrations are non-Active, but a row
  only appears if a *listing* matches a product that has a registration number. The matcher is the
  gate, not the data.
- **State variation is thin.** Drugstore exposes one national price; only HealthPlus and MedPlus
  carry per-pharmacy pricing, and both are Lagos.
- **~10% of Greenbook detail pages returned HTTP 500** during sampling. The scraper needs backoff
  and a resumable ID cursor.
- **No NAFDAC mirror exists.** If the Greenbook blocks, history stops growing. Archive a dated
  full dump each run.
- **Low-risk, watched:** `v_pipeline_health` uses `round(extract(epoch …) / 3600.0, 1)`, which needs
  `extract` to return `numeric` (PG14+). It compiles on 17.11; it would break on PG13 or older.

## Reproducing the verified state

```bash
python scripts/load_seed.py --dry-run                                  # must exit 0
uv venv --python 3.12 .venv                                            # then install -r requirements.txt
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema/001_extensions.sql    # then 002, 003, 004 in order
.venv\Scripts\python.exe scripts/load_seed.py                          # products=1074 match_rules=1074
psql "$DATABASE_URL" -c "refresh materialized view concurrently mv_drug_price_index;"
git log --oneline -1                                                   # must match origin/main
```

Every schema file is idempotent, so a full rebuild is re-running `001`→`004` in order.
