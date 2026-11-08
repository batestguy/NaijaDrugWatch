#!/usr/bin/env python3
"""Drugstore.ng scraper: the third source, and the first that is a marketplace rather than a shop.

WHY THIS SOURCE MATTERS
    HealthPlus and MedPlus are single-shop catalogues in Lagos. Drugstore.ng is the widest
    catalogue probed (16,241 sitemap URLs) and the only one whose product pages name the selling
    pharmacy. It therefore adds breadth to `products` matching and to `v_suspicious_listings`.

WHAT IT DOES *NOT* ADD
    Comparisons. One product page carries exactly ONE seller's offer, so it can never put two
    pharmacies against one product on its own. `is_comparison` stays false for every Drugstore row.
    Do not let this source be described as "multi-pharmacy pricing".

ACCESS
    robots.txt: `User-agent: *` / `Allow: /`, with /search and the account areas disallowed.
    /product/ is allowed, which is all this scraper fetches. One request every >= 2 s per domain,
    custom User-Agent naming the project, product and price fields only.

STRUCTURE
    https://drugstore.ng/sitemap.xml    index; currently one child, sitemap1.xml
    sitemap1.xml                        <loc> entries: /product/, /medicines/, /online-pharmacy/<state>

    The price seam is the JSON-LD `Product` block, not the `__NUXT__` payload. Verified on
    2026-11-08 against /product/coartem-80480-tablets-artemether-lumefantrine:

        {"@type":"Product","name":"Coartem 80/480 Tablets (...)", "sku":3953,
         "brand":{"name":"Novartis Nigeria Limited"},
         "offers":{"priceCurrency":"NGN","price":9350,"availability":".../InStock"}}

    JSON-LD is a published contract; the Nuxt payload is minified to variable references
    (`company_name:h`), so it is used for nothing here. `brand` is the MANUFACTURER, not the seller
    -- reading it as the pharmacy would be wrong.

STATE IS 'National', DELIBERATELY
    `pharmacies.state` is NOT NULL and `v_cheapest_per_product_state` partitions on
    `(product_id, state)`. Verified 2026-11-08: the same product page under `?state=kano` is
    BYTE-IDENTICAL (sha256 1A33F0288D445538...), so a state route does not price anything. Picking
    Lagos would be invented; fanning one product into 37 state rows would be worse. 'National' is a
    separate, honest partition that cannot be mistaken for a state comparison.

    The per-offer seller (`company:{company_name, ..., state:"Lagos"}`) is therefore NOT recorded in
    this version. Revisit as seller-as-pharmacy only after measuring whether two sellers ever carry
    the same product; see PROGRESS.md 2026-11-08.

STOCK IS READ, NOT INFERRED
    `offers.availability` is the source's own statement: InStock -> True, OutOfStock -> False,
    anything else -> NULL (unknown). NULL never becomes "cheapest but unavailable".

Usage
-----
    python scrapers/drugstore.py --dry-run --limit 20
    python scrapers/drugstore.py --limit 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    RateLimitedClient,
    archive_jsonl,
    db_connect,
    ensure_connection,
    finish_run,
    price_bounds_error,
    record_price_history,
    start_run,
)
from healthplus import parse_pack, source_hash, unit_price_of  # noqa: E402

SOURCE = "drugstore"
PHARMACY_NAME = "Drugstore.ng"
PHARMACY_STATE = "National"  # see the module docstring: not a Nigerian state, and not a guess
PHARMACY_WEBSITE = "https://drugstore.ng"
BASE_URL = "https://drugstore.ng"
SITEMAP_INDEX_URL = BASE_URL + "/sitemap.xml"

LD_JSON_RE = re.compile(r'(?is)<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>')
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
# Run one covers the /product/ template only. /medicines/ is a second, unfetched template with
# 1,182 URLs; assuming it parses the same way would be a guess, so it is left for its own run.
PRODUCT_PREFIX = "/product/"

IN_STOCK = "https://schema.org/InStock"
OUT_OF_STOCK = "https://schema.org/OutOfStock"

# A slash pair is a STRENGTH, not a pack count: "Coartem 80/480 Tablets" is artemether 80 mg /
# lumefantrine 480 mg in a 6-tablet pack, not a 480-tablet pack. Observed 2026-11-08 -- without this
# guard parse_pack() returned pack_size=480, unit_price NGN 19.48/tab, i.e. a drug that looks almost
# free per tablet and would win every unit-price comparison. Stripped before pack parsing only; the
# raw title is still stored verbatim.
STRENGTH_PAIR_RE = re.compile(r"\d+\s*/\s*\d+")

INSERT_LISTING_SQL = """
insert into pharmacy_listings
    (pharmacy_id, product_id, raw_title, url, price_ngn, in_stock,
     pack_size, pack_unit, unit_price, scraped_at, source_hash)
