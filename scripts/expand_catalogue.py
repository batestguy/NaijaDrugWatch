#!/usr/bin/env python3
"""Grow the product catalogue from the NAFDAC register, without touching anything already there.

WHY THIS EXISTS
---------------
2,779 live listings, 342 matched to a catalogue product -- one in eight. The reply the user gave was
"more products, not fresher prices": the catalogue is 1,074 products under 597 drug names and the
shops sell far more. `pharmacy_listings.product_id` is NULL for 3,428 rows because no catalogue
product corresponds to the title, not because the matcher is asleep.

This tool proposes products. It does not attach listings: `scripts/match_listings.py` does that, and
it must stay the only thing that assigns a `product_id`. Running the matcher after this tool is the
second half of the job.

THE METHOD (two stages, same shape as the matcher)
--------------------------------------------------
    stage 1  trigram similarity (the `nafdac_registrations_name_trgm_idx` index) proposes up to
             CANDIDATES_PER_TITLE register rows per distinct unmatched shop title
    stage 2  deterministic rejection, in this order, recording the first reason that fires:
               1. the register name has no distinctive token  -> no rule could be written for it
               2. the register name does not overlap the title
               3. the register row lacks a strength or a form  -> a rule with no strength/form gate
                                                                  over-matches, so it is refused
               4. both sides state a strength and they disagree
               5. both sides map to a dosage-form family and they are disjoint

Strength and form parsing are IMPORTED, not re-written: `strength_tokens`, `form_families` and
`compatible` from scripts/link_product_nrn.py, `normalise`, `title_words`, `rule_accepts`,
`load_products`, `load_rules`, `match_all` and `vector_literal` from scripts/match_listings.py. Two
parsers would drift and the drift would be invisible until a wrong product matched.

Acceptance is per PAIR (one title, one register row). Products are then one per distinct
(canonical_name, strength, form), taken from the register row of the chosen registration. Register
rows whose normalised triple already exists are skipped -- that is the dedupe the dry run reports.

WHAT A NEW PRODUCT NEEDS TO BE USEFUL
-------------------------------------
An embedding of `name + form + strength` (the same text the matcher embeds) and a
`drug_match_rules` row on the same (name, strength, form). A product with either missing exists and
matches nothing, which is the failure mode this tool is built to avoid, so the run refuses rather
than writing one.

WHAT IT WRITES
    --apply only (never the default):
        products            new rows only, with embedding and nafdac_registration_number
        drug_match_rules    one rule per new product, deduplicated in code
        scrape_runs         one row, source='expand_catalogue', success or failed

    No UPDATE, no DELETE, no re-pointing of an existing `product_id`, no change to an existing
    product's canonical_name. Those are insert-only guarantees, not conventions.

Usage
-----
    python scripts/expand_catalogue.py                     # dry run, writes nothing
    python scripts/expand_catalogue.py --min-similarity 0.5 --limit 200
    python scripts/expand_catalogue.py --apply --i-know-this-writes

    --apply without --i-know-this-writes refuses and exits 2. More than --max-new (default 2,000)
    proposals refuses and exits 3: that many means the filter is too loose, not that the run worked.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scrapers"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from common import db_connect, ensure_connection, finish_run, start_run  # noqa: E402
from link_product_nrn import choose, compatible, form_families, strength_tokens  # noqa: E402
import match_listings as ml  # noqa: E402

DEFAULT_MIN_SIMILARITY = 0.35
CANDIDATES_PER_TITLE = 8
TITLE_BATCH = 150
MAX_NEW_PRODUCTS = 2000
MODEL_NAME = ml.MODEL_NAME
EMBED_DIM = ml.EMBED_DIM
SOURCE = "expand_catalogue"
PRIORITY = 100  # the seed's priority; a new rule must not outrank a curated one

# Words that carry no drug identity. A register name is rejected when nothing but these is left,
# because `match_pattern` would then be empty and the rule could never match anything. The list is
# deliberately short: "plus", "forte", "retard" and "junior" are part of brand names here
# ("Visionace Plus", "Adalat LA"), so removing them would merge distinct products.
STOPWORDS = frozenset(
    """
    tablet tablets tab tabs tabelet tabelets capsule capsules cap caps softgel softgels
    syrup syrups suspension suspensions susp syp solution solutions elixir
    injection injections inject vial vials ampoule ampoules ampul infusion
    cream creams ointment ointments gel gels lotion lotions balm liniment
    drops drop inhaler inhalers inhalation spray sprays nebuliser nebulizer
    powder powders granule granules sachet sachets suppository suppositories
    mg ml mcg ug gm g iu ww wv
    pack packs strip strips blister blisters bottle bottles tube tubes box boxes carton cartons
    """.split()
)

# `strength_tokens` reads every number+word pair, which means a pack count leaks into the strength:
# "AMARYL 4MG * 30 TABLETS" yields {(4 mg), (30 tablets)}. A pack count is not a strength, and
# comparing the raw sets would reject that title against "Amaryl 4 mg Tablets" for containing
# "30 tablets". These units are therefore dropped before the strength comparison -- a filter over
# the existing helper's output, not a second parser.
FORM_UNITS = frozenset(
    """
    tablet tablets tab tabs capsule capsules cap caps softgel softgels
    sachet sachets lozenge lozenges drop drops spray sprays puff puffs
    patch patches piece pieces pack packs strip strips box boxes
    vial vials bottle bottles tube tubes ampoule ampoules
    suppository suppositories inhaler inhalers dose doses metered
    """.split()
)


# ------------------------------------------------------------------ normalisation


def name_tokens(text: str | None) -> list[str]:
    """Distinctive tokens of a drug name, tokenised exactly as `title_words` tokenises a title.

    The matcher's stage two asks whether every rule token appears in the title's word set, so a
    token here that can never appear there ("20/120") would make the rule unmatchable. Numbers and
    dosage-form words are therefore dropped, and '/' and '.' are split, matching `title_words`.

    Short tokens are KEPT. Dropping them turned 'M & B Vitamin C 1000 mg Tablet' into the single
    token 'vitamin', whose rule would then accept any 1000 mg vitamin product of any kind -- a loose
    rule is how a wrong listing becomes a price.
    """
    words = re.findall(r"[a-z0-9]+", ml.normalise(text or ""))
    return [w for w in words if not w.isdigit() and w not in STOPWORDS]


def display_name(raw: str | None) -> str:
    """The register's own name with scraping debris removed: '*' and '#' prefixes, stray '_', runs
    of spaces. Nothing else -- the name is the register's, not ours."""
    return " ".join((raw or "").split()).strip(" #*_.,;:-/|")


