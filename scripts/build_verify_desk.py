"""Build the personal verification desk: one self-contained HTML file, no server, no network.

    .venv\\Scripts\\python.exe -X utf8 scripts/build_verify_desk.py
    .venv\\Scripts\\python.exe -X utf8 scripts/build_verify_desk.py --fixture site/verify/demo.html

Writes `site/verify/index.html`. It opens by double-click from `file://`, so every asset is inline:
the data is embedded as `<script type="application/json">`, and there is no external CSS, JS, font or
image. The self-check at the end of this file fails the build if any `http` appears outside that data
block, which is the same property the brief asks a person to grep for.

WHAT THE PAGE IS FOR. Two worklists that a person has to settle by reading the real sources:

  A. LICENCE - every product that `v_suspicious_listings` flags: the NAFDAC registration behind it is
     not Active, or its expiry date has passed. One item per product (not per listing), with the
     register page that `nafdac_registrations.source_url` holds, and every shop listing underneath.
  B. PACK - every `v_cheapest_per_product_state` cell with `is_comparison`: two shops publish a price
     for the same product. One item per cell, with every shop row, its page, its pack size and its unit
     price, so a person can say whether the shops really price the same pack.

A CARD IS A NUMBERED CHECKLIST, NOT ONE VERDICT. Every card carries five (licence) or six (pack)
specific questions in a fixed order. Each question prints the evidence we hold beside it, and offers
Pass / Fail / Cannot tell with nothing pre-selected, one click or one key per line. The card's outcome
is *computed* from those ticks - any Fail is a fail, all Pass is a pass, anything else is incomplete -
and is never asked for. That is the point of the rewrite: a judgement that is not prompted is a
judgement that gets skipped, and the wrong medicine on the first card was noticed only by accident.

WHERE THE DATA ALREADY ANSWERS A QUESTION, THE CARD SAYS SO. Two pack lines are answered by our own
rows before the reader starts: whether the two rows are really two different shops (line 5), and
whether the pack counts agree (line 4). The computed answer is printed as a badge marked "answered by
data", with the conflicting values spelled out ("56 vs 25 - differs"), so the reader confirms by eye
instead of discovering the defect late. The ticks are still not pre-filled: the reader confirms.

TWO WARNINGS ARE COMPUTED BEFORE ANY QUESTION. A red strip at the top of the card shows (a) a shop
title whose stated strength contradicts the strength of the product it is attached to, and (b) a pack
card whose rows are both from the same pharmacy. Both are measured defects, not hypotheticals.

THE STRENGTH CHECK IS A HEURISTIC AND SAYS SO ON THE PAGE. It reads mass units only - mg, mcg, g, iu
and % - normalising grams to milligrams, and reports a contradiction only when both sides carry such a
value and they share none. It cannot see that "250 mg/5 ml" and "250 mg" are a concentration against a
plain mass, it ignores volumes, and it stays silent when one side states nothing. It must not be read
as a complete rule about whether two medicines are the same.

VERDICTS DO NOT ENTER THE DATABASE. They are kept in `localStorage` under the versioned key
`ndw.verify.answers.v2`, one entry per card with one answer per line, and they leave through a
downloaded `verify-results.json` or the clipboard. The outcome is stored with each entry but is
recomputed on load, so an edited line can never leave a stale outcome behind. An older `v1` key, if it
is present, is reported as present and is not read as if it were `v2`. The connection here is opened
exactly as `scripts/dbq.py` and `scripts/build_site.py` open it: `default_transaction_read_only=on`, so
the server refuses any write from this script.

NO NUMBER IS TYPED HERE. The counts the build prints come from the queries below, and the item counts
on the page come from the items actually embedded.

WHY THE LINKS ARE NOT BUILT FROM A PATTERN. The register link is `nafdac_registrations.source_url`,
which `scrapers/nafdac_details.py` stores as the URL it actually fetched; the shop links are the
listing rows' own URLs. Nothing is joined onto a base hostname here, because a guessed URL that 404s
is indistinguishable, to a person reading it, from a registration that does not exist.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from envfile import ensure_database_url

OUT = Path("site") / "verify" / "index.html"

# The questions, in the order the brief fixes them. They live here once: the page renders the text from
# this list, so the wording on screen and the wording the self-check enforces cannot drift apart.
LICENCE_QUESTIONS = (
    "Does the register page open and show this registration number?",
    "Does the page's status match what we recorded?",
    "Does the page's expiry date match what we recorded?",
    "Is this the same medicine - name, strength and form?",
    "Does the register contradict itself - a status of Active with an expiry date already past?",
)
PACK_QUESTIONS = (
    "Does each shop's page show the price we recorded?",
    "Do the shops quote the same strength?",
    "Do they quote the same form - tablet, capsule, suspension, cream?",
    "Do they quote the same pack count?",
    "Are these two different shops?",
    "Is the item in stock at both shops?",
)
QUESTIONS = {"licence": LICENCE_QUESTIONS, "pack": PACK_QUESTIONS}

# The three answers, exactly as they are stored and exported.
ANSWERS = ("pass", "fail", "cannot")

HEURISTIC_SENTENCE = (
    "The strength comparison is a heuristic that reads mass units only (mg, mcg, g, iu, %) and "
    "normalises grams to milligrams. It ignores volumes, so a concentration written as 250 mg/5 ml is "
    "not compared with a plain 250 mg, and it stays silent when one side states no strength."
)


# --------------------------------------------------------------------------- reading the database
META_SQL = """
select
    (select max(scraped_at) from v_latest_listings)                  as prices_as_of,
    (select max(scraped_at) from nafdac_registrations)               as register_as_of,
    (select count(*) from v_latest_listings)                         as latest_listings,
    (select count(*) from nafdac_registrations where status is not null) as regs_with_status,
    (select count(*) from nafdac_registrations)                      as regs,
    (now() at time zone 'Africa/Lagos')::date                        as lagos_today,
    now()                                                            as database_now
"""

# One row per product, which is the unit a person judges: judging the same product twice because two
# shops sell it would be asking the same question twice. The join to `nafdac_registrations` reads the
# same row `v_suspicious_listings` already matched, and adds what the register itself says plus the
# detail-page URL, none of which the view exposes.
LICENCE_PRODUCTS_SQL = """
select
    p.id                                       as product_id,
    p.canonical_name,
    p.strength,
    p.form,
    p.nafdac_registration_number               as nrn,
    r.product_name                             as reg_product_name,
    r.brand_name                               as reg_brand_name,
    r.strength                                 as reg_strength,
    r.dosage_form                              as reg_form,
    r.applicant,
    r.status                                   as reg_status,
    r.approval_date,
    r.expiry_date,
    r.pack_description,
    r.source_url,
    r.scraped_at                               as reg_scraped_at,
    count(*)                                   as listing_count,
    count(distinct s.pharmacy_name)            as shop_count,
    min(s.price_ngn)                           as min_price,
    max(s.price_ngn)                           as max_price,
    string_agg(distinct s.suspicion_reason, ',') as reasons
from v_suspicious_listings s
join products p
  on p.id = s.product_id
join nafdac_registrations r
  on r.registration_number = s.registration_number
group by
    p.id, p.canonical_name, p.strength, p.form, p.nafdac_registration_number,
    r.product_name, r.brand_name, r.strength, r.dosage_form, r.applicant, r.status,
    r.approval_date, r.expiry_date, r.pack_description, r.source_url, r.scraped_at
order by p.canonical_name, p.strength nulls first, p.id
"""

# Every listing behind those products, so the item can show who sells it and at what price.
LICENCE_LISTINGS_SQL = """
select
    s.product_id,
    s.pharmacy_name,
    s.state,
    s.raw_title,
    s.url,
    s.price_ngn,
    s.in_stock,
    s.suspicion_reason
from v_suspicious_listings s
order by s.product_id, s.price_ngn nulls last, s.pharmacy_name, s.url
"""

# One row per comparison cell. `is_comparison` is the view's own rule (pharmacy_count >= 2) and is the
# gate for this worklist: the page does not re-decide what counts as a pack comparison.
PACK_CELLS_SQL = """
select
    c.product_id,
    c.canonical_name,
    p.strength,
    p.form,
    p.nafdac_registration_number,
    c.state,
    c.pharmacy_count,
    c.confirmed_pharmacy_count,
    c.cheapest_pack_price,
    c.cheapest_pack_pack_size,
    c.cheapest_pack_pharmacy,
    c.registration_status,
    c.registration_flagged
from v_cheapest_per_product_state c
join products p
  on p.id = c.product_id
where c.is_comparison
order by c.canonical_name, c.state, c.product_id
"""

# The base filter is copied from the view's own `base` CTE (schema/008), so the rows shown are exactly
# the rows the cell was computed from. A row the view excluded must not appear here: it would look like
# a price the comparison was based on when it was not.
PACK_ROWS_SQL = """
select
    l.product_id,
    c.state,
    l.pharmacy_name,
    l.raw_title,
    l.price_ngn,
    l.in_stock,
    l.pack_size,
    l.pack_unit,
    l.unit_price,
    l.url,
    l.scraped_at
from v_cheapest_per_product_state c
join v_latest_listings l
  on l.product_id = c.product_id
 and l.state = c.state
where c.is_comparison
  and l.product_id is not null
  and l.price_ngn is not null
  and l.in_stock is not false
order by l.product_id, c.state, l.pharmacy_name, l.price_ngn, l.url
"""


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def safe_url(value: Any) -> str | None:
    """Only a real absolute link is a link. Anything else is reported as missing, never repaired."""
    text = "" if value is None else str(value).strip()
    return text if text.lower().startswith(("http://", "https://")) else None


def money(value: Any, places: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), places)


def licence_label(status: Any, flagged: Any) -> str:
    """Three labels, never a blank: active / not active / not read. Same rule as build_site.py."""
    if status is None:
        return "not read"
    return "not active" if bool(flagged) else "active"


def reason_words(reasons: str | None) -> list[str]:
    words = {
        "inactive_registration": "the register's status for this registration is not Active",
        "expired_registration": "the registration's expiry date has passed",
    }
    codes = [code.strip() for code in (reasons or "").split(",") if code.strip()]
    return [words.get(code, code) for code in sorted(set(codes))]


# --------------------------------------------------------------------------- reading strengths and forms
# Mass units only: the ones a shop title and a register strength can be compared on without inventing a
# rule about volumes. Grams are normalised to milligrams; mcg stays mcg; iu and % are their own units.
MASS_RE = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:[.,]\d+)?)\s*(mg|mcg|\u00b5g|ug|g|iu|%)", re.IGNORECASE)


def mass_tokens(text: str | None) -> list[tuple[float, str]]:
    tokens: list[tuple[float, str]] = []
    for number, unit in MASS_RE.findall(text or ""):
        value = float(number.replace(",", "."))
        word = unit.lower().replace("\u00b5g", "mcg").replace("ug", "mcg")
        if word == "g":
            value = value * 1000.0
            word = "mg"
        tokens.append((value, word))
    return tokens


def mass_words(tokens: list[tuple[float, str]]) -> str:
    words: list[str] = []
    for value, unit in tokens:
        word = f"{value:g} {unit}"
        if word not in words:
            words.append(word)
    return " and ".join(words)


def strength_contradiction(title: str | None, product_strength: str | None) -> str | None:
    """Return a plain sentence when a listing title and its product disagree on mass, else None.

    HEURISTIC, and deliberately conservative - see HEURISTIC_SENTENCE, which is printed on the page.
    It returns a sentence only when both sides carry a mass unit and share no value at all, so a title
    that says less than the product (or nothing) is not accused of contradicting it.
    """
    have = mass_tokens(title)
    want = mass_tokens(product_strength)
    if not have or not want:
        return None
    have_set = {(round(value, 4), unit) for value, unit in have}
    want_set = {(round(value, 4), unit) for value, unit in want}
    if have_set & want_set:
        return None
    return f"title says {mass_words(have)}, product says {mass_words(want)}"


# Forms are read from the shop's own title, because `pharmacy_listings` holds no form column. Same
# status as the strength check: a heuristic, silent when the title names no form.
FORM_PATTERNS = (
    (r"\bsuspension\b|\bsusp\b", "suspension"),
    (r"\bsyrup\b", "syrup"),
    (r"\btablets?\b|\btabs?\b|\bblister\b", "tablet"),
    (r"\bcapsules?\b|\bcaps?\b", "capsule"),
    (r"\bcaplets?\b", "caplet"),
    (r"\bcream\b", "cream"),
    (r"\bointment\b", "ointment"),
    (r"\bgel\b", "gel"),
    (r"\blotion\b", "lotion"),
    (r"\binjection\b|\binject\b|\bvial\b|\bampoule\b", "injection"),
    (r"\binfusion\b", "infusion"),
    (r"\bdrops?\b", "drops"),
    (r"\bsachets?\b", "sachet"),
    (r"\bpowder\b", "powder"),
    (r"\bsuppositor(?:y|ies)\b", "suppository"),
    (r"\bspray\b", "spray"),
    (r"\bshampoo\b", "shampoo"),
    (r"\bsolution\b|\bsoln\b", "solution"),
)


def form_of(text: str | None) -> str | None:
    low = (text or "").lower()
    for pattern, label in FORM_PATTERNS:
        if re.search(pattern, low):
            return label
    return None


def product_form(form: str | None) -> str | None:
    """The product's stored form, through the same reader, falling back to what is stored."""
    if not form:
        return None
    return form_of(form) or str(form).strip().lower()


