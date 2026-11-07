#!/usr/bin/env python3
"""HealthPlus (healthplusnigeria.com) - Shopify `/products.json` scraper.

Why an API and not HTML
-----------------------
`/products.json?limit=250&page=N` answers 200 JSON on this host and `robots.txt` does not
disallow it (probed 2026-11-06, see `research/2026-11-06-feasibility-probes.md`). Per the
API-first gate in `AGENTS.md`, HTML is only for sites with neither WooCommerce nor Shopify.

Decisions that are not obvious from the code
--------------------------------------------
**One listing per product, not per variant.** `pharmacy_listings` is unique on
`(pharmacy_id, url, scraped_at)` and `url` is the canonical product URL, so two variants of one
product cannot both be stored without inventing a second identity (`?variant=...`) that the
matcher and the state-by-drug index do not expect. A variant id is therefore recorded in the
archive and folded into `source_hash`, but not into the row.

**Which variant's price is stored.** The cheapest variant that is available; if no variant is
available, the cheapest variant overall with `in_stock = false`. When a variant is chosen while
other variants are available, that is a price *range* and the lowest one is stored -- the entry
price a shopper pays, not the largest pack. Both ends of the range go into the archive record
(`variant_price_min`, `variant_price_max`, `variant_count`) so the choice is auditable.

**source_hash inputs** (sha256 over a canonical JSON object, keys sorted, no whitespace):
`url`, `raw_title`, `price_ngn` (2 dp string), `in_stock`, `pack_size`, `pack_unit`,
`unit_price` (4 dp string), `variant_id`. Deliberately excluded: `scraped_at`, `id`,
`pharmacy_id`, `product_id` and the archive-only fields -- none of them is listing *content*, and
including `scraped_at` would make every run a change, which is exactly what `source_hash` exists
to prevent.

**record_count** in `scrape_runs` is the number of listings *observed and emitted* by the run
(parsed product -> row candidates), not the number inserted. A no-change rerun therefore reports
the same `record_count` as the first run while inserting zero rows; `inserted` and `unchanged`
are printed so the two numbers cannot be confused.

**Derived pack fields are inside `source_hash` on purpose.** Fixing the parser therefore mints a
new listing for every affected product with no price change -- 2 rows on 2026-11-07 when the
`7-18kg` nappy titles stopped reading 18000 g as a pack. That is deliberate: the ledger then shows
*when a parse changed*, instead of silently rewriting history. The cost is that a parser release
looks like a market event unless the `inserted` count is read alongside `record_count`.

**What is deliberately not done here.** `product_id` stays NULL (the P5 matcher fills it), and no
`price_history` row is written -- that table is keyed by `listing_id` and belongs to the flow that
owns listing identity, not to this scraper.

**Concurrency.** A session advisory lock (`pg_try_advisory_lock(hashtext('healthplus'))`) makes a
second overlapping run exit with status 2 instead of inserting. Without it two runs that start
before either commits both see an empty table and both insert the whole catalogue; the
`(pharmacy_id, url, scraped_at)` key cannot prevent that because each run writes its own
`scraped_at`. This happened for real on 2026-11-07 and is why the table briefly held 2 x 1,197 rows.

Usage
-----
    python scrapers/healthplus.py --dry-run            # fetch, parse, report; no database
    python scrapers/healthplus.py --limit 50           # first 50 products into Neon
    python scrapers/healthplus.py                      # full run (~5 requests)

`DATABASE_URL` is read from the environment. A `scrape_runs` row is written on success and on
failure -- including when the failure happens before any fetching. The one exception is a run that
loses the advisory lock to an in-flight run: it exits 2 and writes nothing, because nothing was
attempted. Nothing here falls back to Playwright, and no proxy or evasion is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

# Importable both as `python scrapers/healthplus.py` and as `python -m scrapers.healthplus`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    RateLimitedClient,
    archive_jsonl,
    db_connect,
    finish_run,
    record_price_history,
    start_run,
)

SOURCE = "healthplus"
PHARMACY_NAME = "HealthPlus"
PHARMACY_STATE = "Lagos"
PHARMACY_WEBSITE = "https://healthplusnigeria.com"

BASE_URL = "https://healthplusnigeria.com"
PRODUCTS_URL = BASE_URL + "/products.json?limit={limit}&page={page}"
PAGE_SIZE = 250
# Page 5 held 197 rows and page 6 empty on 2026-11-06; 40 pages is a runaway guard, not a target.
MAX_PAGES = 40
# Above this, a "mass" in a title is a product attribute rather than a pack size. Real case:
# "KissKids Super Dry Baby Diapers Size 4, 7-18kg x46" -- 18 kg is the baby's weight range and
# the pack is the 46 the title also states. Without this guard, unit_price divided nappies by
# 18,000 g and made them look near-free per gram.
MAX_PACK_MASS_G = 5000
# HealthPlus quotes NGN; a shop whose prices are not in this band is a shape change, not a price.
ABSURD_PRICE_NGN = Decimal("500000")

TWO_DP = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


class SourceBlocked(RuntimeError):
    """HTTP-level refusal (Cloudflare 403/503, rate limit). Never retried with another tool."""


class SourceShapeError(RuntimeError):
    """The endpoint answered, but not with the Shopify products payload we require."""


# --------------------------------------------------------------------- title parsing
#
# Pack size lives in the title: "Amlodipine Sandoz 10mg Tablets x28", "Adalat LA 30 mg X 30",
# "Retrax Levamisole Unit Pack 15ml Syrup". No `pack_size` field exists in the Shopify payload,
# and NAFDAC's `pack_description` is blank on ~70% of pages, so this is the only source.

# A volume: "60ml", "0.5 l". The lookbehind skips the denominator of "120mg/5ml" so the
# concentration is not mistaken for the pack content.
_VOLUME_RE = re.compile(
    r"(?<![/\w.])(\d+(?:[.,]\d+)?)\s*(mls?|millilitres?|milliliters?|litres?|liters?|l)\b"
)
# A mass: "100g", "1.5 kg" is not handled (no kg in this catalogue). Strengths are in mg and are
# excluded by the fact that "mg" cannot match -- the unit group is anchored after the digits.
_MASS_RE = re.compile(r"(?<![/\w.])(\d+(?:[.,]\d+)?)\s*(kg|gms?|grams?|g)\b")

# An explicit multiplier: "x 30", "X28". Used for counts, and only for counts.
_COUNT_MULTIPLIER_RE = re.compile(r"(?<![\w.])(?:x|×)\s*(\d{1,4})(?![\d.])")
# "28's", "24s".
_COUNT_POSSESSIVE_RE = re.compile(r"(?<![\w.])(\d{1,4})\s*['’]?s\b")
# "Pack of 3", "box of 10".
_COUNT_PACK_OF_RE = re.compile(
    r"\b(?:pack|box|tin|jar|bottle|vial|ampoule|sachet|strip|blister|roll|tube)s?\s+(?:of\s+)?(\d{1,4})\b"
)
# "60 tablets", "12 capsules", "30 sachets", "10 vials".
_COUNT_NOUN_RE = re.compile(
    r"(?<![\w.])(\d{1,4})\s*"
    r"(tabs?|tablets?|caps?|capsules?|sachets?|satchets?|pcs|pieces|strips?|vials?|"
    r"ampoules?|tubes?|bottles?|packs?|rolls?|pads?)\b"
)
# The reverse order, "Tablets 14", which the catalogue also uses. The trailing `(?![\w.])` keeps
# "Tablets 500mg" from being read as a 500-count pack.
_COUNT_NOUN_FIRST_RE = re.compile(
    r"(?<![\w.])(tabs?|tablets?|caps?|capsules?|sachets?|satchets?|pcs|pieces|strips?|vials?|"
    r"ampoules?|tubes?|bottles?|packs?|rolls?|pads?)\s+(?:of\s+)?(\d{1,4})(?![\w.])"
)

_NOUN_TO_UNIT = {
    "tab": "tab",
    "tabs": "tab",
    "tablet": "tab",
    "tablets": "tab",
    "cap": "cap",
    "caps": "cap",
    "capsule": "cap",
    "capsules": "cap",
    "sachet": "sachet",
    "sachets": "sachet",
    "satchet": "sachet",
    "satchets": "sachet",
}

_UNIT_WORDS = (
    ("sachet", re.compile(r"\bsat?chets?\b")),
    ("cap", re.compile(r"\bcapsules?\b|\bcaps\b|\bcap\b")),
    ("tab", re.compile(r"\btablets?\b|\btabs?\b|\bblister\b")),
)


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def parse_pack(title: str) -> tuple[int | None, str | None]:
    """Return `(pack_size, pack_unit)` parsed from a listing title, or `(None, None)`.

    `pack_unit` is one of tab | cap | ml | g | sachet. Ambiguity is resolved towards the pack
    content a shopper compares, and anything genuinely unclear returns `(None, None)` rather than
    a guess, because `unit_price` divides by this number.
    """
    if not title:
        return None, None
    text = title.lower().replace("×", "x")
    count, noun_unit = _parse_count(text)

    volume = [m for m in _VOLUME_RE.finditer(text)]
    if volume:
        match = volume[-1]  # "120mg/5ml ... 60ml" -> 60; the concentration is looked past
        amount = _to_decimal(match.group(1))
        if match.group(2).startswith("l") and match.group(2) not in {"ml", "mls"}:
            amount *= 1000
        if amount > 0:
            return int(amount.to_integral_value(rounding=ROUND_HALF_UP)), "ml"

    mass = [m for m in _MASS_RE.finditer(text)]
    if mass:
        match = mass[-1]
        amount = _to_decimal(match.group(1))
        if match.group(2) == "kg":
            amount *= 1000
        # 1g/2g are strengths (Augmentin 1g), not pack sizes; a real pack in grams is >= 5.
        # A mass above MAX_PACK_MASS_G is a product attribute, not the pack, so the explicit
        # count wins when the title also carries one.
        implausible_mass = amount > MAX_PACK_MASS_G and count is not None
        if amount >= 5 and not implausible_mass:
            return int(amount.to_integral_value(rounding=ROUND_HALF_UP)), "g"

    if count is None:
        return None, None
    return count, noun_unit or _unit_from_title(text)


def _parse_count(text: str) -> tuple[int | None, str | None]:
    """Last explicit count in the title, with a unit when the noun names one."""
    candidates: list[tuple[int, str | None]] = []
    for regex in (_COUNT_MULTIPLIER_RE, _COUNT_POSSESSIVE_RE, _COUNT_PACK_OF_RE):
        for match in regex.finditer(text):
            candidates.append((int(match.group(1)), None))
    for match in _COUNT_NOUN_RE.finditer(text):
        candidates.append((int(match.group(1)), _NOUN_TO_UNIT.get(match.group(2))))
    for match in _COUNT_NOUN_FIRST_RE.finditer(text):
        candidates.append((int(match.group(2)), _NOUN_TO_UNIT.get(match.group(1))))
    plausible = [c for c in candidates if 1 <= c[0] <= 10000]
    if not plausible:
        return None, None
    return plausible[-1]


def _unit_from_title(text: str) -> str | None:
    for unit, regex in _UNIT_WORDS:
        if regex.search(text):
            return unit
    return None


# ------------------------------------------------------------------------ Shopify -> row


def _price_of(variant: dict[str, Any]) -> Decimal | None:
    raw = variant.get("price")
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def choose_variant(variants: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Cheapest available variant, else cheapest variant overall. See module docstring."""
    priced = [v for v in variants if _price_of(v) is not None]
    if not priced:
        return None, "no_priced_variant"
    available = [v for v in priced if v.get("available") is True]
    pool = available or priced
    chosen = min(pool, key=lambda v: (_price_of(v), v.get("id") or 0))
    return chosen, ("available" if available else "all_out_of_stock")


