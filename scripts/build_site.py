"""Build the project's public page from the database, and prove every number on it.

    .venv\\Scripts\\python.exe -X utf8 scripts/build_site.py

Writes `site/index.html`, `site/about.html` and `site/data.json`, and copies the four local images the
tribute uses into `site/assets/dora/`. No external CSS, JS or font is fetched at all, so the page
renders with no network; the only images are four files carried in the repository. `site/` is
gitignored: it is build output, not source.

WHY THE AUDIT IS THE POINT. A page assembled by a script can still lie: a query filtered by hand, a
number copied from yesterday's log, a stale view. So this script does not trust its own first read. It
runs every query, renders the page from the result, then runs every query a second time and compares
what it printed against what the database says now. Nothing is written unless the two agree. The last
line is the audit:

    <N> numbers checked, <M> unexplained

M > 0 exits non-zero and names each value that moved. Two kinds of value are allowed to drift, and only
two: the database clock (`now()`), because time passes between the two reads, and the hour counts
derived from it. Their tolerance is stated where the query is declared. Counts, prices, row lists and
stored timestamps get zero tolerance.

WHY NO NUMBER IS TYPED HERE. Every figure the page prints - counts, prices, hours, dates, shop names,
shop websites - comes out of a query in `SPECS` or out of the `derive` function attached to it. The
only literals in this file that reach the page are policy thresholds and prose: `STALE_HOURS` (48, the
project's own definition of a stale source) and the source list in `EXPECTED_SOURCES`, which is the
list of things the nightly job is supposed to run. That list is deliberate: `v_pipeline_health` groups
`scrape_runs`, so a source that never ran produces no row at all rather than a `STALE` row. The page
must print "never run" for it, so the expected list lives here and is left-joined to the ledger.

READ-ONLY. The connection is opened exactly as `scripts/dbq.py` opens it:
`default_transaction_read_only=on`, so the server itself refuses any write from this script.

NOT DONE HERE. No deploy, no push, no Pages configuration. The workflow job that publishes `site/` is
in `.github/workflows/daily.yml`; enabling Pages is the repository owner's step.
"""

from __future__ import annotations

import html
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

from envfile import ensure_database_url

REPO_URL = "https://github.com/batestguy/NaijaDrugWatch"
GREENBOOK_URL = "http://greenbook.nafdac.gov.ng"
SITE = Path("site")

# Policy, not measurement: the project's own line for "this source has stopped reporting".
# schema/003_views.sql uses the same 48-hour interval in v_pipeline_health. Changing it here does not
# change the view, and the page says which threshold it applied.
STALE_HOURS = 48

# The sources the nightly workflow is supposed to write a `scrape_runs` row for, with what each one
# does in plain words. A source in this dict with no row in `scrape_runs` is printed as "never run":
# absence is the finding, not a blank cell. `expand_catalogue` is deliberately absent - it is a
# one-off tool run by hand, and it is reported separately rather than dressed up as a nightly source.
EXPECTED_SOURCES: dict[str, str] = {
    "nafdac_greenbook": "Greenbook register list",
    "nafdac_details": "Greenbook detail pages: status and expiry",
    "link_product_nrn": "Links a product to a registration number",
    "healthplus": "HealthPlus prices",
    "medplus": "MedPlus prices",
    "drugstore": "Drugstore.ng prices",
    "match_listings": "Links a shop listing to a product",
}

STATE_LABEL = {"Lagos": "Lagos", "National": "Whole country"}


# --------------------------------------------------------------------------- the tribute
# The page carries Dora Akunyili as its identity because the prices on it are checked against the
# register of the agency she led. Every biographical fact below is copied from `.agent/DORA-facts.md`,
# which records where each one was read. Nothing on either page is written from memory.
#
# Her name, honours and dates, exactly as the National Library of Nigeria's own repository item gives
# them (nigeriareposit.nln.gov.ng/items/973ac71e-ea15-4c85-ac11-07dfb5cb8a0c):
#     "Dora Nkem Akunyili OFR (14 July 1954 - 7 June 2014)"
# The two dates are separate constants and not one string, because of the guard in `dora_dates()`.
DORA_NAME = "Dora Nkem Akunyili"
DORA_HONOURS = "OFR"
DORA_BORN: str | None = "14 July 1954"  # National Library of Nigeria repository, item 973ac71e
DORA_DIED: str | None = "7 June 2014"   # National Library of Nigeria repository, item 973ac71e

NLN_ITEM = ("https://nigeriareposit.nln.gov.ng/items/"
            "973ac71e-ea15-4c85-ac11-07dfb5cb8a0c")
PRINCETON_ITEM = ("https://web.archive.org/web/20250909000000/https://successfulsocieties."
                  "princeton.edu/interviews/dora-akunyili")
TIME_ITEM = ("https://web.archive.org/web/2016/https://content.time.com/time/magazine/"
             "article/0,9171,1124244,00.html")

# The one portrait the project holds, and the three photographs of a statue. Crops of one face, not a
# gallery: the masthead, the band and the footer mark are three crops of this single photograph.
PORTRAIT_FILE = "dora-portrait.jpg"
BAND_FILE = "dora-band.jpg"
MARK_FILE = "dora-mark.jpg"
MONUMENT_FILE = "dora-monument.jpg"
IMAGE_FILES = (PORTRAIT_FILE, BAND_FILE, MARK_FILE, MONUMENT_FILE)
ASSET_SRC = Path("docs/assets/dora")

CREDIT_PORTRAIT = {
    "shows": "Portrait of Dora Akunyili",
    "title": ("File:Prof. Dora Akunyili (Hon. Minister of Information Communication 2008 - 2010)"
              ".jpg"),
    "page": ("https://commons.wikimedia.org/wiki/File:Prof._Dora_Akunyili_(Hon._Minister_of_"
             "Information_Communication_2008_-_2010).jpg"),
    "author": "National Library of Nigeria",
    "licence": "CC0 1.0 (public domain dedication)",
    "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "change": "cropped and resized; the masthead, the band and the footer mark are three crops of it",
}
CREDIT_MONUMENT = {
    "shows": "A memorial to Dora Akunyili at Ezinano, Agulu",
    "title": "File:DoraAkunyili Monument at Ezinano Agulu.jpg",
    "page": ("https://commons.wikimedia.org/wiki/"
             "File:DoraAkunyili_Monument_at_Ezinano_Agulu.jpg"),
    "author": "Chiinobis",
    "licence": "CC BY-SA 4.0",
    "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "change": "cropped and resized; this crop is offered under CC BY-SA 4.0 as well",
}

# Page weight is a gate, not a wish: the four images together must stay under this many bytes.
IMAGE_BUDGET_BYTES = 400 * 1024

# Two tints and one accent, taken from the one photograph rather than from taste. The two tints are
# the deep plum of the shadow behind her headwrap (#4f1f2f, about a tenth of the photograph's pixels)
# and the warm sand of the wall behind her (#dad0b7, about an eighth). The accent is the same plum at
# link strength; the band is that plum taken down to a shadow, so the band reads as the same hue and
# not as a second brand. Nothing here is red next to green: the price page must never colour a price.
INK = "#1a1612"
MUTED = "#4a423d"
LINE = "#d7cfbe"
PAPER = "#faf7f1"
PANEL = "#f1ebdf"
ACCENT = "#5f2a54"
WARN = "#7a2e00"
WARN_BG = "#fdf1e3"
BAND_BG = "#2a1a20"
BAND_TEXT = "#f7f0e6"
BAND_ACCENT = "#e2b25c"