def text_key(text: str | None) -> str:
    return " ".join(ml.normalise(text or "").split())


def strength_key(value: str | None) -> str:
    """Strength as an order-insensitive token string, so '300 mg' and '300mg' collapse."""
    tokens = strength_tokens(value)
    if not tokens:
        return ""
    return ";".join(f"{amount}{unit}" for amount, unit in sorted(tokens))


def strength_core(value: str | None) -> frozenset[tuple[str, str]] | None:
    """Strength with pack counts removed: '30 tablets' is a pack size, not a potency.

    None means "this side states no strength it can compare" -- a title that only says 'x30
    tablets', or a register row whose strength is prose. The brief allows an unknown side; it is
    counted separately in the report because a product created from such a pair will match nothing.
    """
    tokens = strength_tokens(value)
    if not tokens:
        return None
    core = frozenset((amount, unit) for amount, unit in tokens if unit not in FORM_UNITS)
    return core or None


def triple_key(name: str | None, strength: str | None, form: str | None) -> tuple[str, str, str]:
    """The dedupe key: the normalised triple the brief names. Strength compares as tokens, so a
    register's '20/120 mg' and a title's '20/120MG' are the same strength, not two products."""
    return (text_key(name), strength_key(strength), text_key(form))


def name_overlaps(reg_tokens: list[str], title_words: frozenset[str]) -> bool:
    """The register's leading distinctive token must appear, plus half the rest.

    One token is too little ('Novo' inside 'Novomix'), all of them is too strict: register names
    carry parenthetical ingredients the shops do not repeat, e.g.
    'Coartem 80/480 mg Tablets (Artemether/Lumefantrine)'. Requiring the leading token and half of
    the rest keeps the brand/generic identity and tolerates the tail.

    "Leading" means the first token of three characters or more where one exists, because an
    ampersand name ('M & B Vitamin C') otherwise leads with the single letter 'm'.
    """
    if not reg_tokens:
        return False
    primary = next((token for token in reg_tokens if len(token) >= 3), reg_tokens[0])
    present = [token for token in reg_tokens if token in title_words]
    if primary not in title_words:
        return False
    return len(present) * 2 >= len(reg_tokens)


