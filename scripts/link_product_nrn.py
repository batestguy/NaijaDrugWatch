#!/usr/bin/env python3
"""Attach a NAFDAC registration to each seeded product, deterministically.

Why this exists: `v_suspicious_listings` joins

    listing -> products.subject -> products.nafdac_registration_number -> nafdac_registrations

and the middle column was NULL for every row, so the view could never return anything however
good the scrapers were. This fills it. It is NOT the listing matcher (P5): no embeddings, no
`drug_match_rules`, and it does not touch `pharmacy_listings`.

THE MODELLING LIMIT, STATED PLAINLY
-----------------------------------
`products.nafdac_registration_number` is a single foreign key, but one canonical product has many
registrations -- that is what the 88 brand aliases per drug mean. This script therefore picks ONE,
ranked Active first. Consequence: `v_suspicious_listings` flags a product only when **no Active
candidate exists**, not when one of its several registrations is inactive. That is the conservative
reading: we never call a drug suspicious while a valid registration is on file.

Selection rules, all deterministic:
    1. name similarity above a floor (candidate generation only)
    2. strength must match when both sides state one (numeric tokens, order-insensitive)
    3. dosage form families must intersect when both sides map to a known family
    4. rank: Active > future expiry > higher similarity

Usage
-----
    python scripts/link_product_nrn.py --dry-run
    python scripts/link_product_nrn.py --limit 50
    python scripts/link_product_nrn.py                 # all products
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scrapers"))

from common import db_connect  # noqa: E402

DEFAULT_MIN_SIMILARITY = 0.45
CANDIDATES_PER_PRODUCT = 20

# -------------------------------------------------------------- normalisation

STRENGTH_TOKEN_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-z]+(?:\s*/\s*[a-z]+)?)")


def strength_tokens(value: str | None) -> frozenset[tuple[str, str]] | None:
    """Numeric strength as an order-insensitive token set: '60mg+30mg' == '30 mg; 60 mg'."""
    if not value:
        return None
    text = value.lower().replace("µg", "mcg").replace("ug", "mcg")
    tokens: set[tuple[str, str]] = set()
    for number, unit in STRENGTH_TOKEN_RE.findall(text):
        try:
            amount = Decimal(number.replace(",", ".")).normalize()
        except InvalidOperation:
            continue
        unit = re.sub(r"\s+", "", unit)
        tokens.add((str(amount), unit))
    return frozenset(tokens) or None


# Dosage-form families. Order matters: ophthalmic before oral liquid, so "eye drops" does not
# become a syrup. "tab-cap" is a seeded category that covers both tablets and capsules.
FORM_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("ophthalmic", ("ophth", "eye drop", "eye-drop", "eyedrop")),
    ("inhaler", ("inhal", "aerosol", "spray", "nebuli")),
    ("suppository", ("suppos",)),
    ("topical", ("cream", "ointment", "gel", "lotion", "balm", "liniment")),
    ("tablet", ("tablet", "tab ", "tab-", "tabcap", "tab-cap", "caplet", "chewable")),
    ("capsule", ("capsule", "cap ", "softgel", "soft gel")),
    ("injection", ("inject", "vial", "ampoule", "ampul", "infusion", "iv ", "i.v.")),
    ("oral_liquid", ("syrup", "susp", "solu", "elixir", "drops", "drop ", "oral liquid")),
    ("powder", ("powder", "granule", "sachet")),
    ("device", ("device", "glove", "pad", "diaper", "sanitary", "syringe", "needle", "test")),
]


def form_families(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    text = f" {value.lower().strip()} "
    found = {family for family, keys in FORM_FAMILIES if any(key in text for key in keys)}
    # The seed's "tab-cap" is one category covering both tablets and capsules, so it must be
    # compatible with either; leaving it as tablet-only would reject every capsule registration.
    if "tab-cap" in text or "tabcap" in text:
        found |= {"tablet", "capsule"}
    return frozenset(found)


def compatible(product_form: frozenset[str], reg_form: frozenset[str]) -> bool:
    """True unless both sides map to known families and those families are disjoint."""
    if not product_form or not reg_form:
        return True
    return bool(product_form & reg_form)


# ------------------------------------------------------------------- database


CANDIDATE_SQL = """
select registration_number, product_name, dosage_form, strength, status, expiry_date,
       similarity(%s, product_name) as sim