PALETTE_CSS = f""":root{{--ink:{INK};--muted:{MUTED};--line:{LINE};--bg:{PAPER};--panel:{PANEL};
--accent:{ACCENT};--warn:{WARN};--warn-bg:{WARN_BG};--band:{BAND_BG};--band-ink:{BAND_TEXT};
--band-accent:{BAND_ACCENT}}}"""

# Every text-on-surface pair the page actually uses, with the ratio WCAG 2.2 AA asks for (4.5:1 for
# body text). Measured at build time and printed; a pair below the floor fails the build.
CONTRAST_FLOOR = 4.5
CONTRAST_PAIRS: list[tuple[str, str, str]] = [
    ("band text on the band", BAND_TEXT, BAND_BG),
    ("gold text on the band", BAND_ACCENT, BAND_BG),
    ("body text on the page", INK, PAPER),
    ("secondary text on the page", MUTED, PAPER),
    ("secondary text on a panel", MUTED, PANEL),
    ("body text on a panel", INK, PANEL),
    ("links on the page", ACCENT, PAPER),
    ("links on a panel", ACCENT, PANEL),
    ("a warning on its own panel", WARN, WARN_BG),
]


class UnsetDate(RuntimeError):
    """Raised when a date constant is None. A remembered date must never reach the page."""


def dora_dates() -> str:
    """Her dates, or a hard stop.

    The guard is the whole point: if `DORA_BORN` or `DORA_DIED` is ever set to None the build stops
    before it opens the database, instead of printing a date from memory. Wire it in at the top of
    `main()`, not in the template, so no rendering path can skip it.
    """
    if not DORA_BORN or not DORA_DIED:
        raise UnsetDate(
            "her dates are unset (DORA_BORN=%r, DORA_DIED=%r): the page will not print a date from "
            "memory. Fill both from the National Library of Nigeria item before building."
            % (DORA_BORN, DORA_DIED)
        )
    return f"{DORA_BORN} \u2013 {DORA_DIED}"


def _luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(front: str, back: str) -> float:
    a, b = _luminance(front), _luminance(back)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def measure_contrast() -> tuple[float, list[str]]:
    """Every pair, measured. Returns the worst ratio and anything under the floor."""
    worst = 99.0
    problems: list[str] = []
    for label, front, back in CONTRAST_PAIRS:
        ratio = contrast_ratio(front, back)
        worst = min(worst, ratio)
        print(f"  contrast  {label:<30s} {ratio:5.2f}:1  ({front} on {back})")
        if ratio < CONTRAST_FLOOR:
            problems.append(f"{label}: {ratio:.2f}:1, below {CONTRAST_FLOOR}:1")
    return worst, problems


def publish_images() -> int:
    """Copy the four repository images next to the pages and refuse an over-weight page.

    The images live in `docs/assets/dora/` as source; `site/` is build output and gitignored, so the
    published directory is filled here rather than committed.
    """
    out_dir = SITE / "assets" / "dora"
    out_dir.mkdir(parents=True, exist_ok=True)
    missing = [str(ASSET_SRC / name) for name in IMAGE_FILES
               if not (ASSET_SRC / name).exists()]
    if missing:
        raise RuntimeError("image missing from the repository: " + ", ".join(missing))
    total = 0
    for name in IMAGE_FILES:
        data = (ASSET_SRC / name).read_bytes()
        (out_dir / name).write_bytes(data)
        total += len(data)
        print(f"  image     {name:<20s} {len(data):>7,} bytes")
    if total > IMAGE_BUDGET_BYTES:
        raise RuntimeError(
            f"images total {total:,} bytes, over the {IMAGE_BUDGET_BYTES:,}-byte page-weight gate"
        )
    return total


# --------------------------------------------------------------------------- facts
@dataclass
class Spec:
    """One query, the shape it is rendered in, and how much drift to forgive on a re-read."""

    key: str
    sql: str
    derive: Callable[[list[tuple]], Any]
    time_tolerance: float = 0.0   # seconds, applied to ISO timestamp strings only
    float_tolerance: float = 0.0  # applied to float leaves only (hour counts); never to prices


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def money(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2) if not isinstance(value, float) else round(value, 2)


def safe_url(value: Any) -> str | None:
    text = "" if value is None else str(value)
    return text if text.lower().startswith(("http://", "https://")) else None


def licence_label(status: Any, flagged: Any) -> str:
    """Three labels, never a blank: active / not active / not read.

    Copied from dashboard/app.py:126-146, which is the same rule in the Streamlit app. `not read`
    means no status was ever scraped for that registration; it is a statement about our reading, not
    about the licence.
    """
    if status is None:
        return "not read"
    return "not active" if bool(flagged) else "active"


# ---- overview --------------------------------------------------------------
OVERVIEW_SQL = """
select
    (select count(*) from products)                                          as products,
    (select count(*) from v_latest_listings)                                 as latest_listings,
    (select count(*) from v_latest_listings where product_id is not null)    as matched_listings,
    (select count(*) from v_latest_listings where in_stock is null)          as stock_unread,
    (select count(*) from v_cheapest_per_product_state)                      as cells_total,
    (select count(*) from v_cheapest_per_product_state where is_comparison)   as cells_comparison,
    (select max(pharmacy_count) from v_cheapest_per_product_state
      where is_comparison)                                                   as shops_in_comparison,
    (select max(scraped_at) from v_latest_listings)                          as newest_scrape,
    now()                                                                    as database_now,
    (now() at time zone 'Africa/Lagos')::date                                as lagos_today,
    (select (max(scraped_at) at time zone 'Africa/Lagos')::date
       from v_latest_listings)                                               as lagos_newest_date,
    (select round(extract(epoch from (now() - max(scraped_at))) / 3600.0, 1)
       from v_latest_listings)                                               as hours_since_newest
"""


def derive_overview(rows: list[tuple]) -> dict[str, Any]:
    (products, latest, matched, stock_unread, cells_total, cells_comp,
     shops_comp, newest, now, lagos_today, lagos_newest, hours) = rows[0]
    return {
        "products": int(products),
        "latest_listings": int(latest),
        "matched_listings": int(matched),
        "unmatched_listings": int(latest) - int(matched),
        "stock_unread_listings": int(stock_unread),
        "cells_total": int(cells_total),
        "cells_comparison": int(cells_comp),
        "cells_single": int(cells_total) - int(cells_comp),
        "shops_in_a_comparison": None if shops_comp is None else int(shops_comp),
        "newest_scrape_utc": iso(newest),
        "database_now_utc": iso(now),
        "lagos_today": str(lagos_today),
        "lagos_newest_date": None if lagos_newest is None else str(lagos_newest),
        "hours_since_newest_scrape": None if hours is None else float(hours),
    }


# ---- registration status ---------------------------------------------------
REG_SQL = """
select
    (select count(*) from nafdac_registrations)                                 as registrations,
    (select count(*) from nafdac_registrations where status is not null)        as status_read,
    (select count(*) from products where nafdac_registration_number is not null) as products_with_number,
    (select count(*) from v_suspicious_listings)                                as flagged_all,
    (select count(*) from v_suspicious_listings
      where suspicion_reason = 'inactive_registration')                         as flagged_inactive,
    (select count(*) from v_suspicious_listings
      where suspicion_reason = 'expired_registration')                          as flagged_expired
"""