# --------------------------------------------------------------------------- building one line
def ev(label: str, value: Any, href: str | None = None, tone: str | None = None) -> dict[str, Any]:
    """One piece of evidence printed beside a question. `tone` is ok / bad / muted, or absent."""
    out: dict[str, Any] = {"label": label, "value": "" if value is None else str(value)}
    if href:
        out["href"] = href
    if tone:
        out["tone"] = tone
    return out


def auto(text: str, tone: str) -> dict[str, str]:
    """A question our own rows already answer, shown with the answer spelled out."""
    return {"text": text, "tone": tone}


def question(number: int, evidence: list[dict[str, Any]],
             computed: dict[str, str] | None = None) -> dict[str, Any]:
    return {"n": number, "evidence": evidence, "auto": computed}


def join_words(parts: list[str]) -> str:
    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# --------------------------------------------------------------------------- assembling the items
def build_licence(product_rows: list[tuple], listing_rows: list[tuple],
                  lagos_today: date) -> list[dict[str, Any]]:
    by_product: dict[int, list[dict[str, Any]]] = {}
    for (product_id, shop, state, title, url, price, in_stock, reason) in listing_rows:
        by_product.setdefault(int(product_id), []).append({
            "shop": shop,
            "state": state,
            "title": title,
            "price": money(price),
            "in_stock": None if in_stock is None else bool(in_stock),
            "url": safe_url(url),
        })

    items: list[dict[str, Any]] = []
    for row in product_rows:
        (product_id, name, strength, form, nrn, reg_name, reg_brand, reg_strength, reg_form,
         applicant, reg_status, approval, expiry, pack_description, source_url, reg_scraped,
         listing_count, shop_count, min_price, max_price, reasons) = row
        expiry_passed = expiry is not None and expiry < lagos_today
        listings = by_product.get(int(product_id), [])
        register_url = safe_url(source_url)
        read_at = iso(reg_scraped)

        status_tone = "bad" if reg_status not in (None, "Active") else ("ok" if reg_status else "muted")
        status_text = reg_status or "not read"
        if not reg_status:
            status_note = "No status was ever scraped for this registration. A gap in our reading, " \
                          "not a finding about the medicine."
        else:
            status_note = f"Recorded from the register page at {read_at or 'an unknown time'}."
        expiry_text = iso(expiry) or "not read"

        # The warning strip, computed from the rows we hold. A shop title that states a different mass
        # from the product it is attached to is the defect found on 2026-11-12.
        flags: list[dict[str, str]] = []
        for listing in listings:
            sentence = strength_contradiction(listing["title"], strength)
            if sentence:
                flags.append({
                    "kind": "strength_mismatch",
                    "headline": "Attached medicine looks wrong",
                    "detail": f'{listing["shop"]}: {sentence}',
                    "raw": listing["title"] or "",
                })

        contradiction: dict[str, str] | None = None
        if reg_status and expiry:
            if reg_status == "Active" and expiry_passed:
                contradiction = auto(
                    f"Fail - the status is Active but the expiry {iso(expiry)} has passed", "bad")
            else:
                contradiction = auto(
                    f"No contradiction - status {reg_status}, expiry {iso(expiry)}", "ok")
        else:
            contradiction = auto(
                "Cannot be checked from what we hold - "
                + ("the status was never read" if not reg_status else "no expiry date was read"),
                "muted")

        reg_summary = " \u00b7 ".join(part for part in (
            reg_name or "no product name read",
            reg_strength or "strength not stated",
            reg_form or "form not stated",
        ) if part)
        product_summary = " \u00b7 ".join(part for part in (
            name or "name not recorded",
            strength or "strength not recorded",
            form or "form not recorded",
        ) if part)

        questions = [
            question(1, [
                ev("Our registration number", nrn or "none recorded",
                   tone=None if nrn else "bad"),
                ev("Expected page", register_url or "no page recorded - a failed fetch was not stored",
                   href=register_url, tone=None if register_url else "bad"),
                ev("We read that page at", read_at or "an unknown time"),
            ]),
            question(2, [
                ev("Our recorded status", status_text, tone=status_tone),
                ev("Where that came from", status_note),
                ev("Register says the pack is", pack_description or "not read"),
            ]),
            question(3, [
                ev("Our recorded expiry", expiry_text,
                   tone="bad" if expiry_passed else ("muted" if not expiry else None)),
                ev("Approval date we hold", iso(approval) or "not read"),
            ]),
            question(4, [
                ev("What we call it", product_summary),
                ev("What the register says", reg_summary),
                ev("Brand on the register", reg_brand or "not read"),
                ev("Applicant on the register", applicant or "not read"),
            ]),
            question(5, [
                ev("Our recorded status", status_text, tone=status_tone),
                ev("Our recorded expiry", expiry_text,
                   tone="bad" if expiry_passed else ("muted" if not expiry else None)),
            ], contradiction),
        ]

        items.append({
            "kind": "licence",
            # Stable across rebuilds: the product row is the unit, so an answer survives a re-scrape.
            "id": f"licence-{int(product_id)}",
            "product_id": int(product_id),
            "name": name,
            "strength": strength,
            "form": form,
            "nrn": nrn,
            "register": {
                "product_name": reg_name,
                "brand_name": reg_brand,
                "strength": reg_strength,
                "form": reg_form,
                "applicant": applicant,
                "status": reg_status,
                "approval_date": iso(approval),
                "expiry_date": iso(expiry),
                "pack_description": pack_description,
                "url": register_url,
                "read_at": read_at,
            },
            "expiry_passed": bool(expiry_passed),
            "reasons": reason_words(reasons),
            "listing_count": int(listing_count),
            "shop_count": int(shop_count),
            "min_price": money(min_price),
            "max_price": money(max_price),
            "listings": listings,
            "flags": flags,
            "questions": questions,
        })
    return items


PACK_UNIT_WORDS = {
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet",
    "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule",
    "sachet": "sachet", "sachets": "sachet", "vial": "vial", "vials": "vial",
    "bottle": "bottle", "bottles": "bottle", "tube": "tube", "tubes": "tube",
}


def normalise_pack_unit(unit: str | None) -> str | None:
    word = (unit or "").strip().lower()
    if not word:
        return None
    return PACK_UNIT_WORDS.get(word, word)


def pack_words(row: dict[str, Any]) -> str | None:
    if row["pack_size"] is None:
        return None
    unit = normalise_pack_unit(row["pack_unit"])
    return f'{row["pack_size"]} {unit}'.strip()


def build_pack(cell_rows: list[tuple], row_rows: list[tuple]) -> list[dict[str, Any]]:
    by_cell: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for (product_id, state, shop, title, price, in_stock, pack_size, pack_unit, unit_price, url,
         scraped) in row_rows:
        by_cell.setdefault((int(product_id), state), []).append({
            "shop": shop,
            "title": title,
            "price": money(price),
            "pack_size": None if pack_size is None else int(pack_size),
            "pack_unit": pack_unit,
            "unit_price": money(unit_price, 4),
            "in_stock": None if in_stock is None else bool(in_stock),
            "url": safe_url(url),
            "read_at": iso(scraped),
        })

    items: list[dict[str, Any]] = []
    for row in cell_rows:
        (product_id, name, strength, form, nrn, state, shops_quoting, shops_confirmed,
         cheapest_price, cheapest_pack, cheapest_shop, reg_status, reg_flagged) = row
        key = (int(product_id), state)
        rows = by_cell.get(key, [])
        shops = [r["shop"] for r in rows]
        unique_shops: list[str] = []
        for shop in shops:
            if shop not in unique_shops:
                unique_shops.append(shop)

        flags: list[dict[str, str]] = []
        for r in rows:
            sentence = strength_contradiction(r["title"], strength)
            if sentence:
                flags.append({
                    "kind": "strength_mismatch",
                    "headline": "Attached medicine looks wrong",
                    "detail": f'{r["shop"]}: {sentence}',
                    "raw": r["title"] or "",
                })
        same_shop = len(unique_shops) < 2
        if same_shop:
            flags.append({
                "kind": "same_shop",
                "headline": "Same shop twice",
                "detail": f'both rows are {join_words(unique_shops)} - this is not a comparison',
                "raw": "",
            })

        # --- line 1: does each page show the price we recorded?
        line1 = [ev(r["shop"], money(r["price"]), href=r["url"], tone=None if r["url"] else "bad")
                 for r in rows]
        line1.append(ev("Each link is the page this project fetched", "prices read "
                        + (rows[0]["read_at"] or "at an unknown time") if rows else "no rows"))

        # --- line 2: same strength?
        product_mass = mass_tokens(strength)
        line2 = [ev("Product strength we hold", strength or "not recorded")]
        bad_strength = []
        stated = 0
        for r in rows:
            tokens = mass_tokens(r["title"])
            if not tokens:
                line2.append(ev(r["shop"], "title states no mass", tone="muted"))
                continue
            stated += 1
            sentence = strength_contradiction(r["title"], strength)
            if sentence:
                bad_strength.append(r["shop"])
                line2.append(ev(r["shop"], sentence, tone="bad"))
            else:
                line2.append(ev(r["shop"], f'title says {mass_words(tokens)} - agrees with the product',
                                tone="ok"))
        if bad_strength:
            strength_computed = auto(
                f"differs - {join_words(bad_strength)} state"
                f"{'s' if len(bad_strength) == 1 else ''} a different mass from the product", "bad")
        elif stated:
            strength_computed = auto(
                f"same - every title that states a mass agrees ({mass_words(product_mass)})", "ok")
        else:
            strength_computed = auto("not stated - no title carries a mass", "muted")

        # --- line 3: same form?
        product_form_word = product_form(form)
        line3 = [ev("Product form we hold", product_form_word or form or "not recorded")]
        forms_seen: list[str] = []
        form_missing: list[str] = []
        for r in rows:
            word = form_of(r["title"])
            if word:
                forms_seen.append(word)
                line3.append(ev(r["shop"], f"title says {word}", tone="ok"))
            else:
                form_missing.append(r["shop"])
                line3.append(ev(r["shop"], "title names no form", tone="muted"))
        distinct_forms = sorted(set(forms_seen))
        if len(forms_seen) < 2:
            form_computed = auto(
                "not stated - fewer than two titles name a form, so the page cannot be compared", "muted")
        elif len(distinct_forms) == 1:
            form_computed = auto(f"same - {distinct_forms[0]} in every title that names one", "ok")
        else:
            form_computed = auto(f"differs - {join_words(distinct_forms)}", "bad")

        # --- line 4: same pack count?
        line4 = []
        by_size: dict[int, list[str]] = {}
        readable = 0
        for r in rows:
            words = pack_words(r)
            if words is None:
                line4.append(ev(r["shop"], "pack not read from the page", tone="bad"))
            else:
                readable += 1
                line4.append(ev(r["shop"], words))
                by_size.setdefault(int(r["pack_size"]), []).append(normalise_pack_unit(r["pack_unit"]) or "")
        display: list[str] = []
        for size, unit_list in by_size.items():
            units = {unit for unit in unit_list if unit}
            word = units.pop() if len(units) == 1 else ""
            display.append(f"{size} {word}".strip())
        all_units = {normalise_pack_unit(r["pack_unit"]) for r in rows if normalise_pack_unit(r["pack_unit"])}
        if readable < 2:
            pack_computed = auto(
                f"not read - only {readable} of {len(rows)} rows carry a pack we could read", "muted")
        elif len(by_size) == 1 and len(all_units) <= 1:
            pack_computed = auto(f"same - each row is {display[0]}", "ok")
        else:
            pack_computed = auto(" vs ".join(display) + " - differs", "bad")

        # --- line 5: two different shops? Answered by our own rows, which is the point of the line.
        if same_shop:
            shops_computed = auto(f"Fail - both rows are {join_words(unique_shops)}", "bad")
        else:
            shops_computed = auto(f"Pass - {join_words(unique_shops)} are different shops", "ok")
        line5 = [ev(r["shop"], r["title"] or "", href=r["url"]) for r in rows]

        # --- line 6: in stock at both?
        line6 = []
        for r in rows:
            if r["in_stock"] is True:
                line6.append(ev(r["shop"], "in stock", tone="ok"))
            elif r["in_stock"] is False:
                line6.append(ev(r["shop"], "out of stock", tone="bad"))
            else:
                line6.append(ev(r["shop"], "stock not read", tone="muted"))
        out_of_stock = [r["shop"] for r in rows if r["in_stock"] is False]
        unread_stock = [r["shop"] for r in rows if r["in_stock"] is None]
        if out_of_stock:
            stock_computed = auto(f"{join_words(out_of_stock)} say out of stock", "bad")
        elif unread_stock:
            stock_computed = auto(f"not read at {join_words(unread_stock)}", "muted")
        else:
            stock_computed = auto("in stock at every shop", "ok")
        line6.append(ev("A missing stock reading", "is a gap in our reading, not evidence either way",
                        tone="muted"))

        items.append({
            "kind": "pack",
            # Product and state together: the cell is the unit, not the product alone.
            "id": f"pack-{int(product_id)}-{state}",
            "product_id": int(product_id),
            "name": name,
            "strength": strength,
            "form": form,
            "nrn": nrn,
            "state": state,
            "shops_quoting": int(shops_quoting),
            "shops_confirmed": int(shops_confirmed),
            "cheapest_price": money(cheapest_price),
            "cheapest_pack_size": None if cheapest_pack is None else int(cheapest_pack),
            "cheapest_shop": cheapest_shop,
            "licence": licence_label(reg_status, reg_flagged),
            "register_status": reg_status,
            "shop_names": unique_shops,
            "rows": rows,
            "flags": flags,
            "questions": [
                question(1, line1),
                question(2, line2, strength_computed),
                question(3, line3, form_computed),
                question(4, line4, pack_computed),
                question(5, line5, shops_computed),
                question(6, line6, stock_computed),
            ],
        })
    return items


