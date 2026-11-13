#!/usr/bin/env python3
"""Stage-one candidate generation plus stage-two deterministic filtering, in that order.

    stage 1  cosine similarity: top-N products by embedding proximity to the listing title
    stage 2  drug_match_rules: the title must contain the drug name, the stated strength and a
             compatible dosage form, or the candidate is rejected

Similarity alone never assigns a product. A listing promoted by cosine but rejected by its rule
stays unmatched, which is the point: a matcher that over-matches manufactures the "suspicious"
headline.

STRENGTH GUARD (the third check, after the rule accepted a candidate)
    Before a listing is given a `product_id`, the mass strength in its own title is compared with
    the product's. If both state one and they are not the same amount, the attach is refused, the
    listing stays unmatched, and the refusal is printed with both strengths. Without it, a title
    saying `ACICLOVIR 800MG` could be attached to the 400 mg product and a two-ingredient brand
    (`Co-Diovan 160/12.5mg`) to a product naming one ingredient.
    The parser is `strength_tokens` from scripts/link_product_nrn.py, imported not re-written.
    Units compared are mg, mcg, g and iu; grams and micrograms are normalised to milligrams, so
    `1 g` and `1000 mg` are equal. ml and litre are IGNORED on purpose: in these titles they are
    pack or bottle volume far more often than strength (`Chloramphenicol ... 70ml`), and comparing
    them would refuse correct attaches. A title with no mass strength at all is silent, not wrong,
    and is attached exactly as before.

    `--repair` is the one-off pass for links written before the guard existed: it finds listings
    whose `product_id` points at a contradicting product and clears that `product_id`. It deletes
    no listing and rewrites no price. `--repair --dry-run` counts without writing.

MODEL
    BAAI/bge-small-en-v1.5 via fastembed -- 384 dimensions, exactly the existing
    `products.embedding vector(384)` column, so no migration. ONNX, CPU, no torch, no API.

WHY THIS FILE DOES NOT QUERY PER CANDIDATE
    The first version issued ~13,000 round-trips to Neo (ten rule lookups per listing, each a
    sequential scan because drug_match_rules has only an expression index) and was killed at 30
    minutes. Products, rules and vectors are now loaded once and the cosine runs in numpy, so the
    whole catalogue matches in seconds. Keep it that way.

WHAT IT WRITES
    products.embedding            canonical_name + form + strength
    pharmacy_listings.product_id  only where a rule accepted the candidate
    scrape_runs                   one row per run, `success` or `failed`, source='match_listings'

    The ledger row is not bookkeeping for its own sake: scripts/freshness_gate.py requires a
    `match_listings` success inside the day's window before it calls the day run. A night that
    scrapes every source and dies here leaves every view a day old, which looks exactly like a
    quiet market -- so the next scheduled fire has to see it and retry. `--dry-run` and
    `--embed-only` write no row: neither matched anything.

Usage
-----
    python scripts/match_listings.py --embed-only
    python scripts/match_listings.py --limit 50 --dry-run
    python scripts/match_listings.py
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scrapers"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from common import db_connect, ensure_connection, finish_run, start_run  # noqa: E402
from envfile import ensure_database_url  # noqa: E402
from link_product_nrn import form_families, strength_tokens  # noqa: E402

MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
TOP_N = 10
EMBED_BATCH = 64

# The `scrape_runs.source` value. scripts/freshness_gate.py REQUIRES_SOURCES names this string, so
# a rename here silently makes the gate treat every day as unrun.
SOURCE = "match_listings"


def normalise(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9+/.\s]", " ", ascii_text.lower().replace("×", "x"))


def pattern_tokens(pattern: str) -> frozenset[str]:
    """Drug-name tokens a title must contain: 'Abacavir+Lamivudine' -> two tokens."""
    return frozenset(t for t in re.split(r"[^a-z0-9]+", normalise(pattern)) if t)


def title_words(title: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", normalise(title)))


# ------------------------------------------------------------------- strength guard

# Unit -> (family it is expressed in, multiplier to get there). Mass units collapse to mg, so
# `1 g` and `1000 mg` are the same amount; `iu` is its own family because it is not a mass and
# 5000 iu has no milligram equivalent. Anything absent -- ml, l, tab, cap, sachet -- is not a
# strength in these titles and is dropped rather than compared.
UNIT_TO_FAMILY: dict[str, tuple[str, Decimal]] = {
    "g": ("mg", Decimal(1000)),
    "mg": ("mg", Decimal(1)),
    "mcg": ("mg", Decimal("0.001")),
    "iu": ("iu", Decimal(1)),
}


def strength_units(tokens) -> dict[str, frozenset[Decimal]]:
    """Mass strength per unit family, normalised: '1 g' -> {'mg': {1000}}.

    Takes the output of `strength_tokens`, so there is one parser in the project, not two. A title
    carrying only volume (ml, l) or a pack count returns {}, which the caller reads as silence.
    """
    amounts: dict[str, set[Decimal]] = {}
    for amount, unit in tokens or ():
        mapped = UNIT_TO_FAMILY.get(unit)
        if mapped is None:
            continue
        family, factor = mapped
        try:
            value = (Decimal(amount) * factor).normalize()
        except InvalidOperation:
            continue
        amounts.setdefault(family, set()).add(value)
    return {family: frozenset(values) for family, values in amounts.items()}


def format_units(units: dict[str, frozenset[Decimal]]) -> str:
    if not units:
        return "(none)"
    return "; ".join(
        ", ".join(f"{amount:f} {family}" for amount in sorted(values))
        for family, values in sorted(units.items())
    )


def strength_conflict(listing_units: dict[str, frozenset[Decimal]], product_units: dict[str, frozenset[Decimal]]) -> bool:
    """True when both sides state a strength in the same unit family and the amounts differ.

    THE RULE, in one sentence: a listing may not be attached to a product whose stated strength it
    contradicts, where a strength is the set of mg (or iu) amounts the text states, and a
    contradiction is a different set in a unit family both sides use.

    Compared per family and as an exact set, never by intersection. Set equality is what refuses
    the shape that matters -- `Co-Diovan 160/12.5mg` against a product stating `160 mg` -- because
    the listing states a second amount the product does not. A title that is silent about strength
    (no mass token at all), or that states only a unit the product does not use, is NOT contradicted:
    silence and incomparability are not disagreements, and refusing them would cost correct attaches.
    """
    for family, listing_values in listing_units.items():
        product_values = product_units.get(family)
        if product_values and product_values != listing_values:
            return True
    return False


def vector_literal(values) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def parse_vector(text: str) -> np.ndarray:
    return np.fromstring(text.strip().strip("[]"), sep=",", dtype=np.float32)


def embed_texts(model, texts: list[str]) -> list[list[float]]:
    return [list(map(float, vec)) for vec in model.embed(texts, batch_size=EMBED_BATCH)]


# ---------------------------------------------------------------------------- loading


def load_products(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            "select id, canonical_name, form, strength, embedding::text"
            " from products where embedding is not null order by id"
        )
        products: list[dict] = []
        for product_id, canonical_name, form, strength, embedding in cursor.fetchall():
            tokens = strength_tokens(strength)
            products.append(
                {
                    "id": product_id,
                    "canonical_name": canonical_name,
                    "form_families": form_families(form),
                    "strength": tokens,
                    "strength_raw": strength,
                    "units": strength_units(tokens),
                    "vector": parse_vector(embedding),
                }
            )
        return products


def load_rules(connection) -> dict[str, list[dict]]:
    """All rules, precomputed once: tokens, strength set and form families per rule."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select canonical_name, match_pattern, required_strength, required_form, priority"
            " from drug_match_rules"
        )
        rules: dict[str, list[dict]] = {}
        for name, pattern, strength, form, priority in cursor.fetchall():
            rules.setdefault(name, []).append(
                {
                    "tokens": pattern_tokens(pattern),
                    "strength": strength_tokens(strength),
                    "forms": form_families(form),
                    "priority": priority,
                }
            )
    return rules