values (%s, null, %s, %s, %s, %s, %s, %s, %s, %s, %s)
returning id
"""


# ------------------------------------------------------------------------------------ parsing


def ld_product(body: str) -> dict[str, Any] | None:
    """The JSON-LD `Product` object from a page, or None. Other blocks (Organization, WebSite,
    BreadcrumbList) are skipped rather than guessed at."""
    for match in LD_JSON_RE.finditer(body):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            # A malformed block must not hide a well-formed later one.
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "Product":
                return candidate
    return None


def _offer_of(product: dict[str, Any]) -> dict[str, Any] | None:
    """`offers` may be a dict or a list; take the first entry that actually carries a price."""
    offers = product.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None
    for offer in offers:
        if isinstance(offer, dict) and offer.get("price") is not None:
            return offer
    return None


def parse_product(body: str, url: str) -> dict[str, Any] | None:
    """One listing candidate from one product page, or None when it cannot be honestly priced.

    Returns None -- and is counted as a failure -- for a page with no Product block, no offer, a
    non-NGN currency, or a price outside the shared plausible band (common.price_bounds_error:
    reject < NGN 20 and > NGN 500000, accept exactly 20.00 and exactly 500000.00). Rejecting at
    build time matters: a 0.00 or 1.00 row wins every `min()`-based view and becomes "cheapest".
    """
    product = ld_product(body)
    if product is None:
        return None

    title = product.get("name")
    if not isinstance(title, str) or not title.strip():
        return None

    offer = _offer_of(product)
    if offer is None:
        # This is what a price-on-request product looks like: no offer block at all.
        return None

    currency = offer.get("priceCurrency")
    if currency != "NGN":
        return None

    try:
        price = Decimal(str(offer["price"]))
    except (TypeError, ValueError, ArithmeticError):
        return None
    reason = price_bounds_error(price)
    if reason is not None:
        # Refuse at build time. The AUDIT_REJECT line keeps a refused price distinguishable from a
        # parse failure, which still lands in the caller's generic `failed` counter.
        print(f"AUDIT_REJECT {reason} url={url} price={price:.2f}")
        return None

    availability = offer.get("availability")
    if availability == IN_STOCK:
        in_stock: bool | None = True
    elif availability == OUT_OF_STOCK:
        in_stock = False
    else:
        in_stock = None

    sku = product.get("sku")

    return {
        "source": SOURCE,
        "url": url,
        "raw_title": title.strip(),
        "price_ngn": f"{price:.2f}",
        "in_stock": in_stock,
        "stock_quantity": None,  # the page states availability, not a unit count
        "stock_evidence": f"json-ld availability={availability}",
        "currency": currency,
        "variant_id": str(sku) if sku is not None else None,
    }


def enrich(record: dict[str, Any]) -> dict[str, Any]:
    """Add pack parsing, unit price and the stable hash, reusing the HealthPlus implementation."""
    pack_title = STRENGTH_PAIR_RE.sub(" ", record["raw_title"])
    pack_size, pack_unit = parse_pack(pack_title)
    unit = unit_price_of(Decimal(record["price_ngn"]), pack_size, pack_unit)
    record["pack_size"] = pack_size
    record["pack_unit"] = pack_unit
    record["unit_price"] = str(unit) if unit is not None else None
    record["source_hash"] = source_hash(record)
    return record


# ---------------------------------------------------------------------------------- discovery


def product_urls(client: RateLimitedClient, *, limit: int | None, log=print) -> list[str]:
    """Every /product/ URL in the sitemap, in sitemap order.

    The sitemap is the whole catalogue, so there is no pagination to follow and no cursor to
    resume: one index fetch, then one child fetch.
    """
    index_body, _ = client.get(SITEMAP_INDEX_URL)
    children = [u for u in LOC_RE.findall(index_body) if "sitemap" in u.lower()]
    if not children:
        raise RuntimeError("sitemap index listed no child sitemaps")

    urls: list[str] = []
    for child in children:
        body, _ = client.get(child)
        for loc in LOC_RE.findall(body):
            path = loc.split(BASE_URL, 1)[-1]
            if path.startswith(PRODUCT_PREFIX):
                urls.append(loc)
        if limit is not None and len(urls) >= limit:
            break
        log(f"  {child}: running total {len(urls)} product URLs")

    urls = list(dict.fromkeys(urls))
    if limit is not None:
        urls = urls[:limit]
    return urls


def fetch_product(client: RateLimitedClient, url: str, *, retries: int = 2) -> str:
    """GET a product page, retrying transient transport errors. A 4xx is not retried."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body, _final = client.get(url)
            return body
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(5 * (attempt + 1))
    raise last  # type: ignore[misc]


