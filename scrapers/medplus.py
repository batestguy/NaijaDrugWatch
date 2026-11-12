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
    /products?data_from=type&type=drugs&page_no={n-1}&page={n}
                                                          the whole drugs catalogue, 20 links per
                                                          page, and the ONLY route on this site
                                                          that actually paginates
    /products?id={category}&data_from=category&page={n}    20 links, then THE SAME 20 again: since
                                                          the 2026-11-09 rebuild this route ignores
                                                          its `page` parameter entirely, so a walk
                                                          of it yields one page per category
    /product/{slug}                                        name, price, currency, stock

DISCOVERY, MEASURED
    Until this change the scraper walked the category route, so six categories produced roughly
    six pages of links (128 rows written nightly) against a catalogue the site advertises as
    3,163 products. The category route is kept as `--route category` for comparison and for the
    day someone needs one category's contents, but discovery defaults to the drugs route.
    The overlap between a category's page 1 and the drugs route is measured in
    `.agent/T1-report.md`; do not assume a category is a subset without re-running it.

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
    python scrapers/medplus.py --discover-only                   # count product URLs, no product pages
    python scrapers/medplus.py --dry-run --limit 40              # fetch 40 product pages, no database
    python scrapers/medplus.py                                   # full drugs sweep, ~1,396 products
    python scrapers/medplus.py --route category --categories 12  # pre-2026-11-09 behaviour, 20 products
