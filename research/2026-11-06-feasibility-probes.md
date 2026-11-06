# Feasibility probe — 2026-11-06

Raw HTTP probes against the real data sources, run before any code was written.
No browser, no JS execution: plain `fetch` with
`User-Agent: NaijaDrugWatch-feasibility-probe/0.1`.
Reproduce any row with `curl -sS -A 'NaijaDrugWatch-feasibility-probe/0.1' <url>`.

## 1. NAFDAC Greenbook — the regulatory layer

| Probe | Result |
|---|---|
| `GET /robots.txt` | `200` — `User-agent: *` / `Disallow:` (empty). Everything is crawlable. |
| `GET /` | `200`, 19.9 KB, server-rendered Laravel (csrf-token meta, Blade templates). |
| `GET /api/products`, `/api/productCategories`, `/api/ingredients` | `404`. No JSON API. |
| `GET /sitemap.xml` | `404`. No URL index. |
| `GET /search?search=paracetamol` | `404`. Search is not a query-string route. |
| `GET /productCategories` | `200`, 13.1 KB, links to 6 category pages. |
| `GET /productCategory/products/{1,2,5,6,7,12}` | `200`. Sizes 4.5 MB / 88 KB / 521 KB / 62 KB / 84 KB / 11 KB. |
| `GET /products/details/2` | `200`, 14.8 KB plain HTML. |
| `GET /products/details/5000` | `200`. |

### What the six category pages give you (cheap path)

Each row carries product name, form, strength and NRN, e.g.

```
Products of Drugs. AG Spironolactone## Tablet Spironolactone 25 mg NRN: A4-100160
```

No pagination: `paginationLinks: []`, `data-tables: false`, `rel="next"` absent.
One request per category returns the whole category.

Counted inline `NRN:` values:

| Category | NRN labels | Unique NRNs |
|---|---|---|
| 1 | 10,152 | 9,353 |
| 2 | 160 | 159 |
| 5 | 1,196 | 1,165 |
| 6 | 101 | 96 |
| 7 | 150 | 146 |
| 12 | 0 | 0 |
| **Total** | **11,759** | **10,899** |

**10,899 unique registrations** reachable in 6 requests (~5.2 MB), not the
"approximately 7,000" in the spec.

### What a detail page adds (expensive path)

`/products/details/2` renders, as plain text:

```
AG Spironolactone | Spironolactone 25 mg Tablet | ROA Oral | Applicant AnnyGod
Pharmaceutical Company Ltd | NRN A4-100160 | Status Active | ATC C03DA01
Product Category Drugs | Packsize 1 x 500's (in a jar)
Manufacturer Alpa Laboratories Pvt Ltd | Country INDIA
Approval Date 2021-12-17 | Expiry Date 2026-12-16
```

Status, approval date and expiry date are **not** on the category pages — they
require one detail request per registration.

**Cost at the mandated 1 req / 2 s:** 10,899 x 2 s = 21,798 s = **6.05 h**,
marginally over the GitHub Actions 6 h per-job ceiling, and it cannot be
parallelised without breaking the per-domain rate limit. Shard across runs, or
fetch details only for registrations that matter to the 50-drug scope.

## 2. Pharmacy layer — the market layer

Probed 8 candidate hosts for Shopify `/products.json` and WooCommerce
`/wp-json/wc/store/products`.

| Host | Shopify | WooCommerce | Note |
|---|---|---|---|
| healthplusnigeria.com | **200, JSON** | not tested | 1,197 products |
| medecify.com | 404 | **200, JSON** | `currency_code: EUR` |
| medplusnig.com | 404 | 404 | Not Woo/Shopify |
| drugstore.ng | 404 | 404 | Nuxt SSR (`data-n-head-ssr`); aggregator, 900+ pharmacies |
| mopheth.com | 404 | 404 | |
| goodhealth.com.ng | 404 | 404 | |
| drugstoc.com | 200, HTML | — | Not JSON |
| megacareonline.com | 403 | — | Blocks the probe UA |

`healthplus.ng`, `medplus.com.ng`, `emednig.com`, `hmedix.com`,
`pharmacyhub.ng` do not resolve (wrong domain or no DNS entry).

### HealthPlus (`healthplusnigeria.com`) — confirmed usable

- Shopify. `/products.json?limit=250&page=N` returns
  `products[].title`, `variants[].price` (NGN string), `variants[].available`
  (in-stock boolean), `sku`, `product_type`, `tags`.
- Catalogue: pages 1-4 return 250 each, page 5 returns 197, page 6 returns 0 →
  **1,197 products**.
- Prices on page 1: min ₦180, median ₦11,910, max ₦1,750,000.
- 166 of the first 250 products (66%) look like medicines by title/type, e.g.
  `Adalat LA 30 mg X 30`, `Amlodipine Sandoz 10mg Tablets x28`,
  `Retrax Levamisole Unit Pack 15ml Syrup`.
- `robots.txt`: `User-agent: *` / `Allow: /`, then disallows for
  `/admin`, `/cart/`, `/checkout`, `/orders`, `/account`, `/services`,
  `/sf_*`, `/recommendations/products`, `/cart.js`, sort/filter crawl traps.
  **`/products.json` is not disallowed.**
- The same file carries Shopify's 2026 agent policy: a pointer to
  `/agents.md`, a UCP profile at `/.well-known/ucp`, an MCP endpoint at
  `/api/ucp/mcp`, and the comment "AJAX surfaces: agents should use UCP/MCP
  instead". `/agents.md` exists (5.8 KB) and describes agent shopping via
  UCP/WebMCP, not bulk price reading.