# ----------------------------------------------------------------------- database


TITLES_SQL = """
select l.raw_title,
       array_agg(l.id order by l.id) as listing_ids,
       count(*) filter (where latest.listing_id is not null) as latest_rows
from pharmacy_listings l
left join v_latest_listings latest on latest.listing_id = l.id
where l.product_id is null
group by l.raw_title
order by count(*) desc, l.raw_title
"""

# Trigram candidate generation. `%` is the operator the GIN index serves; `similarity()` in the
# ORDER BY is the rank, and `%%` is escaped because psycopg owns `%s`.
#
# The LATERAL form is one round trip for a whole batch of titles instead of one per title: 2,445
# separate queries against an EU-hosted database would be minutes of latency for no extra signal.
CANDIDATES_SQL = """
with t as (select unnest(%s::text[]) as title)
select t.title,
       c.registration_number,
       c.product_name,
       c.dosage_form,
       c.strength,
       c.status,
       c.expiry_date,
       c.sim
from t
cross join lateral (
    select r.registration_number, r.product_name, r.dosage_form, r.strength, r.status,
           r.expiry_date,
           similarity(r.product_name, t.title) as sim
    from nafdac_registrations r
    where r.product_name %% t.title
    order by similarity(r.product_name, t.title) desc
    limit %s
) c
order by t.title, c.sim desc
"""

PRODUCT_COUNT_SQL = "select count(*) from products"

PRODUCTS_SQL = """
select id, canonical_name, form, strength
from products
order by id
"""

INSERT_PRODUCT_SQL = """
insert into products (canonical_name, form, strength, nafdac_registration_number, embedding)
values (%s, %s, %s, %s, %s::vector)
on conflict do nothing
"""

INSERT_RULE_SQL = """
insert into drug_match_rules
    (canonical_name, match_pattern, required_strength, required_form, active_ingredient, priority)
values (%s, %s, %s, %s, %s, %s)
on conflict do nothing
"""


