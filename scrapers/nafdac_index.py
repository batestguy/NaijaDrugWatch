#!/usr/bin/env python3
"""NAFDAC Greenbook index scraper (P2) - 6 category pages -> ~10,900 registrations.

Why HTML and no API
-------------------
The Greenbook has no JSON API and no mirror: `/api/*`, `/sitemap.xml` and `/search?q=` all 404
(`research/2026-11-06-feasibility-probes.md` section 1). Six category pages are the whole index,
about 5.2 MB, with no pagination. Detail pages are a different phase (P3) and are the only place
status, approval date and expiry live - so this module leaves those columns NULL on purpose.

What the server actually returns (verified against live HTML on 2026-11-07, not against the
one-line example in the research note). Each registration is a card:

    <div class="card naf-card" >
      <a href="http://greenbook.nafdac.gov.ng/products/details/6931">
        <div class="card-body" >
          <h5>Actemra 162 mg** <span class="form">Solution for injection</span></h5>
          <span>Tocilizumab </span><br/>
          <span>162 mg/0.9 mL</span><br/>
          <span>NRN: A6-100070</span>
        </div>
      </a>
    </div>

so `h5` is name + dosage form, and the three body spans are active ingredient, strength, NRN.
Measured on the live pages: 10,155/10,155 cards in category 1 and 160/160 in category 2 carry
exactly three body spans, so the shape is uniform rather than merely common.

Four parsing decisions that are not obvious from the code:

**Trailing glyph runs are stripped from `product_name`.** The index page appends template
footnote glyphs to the h5 text - `##` on 3,751 category-1 rows, `**` on 2,463, `#` on 277, `*`
on 127, `***`/`+++` on 17, and a bare `$` on 107. They are index-page artifacts, not names: the
detail page for the same product (details/2) renders "AG Spironolactone" with no `##`. A
trailing `+` is only stripped when it is a run of two or more (12 rows, all `+++`), because a
single trailing `+` could be part of a real brand name.

**NRNs are normalised, not regex-validated.** 27 of 10,155 category-1 values are dirty at source:
en dashes (`A4-4279`), spaces around the dash (`A4 - 5180`), old slashed forms (`4/1/9086`),
suffixed forms (`A4-4924L`), and values that are not NRNs at all (`NA`, `Not available yet`, and
pack sizes leaked into the field: `1 X 10`, `2 X 7`). Normalising the dash forms is what makes
them joinable to pharmacy listings later; rejecting the rest is better than storing `NA` as a
primary key. Anything that still contains whitespace after normalisation, has no digit, or is
`NA`/`N/A` is skipped and counted.

**Four cards in category 1 have `<span>NRN:</span>` with no number** (details 4957, 5576, 7276,
12516). They cannot be inserted - `registration_number` is the primary key - so they are skipped
and reported, not written as an empty string.

**`source_url` is the detail URL.** The card links to the page that will carry status and expiry
in P3, so storing it means P3 does not have to guess an id from the NRN.

Idempotency and what this module refuses to touch
------------------------------------------------
The upsert updates only the four index-owned columns and `scraped_at`. It never writes `status`,
`approval_date` or `expiry_date`, so a nightly re-run cannot erase what P3 has filled in. It never
writes `nafdac_status_snapshots` - that ledger belongs to P3, and a status written from an index
page would be a fabricated observation.

`record_count` in `scrape_runs` is unique registrations emitted by the run, not the 11,759 inline
`NRN:` labels: categories repeat registrations (category 1 alone has 763 values appearing more
than once), and the table's key is `registration_number`.

Usage
-----
    python scrapers/nafdac_index.py --dry-run          # fetch, parse, report; no database
    python scrapers/nafdac_index.py --limit 50         # first 50 registrations into Neon
    python scrapers/nafdac_index.py                    # full run (~6 category pages)

`DATABASE_URL` is read from the environment by `common.db_connect`; this module never reads
`.env` itself and never prints the value.
"""

from __future__ import annotations

import argparse
import html as html_unescape
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Importable both as `python scrapers/nafdac_index.py` and as `python -m scrapers.nafdac_index`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    RateLimitedClient,
    archive_jsonl,
    db_connect,
    finish_run,
    start_run,
)

SOURCE = "nafdac_greenbook"
ARCHIVE_SOURCE = "nafdac_index"