def rule_accepts(rule: dict, words: frozenset[str], strength, forms: frozenset[str]) -> bool:
    """Stage two: name tokens, strength and dosage form must all be present in the title."""
    if not rule["tokens"] or not rule["tokens"] <= words:
        return False
    if rule["strength"] is not None:
        if strength is None or not rule["strength"] <= strength:
            return False
    if rule["forms"] and forms and not (rule["forms"] & forms):
        return False
    return True


# ------------------------------------------------------------------------------- repair
#
# The guard above stops a NEW wrong link. This pass fixes the ones written before it existed, and
# it is the only write in this file that is not a match run. It clears `product_id` and touches
# nothing else: no listing deleted, no price rewritten, no materialised view refreshed (the views
# this reports are plain views and recompute by themselves).


def scoreboard(connection) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "select (select count(*) from v_latest_listings where product_id is not null),"
            "       (select count(*) from pharmacy_listings where product_id is not null),"
            "       (select count(*) from v_cheapest_per_product_state),"
            "       (select count(*) from v_cheapest_per_product_state where is_comparison)"
        )
        latest_matched, all_matched, cells, comparisons = cursor.fetchone()
    return {
        "matched listings (latest per URL)": latest_matched,
        "matched rows (all history)": all_matched,
        "cheapest-per-state cells": cells,
        "comparison cells": comparisons,
    }