def load_titles(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(TITLES_SQL)
        return [
            {
                "title": row[0],
                "listing_ids": list(row[1]),
                "rows": len(row[1]),
                "latest_rows": int(row[2]),
            }
            for row in cursor.fetchall()
        ]


def load_candidates(connection, titles: list[str], floor: float) -> dict[str, list[dict]]:
    by_title: dict[str, list[dict]] = defaultdict(list)
    with connection.cursor() as cursor:
        cursor.execute("select set_config('pg_trgm.similarity_threshold', %s, false)", (str(floor),))
        for start in range(0, len(titles), TITLE_BATCH):
            batch = titles[start : start + TITLE_BATCH]
            cursor.execute(CANDIDATES_SQL, (batch, CANDIDATES_PER_TITLE))
            for row in cursor.fetchall():
                by_title[row[0]].append(
                    {
                        "registration_number": row[1],
                        "product_name": row[2],
                        "dosage_form": row[3],
                        "strength": row[4],
                        "status": row[5],
                        "expiry_date": row[6],
                        "sim": float(row[7]),
                    }
                )
    return by_title


# --------------------------------------------------------------- stage two, per pair


def classify(title: str, candidate: dict, cache: dict) -> str:
    """The rejection reason for one (title, register row) pair, or 'accepted'.

    Exactly one reason per pair, first failure wins, so the report's table adds up to the number of
    pairs considered. Order: name (cheapest to test), then whether a safe product can be built at
    all, then strength, then form.
    """
    reg_tokens = name_tokens(candidate["product_name"])
    if not reg_tokens:
        return "register name has no distinctive token (no rule possible)"
    if not name_overlaps(reg_tokens, cache["words"]):
        return "name does not overlap the title"
    # A rule whose required_strength or required_form is NULL imposes no gate at all, so a listing
    # of any strength or any form containing the name would match. That is the corruption this
    # ticket exists to prevent, so a register row missing either cannot become a product.
    if not candidate["strength"] or not candidate["dosage_form"]:
        return "register row lacks a strength or a form"
    reg_strength = strength_core(candidate["strength"])
    if reg_strength is None:
        return "register strength is unparseable"
    if cache["strength"] is not None and cache["strength"] != reg_strength:
        return "strength disagrees"
    if not compatible(cache["form"], form_families(candidate["dosage_form"])):
        return "dosage form incompatible"
    return "accepted"


def build_proposals(accepted: list[dict], existing_products: list[dict]) -> dict:
    """Group accepted pairs into one proposal per register triple, and measure the dedupe."""
    groups: dict[tuple[str, str, str], dict] = {}
    for pair in accepted:
        candidate = pair["candidate"]
        key = triple_key(
            display_name(candidate["product_name"]), candidate["strength"], candidate["dosage_form"]
        )
        group = groups.setdefault(key, {"registrations": {}, "titles": [], "top_sim": 0.0})
        group["titles"].append(pair["title"])
        group["top_sim"] = max(group["top_sim"], pair["sim"])
        known = group["registrations"].get(candidate["registration_number"])
        if known is None or candidate["sim"] > known["sim"]:
            group["registrations"][candidate["registration_number"]] = candidate

    existing_keys = {
        triple_key(p["canonical_name"], p["strength"], p["form"]) for p in existing_products
    }
    # Loose key for the warning only: same name and same strength, any form label. If the families
    # also intersect, the proposal is probably a product we already have under a different form
    # vocabulary -- 'tab-cap' in the seed against 'Tablets' in the register. Reported, never merged
    # silently: merging would widen the scope of a write the user has not authorised.
    loose_existing: dict[tuple[str, str], list[frozenset[str]]] = defaultdict(list)
    for product in existing_products:
        loose_existing[(text_key(product["canonical_name"]), strength_key(product["strength"]))].append(
            form_families(product["form"])
        )

    proposals: list[dict] = []
    duplicates_avoided = 0
    near_duplicates: list[dict] = []
    for key, group in groups.items():
        if key in existing_keys:
            duplicates_avoided += 1
            continue
        representative = max(group["registrations"].values(), key=lambda c: c["sim"])
        chosen, reason = choose(
            {"form": representative["dosage_form"], "strength": representative["strength"]},
            list(group["registrations"].values()),
        )
        if chosen is None:  # cannot happen: every pair was already strength/form filtered
            continue
        canonical_name = display_name(chosen["product_name"])
        tokens = name_tokens(canonical_name)
        others = loose_existing.get((text_key(canonical_name), strength_key(chosen["strength"])), [])
        families = form_families(chosen["dosage_form"])
        same_family = [f for f in others if f and families and (f & families)]
        if same_family:
            # The user's decision (2026-11-09): skip rather than create a look-alike. The register
            # calls it 'Tablet' where the seed calls it 'tab-cap', so a raw-string unique index does
            # not catch it and the same drug would be counted twice.
            near_duplicates.append(
                {
                    "name": canonical_name,
                    "strength": chosen["strength"],
                    "form": chosen["dosage_form"],
                    "titles": group["titles"],
                }
            )
            continue
        proposals.append(
            {
                "key": key,
                "canonical_name": canonical_name,
                "form": chosen["dosage_form"],
                "strength": chosen["strength"],
                "registration_number": chosen["registration_number"],
                "registration_status": chosen["status"],
                "registration_reason": reason,
                "match_pattern": " ".join(tokens),
                "rule_tokens": frozenset(ml.pattern_tokens(" ".join(tokens))),
                "rule_forms": form_families(chosen["dosage_form"]),
                "rule_strength": strength_tokens(chosen["strength"]),
                "titles": group["titles"],
                "top_sim": group["top_sim"],
                "registrations": len(group["registrations"]),
            }
        )
    proposals.sort(key=lambda p: (-len(p["titles"]), -p["top_sim"], p["canonical_name"]))
    return {
        "proposals": proposals,
        "groups": len(groups),
        "duplicates_avoided": duplicates_avoided,
        "near_duplicates": near_duplicates,
    }


# ------------------------------------------------------------------- the projection


def embed_texts(model, texts: list[str], batch: int = 64) -> np.ndarray:
    return np.array(list(model.embed(texts, batch_size=batch)), dtype=np.float32)


def project_attachments(connection, titles: list[dict], proposals: list[dict]) -> dict:
    """Which unmatched listings the real matcher would attach once the new products exist.

    Uses `match_listings.match_all` itself -- stage-one cosine over the whole product set, top-10,
    then `rule_accepts` -- rather than a lookalike, because a lookalike would measure the lookalike.
    """
    from fastembed import TextEmbedding

    existing_products = ml.load_products(connection)
    rules_by_name = ml.load_rules(connection)
    products = list(existing_products)
    for offset, proposal in enumerate(proposals):
        products.append(
            {
                "id": -(offset + 1),  # negative: cannot collide with a real product id
                "canonical_name": proposal["canonical_name"],
                "form_families": proposal["rule_forms"],
                "strength": proposal["rule_strength"],
                "vector": None,
            }
        )

    model = TextEmbedding(MODEL_NAME)
    started = time.time()
    texts = [row["title"] for row in titles]
    vectors = embed_texts(model, texts)
    proposal_vectors = embed_texts(
        model, [f"{p['canonical_name']} {p['form'] or ''} {p['strength'] or ''}".strip() for p in proposals]
        if proposals
        else []
    )
    for offset, vector in enumerate(proposal_vectors):
        products[len(existing_products) + offset]["vector"] = vector

    for offset, proposal in enumerate(proposals):
        rules_by_name.setdefault(proposal["canonical_name"], []).append(
            {
                "tokens": proposal["rule_tokens"],
                "strength": proposal["rule_strength"],
                "forms": proposal["rule_forms"],
                "priority": PRIORITY,
            }
        )

    ml.WORDS_CACHE = [ml.title_words(row["title"]) for row in titles]
    ml.STRENGTH_CACHE = [strength_tokens(row["title"]) for row in titles]
    ml.FORMS_CACHE = [form_families(row["title"]) for row in titles]

    assignments, reasons = ml.match_all(vectors, products, rules_by_name)

    attached_new_rows = attached_new_latest = attached_existing = 0
    per_product: Counter = Counter()
    attached_by_title: dict[str, int] = {}
    for index, product_id, _note in assignments:
        row = titles[index]
        if product_id < 0:
            proposal = proposals[-product_id - 1]
            attached_new_rows += row["rows"]
            attached_new_latest += row["latest_rows"]
            per_product[proposal["canonical_name"]] += row["rows"]
            attached_by_title[row["title"]] = row["rows"]
        else:
            attached_existing += row["rows"]
    return {
        "rows": attached_new_rows,
        "latest_rows": attached_new_latest,
        "existing": attached_existing,
        "reasons": reasons,
        "per_product": per_product,
        "titles": len(attached_by_title),
        "seconds": time.time() - started,
        "proposal_vectors": proposal_vectors,
    }


def project_stage_two_only(titles: list[dict], proposals: list[dict]) -> dict:
    """Upper bound when the embedding model is unavailable: stage two over every proposal rule.

    This over-counts, because the real matcher only considers the top-10 products by cosine. It is
    reported as an upper bound and labelled as one.
    """
    rows = latest = matched_titles = 0
    per_product: Counter = Counter()
    for row in titles:
        words = ml.title_words(row["title"])
        strength = strength_tokens(row["title"])
        forms = form_families(row["title"])
        for proposal in proposals:
            rule = {
                "tokens": proposal["rule_tokens"],
                "strength": proposal["rule_strength"],
                "forms": proposal["rule_forms"],
                "priority": PRIORITY,
            }
            if ml.rule_accepts(rule, words, strength, forms):
                rows += row["rows"]
                latest += row["latest_rows"]
                matched_titles += 1
                per_product[proposal["canonical_name"]] += row["rows"]
                break
    return {
        "rows": rows,
        "latest_rows": latest,
        "existing": 0,
        "reasons": {},
        "per_product": per_product,
        "titles": matched_titles,
        "seconds": 0.0,
        "proposal_vectors": None,
    }


# --------------------------------------------------------------------------- report


def print_pairs(reasons: Counter, pairs: int, unknown_strength_titles: int) -> None:
    print("\n1. candidate pairs (one shop title + one register row)")
    print(f"   pairs considered {pairs:,}")
    print("   rejection reason                     count    share")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"   {reason:34s} {count:8,d}   {100.0 * count / pairs:5.1f}%")
    print(f"   {'TOTAL':34s} {sum(reasons.values()):8,d}")
    if sum(reasons.values()) != pairs:
        print("   !! the reasons do not sum to the pairs considered -- report is wrong")
    print(f"   accepted pairs whose title states no strength: {unknown_strength_titles:,}"
          " (stage two will refuse these: no strength in the title, so no equality test passes)")