def distinct_shops(rows: list[dict[str, Any]]) -> int:
    return len({row["shop"] for row in rows})


# --------------------------------------------------------------------------- the page
CSS = """
:root{--ink:#1b1b1b;--muted:#484848;--line:#b9b9b9;--bg:#ffffff;--panel:#f3f3f1;
--accent:#0b4f6c;--warn:#7a2e00;--warn-bg:#fdf1e3;--ok:#1c5c2e;--ok-bg:#eef5ef;--focus:#ffe08a}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:1.0625rem/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:54rem;margin:0 auto;padding:1rem .75rem 3rem}
a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
:focus-visible,a:focus-visible,button:focus-visible,textarea:focus-visible,summary:focus-visible{
outline:3px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-9999px;top:0;background:var(--bg);padding:.6rem 1rem;z-index:10}
.skip:focus{left:.5rem;top:.5rem;border:2px solid var(--ink)}
header{border-bottom:3px solid var(--ink);padding-bottom:.75rem;margin-bottom:1rem}
h1{font-size:1.6rem;line-height:1.2;margin:.4rem 0 .5rem}
h2{font-size:1.15rem;margin:1.8rem 0 .5rem}
h3{font-size:1rem;margin:1.2rem 0 .35rem}
p,li{margin:.45rem 0;overflow-wrap:break-word}
.banner{background:var(--warn-bg);border:2px solid var(--warn);color:var(--warn);
padding:.75rem .9rem;margin:1rem 0;border-radius:4px}
.banner p{margin:.2rem 0;color:var(--warn)}
.notice{background:var(--panel);border-left:5px solid var(--ink);padding:.6rem .8rem;margin:.8rem 0}
.note{color:var(--muted);font-size:.94rem}
.stamp{font-variant-numeric:tabular-nums}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
clip:rect(0 0 0 0);white-space:nowrap;border:0}
.switcher,.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin:.6rem 0}
button{font:inherit;color:var(--ink);background:var(--panel);border:2px solid var(--ink);
border-radius:5px;padding:.5rem .8rem;cursor:pointer;min-height:44px}
button[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
button:disabled{color:var(--muted);border-color:var(--line);background:var(--bg);cursor:not-allowed}
.card{border:2px solid var(--ink);border-radius:6px;padding:1rem;margin:1rem 0}
.pos{margin:.1rem 0 .5rem;font-size:.94rem;color:var(--muted);font-variant-numeric:tabular-nums}
.item-title{font-size:1.5rem;line-height:1.2;margin:.15rem 0 .3rem;overflow-wrap:break-word}
.sub{margin:.1rem 0 .8rem;font-size:1.05rem}
.pill{display:inline-block;font-size:.84rem;line-height:1.5;padding:0 .4rem;border:1px solid;
border-radius:3px;font-weight:600;white-space:nowrap}
.pill-ok{border-color:var(--ok);color:var(--ok);background:var(--ok-bg)}
.pill-bad{border-color:var(--warn);color:var(--warn);background:var(--warn-bg)}
.pill-muted{border-color:#5b5b5b;color:var(--muted);background:var(--panel)}
.pill-pass{border-color:var(--ok);color:var(--ok);background:var(--ok-bg)}
.pill-fail{border-color:var(--warn);color:var(--warn);background:var(--warn-bg)}
.pill-cannot{border-color:#5b5b5b;color:var(--muted);background:var(--panel)}
.pill-blank{border-color:var(--line);color:var(--muted);background:var(--bg)}
.flags{background:var(--warn-bg);border:3px solid var(--warn);border-radius:5px;
padding:.7rem .85rem;margin:.9rem 0}
.flags h3{margin:.1rem 0 .4rem;color:var(--warn)}
.flags ul{margin:.2rem 0 0;padding-left:1.2rem}
.flags li{color:var(--warn)}
.flag-kind{font-weight:700}
.qlist{list-style:none;margin:.6rem 0 0;padding:0}
.qline{border:2px solid var(--line);border-radius:6px;padding:.65rem .8rem;margin:.65rem 0;
background:var(--bg)}
.qline:focus{outline:4px solid var(--focus);outline-offset:1px;border-color:var(--ink)}
.qline.is-focused{border-color:var(--ink);box-shadow:inset 5px 0 0 var(--accent)}
.qnum{display:inline-block;font-variant-numeric:tabular-nums;font-weight:700;font-size:.9rem;
background:var(--ink);color:var(--bg);border-radius:3px;padding:0 .35rem;margin:0 .4rem 0 0}
.qtext{display:inline;font-weight:700;margin:0}
.qev{margin:.45rem 0 .5rem}
.evrow{margin:.15rem 0;font-size:.96rem}
.evlabel{color:var(--muted);font-weight:600}
.evlabel::after{content:":"}
.evval.bad{color:var(--warn);font-weight:700}
.evval.ok{color:var(--ok);font-weight:600}
.evval.muted{color:var(--muted)}
.autoline{margin:.35rem 0 .1rem;padding:.35rem .5rem;border-left:4px solid var(--accent);
background:var(--panel);font-size:.96rem}
.autoline.bad{border-left-color:var(--warn);background:var(--warn-bg);color:var(--warn)}
.autoline.ok{border-left-color:var(--ok);background:var(--ok-bg);color:var(--ok)}
.answers{display:flex;flex-wrap:wrap;gap:.45rem;margin:.4rem 0 0}
.abtn{min-height:48px;padding:.45rem .8rem}
.abtn[aria-pressed="true"].a-pass{background:var(--ok);border-color:var(--ok);color:var(--bg)}
.abtn[aria-pressed="true"].a-fail{background:var(--warn);border-color:var(--warn);color:var(--bg)}
.abtn[aria-pressed="true"].a-cannot{background:#4a4a4a;border-color:#4a4a4a;color:var(--bg)}
.qstate{margin:.3rem 0 0;font-size:.9rem;color:var(--muted)}
.outcome{border:2px solid var(--ink);border-radius:5px;padding:.7rem .85rem;margin:1rem 0 0}
.outcome h3{margin:.1rem 0 .3rem}
.outcome-fail{border-color:var(--warn);background:var(--warn-bg)}
.outcome-pass{border-color:var(--ok);background:var(--ok-bg)}
.outcome-incomplete{border-color:var(--line);background:var(--panel)}
dl{margin:.4rem 0 .8rem}
dt{font-weight:600;margin:.65rem 0 .1rem}
dd{margin:0 0 0 0}
dd .note{display:block}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:4px;margin:.5rem 0 .9rem}
table{border-collapse:collapse;width:100%;font-size:.94rem}
caption{text-align:left;padding:.45rem .6rem;background:var(--panel);color:var(--muted);
border-bottom:1px solid var(--line);font-size:.9rem}
th,td{padding:.45rem .55rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{background:var(--panel);white-space:nowrap}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.title{min-width:12rem;font-size:.9rem;color:var(--muted)}
.shoplist{margin:.3rem 0 .9rem;padding-left:1.2rem}
label{display:block;font-weight:600;margin:1rem 0 .3rem}
textarea{width:100%;font:inherit;padding:.6rem;border:2px solid var(--line);border-radius:5px;
background:var(--bg);color:var(--ink)}
textarea:focus{border-color:var(--ink)}
.hint{font-size:.92rem;color:var(--muted)}
.okline{color:var(--ok);font-weight:600}
.badline{color:var(--warn);font-weight:600}
table.keys td:first-child{font-family:ui-monospace,Consolas,monospace;white-space:nowrap;
font-weight:600}
footer{margin-top:2.5rem;padding-top:1rem;border-top:2px solid var(--line);color:var(--muted);
font-size:.9rem}
@media (max-width:430px){
 .wrap{padding:.75rem .6rem 2rem}
 h1{font-size:1.35rem}
 .item-title{font-size:1.25rem}
 table{font-size:.86rem}
 .abtn{padding:.4rem .6rem}
}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""

JS = r"""
(function () {
  'use strict';

  var DATA = JSON.parse(document.getElementById('desk-data').textContent);
  var LISTS = { licence: DATA.licence, pack: DATA.pack };
  var QLABELS = { licence: DATA.meta.questions.licence, pack: DATA.meta.questions.pack };
  var STORE_KEY = 'ndw.verify.answers.v2';
  var POS_KEY = 'ndw.verify.pos.v2';
  var OLD_KEYS = ['ndw.verify.licence.v1', 'ndw.verify.pack.v1'];
  var ANSWERS = ['pass', 'fail', 'cannot'];
  var ANSWER_LABEL = { pass: 'Pass', fail: 'Fail', cannot: 'Cannot tell' };
  var FILTERS = ['all', 'open', 'fail'];
  var FILTER_LABEL = { all: 'All', open: 'Open', fail: 'Fail' };

  var state = {
    list: 'licence',
    filter: 'all',
    answers: {},
    pos: { licence: null, pack: null },
    focus: 1,
    storage: true
  };

  var els = {};
  var BY_ID = {};

  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g,
      function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
  }

  function money(value, places) {
    if (value === null || value === undefined || value === '') { return 'not read'; }
    var n = Number(value);
    if (!isFinite(n)) { return 'not read'; }
    var dp = (places === undefined) ? 2 : places;
    var parts = n.toFixed(dp).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return '\u20a6' + parts.join('.');
  }

  function text(value, fallback) {
    if (value === null || value === undefined || String(value).trim() === '') { return fallback; }
    return String(value);
  }

  function listOf(numbers) {
    if (!numbers.length) { return ''; }
    if (numbers.length === 1) { return 'line ' + numbers[0]; }
    return 'lines ' + numbers.slice(0, -1).join(', ') + ' and ' + numbers[numbers.length - 1];
  }

  // ------------------------------------------------------------------ storage
  function readJson(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      if (!raw) { return fallback; }
      var parsed = JSON.parse(raw);
      return (parsed && typeof parsed === 'object') ? parsed : fallback;
    } catch (e) {
      state.storage = false;
      return fallback;
    }
  }

  function writeJson(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      state.storage = false;
      updateStorageWarning();
    }
  }

  function updateStorageWarning() {
    if (state.storage) { els.storageWarning.hidden = true; return; }
    els.storageWarning.hidden = false;
    els.storageWarning.textContent = 'This browser refused to store answers locally, so a reload ' +
      'will lose them. Use the download button before closing the page.';
  }

  function indexItems() {
    ['licence', 'pack'].forEach(function (kind) {
      LISTS[kind].forEach(function (item) { BY_ID[item.id] = item; });
    });
  }

  // The outcome is stored beside each entry, and recomputed the moment the page loads. An entry whose
  // stored outcome was left behind by an edited line is corrected here, not believed.
  function load() {
    var raw = readJson(STORE_KEY, {});
    var corrected = false;
    Object.keys(raw).forEach(function (id) {
      var item = BY_ID[id];
      var source = raw[id];
      if (!item || !source || typeof source !== 'object') { return; }
      var entry = { note: String(source.note || ''), at: source.at || null };
      var total = item.questions.length;
      var answered = 0;
      for (var i = 1; i <= total; i += 1) {
        var value = source[String(i)];
        if (ANSWERS.indexOf(value) >= 0) { entry[String(i)] = value; answered += 1; }
      }
      if (!answered && !entry.note) { return; }
      // The entry has to be in place before the outcome is recomputed, or the recomputation reads an
      // empty card and stamps every reloaded entry "incomplete". Found by _selftest.cjs: a card whose
      // line 5 said fail came back from storage with outcome "incomplete".
      state.answers[id] = entry;
      entry.outcome = outcomeOf(item).outcome;
      if (entry.outcome !== source.outcome) { corrected = true; }
    });
    // A stored outcome that disagreed with its own answers is written back, so storage cannot say
    // "pass" about a card whose line 5 says fail - the export reads the same thing the screen does.
    if (corrected) { writeJson(STORE_KEY, state.answers); }
    var pos = readJson(POS_KEY, {});
    state.pos.licence = pos.licence || null;
    state.pos.pack = pos.pack || null;
  }

  function saveEntry(item) {
    var entry = state.answers[item.id];
    if (!entry) { return; }
    var hasAnswer = false;
    for (var i = 1; i <= item.questions.length; i += 1) {
      if (entry[String(i)]) { hasAnswer = true; }
    }
    if (!hasAnswer && !String(entry.note || '').trim()) {
      delete state.answers[item.id];
    } else {
      entry.outcome = outcomeOf(item).outcome;
      state.answers[item.id] = entry;
    }
    writeJson(STORE_KEY, state.answers);
  }

  function entryOf(item) { return state.answers[item.id] || null; }

  function answerOf(item, line) {
    var entry = entryOf(item);
    return (entry && entry[String(line)]) || null;
  }

  function noteOf(item) {
    var entry = entryOf(item);
    return (entry && entry.note) || '';
  }

  function setAnswer(item, line, answer) {
    var entry = state.answers[item.id] || { note: '', at: null };
    entry[String(line)] = answer;
    entry.note = entry.note || '';
    entry.at = new Date().toISOString();
    state.answers[item.id] = entry;
    saveEntry(item);
  }

  function setNote(item, value) {
    var entry = state.answers[item.id] || { note: '', at: null };
    entry.note = value;
    entry.at = new Date().toISOString();
    state.answers[item.id] = entry;
    saveEntry(item);
  }

  // ------------------------------------------------------------------ the computed outcome
  function outcomeOf(item) {
    var entry = state.answers[item.id] || {};
    var total = item.questions.length;
    var failLines = [];
    var cannotLines = [];
    var missingLines = [];
    var passes = 0;
    for (var i = 1; i <= total; i += 1) {
      var answer = entry[String(i)];
      if (answer === 'fail') { failLines.push(i); }
      else if (answer === 'pass') { passes += 1; }
      else if (answer === 'cannot') { cannotLines.push(i); }
      else { missingLines.push(i); }
    }
    if (failLines.length) {
      return { outcome: 'fail', failLines: failLines, cannot: cannotLines, missing: missingLines };
    }
    if (passes === total) {
      return { outcome: 'pass', failLines: [], cannot: [], missing: [] };
    }
    return { outcome: 'incomplete', failLines: [], cannot: cannotLines, missing: missingLines };
  }

  function outcomeSentence(result) {
    if (result.outcome === 'pass') { return 'Every line is answered Pass.'; }
    if (result.outcome === 'fail') { return 'Answered Fail on ' + listOf(result.failLines) + '.'; }
    var parts = [];
    if (result.missing.length) { parts.push('not answered on ' + listOf(result.missing)); }
    if (result.cannot.length) { parts.push('cannot tell on ' + listOf(result.cannot)); }
    return parts.join('; ') + '.';
  }

  function outcomePill(result) {
    return '<span class="pill pill-' + result.outcome + '">' + result.outcome + '</span>';
  }

  // ------------------------------------------------------------------ the lists
  function currentList() { return LISTS[state.list]; }

  function passes(item, filter) {
    var outcome = outcomeOf(item).outcome;
    if (filter === 'open') { return outcome === 'incomplete'; }
    if (filter === 'fail') { return outcome === 'fail'; }
    return true;
  }

  function visible() {
    return currentList().filter(function (item) { return passes(item, state.filter); });
  }

  function indexOfCurrent(list) {
    if (!list.length) { return -1; }
    var saved = state.pos[state.list];
    if (saved) {
      for (var i = 0; i < list.length; i += 1) {
        if (list[i].id === saved) { return i; }
      }
    }
    return 0;
  }

  function currentItem() {
    var vis = visible();
    if (!vis.length) { return null; }
    return vis[indexOfCurrent(vis)];
  }

  function clamp() {
    var vis = visible();
    var index = indexOfCurrent(vis);
    if (index < 0) { return; }
    state.pos[state.list] = vis[index].id;
  }

  function persistPosition() { writeJson(POS_KEY, state.pos); }

  // ------------------------------------------------------------------ counting
  function outcomeTally(kind) {
    var counts = { pass: 0, fail: 0, incomplete: 0, total: LISTS[kind].length };
    LISTS[kind].forEach(function (item) {
      counts[outcomeOf(item).outcome] += 1;
    });
    return counts;
  }

  // How many cards answered fail on each question: after fifteen cards this is what shows which
  // question is doing the work.
  function lineTally(kind) {
    var labels = QLABELS[kind];
    var counts = [];
    var i;
    for (i = 0; i < labels.length; i += 1) {
      counts.push({ pass: 0, fail: 0, cannot: 0, blank: 0 });
    }
    LISTS[kind].forEach(function (item) {
      var entry = state.answers[item.id] || {};
      for (var line = 1; line <= labels.length; line += 1) {
        var answer = entry[String(line)];
        if (answer === 'pass') { counts[line - 1].pass += 1; }
        else if (answer === 'fail') { counts[line - 1].fail += 1; }
        else if (answer === 'cannot') { counts[line - 1].cannot += 1; }
        else { counts[line - 1].blank += 1; }
      }
    });
    return counts;
  }

  // ------------------------------------------------------------------ rendering
  function toneClass(tone) {
    return tone ? ' ' + tone : '';
  }

  function evidenceHtml(row) {
    var value = row.href
      ? '<a href="' + esc(row.href) + '" rel="noopener noreferrer" target="_blank">' +
        esc(row.value) + '</a>'
      : esc(row.value);
    return '<div class="evrow"><span class="evlabel">' + esc(row.label) + '</span> ' +
      '<span class="evval' + toneClass(row.tone) + '">' + value + '</span></div>';
  }

  function autoHtml(computed) {
    if (!computed) { return ''; }
    return '<p class="autoline' + toneClass(computed.tone) + '">' +
      '<span class="pill pill-' + (computed.tone === 'bad' ? 'fail' :
        (computed.tone === 'ok' ? 'pass' : 'cannot')) + '">answered by data</span> ' +
      esc(computed.text) + '</p>';
  }

  function lineHtml(item, index, entry) {
    var number = index + 1;
    var question = item.questions[index];
    var current = (entry && entry[String(number)]) || null;
    var buttons = ANSWERS.map(function (answer) {
      var pressed = current === answer ? 'true' : 'false';
      return '<button type="button" class="abtn a-' + answer + '" data-answer="' + answer +
        '" data-line="' + number + '" tabindex="-1" aria-pressed="' + pressed + '">' +
        ANSWER_LABEL[answer] + '</button>';
    }).join('');
    var stateLine = current
      ? 'Answered: <strong>' + ANSWER_LABEL[current] + '</strong>' +
        (current === 'cannot' ? ' - this line will not count as a pass' : '')
      : 'Not answered yet. Nothing is pre-selected.';
    return '<li class="qline" id="line-' + number + '" data-line="' + number + '" tabindex="0"' +
      ' role="group" aria-labelledby="line-' + number + '-q" aria-keyshortcuts="p f u">' +
      '<p><span class="qnum">' + number + '</span>' +
      '<span class="qtext" id="line-' + number + '-q">' + esc(QLABELS[item.kind][index]) +
      '</span></p>' +
      '<div class="qev">' + question.evidence.map(evidenceHtml).join('') + '</div>' +
      autoHtml(question.auto) +
      '<div class="answers" role="group" aria-label="Answer for question ' + number + '">' +
      buttons + '</div>' +
      '<p class="qstate">' + stateLine + '</p>' +
      '</li>';
  }

  function flagsHtml(item) {
    if (!item.flags || !item.flags.length) { return ''; }
    var rows = item.flags.map(function (flag) {
      return '<li><span class="flag-kind">' + esc(flag.headline) + '.</span> ' +
        esc(flag.detail) + (flag.raw ? ' <span class="note">(' + esc(flag.raw) + ')</span>' : '') +
        '</li>';
    }).join('');
    return '<div class="flags" role="note" aria-label="Warnings computed from our data">' +
      '<h3>Check this before you start</h3><ul>' + rows + '</ul>' +
      '<p class="note">Computed from the rows we hold, not written by hand. The strength comparison ' +
      'is a heuristic: mass units only (mg, mcg, g, iu, %), grams normalised to milligrams.</p></div>';
  }

  function outcomeHtml(item) {
    var result = outcomeOf(item);
    return '<div class="outcome outcome-' + result.outcome + '">' +
      '<h3>Outcome: ' + outcomePill(result) + ' <span class="note">computed from the ticks, ' +
      'never asked for</span></h3>' +
      '<p>' + esc(outcomeSentence(result)) + '</p></div>';
  }

  function openLabel(item) {
    var links = linksOf(item).length;
    if (item.kind === 'licence') {
      return links ? 'Open the register page (1 tab)' : 'No register page recorded';
    }
    return 'Open ' + links + ' shop page' + (links === 1 ? '' : 's') + ' (' + links + ' tab' +
      (links === 1 ? '' : 's') + ')';
  }

  function linksOf(item) {
    if (item.kind === 'licence') {
      var out = [];
      if (item.register && item.register.url) { out.push(item.register.url); }
      return out;
    }
    var urls = [];
    var seen = {};
    item.rows.forEach(function (row) {
      if (row.url && !seen[row.url]) { seen[row.url] = true; urls.push(row.url); }
    });
    return urls;
  }

  function licenceCard(item, entry) {
    var reg = item.register;
    var expiryTone = item.expiry_passed ? 'bad' : '';
    var expiry = text(reg.expiry_date, 'not read');
    var shops = item.listings.map(function (row) {
      var link = row.url
        ? '<a href="' + esc(row.url) + '" rel="noopener noreferrer" target="_blank">' +
          esc(row.shop) + '</a>'
        : esc(row.shop) + ' <span class="note">(no page recorded)</span>';
      return '<li>' + link + ' \u2014 ' + money(row.price) + ' \u2014 ' +
        esc(text(row.title, '')) + '</li>';
    }).join('');
    var reasons = item.reasons.length
      ? '<ul class="shoplist">' + item.reasons.map(function (word) {
        return '<li>' + esc(word) + '</li>';
      }).join('') + '</ul>'
      : '<p>listed for review</p>';

    return '' +
      '<p class="pos">Licence card \u00b7 registration ' + esc(text(item.nrn, 'none')) + '</p>' +
      '<h2 class="item-title" id="item-title">' + esc(item.name) + '</h2>' +
      '<p class="sub">' + esc(text(item.strength, 'strength not recorded')) + ' \u00b7 ' +
      esc(text(item.form, 'form not recorded')) + ' \u00b7 expiry ' +
      '<span class="' + (expiryTone ? 'badline' : '') + '">' + esc(expiry) + '</span></p>' +
      '<p class="note">Why it is on the list: ' + reasons + '</p>' +
      flagsHtml(item) +
      '<p class="note">Five questions. Pass on line 5 means the register does not contradict ' +
      'itself, so every line points the same way: Pass is good, Fail is a finding.</p>' +
      '<ol class="qlist">' + item.questions.map(function (question, index) {
        return lineHtml(item, index, entry);
      }).join('') + '</ol>' +
      '<h3>Who sells it</h3>' +
      '<p class="note">' + esc(item.listing_count) + ' listing' +
      (item.listing_count === 1 ? '' : 's') + ' from ' + esc(item.shop_count) + ' shop' +
      (item.shop_count === 1 ? '' : 's') + ', priced ' + money(item.min_price) + ' to ' +
      money(item.max_price) + '.</p>' +
      '<ul class="shoplist">' + shops + '</ul>' +
      '<p><button type="button" id="open-sources" tabindex="0">' + openLabel(item) + '</button></p>' +
      '<p class="hint">The register page is the one this project actually fetched and stored. If it ' +
      'does not open, the link is wrong - say so in the note rather than working around it.</p>' +
      outcomeHtml(item) +
      '<p class="hint">The table behind every row, for a reader who wants it before judging:</p>' +
      '<div class="tablewrap" role="region" aria-label="What the register says" tabindex="0">' +
      '<table><caption>The register row this card was built from.</caption>' +
      '<tbody>' +
      '<tr><th scope="row">Product name</th><td>' + esc(text(reg.product_name, 'not read')) +
      '</td></tr>' +
      '<tr><th scope="row">Brand</th><td>' + esc(text(reg.brand_name, 'not read')) + '</td></tr>' +
      '<tr><th scope="row">Strength</th><td>' + esc(text(reg.strength, 'not stated')) + '</td></tr>' +
      '<tr><th scope="row">Dosage form</th><td>' + esc(text(reg.form, 'not stated')) + '</td></tr>' +
      '<tr><th scope="row">Applicant</th><td>' + esc(text(reg.applicant, 'not read')) + '</td></tr>' +
      '<tr><th scope="row">Status</th><td>' + esc(text(reg.status, 'not read')) + '</td></tr>' +
      '<tr><th scope="row">Approval date</th><td>' + esc(text(reg.approval_date, 'not read')) +
      '</td></tr>' +
      '<tr><th scope="row">Expiry date</th><td>' + esc(expiry) + '</td></tr>' +
      '<tr><th scope="row">Pack described</th><td>' +
      esc(text(reg.pack_description, 'not read')) + '</td></tr>' +
      '</tbody></table></div>';
  }

  function packCard(item, entry) {
    var rows = item.rows.map(function (row) {
      var link = row.url
        ? '<a href="' + esc(row.url) + '" rel="noopener noreferrer" target="_blank">open page</a>'
        : '<span class="note">no page recorded</span>';
      var pack = (row.pack_size === null || row.pack_size === undefined)
        ? '<span class="badline">not read</span>'
        : esc(row.pack_size) + (row.pack_unit ? ' ' + esc(row.pack_unit) : '');
      var stock = row.in_stock === true ? 'in stock'
        : (row.in_stock === false ? 'out of stock' : 'stock not read');
      return '<tr>' +
        '<th scope="row">' + esc(row.shop) + '</th>' +
        '<td class="num">' + money(row.price) + '</td>' +
        '<td>' + pack + '</td>' +
        '<td class="num">' + (row.unit_price === null ? '<span class="badline">not read</span>' :
          money(row.unit_price, 4)) + '</td>' +
        '<td>' + esc(stock) + '</td>' +
        '<td class="title">' + esc(text(row.title, '')) + '</td>' +
        '<td>' + link + '</td>' +
        '</tr>';
    }).join('');

    var licenceLine = item.licence === 'active'
      ? '<span class="okline">active</span>'
      : (item.licence === 'not active' ? '<span class="badline">not active</span>' :
        '<span class="note">not read</span>');

    return '' +
      '<p class="pos">Pack card \u00b7 ' + esc(item.state) + ' \u00b7 ' +
      esc(item.shops_quoting) + ' shops quoting</p>' +
      '<h2 class="item-title" id="item-title">' + esc(item.name) + '</h2>' +
      '<p class="sub">' + esc(text(item.strength, 'strength not recorded')) + ' \u00b7 ' +
      esc(text(item.form, 'form not recorded')) + ' \u00b7 registration ' +
      esc(text(item.nrn, 'none recorded')) + ' \u00b7 licence ' + licenceLine + '</p>' +
      flagsHtml(item) +
      '<p class="note">Six questions. Two of them - the pack count and whether these are two ' +
      'different shops - are already answered by our own rows and are marked "answered by data". ' +
      'Confirm them with your eyes; nothing is pre-selected.</p>' +
      '<ol class="qlist">' + item.questions.map(function (question, index) {
        return lineHtml(item, index, entry);
      }).join('') + '</ol>' +
      '<h3 id="shops-heading">What each shop publishes</h3>' +
      '<div class="tablewrap" role="region" aria-labelledby="shops-heading" tabindex="0">' +
      '<table><caption>One row per shop listing. Pack size is what the page said, or ' +
      '<span class="badline">not read</span> when it could not be parsed from the page.</caption>' +
      '<thead><tr><th scope="col">Shop</th><th scope="col">Price</th>' +
      '<th scope="col">Pack size</th><th scope="col">Price per unit</th>' +
      '<th scope="col">Stock</th><th scope="col">What the shop calls it</th>' +
      '<th scope="col">Page</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>' +
      '<p><button type="button" id="open-sources" tabindex="0">' + openLabel(item) +
      '</button></p>' +
      '<p class="hint">Your browser opens one tab per page, all from this one press. If it blocks ' +
      'them, allow pop-ups for this page and press again.</p>' +
      outcomeHtml(item);
  }

  function emptyCard() {
    var counts = outcomeTally(state.list);
    var message = counts.incomplete === 0
      ? 'Every card in this worklist has an outcome. Show all to review them.'
      : 'Nothing matches this filter.';
    return '<div class="card"><p class="item-title">Nothing left here</p>' +
      '<p>' + esc(message) + '</p>' +
      '<p><button type="button" data-filter="all" tabindex="0">Show all ' +
      esc(counts.total) + ' cards</button></p></div>';
  }

  function tallyTable(kind) {
    var counts = lineTally(kind);
    var labels = QLABELS[kind];
    var body = labels.map(function (label, index) {
      var row = counts[index];
      return '<tr><th scope="row" class="num">' + (index + 1) + '</th><td>' + esc(label) +
        '</td><td class="num">' + row.pass + '</td><td class="num">' + row.fail +
        '</td><td class="num">' + row.cannot + '</td><td class="num">' + row.blank + '</td></tr>';
    }).join('');
    return '<div class="tablewrap" role="region" aria-label="Per-line tally" tabindex="0">' +
      '<table class="tally"><caption>Per-line tally for this worklist: how many cards answered ' +
      'each way. After fifteen cards this is what shows which question is doing the work.</caption>' +
      '<thead><tr><th scope="col">#</th><th scope="col">Question</th>' +
      '<th scope="col">Pass</th><th scope="col">Fail</th><th scope="col">Cannot tell</th>' +
      '<th scope="col">Not answered</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function renderHeader() {
    var counts = outcomeTally(state.list);
    var other = outcomeTally(state.list === 'licence' ? 'pack' : 'licence');
    els.progress.innerHTML =
      '<strong>' + esc(counts.total - counts.incomplete) + ' of ' + esc(counts.total) +
      ' cards have an outcome</strong> \u00b7 pass ' + esc(counts.pass) + ' \u00b7 fail ' +
      esc(counts.fail) + ' \u00b7 incomplete ' + esc(counts.incomplete) +
      '<span class="note"> The other worklist: ' + esc(other.total - other.incomplete) + ' of ' +
      esc(other.total) + ' answered.</span>';
    els.tabLicence.textContent = 'Licence \u2014 ' + LISTS.licence.length + ' cards';
    els.tabPack.textContent = 'Pack \u2014 ' + LISTS.pack.length + ' cards';
    els.tabLicence.setAttribute('aria-pressed', state.list === 'licence' ? 'true' : 'false');
    els.tabPack.setAttribute('aria-pressed', state.list === 'pack' ? 'true' : 'false');
    els.tally.innerHTML = tallyTable(state.list);
  }

  function renderFilters() {
    var all = currentList();
    var counts = {
      all: all.length,
      open: all.filter(function (item) { return formulaOpen(item); }).length,
      fail: all.filter(function (item) { return outcomeOf(item).outcome === 'fail'; }).length
    };
    var buttons = els.filters.querySelectorAll('button');
    Array.prototype.forEach.call(buttons, function (button) {
      var filter = button.getAttribute('data-filter');
      button.textContent = FILTER_LABEL[filter] + ' (' + counts[filter] + ')';
      button.setAttribute('aria-pressed', state.filter === filter ? 'true' : 'false');
    });
  }

  function formulaOpen(item) { return outcomeOf(item).outcome === 'incomplete'; }

  function renderNote(item) {
    if (!item) {
      els.note.value = '';
      els.note.removeAttribute('data-item');
      els.note.disabled = true;
      els.openNote.disabled = true;
      return;
    }
    els.note.disabled = false;
    els.openNote.disabled = false;
    if (els.note.getAttribute('data-item') === item.id) { return; }
    els.note.setAttribute('data-item', item.id);
    els.note.value = noteOf(item);
  }

  function render(wantFocus) {
    clamp();
    renderHeader();
    renderFilters();
    var item = currentItem();
    if (!item) {
      els.card.innerHTML = emptyCard();
      els.position.textContent = '';
      renderNote(null);
      return;
    }
    var vis = visible();
    var index = indexOfCurrent(vis);
    var entry = entryOf(item);
    var result = outcomeOf(item);
    state.focus = Math.min(Math.max(state.focus || 1, 1), item.questions.length);
    els.position.innerHTML = '<span class="sr-only">Position. </span>Card ' + (index + 1) + ' of ' +
      vis.length + ' in this filter (' + FILTER_LABEL[state.filter].toLowerCase() + ') \u00b7 ' +
      (index + 1) + ' of ' + currentList().length + ' overall \u00b7 ' + outcomePill(result);
    els.card.innerHTML = item.kind === 'licence' ? licenceCard(item, entry) : packCard(item, entry);
    renderNote(item);
    markFocused();
    if (wantFocus) { focusLine(state.focus, false); }
  }

  function markFocused() {
    var lines = els.card.querySelectorAll('.qline');
    Array.prototype.forEach.call(lines, function (line) {
      var isFocused = Number(line.getAttribute('data-line')) === state.focus;
      line.classList.toggle('is-focused', isFocused);
    });
  }

  function announce(message) {
    els.live.textContent = message;
  }

  function say(message) {
    els.exportMessage.textContent = message;
  }

  // ------------------------------------------------------------------ moving and answering
  function setFocus(line, doFocus) {
    var item = currentItem();
    if (!item) { return; }
    var total = item.questions.length;
    if (line < 1) { line = 1; announce('That is the first line.'); }
    if (line > total) { line = total; announce('That is the last line. Press ] for the next card.'); }
    state.focus = line;
    markFocused();
    if (doFocus !== false) { focusLine(line, true); }
    announce('Question ' + line + ' of ' + total + '. ' + QLABELS[item.kind][line - 1] +
      '. ' + (answerOf(item, line) ? 'Answered ' + ANSWER_LABEL[answerOf(item, line)] + '.' :
        'Not answered.'));
  }

  function focusLine(line, scroll) {
    var el = $('line-' + line);
    if (!el) { return; }
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    if (scroll && el.scrollIntoView) { el.scrollIntoView({ block: 'nearest' }); }
  }

  function moveCard(step) {
    var vis = visible();
    if (!vis.length) { return false; }
    var here = indexOfCurrent(vis);
    var target = here + step;
    if (target < 0 || target >= vis.length) {
      announce(step > 0 ? 'That is the last card in this filter.' : 'First card in this filter.');
      return false;
    }
    state.pos[state.list] = vis[target].id;
    persistPosition();
    state.focus = 1;
    render();
    var item = currentItem();
    if (item) {
      var index = indexOfCurrent(visible());
      announce('Card ' + (index + 1) + ' of ' + visible().length + ': ' + item.name + '. ' +
        outcomeOf(item).outcome + '.');
    }
    return true;
  }

  // p / f / u: set the focused line, then move to the next line, and from the last line to the next
  // card. The next card is chosen from the list as it stands after the answer, so an answer that
  // completes a card under the "Open" filter moves past it instead of showing it again.
  function answerFocused(answer) {
    var item = currentItem();
    if (!item) { return; }
    var line = state.focus || 1;
    setAnswer(item, line, answer);
    var total = item.questions.length;
    if (line < total) {
      state.focus = line + 1;
      render(true);
      announce(QLABELS[item.kind][line - 1] + ' marked ' + ANSWER_LABEL[answer] +
        '. Question ' + (line + 1) + ' of ' + total + ': ' + QLABELS[item.kind][line] + '.');
      return;
    }
    var result = outcomeOf(item);
    var moved = moveCard(1);
    if (moved) {
      announce('Last line marked ' + ANSWER_LABEL[answer] + '. Card outcome ' + result.outcome +
        '. Now showing card ' + (indexOfCurrent(visible()) + 1) + ' of ' + visible().length +
        ': ' + currentItem().name + '.');
    } else {
      render(true);
      announce('Last line marked ' + ANSWER_LABEL[answer] + '. Card outcome ' + result.outcome +
        '. No card after this one.');
    }
  }

  function answerLine(line, answer) {
    var item = currentItem();
    if (!item) { return; }
    state.focus = line;
    setAnswer(item, line, answer);
    render();
    announce('Question ' + line + ' marked ' + ANSWER_LABEL[answer] + '. Card outcome ' +
      outcomeOf(item).outcome + '.');
  }

  function clearCard() {
    var item = currentItem();
    if (!item) { return; }
    delete state.answers[item.id];
    writeJson(STORE_KEY, state.answers);
    state.focus = 1;
    render();
    announce('Every answer and the note cleared for ' + item.name + '.');
  }

  function openSources() {
    var item = currentItem();
    if (!item) { return; }
    var urls = linksOf(item);
    if (!urls.length) {
      announce('This card has no page recorded.');
      return;
    }
    var opened = 0;
    urls.forEach(function (url) {
      try {
        var win = window.open(url, '_blank');
        if (win) { opened += 1; }
      } catch (e) { /* counted as blocked below */ }
    });
    var message = 'Asked for ' + urls.length + ' page' + (urls.length === 1 ? '' : 's') +
      ' in new tabs';
    if (opened < urls.length) {
      message += '. The browser blocked ' + (urls.length - opened) +
        ': allow pop-ups for this page and try again.';
    } else {
      message += '.';
    }
    announce(message);
  }

  function focusNote() {
    if (els.note.disabled) { return; }
    els.note.focus();
    announce('Note field focused. Escape returns to the checklist.');
  }

  function setFilter(filter) {
    state.filter = filter;
    state.focus = 1;
    render();
    var vis = visible();
    announce(FILTER_LABEL[filter] + ': ' + vis.length + ' card' + (vis.length === 1 ? '' : 's') + '.');
  }

  function setList(kind) {
    state.list = kind;
    state.filter = 'all';
    state.focus = 1;
    render();
    announce('Worklist: ' + kind + ', ' + LISTS[kind].length + ' cards.');
  }

  // ------------------------------------------------------------------ export
  function buildExport() {
    var out = {
      checklist_version: 2,
      generated_utc: new Date().toISOString(),
      data_as_of: DATA.meta.data_as_of,
      data_built_utc: DATA.meta.built_utc,
      note: 'One entry per card. Each numbered key is that line of the checklist: pass, fail or ' +
        'cannot. The outcome is recomputed from those answers and is never typed by hand.',
      cards: {},
      line_fail_counts: {}
    };
    ['licence', 'pack'].forEach(function (kind) {
      out.line_fail_counts[kind] = {};
      lineTally(kind).forEach(function (row, index) {
        out.line_fail_counts[kind][String(index + 1)] = row.fail;
      });
    });
    ['licence', 'pack'].forEach(function (kind) {
      LISTS[kind].forEach(function (item) {
        var entry = state.answers[item.id];
        if (!entry) { return; }
        var card = {};
        var answered = 0;
        for (var line = 1; line <= item.questions.length; line += 1) {
          if (entry[String(line)]) { card[String(line)] = entry[String(line)]; answered += 1; }
        }
        var note = String(entry.note || '').trim();
        if (!answered && !note) { return; }
        card.note = note;
        card.outcome = outcomeOf(item).outcome;
        card.at = entry.at || null;
        out.cards[item.id] = card;
      });
    });
    return out;
  }

  function exportText() { return JSON.stringify(buildExport(), null, 2); }

  function download() {
    var text = exportText();
    var blob = new Blob([text], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = 'verify-results.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    say('Saved verify-results.json (' + text.length + ' characters).');
    announce('Export saved.');
  }

  function legacyCopy(text) {
    els.details.open = true;
    els.json.value = text;
    els.json.focus();
    els.json.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    if (ok) {
      say('Copied to the clipboard.');
      announce('Export copied to the clipboard.');
    } else {
      say('This browser would not copy automatically. The JSON is shown below: select it and copy.');
      announce('Copy failed. The JSON is shown below the button.');
    }
  }

  function copy() {
    var text = exportText();
    els.json.value = text;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        say('Copied to the clipboard (' + text.length + ' characters).');
        announce('Export copied to the clipboard.');
      }, function () { legacyCopy(text); });
    } else {
      legacyCopy(text);
    }
  }

  // ------------------------------------------------------------------ events
  function oldAnswersPresent() {
    return OLD_KEYS.some(function (key) {
      try {
        var raw = window.localStorage.getItem(key);
        if (!raw) { return false; }
        var parsed = JSON.parse(raw);
        return !!(parsed && typeof parsed === 'object' && Object.keys(parsed).length);
      } catch (e) { return false; }
    });
  }

  function onKey(event) {
    var tag = (event.target && event.target.tagName || '').toLowerCase();
    var typing = tag === 'textarea' || tag === 'input' || tag === 'select' ||
      (event.target && event.target.isContentEditable);
    if (typing) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.target.blur();
        announce('Left the note field. The checklist keys work again.');
      }
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) { return; }

    var key = event.key;
    if (key === 'ArrowDown') { event.preventDefault(); setFocus(state.focus + 1, true); return; }
    if (key === 'ArrowUp') { event.preventDefault(); setFocus(state.focus - 1, true); return; }
    if (key === 'p' || key === 'P') { event.preventDefault(); answerFocused('pass'); return; }
    if (key === 'f' || key === 'F') { event.preventDefault(); answerFocused('fail'); return; }
    if (key === 'u' || key === 'U') { event.preventDefault(); answerFocused('cannot'); return; }
    if (key === 'o' || key === 'O') { event.preventDefault(); openSources(); return; }
    if (key === 'n' || key === 'N') { event.preventDefault(); focusNote(); return; }
    if (key === '[') { event.preventDefault(); moveCard(-1); return; }
    if (key === ']') { event.preventDefault(); moveCard(1); return; }
    if (key === 'Backspace') { event.preventDefault(); clearCard(); }
  }

  function wire() {
    els.card = $('card');
    els.position = $('position');
    els.progress = $('progress');
    els.filters = $('filters');
    els.tally = $('tally');
    els.live = $('live');
    els.tabLicence = $('tab-licence');
    els.tabPack = $('tab-pack');
    els.note = $('note');
    els.openNote = $('open-note');
    els.exportMessage = $('export-message');
    els.details = $('json-details');
    els.json = $('json-out');
    els.storageWarning = $('storage-warning');
    els.oldNotice = $('v1-notice');

    els.tabLicence.addEventListener('click', function () { setList('licence'); });
    els.tabPack.addEventListener('click', function () { setList('pack'); });

    els.filters.addEventListener('click', function (event) {
      var button = event.target.closest('[data-filter]');
      if (button) { setFilter(button.getAttribute('data-filter')); }
    });

    els.card.addEventListener('click', function (event) {
      var filterButton = event.target.closest('[data-filter]');
      if (filterButton) { setFilter(filterButton.getAttribute('data-filter')); return; }
      if (event.target.closest('#open-sources')) { openSources(); return; }
      var answerButton = event.target.closest('[data-answer]');
      if (answerButton) {
        answerLine(Number(answerButton.getAttribute('data-line')),
          answerButton.getAttribute('data-answer'));
      }
    });

    // Clicking a line puts the highlight there, so the keys and the mouse agree on which line is live.
    els.card.addEventListener('focusin', function (event) {
      var line = event.target.closest ? event.target.closest('.qline') : null;
      if (!line) { return; }
      var number = Number(line.getAttribute('data-line'));
      if (number && number !== state.focus) { state.focus = number; markFocused(); }
    });

    els.openNote.addEventListener('click', focusNote);

    els.note.addEventListener('input', function () {
      var id = els.note.getAttribute('data-item');
      if (!id) { return; }
      var item = BY_ID[id];
      if (!item) { return; }
      setNote(item, els.note.value);
    });

    els.note.addEventListener('blur', function () {
      var id = els.note.getAttribute('data-item');
      if (!id) { return; }
      renderHeader();
      renderFilters();
    });

    $('download').addEventListener('click', download);
    $('copy').addEventListener('click', copy);
    $('clear-card').addEventListener('click', clearCard);
    els.details.addEventListener('toggle', function () {
      if (els.details.open) { els.json.value = exportText(); }
    });

    document.addEventListener('keydown', onKey);
  }

  // Order matters: the elements must exist before loading touches them, because a browser that
  // refuses local storage reports that through the warning element.
  wire();
  indexItems();
  load();
  if (oldAnswersPresent()) {
    els.oldNotice.hidden = false;
  }
  render();
  updateStorageWarning();
})();
"""

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verification desk - licence and pack checklists</title>
<link rel="icon" href="data:,">
<style>__CSS__</style>
</head>
<body>
<a class="skip" href="#main">Skip to the checklist</a>
<div class="wrap">
<header>
<h1>Verification desk</h1>
<div class="banner" role="note">
<p><strong>What this is.</strong> A human observation sheet. Each card is a short numbered
checklist: open the sources, read them, and answer Pass, Fail or Cannot tell on each line. The
card's outcome is worked out from your ticks - any Fail is a fail, every Pass is a pass, anything
else is incomplete - and it is never asked for.</p>
<p><strong>Keys:</strong> <strong>&uarr;</strong> and <strong>&darr;</strong> move between questions,
<strong>p</strong> pass, <strong>f</strong> fail, <strong>u</strong> cannot tell, and each of those
moves to the next line, then to the next card. <strong>o</strong> opens the sources,
<strong>n</strong> the note, <strong>Esc</strong> leaves it, <strong>[</strong> and
<strong>]</strong> change card. Nothing here needs a mouse.</p>
</div>
<p class="stamp note">Built __GENERATED__ from the project database. The newest price was read at
__PRICES_AS_OF__ and the register at __REGISTER_AS_OF__. The export's <code>data_as_of</code> is the
older of those two, so an export can never look fresher than its stalest source. There are
__LISTINGS__ shop listings in the database at that reading.</p>
<p class="note">Register coverage, same breath: a status exists for <strong>__STATUS_READ__ of
__REGS__</strong> registrations (__COVERAGE__%). The rest have never had their detail page read, so
a card whose status reads &ldquo;not read&rdquo; is a gap in our reading, not a finding about the
medicine.</p>
<p class="notice" id="v1-notice" hidden>Older single-verdict answers from the previous version of
this page are still stored in this browser. They are <strong>not counted</strong> here and will not
appear in the export: this version records one answer per question, and an old one-verdict-per-card
record cannot be turned into one without inventing answers.</p>
<p id="storage-warning" class="banner" role="note" hidden></p>
</header>
<main id="main">
<h2>Which worklist</h2>
<div class="switcher" role="group" aria-label="Which worklist">
<button type="button" id="tab-licence" aria-pressed="true">Licence</button>
<button type="button" id="tab-pack" aria-pressed="false">Pack</button>
</div>
<p id="progress" class="pos"></p>
<div class="filters" id="filters" role="group" aria-label="Show only">
<button type="button" data-filter="all" aria-pressed="true">All</button>
<button type="button" data-filter="open" aria-pressed="false">Open</button>
<button type="button" data-filter="fail" aria-pressed="false">Fail</button>
</div>
<p id="live" class="sr-only" role="status" aria-live="polite"></p>
<p id="position" class="pos"></p>
<div id="tally"></div>
<div id="card"></div>

<section aria-labelledby="note-heading">
<h2 id="note-heading">Your note on this card</h2>
<label for="note">Anything the lines above cannot capture (optional)</label>
<textarea id="note" rows="3" spellcheck="true"></textarea>
<p class="hint">Saved in this browser as you type, one entry per card. If a page will not open, say
so here rather than guessing what it says.</p>
<p><button type="button" id="open-note">Put the cursor in the note (n)</button>
<button type="button" id="clear-card">Clear every answer on this card (Backspace)</button></p>
</section>

<section aria-labelledby="export-heading">
<h2 id="export-heading">Take the answers out</h2>
<p>Nothing is sent anywhere. The download is a file called <code>verify-results.json</code>; the copy
button puts the same text on the clipboard. Both carry the time they were made, the
<code>data_as_of</code> stamp, and every line's answer with the outcome computed from them.</p>
<p>
<button type="button" id="download">Download verify-results.json</button>
<button type="button" id="copy">Copy the JSON to the clipboard</button>
</p>
<p id="export-message" class="hint" role="status" aria-live="polite"></p>
<details id="json-details">
<summary>Show the JSON (for copying by hand if the buttons do not work)</summary>
<label for="json-out">The export, as it would be saved</label>
<textarea id="json-out" rows="12" readonly></textarea>
</details>
</section>

<section aria-labelledby="keys-heading">
<h2 id="keys-heading">Keys</h2>
<p>Nothing here needs a mouse, and nothing needs the network. Tab works as it does on any page; the
keys below are shortcuts on top of that, and do nothing while the cursor is in the note field.</p>
<div class="tablewrap" role="region" aria-labelledby="keys-heading" tabindex="0">
<table class="keys">
<caption>One key per row.</caption>
<thead><tr><th scope="col">Key</th><th scope="col">What it does</th></tr></thead>
<tbody>
<tr><th scope="row">&uarr;</th><td>Previous question on this card</td></tr>
<tr><th scope="row">&darr;</th><td>Next question on this card</td></tr>
<tr><th scope="row">p</th><td>Pass on the focused question, then move to the next question</td></tr>
<tr><th scope="row">f</th><td>Fail on the focused question, then move on</td></tr>
<tr><th scope="row">u</th><td>Cannot tell on the focused question, then move on</td></tr>
<tr><th scope="row">&mdash;</th><td>On the last question, any of p / f / u moves to the next
card</td></tr>
<tr><th scope="row">&larr; &rarr;</th><td>Not used: the arrows move between questions, not
cards</td></tr>
<tr><th scope="row">[</th><td>Previous card, without judging anything</td></tr>
<tr><th scope="row">]</th><td>Next card, without judging anything</td></tr>
<tr><th scope="row">o</th><td>Open the sources for this card, one tab each</td></tr>
<tr><th scope="row">n</th><td>Put the cursor in the note</td></tr>
<tr><th scope="row">Esc</th><td>Leave the note</td></tr>
<tr><th scope="row">Backspace</th><td>Clear every answer and the note on this card</td></tr>
</tbody>
</table>
</div>
<p class="hint">Clicking a Pass / Fail / Cannot tell button sets that line and leaves the highlight
where it is. The keys advance; the mouse does not have to.</p>
</section>

<section aria-labelledby="about-heading">
<h2 id="about-heading">What this page does not do</h2>
<ul>
<li>It does not read the pharmacy or register pages for you. It only opens them; the judgement is
yours, and it is the thing the project has not yet done by hand.</li>
<li>It does not decide whether a line passes. It does compute two things and shows them beside the
question - whether the two rows are different shops, and whether the pack counts agree - because
those are answered by our own rows.</li>
<li>It does not write to the database, and it holds no connection to it. It was built from one
read-only read of it, at the time printed above.</li>
<li>It cannot tell whether a page has changed since it was scraped. A page you open today may differ
from the copy this card was built from; if it does, the answer is about what you saw, and the note
is where the difference belongs.</li>
<li>It does not resume on another machine. Answers live in this browser's local storage for this
file; moving them means exporting.</li>
</ul>
<p class="note">The strength warning is a heuristic: mass units only (mg, mcg, g, iu, %), grams
normalised to milligrams. It ignores volumes and says nothing when one side states no strength. Do
not read a clean card as proof that two medicines are the same.</p>
</section>
</main>
<footer>
<p>Built by <code>scripts/build_verify_desk.py</code> from the project database, read-only. Two
worklists: <strong>__LICENCE_COUNT__ licence cards</strong> (products whose registration is not
Active or has expired) and <strong>__PACK_COUNT__ pack cards</strong> (products two shops both
price). Times in UTC. Prices in naira. One file, no external stylesheet, script, font or image, so
it opens from a double-click with no connection.</p>
</footer>
</div>
<script id="desk-data" type="application/json">__DATA__</script>
<script>__JS__</script>
</body>
</html>
"""


