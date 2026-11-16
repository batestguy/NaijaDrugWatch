"""Cross-check a matched price against the page it came from, without the scraper's parser.

WHY. Checking a scraped price with the code that scraped it only asks the parser whether it agrees
with itself. This reads a second source per shop:

  HealthPlus  the storefront's own JSON (`<product-url>.js`). Price, title and availability as the
              platform reports them, with no HTML parsing at all -- a genuinely different channel.
  MedPlus     the server page's add-to-cart form. NOTE: this is the same `data-product-price`
              attribute the scraper reads, so this is NOT an independent parse. It still catches the
              things that matter most -- the page changed after we collected it, the product was
              withdrawn, the price moved -- but it cannot catch a parser that has always read the
              field wrongly. MedPlus has no second server-side source; a genuinely independent read
              there needs a rendered browser.

POLITENESS. Both hosts rate-limit. One request every `--pause` seconds per host, and a 429 backs off
rather than retrying hard. This is why an ad-hoc check fails where the batch succeeds.

Usage:
    python -X utf8 scripts/crosscheck_pages.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

from envfile import ensure_database_url

UA = "NaijaDrugWatch/0.1 (+https://github.com/batestguy/NaijaDrugWatch) price cross-check"
HP_PRICE = re.compile(r'data-product-price="([0-9.]+)"')
HP_NAME = re.compile(r'data-product-name="([^"]*)"')
MP_PRICE = re.compile(r'data-product-price="([0-9.]+)"')
MP_NAME = re.compile(r'data-product-name="([^"]*)"')
MP_STOCK = re.compile(r'name="quantity"[^>]*max="(\d+)"', re.S)

last_call: dict[str, float] = {}


def fetch(url: str, host: str, pause: float, timeout: int = 30) -> str:
    """One request, spaced by host, with a single polite backoff on 429."""
    wait = pause - (time.time() - last_call.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    for attempt in (1, 2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                last_call[host] = time.time()
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            last_call[host] = time.time()
            if exc.code == 429 and attempt == 1:
                time.sleep(30)
                continue
            raise
    raise RuntimeError("unreachable")


def numbers(text: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d{1,4}", text.replace(",", ""))}


def healthplus(url: str, pause: float) -> dict:
    data = json.loads(fetch(url.split("?")[0] + ".js", "healthplusnigeria.com", pause))
    variants = data.get("variants") or []
    live = [v for v in variants if v.get("available")]
    chosen = (live or variants or [None])[0]
    return {
        "title": data.get("title", ""),
        "price": float(chosen["price"]) / 100.0 if chosen else None,
        "available": bool(live),
        "channel": "storefront JSON (independent of HTML parsing)",
    }


def medplus(url: str, pause: float) -> dict:
    body = fetch(url, "medplusnig.com", pause)
    price = MP_PRICE.search(body)
    name = MP_NAME.search(body)
    stock = MP_STOCK.search(body)
    return {
        "title": name.group(1) if name else "",
        "price": float(price.group(1)) if price else None,
        "available": bool(stock) and int(stock.group(1)) > 0,
        "channel": "form attribute (same field as the scraper: drift only)",
    }


EXTRACTORS = {
    "HealthPlus": (healthplus, "healthplusnigeria.com"),
    "MedPlus": (medplus, "medplusnig.com"),
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--pause", type=float, default=2.5)
    args = parser.parse_args(argv[1:])

    ensure_database_url()
    import os

    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute("""
            with cheapest_per_shop as (
              select l.product_id, l.canonical_name, l.state, l.pharmacy_name, l.price_ngn,
                     l.pack_size, l.url,
                     row_number() over (partition by l.product_id, l.state, l.pharmacy_name
                                        order by l.price_ngn) rn
              from v_latest_listings l
              where l.product_id is not null and l.in_stock is true and l.price_ngn is not null
            )
            select canonical_name, state, pharmacy_name, price_ngn, pack_size, url
            from cheapest_per_shop
            where rn = 1 and (product_id, state) in (
                select product_id, state from v_cheapest_per_product_state where is_comparison)
            order by canonical_name, pharmacy_name
        """).fetchall()

    products = {}
    for row in rows:
        products.setdefault((row[0], row[1]), []).append(row)
    targets = list(products.items()) if args.all else list(products.items())[: args.limit]

    print(f"{'product':<34} {'shop':<12} {'ours':>10} {'page':>10} {'pack':>5}  live   verdict")
    print("-" * 104)
    problems = 0
    checked = 0
    for (name, state), entries in targets:
        for _, _, shop, our_price, pack, url in entries:
            extractor_entry = EXTRACTORS.get(shop)
            if extractor_entry is None:
                continue
            extractor, host = extractor_entry
            try:
                seen = extractor(url, args.pause)
            except Exception as exc:  # noqa: BLE001 -- a failed fetch is a finding, not a crash
                print(f"{name[:33]:<34} {shop:<12} {float(our_price):>10,.0f} {'-':>10} "
                      f"{str(pack or '-'):>5}  {'-':<6} could not read: {type(exc).__name__} "
                      f"{getattr(exc, 'code', '')}")
                problems += 1
                checked += 1
                continue
            checked += 1
            page_price = seen["price"]
            price_ok = page_price is not None and abs(page_price - float(our_price)) <= max(
                1.0, float(our_price) * 0.02)
            pack_ok = pack is None or pack in numbers(seen["title"])
            verdict = []
            if not price_ok:
                verdict.append("PRICE DIFFERS" if page_price is not None else "no price on page")
            if not pack_ok:
                verdict.append(f"stored pack {pack} not in page title")
            if not seen["available"]:
                verdict.append("not available")
            problems += bool(verdict)
            print(f"{name[:33]:<34} {shop:<12} {float(our_price):>10,.0f} "
                  f"{(page_price if page_price is not None else float('nan')):>10,.0f} "
                  f"{str(pack or '-'):>5}  {str(seen['available'])[:6]:<6} "
                  f"{'; '.join(verdict) if verdict else 'agrees'}")
        print()

    print(f"{checked} page reads over {len(targets)} products, {problems} with something to look at.")
    print("A price difference is not automatically wrong: the page may simply have moved on since")
    print("collection. It is a reason to look, not a verdict.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