def print_examples(accepted: list[dict], near: list[dict]) -> None:
    print("\n5. 20 accepted examples (title -> register name -> product name / strength / form)")
    for pair in accepted[:20]:
        candidate = pair["candidate"]
        print(
            f"   {pair['sim']:.2f}  {pair['title'][:44]:44s} -> "
            f"{candidate['product_name'][:38]:38s} -> "
            f"{display_name(candidate['product_name'])[:34]:34s} | "
            f"{candidate['strength'] or '-':12s} | {candidate['dosage_form'] or '-'}"
        )
    print("\n6. 20 rejections that came close (high similarity, failed strength or form)")
    if not near:
        print("   none above the similarity floor")
    for pair in near[:20]:
        candidate = pair["candidate"]
        print(
            f"   {pair['sim']:.2f}  {pair['title'][:44]:44s} -> "
            f"{candidate['product_name'][:38]:38s} [{pair['reason']}: "
            f"{candidate['strength'] or '-'} / {candidate['dosage_form'] or '-'}]"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Propose new catalogue products from the NAFDAC register. Dry run by default."
    )
    parser.add_argument("--dry-run", action="store_true", help="the default; stated so it can be typed")
    parser.add_argument("--apply", action="store_true", help="insert the products and rules")
    parser.add_argument(
        "--i-know-this-writes",
        action="store_true",
        help="required with --apply: the write is the user's decision, not the tool's default",
    )
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY)
    parser.add_argument("--max-new", type=int, default=MAX_NEW_PRODUCTS)
    parser.add_argument("--limit", type=int, default=None, help="only the N most-unmatched titles")
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="skip stage one and report a stage-two upper bound (no model needed)",
    )
    args = parser.parse_args(argv)

    if args.apply and not args.i_know_this_writes:
        print(
            "refused: --apply needs --i-know-this-writes. Inserting products is a catalogue change\n"
            "the user authorises, not a default. Run without flags to see the dry-run report.",
            file=sys.stderr,
        )
        return 2
    if args.apply and args.dry_run:
        print("refused: --apply and --dry-run contradict each other", file=sys.stderr)
        return 2

    connection = None
    run_id = None
    inserted_products = inserted_rules = 0
    try:
        connection = db_connect()
        with connection.cursor() as cursor:
            cursor.execute(PRODUCT_COUNT_SQL)
            products_before = int(cursor.fetchone()[0])

        titles = load_titles(connection)
        if args.limit:
            titles = titles[: args.limit]
        titles.sort(key=lambda row: row["title"])
        listing_rows = sum(row["rows"] for row in titles)
        latest_rows = sum(row["latest_rows"] for row in titles)

        print(f"--- expand_catalogue {'APPLY' if args.apply else 'dry run'} ---")
        print(f"products in catalogue      {products_before:,}")
        print(f"unmatched listings         {listing_rows:,} rows, {len(titles):,} distinct titles")
        print(f"  of those, the latest row per URL {latest_rows:,}")

        with connection.cursor() as cursor:
            cursor.execute("select count(*) from nafdac_registrations")
            registrations = int(cursor.fetchone()[0])
        print(f"register rows available    {registrations:,}")
        print(f"candidate floor            trigram similarity >= {args.min_similarity}, "
              f"max {CANDIDATES_PER_TITLE} per title")

        started = time.time()
        candidates = load_candidates(connection, [row["title"] for row in titles], args.min_similarity)
        connection.commit()  # release the read snapshot before the minutes-long embedding pass
        print(f"candidate generation       {time.time() - started:.1f}s")

        caches = {
            row["title"]: {
                "words": ml.title_words(row["title"]),
                "strength": strength_core(row["title"]),
                "form": form_families(row["title"]),
            }
            for row in titles
        }

        reasons: Counter = Counter()
        accepted: list[dict] = []
        near: list[dict] = []
        pairs = 0
        unknown_strength_titles = 0
        for row in titles:
            title = row["title"]
            cache = caches[title]
            for candidate in candidates.get(title, []):
                pairs += 1
                reason = classify(title, candidate, cache)
                reasons[reason] += 1
                if reason == "accepted":
                    accepted.append({"title": title, "sim": candidate["sim"], "candidate": candidate})
                    if cache["strength"] is None:
                        unknown_strength_titles += 1
                elif reason in ("strength disagrees", "dosage form incompatible") and candidate["sim"] >= 0.60:
                    near.append({"title": title, "sim": candidate["sim"], "candidate": candidate,
                                 "reason": reason})

        with connection.cursor() as cursor:
            cursor.execute(PRODUCTS_SQL)
            existing_products = [
                {"id": row[0], "canonical_name": row[1], "form": row[2], "strength": row[3]}
                for row in cursor.fetchall()
            ]

        built = build_proposals(accepted, existing_products)
        proposals = built["proposals"]
        near.sort(key=lambda pair: -pair["sim"])
        accepted.sort(key=lambda pair: -pair["sim"])

        print_pairs(reasons, pairs, unknown_strength_titles)

        print("\n2. products")
        print(f"   register rows accepted (pairs)   {len(accepted):,}")
        print(f"   distinct product triples         {built['groups']:,}")
        print(f"     already in the catalogue       {built['duplicates_avoided']:,} (skipped)")
        print(f"     new                            {len(proposals):,}")
        print(f"   cap                              {args.max_new:,}"
              f" -> {'OVER, refusing' if len(proposals) > args.max_new else 'ok'}")
        if built["near_duplicates"]:
            print(f"   SKIPPED {len(built['near_duplicates']):,} products share a name and strength with an"
                  " existing product under a different form label (same drug, two spellings):")
            for item in built["near_duplicates"][:5]:
                print(f"        {item['name'][:44]:44s} {item['strength'] or '-':12s} {item['form'] or '-'}")

        print("\n3. what each new product needs")
        without_rule = sum(1 for p in proposals if not p["rule_tokens"])
        print(f"   with a match rule                {len(proposals) - without_rule:,} of {len(proposals):,}")
        print(f"   without a rule (no name token)   {without_rule:,}")

        if len(proposals) > args.max_new:
            print(f"\nSTOP: {len(proposals):,} proposed products exceeds the --max-new cap of "
                  f"{args.max_new:,}. That means the filter is too loose, not that the run worked.")
            print("nothing written")
            return 3

        projection = None
        label = ""
        if not proposals or not titles:
            projection = project_stage_two_only(titles, proposals)
            label = "nothing to project (no proposals or no unmatched titles)"
        elif args.no_embeddings:
            print("   embedding                        skipped (--no-embeddings)")
        else:
            try:
                projection = project_attachments(connection, titles, proposals)
                label = "stage one + stage two, using match_listings.match_all"
                print(f"   embedded                         {len(proposals):,} products + "
                      f"{len(titles):,} titles at {EMBED_DIM} dims"
                      f" ({projection['seconds']:.1f}s)")
            except Exception as exc:  # noqa: BLE001 - the model is optional for a dry run
                print(f"   embedding FAILED                 {type(exc).__name__}: {exc}")
                print("   -> a product without an embedding matches nothing; --apply will refuse")

        if projection is None:
            projection = project_stage_two_only(titles, proposals)
            label = "stage-two upper bound (no embeddings: stage one not applied)"
        print(f"\n4. listings that would then match  [{label}]")
        print(f"   unmatched listings               {listing_rows:,}")
        print(f"   would attach to a new product    {projection['rows']:,} rows "
              f"across {projection['titles']:,} titles")
        print(f"     of those, the latest row per URL {projection['latest_rows']:,}")
        if projection["existing"]:
            print(f"   would attach to an EXISTING product {projection['existing']:,} -- projection artefact,"
                  " report it")
        for reason, count in sorted(projection["reasons"].items(), key=lambda kv: -kv[1]):
            if count:
                print(f"   matcher reason: {count:,} {reason}")
        if projection["per_product"]:
            print("   busiest new products:")
            for name, count in projection["per_product"].most_common(10):
                print(f"        {count:5,d} rows  {name}")
        dead = len(proposals) - len(projection["per_product"])
        print(f"   new products that would attach NOTHING {dead:,} of {len(proposals):,}"
              f" ({100.0 * dead / len(proposals):.0f}%)" if proposals else "   no proposals")

        print_examples(accepted, near)
        print(f"\n7. existing catalogue triples the dedupe refused to duplicate: "
              f"{built['duplicates_avoided']:,}")

        if args.apply:
            if projection["proposal_vectors"] is not None and len(projection["proposal_vectors"]) != len(proposals):
                print("refused: embedding count does not match the proposal count", file=sys.stderr)
                return 1
            if projection["proposal_vectors"] is None:
                print("refused: --apply needs embeddings; drop --no-embeddings", file=sys.stderr)
                return 4

            connection = ensure_connection(connection)
            run_id = start_run(connection, SOURCE)
            print(f"\nscrape_runs id={run_id} status=running source={SOURCE}")
            with connection.cursor() as cursor:
                for proposal, vector in zip(proposals, projection["proposal_vectors"]):
                    cursor.execute(
                        INSERT_PRODUCT_SQL,
                        (
                            proposal["canonical_name"],
                            proposal["form"],
                            proposal["strength"],
                            proposal["registration_number"],
                            ml.vector_literal(vector),
                        ),
                    )
                    inserted_products += cursor.rowcount
                for proposal in proposals:
                    cursor.execute(
                        INSERT_RULE_SQL,
                        (
                            proposal["canonical_name"],
                            proposal["match_pattern"],
                            proposal["strength"],
                            proposal["form"],
                            proposal["match_pattern"],
                            PRIORITY,
                        ),
                    )
                    inserted_rules += cursor.rowcount
            connection.commit()

            with connection.cursor() as cursor:
                cursor.execute(PRODUCT_COUNT_SQL)
                products_after = int(cursor.fetchone()[0])
            print(f"products inserted          {inserted_products:,} "
                  f"(catalogue {products_before:,} -> {products_after:,})")
            print(f"rules inserted             {inserted_rules:,}")
            print("next step                  python scripts/match_listings.py  (it owns product_id)")

            connection = ensure_connection(connection)
            finish_run(connection, run_id, status="success", record_count=inserted_products)
            print(f"scrape_runs id={run_id} status=success record_count={inserted_products}")
        else:
            print(f"\nVERDICT: would create {len(proposals):,} products and attach "
                  f"{projection['rows']:,} listing rows. Nothing written (dry run).")
        return 0
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if run_id is not None:
            try:
                finish_run(
                    connection or db_connect(),
                    run_id,
                    status="failed",
                    record_count=inserted_products or None,
                    error=message,
                )
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                try:
                    finish_run(db_connect(), run_id, status="failed",
                               record_count=inserted_products or None, error=message)
                    print(f"scrape_runs id={run_id} status=failed (reconnected)", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