def esc_html(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def meta_stamp(value: str | None) -> str:
    return "an unknown time" if not value else value


def render_document(items: dict[str, list[dict[str, Any]]], meta: dict[str, Any]) -> str:
    payload = {
        "meta": meta,
        "licence": items["licence"],
        "pack": items["pack"],
    }
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # A literal `</script` inside the JSON would close the block early. Escaping the slash is the
    # JSON-legal way to prevent that; the browser still parses it back to `</`.
    data_json = data_json.replace("</", "<\\/")

    document = (SHELL
                .replace("__CSS__", CSS)
                .replace("__JS__", JS)
                .replace("__DATA__", data_json))
    replacements = {
        "__GENERATED__": esc_html(meta["built_utc"]),
        "__PRICES_AS_OF__": esc_html(meta_stamp(meta["prices_as_of"])),
        "__REGISTER_AS_OF__": esc_html(meta_stamp(meta["register_as_of"])),
        "__LISTINGS__": esc_html(f'{meta["latest_listings"]:,}'),
        "__STATUS_READ__": esc_html(f'{meta["regs_with_status"]:,}'),
        "__REGS__": esc_html(f'{meta["regs"]:,}'),
        "__COVERAGE__": esc_html(meta["coverage_pct"]),
        "__LICENCE_COUNT__": esc_html(len(items["licence"])),
        "__PACK_COUNT__": esc_html(len(items["pack"])),
    }
    for token, value in replacements.items():
        document = document.replace(token, value)
    return document


# --------------------------------------------------------------------------- the self-check
def self_check(document: str, items: dict[str, list[dict[str, Any]]],
               expected: dict[str, int], lagos_today: date) -> tuple[int, list[str]]:
    """Prove the file the way the brief says to prove it. Returns (checks, problems).

    Each check is something that would silently break the desk: a data block the browser cannot
    parse, a count that disagrees with the query, a question with no evidence beside it, a card that
    carries an answer it was never given, a computed warning that disagrees with its own rows, a
    reference to the network that `file://` would try to follow, or a storage key from another version.
    """
    checks = 0
    problems: list[str] = []

    blocks = re.findall(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        document, re.S)
    checks += 1
    if len(blocks) != 1:
        problems.append(f"expected exactly one embedded data block, found {len(blocks)}")
        return checks, problems

    try:
        payload = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        problems.append(f"the embedded data block is not valid JSON: {exc}")
        return checks, problems
    checks += 1

    # The questions the page prints are the ones this file fixes, in this order, once.
    checks += 1
    if payload["meta"]["questions"] != {kind: list(words) for kind, words in QUESTIONS.items()}:
        problems.append("the page's question list is not the fixed list and order")

    for kind in ("licence", "pack"):
        checks += 1
        if len(payload[kind]) != expected[kind]:
            problems.append(f"{kind}: {len(payload[kind])} items embedded, {expected[kind]} rows read")
        checks += 1
        if len(payload[kind]) != len(items[kind]):
            problems.append(f"{kind}: embedded list and built list disagree")

    # Every card carries every line, every line carries evidence, and no line carries an answer.
    for kind in ("licence", "pack"):
        wanted = len(QUESTIONS[kind])
        for item in items[kind]:
            checks += 1
            if len(item["questions"]) != wanted:
                problems.append(f'{item["id"]}: {len(item["questions"])} questions, '
                                f"expected {wanted}")
            if [q["n"] for q in item["questions"]] != list(range(1, wanted + 1)):
                problems.append(f'{item["id"]}: question numbers are not 1..{wanted} in order')
            for line in item["questions"]:
                checks += 1
                if not line["evidence"]:
                    problems.append(f'{item["id"]}: question {line["n"]} has no evidence beside it')
                checks += 1
                if line["auto"] is not None and line["auto"]["tone"] not in ("ok", "bad", "muted"):
                    problems.append(f'{item["id"]}: question {line["n"]} has an unknown tone '
                                    f'{line["auto"]["tone"]!r}')
            checks += 1
            if any(key in item for key in ("outcome", "verdict", "answers", "answer")):
                problems.append(f'{item["id"]}: the payload carries an outcome or answer of its own')

    # Every licence item has a register page, and genuinely fails the rule that put it on the list.
    for item in items["licence"]:
        checks += 1
        if not item["register"]["url"]:
            problems.append(f'{item["id"]}: no register page recorded')
        checks += 1
        status = item["register"]["status"]
        expired = item["register"]["expiry_date"] is not None and \
            date.fromisoformat(item["register"]["expiry_date"]) < lagos_today
        if not (status is not None and (status != "Active" or expired)):
            problems.append(f'{item["id"]}: on the licence list but does not fail the flag rule')
        checks += 1
        if not item["listings"]:
            problems.append(f'{item["id"]}: no shop listing behind it')
        checks += 1
        if item["shop_count"] != distinct_shops(item["listings"]):
            problems.append(f'{item["id"]}: shop_count {item["shop_count"]} disagrees with the '
                            f'{distinct_shops(item["listings"])} shops in its listings')
        # The red strip is computed, not typed: recompute it from the rows and compare.
        checks += 1
        want = sum(1 for row in item["listings"]
                   if strength_contradiction(row["title"], item["strength"]))
        got = sum(1 for flag in item["flags"] if flag["kind"] == "strength_mismatch")
        if got != want:
            problems.append(f'{item["id"]}: {got} strength warnings, {want} contradicting listings')

    # Every pack item has two or more rows, each with the link a person must open.
    for item in items["pack"]:
        checks += 1
        if len(item["rows"]) < 2:
            problems.append(f'{item["id"]}: fewer than two shop rows')
        for row in item["rows"]:
            checks += 1
            if not row["url"]:
                problems.append(f'{item["id"]}: a shop row has no page recorded')
            if row["price"] is None:
                problems.append(f'{item["id"]}: a shop row has no price')
        # Fewer than two distinct shops is deliberately NOT a build failure any more: the card
        # computes Fail on line 5 and says so in the strip before the reader starts.
        checks += 1
        want = sum(1 for row in item["rows"]
                   if strength_contradiction(row["title"], item["strength"]))
        got = sum(1 for flag in item["flags"] if flag["kind"] == "strength_mismatch")
        if got != want:
            problems.append(f'{item["id"]}: {got} strength warnings, {want} contradicting rows')
        checks += 1
        same_shop = distinct_shops(item["rows"]) < 2
        if same_shop != any(flag["kind"] == "same_shop" for flag in item["flags"]):
            problems.append(f'{item["id"]}: the same-shop warning disagrees with its own rows')
        checks += 1
        line5 = item["questions"][4]["auto"]
        if line5 is None:
            problems.append(f'{item["id"]}: line 5 does not answer itself from the data')
        elif same_shop and line5["tone"] != "bad":
            problems.append(f'{item["id"]}: both rows are one shop but line 5 is not a computed Fail')

    # The version that is written is v2, and the v1 keys are only ever read to warn about them.
    checks += 1
    if "ndw.verify.answers.v2" not in document:
        problems.append("the page does not write the v2 storage key")
    checks += 1
    if "checklist_version: 2" not in document:
        problems.append("the export does not declare checklist_version 2")
    checks += 1
    if "mass units only" not in document:
        problems.append("the strength heuristic is not labelled on the page")

    # No reference to the network outside the data block. This is the property `file://` cares about:
    # a stylesheet, script, font or image at another address would be a request, and on a double-click
    # it would fail silently.
    outside = document.replace(blocks[0], "")
    checks += 1
    stray = re.findall(r"(?i)http", outside)
    if stray:
        problems.append(f"{len(stray)} 'http' occurrence(s) outside the data block")

    return checks, problems


# --------------------------------------------------------------------------- a labelled fixture
def write_fixture(path: Path) -> int:
    """Write a two-card page with synthetic rows, to prove the two computed warnings render.

    The measured data can contain neither case on demand - no comparison cell has both rows from one
    shop - so the only honest way to show that the page says "Fail - both rows are HealthPlus" before
    a key is pressed is to build one from rows that say it. It goes through the same builders and the
    same self-check as the real page, and every card says it is a fixture.
    """
    stamp = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)
    licence_products = [
        (900001, "Fixture Medicine", "400 mg", "Tablet", "04-9999", "Fixture Medicine", None,
         "400 mg", "Tablet", "Fixture Labs", "Inactive", date(2019, 3, 1), date(2024, 2, 28),
         "20 tablets", "https://example.invalid/register/04-9999", stamp, 1, 1, 1500.0, 1500.0,
         "inactive_registration"),
    ]
    licence_listings = [
        (900001, "HealthPlus", "Lagos", "Fixture Medicine 800MG Tablets x 20",
         "https://example.invalid/shop/fixture-800mg", 1500.0, True, "inactive_registration"),
    ]
    pack_cells = [
        (900002, "Fixture Medicine", "400 mg", "Tablet", "04-9998", "Lagos", 3, 2, 1500.0, 20,
         "HealthPlus", "Active", False),
    ]
    pack_rows = [
        (900002, "Lagos", "HealthPlus", "Fixture Medicine 400mg Tabs x 20", 1500.0, True, 20, "tab",
         75.0, "https://example.invalid/shop/hp-20", stamp),
        (900002, "Lagos", "HealthPlus", "Fixture Medicine 400mg Tabs x 25", 1900.0, True, 25, "tab",
         76.0, "https://example.invalid/shop/hp-25", stamp),
    ]

    today = date(2026, 11, 12)
    items = {
        "licence": build_licence(licence_products, licence_listings, today),
        "pack": build_pack(pack_cells, pack_rows),
    }
    meta = {
        "built_utc": "2026-11-12 06:00 UTC",
        "prices_as_of": "2026-11-12 01:00 UTC",
        "register_as_of": "2026-11-12 01:00 UTC",
        "data_as_of": "2026-11-12 01:00 UTC",
        "latest_listings": 2,
        "regs_with_status": 1,
        "regs": 1,
        "coverage_pct": 100.0,
        "lagos_today": str(today),
        "licence_items": 1,
        "pack_items": 1,
        "licence_listings": 1,
        "pack_shop_rows": 2,
        "fixture": True,
        "questions": {kind: list(words) for kind, words in QUESTIONS.items()},
        "heuristic": HEURISTIC_SENTENCE,
        "how_built": "scripts/build_verify_desk.py --fixture, synthetic rows, not project data",
    }
    document = render_document(items, meta)
    checks, problems = self_check(document, items, {"licence": 1, "pack": 1}, today)

    licence_flags = [flag for flag in items["licence"][0]["flags"]]
    pack_line5 = items["pack"][0]["questions"][4]["auto"]
    problems = list(problems)
    checks += 1
    if not any(flag["kind"] == "strength_mismatch" and "800 mg" in flag["detail"] and
               "400 mg" in flag["detail"] for flag in licence_flags):
        problems.append("the fixture licence card does not carry the strength warning both ways")
    checks += 1
    if "both rows are HealthPlus" not in document:
        problems.append("the same-shop answer never reaches the page")
    checks += 1
    if not (pack_line5 and pack_line5["tone"] == "bad"):
        problems.append("the fixture pack card does not compute Fail on line 5")

    if problems:
        print(f"fixture: {checks} checks, {len(problems)} failed", file=sys.stderr)
        for problem in problems[:40]:
            print("  failed:", problem, file=sys.stderr)
        return 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(document.encode("utf-8"))
    print(f"fixture: wrote {path.as_posix()} ({len(document.encode('utf-8')):,} bytes)")
    print("fixture: licence card flag -> "
          + next(flag["detail"] for flag in licence_flags if flag["kind"] == "strength_mismatch"))
    print(f"fixture: pack card line 5 -> {pack_line5['text']}")
    print(f"fixture: pack card line 4 -> {items['pack'][0]['questions'][3]['auto']['text']}")
    print(f"fixture: {checks:,} checks passed, 0 failed")
    return 0