def source_hash(record: dict[str, Any]) -> str:
    """Stable content digest. Inputs are documented in the module docstring."""
    payload = {
        "url": record["url"],
        "raw_title": record["raw_title"],
        "price_ngn": record["price_ngn"],
        "in_stock": record["in_stock"],
        "pack_size": record["pack_size"],
        "pack_unit": record["pack_unit"],
        "unit_price": record["unit_price"],
        "variant_id": record["variant_id"],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def unit_price_of(price: Decimal | None, pack_size: int | None, pack_unit: str | None) -> Decimal | None:
    """price / pack_size at 4 dp. NULL when either side is missing or non-positive."""
    if price is None or pack_size is None or pack_unit is None:
        return None
    if price <= 0 or pack_size <= 0:
        return None
    return (price / Decimal(pack_size)).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def build_record(product: dict[str, Any]) -> dict[str, Any] | None:
    """One listing candidate from one Shopify product, or None when it cannot be priced."""
    handle = product.get("handle")
    title = product.get("title")
    if not handle or not title:
        return None
    variants = product.get("variants") or []
    chosen, variant_reason = choose_variant(variants)
    if chosen is None:
        return None

    price = _price_of(chosen)
    if price is None or price <= 0:
        # A zero or missing price cannot be a real listing, and it would win every min()-based
        # view as the "cheapest" row. Reject at build time rather than only reporting it later.
        return None
    pack_size, pack_unit = parse_pack(title)
    prices = [_price_of(v) for v in variants if _price_of(v) is not None]

    record = {
        "source": SOURCE,
        "url": f"{BASE_URL}/products/{handle}",
        "handle": handle,
        "raw_title": title,
        "price_ngn": str(price) if price is not None else None,
        "in_stock": bool(chosen.get("available")),
        "pack_size": pack_size,
        "pack_unit": pack_unit,
        "unit_price": (
            str(unit_price_of(price, pack_size, pack_unit))
            if unit_price_of(price, pack_size, pack_unit) is not None
            else None
        ),
        "variant_id": chosen.get("id"),
        "variant_reason": variant_reason,
        "variant_count": len(variants),
        "variant_price_min": str(min(prices)) if prices else None,
        "variant_price_max": str(max(prices)) if prices else None,
        "variant_sku": chosen.get("sku"),
        "product_type": product.get("product_type"),
        "published_at": product.get("published_at"),
        "shopify_updated_at": product.get("updated_at"),
    }
    record["source_hash"] = source_hash(record)
    return record


# ----------------------------------------------------------------------------- fetching


def fetch_products(
    client: RateLimitedClient,
    *,
    limit: int | None = None,
    log=print,
) -> tuple[list[dict[str, Any]], int]:
    """Page through `/products.json` until an empty page. Returns (products, requests used)."""
    products: list[dict[str, Any]] = []
    requests_used = 0
    for page in range(1, MAX_PAGES + 1):
        url = PRODUCTS_URL.format(limit=PAGE_SIZE, page=page)
        try:
            body, _final_url = client.get(url)
        except urllib.error.HTTPError as exc:  # 401/403/429/503 land here
            snippet = ""
            try:
                snippet = exc.read()[:200].decode("utf-8", errors="replace")
            except Exception:
                pass
            raise SourceBlocked(f"HTTP {exc.code} from {url}: {snippet!r}") from exc
        requests_used += 1

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SourceShapeError(
                f"{url} did not return JSON ({len(body)} bytes): {body[:200]!r}"
            ) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
            raise SourceShapeError(
                f"{url} returned JSON without a 'products' list: {body[:200]!r}"
            )

        batch = payload["products"]
        log(f"page {page}: {len(batch)} products")
        if not batch:
            break
        missing = [p for p in batch if "variants" not in p or "handle" not in p]
        if missing:
            raise SourceShapeError(
                f"{url} product shape changed: {len(missing)} rows lack 'variants'/'handle', "
                f"first keys={sorted(batch[0].keys())[:12]}"
            )
        products.extend(batch)
        if limit is not None and len(products) >= limit:
            products = products[:limit]
            break
    else:
        raise SourceShapeError(f"stopped at MAX_PAGES={MAX_PAGES} without an empty page")
    return products, requests_used


# ------------------------------------------------------------------------------ database

INSERT_LISTING_SQL = """
insert into pharmacy_listings
    (pharmacy_id, product_id, raw_title, url, price_ngn, in_stock,
     pack_size, pack_unit, unit_price, scraped_at, source_hash)
values (%s, null, %s, %s, %s, %s, %s, %s, %s, %s, %s)
returning id
"""


def acquire_run_lock(connection) -> bool:
    """Session advisory lock per source: two overlapping runs may not insert at the same time.

    Without this, two runs that start before either commits both see "no listings yet" and both
    insert the full catalogue -- the `(pharmacy_id, url, scraped_at)` key cannot stop it because
    each run writes its own `scraped_at`. Observed for real on 2026-11-07 (two overlapping runs put
    2 x 1,197 rows in). The lock is session-scoped and released when the connection closes.
    """
    with connection.cursor() as cursor:
        cursor.execute("select pg_try_advisory_lock(hashtext(%s))", (SOURCE,))
        return bool(cursor.fetchone()[0])


def ensure_pharmacy(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into pharmacies (name, website, state) values (%s, %s, %s)"
            " on conflict (name, state)"
            " do update set website = coalesce(excluded.website, pharmacies.website)"
            " returning id",
            (PHARMACY_NAME, PHARMACY_WEBSITE, PHARMACY_STATE),
        )
        pharmacy_id = cursor.fetchone()[0]
    connection.commit()
    return int(pharmacy_id)


def latest_hashes(connection, pharmacy_id: int) -> dict[str, str]:
    """Newest `source_hash` per URL already stored, so an unchanged run adds no rows."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select distinct on (url) url, source_hash from pharmacy_listings"
            " where pharmacy_id = %s order by url, scraped_at desc, id desc",
            (pharmacy_id,),
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def store_records(
    connection,
    records: Iterable[dict[str, Any]],
    *,
    scraped_at: datetime,
    log=print,
) -> dict[str, int]:
    """Insert new or changed listings. Returns counts; never updates an existing row."""
    pharmacy_id = ensure_pharmacy(connection)
    seen = latest_hashes(connection, pharmacy_id)

    inserted = unchanged = duplicate_url = 0
    batch_urls: set[str] = set()
    inserted_ids: list[int] = []
    with connection.cursor() as cursor:
        for record in records:
            url = record["url"]
            if url in batch_urls:
                duplicate_url += 1
                continue
            batch_urls.add(url)
            if seen.get(url) == record["source_hash"]:
                unchanged += 1
                continue
            cursor.execute(
                INSERT_LISTING_SQL,
                (
                    pharmacy_id,
                    record["raw_title"],
                    url,
                    record["price_ngn"],
                    record["in_stock"],
                    record["pack_size"],
                    record["pack_unit"],
                    record["unit_price"],
                    scraped_at,
                    record["source_hash"],
                ),
            )
            inserted_ids.append(int(cursor.fetchone()[0]))
            inserted += 1
    # The price series the materialised index reads. Listings are immutable observations, so
    # each new listing contributes exactly one price_history row; see common.record_price_history.
    price_rows = record_price_history(connection, inserted_ids)
    connection.commit()
    log(
        f"listings: inserted={inserted} unchanged={unchanged} duplicate_url={duplicate_url}"
        f" price_history+={price_rows}"
    )
    return {
        "pharmacy_id": pharmacy_id,
        "inserted": inserted,
        "unchanged": unchanged,
        "duplicate_url": duplicate_url,
    }


# --------------------------------------------------------------------------------- report


def summarise(records: list[dict[str, Any]], products_seen: int, requests_used: int) -> dict[str, Any]:
    with_pack = [r for r in records if r["pack_size"] is not None]
    with_unit_price = [r for r in records if r["unit_price"] is not None]
    prices = [Decimal(r["price_ngn"]) for r in records if r["price_ngn"] is not None]
    null_prices = [r for r in records if r["price_ngn"] is None]
    absurd = [r for r in records if r["price_ngn"] is not None
              and (Decimal(r["price_ngn"]) <= 0 or Decimal(r["price_ngn"]) > ABSURD_PRICE_NGN)]
    multi_variant = [r for r in records if r["variant_count"] > 1]
    ranged = [r for r in records if r["variant_price_min"] != r["variant_price_max"]]
    volume_and_multiplier = [
        r for r in records
        if r["pack_unit"] == "ml" and _COUNT_MULTIPLIER_RE.search(r["raw_title"].lower())
    ]
    return {
        "products_seen": products_seen,
        "listings": len(records),
        "pack_parsed": len(with_pack),
        "pack_parse_rate": (len(with_pack) / len(records)) if records else 0.0,
        "unit_price_set": len(with_unit_price),
        "unit_price_rate": (len(with_unit_price) / len(records)) if records else 0.0,
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "price_median": sorted(prices)[len(prices) // 2] if prices else None,
        "null_prices": len(null_prices),
        "absurd_prices": [r["raw_title"] for r in absurd][:10],
        "absurd_price_count": len(absurd),
        "multi_variant": len(multi_variant),
        "price_ranges": len(ranged),
        "ml_with_x_multiplier": len(volume_and_multiplier),
        "requests": requests_used,
    }


def print_report(report: dict[str, Any], archive_path: Path | None, archive_sha: str | None) -> None:
    median = report["price_median"]
    print("\n--- healthplus dry run ---")
    print(f"products fetched        {report['products_seen']}")
    print(f"listings built          {report['listings']}")
    print(f"pack size parsed        {report['pack_parsed']} "
          f"({report['pack_parse_rate']:.1%} of listings)")
    print(f"unit_price set          {report['unit_price_set']} "
          f"({report['unit_price_rate']:.1%} of listings)")
    print(f"price NGN min/median/max {report['price_min']} / {median} / {report['price_max']}")
    print(f"null prices             {report['null_prices']}")
    print(f"absurd prices (<=0 or >{ABSURD_PRICE_NGN}): {report['absurd_price_count']}")
    for title in report["absurd_prices"]:
        print(f"    {title!r}")
    print(f"multi-variant products  {report['multi_variant']} (with a price range: {report['price_ranges']})")
    print(f"ml titles with 'x N'    {report['ml_with_x_multiplier']} (pack content, not multipack total)")
    print(f"http requests           {report['requests']}")
    if archive_path is not None:
        print(f"archive                 {archive_path} sha256={archive_sha}")


# ----------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape HealthPlus (Shopify products.json).")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write no database rows")
    parser.add_argument("--limit", type=int, default=None, help="stop after N products")
    args = parser.parse_args(argv)

    client = RateLimitedClient()
    connection = None
    run_id = None
    scraped_at = datetime.now(timezone.utc)

    try:
        if not args.dry_run:
            connection = db_connect()
            if not acquire_run_lock(connection):
                print(
                    f"another {SOURCE} run holds the advisory lock; exiting without writing anything",
                    file=sys.stderr,
                )
                return 2
            run_id = start_run(connection, SOURCE)

        products, requests_used = fetch_products(client, limit=args.limit)
        records = [r for r in (build_record(p) for p in products) if r is not None]
        skipped = len(products) - len(records)

        archive_path, archive_sha = archive_jsonl(SOURCE, records, when=scraped_at)
        report = summarise(records, len(products), requests_used)
        report["skipped_products"] = skipped
        print_report(report, archive_path, archive_sha)
        if skipped:
            print(f"products skipped        {skipped} (no handle/title or no priced variant)")

        if args.dry_run:
            print("\ndry run: no database rows written")
        else:
            counts = store_records(connection, records, scraped_at=scraped_at)
            finish_run(connection, run_id, status="success", record_count=len(records))
            print(
                f"\nscrape_runs id={run_id} status=success record_count={len(records)} "
                f"pharmacy_id={counts['pharmacy_id']}"
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - the ledger row is the point of this except
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if connection is not None and run_id is not None:
            try:
                finish_run(connection, run_id, status="failed", error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