def print_scoreboard(label: str, board: dict[str, int]) -> None:
    print(f"--- {label} ---")
    for key, value in board.items():
        print(f"{key:<36}{value}")


def repair_strength_conflicts(connection, dry_run: bool) -> int:
    """Clear `product_id` where it points at a product whose strength the title contradicts."""
    before = scoreboard(connection)
    print_scoreboard("before", before)

    with connection.cursor() as cursor:
        cursor.execute(
            "select l.id, l.raw_title, l.product_id, p.canonical_name, p.strength"
            " from pharmacy_listings l"
            " join products p on p.id = l.product_id"
            " where l.product_id is not null"
            " order by l.id"
        )
        rows = cursor.fetchall()

    cleared = []
    for listing_id, title, product_id, name, strength in rows:
        listing_units = strength_units(strength_tokens(title))
        product_units = strength_units(strength_tokens(strength))
        if strength_conflict(listing_units, product_units):
            cleared.append(
                (listing_id, title, product_id, name, strength, format_units(listing_units), format_units(product_units))
            )

    product_ids = sorted({row[2] for row in cleared})
    affected_cells = 0
    if product_ids:
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from v_cheapest_per_product_state"
                " where is_comparison and product_id = any(%s)",
                (product_ids,),
            )
            affected_cells = cursor.fetchone()[0]

    print(f"\nmatched rows scanned           {len(rows)}")
    print(f"contradicting rows             {len(cleared)}")
    print(f"products they point at         {len(product_ids)}")
    print(f"comparison cells they sit in   {affected_cells} (of {before['comparison cells']})")
    print("\n--- cleared ---")
    for listing_id, title, product_id, name, strength, listing_text, product_text in cleared:
        print(
            f"listing {listing_id} | old product {product_id} {name} ({strength}) "
            f"| title {title[:70]} | title strength {listing_text} vs product {product_text}"
        )

    if dry_run:
        print("\ndry run: nothing written")
        return 0
    if cleared:
        with connection.cursor() as cursor:
            cursor.executemany(
                "update pharmacy_listings set product_id = null where id = %s",
                [(row[0],) for row in cleared],
            )
        connection.commit()

    print_scoreboard("\nafter", scoreboard(connection))
    print(f"\ncleared {len(cleared)} listings; none deleted, no price rewritten")
    return 0


# ----------------------------------------------------------------------------- matching