# --------------------------------------------------------------------------- main
def main() -> int:
    if "--fixture" in sys.argv:
        index = sys.argv.index("--fixture")
        target = sys.argv[index + 1] if len(sys.argv) > index + 1 else "site/verify/demo.html"
        return write_fixture(Path(target))

    try:
        import psycopg
    except Exception as exc:  # noqa: BLE001
        print(f"psycopg is not importable: {exc}", file=sys.stderr)
        return 2

    url = ensure_database_url()
    if not url:
        print("no DATABASE_URL in the environment and none found in .env", file=sys.stderr)
        return 2

    try:
        conn = psycopg.connect(
            url,
            autocommit=True,
            connect_timeout=20,
            options="-c default_transaction_read_only=on",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"cannot connect: {type(exc).__name__}: {exc}".splitlines()[0], file=sys.stderr)
        return 2

    with conn:
        conn.execute("set statement_timeout = '120s'")

        meta_row = conn.execute(META_SQL).fetchone()
        (prices_as_of, register_as_of, latest_listings, regs_with_status, regs,
         lagos_today, database_now) = meta_row

        licence_products = conn.execute(LICENCE_PRODUCTS_SQL).fetchall()
        licence_listings = conn.execute(LICENCE_LISTINGS_SQL).fetchall()
        pack_cells = conn.execute(PACK_CELLS_SQL).fetchall()
        pack_rows = conn.execute(PACK_ROWS_SQL).fetchall()

    items = {
        "licence": build_licence(licence_products, licence_listings, lagos_today),
        "pack": build_pack(pack_cells, pack_rows),
    }
    expected = {
        "licence": len(licence_products),
        "pack": len(pack_cells),
    }

    coverage = round(100.0 * int(regs_with_status) / int(regs), 1) if int(regs) else "not known"
    # `data_as_of` is the older of the two readings: a price answer and a licence answer cannot be
    # newer than the stalest thing they were judged against.
    stamps = [value for value in (prices_as_of, register_as_of) if value is not None]
    oldest = min(stamps) if stamps else None
    meta = {
        "built_utc": iso(database_now),
        "database_now": iso(database_now),
        "prices_as_of": iso(prices_as_of),
        "register_as_of": iso(register_as_of),
        "data_as_of": iso(oldest),
        "latest_listings": int(latest_listings),
        "regs_with_status": int(regs_with_status),
        "regs": int(regs),
        "coverage_pct": coverage,
        "lagos_today": str(lagos_today),
        "licence_items": len(items["licence"]),
        "pack_items": len(items["pack"]),
        "licence_listings": sum(item["listing_count"] for item in items["licence"]),
        "pack_shop_rows": sum(len(item["rows"]) for item in items["pack"]),
        "questions": {kind: list(words) for kind, words in QUESTIONS.items()},
        "heuristic": HEURISTIC_SENTENCE,
        "how_built": (
            "scripts/build_verify_desk.py, one read-only read of the project database; licence cards "
            "come from v_suspicious_listings grouped by product, pack cards from "
            "v_cheapest_per_product_state where is_comparison"
        ),
    }

    document = render_document(items, meta)
    checks, problems = self_check(document, items, expected, lagos_today)

    if problems:
        print(f"{checks} checks, {len(problems)} failed", file=sys.stderr)
        for problem in problems[:40]:
            print("  failed:", problem, file=sys.stderr)
        print("nothing written: a desk that disagrees with its own database is not usable.",
              file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(document.encode("utf-8"))

    strength_licence = sum(1 for item in items["licence"] if item["flags"])
    strength_pack = sum(1 for item in items["pack"]
                        if any(flag["kind"] == "strength_mismatch" for flag in item["flags"]))
    same_shop_pack = sum(1 for item in items["pack"]
                         if any(flag["kind"] == "same_shop" for flag in item["flags"]))

    print(f"wrote {OUT.as_posix()} ({len(document.encode('utf-8')):,} bytes)")
    print(f"licence cards embedded: {len(items['licence'])} products, "
          f"{meta['licence_listings']} shop listings, "
          f"{len(LICENCE_QUESTIONS)} questions each")
    print(f"pack cards embedded:    {len(items['pack'])} cells, "
          f"{meta['pack_shop_rows']} shop rows, {len(PACK_QUESTIONS)} questions each")
    print(f"computed warnings: {strength_licence} licence cards and {strength_pack} pack cards carry "
          f"a strength disagreement; {same_shop_pack} pack cards have both rows from one shop")
    print(f"data as of: {meta['data_as_of']} (prices {meta['prices_as_of']}, "
          f"register {meta['register_as_of']})")
    print(f"{checks:,} checks passed, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
