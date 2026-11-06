# Schema reference

Eight tables, defined in [`../schema/002_tables.sql`](../schema/002_tables.sql). Names are fixed
by contract — the dashboard and API are built on them.

## Run order

| File | Depends on | Why it must be separate |
|---|---|---|
| `001_extensions.sql` | nothing | the `vector` type must exist before a table uses it |
| `002_tables.sql` | 001 | — |
| `003_views.sql` | 002 | views reference table columns |
| `004_materialized.sql` | 002, 003 | the index must exist for `REFRESH ... CONCURRENTLY` |

All files are idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE`), so a rebuild is re-running
them in order. No migration framework, no dbt.

## Tables

| Table | Primary key | Growth | Notes |
|---|---|---|---|
| `pharmacies` | `id` | static | `state` is **not null**: the index is state-partitioned |
| `nafdac_registrations` | `registration_number` | ~10,895 | `pack_description` is free text and blank ~70% of the time |
| `nafdac_status_snapshots` | `id` | +10,895/day | unique on (registration_number, snapshot_date); append-only |
| `products` | `id` | ~600 seed | `embedding vector(384)`, `brand_aliases text[]` |
| `drug_match_rules` | `id` | ~600 seed | stage two of the matcher |
| `pharmacy_listings` | `id` | 3,600–16,000/day | carries `pack_size`, `pack_unit`, `unit_price` |
| `price_history` | `id` | same as listings | append-only; ~0.1 GB/year at MVP volume |
| `scrape_runs` | `id` | ~10/day | written even when a run fails |

## Decisions encoded here

**`embedding vector(384)`.** pgvector requires a fixed dimension for an HNSW index. 384 matches
common sentence-transformer models. If you change embedding model, `ALTER COLUMN` and rebuild
the index — the value is a placeholder until the matcher is built.

**`pack_size` / `pack_unit` / `unit_price` on `pharmacy_listings`.** An addition to the original
spec. Without them, "cheapest" compares a 12-tablet pack to a 500-tablet jar. `unit_price` is
`price_ngn / pack_size` with a `CHECK (unit_price > 0)`.

**Two uniqueness mechanisms on `pharmacy_listings`.** The contract constraint is
`(pharmacy_id, url, scraped_at)`. That key cannot deduplicate across runs, because `scraped_at`
moves on every scrape — `source_hash` is the handle that actually does. Both are kept: the
constraint for the contract, the hash index for the dedupe lookup.

**Expression unique indexes on `products` and `drug_match_rules`.** `(canonical_name,
coalesce(strength,''), coalesce(form,''))` rather than a plain unique constraint, so rows with a
missing strength or form still collapse to one instead of multiplying. `ON CONFLICT DO NOTHING`
in the loader relies on these.

**`nafdac_status_snapshots` stores both status and expiry.** The source data contradicts itself:
at least one registration is published as `Expired` with a 2030 expiry date. Deriving one field
from the other silently loses rows.

## Seed CSV mapping

`seed/medprices.csv` loads **only** `products` and `drug_match_rules`. It has no NRN, no status
and no expiry, so it cannot populate `nafdac_registrations`. Its `price` column is a unit
reference price (0.0007–1,877 across mixed units), not NGN — it must never reach
`price_history`. See [`seed-data.md`](seed-data.md).
