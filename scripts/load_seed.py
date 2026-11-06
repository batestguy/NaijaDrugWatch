#!/usr/bin/env python3
"""Load the #FixMedPrices catalogue into `products` and `drug_match_rules`.

Source: openAFRICA "Medicine Prices" (Code for Nigeria, #FixMedPrices), CC-BY-4.0.
Vendored at seed/medprices.csv so the build does not depend on a live download.

What this file IS used for
--------------------------
`products`      canonical drug name + strength + form, with the CSV's brand aliases.
`drug_match_rules`  one rule per (name, strength, form): the deterministic stage two of the
                    matcher, applied after pgvector proposes candidates.

What it is NOT used for
-----------------------
`nafdac_registrations`. The CSV has no NRN, no status and no expiry, so it cannot seed the
regulatory layer - that comes from the Greenbook scraper.

`price_history`. The CSV's `price` column is a unit reference price (values like 0.0197,
spanning 0.0007-1877 across mixed units), not an NGN retail price. Loading it would poison
the index and make every "cheapest" claim wrong. Do not do it.

Usage
-----
    python scripts/load_seed.py --dry-run      # print SQL, no database needed
    python scripts/load_seed.py                # upsert into DATABASE_URL
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "seed" / "medprices.csv"
BATCH_SIZE = 500


# ---------------------------------------------------------------- normalisation

def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalise(value: str | None) -> str | None:
    """Collapse whitespace and drop accents so 'Paracétamol' == 'Paracetamol'."""
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", strip_accents(value)).strip()
    return cleaned or None


def sql_literal(value: str | None) -> str:
    if value is None:
        return "null"
    return "'" + value.replace("'", "''") + "'"


def sql_array(values: list[str]) -> str:
    if not values:
        return "null"
    return "array[" + ", ".join(sql_literal(v) for v in values) + "]::text[]"


# ---------------------------------------------------------------------- reading

def read_rows(csv_path: Path) -> Iterator[dict[str, str]]:
    """Yield rows keyed by header, tolerating the 88 brand_names/N columns."""
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("name") or "").strip():
                yield row


def brand_columns(fieldnames: Iterable[str]) -> list[str]:
    columns = [name for name in fieldnames if name.startswith("brand_names/")]
    # brand_names/10 sorts before brand_names/2 as text; order numerically for stable output.
    return sorted(columns, key=lambda c: int(c.split("/", 1)[1]))


# ---------------------------------------------------------------------- mapping

def build_records(csv_path: Path) -> tuple[list[dict], list[dict], int]:
    """Return (products, match_rules, skipped)."""
    products: list[dict] = []
    rules: list[dict] = []
    skipped = 0
    seen_products: set[tuple] = set()
    seen_rules: set[tuple] = set()

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        cols = brand_columns(reader.fieldnames or [])
        all_rows = list(reader)

    for row in all_rows:
        name = normalise(row.get("name"))
        if not name:
            skipped += 1
            continue

        strength = normalise(row.get("strength"))
        form = normalise(row.get("form"))

        brands: list[str] = []
        for column in cols:
            alias = normalise(row.get(column))
            if alias and alias not in brands:
                brands.append(alias)

        product_key = (name.lower(), (strength or "").lower(), (form or "").lower())
        if product_key not in seen_products:
            seen_products.add(product_key)
            products.append(
                {
                    "canonical_name": name,
                    "brand_name": brands[0] if brands else None,
                    "brand_aliases": brands,
                    "form": form,
                    "strength": strength,
                }
            )

        rule_key = product_key
        if rule_key not in seen_rules:
            seen_rules.add(rule_key)
            rules.append(
                {
                    "canonical_name": name,
                    # Stored as the plain name; the matcher wraps it in %...% for ILIKE.
                    "match_pattern": name,
                    "required_strength": strength,
                    "required_form": form,
                    "active_ingredient": name,
                }
            )

    return products, rules, skipped


# ----------------------------------------------------------------------- SQL

def products_sql(products: list[dict]) -> Iterator[str]:
    for start in range(0, len(products), BATCH_SIZE):
        batch = products[start : start + BATCH_SIZE]
        values = ",\n    ".join(
            "({}, {}, {}, {}, {})".format(
                sql_literal(p["canonical_name"]),
                sql_literal(p["brand_name"]),
                sql_array(p["brand_aliases"]),
                sql_literal(p["form"]),
                sql_literal(p["strength"]),
            )
            for p in batch
        )
        yield (
            "insert into products (canonical_name, brand_name, brand_aliases, form, strength) values\n"
            f"    {values}\n"
            "on conflict do nothing;"
        )


def rules_sql(rules: list[dict]) -> Iterator[str]:
    for start in range(0, len(rules), BATCH_SIZE):
        batch = rules[start : start + BATCH_SIZE]
        values = ",\n    ".join(
            "({}, {}, {}, {}, {}, {})".format(
                sql_literal(r["canonical_name"]),
                sql_literal(r["match_pattern"]),
                sql_literal(r["required_strength"]),
                sql_literal(r["required_form"]),
                sql_literal(r["active_ingredient"]),
                100,
            )
            for r in batch
        )
        yield (
            "insert into drug_match_rules "
            "(canonical_name, match_pattern, required_strength, required_form, active_ingredient, priority) values\n"
            f"    {values}\n"
            "on conflict do nothing;"
        )


# ----------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="path to medprices.csv")
    parser.add_argument("--dry-run", action="store_true", help="print SQL to stdout, no database")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"error: CSV not found at {args.csv}", file=sys.stderr)
        return 2

    products, rules, skipped = build_records(args.csv)
    statements = list(products_sql(products)) + list(rules_sql(rules))

    summary = (
        f"products={len(products)} match_rules={len(rules)} skipped={skipped} "
        f"statements={len(statements)} source={args.csv.name}"
    )

    if args.dry_run:
        print("-- generated by scripts/load_seed.py --dry-run", file=sys.stderr)
        print(f"-- {summary}", file=sys.stderr)
        for statement in statements:
            print(statement)
        return 0

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "error: DATABASE_URL is not set. Put the Neon connection string in .env "
            "(never commit it) or pass it in the environment.",
            file=sys.stderr,
        )
        return 2

    import psycopg  # imported lazily so --dry-run works without the driver installed

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()

    print(f"loaded {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