def match_all(vectors: np.ndarray, products: list[dict], rules_by_name: dict, titles: list[str]) -> tuple[list, dict, list]:
    """Return (assignments, rejection_reasons, strength_refusals).

    assignments is [(listing_index, product_id, note)]; strength_refusals is
    [(listing_index, product, product_strength, listing_strength, product_strength_parsed,
    listing_strength_parsed)] for the attaches the guard refused.
    """
    matrix = np.stack([p["vector"] for p in products])
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    listing_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    similarity = listing_vectors @ matrix.T  # (listings, products)

    assignments: list[tuple[int, int, str]] = []
    refusals: list[tuple] = []
    reasons: dict[str, int] = {
        "no products": 0,
        "stage-two rejected all candidates": 0,
        "strength contradicts the product": 0,
    }
    for index in range(similarity.shape[0]):
        row = similarity[index]
        top = np.argpartition(-row, min(TOP_N, len(row) - 1))[:TOP_N]
        top = top[np.argsort(-row[top])]
        accepted = None
        refused = None
        for product_index in top:
            product = products[product_index]
            for rule in rules_by_name.get(product["canonical_name"], []):
                if not rule_accepts(rule, WORDS_CACHE[index], STRENGTH_CACHE[index], FORMS_CACHE[index]):
                    continue
                # The third check. The rule compared atoms; this compares amounts, because a rule
                # for `Acyclovir` accepts `400 mg` and `800 mg` alike.
                if strength_conflict(LISTING_UNITS[index], product["units"]):
                    refused = (index, product, format_units(LISTING_UNITS[index]), format_units(product["units"]))
                else:
                    accepted = (product, rule, float(row[product_index]))
                break
            if accepted is not None or refused is not None:
                break
        if refused is not None:
            # Refused, not re-routed: the listing stays unmatched for this run. Attaching it to a
            # lower-ranked product because its best candidate contradicted would trade one wrong
            # link for another kind of guess.
            reasons["strength contradicts the product"] += 1
            refusals.append(refused)
        elif accepted is None:
            reasons["stage-two rejected all candidates"] += 1
        else:
            product, rule, sim = accepted
            assignments.append(
                (index, product["id"], f"{product['canonical_name']} (sim {sim:.3f}, priority {rule['priority']})")
            )
    return assignments, reasons, refusals