# ------------------------------------------------------------------------------------ database


def ensure_pharmacy(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into pharmacies (name, website, state) values (%s, %s, %s)"
            " on conflict (name, state) do update set website = coalesce(excluded.website, pharmacies.website)"
            " returning id",
            (PHARMACY_NAME, PHARMACY_WEBSITE, PHARMACY_STATE),
        )
        pharmacy_id = cursor.fetchone()[0]
    connection.commit()
    return int(pharmacy_id)


def latest_hashes(connection, pharmacy_id: int) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "select distinct on (url) url, source_hash from pharmacy_listings"
            " where pharmacy_id = %s order by url, scraped_at desc, id desc",
            (pharmacy_id,),
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def store(connection, records: list[dict[str, Any]], scraped_at: datetime, log=print) -> dict[str, int]:
    pharmacy_id = ensure_pharmacy(connection)
    seen = latest_hashes(connection, pharmacy_id)
    inserted = unchanged = 0
    inserted_ids: list[int] = []
    with connection.cursor() as cursor:
        for record in records:
            if seen.get(record["url"]) == record["source_hash"]:
                unchanged += 1
                continue
            cursor.execute(
                INSERT_LISTING_SQL,
                (
                    pharmacy_id,
                    record["raw_title"],
                    record["url"],
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
    price_rows = record_price_history(connection, inserted_ids)
    connection.commit()
    log(f"listings: inserted={inserted} unchanged={unchanged} price_history+={price_rows}")
    return {"pharmacy_id": pharmacy_id, "inserted": inserted, "unchanged": unchanged}


# ------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Drugstore.ng product prices.")
    parser.add_argument("--limit", type=int, default=None, help="stop after N products")
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse, write no rows")
    args = parser.parse_args(argv)

    connection = None
    run_id = None
    started = time.monotonic()
    scraped_at = datetime.now(timezone.utc)

    try:
        if not args.dry_run:
            connection = db_connect()
            run_id = start_run(connection, SOURCE)

        client = RateLimitedClient()
        urls = product_urls(client, limit=args.limit)
        print(f"product URLs: {len(urls)}")

        records: list[dict[str, Any]] = []
        failed = 0
        for index, url in enumerate(urls, start=1):
            try:
                body = fetch_product(client, url)
            except Exception as exc:  # noqa: BLE001 - one bad page must not end the run
                failed += 1
                print(f"  {url}: {type(exc).__name__}", flush=True)
                continue
            record = parse_product(body, url)
            if record is None:
                failed += 1
                continue
            records.append(enrich(record))
            if index % 25 == 0 or index == len(urls):
                rate = index / max(time.monotonic() - started, 1e-9)
                print(f"  {index}/{len(urls)}  {rate:.2f}/s", flush=True)

        archive_path, archive_sha = archive_jsonl(SOURCE, records, when=scraped_at)
        prices = sorted(float(r["price_ngn"]) for r in records)
        print(f"\n--- {'dry run' if args.dry_run else 'drugstore run'} ---")
        print(f"products fetched     {len(urls)}")
        print(f"records              {len(records)}")
        print(f"failed               {failed}")
        if prices:
            print(f"price NGN min/median/max {prices[0]:.2f} / {prices[len(prices) // 2]:.2f} / {prices[-1]:.2f}")
        print(f"in stock true        {sum(1 for r in records if r['in_stock'] is True)}")
        print(f"in stock unknown     {sum(1 for r in records if r['in_stock'] is None)}")
        print(f"pack parsed          {sum(1 for r in records if r['pack_size'] is not None)}")
        print(f"unit_price set       {sum(1 for r in records if r['unit_price'] is not None)}")
        print(f"archive              {archive_path.name} sha256={archive_sha[:16]}")

        if args.dry_run:
            print("dry run: no database rows written")
            return 0

        counts = store(connection := ensure_connection(connection), records, scraped_at)
        finish_run(connection, run_id, status="success", record_count=len(records))
        print(f"scrape_runs id={run_id} status=success record_count={len(records)} "
              f"pharmacy_id={counts['pharmacy_id']}")
        return 0
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if connection is not None and run_id is not None:
            try:
                finish_run(connection, run_id, status="failed", error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                # The database socket is often what died; try a fresh one before leaving the run
                # stuck at 'running'.
                try:
                    fresh = db_connect()
                    finish_run(fresh, run_id, status="failed", error=message)
                    print(f"scrape_runs id={run_id} status=failed (reconnected)", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
