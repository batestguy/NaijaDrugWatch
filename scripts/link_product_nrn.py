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

WHAT IT WRITES
    products.nafdac_registration_number   one registration per product, ranked Active first
    scrape_runs                           one row per run, `success` or `failed`,
                                          source='link_product_nrn'

    The ledger row exists because `v_pipeline_health` reads `scrape_runs`: a step that fails without
    leaving a row is a step nobody can see fail. `--dry-run` writes none.

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

from common import db_connect, ensure_connection, finish_run, start_run  # noqa: E402

DEFAULT_MIN_SIMILARITY = 0.45
CANDIDATES_PER_PRODUCT = 20

# The `scrape_runs.source` value. Not a required source in scripts/freshness_gate.py (a night that
# fails here still leaves the views correct, just with fewer suspicious rows), but the row must
# exist: v_pipeline_health reads this table, and a step that leaves no record cannot be seen to fail.
SOURCE = "link_product_nrn"

# -------------------------------------------------------------- normalisation

# A strength is a number, and a slash pair is TWO numbers sharing the unit that follows: the shops
# write `AMATEM 20/120MG` for artemether 20 mg / lumefantrine 120 mg, and the register writes
# `20 mg; 120 mg`. Reading the pair as one number silently dropped the first component -- `20` has no
# unit after it -- so the token set was {120 mg} against the register's {20 mg, 120 mg} and rule 2
# rejected the pair. The number group therefore collects `A/B/...` and the loop below splits it.
STRENGTH_TOKEN_RE = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)*)\s*([a-z]+(?:\s*/\s*[a-z]+)?)"
)
STRENGTH_PAIR_SPLIT_RE = re.compile(r"\s*/\s*")


def strength_tokens(value: str | None) -> frozenset[tuple[str, str]] | None:
    """Numeric strength as an order-insensitive token set: '60mg+30mg' == '30 mg; 60 mg'.

    A slash pair sharing a unit is two tokens: '20/120MG' == '20 mg; 120 mg'. Keep that in mind
    before widening the pattern -- a slash is not always a combination. `250/5 SUSP` means 250 mg
    per 5 ml and `30/70` is an insulin ratio; neither is a pair of strengths, and both are asserted
    against in SELF_TEST_CASES below.
    """
    if not value:
        return None
    text = value.lower().replace("µg", "mcg").replace("ug", "mcg")
    tokens: set[tuple[str, str]] = set()
    for numbers, unit in STRENGTH_TOKEN_RE.findall(text):
        unit = re.sub(r"\s+", "", unit)
        for number in STRENGTH_PAIR_SPLIT_RE.split(numbers):
            try:
                amount = Decimal(number.replace(",", ".")).normalize()
            except InvalidOperation:
                continue
            tokens.add((str(amount), unit))
    return frozenset(tokens) or None


# ---------------------------------------------------------------- self test
#
# Run with `python scripts/link_product_nrn.py --self-test`. No database, no network, nothing
# written: it exercises the parsers and `choose()` against a fixture table and exits non-zero if a
# fixture disagrees. It exists because the slash-strength rule is the whole reason a pair of
# first-line antimalarials was being rejected, and a rule that decides what links needs a check that
# fails loudly when it is edited. A pair that compares equal today must still compare equal unless
# the table says otherwise, and the table says so in writing.

# (product strength, register strength, must the token sets be equal?, why this row exists)
SELF_TEST_CASES: list[tuple[str, str | None, bool, str]] = [
    # -- the defect this ticket fixes: a slash pair is a combination, not one strength
    ("20/120MG", "20 mg; 120 mg", True, "AMATEM -- the reported case"),
    ("80/480MG", "80 mg; 480 mg", True, "COARTEM -- first-line antimalarial"),
    ("500/125MG", "500 mg; 125 mg", True, "amoxicillin/clavulanate shape"),
    ("100/12.5MG", "100 mg; 12.5 mg", True, "decimal in the second component"),
    ("20/120 mg", "20 mg; 120 mg", True, "space before the unit, no space at the slash"),
    ("100/12,5MG", "100 mg; 12.5 mg", True, "comma decimal in the second component"),
    ("80/480MG", "480 mg; 80 mg", True, "order-insensitive, as rule 2 requires"),
    # -- must not regress: these already compare equal
    ("60mg+30mg", "30 mg; 60 mg", True, "plus-separated pair, order-insensitive"),
    ("500MG", "500 mg", True, "one plain strength"),
    ("80MG/480MG", "80 mg; 480 mg", True, "unit repeated on both sides -- one token each, already"),
    ("500MG/5ML", "500 mg; 5 ml", True, "a concentration, already two tokens -- must stay two"),
    ("1/2 TAB", "2 TAB", False, "a half-tablet dose must not equal a two-tablet one -- it does today"),
    # -- must NOT become equal: the wrong-link direction
    ("20/120MG", "20 mg", False, "a combination is not one of its components"),
    ("80/480MG", "480 mg", False, "the component-only register row must not win"),
    ("5/5", "5 mg", False, "no unit after the pair: not a strength at all"),
    ("30/70", "30 mg; 70 mg", False, "an insulin ratio with no unit -- must not invent mg"),
    ("250/5 SUSP", "250 mg; 5 ml", False, "'per 5 ml' is a concentration, not two strengths"),
    ("500MG", "250 mg", False, "plain different strengths never match"),
]

