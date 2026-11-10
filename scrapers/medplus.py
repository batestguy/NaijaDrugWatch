#!/usr/bin/env python3
"""MedPlus (medplusnig.com) scraper: the second pharmacy, and the one that can create a comparison.

WHY THIS SOURCE MATTERS
    HealthPlus alone can never satisfy `v_cheapest_per_product_state`: `is_comparison` needs TWO
    independent pharmacies quoting the same product in the same state. MedPlus is Lagos-based like
    HealthPlus, so a shared product is a genuine comparison rather than a national price.

ACCESS
    robots.txt: `User-agent: *` with no Disallow, plus Cloudflare content signals
    `search=yes, ai-train=no, use=reference`. We aggregate and cite (reference use); we do not
    train on it. Named AI crawlers are blocked and our User-Agent is not one of them. This needs
    a line in the published disclosure.

STRUCTURE
    /products?id={category}&data_from=category&page={n}    20 product links per page
    /product/{slug}                                        name, price, currency, stock

    Each product page carries the numbers on one element:
        <form id="add-to-cart-form" data-product-name="..." data-product-price="3300"
              data-currency="NGN">
    That is the seam we read: no price regex, no currency guessing.

STOCK IS READ, NOT INFERRED
    The add-to-cart form's own hidden quantity input carries `max="<units available>"`, so stock
    is a number the page states: `in_stock = max > 0`. Read since the 2026-11-09 rebuild, whose
    *visible* quantity input (`x-ref="quantityInput"`) carries a constant `max="50"` on every
    page -- a per-order cap, not stock, and it is 50 on pages that render "Notify me" too. The
    pre-rebuild `class="input-number"` input is still tried, but only when the cart input is
    absent, so a fallback can never overwrite a reading that succeeded. When neither a count nor
    a marker is present, stock is NULL (unknown) rather than assumed true -- claiming stock we
    did not read is how an unavailable item ends up winning a "cheapest" comparison.
    `stock_quantity` and `stock_evidence` are archived per product so the reading can be audited.

Usage
-----
    python scrapers/medplus.py --dry-run --categories 31,32 --limit 40
    python scrapers/medplus.py --categories 12,31,32,50,57,58
"""

from __future__ import annotations

import argparse
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
from healthplus import ABSURD_PRICE_NGN, parse_pack, source_hash, unit_price_of  # noqa: E402

SOURCE = "medplus"
PHARMACY_NAME = "MedPlus"
PHARMACY_STATE = "Lagos"
PHARMACY_WEBSITE = "https://medplusnig.com"
BASE_URL = "https://medplusnig.com"
MAX_PAGES = 40
HARD_TIMEOUT_S = 40

CATEGORY_URL = BASE_URL + "/products?id={category}&data_from=category&page={page}"
PRODUCT_LINK_RE = re.compile(r'(https://medplusnig\.com/product/[^"\\\s]+)')
# The category markup also links/actions to /product/availability/notify; that is a form target,
# not a product, and requesting it returns HTTP 405.
NON_PRODUCT_PATHS = ("/product/availability/",)
CART_FORM_RE = re.compile(r'<form id="add-to-cart-form"[^>]*>', re.S)
ATTR_RE = re.compile(r'data-(?:product-)?([a-z]+)="([^"]*)"')
OOS_RE = re.compile(r"(?i)out of stock")
INPUT_TAG_RE = re.compile(r"<input[^>]*>", re.S)
# PRE-REBUILD stock signal, kept as a fallback only: the visible quantity input carried
# max="<units available>". As of 2026-11-09 that input is gone and its replacement carries a
# constant max="50", so this now matches nothing on current pages.
STOCK_INPUT_RE = re.compile(r'<input[^>]*class="[^"]*input-number[^"]*"[^>]*>', re.S)
MAX_ATTR_RE = re.compile(r'max="(\d+)"')

INSERT_LISTING_SQL = """
insert into pharmacy_listings
    (pharmacy_id, product_id, raw_title, url, price_ngn, in_stock,
     pack_size, pack_unit, unit_price, scraped_at, source_hash)
values (%s, null, %s, %s, %s, %s, %s, %s, %s, %s, %s)
returning id
"""


# ------------------------------------------------------------------------------------ parsing


def cart_form_region(body: str, form_start: int) -> str:
    """The add-to-cart form up to the next `<form>`: its hidden inputs live there, not elsewhere.

    Scoping matters on this site. The page also carries a "request a product" form whose
    `<input name="quantity" id="quantity">` has no `max` at all, so a document-wide search for
    `id="quantity"` can land on an unrelated field.
    """
    next_form = body.find("<form", form_start + len("<form"))
    return body[form_start: next_form if next_form != -1 else len(body)]


def cart_stock_quantity(region: str) -> int | None:
    """Units the cart form will accept, from its own `<input name="quantity" ... max="N">`.

    `max` is the page's own count of units available: 0 on every control we know to be
    unavailable, a positive count on every control we know to be available. Only the zero vs
    non-zero distinction is load-bearing; the magnitude is archived, not interpreted.
    """
    for tag in INPUT_TAG_RE.findall(region):
        if 'name="quantity"' not in tag:
            continue
        maximum = MAX_ATTR_RE.search(tag)
        if maximum is not None:
            return int(maximum.group(1))
    return None