### Drugstore.ng — the aggregator angle

- `robots.txt`: `Allow: /` minus `/auth/`, `/cart/`, `/checkout/`, `/orders/`,
  `/dashboard/`, `/profile/`, `/search`, `/pharmacy/request`.
- No `products.json`, no `wc/store`, `/api/products` 404. Nuxt SSR app.
- Site claims 900+ pharmacies. If a product endpoint exists it is private and
  would need discovery; `/search` is disallowed, so the obvious door is shut.

## 3. Seed dataset — #FixMedPrices

`africaopendata.org/api/3/action/package_show?id=medicine-prices`
→ "Medicine Prices", licence **Creative Commons Attribution**, one CSV resource:

`https://open.africa/dataset/b48de105-0c93-4f47-a718-a4d54b3c2b9b/resource/3adff776-5c8e-4875-9f9a-a6eeff8f4ddb/download/medprices.csv`

- 195 KB, **1,074 data rows**.
- Header: `strength, name, form, price, brand_names/0 … brand_names/87, id`
  (88 brand-name columns).
- Sample rows:
  `20 mg/ml, Abacavir, solution, 0.0197, Abavir, 0`
  `60 mg, Abacavir Sulfate, tab-cap, 0.0943, , 2`
- **No registration number, no status, no expiry date, no applicant.**
- `price` values are fractions of a currency unit (`0.0197`, `0.0942`), i.e. a
  unit reference price, not an NGN retail price.

So the dataset can populate `drug_match_rules` / canonical `products`
(name, strength, form, brand aliases) but **cannot** populate
`nafdac_registrations`.

## 4. Free-tier limits (checked Nov 2026)

| Service | Limit | Source |
|---|---|---|
| Neon Free | 100 CU-h/mo per project, 0.5 GB → **1 GB** per project (changed 2026-10-02), 100 projects, 10 branches, 5 GB egress | multiple 2026 pricing trackers; re-check at signup |
| Prefect Cloud Hobby | 2 users, 1 workspace, **5 deployments**, **500 serverless min/mo**, 5 automations, 7-day run retention, 625 req/min | prefect.io/pricing |
| GitHub Actions | **free and unlimited** on public repos with standard runners; 6 h max per job; 35 days max per workflow run; 20 concurrent jobs on Free | docs.github.com billing |
| Streamlit Community Cloud | unlimited public apps, **2.7 GB RAM** per app (was 1 GB), sleeps after 12 h idle, no custom domain | streamlit docs/forum |

## 5. Not verified

- Proportion of the 10,899 registrations that are expired or non-Active —
  decides whether `v_suspicious_listings` has rows on day one. Sample 200
  detail pages (~7 min) to measure it.
- Whether a Nigerian (NGN-priced) WooCommerce store exists among the hosts not
  probed. Only `medecify.com` answered, and it prices in EUR.
- Whether `drugstore.ng` exposes any product endpoint to a logged-out client.
- Whether NAFDAC will block at the IP/UA level under sustained load; the
  9jaCheckr precedent says it can, robots.txt notwithstanding.
- ~~The independent `greenbook-open` mirror~~ **Disproven in round 2 (below).** It does not exist. There is no third-party mirror, so the Greenbook is a single point of failure and the project must keep its own snapshots.

## 6. Round 2 — independent verification (scout, same day)

Carried out by a separate read-only agent to test whether round 1's DNS failures
were an artefact of one sandbox. Method: resolution checked against two
independent resolvers (`dns.google`, `cloudflare-dns.com`), then direct HTTPS.

### Domains that genuinely do not exist

`NXDOMAIN` on both resolvers, i.e. not a sandbox artefact:

`medplus.com.ng`, `medplus.ng`, `emednig.com`, `emednigeria.com`,
`hmedix.com.ng`, `pharmacyhub.ng`, `healthlandpharmacy.com.ng`

So round 1 was right to discard them. `hmedix.com` resolves
(`208.91.197.195`) but could not be fetched — still unresolved.

### Hosts that exist but have no product API

| Host | Status | Platform | Verdict |
|---|---|---|---|
| medplusnig.com | 200, Cloudflare, PHP 8.2.35 | custom | `/products.json` 404, `/wp-json/` 404 |
| mopheth.com | 403 Cloudflare challenge | openresty | both endpoints 404 |
| goodhealth.com.ng | resolves (162.159.140.166), home 404 | dead | both endpoints 404 |
| drugstore.ng | 200 | Nuxt / nginx | `/products.json` 404 (`{}`), no Woo |
| healthplusnigeria.com | 200 | **Shopify** | `/products.json` 200, `products` array |

**Total NGN-priced API pharmacies confirmed across both rounds: 1.**
MedPlus is a live, scrapeable HTML target — that is the realistic path to
pharmacy #2, not an API.

### The mirror does not exist

- `api.github.com/repos/DeusOfConsensus/greenbook-open` → `404`
- `github.com/DeusOfConsensus/greenbook-open` → `404`
- The owner exists (`200`) with two unrelated public repos (`kvraft`, `focusee-render`)
- GitHub search for "greenbook nafdac" returns six unrelated repos

The search snippet that described a versioned snapshot API was wrong. **No
fallback exists**: if NAFDAC blocks, there is no mirror to fail over to. The
only hedge is the project's own archive — keep a dated full dump of the
register (not just `nafdac_status_snapshots` deltas) in version control or
object storage, so a block costs freshness rather than history.