WORDS_CACHE: list[frozenset[str]] = []
STRENGTH_CACHE: list = []
FORMS_CACHE: list[frozenset[str]] = []
LISTING_UNITS: list[dict[str, frozenset[Decimal]]] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Two-stage listing matcher.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--embed-only", action="store_true")
    parser.add_argument("--reembed", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="clear product_id where a listing's stated strength contradicts the product's; "
        "combine with --dry-run to count without writing",
    )
    args = parser.parse_args(argv)
    # A laptop run has no job environment variable; an already-set one always wins, so the workflow
    # secret is never overridden by a stray .env.
    ensure_database_url()

    if args.repair:
        # Before fastembed is imported: the repair never embeds anything, so it must not need the
        # model (or the ~90 MB download) to run.
        connection = None
        try:
            connection = db_connect()
            return repair_strength_conflicts(connection, args.dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    from fastembed import TextEmbedding

    connection = None
    run_id = None
    matched = 0

    try:
        connection = db_connect()
        # A dry run and an embedding-only maintenance pass write no ledger row: neither matched a
        # listing, and a `success` for either would let the freshness gate skip a night whose views
        # are a day old. A real run writes one on success AND on failure, like the scrapers do, so
        # a night that scrapes every source and then fails here is retried by the next fire.
        if not (args.dry_run or args.embed_only):
            run_id = start_run(connection, SOURCE)
            print(f"scrape_runs id={run_id} status=running source={SOURCE}")

        model = TextEmbedding(MODEL_NAME)

        embed_sql = "select id, canonical_name, form, strength from products"
        embed_sql += "" if args.reembed else " where embedding is null"
        with connection.cursor() as cursor:
            cursor.execute(embed_sql)
            product_rows = cursor.fetchall()
        if product_rows:
            texts = [f"{name} {form or ''} {strength or ''}".strip() for _, name, form, strength in product_rows]
            vectors = embed_texts(model, texts)
            with connection.cursor() as cursor:
                for (product_id, *_rest), vector in zip(product_rows, vectors):
                    cursor.execute(
                        "update products set embedding = %s::vector where id = %s",
                        (vector_literal(vector), product_id),
                    )
            connection.commit()
        print(f"products embedded    {len(product_rows)} (dim {EMBED_DIM})")
        if args.embed_only:
            return 0

        listing_sql = "select id, raw_title from pharmacy_listings where product_id is null order by id"
        if args.limit:
            listing_sql += f" limit {int(args.limit)}"
        with connection.cursor() as cursor:
            cursor.execute(listing_sql)
            listings = [{"id": row[0], "raw_title": row[1]} for row in cursor.fetchall()]

        products = load_products(connection)
        rules_by_name = load_rules(connection)
        print(f"products loaded      {len(products)} with embeddings, {sum(len(v) for v in rules_by_name.values())} rules")

        global WORDS_CACHE, STRENGTH_CACHE, FORMS_CACHE, LISTING_UNITS
        WORDS_CACHE = [title_words(l["raw_title"]) for l in listings]
        STRENGTH_CACHE = [strength_tokens(l["raw_title"]) for l in listings]
        FORMS_CACHE = [form_families(l["raw_title"]) for l in listings]
        LISTING_UNITS = [strength_units(tokens) for tokens in STRENGTH_CACHE]

        vectors = np.array(embed_texts(model, [l["raw_title"] for l in listings]), dtype=np.float32) if listings else np.zeros((0, EMBED_DIM), dtype=np.float32)
        assignments, reasons, refusals = match_all(
            vectors, products, rules_by_name, [l["raw_title"] for l in listings]
        )
        matched = len(assignments)

        if not args.dry_run and assignments:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "update pharmacy_listings set product_id = %s where id = %s",
                    [(product_id, listings[index]["id"]) for index, product_id, _ in assignments],
                )
            connection.commit()

        print(f"\n--- match {'dry run' if args.dry_run else 'run'} ---")
        print(f"listings considered  {len(listings)}")
        print(f"matched              {matched} ({100.0 * matched / len(listings):.1f}%)" if listings else "matched 0")
        print(f"unmatched            {len(listings) - matched}")
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            if count:
                print(f"  {count:4d}  {reason}")
        print("\nexamples:")
        for index, _product_id, note in assignments[:12]:
            print(f"  {listings[index]['raw_title'][:48]:48s} -> {note}")
        if refusals:
            print(f"\nrefused by the strength guard: {len(refusals)}")
            for index, product, listing_text, product_text in refusals:
                print(
                    f"  {listings[index]['raw_title'][:48]:48s} -> refused "
                    f"{product['canonical_name']} [{product_text}]: title states {listing_text}"
                )
        if args.dry_run:
            print("\ndry run: nothing written")

        if run_id is not None:
            # `record_count` is what this run matched, so a night with no new listings records 0 and
            # stays visibly distinct from a night that matched thousands. The embedding pass can
            # outlast a Neon idle timeout (AdminShutdown), which would make the ledger write itself
            # fail, so reconnect first.
            connection = ensure_connection(connection)
            finish_run(connection, run_id, status="success", record_count=matched)
            print(f"scrape_runs id={run_id} status=success record_count={matched}")
        return 0
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if run_id is not None:
            try:
                finish_run(connection or db_connect(), run_id, status="failed", record_count=matched or None, error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                # The database socket is often what died; try a fresh one before leaving the run
                # stuck at 'running', which is the one state the ledger must never keep.
                try:
                    finish_run(db_connect(), run_id, status="failed", record_count=matched or None, error=message)
                    print(f"scrape_runs id={run_id} status=failed (reconnected)", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
