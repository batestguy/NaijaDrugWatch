# NaijaDrugWatch — project map

Updated 2026-11-06, after three recon rounds. Every number traces to
`research/2026-11-06-feasibility-probes.md`; anything without a probe behind it is marked
*unverified*.

## 1. What this is

One join nobody has built: **NAFDAC registration status × live Nigerian pharmacy price**.
The question it answers: *is this drug genuine, is it in stock, where is it cheapest?*

Not: a price-comparison app, a prescription service, a mobile app. v1 is a database, six
views, one dashboard, one read-only API — on free tiers only.

## 2. Source inventory (all probed)

| Layer | Source | Access | Volume | Currency |
|---|---|---|---|---|
| Regulatory index | Greenbook, 6 category pages | HTML, robots allow-all | **10,895 NRNs** / 11,754 product rows / IDs 2–12,519 | — |
| Regulatory status | `/products/details/{id}` | HTML | status + approval + expiry per ID | — |
| Market A | healthplusnigeria.com | Shopify `/products.json` | **1,197** SKUs | NGN |
| Market B | drugstore.ng | Nuxt SSR + `__NUXT__` payload, **state/LGA routes** | **13,202** product URLs, **908** state+LGA URLs, **all 37 states** | NGN |
| Market C | medplusnig.com | custom PHP, server-rendered | ~1,400–2,800 (unverified) | NGN |
| Market D | nettpharmacy.com | Shopify `/products.json` | unknown | **NGN (confirmed via `/cart.json`)** |
| Catalogue | #FixMedPrices CSV | openAFRICA, CC-BY | 1,074 rows / **597** drug names | unit price only |

**The Greenbook is healthy, not frozen.** Max Approval Date observed `2026-03-31`.
`Packsize` is blank on **70%** of detail pages — pack size must come from listing titles,
never from NAFDAC.

**77% of sampled registrations are not usable stock.** n=43 detail pages: `Active` 11,
`Expired` 22, `Inactive` 10; 33 of 43 had an expiry before 2026-11-06. Status and expiry can
contradict (id 4125: `Expired`, expiry 2030) — read both, never derive one from the other.

## 3. Pipeline

```
scrapers/nafdac_index.py    6 req      ─┐
scrapers/nafdac_detail.py   11,754 req ─┼─→ nafdac_registrations
                                       └─→ nafdac_status_snapshots (append daily)
scrapers/healthplus.py      5 req     ─┐
scrapers/drugstore.py       sitemap   ─┼─→ pharmacy_listings → price_history
scrapers/medplus.py         HTML      ─┘
seed/fixmedprices.py        CSV       ──→ products + drug_match_rules
                                            ↓
                                   matcher (pgvector → rules)
                                            ↓
                        views → mv_drug_price_index → dashboard / API
flows/daily.py   one Prefect deployment: index → detail delta → prices → match → refresh mv
```

## 4. Schema

| Table | Key | Growth | Constraint that matters |
|---|---|---|---|
| `pharmacies` | id | static | needs state — the whole index is state-partitioned |
| `nafdac_registrations` | registration_number | 10,895 | source URL per row |
| `nafdac_status_snapshots` | (registration_number, snapshot_date) | +10,895/day | **append only**; this is the value |
| `products` | id | ~600 | `embedding vector` |
| `drug_match_rules` | id | ~600 | canonical → pattern + strength + form |
| `pharmacy_listings` | (pharmacy, url, timestamp) | ~3,600–16,000/day | `source_hash` is the real dedupe key |
| `price_history` | id | same | append only |
| `scrape_runs` | id | ~10/day | written even on failure |

**Required deviation from the spec schema** — `pharmacy_listings` additionally needs
`pack_size int`, `pack_unit text`, `unit_price numeric`. Column additions, not renames.
Without them `v_cheapest_per_product_state` compares a 12-tablet pack to a 500-tablet jar.

## 5. Views

| View | Reads | Refresh | Risk |
|---|---|---|---|
| `v_latest_listings` | listings, pharmacies, products | live | window fn per (pharmacy,url) |
| `v_cheapest_per_product_state` | latest + `unit_price` | live | wrong without pack size |
| `v_suspicious_listings` | latest + registrations | live | **viable: 77% non-active in sample** |
| `v_price_change_7d` | price_history | live | needs 8 days of history |
| `mv_drug_price_index` | price_history | daily, `CONCURRENTLY` | needs unique index on (day, canonical_name, state) |
| `v_pipeline_health` | scrape_runs | live | 48 h → STALE |

`v_suspicious_listings` should union two conditions, because they disagree: `status <> 'Active'`
**OR** `expiry_date < current_date`.

`v_cheapest_per_product_state` carries a `pharmacy_count` and only claims "cheapest" when that
count is ≥ 2. A single-pharmacy cell is a national price, not a state comparison.

## 6. Matching

Two stages as specified: pgvector top-10 → deterministic filter on strength, form, ingredient.

Measured: **90.4%** of 250 live HealthPlus titles carry a parseable pack token (`xN` 68%,
mg/ml 65%). The parser is feasible; the failure mode is unit confusion, not missing data.

```
"Amlodipine Sandoz 10mg Tablets x28"  ₦4,200
→ amlodipine | 10mg | tablet | 28 tab | ₦150/tab
```

Priority: NRN in title → brand alias from `drug_match_rules` → pgvector on normalised name.
Reject on strength/form conflict even when similarity is high.