from nafdac_registrations
where similarity(%s, product_name) > %s
order by sim desc
limit %s
"""


def fetch_candidates(connection, name: str, floor: float) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(CANDIDATE_SQL, (name, name, floor, CANDIDATES_PER_PRODUCT))
        rows = cursor.fetchall()
    return [
        {
            "registration_number": row[0],
            "product_name": row[1],
            "dosage_form": row[2],
            "strength": row[3],
            "status": row[4],
            "expiry_date": row[5],
            "sim": float(row[6]),
        }
        for row in rows
    ]


def choose(product: dict, candidates: list[dict]) -> tuple[dict | None, str]:
    """Pick one registration, or explain why none qualifies."""
    product_form = form_families(product["form"])
    product_strength = strength_tokens(product["strength"])

    qualified: list[dict] = []
    strength_mismatch = form_mismatch = 0
    for candidate in candidates:
        reg_strength = strength_tokens(candidate["strength"])
        if product_strength and reg_strength and product_strength != reg_strength:
            strength_mismatch += 1
            continue
        if not compatible(product_form, form_families(candidate["dosage_form"])):
            form_mismatch += 1
            continue
        qualified.append(candidate)

    if not qualified:
        if strength_mismatch or form_mismatch:
            return None, f"no candidate survived strength/form ({strength_mismatch} strength, {form_mismatch} form)"
        return None, "no candidate"

    qualified.sort(
        key=lambda c: (
            c["status"] != "Active",           # Active first
            c["status"] is None,               # then a known status before an unscraped one
            c["expiry_date"] is None,          # dated before undated
            -(c["expiry_date"].toordinal()) if c["expiry_date"] else 0,
            -c["sim"],
        )
    )
    chosen = qualified[0]
    reason = "active" if chosen["status"] == "Active" else f"best available ({chosen['status']})"
    return chosen, f"{reason}, {len(qualified)} qualified of {len(candidates)}"


UPDATE_SQL = "update products set nafdac_registration_number = %s where id = %s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Link products to a NAFDAC registration.")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    parser.add_argument("--refresh", action="store_true", help="re-link products that already have an NRN")
    args = parser.parse_args(argv)

    connection = db_connect()
    sql = "select id, canonical_name, form, strength from products"
    if not args.refresh:
        sql += " where nafdac_registration_number is null"
    sql += " order by id"
    with connection.cursor() as cursor:
        cursor.execute(sql)
        products = [
            {"id": row[0], "canonical_name": row[1], "form": row[2], "strength": row[3]}
            for row in cursor.fetchall()
        ]
    if args.limit:
        products = products[: args.limit]

    linked: list[tuple[str, str, str, str | None]] = []
    unmatched: dict[str, int] = {}

    for product in products:
        candidates = fetch_candidates(connection, product["canonical_name"], args.min_similarity)
        chosen, reason = choose(product, candidates)
        if chosen is None:
            unmatched[reason] = unmatched.get(reason, 0) + 1
            continue
        linked.append(
            (product["canonical_name"], chosen["registration_number"], reason, chosen["status"])
        )
        if not args.dry_run:
            with connection.cursor() as cursor:
                cursor.execute(UPDATE_SQL, (chosen["registration_number"], product["id"]))

    if not args.dry_run:
        connection.commit()

    total = len(products)
    active = sum(1 for _, _, _, status in linked if status == "Active")
    known = sum(1 for _, _, _, status in linked if status is not None)
    print(f"\n--- link {'dry run' if args.dry_run else 'run'} ---")
    print(f"products considered  {total}")
    print(f"linked               {len(linked)} ({100.0 * len(linked) / total:.1f}%)" if total else "linked 0")
    print(f"  to Active          {active}")
    print(f"  to known non-Active{known - active:>4d}")
    print(f"  to UNVERIFIED      {len(linked) - known} (status not scraped: cannot be judged suspicious)")
    print(f"not linked           {sum(unmatched.values())}")
    for reason, count in sorted(unmatched.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  {count:4d}  {reason}")
    print("\nfirst 10 links:")
    for name, nrn, reason, status in linked[:10]:
        print(f"  {name[:30]:30s} -> {nrn:12s} [{status or 'unverified'}] ({reason})")
    if args.dry_run:
        print("\ndry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