# (label, product side, candidate strengths, must `choose()` return a registration?)
SELF_TEST_CHOOSE_CASES: list[tuple[str, dict, list[str], bool]] = [
    ("slash strength vs semicolon register", {"form": "tablet", "strength": "20/120MG"}, ["20 mg; 120 mg"], True),
    ("plain strength, passes today", {"form": "tablet", "strength": "500MG"}, ["500 mg"], True),
    ("combination vs a component-only register row", {"form": "tablet", "strength": "80/480MG"}, ["480 mg"], False),
    ("plain strength vs a different strength", {"form": "tablet", "strength": "500MG"}, ["250 mg"], False),
]


def _format_tokens(tokens: frozenset[tuple[str, str]] | None) -> str:
    if not tokens:
        return "(none)"
    return "{" + ", ".join(f"{amount} {unit}" for amount, unit in sorted(tokens)) + "}"


def run_self_test() -> int:
    """Print the fixture table with real parser output. Returns 0 when every row agrees."""
    failures = 0
    print(f"{'product strength':<20} {'register strength':<20} {'equal':<6} {'want':<5} {'result':<7} why")
    print("-" * 118)
    for product_strength, reg_strength, want_equal, why in SELF_TEST_CASES:
        product_tokens = strength_tokens(product_strength)
        reg_tokens = strength_tokens(reg_strength)
        got_equal = product_tokens == reg_tokens
        ok = got_equal == want_equal
        failures += 0 if ok else 1
        print(
            f"{product_strength:<20} {str(reg_strength):<20} {str(got_equal):<6} "
            f"{str(want_equal):<5} {'PASS' if ok else 'FAIL':<7} {why}"
        )
        print(f"{'':<20} {_format_tokens(product_tokens):<48} | {_format_tokens(reg_tokens)}")
    print(f"\nstrength fixtures: {len(SELF_TEST_CASES) - failures}/{len(SELF_TEST_CASES)} pass")

    print("\n--- choose() verdicts (one candidate each) ---")
    choose_failures = 0
    for label, product, strengths, must_link in SELF_TEST_CHOOSE_CASES:
        candidates = [
            {
                "registration_number": f"TEST-{index}",
                "product_name": "TEST",
                "dosage_form": "Tablet",
                "strength": strength,
                "status": "Active",
                "expiry_date": None,
                "sim": 0.80,
            }
            for index, strength in enumerate(strengths)
        ]
        chosen, reason = choose({"canonical_name": "TEST", **product}, candidates)
        got_link = chosen is not None
        ok = got_link == must_link
        choose_failures += 0 if ok else 1
        verdict = f"linked {chosen['registration_number']}" if chosen else "rejected"
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<48} want={'link' if must_link else 'reject':<6} {verdict:<16} ({reason})")
    print(f"\nchoose fixtures: {len(SELF_TEST_CHOOSE_CASES) - choose_failures}/{len(SELF_TEST_CHOOSE_CASES)} pass")

    total_failures = failures + choose_failures
    print(f"\nself test: {'FAILED' if total_failures else 'OK'} ({total_failures} failing)")
    return 1 if total_failures else 0


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
    parser.add_argument("--self-test", action="store_true", help="run the parser fixtures, no database")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    connection = None
    run_id = None
    linked: list[tuple[str, str, str, str | None]] = []
    unmatched: dict[str, int] = {}

    try:
        connection = db_connect()
        # A dry run writes no ledger row: it wrote no links, and `success` for it would be a claim
        # about a pipeline step that did not happen. A real run records one on success and failure.
        if not args.dry_run:
            run_id = start_run(connection, SOURCE)
            print(f"scrape_runs id={run_id} status=running source={SOURCE}")

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

        if run_id is not None:
            # `record_count` is products linked, not products considered: a run that read 1,074 and
            # linked 278 says 278, so the number cannot be mistaken for work that did not happen.
            connection = ensure_connection(connection)
            finish_run(connection, run_id, status="success", record_count=len(linked))
            print(f"scrape_runs id={run_id} status=success record_count={len(linked)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if run_id is not None:
            try:
                finish_run(connection or db_connect(), run_id, status="failed", record_count=len(linked) or None, error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                # The socket is often what died; try a fresh one before leaving the run 'running'.
                try:
                    finish_run(db_connect(), run_id, status="failed", record_count=len(linked) or None, error=message)
                    print(f"scrape_runs id={run_id} status=failed (reconnected)", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