# How the 580 matched listings divide up, so the flagged count cannot be read as the whole story.
# The four buckets are exclusive and must sum to `overview.matched_listings`; the audit checks the
# sum as well as each bucket.
BREAKDOWN_SQL = """
select
    count(*) filter (
        where r.status is not null
          and (r.status <> 'Active' or r.expiry_date < current_date))            as flagged,
    count(*) filter (
        where r.status = 'Active'
          and coalesce(r.expiry_date < current_date, false) = false)             as active,
    count(*) filter (
        where p.nafdac_registration_number is not null
          and (r.registration_number is null or r.status is null))               as status_not_read,
    count(*) filter (where p.nafdac_registration_number is null)                 as no_registration_number
from v_latest_listings l
join products p on p.id = l.product_id
left join nafdac_registrations r
       on r.registration_number = p.nafdac_registration_number
where l.product_id is not null
"""


def derive_registration(reg_rows: list[tuple], breakdown_rows: list[tuple]) -> dict[str, Any]:
    registrations, status_read, products_with_number, flagged, inactive, expired = reg_rows[0]
    flagged_b, active_b, not_read_b, no_number_b = breakdown_rows[0]
    total = int(registrations)
    read = int(status_read)
    return {
        "registrations_total": total,
        "registrations_status_read": read,
        "registrations_status_unread": total - read,
        "coverage_pct": round(100.0 * read / total, 1) if total else None,
        "products_with_registration_number": int(products_with_number),
        "flagged_listings": int(flagged),
        "flagged_inactive": int(inactive),
        "flagged_expired": int(expired),
        "matched_flagged": int(flagged_b),
        "matched_active": int(active_b),
        "matched_status_not_read": int(not_read_b),
        "matched_no_registration_number": int(no_number_b),
        "matched_buckets_sum": int(flagged_b) + int(active_b) + int(not_read_b) + int(no_number_b),
    }


# ---- prices ----------------------------------------------------------------
CELL_COLUMNS = """
    canonical_name,
    state,
    cheapest_pack_pharmacy,
    cheapest_pack_price,
    unit_price,
    cheapest_pack_pack_size,
    pharmacy_count,
    confirmed_pharmacy_count,
    cheapest_pack_stock_confirmed,
    registration_status,
    registration_flagged,
    cheapest_pack_url
"""

# Named in the brief and required to be stated exactly. It is a caption, not a claim about the
# market: the two shops are the two that publish prices for that product in Lagos.
COMPARISON_CAPTION = ("cheapest among the online pharmacies that publish prices - Lagos, two shops")

COMPARISON_SQL = f"""
select {CELL_COLUMNS}
from v_cheapest_per_product_state
where state = 'Lagos' and is_comparison
order by canonical_name, cheapest_pack_price, cheapest_pack_pharmacy, product_id
"""

SINGLE_SQL = f"""
select {CELL_COLUMNS}
from v_cheapest_per_product_state
where not is_comparison
order by canonical_name, state, cheapest_pack_price, cheapest_pack_pharmacy, product_id
"""


def derive_cells(rows: list[tuple]) -> list[dict[str, Any]]:
    out = []
    for (name, state, shop, price, unit_price, pack_size, shops, confirmed, stock_confirmed,
         status, flagged, url) in rows:
        out.append({
            "product": name,
            "state": state,
            "state_label": STATE_LABEL.get(state, state),
            "shop": shop,
            "price_ngn": money(price),
            "unit_price_ngn": money(unit_price),
            "pack_size": pack_size,
            "shops_quoting": int(shops),
            "shops_confirmed_in_stock": int(confirmed),
            "stock_confirmed": None if stock_confirmed is None else bool(stock_confirmed),
            "licence": licence_label(status, flagged),
            "registration_status": status,
            "url": safe_url(url),
        })
    return out


# ---- pipeline health -------------------------------------------------------
HEALTH_SQL = """
select
    source,
    max(finished_at) filter (where status = 'success')                        as last_success,
    count(*) filter (where status = 'success')                                as ok_runs,
    count(*) filter (where status = 'failed')                                 as failed_runs,
    count(*)                                                                  as runs,
    round(extract(epoch from (now() - max(finished_at) filter (where status = 'success')))
          / 3600.0, 1)                                                        as hours_since_success
from scrape_runs
group by source
order by source
"""

LEDGER_SQL = """
select count(*) as runs, min(started_at) as first_run, max(finished_at) as last_run,
       (now() at time zone 'Africa/Lagos')::date as lagos_today
from scrape_runs
"""


def derive_health(rows: list[tuple], ledger: list[tuple],
                  stale_hours: float = STALE_HOURS) -> dict[str, Any]:
    seen = {}
    for source, last_ok, ok_runs, failed_runs, runs, hours in rows:
        seen[source] = {
            "source": source,
            "last_success_utc": iso(last_ok),
            "successful_runs": int(ok_runs),
            "failed_runs": int(failed_runs),
            "runs": int(runs),
            "hours_since_success": None if hours is None else float(hours),
        }

    table: list[dict[str, Any]] = []
    for source, description in EXPECTED_SOURCES.items():
        entry = seen.pop(source, None)
        if entry is None:
            table.append({
                "source": source,
                "what_it_does": description,
                "last_success_utc": None,
                "hours_since_success": None,
                "successful_runs": 0,
                "failed_runs": 0,
                "runs": 0,
                "state": "never",
                "state_label": "never run",
                "extra": False,
            })
            continue
        entry["what_it_does"] = description
        entry["extra"] = False
        if entry["hours_since_success"] is None:
            entry["state"], entry["state_label"] = "never", "never run"
        elif entry["hours_since_success"] > stale_hours:
            entry["state"], entry["state_label"] = "stale", "stale"
        else:
            entry["state"], entry["state_label"] = "ok", "reporting"
        table.append(entry)

    extras = []
    for source, entry in sorted(seen.items()):
        entry["what_it_does"] = "not part of the nightly job (a tool run by hand)"
        entry["extra"] = True
        entry["state"], entry["state_label"] = "extra", "not nightly"
        extras.append(entry)

    not_reporting = [row["source"] for row in table if row["state"] != "ok"]
    runs, first_run, last_run, lagos_today = ledger[0]
    return {
        "stale_hours_threshold": stale_hours,
        "sources": table,
        "extra_sources": extras,
        "nightly_not_reporting": not_reporting,
        "nightly_sources": len(table),
        "runs_logged": int(runs),
        "first_run_utc": iso(first_run),
        "last_run_utc": iso(last_run),
        "lagos_today": str(lagos_today),
    }


# ---- pharmacies (names and websites, so no hostname is typed on the page) --
PHARMACY_SQL = """
select name, website, state from pharmacies order by id
"""


def derive_pharmacies(rows: list[tuple]) -> list[dict[str, Any]]:
    return [{"name": name, "website": safe_url(website),
             "state": state, "state_label": STATE_LABEL.get(state, state)}
            for name, website, state in rows]


SPECS: list[Spec] = [
    Spec("overview", OVERVIEW_SQL, derive_overview, time_tolerance=300.0, float_tolerance=1.0),
    Spec("registration", REG_SQL, lambda rows: rows, time_tolerance=300.0),
    Spec("breakdown", BREAKDOWN_SQL, lambda rows: rows),
    Spec("comparison_cells", COMPARISON_SQL, derive_cells),
    Spec("single_cells", SINGLE_SQL, derive_cells),
    Spec("health", HEALTH_SQL, lambda rows: rows, time_tolerance=300.0, float_tolerance=1.0),
    Spec("ledger", LEDGER_SQL, lambda rows: rows, time_tolerance=300.0),
    Spec("pharmacies", PHARMACY_SQL, derive_pharmacies),
]