# http:// is deliberate. The host serves an expired TLS certificate, so https fails with
# SEC_E_CERT_EXPIRED; using the working scheme directly keeps the client's documented
# https->http fallback untouched and avoids ever disabling certificate verification.
BASE_URL = "http://greenbook.nafdac.gov.ng"
CATEGORIES_URL = BASE_URL + "/productCategories"
CATEGORY_URL = BASE_URL + "/productCategory/products/{category_id}"

# The six links the categories page publishes; used as a sanity check on discovery, never as the
# source of truth - the ids are read from the page so a renumbering is visible rather than silent.
EXPECTED_CATEGORY_IDS = (1, 2, 5, 6, 7, 12)

# ------------------------------------------------------------------------------ HTML patterns
#
# Non-greedy up to `</div></a>`: every card nests one `div.card-body` inside one `a`, and no
# card contains a second anchor, so the first `</div>` followed by `</a>` closes that card.

CARD_RE = re.compile(r'<div class="card naf-card"\s*>(.*?)</div>\s*</a>', re.S)
CATEGORY_CARD_RE = re.compile(r'<a href="([^"]*/productCategory/products/(\d+))"[^>]*>(.*?)</a>', re.S)
HREF_RE = re.compile(r'<a href="([^"]+)"')
H5_RE = re.compile(r"<h5>(.*?)</h5>", re.S)
FORM_RE = re.compile(r'<span class="form">(.*?)</span>', re.S)
BODY_SPAN_RE = re.compile(r"<span>(.*?)</span>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
NRN_PREFIX_RE = re.compile(r"^NRN\s*:\s*", re.I)
TRAILING_GLYPH_RUN_RE = re.compile(r"[\s#*$]+$")
TRAILING_PLUS_RUN_RE = re.compile(r"\++$")

UNICODE_DASHES = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212")
NOT_AN_NRN = {"NA", "N/A", "N.A.", "NONE", "-", "--"}

# The index publishes `NA` in the form and strength cells instead of leaving them empty. Stored
# literally it looks like a value to a matcher, which filters on exactly these two columns, so it
# is normalised to NULL. Product names keep their leading `#` for now: P3 rewrites names from the
# canonical detail page, and stripping a glyph that might be meaningful would be guessing twice.
NA_SENTINELS = NOT_AN_NRN | {"NULL", "NIL"}

# ----------------------------------------------------------------------------------- database

INSERT_REGISTRATION_SQL = """
insert into nafdac_registrations
    (registration_number, product_name, dosage_form, strength, source_url, scraped_at)
values (%s, %s, %s, %s, %s, %s)
on conflict (registration_number) do update set
    product_name = coalesce(excluded.product_name, nafdac_registrations.product_name),
    dosage_form  = coalesce(excluded.dosage_form,  nafdac_registrations.dosage_form),
    strength     = coalesce(excluded.strength,     nafdac_registrations.strength),
    source_url   = coalesce(excluded.source_url,   nafdac_registrations.source_url),
    scraped_at   = excluded.scraped_at
"""


# ------------------------------------------------------------------------------------ parsing


def text_of(fragment: str) -> str:
    """Tag-stripped, entity-decoded, whitespace-collapsed text. Tags first, then entities."""
    return re.sub(r"\s+", " ", html_unescape.unescape(TAG_RE.sub(" ", fragment))).strip()


def text_or_none(fragment: str) -> str | None:
    """`text_of`, but a published `NA` / `-` sentinel becomes NULL rather than a fake value."""
    value = text_of(fragment)
    if not value or value.upper() in NA_SENTINELS:
        return None
    return value


def strip_trailing_glyphs(name: str) -> str:
    """Drop the index page's trailing footnote glyphs, keeping any single trailing `+`.

    A run of two or more `+` is stripped (12 category-1 rows, all `+++`); a single trailing `+`
    is left in place because it could be part of a brand name.
    """
    cleaned = TRAILING_GLYPH_RUN_RE.sub("", name)
    plus = TRAILING_PLUS_RUN_RE.search(cleaned)
    if plus is not None and len(plus.group(0)) >= 2:
        cleaned = cleaned[: plus.start()].rstrip()
    return cleaned


def normalise_nrn(raw: str) -> str | None:
    """Return a joinable NRN, or None when the value is not an identification number.

    Folds unicode dashes and spaces around the dash, because `A4 - 5180` and `A4-5180` are the
    same registration; rejects anything still containing whitespace (the source leaks pack sizes
    such as `1 X 10` and prose such as `Not available yet` into this field).
    """
    value = NRN_PREFIX_RE.sub("", text_of(raw))
    value = unicodedata.normalize("NFKC", value)
    for dash in UNICODE_DASHES:
        value = value.replace(dash, "-")
    value = re.sub(r"\s*-\s*", "-", value).strip()
    if not value:
        return None
    if any(ch.isspace() for ch in value):
        return None
    if value.upper() in NOT_AN_NRN or not any(ch.isdigit() for ch in value):
        return None
    return value.upper()


def parse_category(body: str, *, category_id: int, category_name: str | None) -> dict[str, Any]:
    """Parse one category page into records plus the counts the report needs."""
    records: list[dict[str, Any]] = []
    cards = malformed = missing_nrn = 0
    for block in CARD_RE.findall(body):
        cards += 1
        href = HREF_RE.search(block)
        heading = H5_RE.search(block)
        spans = BODY_SPAN_RE.findall(block)
        if href is None or heading is None or len(spans) != 3:
            malformed += 1
            continue

        registration_number = normalise_nrn(spans[2])
        if registration_number is None:
            missing_nrn += 1
            continue

        form = FORM_RE.search(heading.group(1))
        name = strip_trailing_glyphs(
            text_of(FORM_RE.sub(" ", heading.group(1)))
        )
        records.append(
            {
                "registration_number": registration_number,
                "product_name": name or None,
                "dosage_form": text_or_none(form.group(1)) if form else None,
                "strength": text_or_none(spans[1]),
                "source_url": href.group(1),
                "active_ingredient": text_of(spans[0]) or None,
                "category_id": category_id,
                "category_name": category_name,
            }
        )
    return {
        "category_id": category_id,
        "category_name": category_name,
        "cards": cards,
        "malformed": malformed,
        "missing_nrn": missing_nrn,
        "records": records,
    }


def discover_categories(client: RateLimitedClient) -> list[dict[str, Any]]:
    """Read the six category links off /productCategories, in page order."""
    body, final_url = client.get(CATEGORIES_URL)
    categories: list[dict[str, Any]] = []
    seen: set[int] = set()
    for href, raw_id, inner in CATEGORY_CARD_RE.findall(body):
        category_id = int(raw_id)
        if category_id in seen:
            continue
        seen.add(category_id)
        heading = H5_RE.search(inner)
        categories.append(
            {
                "category_id": category_id,
                "url": href,
                "category_name": text_of(heading.group(1)) if heading else None,
            }
        )
    if not categories:
        raise RuntimeError(f"no category links found on {final_url}; the page layout changed")
    return categories


def collect(
    client: RateLimitedClient,
    categories: Iterable[dict[str, Any]],
    *,
    limit: int | None = None,
    log=print,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Fetch and parse each category; deduplicate on NRN, first occurrence wins.

    Returns (unique records, per-category stats, pages fetched).
    """
    unique: dict[str, dict[str, Any]] = {}
    stats: list[dict[str, Any]] = []
    pages = 0
    for category in categories:
        if limit is not None and len(unique) >= limit:
            break
        body, _ = client.get(category["url"])
        pages += 1
        parsed = parse_category(
            body,
            category_id=category["category_id"],
            category_name=category["category_name"],
        )
        added = 0
        for record in parsed["records"]:
            key = record["registration_number"]
            if key in unique:
                continue
            unique[key] = record
            added += 1
            if limit is not None and len(unique) >= limit:
                break
        parsed["added"] = added
        parsed.pop("records")
        stats.append(parsed)
        log(
            f"  category {category['category_id']:>2} ({(category['category_name'] or '?')[:34]:<34})"
            f" cards={parsed['cards']:>5} malformed={parsed['malformed']:>2}"
            f" no_nrn={parsed['missing_nrn']:>2} new={added:>5}"
        )
    return list(unique.values()), stats, pages


# --------------------------------------------------------------------------------- database io


def store_records(
    connection,
    records: Iterable[dict[str, Any]],
    *,
    scraped_at: datetime,
    log=print,
) -> dict[str, int]:
    """Upsert registrations. Returns inserted/updated counts; never clears P3-owned columns."""
    rows = list(records)
    with connection.cursor() as cursor:
        cursor.execute(
            "select registration_number from nafdac_registrations where registration_number = any(%s)",
            ([row["registration_number"] for row in rows],),
        )
        existing = {value for (value,) in cursor.fetchall()}
        cursor.executemany(
            INSERT_REGISTRATION_SQL,
            [
                (
                    row["registration_number"],
                    row["product_name"],
                    row["dosage_form"],
                    row["strength"],
                    row["source_url"],
                    scraped_at,
                )
                for row in rows
            ],
        )
    connection.commit()
    inserted = sum(1 for row in rows if row["registration_number"] not in existing)
    updated = len(rows) - inserted
    log(f"registrations: inserted={inserted} updated={updated} total={len(rows)}")
    return {"inserted": inserted, "updated": updated, "total": len(rows)}


# ------------------------------------------------------------------------------------ reporting


def print_report(
    *,
    stats: list[dict[str, Any]],
    records: list[dict[str, Any]],
    pages: int,
    archive_path: Path,
    archive_sha: str,
    dry_run: bool,
    db_counts: dict[str, int] | None,
    database_total: int | None,
    limit: int | None,
) -> None:
    cards = sum(s["cards"] for s in stats)
    malformed = sum(s["malformed"] for s in stats)
    missing = sum(s["missing_nrn"] for s in stats)
    labelled = cards - malformed - missing
    print("\n--- nafdac greenbook index ---")
    print(f"category pages fetched   {pages}  (+1 categories page, +1 robots.txt)")
    print(f"cards seen               {cards}")
    print(f"malformed cards          {malformed}")
    print(f"cards with no NRN value  {missing}")
    print(f"NRN labels parsed        {labelled}")
    print(f"unique registrations     {len(records)}")
    print(f"duplicates collapsed     {labelled - len(records)}")
    print(f"parse rate               {labelled / cards:.2%} of cards carry a usable NRN")
    if limit is not None:
        print(f"limit applied            {limit}")
    coverage = [r for r in records if r["product_name"] and r["dosage_form"] and r["strength"]]
    print(f"name+form+strength set   {len(coverage)} ({len(coverage) / len(records):.2%})")
    print(f"archive                  {archive_path}")
    print(f"archive sha256           {archive_sha}")
    if dry_run:
        print("database                 not touched (--dry-run)")
    elif db_counts is not None:
        print(f"registrations upserted   inserted={db_counts['inserted']} updated={db_counts['updated']}")
        print(f"nafdac_registrations     {database_total}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape the NAFDAC Greenbook index (6 category pages) into nafdac_registrations."
    )
    parser.add_argument("--dry-run", action="store_true", help="parse and report without touching the database")
    parser.add_argument("--limit", type=int, metavar="N", help="stop after N unique registrations (smoke test)")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")

    run_started = datetime.now(timezone.utc).replace(microsecond=0)
    connection = None
    run_id: int | None = None
    try:
        if not args.dry_run:
            connection = db_connect()
            run_id = start_run(connection, SOURCE)
            print(f"scrape_runs: run_id={run_id} status=running source={SOURCE}")

        client = RateLimitedClient()
        categories = discover_categories(client)
        print(
            f"discovered {len(categories)} categories: "
            + ", ".join(f"{c['category_id']}={c['category_name'] or '?'}" for c in categories)
        )
        if len(categories) != len(EXPECTED_CATEGORY_IDS):
            print(
                f"WARNING: expected {len(EXPECTED_CATEGORY_IDS)} categories, found {len(categories)}",
                file=sys.stderr,
            )

        records, stats, pages = collect(client, categories, limit=args.limit)
        if not records:
            raise RuntimeError("no registrations parsed; refusing to record an empty success")

        archive_path, archive_sha = archive_jsonl(ARCHIVE_SOURCE, records, when=run_started)
        print(f"archived {len(records)} records -> {archive_path}")

        db_counts = None
        database_total = None
        if connection is not None:
            db_counts = store_records(connection, records, scraped_at=run_started)
            with connection.cursor() as cursor:
                cursor.execute("select count(*) from nafdac_registrations")
                database_total = cursor.fetchone()[0]
            finish_run(
                connection, run_id, status="success", record_count=len(records)
            )

        print_report(
            stats=stats,
            records=records,
            pages=pages,
            archive_path=archive_path,
            archive_sha=archive_sha,
            dry_run=args.dry_run,
            db_counts=db_counts,
            database_total=database_total,
            limit=args.limit,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - a failed run must still be recorded
        if connection is not None and run_id is not None:
            try:
                finish_run(
                    connection,
                    run_id,
                    status="failed",
                    record_count=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            except Exception as ledger_exc:  # noqa: BLE001
                print(f"WARNING: could not record failure: {ledger_exc}", file=sys.stderr)
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