"""

from __future__ import annotations

import argparse
import http.client
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
MAX_PAGES = 70
# Measured 2026-11-12: the drugs catalogue ends at page 70 (page 70 holds 16 links, page 71 is
# empty, so 69 x 20 + 16 = 1,396 products). 70 is therefore a full sweep and not a sample. A
# smaller cap would starve every product after it, because the route is ordered rather than
# shuffled, so a fixed prefix never refreshes the tail. The walk still stops on its own when a
# page adds nothing, so a cap above the catalogue's end costs no requests.
HARD_TIMEOUT_S = 40

# ------------------------------------------------------------------ when a night is NOT a night
#
# Both numbers below are a JUDGEMENT, not a measurement. There is no measured distribution of
# nightly per-page failures, because the full sweep has never run unattended with this code: the
# only quantities on record (2026-11-12) are the catalogue size, 1,396 products over 70 pages, and
# the last full-ish run's 128 records, which predates the drugs-route fix. A normal night re-reads
# every product page, so `records` tracks the catalogue rather than the day's price changes: a
# quiet market barely moves it, which is why a floor on records is a fair test and not a test of
# how much churn happened.
#
# MAX_FAILED_SHARE: above this, the night is broken rather than thin. Set at 10% because a single
#   stray parse refusal (an `AUDIT_REJECT` placeholder price, a redesigned template) must not fail
#   an otherwise complete sweep, while a fifth of the catalogue failing is a source that has
#   changed shape under us and must not be graded fresh.
# MIN_RECORDS_FULL_SWEEP: about 70% of the 1,396 measured products. A full sweep that returns fewer
#   than this is missing the catalogue's tail, so the freshness gate would call a partial night a
#   completed one. It is a FLOOR, not a target: it says nothing about price changes.
MAX_FAILED_SHARE = 0.10
MIN_RECORDS_FULL_SWEEP = 1000

# Transport failures, i.e. the connection, not the answer. `HTTPError` is a `URLError` and is
# handled first everywhere, because it IS an answer. `IncompleteRead` lives under HTTPException:
# it is what a dropped connection looks like mid-body, and it is what ended a 70-page walk on
# 2026-11-12 (`.agent/T3-review.md`).
TRANSIENT_ERRORS = (
    TimeoutError,
    ConnectionResetError,
    http.client.HTTPException,
    urllib.error.URLError,
    OSError,
)


class Blocked(Exception):
    """The site answered 403 or 429: stop the run and report it.

    Deliberately NOT an `HTTPError` subclass and deliberately not caught by the product loop's
    per-page handler. A refusal is a statement about this client, not an accident on one page, so
    it must end the run instead of being counted as one failed page out of 1,396. The project rule
    is no evasion - no proxy rotation, no headless tricks - so a block is reported, not worked
    around.
    """

    def __init__(self, where: str, code: int) -> None:
        super().__init__(f"{where}: HTTP {code} — the site refused this client")
        self.where = where
        self.code = code


CATEGORY_URL = BASE_URL + "/products?id={category}&data_from=category&page={page}"
# The drugs route carries BOTH `page_no` (0-based) and `page` (1-based); the site's own "next"
# link publishes the pair, so both are sent rather than guessing which one the server reads.
DRUGS_URL = BASE_URL + "/products?data_from=type&type=drugs&page_no={page_no}&page={page}"
DISCOVERY_ROUTES = ("drugs", "category")
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


def page_product_links(body: str) -> list[str]:
    """Product URLs on one listing page, with the notify form target removed.

    The category markup also links/actions to /product/availability/notify; that is a form target,
    not a product, and requesting it returns HTTP 405.
    """
    found = [u.split("?")[0] for u in PRODUCT_LINK_RE.findall(body)]
    return [u for u in found if not any(bad in u for bad in NON_PRODUCT_PATHS)]


def _get(
    client: RateLimitedClient,
    url: str,
    *,
    where: str = "",
    retries: int = 2,
    log=print,
) -> str:
    """GET one URL with the retry policy the scraper applies everywhere.

    Retried: transport failures (a dropped connection, a timeout, a truncated body) and HTTP 5xx,
    the same number of attempts and the same spacing as `fetch_product()` has always used - two
    retries, five then ten seconds apart. Not retried: any other 4xx, which will not change on a
    second ask, and `robots.txt` refusals, which are consent and not a blip.

    Raises `Blocked` on 403/429 immediately - a refusal is answerable only by stopping.
    """
    label = where or url
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body, _final = client.get(url)
            return body
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise Blocked(label, exc.code) from exc
            if exc.code < 500:
                raise
            last = exc
        except PermissionError:
            # robots.txt disallows the path: asking twice more is not a retry, it is a pester.
            raise
        except TRANSIENT_ERRORS as exc:
            last = exc
        if attempt < retries:
            log(f"  {label}: {type(last).__name__} on attempt {attempt + 1}/{retries + 1},"
                f" retrying in {5 * (attempt + 1)} s")
            time.sleep(5 * (attempt + 1))
    raise last  # type: ignore[misc]


def _walk(
    client: RateLimitedClient,
    url_for_page,
    *,
    max_pages: int,
    start_page: int = 1,
    label: str,
    log=print,
    retries: int = 2,
) -> list[str]:
    """Follow a listing route until a page adds no link it has not already seen.

    "Adds nothing new" is the stop test rather than "page is empty", because the failure this
    ticket exists to fix is a route that ignores its page parameter and re-serves page 1 forever.
    A route that loops therefore stops on page 2 instead of burning its whole page budget.

    A transport failure is retried like any other request (`_get`), because the alternative is
    what happened on 2026-11-12: one `IncompleteRead` at any of the 70 pages ended the whole step
    and cost a night. Only when the retries are exhausted does the walk end, and it ends by
    RAISING, naming the page and the exception, rather than returning a short list that the run
    would have graded as a complete sweep.

    An HTTP 403 or 429 raises `Blocked` and ends the run: no retry, no workaround.
    """
    seen: list[str] = []
    known: set[str] = set()
    last = start_page + max_pages - 1
    for page in range(start_page, last + 1):
        url = url_for_page(page)
        where = f"{label} page {page}"
        try:
            body = _get(client, url, where=where, retries=retries, log=log)
        except Blocked as exc:
            log(f"  {where}: HTTP {exc.code} — BLOCKED, stopping this run. "
                "No retry, no workaround: a fix designed against a block is a fix against nothing.")
            raise
        except urllib.error.HTTPError as exc:
            log(f"  {where}: HTTP {exc.code}, stopping this route")
            break
        except TRANSIENT_ERRORS as exc:
            raise RuntimeError(
                f"{where}: {type(exc).__name__} on all {retries + 1} attempts, abandoning the"
                f" walk with {len(seen)} products found: {exc}"
            ) from exc
        found = page_product_links(body)
        if not found:
            log(f"  {label} page {page}: no product links on the page, stopping this route")
            break
        # Dedupe within the page as well as across pages: a listing page links the same product
        # twice (image and title), so counting anchors overstates a page's yield by ~20-30%.
        new = [u for u in dict.fromkeys(found) if u not in known]
        if not new:
            log(f"  {label} page {page}: +0 new products (all {len(found)} links already seen), stopping")
            break
        known.update(new)
        seen.extend(new)
        log(f"  {label} page {page}: +{len(new)} products, cumulative {len(seen)}")
    return seen


def product_urls(
    category: int,
    client: RateLimitedClient,
    *,
    max_pages: int,
    start_page: int = 1,
    log=print,
) -> list[str]:
    """Every product URL in a category. Retained for `--route category`.

    As of the 2026-11-09 rebuild this route ignores `page`, so in practice it yields page 1 and
    the walk stops on page 2 having added nothing. That is the route's behaviour, not a bug here.
    """
    return _walk(
        client,
        lambda page: CATEGORY_URL.format(category=category, page=page),
        max_pages=max_pages,
        start_page=start_page,
        label=f"category {category}",
        log=log,
    )


def drug_urls(
    client: RateLimitedClient,
    *,
    max_pages: int,
    start_page: int = 1,
    log=print,
) -> list[str]:
    """Product URLs from the drugs catalogue: the one route that paginates cleanly.

    `page_no` is 0-based and `page` is 1-based, matching the next-link the site publishes.
    """
    return _walk(
        client,
        lambda page: DRUGS_URL.format(page_no=page - 1, page=page),
        max_pages=max_pages,
        start_page=start_page,
        label="drugs route",
        log=log,
    )


def fetch_product(client: RateLimitedClient, url: str, *, retries: int = 2, log=print) -> str:
    """GET a product page, retrying transient transport errors. A 4xx is not retried.

    A 403 or 429 raises `Blocked` rather than a plain HTTP error, so the caller stops the run
    instead of counting it as another failed page and carrying on down the remaining URL list.
    """
    return _get(client, url, retries=retries, log=log)


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
    parser.add_argument("--categories", default=None,
                        help="comma-separated category ids for --route category (default: 12 Drugs)")
    parser.add_argument("--route", choices=DISCOVERY_ROUTES, default="drugs",
                        help="how product URLs are discovered: 'drugs' (default) walks the type=drugs"
                             " catalogue, which paginates; 'category' walks --categories, which the"
                             " site stopped paginating on 2026-11-09")
    parser.add_argument("--limit", type=int, default=None, help="stop after N products")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--start-page", type=int, default=1,
                        help="first discovery page (probe a deep page without walking to it)")
    parser.add_argument("--discover-only", action="store_true",
                        help="stop after discovery and print the product count: no product pages,"
                             " no archive, no database")
    parser.add_argument("--print-urls", action="store_true",
                        help="with --discover-only, print each discovered URL on its own line"
                             " prefixed 'URL ' so the list can be diffed between routes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    category_ids = [int(c) for c in (args.categories or "12").split(",") if c.strip()]
    connection = None
    run_id = None
    started = time.monotonic()
    scraped_at = datetime.now(timezone.utc)

    try:
        if not args.dry_run and not args.discover_only:
            connection = db_connect()
            run_id = start_run(connection, SOURCE)

        client = RateLimitedClient()
        urls: list[str] = []
        if args.route == "drugs":
            if args.categories is not None:
                print("note: --categories is ignored on the drugs route; "
                      "pass --route category to walk categories instead")
            urls = drug_urls(client, max_pages=args.max_pages, start_page=args.start_page)
            print(f"route drugs: {len(urls)} products")
        else:
            for category in category_ids:
                found = product_urls(
                    category, client, max_pages=args.max_pages, start_page=args.start_page
                )
                print(f"category {category}: {len(found)} products")
                urls.extend(found)
                if args.limit and len(urls) >= args.limit:
                    break
        urls = list(dict.fromkeys(urls))
        if args.limit:
            urls = urls[: args.limit]
        print(f"product URLs: {len(urls)}")

        if args.discover_only:
            elapsed = time.monotonic() - started
            rate = len(urls) / elapsed * 60 if elapsed else 0.0
            if args.print_urls:
                for url in urls:
                    print(f"URL {url}")
            print(f"discover-only: {len(urls)} distinct product URLs in {elapsed:.1f} s"
                  f" ({rate:.0f} URLs/min discovery rate)")
            print("discover-only: no product pages fetched, no archive, no database rows written")
            return 0

        records: list[dict[str, Any]] = []
        failed = 0
        for index, url in enumerate(urls, start=1):
            try:
                body = fetch_product(client, url)
            except Blocked as exc:
                # A refusal is not a per-page accident. Stop requesting NOW - the remaining URLs
                # are not asked for - and let the top-level handler write the night as failed.
                print(f"  BLOCKED at product {index}/{len(urls)}: {exc}", flush=True)
                print(f"  stopping: {len(urls) - index} URLs left unrequested", flush=True)
                raise
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

        # Is this a night, or a fragment of one? A run that collected something but lost a large
        # share of the catalogue must not be graded as a completed day, because the freshness gate
        # reads `status=success` and would call the source fresh. See the constants block at the
        # top for why these two numbers are a judgement rather than a measurement.
        attempted = len(urls)
        failure_share = failed / attempted if attempted else 1.0
        # The records floor is a statement about a FULL sweep (no --limit, the default drugs route,
        # the whole page budget from page 1). A deliberate sample is not a thin night.
        full_sweep = (
            args.limit is None
            and args.route == "drugs"
            and args.max_pages >= MAX_PAGES
            and args.start_page == 1
        )
        thin_reason: str | None = None
        if attempted == 0:
            thin_reason = "no product URLs discovered"
        elif failure_share > MAX_FAILED_SHARE:
            thin_reason = (f"{failed} of {attempted} product pages failed"
                           f" ({failure_share:.1%} > {MAX_FAILED_SHARE:.0%})")
        elif full_sweep and len(records) < MIN_RECORDS_FULL_SWEEP:
            thin_reason = (f"{len(records)} records from a full sweep"
                           f" (floor {MIN_RECORDS_FULL_SWEEP})")

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
            if thin_reason is not None:
                print(f"THIN NIGHT: {thin_reason}", file=sys.stderr)
                return 1
            return 0

        counts = store(connection := ensure_connection(connection), records, scraped_at)
        if thin_reason is not None:
            # Keep what was really observed, but do not claim the night: the archive above and the
            # listings below are genuine readings of a partial sweep, and the ledger's job is to
            # say the sweep was partial.
            message = f"thin night: {thin_reason}"
            finish_run(connection, run_id, status="failed",
                       record_count=len(records), error=message)
            print(f"scrape_runs id={run_id} status=failed record_count={len(records)} "
                  f"pharmacy_id={counts['pharmacy_id']} — {message}", file=sys.stderr)
            return 1
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
