#!/usr/bin/env python3
"""Stage-one candidate generation plus stage-two deterministic filtering, in that order.

    stage 1  cosine similarity: top-N products by embedding proximity to the listing title
    stage 2  drug_match_rules: the title must contain the drug name, the stated strength and a
             compatible dosage form, or the candidate is rejected

Similarity alone never assigns a product. A listing promoted by cosine but rejected by its rule
stays unmatched, which is the point: a matcher that over-matches manufactures the "suspicious"
headline.

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
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scrapers"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from common import db_connect, ensure_connection, finish_run, start_run  # noqa: E402
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
        return [
            {
                "id": row[0],
                "canonical_name": row[1],
                "form_families": form_families(row[2]),
                "strength": strength_tokens(row[3]),
                "vector": parse_vector(row[4]),
            }
            for row in cursor.fetchall()
        ]


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


# ----------------------------------------------------------------------------- matching


def match_all(vectors: np.ndarray, products: list[dict], rules_by_name: dict) -> tuple[list, dict]:
    """Return (assignments, rejection_reasons). assignments is [(listing_index, product_id, note)]."""
    matrix = np.stack([p["vector"] for p in products])
    matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
    listing_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    similarity = listing_vectors @ matrix.T  # (listings, products)

    assignments: list[tuple[int, int, str]] = []
    reasons: dict[str, int] = {"no products": 0, "stage-two rejected all candidates": 0}
    for index in range(similarity.shape[0]):
        row = similarity[index]
        top = np.argpartition(-row, min(TOP_N, len(row) - 1))[:TOP_N]
        top = top[np.argsort(-row[top])]
        yield_candidate = None
        for product_index in top:
            product = products[product_index]
            for rule in rules_by_name.get(product["canonical_name"], []):
                if rule_accepts(rule, WORDS_CACHE[index], STRENGTH_CACHE[index], FORMS_CACHE[index]):
                    if yield_candidate is None:
                        yield_candidate = (product, rule, float(row[product_index]))
                    break
        if yield_candidate is None:
            reasons["stage-two rejected all candidates"] += 1
        else:
            product, rule, sim = yield_candidate
            assignments.append(
                (index, product["id"], f"{product['canonical_name']} (sim {sim:.3f}, priority {rule['priority']})")
            )
    return assignments, reasons


WORDS_CACHE: list[frozenset[str]] = []
STRENGTH_CACHE: list = []
FORMS_CACHE: list[frozenset[str]] = []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Two-stage listing matcher.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--embed-only", action="store_true")
    parser.add_argument("--reembed", action="store_true")
    args = parser.parse_args(argv)

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

        global WORDS_CACHE, STRENGTH_CACHE, FORMS_CACHE
        WORDS_CACHE = [title_words(l["raw_title"]) for l in listings]
        STRENGTH_CACHE = [strength_tokens(l["raw_title"]) for l in listings]
        FORMS_CACHE = [form_families(l["raw_title"]) for l in listings]

        vectors = np.array(embed_texts(model, [l["raw_title"] for l in listings]), dtype=np.float32) if listings else np.zeros((0, EMBED_DIM), dtype=np.float32)
        assignments, reasons = match_all(vectors, products, rules_by_name)
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