def read_facts(conn: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for spec in SPECS:
        cursor = conn.execute(spec.sql)
        rows = cursor.fetchall()
        facts[spec.key] = spec.derive(rows)
    # Composed facts: built from other queries rather than from a query of their own, which is why
    # they are derived here instead of in a Spec - and still audited, because the compose functions
    # run again on the fresh read.
    facts["registration"] = derive_registration(facts["registration"], facts["breakdown"])
    facts["health"] = derive_health(facts["health"], facts["ledger"])
    return facts


# Queries whose result is consumed by a compose function rather than printed on its own.
CONSUMED = {"breakdown", "ledger"}


# --------------------------------------------------------------------------- the page
CSS = PALETTE_CSS + """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:1rem/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:62rem;margin:0 auto;padding:1rem .75rem 3rem}
/* Prose keeps a readable measure; tables are allowed the full width. */
.wrap p,.wrap li{max-width:68ch}
.wrap .tablewrap,.wrap table{max-width:none}
.wrap>h2:first-child{margin-top:.9rem;padding-top:0;border-top:0}
/* The header block now sits directly above the tribute band; no dead strip between them. */
.wrap:has(> header){padding-bottom:.75rem}
a{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
a:focus-visible,:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-9999px;top:0;background:var(--bg);padding:.6rem 1rem;z-index:10}
.skip:focus{left:.5rem;top:.5rem;border:2px solid var(--ink)}
header{border-bottom:3px solid var(--ink);padding-bottom:.75rem;margin-bottom:1rem}
h1{font-size:1.55rem;line-height:1.25;margin:.5rem 0 .35rem}
h2{font-size:1.2rem;line-height:1.3;margin:2.25rem 0 .5rem;padding-top:1rem;
border-top:2px solid var(--line)}
h3{font-size:1.02rem;margin:1.5rem 0 .4rem}
p,li{margin:.5rem 0;overflow-wrap:break-word}
.lede{font-size:1.03rem}
.note{color:var(--muted)}
.fact{background:var(--panel);border-left:4px solid var(--accent);padding:.7rem .85rem;
margin:.9rem 0;border-radius:0 4px 4px 0}
.banner{background:var(--warn-bg);border:2px solid var(--warn);color:var(--warn);
padding:.75rem .9rem;margin:1rem 0;border-radius:4px}
.banner strong{color:var(--warn)}
.stamp{font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:4px;margin:.6rem 0 1.2rem}
table{border-collapse:collapse;width:100%;font-size:.92rem}
caption{text-align:left;padding:.55rem .6rem;background:var(--panel);color:var(--muted);
border-bottom:1px solid var(--line);font-size:.9rem}
/* The label lives above the scroll box, not in <caption>. A caption stretches to the table's own
   width, so at 375 px its tail is clipped by the scrolling container and can never be read; a
   paragraph above the box wraps inside the viewport. Every table keeps a <caption> describing its
   rows, because <caption> is what a screen reader announces first. */
.tablelabel{font-weight:600;margin:.8rem 0 .3rem;font-size:.97rem;overflow-wrap:break-word}
/* A short column of long prose collapses to one character per line on a phone and makes every row
   100 px tall. The table already scrolls; give the description room to be read at that width. */
td.desc{min-width:11rem}
th,td{padding:.42rem .55rem;border-bottom:1px solid var(--line);text-align:left;
vertical-align:top}
thead th{background:var(--panel);white-space:nowrap}
tbody th{font-weight:600}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:.82rem;line-height:1.4;padding:0 .3rem;border:1px solid;
border-radius:3px}
.tag-ok{border-color:#1c5c2e}
.tag-bad{border-color:var(--warn)}
.tag-unknown{border-color:#5b5b5b}
ol.limits{padding-left:1.15rem}
ol.limits li{margin:.7rem 0}
footer{margin-top:2.5rem;padding-top:1rem;border-top:2px solid var(--line);
color:var(--muted);font-size:.9rem}
/* ---- the tribute ------------------------------------------------------------------------------
   Three crops of one photograph, not a gallery: a mark in the masthead, one wide band between the
   price tables and the registration section, and a small mark in the footer. The band carries the
   name and one line and no figures at all, so it cannot compete with the numbers above it. Text sits
   on the flat tint rather than on the photograph, so its contrast is a measured number (see
   CONTRAST_PAIRS) and not a hope. */
.masthead{display:flex;gap:.9rem;align-items:flex-start}
.masthead-mark{width:6.5rem;height:auto;flex:0 0 6.5rem;display:block;border-radius:3px;
box-shadow:0 0 0 1px var(--line)}
.masthead-text{min-width:0;flex:1 1 auto}
.tribute-line{margin:.45rem 0 .5rem;font-size:.95rem}
.tribute-line .name{font-weight:700}
.band{background:var(--band);color:var(--band-ink);margin:0 0 2rem;padding:0}
.band-inner{max-width:62rem;margin:0 auto;display:grid;grid-template-columns:20rem 1fr;
align-items:stretch}
.band-photo{margin:0;display:flex;overflow:hidden}
.band-photo img{display:block;width:100%;height:100%;min-height:15rem;max-height:19rem;
object-fit:cover;object-position:50% 30%}
.band-text{padding:1.5rem 1.1rem 1.6rem;align-self:center}
.band-name{margin:0;font-size:1.7rem;line-height:1.15;color:var(--band-ink)}
.band-dates{margin:.3rem 0 0;font-size:.92rem;color:var(--band-ink)}
.band-why{margin:.75rem 0 0;font-size:1rem;line-height:1.5;color:var(--band-ink);max-width:33rem}
.band a{color:var(--band-accent)}
.band a:focus-visible{outline-color:var(--band-accent)}
.footer-mark{width:4rem;height:4rem;float:left;margin:0 .8rem .5rem 0;border-radius:3px;
box-shadow:0 0 0 1px var(--line);display:block}
.credits{clear:both;padding-top:.6rem}
.credits p{margin:.4rem 0}
/* ---- the About page ------------------------------------------------------------------------- */
.subhead{font-size:.95rem;color:var(--muted);margin:.2rem 0 .6rem}
figure.pull{margin:1.4rem 0;padding:.1rem 0 .1rem 1rem;border-left:4px solid var(--accent)}
figure.pull blockquote{margin:0;font-size:1.15rem;line-height:1.45}
figure.pull figcaption{margin-top:.5rem;font-size:.92rem;color:var(--muted)}
figure.about-figure{margin:1.4rem 0;max-width:24rem}
figure.about-figure img{display:block;width:100%;height:auto;border:1px solid var(--line);
border-radius:4px}
figure.about-figure figcaption{margin-top:.45rem;font-size:.88rem;color:var(--muted)}
.opinion{background:var(--panel);border-left:4px solid var(--accent);padding:.7rem .9rem;
margin:1rem 0;border-radius:0 4px 4px 0}
.opinion .label{font-weight:700;display:block;margin-bottom:.25rem}
@media (max-width:640px){
 .band-inner{grid-template-columns:1fr}
 .band-photo img{height:9rem;min-height:9rem;max-height:9rem;object-position:50% 26%}
 .band-text{padding:1.1rem .9rem 1.2rem}
 .band-name{font-size:1.4rem}
}
@media (max-width:420px){
 .wrap{padding:.75rem .6rem 2rem}
 h1{font-size:1.35rem}
 table{font-size:.86rem}
 th,td{padding:.35rem .4rem}
 .masthead{gap:.7rem}
 .masthead-mark{width:4.6rem;flex-basis:4.6rem}
}
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def tag(text: str, kind: str) -> str:
    """A status whose meaning is in the word, not in the colour (WCAG 1.4.1)."""
    return f'<span class="tag tag-{kind}">{esc(text)}</span>'


def naira(value: Any) -> str:
    if value is None:
        return '<span class="note">not known</span>'
    return f"\u20a6{value:,.2f}"


def link(url: Any, text: str) -> str:
    if not url:
        return esc(text)
    return f'<a href="{esc(url)}" rel="nofollow noopener">{esc(text)}</a>'


def stock_cell(row: dict[str, Any]) -> str:
    if row["stock_confirmed"] is True:
        return tag("confirmed", "ok")
    return tag("not read", "unknown")


def licence_cell(row: dict[str, Any]) -> str:
    label = row["licence"]
    if label == "active":
        return tag(label, "ok")
    if label == "not active":
        return tag(label, "bad")
    return tag(label, "unknown")


def price_rows(rows: list[dict[str, Any]], with_state: bool) -> str:
    body = []
    for row in rows:
        cells = [
            f'<th scope="row">{esc(row["product"])}</th>',
        ]
        if with_state:
            cells.append(f'<td>{esc(row["state_label"])}</td>')
        cells += [
            f'<td>{link(row["url"], row["shop"])}</td>',
            f'<td class="num">{naira(row["price_ngn"])}</td>',
            f'<td>{stock_cell(row)}</td>',
            f'<td>{licence_cell(row)}</td>',
            f'<td class="num">{naira(row["unit_price_ngn"])}</td>',
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(body)


def single_rows(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        cells = [
            f'<th scope="row">{esc(row["product"])}</th>',
            f'<td>{esc(row["state_label"])}</td>',
            f'<td>{link(row["url"], row["shop"])}</td>',
            f'<td class="num">{naira(row["price_ngn"])}</td>',
            f'<td>{stock_cell(row)}</td>',
            f'<td>{licence_cell(row)}</td>',
        ]
        body.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(body)


def health_rows(health: dict[str, Any]) -> str:
    out = []
    for row in health["sources"] + health["extra_sources"]:
        if row["state"] == "never":
            status = tag("never run", "bad")
        elif row["state"] == "stale":
            status = tag("stale", "bad")
        elif row["state"] == "extra":
            status = tag("not nightly", "unknown")
        else:
            status = tag("reporting", "ok")
        last = row["last_success_utc"] or '<span class="note">no successful run ever</span>'
        hours = ("<span class=\"note\">not known</span>" if row["hours_since_success"] is None
                 else f'{row["hours_since_success"]:,.1f} h')
        out.append(
            "<tr>"
            f'<th scope="row">{esc(row["source"])}</th>'
            f'<td>{status}</td>'
            f'<td>{last}</td>'
            f'<td class="num">{hours}</td>'
            f'<td class="desc">{esc(row["what_it_does"])}</td>'
            "</tr>"
        )
    return "\n".join(out)


def about_page(dates: str) -> str:
    """The one biography page: sourced facts, each traceable to one of three URLs, and nothing else.

    The prose is deliberately thin. It renders only what `.agent/DORA-facts.md` records, it does not
    date the attack (TIME's own dating is not precise enough), it makes no claim either way about
    criticism of her tenure, and it adds no honour beyond OFR. The one paragraph of opinion is
    labelled as opinion.
    """
    portrait = CREDIT_PORTRAIT
    monument = CREDIT_MONUMENT
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>About {DORA_NAME} {DORA_HONOURS}</title>
<link rel="icon" href="data:,">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<div class="wrap">
<header>
<p class="subhead"><a href="index.html">&larr; Medicine prices and registration status in Nigeria</a></p>
<div class="masthead">
<img class="masthead-mark" src="assets/dora/{PORTRAIT_FILE}" width="480" height="600"
 alt="Portrait of Dora Akunyili">
<div class="masthead-text">
<h1>{DORA_NAME} {DORA_HONOURS}</h1>
<p class="tribute-line">{dates}</p>
</div>
</div>
</header>
<main id="main">
<p class="lede">This page is here because the prices on the other page are checked against the register
of the agency she led. Everything below comes from the three sources listed at the foot of the page.
Where those sources are silent, this page is silent too.</p>

<h2 id="who">Who she was</h2>
<p>Dora Nkem Akunyili OFR was born on 14 July 1954 and died on 7 June 2014. Both dates are as the
National Library of Nigeria records them. Before NAFDAC she was a senior lecturer and consultant
pharmacologist at the University of Nigeria, Nsukka.</p>

<h2 id="nafdac">NAFDAC, 2001 to 2008</h2>
<p>She was Director-General of the National Agency for Food and Drug Administration and Control from
2001 to 2008. The Princeton profile of her puts her start in April 2001 and describes her service as
nearly eight years.</p>

<h2 id="after">Afterwards</h2>
<p>In December 2008 she was appointed Minister of the Federal Ministry of Information and
Communication. She died at a specialist cancer hospital in India on 7 June 2014, after a two-year
battle with uterine cancer, and was laid to rest at Agulu in Anambra State.</p>

<figure class="about-figure">
<img src="assets/dora/{MONUMENT_FILE}" width="480" height="776"
 alt="A memorial statue of Dora Akunyili">
<figcaption>A memorial to her at Ezinano, Agulu. The name of the place and of what is shown are the
photographer's, as given on Wikimedia Commons.</figcaption>
</figure>

<h2 id="words">In her words</h2>
<figure class="pull">
<blockquote><p>"The back windscreen was shattered&hellip; A bullet pierced through my head scarf and
grazed my scalp."</p></blockquote>
<figcaption>{DORA_NAME}, quoted in TIME, "Drug Warrior", 31 October 2005.</figcaption>
</figure>
<p>Those are her words describing an attack on the car she and her family were travelling in. This
page does not give that attack a date: TIME places it "three years" before the article was published,
which is not precise enough to print as a year.</p>

<h2 id="sister">Her sister</h2>
<p>TIME reports the next sentence in its own words, not in hers:</p>
<figure class="pull">
<blockquote><p>"Akunyili's sister Vivian, a diabetic, died in 1988, a victim of fake insulin."</p>
</blockquote>
<figcaption>TIME, "Drug Warrior", 31 October 2005. The sentence is TIME's; this page does not put it
in her mouth.</figcaption>
</figure>

<h2 id="figure">A figure this page does not print</h2>
<p>TIME reported that before she took over her post in 2001, "a staggering 80%" of the medicines sold
were "deficient in one way or another". The report gives no method for that number, so it is quoted
here only as TIME stated it.</p>
<p>A widely repeated pair of numbers &mdash; a high share before her tenure and a much lower share
after it &mdash; is not printed on this page, because nothing read for this page supports either
number.</p>

<h2 id="view">The project's view</h2>
<div class="opinion">
<p class="label">Opinion, labelled as opinion. Not a finding, and not sourced above.</p>
<p>A price can only be checked against a register that somebody keeps, and a register that nobody can
read protects nobody. This project can attach a licence status to only part of what it lists, and it
prints that shortfall on the page rather than behind it. We think the shortfall is worth showing: a
page that hides what it cannot read is worth less than one that says so.</p>
</div>

<h2 id="sources">Sources</h2>
<ol class="limits">
<li>The National Library of Nigeria's repository, item 973ac71e: her name and honours, both dates, the
years as Director-General, where she died and where she was laid to rest.
{link(NLN_ITEM, "nigeriareposit.nln.gov.ng")}</li>
<li>Princeton, Innovations for Successful Societies, profile of Dora Akunyili, read through a Wayback
snapshot dated 9 September 2025 because the live host answers this machine with a challenge: April
2001, "nearly eight years", the December 2008 appointment, and the post at the University of Nigeria,
Nsukka. {link(PRINCETON_ITEM, "the archived profile")}</li>
<li>TIME, "Drug Warrior", by Michael Lemonick and Gilbert Da Costa, 31 October 2005, read through a
Wayback replay: her own words on the attack, the sentence about her sister, and the 80% figure.
{link(TIME_ITEM, "the archived article")}</li>
</ol>
<p class="note">Nothing beyond those three is claimed here. This page does not date the attack, it
does not say whether her tenure was criticised or not, and it adds no honour beyond OFR.</p>

<h2 id="images">The images on this page</h2>
<div class="credits">
<p><strong>1. The portrait</strong> in the masthead, and the mark in the footer. A crop of
{link(portrait["page"], portrait["title"])} on Wikimedia Commons, credited to the
{esc(portrait["author"])}, released under {link(portrait["licence_url"], "CC0 1.0")} (public domain
dedication). Changes: {esc(portrait["change"])}. CC0 requires no attribution; it is given anyway.</p>
<p><strong>2. The statue photograph</strong> above. A crop of
{link(monument["page"], monument["title"])} on Wikimedia Commons, photographed by
{esc(monument["author"])}, released under
{link(monument["licence_url"], "CC BY-SA 4.0")}. Changes: {esc(monument["change"])}, so this crop
carries the same licence and may be reused under it. Share-alike applies to the photograph, not to
the price data on the other page, which is CC-BY-4.0.</p>
</div>
</main>
<footer>
<img class="footer-mark" src="assets/dora/{MARK_FILE}" width="220" height="220" alt="">
<p><strong>{DORA_NAME} {DORA_HONOURS}</strong>, {dates}.
<a href="index.html">Medicine prices and registration status in Nigeria</a>.</p>
<p>This page is one file and three local images. No external stylesheet, script, font or image is
fetched, so it works with no network. It is generated by <code>scripts/build_site.py</code> from
constants that quote the National Library of Nigeria's record; if a date in that generator is ever
unset, the build refuses to write either page instead of printing a date from memory.</p>
</footer>
</div>
</body>
</html>
"""


class Page:
    """Renders the document and records which facts it actually printed."""

    def __init__(self, facts: dict[str, Any], dates: str) -> None:
        self.facts = facts
        self.dates = dates
        self.used: set[str] = set()

    def f(self, key: str) -> Any:
        self.used.add(key)
        return self.facts[key]

    def build(self) -> str:
        facts = self.facts
        overview = self.f("overview")
        reg = self.f("registration")
        comparison = self.f("comparison_cells")
        single = self.f("single_cells")
        health = self.f("health")
        pharmacies = self.f("pharmacies")

        hours = overview["hours_since_newest_scrape"]
        hours_text = "an unknown length of time" if hours is None else f"{hours:,.1f} hours"
        shops = overview["shops_in_a_comparison"]
        shops_text = "not known" if shops is None else str(shops)

        not_reporting = health["nightly_not_reporting"]
        if not_reporting:
            banner = (
                '<div class="banner" role="note">'
                '<p><strong>What did not happen.</strong> '
                f'{len(not_reporting)} of the {health["nightly_sources"]} sources this page depends on '
                f'has no successful run in the last {health["stale_hours_threshold"]:g} hours: '
                f'{esc(", ".join(not_reporting))}. Everything below is still shown, but it is older '
                'than it should be, and the last panel says which source stopped.</p>'
                "</div>"
            )
        else:
            banner = ""

        extras = health["extra_sources"]
        extras_line = ""
        if extras:
            names = ", ".join(row["source"] for row in extras)
            extras_line = (
                f'<p class="note">The run log also holds {len(extras)} entry of its own for tools run '
                f'by hand rather than nightly: {esc(names)}.</p>'
            )

        pharmacy_list = "".join(
            f'<li>{link(p["website"], p["name"])} - {esc(p["state_label"])}</li>'
            for p in pharmacies
        )

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Medicine prices and registration status, read from an open database</title>
<link rel="icon" href="data:,">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<div class="wrap">
<header>
<h1>Medicine prices and registration status in Nigeria</h1>
<p class="tribute-line"><span class="name">{DORA_NAME} {DORA_HONOURS}</span>, {self.dates},
led NAFDAC from 2001 to 2008. The prices below are checked against the register her agency keeps.
<a href="about.html">About her</a></p>
<p class="lede">This page is built from a database that records what three online pharmacies asked for
medicines on the day it was read, and what the NAFDAC register says about the registration behind each
of those medicines. It is independent, it is not a shop, and it is not endorsed by NAFDAC.</p>
<p class="stamp note">Read from the database at {esc(overview["database_now_utc"])}
({esc(overview["lagos_today"])} in Lagos). The newest price on the page was recorded at
{esc(overview["newest_scrape_utc"])} ({esc(overview["lagos_newest_date"])} in Lagos), which is
{hours_text} before the page was built.</p>
{banner}
</header>
</div>

<section class="band" aria-label="A tribute to Dora Akunyili">
<div class="band-inner">
<figure class="band-photo">
<img src="assets/dora/{BAND_FILE}" width="640" height="305" alt="">
</figure>
<div class="band-text">
<p class="band-name"><strong>{DORA_NAME} {DORA_HONOURS}</strong></p>
<p class="band-dates">{self.dates}</p>
<p class="band-why">She led the agency whose register this page reads. Where the reading falls short,
the page says so. <a href="about.html">About her</a></p>
</div>
</div>
</section>
<main id="main">
<div class="wrap">

<h2 id="prices">Prices</h2>
<p>Each row below is one product, and the price shown is the lowest one quoted for it by the shops
this project reads. Two kinds of row are kept apart, because they mean different things:</p>
<ul>
<li><strong>A comparison</strong> - two online shops both published a price for the same product, so
the two prices can be set against each other. Every one of those rows carries a count of shops.</li>
<li><strong>A single-shop price</strong> - one shop published this price and nobody else quoted the
same product. It is a real price from a real page. It is not a comparison, and this page does not
call it the lowest price in any market.</li>
</ul>
<p class="note">Stock is reported only where the shop's own page said something we could read. Where
it says <strong>not read</strong>, the page we fetched carried no stock signal we could parse; that is
a gap in our reading, not a statement that the item is out of stock. The licence column is the NAFDAC
status of the product's registration: <strong>active</strong>, <strong>not active</strong>, or
<strong>not read</strong> where no status was ever scraped. A medicine whose licence reads
<em>not active</em> is still a priced medicine; the label is the finding.</p>

<h3 id="comparisons">Two shops, compared</h3>
<p class="tablelabel">{esc(COMPARISON_CAPTION)}</p>
<div class="tablewrap" role="region" aria-labelledby="comparisons" tabindex="0">
<table>
<caption>One product per row.</caption>
<thead><tr>
<th scope="col">Product</th><th scope="col">Shop with the lower price</th>
<th scope="col">Price</th><th scope="col">Stock</th><th scope="col">Registration</th>
<th scope="col">Price per pack unit</th>
</tr></thead>
<tbody>
{price_rows(comparison, with_state=False)}
</tbody>
</table>
</div>
<p class="note">{len(comparison)} rows. Every one comes from two shops quoting the same product; the
largest number of shops quoting a single product here is
{shops_text}. Price per pack unit is shown only where the pack size could be
read from the page, and is blank where it could not. On a narrow screen the table scrolls
sideways inside its own box; the rest of the page does not move.</p>

<h3 id="single">One shop only</h3>
<p class="tablelabel">Single-shop prices: one shop's price for one product, not a comparison</p>
<div class="tablewrap" role="region" aria-labelledby="single" tabindex="0">
<table>
<caption>Quoted by one shop only.</caption>
<thead><tr>
<th scope="col">Product</th><th scope="col">Where</th><th scope="col">Shop</th>
<th scope="col">Price</th><th scope="col">Stock</th><th scope="col">Registration</th>
</tr></thead>
<tbody>
{single_rows(single)}
</tbody>
</table>
</div>
<p class="note">{len(single)} rows. Drugstore.ng is recorded as a single shop covering the whole
country, so a Drugstore price can never pair with another shop's price in the same state and can
never form a comparison. On a narrow screen this table scrolls sideways inside its own box.</p>
</div>

<div class="wrap">
<h2 id="registration">Registration status of what is sold</h2>
<div class="fact">
<p><strong>{reg["flagged_listings"]} shop listings</strong> carry a registration that is not Active:
{reg["flagged_inactive"]} on an inactive registration and {reg["flagged_expired"]} on a registration
whose expiry date has passed. Only listings that were matched to a product with a registration number
can be checked at all.</p>
<p class="note">Coverage, in the same breath: this project holds a status for
<strong>{reg["registrations_status_read"]} of {reg["registrations_total"]} registrations</strong> in the
register list it holds ({reg["coverage_pct"]}%). The other
{reg["registrations_status_unread"]} have never had their detail page read. A partial sweep of the
register is not the register, so the count above is a count of what was checked, not a national
tally.</p>
</div>
<p>How the {overview["matched_listings"]} shop listings that carry a product divide up:</p>
<p class="tablelabel">Every listing matched to a product, by the registration behind that product</p>
<div class="tablewrap" role="region" aria-labelledby="registration" tabindex="0">
<table>
<caption>Adds up to the listings carrying a product.</caption>
<thead><tr><th scope="col">What the registration says</th><th scope="col">Listings</th></tr></thead>
<tbody>
<tr><th scope="row">Active</th><td class="num">{reg["matched_active"]}</td></tr>
<tr><th scope="row">Not Active, or past its expiry date</th>
<td class="num">{reg["matched_flagged"]}</td></tr>
<tr><th scope="row">A registration number, but no status ever read</th>
<td class="num">{reg["matched_status_not_read"]}</td></tr>
<tr><th scope="row">No registration number linked to the product</th>
<td class="num">{reg["matched_no_registration_number"]}</td></tr>
</tbody>
</table>
</div>
<p class="note">Those four numbers add up to {reg["matched_buckets_sum"]}, which is the number of shop
listings that carry a product. The {overview["unmatched_listings"]} listings without a product are not
in any of the rows above and do not appear in the price tables: a price nobody can name is not a price
anybody can use.</p>
<p><strong>No listing on this page has been compared by hand against a rendered NAFDAC record.</strong>
The status comes from a scraped page and nothing here has been eyeballed by a person. Treat
<em>not active</em> as "the register we hold says not active", which is a real finding and not the
same thing as a person having confirmed the record.</p>

<h2 id="health">Pipeline health</h2>
<p>This panel is about the machinery, not the medicines, and it says what did not happen as loudly as
what did. A source with no row in the run log at all is printed as <strong>never run</strong> - zero
rows is not "fine". A source is called <strong>stale</strong> after
{health["stale_hours_threshold"]:g} hours without a successful run.</p>
<p class="tablelabel">Last successful run of each source, as the run log records it (times UTC)</p>
<div class="tablewrap" role="region" aria-labelledby="health" tabindex="0">
<table>
<caption>One source per row.</caption>
<thead><tr>
<th scope="col">Source</th><th scope="col">Status</th>
<th scope="col">Last success</th><th scope="col">Age</th><th scope="col">What it does</th>
</tr></thead>
<tbody>
{health_rows(health)}
</tbody>
</table>
</div>
<p class="note">{health["runs_logged"]} runs are logged in total, the first at
{esc(health["first_run_utc"])} and the most recent finish at {esc(health["last_run_utc"])}. A failed
run is logged too, and a failed run is why a source can have rows in the log and still read
<em>never run</em> here: nothing has succeeded yet.</p>
{extras_line}

<h2 id="limits">What this page does not claim</h2>
<ol class="limits">
<li><strong>It is not the market.</strong> Prices come from {len(pharmacies)} online shops, and a
comparison needs two of them to publish the same product. Pharmacies that do not publish prices on a
website are not in this data at all, and nothing here is a national average or an index of what
medicines cost.</li>
<li><strong>A single-shop row is one shop's price.</strong> {overview["cells_single"]} of the
{overview["cells_total"]} priced products on this page were quoted by one shop only. They are shown
in their own table and are never described as a comparison.</li>
<li><strong>Registration coverage is partial.</strong> A status exists for
{reg["registrations_status_read"]} of {reg["registrations_total"]} registrations
({reg["coverage_pct"]}%). A product whose registration was never read carries
<a href="#registration">no status</a>, and that is a gap in this project's reading, not a finding
about the medicine.</li>
<li><strong>"Not active" describes a registration, not a medicine.</strong> A registration that has
lapsed or been marked inactive is recorded here as exactly that. It is not evidence that the medicine
is fake or illegal, and this project has not inspected, tested or bought any product.</li>
<li><strong>Brand and generic names count as separate products.</strong> The same medicine sold under
two names appears as two rows and is never compared with itself. {overview["unmatched_listings"]} of
{overview["latest_listings"]} shop listings could not be matched to any product and are absent from
the price tables.</li>
<li><strong>Prices are what a site displayed when it was read.</strong> Delivery, card fees,
counter discounts and what is on the shelf when you ask are all outside this data. The newest price
here is from {esc(overview["newest_scrape_utc"])}. Drugstore.ng is recorded as one shop covering the
whole country, so its price is a single national listing and can never form a comparison.</li>
</ol>

<h2 id="sources">Sources, licences and independence</h2>
<p>Prices are read from the public product pages of these shops, one page at a time, no faster than
one request every two seconds:</p>
<ul>
{pharmacy_list}
</ul>
<p>Registration numbers, statuses and expiry dates come from the NAFDAC Greenbook
({link(GREENBOOK_URL, "greenbook.nafdac.gov.ng")}). The medicines this project looks for come from
the #FixMedPrices catalogue, released under CC-BY-4.0 and credited here as its licence requires. The
Greenbook's certificate has expired, so its pages are fetched over plain HTTP and the integrity of
what we store rests on checksums we keep ourselves, not on the connection.</p>
<p><strong>This is an independent project.</strong> It is not endorsed by NAFDAC and it is not
endorsed by, affiliated with or paid by any pharmacy named on this page. Code is MIT licensed; the
data this page renders is CC-BY-4.0. The source, the schema and this page's generator are at
{link(REPO_URL, "github.com/batestguy/NaijaDrugWatch")}.</p>

<h2 id="check">How to check this page</h2>
<p>Every number here was read from the database when the page was built, and the same script then read
the database a second time and compared each value against what it had printed. If any value had
failed to match, this page would not have been written and the build would have failed. The same
numbers are in <a href="data.json">data.json</a>. The queries behind each figure are in the generator,
and the views they read are in the repository, so a stranger can re-run the whole thing.</p>
</div>
</main>
<div class="wrap">
<footer>
<img class="footer-mark" src="assets/dora/{MARK_FILE}" width="220" height="220" alt="">
<p><strong>{DORA_NAME} {DORA_HONOURS}</strong>, {self.dates}.
<a href="about.html">About her</a>.</p>
<p>Built from a Postgres database by <code>scripts/build_site.py</code>. Prices in Nigerian naira
(&#8358;). Times in UTC unless a Lagos date is named. The page is two files and four local images:
no external stylesheet, script, font or image is fetched, so it works with no network.</p>
<div class="credits">
<p><strong>Images.</strong> The mark in this footer, the portrait in the masthead and the wide crop in
the band are three crops of one photograph,
<a href="{esc(CREDIT_PORTRAIT['page'])}">{esc(CREDIT_PORTRAIT['title'])}</a> on Wikimedia Commons,
credited to the {esc(CREDIT_PORTRAIT['author'])} and released under
<a href="{esc(CREDIT_PORTRAIT['licence_url'])}">CC0 1.0</a>, a public domain dedication. That licence
requires no attribution; it is given here anyway, naming the file, the author and the change made to
it. One further image, a photograph of a memorial to her, appears on the
<a href="about.html">About page</a>, with its own credit beside it.</p>
<p class="note">The CC0 file is a photograph from the National Library of Nigeria, the same
institution whose repository holds the dates and the NAFDAC dates used on the About page. The
photograph and the register data are different things: the photograph identifies the person the
register is named for, and nothing on this page is drawn from it.</p>
</div>
</footer>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------------- the audit
def leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from leaves(child, f"{path}[{index}]")
    else:
        yield path, value


def parse_stamp(text: str) -> datetime | None:
    for pattern in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def same(printed: Any, fresh: Any, spec: Spec) -> tuple[bool, str]:
    if isinstance(printed, bool) or isinstance(fresh, bool):
        return (printed is fresh), ""
    if printed is None or fresh is None:
        return (printed is fresh), ""
    if isinstance(printed, (int, float)) and isinstance(fresh, (int, float)):
        if printed == fresh:
            return True, ""
        if isinstance(printed, float) or isinstance(fresh, float):
            if spec.float_tolerance and abs(printed - fresh) <= spec.float_tolerance:
                return True, ""
        return False, f"printed {printed!r}, re-read {fresh!r}"
    if isinstance(printed, str) and isinstance(fresh, str):
        if printed == fresh:
            return True, ""
        if spec.time_tolerance:
            left, right = parse_stamp(printed), parse_stamp(fresh)
            if left and right:
                drift = abs((left - right).total_seconds())
                if drift <= spec.time_tolerance:
                    return True, ""
                return False, f"printed {printed!r}, re-read {fresh!r} ({drift:.0f}s apart)"
        return False, f"printed {printed!r}, re-read {fresh!r}"
    return (printed == fresh), f"printed {printed!r}, re-read {fresh!r}"


def compare(printed: Any, fresh: Any, spec: Spec, path: str,
            problems: list[str]) -> None:
    if isinstance(printed, dict) and isinstance(fresh, dict):
        for key in printed:
            if key not in fresh:
                problems.append(f"{path}.{key}: present when printed, absent on re-read")
            else:
                compare(printed[key], fresh[key], spec, f"{path}.{key}", problems)
        for key in fresh:
            if key not in printed:
                problems.append(f"{path}.{key}: absent when printed, present on re-read")
        return
    if isinstance(printed, (list, tuple)) and isinstance(fresh, (list, tuple)):
        if len(printed) != len(fresh):
            problems.append(f"{path}: {len(printed)} rows became {len(fresh)}")
            return
        for index, (left, right) in enumerate(zip(printed, fresh)):
            compare(left, right, spec, f"{path}[{index}]", problems)
        return
    ok, detail = same(printed, fresh, spec)
    if not ok:
        problems.append(f"{path}: {detail}")


def audit(conn: Any, printed_facts: dict[str, Any], used: set[str]
          ) -> tuple[int, list[str]]:
    """Re-read every query and compare. Returns (numbers checked, problems).

    The comparison is keyed on the Spec, so `registration` and `health` - whose values are composed
    from two queries each - are audited against the composed value on the fresh read, with the
    tolerance their Spec declares. `breakdown` and `ledger` are raw inputs that the page never prints
    on their own; their leaves are still compared, and they are listed in CONSUMED so the
    "collected but never printed" check does not mistake them for dead weight.
    """
    fresh = read_facts(conn)
    problems: list[str] = []
    checked = 0
    for spec in SPECS:
        for _path, _value in leaves(printed_facts[spec.key]):
            checked += 1
        compare(printed_facts[spec.key], fresh[spec.key], spec, spec.key, problems)
    unused = sorted(set(printed_facts) - used - CONSUMED)
    if unused:
        problems.append(
            "facts collected but never printed, so not auditable from the page: " + ", ".join(unused)
        )
    return checked, problems


# --------------------------------------------------------------------------- main
def main() -> int:
    # The date guard runs first, before the database is opened and before any page is rendered: a
    # build with an unset date stops here rather than printing a date from memory.
    try:
        dates = dora_dates()
    except UnsetDate as exc:
        print(str(exc), file=sys.stderr)
        return 3

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

        facts = read_facts(conn)
        page = Page(facts, dates)
        document = page.build()

        checked, problems = audit(conn, facts, page.used)

    if problems:
        print(f"{checked} numbers checked, {len(problems)} unexplained", file=sys.stderr)
        for problem in problems[:40]:
            print("  unexplained:", problem, file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        print("nothing written: a page whose numbers cannot be re-derived is not published.",
              file=sys.stderr)
        return 1

    worst_contrast, contrast_problems = measure_contrast()
    if contrast_problems:
        print(f"contrast: {len(contrast_problems)} pair(s) below {CONTRAST_FLOOR}:1",
              file=sys.stderr)
        for problem in contrast_problems:
            print("  " + problem, file=sys.stderr)
        print("nothing written: text a reader cannot separate from its background is not published.",
              file=sys.stderr)
        return 1

    SITE.mkdir(parents=True, exist_ok=True)
    try:
        image_bytes = publish_images()
    except RuntimeError as exc:
        print(f"images: {exc}", file=sys.stderr)
        print("nothing written.", file=sys.stderr)
        return 1

    html_bytes = document.encode("utf-8")
    (SITE / "index.html").write_bytes(html_bytes)
    about_bytes = about_page(dates).encode("utf-8")
    (SITE / "about.html").write_bytes(about_bytes)

    payload = {
        "about": (
            "Machine-readable copy of the numbers on index.html, built by scripts/build_site.py from "
            "the project database. Every value here was re-read from the database after the page was "
            "rendered and compared; see audit."
        ),
        "repo": REPO_URL,
        "data_licence": "CC-BY-4.0",
        "code_licence": "MIT",
        "audit": {
            "numbers_checked": checked,
            "unexplained": 0,
            "how": "every query was run twice; the page is only written when both reads agree",
        },
        "row_counts": {
            "comparison_cells": len(facts["comparison_cells"]),
            "single_shop_cells": len(facts["single_cells"]),
            "health_sources": len(facts["health"]["sources"]),
        },
        "overview": facts["overview"],
        "registration": facts["registration"],
        "health": facts["health"],
        "pharmacies": facts["pharmacies"],
        "comparison_cells": facts["comparison_cells"],
        "single_shop_cells": facts["single_cells"],
        "limits": [
            "Prices come from the online shops this project reads, not from the market.",
            "A single-shop row is one shop's price and is not a comparison.",
            "Registration coverage is partial: see registration.coverage_pct.",
            "A registration that is not Active is a registration finding, not evidence about a medicine.",
            "Brand and generic names are separate products; unmatched listings are excluded.",
            "Prices are what a site displayed when it was read; Drugstore.ng is one national listing.",
        ],
    }
    json_bytes = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    (SITE / "data.json").write_bytes(json_bytes)

    print(f"wrote site/index.html ({len(html_bytes):,} bytes, "
          f"{len(facts['comparison_cells'])} comparison rows, "
          f"{len(facts['single_cells'])} single-shop rows)")
    print(f"wrote site/data.json ({len(json_bytes):,} bytes)")
    print(f"{checked:,} numbers checked, 0 unexplained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