Only **66%** of HealthPlus SKUs are medicines (rest are vitamins, pumps, condoms). Filter by
`product_type` before matching or the index is polluted.

## 7. Infrastructure

| Service | Limit (verified Nov 2026) | Real constraint |
|---|---|---|
| Neon Free | 100 CU-h, 0.5–1 GB/project | none at MVP: ~0.1 GB/yr, ~1.5 CU-h/mo |
| Prefect Hobby | 5 deployments, 500 serverless min/mo | one deployment ≈ 300 min/mo; no retry headroom |
| GitHub Actions | free/unlimited public repos, **6 h/job** | full detail backfill ≈ 6.5 h → shard |
| Streamlit Cloud | 2.7 GB RAM/app, sleeps 12 h | never load `price_history` into memory |
| Neon Data API | Free-plan availability **unverified** | if unusable, serve REST from the app |

## 8. Build sequence

| Phase | Work | Exit gate |
|---|---|---|
| 0 | `git init`, public repo, MIT + disclosure, Neon project, extensions | `CREATE EXTENSION vector` succeeds |
| 1 | schema `.sql`; CSV → `products` + `drug_match_rules` | 597 names, 386 with aliases |
| 2 | Greenbook index (6 requests) | 10,895 NRNs, unique, IDs 2–12,519 |
| 3 | detail scraper, sharded, **retry on 500 (~10% of pages fail)** | status + expiry ≥95% populated |
| 4 | HealthPlus end-to-end | 1,197 listings, `unit_price` on ≥85% |
| 5 | Drugstore.ng + MedPlus; matcher; 6 views | cheapest-per-state returns rows in ≥2 states |
| 6 | Prefect daily + `scrape_runs` on every path | 7 consecutive green runs |
| 7 | Streamlit + API | index renders; JSON answers cheapest-per-state |

Detail budget: 11,754 pages ÷ 2 s = **6.5 h**, over the 6 h job cap. Shard 3 × ~2 h runs, or
restrict details to NRNs matching the 50-drug scope (≈500–1,500 pages ≈ 17–50 min).

## 9. Risk register

| Risk | Likelihood | Mitigation (verified state) |
|---|---|---|
| NAFDAC blocks the scrape | medium | **no mirror exists** → own dated full dump each run; block costs freshness, not history |
| Expired listings don't exist | **resolved** | 77% of sample is Expired/Inactive |
| Pack-size parsing wrong | medium | 90.4% parse rate; store raw title, never overwrite |
| Detail pages 500 intermittently | **confirmed ~10%** | exponential backoff, resume by ID cursor, never restart the range |
| Only one NGN API pharmacy | **resolved** | 4 price sources; 3 NGN-confirmed |
| State coverage thin (all Lagos) | **open** | Drugstore.ng carries 920 pharmacies — multi-state presence *unverified* |
| Cloudflare `Content-Signal: ai-train=no` | low | we reference data, not train; say so in the README |

## 10. Decisions

1. **Schema deviation** — add `pack_size`/`pack_unit`/`unit_price`. Recommended: yes.
2. **Pharmacy set** — HealthPlus + Drugstore.ng + MedPlus; nettpharmacy.com confirmed NGN, so
   it is available as a fourth source.
3. **Reporting policy — chosen: B (2026-11-06).** Publish a "cheapest" figure only where ≥2
   independent pharmacies quote that product in that state; elsewhere expose the national price
   plus `pharmacy_count = 1`. Lagos/FCT will be the only genuinely comparative cells. Never
   present a single-pharmacy national price as a state comparison.
3. **API layer** — Neon Data API if Free supports it, else a thin read-only service.
4. **Archive** — dated full register dump to Hugging Face Datasets from run one (git is wrong
   for >5 MB).

## 11. Definition of Done, re-scored

| Criterion | Status | Basis |
|---|---|---|
| Daily scrape green 7 days | **achievable** | flow ≈ 10 min; free minutes; 5-deployment cap respected |
| `v_suspicious_listings` ≥ 1 row | **achievable** | 77% non-active in sample |
| Dashboard renders state-by-drug index | **achievable** | Drugstore.ng covers all 37 states with LGA-level routes |
| API answers cheapest-per-state | **achievable** | same source; only Neon Data API availability is open |

Critical path is no longer data or geography — both are settled. It is **price variation**: a
Drugstore.ng product page exposes **one** price (`₦360` on the alben-paracetamol-drops page,
7 occurrences of the same string, no `pharmacy_name`/`seller`/`vendor` field in the SSR
payload, no compare-pharmacies text). So Drugstore is a national **single-price** source, not a
per-pharmacy marketplace view. "Cheapest per state" is therefore near-degenerate from that
source alone: one price nationwide. State-level *variation* needs pharmacies with their own
pricing, which means HealthPlus/MedPlus (Lagos) plus whatever else can be found.
Unverified: whether that one price changes with the selected state/LGA.

## 12. Unproven

- Does a Drugstore.ng product page show **several pharmacies' prices** (marketplace) or one
  platform price? This decides whether pharmacy #2 and #3 need real scrapers at all.
- MedPlus catalogue size (paginator clamps at 70, per-page count unknown).
- Neon Data API on Free.
- Second half of the NAFDAC status sample (IDs 6,375–12,500); exact ID bound in 12,520–12,599.
- Whether NAFDAC blocks under sustained load.