def parse_product(body: str, url: str) -> dict[str, Any] | None:
    """Name, price and currency from the add-to-cart form; stock from the same form's cap."""
    form = CART_FORM_RE.search(body)
    if form is None:
        return None
    attributes = dict(ATTR_RE.findall(form.group(0)))
    name = attributes.get("name")
    price = attributes.get("price")
    currency = attributes.get("currency")
    if not name or not price or currency != "NGN":
        return None

    lead_in = body[: form.start()]
    out_of_stock_marker = OOS_RE.search(lead_in) is not None

    stock_quantity = cart_stock_quantity(cart_form_region(body, form.start()))
    if stock_quantity is not None:
        in_stock: bool | None = stock_quantity > 0
        evidence = f"cart quantity max={stock_quantity}"
    else:
        # Fallback, consulted only when the current signal is absent, so it cannot overwrite it.
        legacy = STOCK_INPUT_RE.search(body)
        legacy_max = MAX_ATTR_RE.search(legacy.group(0)) if legacy is not None else None
        if legacy_max is not None:
            stock_quantity = int(legacy_max.group(1))
            in_stock = stock_quantity > 0
            evidence = f"legacy quantity max={stock_quantity}"
        elif out_of_stock_marker:
            in_stock = False
            evidence = "out-of-stock marker before add-to-cart"
        else:
            # No count and no marker: UNKNOWN, not in stock. Claiming stock we did not read
            # is how an unavailable item ends up winning a "cheapest" comparison.
            in_stock = None
            evidence = "no stock signal on page"

    try:
        price_value = f"{float(price):.2f}"
    except ValueError:
        return None
    reason = price_bounds_error(Decimal(price_value))
    if reason is not None:
        # NGN 1.00 is a placeholder, not a price, and it wins every min()-based view. Reject at
        # build time; the AUDIT_REJECT line keeps a refused price distinguishable from a parse
        # failure, which still lands in the caller's generic `failed` counter.
        print(f"AUDIT_REJECT {reason} url={url} price={price_value}")
        return None

    return {
        "source": SOURCE,
        "url": url,
        "raw_title": name.strip(),
        "price_ngn": price_value,
        "in_stock": in_stock,
        "stock_quantity": stock_quantity,
        "stock_evidence": evidence,
        "currency": currency,
        # MedPlus has one price per product, no variant model; kept explicit so the shared
        # source_hash() contract stays identical across sources.
        "variant_id": None,
    }


def enrich(record: dict[str, Any]) -> dict[str, Any]:
    """Add pack parsing, unit price and the stable hash, reusing the HealthPlus implementation."""
    pack_size, pack_unit = parse_pack(record["raw_title"])
    unit = unit_price_of(Decimal(record["price_ngn"]), pack_size, pack_unit)
    record["pack_size"] = pack_size
    record["pack_unit"] = pack_unit
    record["unit_price"] = str(unit) if unit is not None else None
    record["source_hash"] = source_hash(record)
    return record


def product_urls(category: int, client: RateLimitedClient, *, max_pages: int, log=print) -> list[str]:
    """Every product URL in a category, following pages until one adds nothing new."""
    seen: list[str] = []
    known: set[str] = set()
    for page in range(1, max_pages + 1):
        url = CATEGORY_URL.format(category=category, page=page)
        try:
            body, _ = client.get(url)
        except urllib.error.HTTPError as exc:
            log(f"  category {category} page {page}: HTTP {exc.code}, stopping this category")
            break
        found = [u.split("?")[0] for u in PRODUCT_LINK_RE.findall(body)]
        found = [u for u in found if not any(bad in u for bad in NON_PRODUCT_PATHS)]
        new = [u for u in found if u not in known]
        if not new:
            break
        known.update(new)
        seen.extend(new)
        log(f"  category {category} page {page}: +{len(new)} products")
    return seen


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
    parser = argparse.ArgumentParser(description="Scrape MedPlus product prices.")
    parser.add_argument("--categories", default="12", help="comma-separated category ids (default: 12 Drugs)")
    parser.add_argument("--limit", type=int, default=None, help="stop after N products")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    categories = [int(c) for c in args.categories.split(",") if c.strip()]
    connection = None
    run_id = None
    started = time.monotonic()
    scraped_at = datetime.now(timezone.utc)

    try:
        if not args.dry_run:
            connection = db_connect()
            run_id = start_run(connection, SOURCE)

        client = RateLimitedClient()
        urls: list[str] = []
        for category in categories:
            found = product_urls(category, client, max_pages=args.max_pages)
            print(f"category {category}: {len(found)} products")
            urls.extend(found)
            if args.limit and len(urls) >= args.limit:
                break
        urls = list(dict.fromkeys(urls))
        if args.limit:
            urls = urls[: args.limit]
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
            if index % 25 == 0:
                print(f"  {index}/{len(urls)}  {index / (time.monotonic() - started):.2f}/s", flush=True)

        archive_path, archive_sha = archive_jsonl(SOURCE, records, when=scraped_at)
        prices = sorted(float(r["price_ngn"]) for r in records)
        print(f"\n--- {'dry run' if args.dry_run else 'medplus run'} ---")
        print(f"products fetched     {len(urls)}")
        print(f"records              {len(records)}")
        print(f"failed               {failed}")
        if prices:
            print(f"price NGN min/median/max {prices[0]:.2f} / {prices[len(prices) // 2]:.2f} / {prices[-1]:.2f}")
            print(f"absurd prices        {sum(1 for p in prices if p <= 0 or p > ABSURD_PRICE_NGN)}")
        print(f"in stock             {sum(1 for r in records if r['in_stock'])}")
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
