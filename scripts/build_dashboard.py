"""Build the explorable page: every price, what the dataset contains, and what it cannot say.

WHY A STATIC PAGE RATHER THAN THE STREAMLIT APP. The dashboard in `dashboard/` is a live application: it
opens a database connection on every visit. That was right while the pipeline ran nightly. The project is
frozen, so every visit would return the same numbers - and a hosted app would put the connection string
on a third party and depend on a free database that suspends itself when idle. The one thing the
Streamlit app offered that the front page did not is interactivity, and interactivity does not need a
server: 2,800 rows are 400 KB of JSON and a filter is twenty lines of JavaScript.

WHAT THIS WRITES. `site/dashboard.html` - one file, no external stylesheet, script, font, image or
network call, so it opens from a double-click with no connection. The three charts are inline SVG built
here, not drawn by a library, and the table holds every row in the browser so search, sort, the ten-row
window and the CSV export all work with no server.

WHAT IT PROVES BEFORE WRITING. It runs every query twice and compares: the rows, and each of the
figures and counts the page prints. A figure that cannot be derived is a failed build, not a zero. Every
text-on-background pair the page uses is measured here, and a pair under 4.5:1 refuses to publish.

WHAT IT DELIBERATELY DOES NOT DO. It never colours a price, and no green appears on the page: her navy,
red and gold are categories with a legend - never good and bad - and "never read" is a pattern rather
than a fourth colour, because a gap in our reading is not a finding about a medicine.

    .venv\\Scripts\\python.exe -X utf8 scripts/build_dashboard.py
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from envfile import ensure_database_url

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BUILD_SITE = Path(__file__).resolve().parent / "build_site.py"
REPO_URL = "https://github.com/batestguy/NaijaDrugWatch"
FREEZE = json.loads((ROOT / "freeze.json").read_text(encoding="utf-8"))

# ---- the palette -----------------------------------------------------------------------------------
# Taken from the methods page, which is where her three colours were first sampled off the photograph
# (navy, red, the gold of the wrapper's print) on a cream paper. They are repeated here rather than
# imported, because importing `build_site` would load two embedded typefaces and three hundred lines of
# page template to read eleven colours. The copy is not trusted: `audit_palette()` reads the same
# constants out of `build_site.py` at build time and fails if the two have drifted apart.
CREAM_INK = "#1a1612"
CREAM_MUTED = "#4a423d"
CREAM_LINE = "#d7cfbe"
CREAM_PAPER = "#faf7f1"
CREAM_PANEL = "#f1ebdf"
CREAM_ACCENT = "#5f2a54"
ZEBRA = "#fffdf9"
DRESS_NAVY = "#161A64"   # her wrapper, unchanged: 14.6:1 on the page
DRESS_RED = "#9F2519"    # her wrapper, unchanged: 7.3:1 on the page
DRESS_GOLD = "#7A5800"   # the gold of the print at text strength; the raw #D7A320 is 2.2:1 as a fill
# The raw gold is a band fill on this page, so it needs a name of its own: as a surface it carries ink
# at 7.6:1, and as text on paper it would be 2.18:1, which is why it is never used for words.
DRESS_GOLD_RAW = "#D7A320"
PAPER_WHITE = "#FFFFFF"  # the text on the navy band and the red band


def _blend(front: str, back: str, alpha: float) -> str:
    """The colour a reader sees when a layer is painted at `alpha` over a background."""
    out = []
    for i in (1, 3, 5):
        f = int(front[i:i + 2], 16)
        b = int(back[i:i + 2], 16)
        out.append(int(round(alpha * f + (1 - alpha) * b)))
    return "#%02X%02X%02X" % tuple(out)


TINT_NAVY = _blend(DRESS_NAVY, CREAM_PAPER, 0.10)
TINT_RED = _blend(DRESS_RED, CREAM_PAPER, 0.10)
TINT_GOLD = _blend(DRESS_GOLD, CREAM_PAPER, 0.12)
# The empty part of a measure in the charts. A reader has to be able to see where the bar ends, so this
# is the muted ink at three quarters strength rather than the hairline the tables use.
TRACK = _blend(CREAM_MUTED, CREAM_PANEL, 0.75)
# The row under the pointer: her navy at four parts in a hundred over the paper - a tint a reader sees
# without it reading as a state. Measured as text-on-surface in CONTRAST_PAIRS, never assumed.
HOVER_TINT = _blend(DRESS_NAVY, CREAM_PAPER, 0.04)

# ---- what the page is allowed to say ---------------------------------------------------------------
# The four licence categories, in the order they stack, each with the colour it is drawn in. Three of
# them are her colours; "never read" is a pattern, because it is the absence of an answer and must not
# look like an answer. Every one of them is also printed as a number in text.
LICENCE_STATES: list[tuple[str, str, str]] = [
    ("active", DRESS_NAVY, ""),
    ("inactive", DRESS_GOLD, ""),
    ("expired", DRESS_RED, ""),
    ("never read", "", "\u2014 a gap in our data, not a finding"),
]

SQL = """
select l.listing_id,
       l.pharmacy_name,
       l.state,
       coalesce(l.canonical_name, '') as medicine,
       l.raw_title,
       l.price_ngn,
       l.pack_size,
       coalesce(l.pack_unit, '') as pack_unit,
       l.unit_price,
       l.in_stock,
       l.url,
       coalesce(p.strength, '') as strength,
       coalesce(r.registration_number, '') as registration,
       coalesce(r.status, '') as status,
       r.expiry_date,
       coalesce(r.source_url, '') as register_url,
       case when c.product_id is null then 0 else 1 end as in_comparison,
       case when s.listing_id is null then 0 else 1 end as flagged,
       to_char(l.scraped_at at time zone 'UTC', 'YYYY-MM-DD') as as_at
  from v_latest_listings l
  left join products p on p.id = l.product_id
  left join nafdac_registrations r on r.registration_number = p.nafdac_registration_number
  left join (select distinct product_id
               from v_cheapest_per_product_state
              where is_comparison) c on c.product_id = l.product_id
  left join (select listing_id from v_suspicious_listings) s on s.listing_id = l.listing_id
 order by medicine nulls last, l.price_ngn
"""

# The counts that cannot be read off the price rows: the register, the comparison cells, the runs.
COUNT_SQL = {
    "registrations": "select count(*) from nafdac_registrations",
    "registrations_read": "select count(*) from nafdac_registrations where status is not null",
    "comparisons": "select count(*) from v_cheapest_per_product_state where is_comparison",
    # How many of those comparison cells actually price the same pack. A comparison of a 100-tablet
    # box against a 10-tablet strip is not a price difference, it is two different products, so the
    # figure beside "comparisons" has to be this one and not the cell total. The rule, stated so it can
    # be argued with: a cell is like for like when every in-stock price behind it states the same pack
    # size and none of them leaves the pack size blank. Joined on product_id, the view's own key, not
    # on the display name - a name join silently drops cells and overstates the share.
    "like_for_like": """with cells as (
      select product_id, state from v_cheapest_per_product_state where is_comparison
    ), per as (
      select c.product_id, c.state,
             count(distinct l.pack_size) as distinct_packs,
             count(*) filter (where l.pack_size is null) as blank_rows
        from cells c
        join v_latest_listings l
          on l.product_id = c.product_id and l.state = c.state and l.in_stock is not false
       group by 1, 2
    )
    select count(*) filter (where distinct_packs = 1 and blank_rows = 0) from per""",
    "flagged": "select count(*) from v_suspicious_listings",
    "newest": "select to_char(max(scraped_at) at time zone 'UTC', 'YYYY-MM-DD') from pharmacy_listings",
}

RUNS_SQL = """
select to_char((started_at at time zone 'UTC')::date, 'YYYY-MM-DD') as day,
       count(*) as runs,
       count(*) filter (where status = 'success') as ok
  from scrape_runs
 group by 1
 order by 1
"""

# Every text-on-surface pair the page uses. Measured in `measure_contrast`, printed with the worst one,
# and any pair under the floor stops the build. All of them are flat colours: no text sits on an image.
CONTRAST_FLOOR = 4.5
CONTRAST_PAIRS: list[tuple[str, str, str]] = [
    ("page: body text on the page", CREAM_INK, CREAM_PAPER),
    ("page: secondary text on the page", CREAM_MUTED, CREAM_PAPER),
    ("page: links on the page", CREAM_ACCENT, CREAM_PAPER),
    ("page: a figure's number on the page", DRESS_NAVY, CREAM_PAPER),
    ("page: body text on a panel", CREAM_INK, CREAM_PANEL),
    ("page: secondary text on a panel", CREAM_MUTED, CREAM_PANEL),
    ("page: links on a panel", CREAM_ACCENT, CREAM_PANEL),
    ("page: the focus ring on the page", CREAM_INK, CREAM_PAPER),
    ("table: header text on the header", CREAM_MUTED, CREAM_PANEL),
    ("table: body text on a plain row", CREAM_INK, CREAM_PAPER),
    ("table: body text on a tinted row", CREAM_INK, ZEBRA),
    ("table: a link on a tinted row", CREAM_ACCENT, ZEBRA),
    ("table: a digit on a plain row", CREAM_INK, CREAM_PAPER),
    ("tag: active, on its own tint", DRESS_NAVY, TINT_NAVY),
    ("tag: inactive, on its own tint", DRESS_GOLD, TINT_GOLD),
    ("tag: expired, on its own tint", DRESS_RED, TINT_RED),
    ("tag: never read, on the panel", CREAM_INK, CREAM_PANEL),
    ("tag: in stock, on the panel", CREAM_INK, CREAM_PANEL),
    ("tag: out of stock, on its own tint", DRESS_RED, TINT_RED),
    ("tag: no stock stated, on the panel", CREAM_INK, CREAM_PANEL),
    ("chart: a label on the chart ground", CREAM_INK, CREAM_PANEL),
    ("chart: a secondary label on the chart ground", CREAM_MUTED, CREAM_PANEL),
    ("chart: the authored bar, on the chart ground", DRESS_NAVY, CREAM_PANEL),
    ("chart: the inactive fill, on the chart ground", DRESS_GOLD, CREAM_PANEL),
    ("chart: the expired fill, on the chart ground", DRESS_RED, CREAM_PANEL),
    ("picker: the highlighted match, on its tint", CREAM_INK, TINT_NAVY),
    # The bands that separate the sections, one pair each: white on her navy, white on her red, ink on
    # the raw gold, ink on paper. "Six bands, four pairs" is the whole colour system of the document.
    ("band: white on the navy band", PAPER_WHITE, DRESS_NAVY),
    ("band: white on the red band", PAPER_WHITE, DRESS_RED),
    ("band: ink on the gold band", CREAM_INK, DRESS_GOLD_RAW),
    ("band: ink on a paper band", CREAM_INK, CREAM_PAPER),
    # The jump bar: an item at rest, then the active item in each section's own colour. The gold one is
    # the text-strength gold, because the raw gold as text is 2.18:1 and would fail.
    ("jump: an item at rest, on the bar", CREAM_INK, CREAM_PAPER),
    ("jump: the active item, navy on the bar", DRESS_NAVY, CREAM_PAPER),
    ("jump: the active item, red on the bar", DRESS_RED, CREAM_PAPER),
    ("jump: the active item, gold on the bar", DRESS_GOLD, CREAM_PAPER),
    # The table's own states: the row under the pointer, and the filter chips.
    ("row: text on the row under the pointer", CREAM_INK, HOVER_TINT),
    ("chip: the chip's text on its tint", CREAM_INK, TINT_NAVY),
    ("chip: the clear-all label on the panel", CREAM_INK, CREAM_PANEL),
    # the site bar above the jump bar: its links, and the rule under the current page
    ("nav: a link on the bar", CREAM_INK, CREAM_PAPER),
    ("nav: the current page's rule on the bar", DRESS_RED, CREAM_PAPER),
]

# Measured and printed, and held to the floor in the fourth column: 3.0 for a boundary a reader has to
# see, 0.0 for a tint that carries no meaning on its own. A boundary below 3:1 fails the build.
DECORATIVE_PAIRS: list[tuple[str, str, str, float, str]] = [
    ("the tinted row against the page", ZEBRA, CREAM_PAPER, 0.0, "a tint, not a boundary"),
    ("the table's hairline against the page", CREAM_LINE, CREAM_PAPER, 0.0, "a hairline, not a boundary"),
    ("a pale tag border against its tint", DRESS_NAVY, TINT_NAVY, 3.0, "a boundary"),
    ("a measure's empty track on the chart ground", TRACK, CREAM_PANEL, 3.0, "a boundary"),
    ("a price bar's fill against its own track", CREAM_INK, CREAM_PANEL, 3.0, "a boundary"),
    ("a paper band's navy top rule", DRESS_NAVY, CREAM_PAPER, 3.0, "a boundary"),
    ("a paper band's red top rule", DRESS_RED, CREAM_PAPER, 3.0, "a boundary"),
    ("the row under the pointer against the page", HOVER_TINT, CREAM_PAPER, 0.0, "a tint, not a boundary"),
]

# ---- the page as six sections ----------------------------------------------------------------------
# ONE LIST, USED TWICE. The jump bar and the band that opens each section are both generated from here,
# so a bar item cannot exist without a band and a band cannot exist without a bar item - the failure a
# hand-written bar always eventually has. The order is the page order and the number is the position, so
# renumbering is a re-sort, not four edits. The band colours alternate, so no two neighbours match, and
# each one is a pair measured in CONTRAST_PAIRS above.
#
# "accent" is what the bar item turns when its section is in view. For the gold band it is the same gold
# taken to text strength (DRESS_GOLD), because the raw gold fails 4.5:1 as words on paper.
SECTIONS: list[dict[str, str]] = [
    {"id": "s-data", "n": "01", "name": "The data", "theme": "navy", "accent": "navy",
     "stand": "Not the whole market: these shops."},
    {"id": "s-survive", "n": "02", "name": "How much survives", "theme": "paper-navy",
     "accent": "navy",
     "stand": ""},
    {"id": "s-licence", "n": "03", "name": "The licence", "theme": "red", "accent": "red",
     "stand": ""},
    {"id": "s-nights", "n": "04", "name": "Nine nights", "theme": "paper-red", "accent": "red",
     "stand": "Navy: succeeded. Hatched: not successful."},
    {"id": "ask", "n": "05", "name": "Ask it", "theme": "gold", "accent": "gold",
     "stand": "Out-of-stock prices never count."},
    {"id": "browse", "n": "06", "name": "Browse it", "theme": "navy", "accent": "navy",
     "stand": "Names as the shops wrote them."},
]

# The three row heights the table offers, in the order the list shows them, with the pixels each one
# sets. Written once and checked against the JavaScript's own table at build time, so the two cannot
# drift apart. The middle one is the default and is what the page was built at before this list existed.
DENSITIES: list[tuple[str, str, int]] = [
    ("compact", "Compact", 32),
    ("comfortable", "Comfortable", 36),
    ("spacious", "Spacious", 44),
]


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value: Any) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}"


def licence_state(status: str, has_record: bool) -> str:
    """Four labels from the register's own words, or "never read" when it said nothing.

    WHY THIS IS NOT DERIVED FROM `v_suspicious_listings`. The view answers a different question - "is
    this listing suspect?" - and lumps inactive with expired. The page needs the four states separately
    so the reader can see which of them is a gap in our reading. The two are reconciled in `main`:
    inactive + expired must equal the view's count, or nothing is written.
    """
    if not has_record:
        return "never read"
    if status == "Active":
        return "active"
    if status == "Inactive":
        return "inactive"
    if status == "Expired":
        return "expired"
    return "never read"


def fetch(conn) -> list[dict[str, Any]]:
    rows = []
    for (listing_id, shop, state, medicine, title, price, pack, unit, unit_price, stock,
         url, strength, registration, status, expiry, register_url, in_comparison, flagged,
         as_at) in conn.execute(SQL):
        rows.append({
            "i": listing_id,
            "s": shop,
            "t": title or medicine or "unnamed listing",
            "m": medicine,
            "p": money(price),
            "k": pack,
            "u": (unit or "").strip(),
            "pu": money(unit_price),
            "st": None if stock is None else (1 if stock else 0),
            "a": url or "",
            "x": int(in_comparison),
            "g": registration or "",
            "l": licence_state(status, bool(registration)),
            "ru": register_url or "",
            # The day this quote was read, which is not the same day for every row: collection ran
            # from 7 to 15 November and a listing keeps the date it was last seen. The picker prints
            # it, because "the price on this page" and "the price on the shop's page today" differ.
            "d": as_at or "",
        })
    return rows


def fetch_counts(conn) -> dict[str, Any]:
    counts = {name: conn.execute(sql).fetchone()[0] for name, sql in COUNT_SQL.items()}
    counts["runs"] = [
        {"day": day, "runs": runs, "ok": ok}
        for day, runs, ok in conn.execute(RUNS_SQL)
    ]
    return counts


# ---- the figures -----------------------------------------------------------------------------------
def figures(rows: list[dict[str, Any]], counts: dict[str, Any]) -> list[dict[str, str]]:
    """The six numbers, each derived here, each carrying the line that says what it counts.

    Every one is a value computed from the rows just read or from a query re-read in the same
    connection. None is typed, and `main` fails the build if any of them comes back empty.
    """
    by_state: dict[str, int] = {}
    for row in rows:
        if not row["m"]:
            continue  # a price with no medicine was never looked up, so it has no state to count
        by_state[row["l"]] = by_state.get(row["l"], 0) + 1
    with_status = by_state.get("active", 0) + by_state.get("inactive", 0) + by_state.get("expired", 0)
    read = counts["registrations_read"]
    total = counts["registrations"]
    frozen_on = datetime.strptime(FREEZE["frozen_on"], "%Y-%m-%d")
    return [
        {"k": "prices", "label": "prices collected", "value": f"{len(rows):,}",
         "sub": f"over {len(counts['runs'])} nights"},
        {"k": "medicines", "label": "medicines priced",
         "value": f"{len({r['m'] for r in rows if r['m']}):,}", "sub": ""},
        {"k": "comparisons", "label": "two shops price it", "value": f"{counts['comparisons']:,}",
         "sub": f"{counts['like_for_like']:,} with the same pack size"},
        {"k": "lapsed", "label": "licence not active", "value": f"{counts['flagged']:,}",
         "sub": f"of {with_status:,} with a status"},
        {"k": "register", "label": "licence status known",
         "value": f"{100.0 * read / total:.1f}%" if total else "",
         "sub": f"of {total:,} registrations"},
        {"k": "frozen", "label": "data collected up to", "value": frozen_on.strftime("%d %b %Y"),
         "sub": ""},
    ]


# ---- what a day of wages is ------------------------------------------------------------------------
# The law states a month, so a daily rate is a convention and the page says whose: 30 days to the month
# is the WHO/HAI affordability method's convention. The national rate is used rather than Lagos's
# 85,000, because no shop in this data publishes a price per state - this page has one price per shop -
# and dividing a national price by a Lagos wage would invent a comparison. Both rates are named here so
# the footnote cannot drift from the arithmetic that is printed beside it.
MINIMUM_WAGE_MONTHLY_NGN = 70_000        # National Minimum Wage (Amendment) Act 2024, national rate
MINIMUM_WAGE_DAYS_PER_MONTH = 30          # WHO/HAI: a month of wages is 30 days
MINIMUM_WAGE_DAILY_NGN = MINIMUM_WAGE_MONTHLY_NGN // MINIMUM_WAGE_DAYS_PER_MONTH   # 2,333
LAGOS_MINIMUM_WAGE_MONTHLY_NGN = 85_000   # named only so the footnote can say why it is not the rate
# A pack is not a course. The project holds no dosing - no dose, no frequency, no duration - so the
# figure answers "what part of a day's wage buys this box" and never "can this be paid for for a month".
DAYS_FIGURE_SUB = "days of minimum wage to buy this pack"


def _half_up(value: float, places: int) -> float:
    """Round half away from zero, which is what the page's own `toFixed` does; `round` is half-even.

    The five figures are computed twice - here at build time, and in the browser on every selection -
    so the two must round identically or a reader comparing the page with the build log sees a
    difference that is not in the data.
    """
    factor = 10 ** places
    return math.floor(abs(value) * factor + 0.5) / factor * (1 if value >= 0 else -1)


def _ngn(value: float) -> str:
    return "\u20a6" + f"{_half_up(value, 2):,.2f}"


def _pct(value: float) -> str:
    """A percentage at a precision a reader can use: whole numbers past 100, one decimal below it."""
    return f"{_half_up(value, 0):,.0f}%" if value >= 100 else f"{_half_up(value, 1):.1f}%"


def _and_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def ask_pack(row: dict[str, Any]) -> str:
    """The pack as the shop stated it, or an empty string when it stated no size."""
    if row["k"] is None:
        return ""
    return f"{row['k']} {row['u']}".strip() if row["u"] else str(row["k"])


def ask_medicines(rows: list[dict[str, Any]]) -> list[str]:
    """Every medicine a price was attached to: the 288 names the picker offers, in one fixed order."""
    return sorted({r["m"] for r in rows if r["m"]})


def ask_quotes(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The quotes for one medicine, cheapest first. Never any other medicine's price."""
    return sorted((r for r in rows if r["m"] == name),
                  key=lambda r: (float(r["p"]), r["s"]))


def _shops_at(quotes: list[dict[str, Any]], price: float) -> list[str]:
    """The shops quoting that exact price, each named once, in the order the quotes come."""
    out: list[str] = []
    for q in quotes:
        if float(q["p"]) == price and q["s"] not in out:
            out.append(q["s"])
    return out


# ---- the shop's own stock statement -----------------------------------------------------------------
# Three values, and the third one is not a guess. A shop either says the medicine is in stock, says it is
# out of stock, or says nothing either way - and 14 of the 2,800 prices say nothing. Reading those as
# available would be inventing a fact about a shop, and quoting a price for a medicine nobody has would
# be inventing an offer. So the state is carried in words on every quote and used as a filter here.
STOCK_IN = 1
STOCK_OUT = 0
STOCK_UNSTATED = None
STOCK_WORDS = {STOCK_IN: "in stock", STOCK_OUT: "out of stock", STOCK_UNSTATED: "state not stated"}


def ask_in_stock(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the quotes a shop marked in stock: the only ones a cheapest or a dearest may be read off."""
    return [q for q in quotes if q["st"] == STOCK_IN]


def _no_stock_sub(f: dict[str, Any]) -> str:
    """Why the tiles carry no price, in the words that are true for this medicine's quotes."""
    if f["out"] and f["unstated"]:
        head = f"{f['out']} marked out of stock, {f['unstated']} stating no stock"
    elif f["out"]:
        head = f"all {f['out']} marked out of stock"
    else:
        head = "no quote states whether it is in stock"
    return head + " \u2014 listed below"


def ask_figures(quotes: list[dict[str, Any]]) -> dict[str, Any]:
    """The five figures for one medicine, over the quotes a shop marked IN STOCK, and the gap's rule.

    WHY ONLY IN-STOCK QUOTES. A price beside a medicine the shop has marked out of stock is a page a
    reader cannot buy from. Putting the lowest of those on the page as "the cheapest" states an offer
    that does not exist - on this vintage that would have shown Amoxicillin at ₦590 when the cheapest
    shop that actually has it charges ₦29,540, a fifty-fold misstatement.

    The gap's honest rule, in four branches and no fifth:
      * no in-stock quote   -> the words "no shop has this in stock". No cheapest, no dearest, no zero.
      * one shop only       -> the words "no second shop". Never naira 0 and never 0%.
      * every quote states the same pack size -> the naira gap and the percentage.
      * packs differ, or a pack was never stated -> the naira gap and "packs differ - not a saving",
        because a 10-tablet strip beside a 56-tablet box is two different products, not a saving.
    A pack size that was never stated cannot be evidence that two packs are the same, so it takes the
    last branch rather than the percentage.
    """
    inside = ask_in_stock(quotes)
    prices = sorted(float(q["p"]) for q in inside)
    n = len(prices)
    has_price = n > 0
    cheapest = prices[0] if has_price else None
    dearest = prices[-1] if has_price else None
    median = None
    if has_price:
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    shops = sorted({q["s"] for q in inside})
    packs = {ask_pack(q) for q in inside}
    # A pack size that was never stated is not evidence that two packs match, so it takes the third
    # branch. `ask_pack` returns "" for "not stated", so the blank is detected from the raw column.
    if not has_price:
        mode = "none"
    elif len(shops) < 2:
        mode = "single"
    elif len(packs) == 1 and all(q["k"] is not None for q in inside):
        mode = "percent"
    else:
        mode = "packs"
    return {
        "n": n,                      # quotes a shop marked in stock: the ones these figures use
        "quoted": len(quotes),       # every quote the shops published for this medicine
        "out": sum(1 for q in quotes if q["st"] == STOCK_OUT),
        "unstated": sum(1 for q in quotes if q["st"] == STOCK_UNSTATED),
        "cheapest": cheapest,
        "dearest": dearest,
        "median": median,
        "gap": (dearest - cheapest) if has_price else None,
        "gap_pct": (dearest - cheapest) / cheapest * 100 if cheapest else 0.0,
        "gap_mode": mode,
        "days": (cheapest / MINIMUM_WAGE_DAILY_NGN) if has_price else None,
        "shops": shops,
        # A shop that lists the same medicine twice at the same price is one shop at that price, not
        # two: the tile names the shops, so it names each once, in price order.
        "cheapest_shops": [s for s in _shops_at(inside, cheapest)] if has_price else [],
        "dearest_shops": [s for s in _shops_at(inside, dearest)] if has_price else [],
        "packs": sorted(p for p in packs if p),
        "pack_missing": any(q["k"] is None for q in inside),
    }


def ask_tiles(quotes: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """The tiles as (label, value, sub-line). The browser prints the same ones from the same rule.

    One tile, not five, when no shop has the medicine in stock: five tiles of dashes would look like a
    gap in our reading, and the reason is not a gap, it is that every shop says it has none.
    """
    f = ask_figures(quotes)
    if f["gap_mode"] == "none":
        return [("lowest price", "no shop has this in stock", _no_stock_sub(f))]
    n = f["n"]
    # "of 2 prices" when every quote is in stock; "of 2 in-stock prices" when some were left out, so the
    # sub-line cannot be read as a claim about a price it did not use.
    which = "in-stock " if (f["out"] + f["unstated"]) else ""
    tiles = [
        ("lowest price", _ngn(f["cheapest"]), "at " + _and_list(f["cheapest_shops"])),
        ("highest price", _ngn(f["dearest"]), "at " + _and_list(f["dearest_shops"])),
        ("middle price", _ngn(f["median"]),
         f"of {n} {which}prices" if n > 1 else f"of the one {which}price"),
    ]
    if f["gap_mode"] == "single":
        tiles.append(("gap", "no second shop", "one shop has it in stock"))
    elif f["gap_mode"] == "packs":
        tiles.append(("gap", _ngn(f["gap"]), "packs differ \u2014 not a saving"))
    else:
        tiles.append(("gap", _ngn(f["gap"]), "+" + _pct(f["gap_pct"]) + " on the lowest, same pack size"))
    tiles.append(("days of minimum wage", f"{_half_up(f['days'], 2):.2f}", DAYS_FIGURE_SUB))
    return tiles


def ask_default(rows: list[dict[str, Any]]) -> tuple[str, int, int]:
    """The medicine the block opens on: the most shops quoting it, then the most quotes, then the name.

    Not taste. Opening on a medicine only one shop sells would show "no second shop" before the reader
    has learned what the block does, and would make the page's first answer an empty one.
    """
    seen: dict[str, tuple[set[str], int]] = {}
    for row in rows:
        if not row["m"]:
            continue
        shops, quotes = seen.get(row["m"], (set(), 0))
        shops.add(row["s"])
        seen[row["m"]] = (shops, quotes + 1)
    ranked = sorted(seen.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))
    name, (shops, quotes) = ranked[0]
    return name, len(shops), quotes


def ask_line(name: str, quotes: list[dict[str, Any]]) -> str:
    """One medicine, five figures, one line - printed for all of them so any tile can be checked."""
    f = ask_figures(quotes)
    head = (f"{name[:38]:<38s} {len(f['shops'])}s/{f['n']:>2}q in stock, "
            f"{f['out']} out, {f['unstated']} unknown  ")
    if f["gap_mode"] == "none":
        return head + "no shop has this in stock - the prices it published are not a cheapest"
    if f["gap_mode"] == "single":
        gap = "gap          no second shop"
    elif f["gap_mode"] == "packs":
        gap = f"gap {_ngn(f['gap']):>12s}  packs differ"
    else:
        gap = f"gap {_ngn(f['gap']):>12s}  +{_pct(f['gap_pct'])}"
    return (head + f"lo {_ngn(f['cheapest']):>11s}  hi {_ngn(f['dearest']):>11s}  "
            f"med {_ngn(f['median']):>11s}  {gap}  {_half_up(f['days'], 2):6.2f} days")


def _js_money(value: str) -> str:
    """Naira at two decimals, half away from zero - formatting that shares no code with `_ngn`."""
    return "\u20a6" + format(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ",.2f")


def _js_pct(value: Decimal) -> str:
    if value >= 100:
        return format(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP), ",.0f") + "%"
    return format(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), ".1f") + "%"


def browser_tiles(payload: str, name: str) -> list[tuple[str, str, str]]:
    """The tiles the page's own JavaScript would print, recomputed from the JSON the page embeds.

    WHY THIS IS WRITTEN TWICE. The five figures exist twice: `ask_tiles` here, and `askTiles` in the
    page. A reader sees the second one. If the two drift - one filtering out-of-stock quotes and the
    other not, or one rounding differently - the build log would keep printing a number the page never
    shows, which is exactly the failure this ticket exists to remove.

    This is a second implementation, not a call into the first: it reads the payload as the browser
    receives it (strings, `st` as 1/0/null), follows the JavaScript's own order of operations, and
    formats money and percentages with `Decimal` rather than with `_ngn`/`_pct`. What it cannot prove is
    that the JavaScript itself is what runs in a browser - that was done once by hand, in node, and is
    recorded in the ticket's report rather than run on every build, because the build must not depend on
    a JavaScript runtime being installed.
    """
    data = json.loads(payload)
    quotes = sorted((r for r in data if r["m"] == name),
                    key=lambda r: (float(r["p"]), r["s"]))
    inside = [r for r in quotes if r["st"] == 1]
    prices = [Decimal(r["p"]) for r in inside]
    n = len(prices)
    out = sum(1 for r in quotes if r["st"] == 0)
    unstated = sum(1 for r in quotes if r["st"] is None)
    if not n:
        if out and unstated:
            head = f"{out} marked out of stock, {unstated} stating no stock"
        elif out:
            head = f"all {out} marked out of stock"
        else:
            head = "no quote states whether it is in stock"
        return [("lowest price", "no shop has this in stock", head + " \u2014 listed below")]

    def pack(r: dict[str, Any]) -> str:
        if r["k"] is None:
            return ""
        return f"{r['k']} {r['u']}".strip() if r["u"] else str(r["k"])

    def at(price: Decimal) -> list[str]:
        found: list[str] = []
        for r in inside:
            if Decimal(r["p"]) == price and r["s"] not in found:
                found.append(r["s"])
        return found

    shops = []
    for r in inside:
        if r["s"] not in shops:
            shops.append(r["s"])
    packs = {pack(r) for r in inside}
    def at(price: Decimal) -> str:
        found: list[str] = []
        for r in inside:
            if Decimal(r["p"]) == price and r["s"] not in found:
                found.append(r["s"])
        return "at " + (", ".join(found[:-1] + ["and " + found[-1]]) if len(found) > 1 else "".join(found))

    cheapest, dearest = prices[0], prices[-1]
    median = prices[(n - 1) // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    missing = any(r["k"] is None for r in inside)
    mode = ("single" if len(shops) < 2
            else ("percent" if len(packs) == 1 and not missing else "packs"))
    which = "in-stock " if (out + unstated) else ""
    tiles = [
        ("lowest price", _js_money(cheapest), at(cheapest)),
        ("highest price", _js_money(dearest), at(dearest)),
        ("middle price", _js_money(median),
         f"of {n} {which}prices" if n > 1 else f"of the one {which}price"),
    ]
    if mode == "single":
        tiles.append(("gap", "no second shop", "one shop has it in stock"))
    elif mode == "packs":
        tiles.append(("gap", _js_money(dearest - cheapest), "packs differ \u2014 not a saving"))
    else:
        tiles.append(("gap", _js_money(dearest - cheapest),
                      "+" + _js_pct((dearest - cheapest) / cheapest * 100) +
                      " on the lowest, same pack size"))
    tiles.append(("days of minimum wage",
                  format((cheapest / Decimal(MINIMUM_WAGE_DAILY_NGN)).quantize(
                      Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
                  DAYS_FIGURE_SUB))
    return tiles



# ---- the charts ------------------------------------------------------------------------------------
# Inline SVG, built here. Each one is `role="img"` with an `aria-label` that carries the headline fact,
# so a reader who cannot see the drawing is told the answer rather than the shape. No chart encodes a
# value in colour alone: every series has its number printed beside it in text.

CHART_W = 360  # the coordinate system every chart is drawn in; the page scales it, never redraws it


def _fmt_pct(value: int, base: int) -> str:
    pct = 0.0 if not base else 100.0 * value / base
    return "100%" if pct >= 99.95 else f"{pct:.1f}%"


def _gap_pattern(name: str) -> str:
    """The hatch that means "we do not know", drawn rather than filled, so it is never read as a colour."""
    return ('<defs><pattern id="' + name + '" width="7" height="7" patternUnits="userSpaceOnUse" '
            f'patternTransform="rotate(45)"><rect width="7" height="7" fill="{CREAM_PANEL}"/>'
            f'<line x1="0" y1="0" x2="0" y2="7" stroke="{CREAM_INK}" stroke-width="2.2"/>'
            "</pattern></defs>")


def chart_funnel(steps: list[tuple[str, int]]) -> str:
    """Four bars, one per stage, each with its number and share printed at the right of its label."""
    base = steps[0][1]
    row_h, bar_h = 44, 12
    height = len(steps) * row_h + 8
    parts = [f'<svg viewBox="0 0 {CHART_W} {height}" role="img" aria-label="'
             f'Of {base:,} prices, {steps[1][1]:,} matched to a medicine, '
             f'{steps[2][1]:,} carry a readable licence status, and {steps[3][1]:,} can be compared '
             f'across two shops." class="chart">']
    for i, (label, value) in enumerate(steps):
        y = 8 + i * row_h
        width = max(3.0, CHART_W * value / base) if base else 0.0
        parts.append(f'<text x="0" y="{y + 13}" class="cl">{esc(label)}</text>')
        parts.append(f'<text x="{CHART_W}" y="{y + 13}" class="cv" text-anchor="end">'
                     f'{value:,} &middot; {_fmt_pct(value, base)}</text>')
        parts.append(f'<rect x="0" y="{y + 19}" width="{CHART_W}" height="{bar_h}" rx="2" '
                     f'fill="{CREAM_PAPER}" stroke="{TRACK}" stroke-width="1"/>')
        parts.append(f'<rect x="0" y="{y + 19}" width="{width:.1f}" height="{bar_h}" rx="2" '
                     f'fill="{DRESS_NAVY}"/>')
    parts.append("</svg>")
    return "".join(parts)


def chart_licence(counts: dict[str, int]) -> str:
    """One stacked bar, the four states in order, "never read" hatched rather than filled."""
    total = sum(counts.values()) or 1
    bar_y, bar_h, height = 4, 34, 46
    parts = [f'<svg viewBox="0 0 {CHART_W} {height}" role="img" aria-label="'
             f'Of the {total:,} prices attached to a medicine, {counts.get("active", 0):,} sit on an '
             f'active registration, {counts.get("inactive", 0):,} on an inactive one, '
             f'{counts.get("expired", 0):,} on an expired one, and {counts.get("never read", 0):,} '
             f'cannot be judged because no status was ever read." class="chart">',
             f'{_gap_pattern("gap-licence")}']
    x = 0.0
    for name, colour, _note in LICENCE_STATES:
        width = CHART_W * counts.get(name, 0) / total
        fill = colour if colour else "url(#gap-licence)"
        parts.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{width:.2f}" height="{bar_h}" '
                     f'fill="{fill}" stroke="{CREAM_PAPER}" stroke-width="1.5"/>')
        x += width
    parts.append(f'<rect x="0" y="{bar_y}" width="{CHART_W}" height="{bar_h}" fill="none" '
                 f'stroke="{CREAM_INK}" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def chart_runs(runs: list[dict[str, Any]]) -> str:
    """Runs per night: the whole bar is the runs that started, the navy part the ones that succeeded."""
    top = max((r["runs"] for r in runs), default=1) or 1
    height = 132
    plot = 96
    slot = CHART_W / max(len(runs), 1)
    bar = min(18.0, slot * 0.56)
    base_y = 8 + plot
    parts = [f'<svg viewBox="0 0 {CHART_W} {height}" role="img" aria-label="'
             f'{sum(r["runs"] for r in runs)} pipeline runs over {len(runs)} nights; '
             f'{sum(r["ok"] for r in runs)} succeeded and '
             f'{sum(r["runs"] - r["ok"] for r in runs)} did not." class="chart">',
             f'{_gap_pattern("gap-runs")}']
    for i, run in enumerate(runs):
        cx = slot * i + slot / 2
        total_h = plot * run["runs"] / top
        ok_h = plot * run["ok"] / top
        x = cx - bar / 2
        parts.append(f'<rect x="{x:.1f}" y="{base_y - total_h:.1f}" width="{bar:.1f}" '
                     f'height="{total_h:.1f}" fill="{CREAM_PANEL}" stroke="{CREAM_LINE}" '
                     'stroke-width="1"/>')
        parts.append(f'<rect x="{x:.1f}" y="{base_y - ok_h:.1f}" width="{bar:.1f}" '
                     f'height="{ok_h:.1f}" fill="{DRESS_NAVY}"/>')
        if run["runs"] != run["ok"]:
            miss_h = total_h - ok_h
            parts.append(f'<rect x="{x:.1f}" y="{base_y - total_h:.1f}" width="{bar:.1f}" '
                         f'height="{miss_h:.1f}" fill="url(#gap-runs)"/>')
        parts.append(f'<text x="{cx:.1f}" y="{base_y + 15}" class="cd" text-anchor="middle">'
                     f'{int(run["day"][-2:])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{base_y - total_h - 4:.1f}" class="cn" '
                     f'text-anchor="middle">{run["runs"]}</text>')
    parts.append(f'<line x1="0" y1="{base_y}" x2="{CHART_W}" y2="{base_y}" '
                 f'stroke="{CREAM_LINE}" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---- the page --------------------------------------------------------------------------------------
CSS = """
:root{--bg:""" + CREAM_PAPER + """;--ink:""" + CREAM_INK + """;--muted:""" + CREAM_MUTED + """;
--line:""" + CREAM_LINE + """;--panel:""" + CREAM_PANEL + """;--accent:""" + CREAM_ACCENT + """;
--navy:""" + DRESS_NAVY + """;--red:""" + DRESS_RED + """;--gold:""" + DRESS_GOLD + """;
--tint-navy:""" + TINT_NAVY + """;--tint-red:""" + TINT_RED + """;--tint-gold:""" + TINT_GOLD + """;
--zebra:""" + ZEBRA + """;--hover:""" + HOVER_TINT + """;--white:""" + PAPER_WHITE + """;
--gold-raw:""" + DRESS_GOLD_RAW + """;
--row-h:36px;--head-h:38px;--rows:10;
--pad-x:.75rem;--jump-h:56px;--sb-h:49px;--s1:8px;--s2:16px;--s3:24px;--s4:32px;--s5:48px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
/* The pointer: a capsule, one half her red and one half white, over the page and over every table.
   A dark rim keeps it visible on the cream ground and on a white panel, it is 24x24 with the hotspot
   at the centre, and where a browser refuses the SVG the fallback is a crosshair, which still reads
   as "you are reading a chart". Decoration: it carries no data, it is not in the contrast audit, and
   it changes no layout, no CSV and no print output. Links and buttons keep their own hand. */
html,table,tbody,tr,td,th{cursor:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3Cdefs%3E%3CclipPath id='c'%3E%3Crect x='4' y='8' width='16' height='8' rx='4'/%3E%3C/clipPath%3E%3C/defs%3E%3Cg transform='rotate(-45 12 12)'%3E%3Crect x='4' y='8' width='16' height='8' rx='4' fill='%23ffffff'/%3E%3Crect x='4' y='8' width='8' height='8' fill='%239F2519' clip-path='url(%23c)'/%3E%3Crect x='4' y='8' width='16' height='8' rx='4' fill='none' stroke='%231a1612' stroke-width='1.5'/%3E%3C/g%3E%3C/svg%3E") 12 12, crosshair}
body{margin:0;background:var(--bg);color:var(--ink);
font:1rem/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:76rem;margin:0 auto;padding:1rem var(--pad-x) 3rem}
h1{font-size:1.6rem;margin:.2rem 0 .4rem}
h2{font-size:1.2rem;margin:2rem 0 .3rem}
h3{font-size:1rem;margin:1.4rem 0 .3rem}
.lede{max-width:66ch;color:var(--muted)}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{
outline:3px solid var(--ink);outline-offset:2px}
.skip{position:absolute;left:-9999px}
.skip:focus{left:.5rem;top:.5rem;background:var(--bg);padding:.5rem;z-index:9}
.figs{list-style:none;display:grid;gap:.6rem;margin:1.2rem 0;padding:0;
grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr))}
.figs li{padding:.7rem .8rem;background:var(--panel);border:2px solid var(--line);border-radius:6px;
display:flex;flex-direction:column;gap:.1rem}
.figs .label{font-size:.78rem;font-weight:700;letter-spacing:.03em;text-transform:uppercase;
color:var(--muted)}
.figs .value{font-size:1.7rem;font-weight:800;line-height:1.15;color:var(--navy);
font-variant-numeric:tabular-nums}
.figs .sub{font-size:.82rem;color:var(--muted)}
.card{background:var(--panel);border:2px solid var(--line);border-radius:6px;padding:.8rem;margin:.6rem 0}
.chart{display:block;width:100%;max-width:540px;height:auto}
.chart text{font-family:inherit;fill:var(--ink)}
.chart .cl{font-size:13px}
.chart .cv{font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}
.chart .cd{font-size:12px;fill:""" + CREAM_MUTED + """}
.chart .cn{font-size:11px;fill:""" + CREAM_MUTED + """;font-variant-numeric:tabular-nums}
thead th[aria-sort="descending"] .arrow{display:inline-block;transform:rotate(180deg)}
.legend{list-style:none;margin:.7rem 0 0;padding:0;display:grid;gap:.25rem;
grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));font-size:.92rem}
.legend li{display:flex;align-items:baseline;gap:.5rem}
.swatch{flex:0 0 auto;width:1.1rem;height:.85rem;border:1px solid var(--ink);border-radius:2px;
position:relative;top:.08rem}
.swatch-gap{background-image:repeating-linear-gradient(45deg,var(--ink) 0 2px,transparent 2px 5px)}
.legend .n{font-variant-numeric:tabular-nums;font-weight:700}
.caption{max-width:62ch;color:var(--muted);font-size:.92rem;margin:.6rem 0 0}
.caption strong{color:var(--ink)}
.controls{display:flex;flex-wrap:wrap;gap:.7rem;align-items:flex-end;margin:1rem 0 .6rem;
padding:.8rem;background:var(--panel);border:2px solid var(--line);border-radius:6px}
.field{display:flex;flex-direction:column;gap:.2rem}
.field label{font-size:.82rem;font-weight:700;letter-spacing:.02em;text-transform:uppercase;
color:var(--muted)}
input[type=search],select{font:inherit;padding:.4rem .5rem;border:2px solid var(--line);
border-radius:4px;background:var(--bg);color:var(--ink);min-width:11rem}
button{font:inherit;padding:.45rem .8rem;border:2px solid var(--ink);border-radius:4px;
background:var(--bg);color:var(--ink);cursor:pointer}
button:hover{background:var(--panel)}
.count{margin:.2rem 0 .8rem;font-variant-numeric:tabular-nums}
.count strong{font-size:1.05rem}
.scroll{overflow:auto;border:2px solid var(--line);border-radius:6px;background:var(--bg);
height:calc(var(--rows) * var(--row-h) + var(--head-h))}
.scroll:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:30rem;
table-layout:fixed;font-size:.95rem}
caption{text-align:left;padding:.5rem .6rem;color:var(--muted);background:var(--panel)}
th,td{height:var(--row-h);max-height:var(--row-h);padding:0 .55rem;text-align:left;
vertical-align:middle;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
border-bottom:1px solid var(--line)}
thead th{position:sticky;top:0;z-index:2;height:var(--head-h);background:var(--panel);
color:var(--muted);font-size:.8rem;letter-spacing:.03em;text-transform:uppercase;
box-shadow:0 1px 0 var(--line)}
thead th button{border:0;background:none;padding:0;font:inherit;color:inherit;
text-transform:inherit;letter-spacing:inherit;cursor:pointer;width:100%;text-align:left;
display:flex;align-items:center;gap:.3rem;height:100%}
thead th .arrow{font-size:.85em;visibility:hidden}
thead th[aria-sort] .arrow{visibility:visible}
tbody tr:nth-child(even){background:var(--zebra)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.num a{display:inline}
.tag{display:inline-block;font-size:.8rem;padding:.05rem .4rem;border:1px solid currentColor;
border-radius:3px;white-space:nowrap}
.tag-active{color:var(--navy);background:var(--tint-navy)}
.tag-inactive{color:var(--gold);background:var(--tint-gold)}
.tag-expired{color:var(--red);background:var(--tint-red)}
.tag-gap{color:var(--ink);background:var(--panel);border-style:dashed}
/* The shop's own stock statement. Words, never colour alone: the tag prints "in stock", "out of stock"
   or "state not stated", and the colour only repeats what the word already says. Red is her red, the
   same tag the expired licence uses - it is not a judgement on the price. */
.tag-in{color:var(--ink);background:var(--panel)}
.tag-out{color:var(--red);background:var(--tint-red)}
.tag-un{color:var(--ink);background:var(--panel);border-style:dashed}
.muted{color:var(--muted)}
.empty{padding:1.5rem;text-align:center;color:var(--muted)}
footer{margin-top:2rem;padding-top:1rem;border-top:2px solid var(--line);color:var(--muted);
font-size:.9rem;max-width:70ch}
footer strong{color:var(--ink)}
/* ask the data: the picker, its five tiles, one bar per quote, the block's own table */
.vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip-path:inset(50%);white-space:nowrap;border:0}
.ask{display:grid;gap:.5rem;margin:.8rem 0 0}
.combo{position:relative}
#ask-list{position:absolute;z-index:5;left:0;right:0;top:100%;margin:.2rem 0 0;padding:0;
list-style:none;background:var(--bg);border:2px solid var(--ink);border-radius:4px;
max-height:15rem;overflow:auto;box-shadow:0 6px 14px rgba(26,22,18,.18)}
#ask-list li{padding:.35rem .55rem;cursor:pointer;border-bottom:1px solid var(--line)}
#ask-list li:last-child{border-bottom:0}
#ask-list li[aria-selected="true"]{background:var(--tint-navy);outline:2px solid var(--navy);
outline-offset:-2px;font-weight:700}
.ask-head{margin:1rem 0 .1rem;font-size:1.1rem}
.ask-meta{margin:0 0 .4rem;color:var(--muted);font-size:.92rem;
font-variant-numeric:tabular-nums}
.figs.ask-figs{grid-template-columns:repeat(auto-fit,minmax(10.5rem,1fr));margin-top:.4rem}
.figs.ask-figs .value{font-size:1.2rem}
.figs.ask-figs .sub{font-size:.8rem}
/* One tile instead of five when no shop has the medicine in stock: the sentence needs the whole row,
   because it is the answer and not a caveat on one of five numbers. */
.figs.ask-figs.solo{grid-template-columns:1fr}
.figs.ask-figs.solo .value{font-size:1.05rem;color:var(--ink)}
.bars{list-style:none;margin:.5rem 0 0;padding:0;display:grid;gap:.45rem}
.bars li{display:grid;gap:.15rem .6rem;align-items:center;font-size:.9rem;
grid-template-columns:minmax(6rem,10rem) minmax(0,1fr) auto auto auto auto;
grid-template-areas:"shop track price stock pack tag"}
.bshop{grid-area:shop;overflow-wrap:anywhere}
.btrack{grid-area:track;display:block;height:.9rem;background:var(--panel);
border:1px solid var(--line);border-radius:2px;overflow:hidden}
.bfill{display:block;height:100%;background:var(--ink)}
.bprice{grid-area:price;font-variant-numeric:tabular-nums;font-weight:700;text-align:right;
min-width:5.5rem}
.bpack{grid-area:pack;font-variant-numeric:tabular-nums;white-space:nowrap}
.bstock{grid-area:stock}
.bars .tag{grid-area:tag}
.warn{margin:.6rem 0 0;padding:.5rem .7rem;background:var(--panel);border-left:4px solid var(--ink);
border-radius:0 4px 4px 0;font-size:.92rem;max-width:62ch}
.note{margin:.9rem 0 0;font-size:.88rem;color:var(--muted);max-width:66ch}
.note strong{color:var(--ink)}
/* ---- the jump bar ---------------------------------------------------------------------------
   Sticky under the top of the window, one item per section, generated from the same list as the
   bands so the two cannot disagree. The bar bleeds to the edges of the column; it scrolls sideways
   inside itself on a narrow screen, so the page never gains a horizontal scrollbar because of it.
   The active item is marked three ways - weight, a 3px filled base, and colour - because colour
   alone is not a difference a colour-blind reader can see. */
.jump{margin:var(--s2) calc(-1 * var(--pad-x)) 0;padding:0 var(--pad-x);background:var(--bg);
border-top:2px solid var(--line);border-bottom:2px solid var(--line);
position:sticky;top:0;z-index:6}
.jump ul{list-style:none;margin:0;padding:0;display:flex;overflow-x:auto;overscroll-behavior-x:contain;
scrollbar-width:thin}
.jump li{flex:0 0 auto}
.jump a{display:flex;align-items:center;gap:.45rem;min-height:44px;padding:0 var(--s2);
color:var(--ink);text-decoration:none;font-weight:600;white-space:nowrap}
.jump a .jn{font-size:.78rem;font-weight:700;color:var(--muted);font-variant-numeric:tabular-nums}
.jump a[data-accent="navy"]{--c:var(--navy)}
.jump a[data-accent="red"]{--c:var(--red)}
.jump a[data-accent="gold"]{--c:var(--gold)}
.jump a:hover{background:var(--panel)}
.jump a[aria-current="true"]{color:var(--c);font-weight:800;box-shadow:inset 0 -3px 0 var(--c)}
.jump a[aria-current="true"] .jn{color:var(--c)}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}

/* ---- the site bar: one row of links, on every page but the front one --------------------
   The front page carries its three links inside its own masthead, so this bar is for the two
   inner pages. It is a fixed 49px, and `--sb-h` is that height and nothing else: the dashboard's
   jump bar is told to stick directly under it with no script, because a number that is written
   down cannot drift from the number that was measured. */
.sitebar{--nav-max:76rem;--nav-pad:var(--pad-x);background:var(--bg);border-bottom:1px solid var(--line);
 position:sticky;top:0;z-index:8;height:var(--sb-h)}
.sb-inner{max-width:var(--nav-max);margin:0 auto;padding:0 var(--nav-pad);height:100%;
 display:flex;align-items:center;justify-content:space-between;gap:16px}
.sb-mark{font-family:"Archivo Black",Impact,sans-serif;font-size:11.5px;letter-spacing:.13em;
 text-transform:uppercase;color:var(--ink);text-decoration:none;white-space:nowrap;line-height:1}
.sb-mark:hover{color:var(--red)}
.sb-links{list-style:none;display:flex;align-items:center;margin:0;padding:0;overflow-x:auto;
 overscroll-behavior-x:contain;scrollbar-width:none}
.sb-links::-webkit-scrollbar{display:none}
.sb-links li{margin:0;padding:0;flex:0 0 auto}
.sb-links a{position:relative;display:block;padding:12px 11px;min-height:44px;line-height:20px;
 font-size:13.5px;font-weight:600;color:var(--ink);text-decoration:none;white-space:nowrap}
.sb-links a::after{content:"";position:absolute;left:11px;right:11px;bottom:9px;height:3px;
 background:transparent}
.sb-links a:hover{color:var(--red)}
.sb-links a[aria-current="page"]{font-weight:700}
.sb-links a[aria-current="page"]::after{background:var(--red)}
.sitebar a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
@media (max-width:560px){
 /* The bar stacks on a phone: the wordmark on one row, the links on the next, the links
    scrolling inside themselves rather than wrapping, so the bar's height stays the height the
    jump bar is told to sit under. */
 :root{--sb-h:76px}
 .sb-inner{flex-direction:column;align-items:stretch;justify-content:flex-start;gap:0}
 .sb-mark{height:31px;display:flex;align-items:center}
 .sb-links{height:44px}
}

/* The jump bar sticks directly under the site bar, and a section's scroll margin grows by
   the same amount, so a jumped-to heading still lands below the jump bar and not under it. */
.jump{top:var(--sb-h)}
/* ---- the bands ---------------------------------------------------------------------------------
   The band is what separates one section from the next: a full-width field of colour carrying the
   number, the name and the standfirst, with the section's content sitting on the page ground beneath
   it. Six bands, four measured pairs, alternating so no two neighbours are the same colour. */
.sect{margin:0 0 var(--s5);scroll-margin-top:calc(var(--sb-h) + var(--jump-h) + var(--s1))}
main{scroll-margin-top:calc(var(--sb-h) + var(--jump-h) + var(--s1))}
.sect:first-child{margin-top:var(--s4)}
.band{display:grid;grid-template-columns:auto 1fr;align-items:baseline;
column-gap:var(--s2);row-gap:var(--s1);
margin:0 calc(-1 * var(--pad-x)) var(--s3);padding:var(--s2) var(--pad-x) var(--s3)}
.band .bnum{grid-row:1;grid-column:1;font-size:.85rem;font-weight:800;letter-spacing:.14em;
font-variant-numeric:tabular-nums}
.band h2{grid-row:1;grid-column:2;margin:0;font-size:1.4rem;line-height:1.2}
.band .bstand{grid-row:2;grid-column:2;margin:0;max-width:64ch;font-size:.95rem}
.band-navy{background:var(--navy);color:var(--white)}
.band-red{background:var(--red);color:var(--white)}
.band-gold{background:var(--gold-raw);color:var(--ink)}
.band-paper-navy{background:var(--bg);color:var(--ink);border-top:3px solid var(--navy)}
.band-paper-red{background:var(--bg);color:var(--ink);border-top:3px solid var(--red)}
/* ---- the filters, as chips ---------------------------------------------------------------------
   One chip per active control, each a single button that removes its own filter. The list is drawn
   from the same three values the table filters on, in the same function that redraws the rows, so a
   chip and the count line cannot describe two different filters. */
.chips-row{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s1);margin:0 0 var(--s2)}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:var(--s1);margin:0;padding:0}
.chip{display:inline-flex;align-items:center;gap:.4rem;min-height:32px;padding:.1rem .3rem .1rem .7rem;
border:1px solid var(--navy);border-radius:999px;background:var(--tint-navy);color:var(--ink);
font-size:.88rem;max-width:22rem}
.chip .what{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip .x{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;
border-radius:999px;background:var(--bg);color:var(--ink);font-size:1rem;line-height:1;flex:0 0 auto}
.chip:hover .x{background:var(--panel)}
#clear-all{min-height:32px;padding:.1rem .8rem;border-radius:999px;background:var(--panel)}
.chips-row .label{margin:0;font-size:.82rem;font-weight:700;letter-spacing:.02em;
text-transform:uppercase;color:var(--muted)}
/* Row states. The tint is drawn after the zebra rule above, so a row under the pointer is one colour
   and not a half-and-half; the focus ring on a link inside a row is drawn inwards, because a row
   clips its overflow and an outward ring would be cut off. */
tbody tr:hover{background:var(--hover)}
tbody a:focus-visible,tbody button:focus-visible{outline:2px solid var(--ink);outline-offset:-2px}
td.nm,th.nm{text-overflow:ellipsis}
@media (max-width:640px){:root{--pad-x:.6rem;--jump-h:44px}
input[type=search],select{width:100%}.figs .value{font-size:1.45rem}
table{font-size:.85rem}th,td{padding:0 .35rem}.tag{font-size:.72rem;padding:.02rem .3rem}
.bars li{grid-template-columns:1fr auto;
grid-template-areas:"shop tag" "track track" "price pack" "stock stock"}
.bprice{text-align:left;min-width:0}
.figs.ask-figs{grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr))}
.band h2{font-size:1.2rem}.band{padding:var(--s2) var(--pad-x)}
/* The first column stays put while the table scrolls sideways, so the medicine name is never lost.
   The corner cell - the one that is both the sticky header and the frozen column - takes the highest
   of the three layers, so the two do not fight over it: body 1, headers 2, corner 4. */
#scroll thead th:first-child{left:0;z-index:4;background:var(--panel)}
#scroll tbody th{position:sticky;left:0;z-index:1;background:var(--bg);
box-shadow:6px 0 6px -6px rgba(26,22,18,.5)}
#scroll tbody tr:nth-child(even) th{background:var(--zebra)}
#scroll tbody tr:hover th{background:var(--hover)}}
@media print{
  .controls,.skip,.noprint,.jump,.chips-row{display:none!important}
  .scroll{height:auto!important;max-height:none!important;overflow:visible!important}
  .scroll th,.scroll td{height:auto!important;max-height:none!important;white-space:normal!important}
  thead th{position:static}
  .sect{margin-bottom:1.5rem}
  tbody tr{break-inside:avoid}
  .figs{grid-template-columns:repeat(3,1fr)}
  body{background:#fff}
}
"""

JS = r"""
(function () {
  var DATA = JSON.parse(document.getElementById('rows').textContent);
  var MONEY = {minimumFractionDigits: 2, maximumFractionDigits: 2};
  var DAILY = 2333;  // = MINIMUM_WAGE_DAILY_NGN in the build; 70,000 a month over 30 days

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }
  // Half away from zero on the same double the build rounds, so a tile and the build log cannot
  // disagree in the last digit.
  function halfUp(v, p) { var f = Math.pow(10, p); return Math.floor(v * f + 0.5) / f; }
  function fmt(n) {
    return n === null || n === undefined ? '' :
      '\u20a6' + halfUp(Number(n), 2).toLocaleString('en-NG', MONEY);
  }
  function pct(v) {
    return (v >= 100 ? Math.round(v).toLocaleString('en-NG') : halfUp(v, 1).toFixed(1)) + '%';
  }
  function andList(items) {
    if (items.length < 2) { return items.join(''); }
    return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }
  function packLabel(r) {
    return r.k === null ? '' : String(r.k) + (r.u ? ' ' + r.u : '');
  }
  function licenceCell(r) {
    var body = '<span class="tag tag-' + (r.l === 'never read' ? 'gap' : r.l) + '">' +
      esc(r.l) + '</span>';
    if (r.ru) {
      return '<a href="' + esc(r.ru) + '" rel="nofollow noopener" ' +
        'title="the NAFDAC register record">' + body + '</a>';
    }
    return body;
  }
  // The shop's own stock statement, in words. 1 = it says it has it, 0 = it says it has none, null = it
  // said nothing either way. Null is never read as "available" anywhere on this page.
  function stockWord(r) {
    return r.st === null ? 'state not stated' : (r.st === 1 ? 'in stock' : 'out of stock');
  }
  function stockCell(r) {
    return '<span class="tag tag-' + (r.st === null ? 'un' : (r.st === 1 ? 'in' : 'out')) + '">' +
      stockWord(r) + '</span>';
  }

  // ---- one ten-row window, used by both tables --------------------------------------------------
  function downloadCsv(filename, head, rows, cells) {
    var lines = [head.join(',')];
    rows.forEach(function (r) {
      lines.push(cells(r).map(function (c) {
        var s = c === null || c === undefined ? '' : String(c);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      }).join(','));
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
  }

  // A scroll box holding exactly the rows in view, a sticky header, a count line, Home/End, and a
  // CSV of whatever is in it. One implementation, two tables: the browse-all one and the block's.
  function windowTable(cfg) {
    var shown = cfg.shown || 10;
    function fitRows() {
      var row = cfg.tbody.querySelector('tr');
      var rh = row ? row.getBoundingClientRect().height : 36;
      var hh = cfg.thead.getBoundingClientRect().height || 38;
      var wanted = hh + rh * shown;
      cfg.wrap.style.height = Math.round(wanted) + 'px';
      // Correct for the box's borders and, on a narrow screen, the horizontal scrollbar: one pass is
      // enough because the correction is the only thing the borders change.
      var gap = wanted - cfg.wrap.clientHeight;
      if (Math.abs(gap) > 0.5) { cfg.wrap.style.height = Math.round(wanted + gap) + 'px'; }
    }
    function render(announce) {
      var rows = cfg.rows();
      cfg.tbody.innerHTML = rows.map(cfg.row).join('');
      // Two empty states, and which one shows is a question about the filters rather than about the
      // count: rows can be missing because the filters exclude them, which the reader can undo, or
      // because there is nothing to show at all, which nobody can. Never both, never neither.
      if (cfg.empty || cfg.emptyNone) {
        var none = rows.length === 0;
        var narrowed = !!(cfg.hasFilters && cfg.hasFilters());
        if (cfg.empty) { cfg.empty.hidden = !(none && narrowed); }
        if (cfg.emptyNone) { cfg.emptyNone.hidden = !(none && !narrowed); }
      }
      var visible = Math.min(shown, rows.length);
      cfg.count.innerHTML = '<strong>' + visible + '</strong> of ' + rows.length.toLocaleString() +
        (rows.length > visible ? ' \u2014 scroll, or narrow it' : '');
      fitRows();
      return rows;
    }
    cfg.wrap.addEventListener('keydown', function (e) {
      if (e.key === 'Home') { cfg.wrap.scrollTop = 0; e.preventDefault(); }
      if (e.key === 'End') { cfg.wrap.scrollTop = cfg.wrap.scrollHeight; e.preventDefault(); }
    });
    window.addEventListener('resize', fitRows);
    if (cfg.csv) {
      cfg.csv.addEventListener('click', function () {
        downloadCsv(cfg.filename(), cfg.csvHead, cfg.rows(), cfg.cells);
      });
    }
    render(false);
    return {render: render, setShown: function (n) { shown = n; render(true); }};
  }

  // ---- the browse-all table ---------------------------------------------------------------------
  var Q = document.getElementById('q'), SHOP = document.getElementById('shop'),
      LIC = document.getElementById('lic'), PER = document.getElementById('per');
  var keys = {
    name: function (r) { return (r.t || '').toLowerCase(); },
    shop: function (r) { return (r.s || '').toLowerCase(); },
    price: function (r) { return r.p === null ? Infinity : Number(r.p); },
    pack: function (r) { return (r.k === null ? '' : String(r.k)) + ' ' + (r.u || ''); },
    unit: function (r) { return r.pu === null ? Infinity : Number(r.pu); },
    stock: function (r) { return r.st === null ? -1 : r.st; },
    lic: function (r) { return r.l; }
  };
  var sortBy = 'price', sortUp = true;

  function browseRows() {
    var q = Q.value.trim().toLowerCase(), shop = SHOP.value, lic = LIC.value;
    var rows = DATA.filter(function (r) {
      if (shop && r.s !== shop) return false;
      if (lic && r.l !== lic) return false;
      if (q && (r.t + ' ' + r.m + ' ' + r.s).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    var get = keys[sortBy];
    rows.sort(function (a, b) {
      var x = get(a), y = get(b);
      var cmp = (typeof x === 'string') ? String(x).localeCompare(String(y)) : (x - y);
      if (cmp === 0) { cmp = (a.p === null ? Infinity : Number(a.p)) - (b.p === null ? Infinity : Number(b.p)); }
      return sortUp ? cmp : -cmp;
    });
    return rows;
  }

  // Which of the three controls is doing any narrowing at all. Defined before the table so the two
  // empty states and the chips answer from the same three values the filter itself reads.
  function anyFilter() { return !!(Q.value.trim() || SHOP.value || LIC.value); }

  var browse = windowTable({
    thead: document.getElementById('rows-head'),
    tbody: document.getElementById('rows-body'),
    count: document.getElementById('count'),
    empty: document.getElementById('empty-filters'),
    emptyNone: document.getElementById('empty-none'),
    hasFilters: anyFilter,
    wrap: document.getElementById('scroll'),
    csv: document.getElementById('csv'),
    filename: function () { return 'naijadrugwatch-prices.csv'; },
    csvHead: ['medicine as the shop names it', 'shop', 'price ngn', 'pack', 'stock',
              'price per unit', 'licence', 'shop page', 'register record'],
    cells: function (r) {
      return [r.t, r.s, r.p === null ? '' : r.p, packLabel(r), stockWord(r),
              r.pu === null ? '' : r.pu, r.l, r.a, r.ru];
    },
    rows: browseRows,
    row: function (r) {
      var unit = r.pu === null ? '' : fmt(r.pu) + (r.u ? ' / ' + esc(r.u) : '');
      var pack = packLabel(r);
      var name = r.a
        ? '<a href="' + esc(r.a) + '" rel="nofollow noopener">' + esc(r.t) + '</a>'
        : esc(r.t);
      if (!r.m) { name += ' <span class="tag tag-gap">no match</span>'; }
      return '<tr><th scope="row">' + name + '</th><td>' + esc(r.s) +
        '</td><td class="num">' + fmt(r.p) + '</td><td>' + esc(pack) +
        '</td><td>' + stockCell(r) +
        '</td><td class="num">' + unit + '</td><td>' + licenceCell(r) + '</td></tr>';
    }
  });

  function sortByColumn(name) {
    if (sortBy === name) { sortUp = !sortUp; } else { sortBy = name; sortUp = true; }
    Array.prototype.forEach.call(
      document.getElementById('rows-head').querySelectorAll('th[data-key]'), function (th) {
        if (th.getAttribute('data-key') === sortBy) {
          th.setAttribute('aria-sort', sortUp ? 'ascending' : 'descending');
        } else {
          th.removeAttribute('aria-sort');
        }
      });
    browse.render(true);
  }
  Array.prototype.forEach.call(
    document.getElementById('rows-head').querySelectorAll('th[data-key] button'), function (b) {
      b.addEventListener('click', function () { sortByColumn(b.parentNode.getAttribute('data-key')); });
    });
  [Q, SHOP, LIC].forEach(function (node) {
    node.addEventListener('input', function () { refresh(); });
    node.addEventListener('change', function () { refresh(); });
  });
  PER.addEventListener('change', function () {
    browse.setShown(parseInt(PER.value, 10) || 10);
  });
  document.getElementById('print').addEventListener('click', function () { window.print(); });
  document.getElementById('rows-head').querySelector('th[data-key="price"]')
    .setAttribute('aria-sort', 'ascending');

  // ---- ask the data: the picker ----------------------------------------------------------------
  var A = {
    q: document.getElementById('ask-q'), list: document.getElementById('ask-list'),
    live: document.getElementById('ask-live'), title: document.getElementById('ask-title'),
    meta: document.getElementById('ask-meta'), figs: document.getElementById('ask-figs'),
    bars: document.getElementById('ask-bars'), warn: document.getElementById('ask-warn'),
    nos: document.getElementById('ask-nos'),
    count: document.getElementById('ask-count'), csv: document.getElementById('ask-csv'),
    thead: document.getElementById('ask-head'), tbody: document.getElementById('ask-body'),
    wrap: document.getElementById('ask-scroll')
  };
  var NAMES = [], SEEN = {};
  DATA.forEach(function (r) {
    if (r.m && !SEEN[r.m]) { SEEN[r.m] = 1; NAMES.push(r.m); }
  });
  NAMES.sort();
  var current = A.q.value;
  if (NAMES.indexOf(current) === -1) { current = NAMES[0]; A.q.value = current; }

  function quotesFor(name) {
    return DATA.filter(function (r) { return r.m === name; })
      .sort(function (a, b) {
        var d = Number(a.p) - Number(b.p);
        return d !== 0 ? d : (a.s < b.s ? -1 : (a.s > b.s ? 1 : 0));
      });
  }

  // The five figures, for one medicine only, over the quotes a shop marked IN STOCK. A price beside a
  // medicine the shop says it has none of is not an offer, so it may never be the cheapest: on this
  // vintage that would have shown Amoxicillin at naira 590 when the cheapest shop that has it charges
  // 29,540. Mirrors the build's `ask_figures` branch for branch: no in-stock quote -> 'none'; one shop
  // -> 'single'; every quote one stated pack size -> 'percent'; anything else -> 'packs'.
  function askFigures(name) {
    var q = quotesFor(name);
    var inside = q.filter(function (r) { return r.st === 1; });
    var prices = inside.map(function (r) { return Number(r.p); });
    var n = prices.length;
    var cheapest = n ? prices[0] : null, dearest = n ? prices[n - 1] : null;
    var median = n ? (n % 2 ? prices[(n - 1) / 2] : (prices[n / 2 - 1] + prices[n / 2]) / 2) : null;
    var shops = [], seenShop = {}, packs = {}, missing = false;
    inside.forEach(function (r) {
      if (!seenShop[r.s]) { seenShop[r.s] = 1; shops.push(r.s); }
      var p = packLabel(r);
      if (p) { packs[p] = 1; } else { missing = true; }
    });
    var packCount = Object.keys(packs).length;
    var mode = !n ? 'none'
      : (shops.length < 2 ? 'single' : (packCount === 1 && !missing ? 'percent' : 'packs'));
    function at(price) {
      var found = [];
      inside.forEach(function (r) {
        if (Number(r.p) === price && found.indexOf(r.s) === -1) { found.push(r.s); }
      });
      return found;
    }
    var out = 0, unstated = 0;
    q.forEach(function (r) { if (r.st === 0) { out += 1; } else if (r.st === null) { unstated += 1; } });
    return {q: q, inside: inside, n: n, quoted: q.length, out: out, unstated: unstated,
            cheapest: cheapest, dearest: dearest, median: median, mode: mode,
            packs: Object.keys(packs).sort(), missing: missing, shops: shops, at: at,
            gapPct: cheapest ? (dearest - cheapest) / cheapest * 100 : 0};
  }

  function noStockSub(f) {
    var head = (f.out && f.unstated)
      ? f.out + ' marked out of stock, ' + f.unstated + ' stating no stock'
      : (f.out ? 'all ' + f.out + ' marked out of stock'
               : 'no quote states whether it is in stock');
    return head + ' \u2014 the prices are listed below';
  }

  function askTiles(f) {
    // One tile, not five of dashes: the answer is that nobody has it, and five empty figures would look
    // like a gap in our reading rather than a fact about the shops.
    if (f.mode === 'none') {
      return [['lowest price', 'no shop has this in stock', noStockSub(f)]];
    }
    var which = (f.out + f.unstated) ? 'in-stock ' : '';
    var tiles = [
      ['lowest price', fmt(f.cheapest), 'at ' + andList(f.at(f.cheapest))],
      ['highest price', fmt(f.dearest), 'at ' + andList(f.at(f.dearest))],
      ['middle price', fmt(f.median),
       f.n > 1 ? 'of ' + f.n + ' ' + which + 'prices'
               : 'of the one ' + which + 'price']
    ];
    if (f.mode === 'single') {
      tiles.push(['gap', 'no second shop', 'one shop has it in stock']);
    } else if (f.mode === 'packs') {
      tiles.push(['gap', fmt(f.dearest - f.cheapest), 'packs differ \u2014 not a saving']);
    } else {
      tiles.push(['gap', fmt(f.dearest - f.cheapest),
                  '+' + pct(f.gapPct) + ' on the cheapest, same pack']);
    }
    tiles.push(['days of minimum wage', halfUp(f.cheapest / DAILY, 2).toFixed(2),
                'days of minimum wage to buy this pack']);
    return tiles;
  }

  function askWarn(f) {
    if (f.mode === 'none') { return ''; }
    if (f.mode === 'single') {
      return 'Only one shop has this medicine in stock, and one is nothing to compare with, so the gap ' +
        'tile says \u201cno second shop\u201d rather than printing a zero.';
    }
    if (f.mode !== 'packs') { return ''; }
    var what = f.packs.length > 1
      ? 'the quotes are for ' + f.packs.length + ' different packs (' + f.packs.join(', ') + ')'
      : 'every quote states the same pack size, but ' + 'a pack size is missing from at least one';
    if (f.packs.length === 0) { what = 'none of these quotes states a pack size'; }
    return 'Packs differ: ' + what + '.';
  }

  function noStockLine(f) {
    var what = (f.out && f.unstated)
      ? f.out + ' marked out of stock and ' + f.unstated + ' stating no stock'
      : (f.out ? 'each marked out of stock'
               : 'none of them stating whether it is in stock');
    return 'No shop says it has this medicine in stock. The ' + f.quoted +
      (f.quoted === 1 ? ' price below is what the shop published, ' : ' prices below are what the shops published, ') +
      what + ' \u2014 a price on a shop\u2019s page, not an offer to sell.';
  }

  function askSummary(name, f) {
    if (f.mode === 'none') {
      return name + '. No shop has this medicine in stock, so there is no cheapest and no dearest. ' +
        f.quoted + (f.quoted === 1 ? ' price is' : ' prices are') +
        ' published, none of them an offer to sell.';
    }
    var gap = f.mode === 'single' ? 'no second shop to compare it with'
      : (f.mode === 'packs' ? 'the packs differ, so no percentage is given'
        : '+' + pct(f.gapPct) + ' on the cheapest');
    var stock = f.out || f.unstated
      ? ' ' + f.out + ' out of stock and ' + f.unstated + ' with no state stated are left out.'
      : '';
    return name + '. ' + f.n + (f.n === 1 ? ' in-stock quote' : ' in-stock quotes') + ' from ' +
      f.shops.length + (f.shops.length === 1 ? ' shop' : ' shops') + '. Cheapest ' +
      fmt(f.cheapest) + ' at ' + andList(f.at(f.cheapest)) + '; dearest ' + fmt(f.dearest) +
      ' at ' + andList(f.at(f.dearest)) + '; ' + gap + '.' + stock;
  }

  function announce(msg) { A.live.textContent = msg; }

  function renderAsk(name, quiet) {
    var f = askFigures(name);
    // Shops that published a price for it, which is not the same as shops that have it in stock: a shop
    // with nothing on the shelf still quoted a price, and saying "from 0 shops" would deny its own row.
    var quotedShops = {}, quotedCount = 0;
    f.q.forEach(function (r) { if (!quotedShops[r.s]) { quotedShops[r.s] = 1; quotedCount += 1; } });
    A.title.textContent = name;
    A.meta.textContent = f.quoted + (f.quoted === 1 ? ' quote' : ' quotes') + ' from ' +
      quotedCount + (quotedCount === 1 ? ' shop' : ' shops') + ' \u00b7 ' +
      f.n + ' in stock' +
      (f.out ? ', ' + f.out + ' out of stock' : '') +
      (f.unstated ? ', ' + f.unstated + ' with no state stated' : '') +
      (f.quoted > 1 ? ', lowest first' : '');
    A.figs.className = 'figs ask-figs' + (f.mode === 'none' ? ' solo' : '');
    A.figs.innerHTML = askTiles(f).map(function (t) {
      return '<li><span class="label">' + esc(t[0]) + '</span><span class="value">' + esc(t[1]) +
        '</span><span class="sub">' + esc(t[2]) + '</span></li>';
    }).join('');
    A.nos.hidden = f.mode !== 'none';
    A.nos.textContent = f.mode === 'none' ? noStockLine(f) : '';
    A.bars.innerHTML = f.q.map(function (r) {
      var w = f.dearest ? Number(r.p) / f.dearest * 100 : 0;
      var pack = packLabel(r);
      return '<li><span class="bshop">' + esc(r.s) + '</span>' +
        '<span class="btrack" aria-hidden="true"><span class="bfill" style="width:' +
        Math.max(w, 1.5).toFixed(1) + '%"></span></span>' +
        '<span class="bprice">' + fmt(r.p) + '</span>' +
        '<span class="bstock">' + stockCell(r) + '</span>' +
        '<span class="bpack">' + (pack ? esc(pack) : 'no pack stated') + '</span>' +
        licenceCell(r) + '</li>';
    }).join('');
    var warn = askWarn(f);
    A.warn.hidden = !warn;
    A.warn.textContent = warn;
    askTable.render(true);
    if (!quiet) { announce(askSummary(name, f)); }
  }

  var askTable = windowTable({
    thead: A.thead, tbody: A.tbody, count: A.count, wrap: A.wrap, csv: A.csv, shown: 10,
    rows: function () { return quotesFor(current); },
    filename: function () {
      return 'naijadrugwatch-quotes-' + current.toLowerCase()
        .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) + '.csv';
    },
    csvHead: ['shop', 'price ngn', 'pack', 'stock', 'price per unit', 'licence', 'as at',
              'shop page', 'register record'],
    cells: function (r) {
      return [r.s, r.p === null ? '' : r.p, packLabel(r), stockWord(r), r.pu === null ? '' : r.pu,
              r.l, r.d || '', r.a, r.ru];
    },
    row: function (r) {
      var pack = packLabel(r);
      var unit = r.pu === null ? '' : fmt(r.pu) + (r.u ? ' / ' + esc(r.u) : '');
      return '<tr><td>' + esc(r.s) + '</td><td class="num">' + fmt(r.p) + '</td><td>' +
        (pack ? esc(pack) : '<span class="muted">not stated</span>') +
        '</td><td>' + stockCell(r) +
        '</td><td class="num">' + unit + '</td><td>' + licenceCell(r) +
        '</td><td>' + esc(r.d || '') + '</td></tr>';
    }
  });

  // ---- the combobox ----------------------------------------------------------------------------
  var matches = [], matchIndex = -1;

  function closeList() {
    A.list.hidden = true;
    A.q.setAttribute('aria-expanded', 'false');
    A.q.removeAttribute('aria-activedescendant');
    matchIndex = -1;
  }

  function openList(text) {
    var q = text.trim().toLowerCase();
    matches = q ? NAMES.filter(function (n) { return n.toLowerCase().indexOf(q) !== -1; })
                : NAMES.slice();
    A.list.innerHTML = matches.map(function (n, i) {
      return '<li role="option" id="ask-opt-' + i + '" aria-selected="false" data-name="' +
        esc(n) + '">' + esc(n) + '</li>';
    }).join('');
    A.list.hidden = false;
    A.q.setAttribute('aria-expanded', 'true');
    matchIndex = -1;
    A.q.removeAttribute('aria-activedescendant');
    announce(matches.length === 0
      ? 'No medicine matches \u201c' + text.trim() + '\u201d. ' + NAMES.length + ' names are offered.'
      : matches.length + (matches.length === 1 ? ' medicine matches' : ' medicines match') +
        (q ? ' \u201c' + text.trim() + '\u201d' : '') + '. Arrow keys to move, Enter to pick.');
  }

  function highlight(i) {
    var opts = A.list.children;
    if (!opts.length) { return; }
    matchIndex = (i + opts.length) % opts.length;
    Array.prototype.forEach.call(opts, function (o, k) {
      o.setAttribute('aria-selected', k === matchIndex ? 'true' : 'false');
    });
    A.q.setAttribute('aria-activedescendant', opts[matchIndex].id);
    if (opts[matchIndex].scrollIntoView) {
      opts[matchIndex].scrollIntoView({block: 'nearest'});
    }
  }

  function choose(name) {
    if (NAMES.indexOf(name) === -1) { return; }
    current = name;
    A.q.value = name;
    closeList();
    renderAsk(name, false);
  }

  A.q.addEventListener('input', function () { openList(A.q.value); });
  A.q.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (A.list.hidden) { openList(A.q.value); } else { highlight(matchIndex + 1); }
    } else if (e.key === 'ArrowUp') {
      if (!A.list.hidden) { e.preventDefault(); highlight(matchIndex - 1); }
    } else if (e.key === 'Enter') {
      if (A.list.hidden || !matches.length) { return; }
      e.preventDefault();
      choose(matches[matchIndex >= 0 ? matchIndex : 0]);
    } else if (e.key === 'Escape') {
      if (!A.list.hidden) {
        e.preventDefault();
        closeList();
        A.q.value = current;
        announce('Closed. Still showing ' + current + '.');
      }
    } else if (e.key === 'Tab') {
      closeList();
    }
  });
  A.list.addEventListener('mousedown', function (e) {
    var li = e.target.closest ? e.target.closest('li[role="option"]') : null;
    if (li) { e.preventDefault(); choose(li.getAttribute('data-name')); }
  });
  A.q.addEventListener('blur', function () { setTimeout(closeList, 150); });

  // ---- the filters, drawn as chips ---------------------------------------------------------------
  // One chip per active control, each a single button that removes its own filter. The chips are
  // derived from the same three values the table filters on, in `refresh()` alongside the row render,
  // so a chip and the count line cannot describe two different sets of filters.
  function filterChips() {
    var out = [], q = Q.value.trim();
    if (q) { out.push({what: 'search \u201c' + q + '\u201d',
                       undo: function () { Q.value = ''; Q.focus(); }}); }
    if (SHOP.value) { out.push({what: 'shop: ' + SHOP.value,
                                undo: function () { SHOP.value = ''; SHOP.focus(); }}); }
    if (LIC.value) { out.push({what: 'licence: ' + LIC.value,
                               undo: function () { LIC.value = ''; LIC.focus(); }}); }
    return out;
  }
  var CHIPS = document.getElementById('chips'), CHIPROW = document.getElementById('chips-row'),
      CLEARALL = document.getElementById('clear-all');
  function drawChips() {
    var chips = filterChips();
    CHIPS.innerHTML = chips.map(function (c, i) {
      return '<li><button type="button" class="chip" data-i="' + i +
        '" aria-label="Remove the filter: ' + esc(c.what) + '"><span class="what">' + esc(c.what) +
        '</span><span class="x" aria-hidden="true">\u00d7</span></button></li>';
    }).join('');
    CHIPROW.hidden = chips.length === 0;
    CLEARALL.hidden = chips.length < 2;
  }
  function clearAll() { Q.value = ''; SHOP.value = ''; LIC.value = ''; Q.focus(); }
  function refresh() { drawChips(); browse.render(true); }
  CHIPS.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('button.chip') : null;
    if (!b) { return; }
    var picked = filterChips()[Number(b.getAttribute('data-i'))];
    if (!picked) { return; }
    picked.undo();
    refresh();
  });
  CLEARALL.addEventListener('click', function () { clearAll(); refresh(); });
  document.getElementById('empty-clear').addEventListener('click', function () { clearAll(); refresh(); });

  // ---- the row height ----------------------------------------------------------------------------
  // Three densities, the middle one the height this page has always used. The window is ten rows in
  // all three: the table measures its own first row after the change and sizes its box to hold ten of
  // them, so the number of rows on screen is a property of the mode and not of the browser's zoom.
  var DENS = {compact: 32, comfortable: 36, spacious: 44};
  var DENSITY = document.getElementById('density');
  DENSITY.addEventListener('change', function () {
    var px = DENS[DENSITY.value] || 36;
    document.getElementById('scroll').style.setProperty('--row-h', px + 'px');
    browse.render(true);
  });

  // ---- the jump bar ------------------------------------------------------------------------------
  // The bar sticks to the window; the table's header sticks inside its own scroll box, so the two
  // never meet. `--jump-h` is measured rather than guessed, and `scroll-margin-top` on `.sect` reads
  // it, so a section heading lands below the bar on a wide screen and on a narrow one.
  var BAR = document.getElementById('jump');
  var JLINKS = Array.prototype.slice.call(BAR.querySelectorAll('a'));
  var JREFS = JLINKS.map(function (a) { return document.querySelector(a.getAttribute('href')); });
  function measureBar() {
    document.documentElement.style.setProperty('--jump-h', BAR.offsetHeight + 'px');
  }
  function markSection() {
    // The edge is the line a jumped-to heading lands on, not the bar's own bottom. A section carries
    // `scroll-margin-top` equal to the bar's height, so after a jump the target's top sits BELOW the
    // bar; comparing against the bar's bottom alone therefore marked the previous section as current
    // on every jump. Adding the section's own measured scroll margin fixes that without a magic number.
    var margin = 0;
    JREFS.forEach(function (s) {
      if (s && !margin) {
        var m = parseFloat(window.getComputedStyle(s).scrollMarginTop);
        if (m > 0) { margin = m; }
      }
    });
    var edge = BAR.getBoundingClientRect().bottom + margin + 4, here = 0;
    JREFS.forEach(function (s, i) {
      if (s && s.getBoundingClientRect().top <= edge) { here = i; }
    });
    JLINKS.forEach(function (a, i) {
      if (i === here) { a.setAttribute('aria-current', 'true'); }
      else { a.removeAttribute('aria-current'); }
    });
  }
  var scrolling = false;
  var lockUntil = 0;
  // A click names the section the reader is going to, so the bar should say so at once rather than
  // wait for the smooth scroll to arrive. Without this, a short jump to a section that is already
  // on screen leaves the bar pointing at the section before it. The lock is short: the scroll
  // listener takes over again as soon as the movement stops.
  JLINKS.forEach(function (a, i) {
    a.addEventListener('click', function () {
      lockUntil = Date.now() + 900;
      JLINKS.forEach(function (b, j) {
        if (j === i) { b.setAttribute('aria-current', 'true'); }
        else { b.removeAttribute('aria-current'); }
      });
    });
  });
  window.addEventListener('scroll', function () {
    if (scrolling) { return; }
    scrolling = true;
    window.requestAnimationFrame(function () {
      scrolling = false;
      if (Date.now() > lockUntil) { markSection(); }
    });
  }, {passive: true});
  window.addEventListener('resize', function () { measureBar(); markSection(); });
  measureBar();
  markSection();
  drawChips();

  renderAsk(current, true);
})();
"""


def audit_palette() -> list[str]:
    """The eleven colours are copied from `build_site.py`; read them back and refuse a drift."""
    wanted = {
        "CREAM_INK": CREAM_INK, "CREAM_MUTED": CREAM_MUTED, "CREAM_LINE": CREAM_LINE,
        "CREAM_PAPER": CREAM_PAPER, "CREAM_PANEL": CREAM_PANEL, "CREAM_ACCENT": CREAM_ACCENT,
        "DRESS_NAVY": DRESS_NAVY, "DRESS_RED": DRESS_RED, "DRESS_GOLD": DRESS_GOLD,
    }
    if not BUILD_SITE.exists():
        return ["build_site.py is missing, so the palette cannot be checked against it"]
    text = BUILD_SITE.read_text(encoding="utf-8")
    problems = []
    for name, value in wanted.items():
        found = re.search(rf'^{name}\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if not found:
            problems.append(f"{name} is not in build_site.py any more")
        elif found.group(1).lower() != value.lower():
            problems.append(f"{name} is {found.group(1)} in build_site.py and {value} here")
    return problems


def _luminance(colour: str) -> float:
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(front: str, back: str) -> float:
    a, b = _luminance(front), _luminance(back)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def measure_contrast() -> tuple[float, str, list[str]]:
    """Every pair, measured. Returns the worst ratio, the pair it belongs to, and anything under the floor."""
    worst, worst_label = 99.0, ""
    problems: list[str] = []
    for label, front, back in CONTRAST_PAIRS:
        ratio = contrast_ratio(front, back)
        if ratio < worst:
            worst, worst_label = ratio, label
        print(f"  contrast  {label:<50s} {ratio:5.2f}:1  ({front} on {back})")
        if ratio < CONTRAST_FLOOR:
            problems.append(f"{label}: {ratio:.2f}:1, below {CONTRAST_FLOOR}:1")
    for label, front, back, floor, note in DECORATIVE_PAIRS:
        ratio = contrast_ratio(front, back)
        print(f"  not text  {label:<50s} {ratio:5.2f}:1  ({front} on {back}) - {note}"
              + (f", floor {floor:.1f}:1" if floor else ""))
        if floor and ratio < floor:
            problems.append(f"{label}: {ratio:.2f}:1, below its {floor:.1f}:1 boundary floor")
    return worst, worst_label, problems


def _legend(counts: dict[str, int], total: int) -> str:
    items = []
    for name, colour, note in LICENCE_STATES:
        n = counts.get(name, 0)
        swatch = ('<span class="swatch swatch-gap" aria-hidden="true"></span>' if not colour
                  else f'<span class="swatch" style="background:{colour}" aria-hidden="true"></span>')
        share = 100.0 * n / total if total else 0.0
        items.append(f'<li>{swatch}<span><span class="n">{n:,}</span> {esc(name)} '
                     f'({share:.0f}%) &mdash; {esc(note)}</span></li>')
    return '<ul class="legend">' + "".join(items) + "</ul>"


def page(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    shops = sorted({r["s"] for r in rows})
    still = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    options = "\n".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in shops)
    figs = meta["figures"]
    counts = meta["licence_counts"]
    medicines = meta["medicines"]
    default = meta["default"]
    matched = sum(counts.values())
    unmatched = len(rows) - matched
    # The frame the five figures are computed inside, said in one line under the tiles and counted here
    # so the sentence cannot drift from the filter that does the work.
    stock_in = sum(1 for r in rows if r["st"] == STOCK_IN)
    stock_out = sum(1 for r in rows if r["st"] == STOCK_OUT)
    stock_unstated = len(rows) - stock_in - stock_out
    frame = ""
    meta["frame"] = frame
    fig_html = "\n".join(
        f'<li><span class="label">{esc(f["label"])}</span>'
        f'<span class="value">{esc(f["value"])}</span>'
        f'<span class="sub">{esc(f["sub"])}</span></li>'
        for f in figs
    )
    funnel = chart_funnel([
        ("prices collected", len(rows)),
        ("matched to a medicine", matched),
        ("with a readable licence status",
         counts.get("active", 0) + counts.get("inactive", 0) + counts.get("expired", 0)),
        ("comparable across two shops", meta["counts"]["comparisons"]),
    ])
    licence = chart_licence(counts)
    runs = chart_runs(meta["counts"]["runs"])
    run_total = sum(r["runs"] for r in meta["counts"]["runs"])
    run_ok = sum(r["ok"] for r in meta["counts"]["runs"])
    nights = len(meta["counts"]["runs"])
    rough_days = [int(r["day"][-2:]) for r in meta["counts"]["runs"] if r["runs"] != r["ok"]]
    clean = nights - len(rough_days)
    rough = ""
    if rough_days:
        rough = ("; the other " + (f"{len(rough_days)} " if len(rough_days) > 1 else "one ") +
                 "did not (" + ", ".join(f"{d} Nov" for d in rough_days) + ")")
    first_day = datetime.strptime(meta["counts"]["runs"][0]["day"], "%Y-%m-%d")
    last_day = datetime.strptime(meta["counts"]["runs"][-1]["day"], "%Y-%m-%d")

    # The jump bar and the six bands, from the one list. `bands` is keyed by section id so the template
    # below reads in page order, and the bar is built in the same order from the same rows: the two
    # cannot come apart, which is the failure a hand-written bar always has eventually.
    def band_of(s: dict[str, str]) -> str:
        return ('<div class="band band-%s">'
                '<span class="bnum" aria-hidden="true">%s</span>'
                '<h2>%s</h2>'
                '<p class="bstand">%s</p></div>'
                % (s["theme"], s["n"], esc(s["name"]), esc(s["stand"])))

    bands = {s["id"]: band_of(s) for s in SECTIONS}
    bar_items = "\n".join(
        '<li><a href="#%s" data-accent="%s"><span class="jn" aria-hidden="true">%s</span>%s</a></li>'
        % (s["id"], s["accent"], s["n"], esc(s["name"]))
        for s in SECTIONS)
    density_options = "\n".join(
        '<option value="%s"%s>%s &mdash; %d px</option>'
        % (value, " selected" if value == "comfortable" else "", esc(label), px)
        for value, label, px in DENSITIES)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Every price, and what the data can say - NaijaDrugWatch</title>
<link rel="icon" href="data:,">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the prices</a>
<nav class="sitebar" aria-label="Site">
  <div class="sb-inner">
    <a class="sb-mark" href="index.html" aria-label="NaijaDrugWatch, home page">NaijaDrugWatch</a>
    <ul class="sb-links">
      <li><a href="index.html">The finding</a></li>
      <li><a href="dashboard.html" aria-current="page">Every price</a></li>
      <li><a href="about.html">How this was made</a></li>
    </ul>
  </div>
</nav>
<div class="wrap">
<header>
<h1>Every price, and what the data can say</h1>
<p class="lede">All {len(rows):,} prices, collected up to {datetime.strptime(FREEZE["frozen_on"], "%Y-%m-%d").strftime("%d %B %Y")}. Nothing here is live.</p>
<p class="muted">Newest price {datetime.strptime(meta["newest"], "%Y-%m-%d").strftime("%d %B %Y")}. Built {still}, reads nothing from a server.</p>
</header>

<nav class="jump" id="jump" aria-label="Sections of this page">
<ul>
{bar_items}
</ul>
</nav>

<main id="main">
<section class="sect" id="s-data">
{bands["s-data"]}
<ul class="figs">
{fig_html}
</ul>
</section>

<section class="sect" id="s-survive">
{bands["s-survive"]}
<h3>From a price to a comparison</h3>
<div class="card">
{funnel}
</div>
</section>

<section class="sect" id="s-licence">
{bands["s-licence"]}
<h3>The licence behind the {matched:,} prices that have a medicine</h3>
<div class="card">
{licence}
{_legend(counts, matched)}
</div>
</section>

<section class="sect" id="s-nights">
{bands["s-nights"]}
<div class="card">
{runs}
<p class="caption" style="margin-bottom:.2rem">Navy: finished. Hatched: did not.
{first_day.day}&ndash;{last_day.day} {last_day.strftime("%B %Y")}.</p>
</div>
<p class="caption"><strong>{run_total} runs, {run_ok} finished.</strong>{rough}</p>
</section>

<section class="sect" id="ask">
{bands["ask"]}
<div class="controls">
  <div class="field" style="flex:1 1 20rem">
    <label for="ask-q">Type Medicine</label>
    <div class="combo">
      <input type="text" id="ask-q" value="{esc(default['name'])}" role="combobox"
             aria-expanded="false" aria-controls="ask-list" aria-autocomplete="list"
             autocomplete="off" spellcheck="false">
      <ul id="ask-list" role="listbox" aria-label="Medicines that match what you typed" hidden></ul>
    </div>
    <p class="vh" id="ask-live" aria-live="polite"></p>
  </div>
</div>
<p class="caption" id="ask-caption">Type part of a name, arrows to move, Enter to pick.</p>

<h3 class="ask-head" id="ask-title">{esc(default['name'])}</h3>
<p class="ask-meta" id="ask-meta"></p>
<ul class="figs ask-figs" id="ask-figs"
    aria-label="Figures for the selected medicine, from the prices a shop marked in stock"></ul>
{frame}
<p class="warn" id="ask-nos" hidden></p>
<h3>What each shop charges</h3>
<p class="caption">Out-of-stock prices are shown, never counted.</p>
<ul class="bars" id="ask-bars"></ul>
<p class="warn" id="ask-warn" hidden></p>

<h3>The quotes themselves</h3>
<p class="count" id="ask-count" role="status" aria-live="polite"></p>
<div class="scroll" id="ask-scroll" role="region"
     aria-label="Every quote for the selected medicine" tabindex="0">
<table>
<colgroup>
<col style="width:16%"><col style="width:13%"><col style="width:12%">
<col style="width:15%"><col style="width:13%"><col style="width:16%">
<col style="width:15%">
</colgroup>
<thead id="ask-head"><tr>
<th scope="col">Shop</th>
<th scope="col" class="num">Price</th>
<th scope="col">Pack</th>
<th scope="col">Stock</th>
<th scope="col" class="num">Price per unit</th>
<th scope="col">Licence</th>
<th scope="col">As at</th>
</tr></thead>
<tbody id="ask-body"></tbody>
</table>
</div>
<p class="noprint" style="margin:.6rem 0 0"><button type="button" id="ask-csv">Export these quotes as
CSV</button></p>

<p class="note"><strong>Days of minimum wage</strong>: {MINIMUM_WAGE_MONTHLY_NGN:,} a month divided by
{MINIMUM_WAGE_DAYS_PER_MONTH} is {MINIMUM_WAGE_DAILY_NGN:,} a day. Lagos pays
{LAGOS_MINIMUM_WAGE_MONTHLY_NGN:,}; the national rate is used so one price is not compared
against one city&rsquo;s wage.</p>

</section>

<section class="sect" id="browse">
{bands["browse"]}
<p class="lede">{unmatched:,} never matched a medicine.</p>

<div class="controls">
  <div class="field">
    <label for="q">Search a medicine or a shop</label>
    <input type="search" id="q" placeholder="e.g. amoxicillin, or MedPlus" autocomplete="off">
  </div>
  <div class="field">
    <label for="shop">Shop</label>
    <select id="shop"><option value="">All shops</option>
{options}
    </select>
  </div>
  <div class="field">
    <label for="lic">Licence</label>
    <select id="lic">
      <option value="">Any</option>
      <option value="active">Active</option>
      <option value="inactive">Inactive</option>
      <option value="expired">Expired</option>
      <option value="never read">Never read</option>
    </select>
  </div>
  <div class="field">
    <label for="density">Row height</label>
    <select id="density">
{density_options}
    </select>
  </div>
  <div class="field">
    <label for="per">Rows in view</label>
    <select id="per">
      <option value="10" selected>10</option>
      <option value="25">25</option>
      <option value="50">50</option>
    </select>
  </div>
  <div class="field">
    <label for="csv">Take it away</label>
    <span><button type="button" id="csv">Export CSV</button>
    <button type="button" id="print">Print all rows</button></span>
  </div>
</div>

<div class="chips-row" id="chips-row" hidden>
  <p class="label" id="chips-label">Filtered by</p>
  <ul class="chips" id="chips" aria-labelledby="chips-label"></ul>
  <button type="button" id="clear-all" hidden>Clear all</button>
</div>

<p class="count" id="count" role="status" aria-live="polite"></p>

<h3 id="rows-heading">All prices</h3>

<div class="scroll" id="scroll" role="region" aria-labelledby="rows-heading" tabindex="0">
<table>
<colgroup>
<col style="width:22%"><col style="width:12%"><col style="width:13%">
<col style="width:13%"><col style="width:14%"><col style="width:12%">
<col style="width:14%">
</colgroup>
<thead id="rows-head"><tr>
<th scope="col" data-key="name"><button type="button">Medicine as the shop names it
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="shop"><button type="button">Shop
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="price" class="num"><button type="button">Price
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="pack"><button type="button">Pack
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="stock"><button type="button">Stock
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="unit" class="num"><button type="button">Price per unit
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
<th scope="col" data-key="lic"><button type="button">Licence
<span class="arrow" aria-hidden="true">&#9650;</span></button></th>
</tr></thead>
<tbody id="rows-body"></tbody>
</table>
</div>
<p id="empty-filters" class="empty" hidden>No price matches those filters &mdash; clear them and the
table shows every row again. <button type="button" id="empty-clear">Clear them</button></p>
<p id="empty-none" class="empty" hidden>There is nothing to show yet: this page holds no price at
all.</p>
</section>
</main>

<footer>
<p>Code MIT, data CC-BY-4.0. {meta["flag_note"]} Source and method:
<a href="{REPO_URL}">{esc(REPO_URL.replace('https://', ''))}</a>.</p>
</footer>
</div>
<script id="rows" type="application/json">{json.dumps(rows, ensure_ascii=False)}</script>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    url = ensure_database_url()
    if not url:
        print("no DATABASE_URL: set it or put it in .env", file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError as exc:
        print(f"psycopg is not importable: {exc}", file=sys.stderr)
        return 2

    conn = psycopg.connect(url, autocommit=True, connect_timeout=20,
                           options="-c default_transaction_read_only=on")
    with conn:
        rows = fetch(conn)
        recheck = fetch(conn)  # second read: nothing is written unless the two agree
        counts = fetch_counts(conn)
        counts_again = fetch_counts(conn)
        figs = figures(rows, counts)
        figs_again = figures(recheck, counts_again)

    problems: list[str] = []

    # 1. The rows are stable between two reads.
    if len(rows) != len(recheck):
        problems.append(f"row count moved between two reads: {len(rows)} then {len(recheck)}")
    elif json.dumps(rows, sort_keys=True) != json.dumps(recheck, sort_keys=True):
        problems.append("the rows themselves changed between two reads")

    # 2. Every figure is derivable, and derived the same way twice.
    for fig, again in zip(figs, figs_again):
        if not fig["value"] or fig["value"] in ("0", "0.0%"):
            problems.append(f"the figure '{fig['label']}' came back empty or zero")
        if fig["value"] != again["value"]:
            problems.append(f"the figure '{fig['label']}' moved between two reads")

    # 2b. The like-for-like count is a claim about the comparisons, so it cannot exceed them and cannot
    # be zero: zero would mean no comparison on the page prices the same pack, and the sub-line would be
    # advertising a comparison the page then admits is not one.
    if counts["like_for_like"] != counts_again["like_for_like"]:
        problems.append("the like-for-like count moved between two reads")
    if counts["like_for_like"] > counts["comparisons"]:
        problems.append(f"like-for-like {counts['like_for_like']} exceeds comparisons {counts['comparisons']}")
    if counts["like_for_like"] <= 0:
        problems.append("no comparison prices the same pack")

    # 3. The four licence states account for every matched price, and the lapsed ones agree with the view.
    by_state: dict[str, int] = {}
    for row in rows:
        if not row["m"]:
            continue  # a price with no medicine was never looked up, so it has no state to count
        by_state[row["l"]] = by_state.get(row["l"], 0) + 1
    if set(by_state) - {name for name, _c, _n in LICENCE_STATES}:
        problems.append(f"unexpected licence state: {sorted(set(by_state) - {n for n, _c, _x in LICENCE_STATES})}")
    matched = sum(by_state.values())
    if sum(1 for r in rows if r["m"]) != matched:
        problems.append("the licence states do not add up to the prices that carry a medicine")
    lapsed = by_state.get("inactive", 0) + by_state.get("expired", 0)
    if lapsed != counts["flagged"]:
        problems.append(f"inactive + expired is {lapsed}, v_suspicious_listings says {counts['flagged']}")

    # 4. The colour pairs, and the palette the page borrowed.
    worst, worst_label, contrast_problems = measure_contrast()
    problems.extend(contrast_problems)
    problems.extend(audit_palette())

    # 5. The picker: every medicine the shops priced gets five figures, and every branch the block can
    #    print is reachable in this data. A branch nothing reaches is a rule nobody has tested - the
    #    percentage is allowed only on one stated pack size, so a page that could never show it would be
    #    shipping an untested rule.
    medicines = ask_medicines(rows)
    quotes_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["m"]:
            quotes_by_name.setdefault(row["m"], []).append(row)
    if sum(len(v) for v in quotes_by_name.values()) != sum(1 for r in rows if r["m"]):
        problems.append("the quotes per medicine do not add up to the prices that carry a medicine")
    default_name, default_shops, default_quotes = ask_default(rows)
    default_tiles = ask_tiles(quotes_by_name[default_name])
    by_mode: dict[str, list[str]] = {}
    for name in medicines:
        on_this_one = quotes_by_name[name]
        f = ask_figures(on_this_one)
        # The three stock buckets have to account for every quote of this medicine, so a quote cannot
        # fall out of the figures without one of the counts saying so.
        if f["n"] + f["out"] + f["unstated"] != len(on_this_one):
            problems.append(f"{name}: the stock counts read {f['n']} + {f['out']} + {f['unstated']} "
                            f"of {len(on_this_one)} quotes")
        by_mode.setdefault(f["gap_mode"], []).append(name)
    for mode, why in (("percent", "no medicine has two shops quoting one stated pack size"),
                      ("packs", "no medicine has two shops quoting different packs"),
                      ("single", "every medicine has two shops or more")):
        if not by_mode.get(mode):
            problems.append(f"the picker's '{mode}' path cannot be reached: {why}")
    if default_shops < 2:
        problems.append("the default medicine has one shop, so the block would open on 'no second shop'")

    # 5b. Stock. Every price carries the shop's own statement, and the figures are computed over the
    #     in-stock ones only. Three counts, because the page now has three cases to answer for.
    stock_in = sum(1 for r in rows if r["st"] == STOCK_IN)
    stock_out = sum(1 for r in rows if r["st"] == STOCK_OUT)
    stock_unstated = sum(1 for r in rows if r["st"] == STOCK_UNSTATED)
    if stock_in + stock_out + stock_unstated != len(rows):
        problems.append("the stock states do not add up to the prices on the page")
    has_stock: list[str] = []
    out_only: list[str] = []
    null_only: list[str] = []
    cheapest_moved: list[tuple[str, float, float]] = []
    for name in medicines:
        quotes = quotes_by_name[name]
        inside = ask_in_stock(quotes)
        if not inside:
            if any(q["st"] == STOCK_OUT for q in quotes):
                out_only.append(name)
            else:
                null_only.append(name)
            continue
        has_stock.append(name)
        loosest = min(float(q["p"]) for q in quotes)
        honest = min(float(q["p"]) for q in inside)
        if loosest != honest:
            cheapest_moved.append((name, loosest, honest))
    # The three cases have to account for every name, or one of them is silently absorbing the others.
    if len(has_stock) + len(out_only) + len(null_only) != len(medicines):
        problems.append(f"the stock cases cover {len(has_stock) + len(out_only) + len(null_only)} "
                        f"medicines of {len(medicines)}")
    # The same 288 names counted the other way round: how many carry no out-of-stock quote at all. This
    # is the 168 in the ticket, and it is not the same question as "has an in-stock quote" - 59 names
    # carry both an in-stock quote and an out-of-stock one, so they are untouched by the fix and usable.
    untouched = sum(1 for q in quotes_by_name.values() if not any(r["st"] == STOCK_OUT for r in q))
    # The guard: the block must not open on an empty answer. A default medicine with no in-stock quote
    # would make the page's first sentence "no shop has this in stock", which is true and useless.
    if not ask_in_stock(quotes_by_name[default_name]):
        problems.append(f"the default medicine {default_name!r} has no in-stock quote, so the block "
                        "opens on 'no shop has this in stock'")
    # The branch that says "no shop has this in stock" is only tested if some medicine reaches it.
    if not out_only:
        problems.append("no medicine is out of stock only, so the 'no shop has this in stock' path "
                        "cannot be reached and nothing has exercised it")
    else:
        example = out_only[0]
        tile = ask_tiles(quotes_by_name[example])[0]
        if tile[1] != "no shop has this in stock":
            problems.append(f"{example} is out of stock only but its tile says {tile[1]!r}")

    # 5c. The page's own arithmetic, recomputed from the JSON it embeds, for every medicine. This is a
    #     second implementation written from the JavaScript, not a call into it: it reads the payload as
    #     the browser receives it and formats money with Decimal. If the two ever drift, this build fails
    #     rather than printing a figure the page does not show.
    payload = json.dumps(rows, ensure_ascii=False)
    for name in medicines:
        here = ask_tiles(quotes_by_name[name])
        there = browser_tiles(payload, name)
        if here != there:
            problems.append(f"{name}: the build's tiles and the page's differ\n"
                            f"      build: {here}\n      page:  {there}")

    print(f"\n  ask the data: {len(medicines)} medicines; opening on {default_name!r} "
          f"({default_shops} shops, {default_quotes} quotes) - the most shops of any medicine")
    print(f"  stock: {stock_in:,} prices a shop marked in stock, {stock_out:,} marked out of stock, "
          f"{stock_unstated:,} stating no stock either way")
    print(f"  medicines: {len(medicines)} names; {len(has_stock)} with at least one in-stock quote; "
          f"{len(out_only)} out of stock only; {len(null_only)} with no stock state stated")
    print(f"    counted the other way: {untouched} of the {len(medicines)} carry no out-of-stock quote "
          f"at all; {len(medicines) - untouched} carry one, and {len(out_only)} of those have nothing "
          f"in stock")
    print(f"  cheapest changes once out-of-stock prices are excluded: {len(cheapest_moved)} name(s)")
    for name, loosest, honest in cheapest_moved:
        print(f"    {name[:38]:<38s} every quote {_ngn(loosest):>12s}  "
              f"in stock only {_ngn(honest):>12s}")
    if out_only:
        print(f"  out of stock only, e.g. {out_only[0]!r} -> tile reads "
              f"{ask_tiles(quotes_by_name[out_only[0]])[0][1]!r}")
    for name in null_only:
        print(f"  no stock state at all: {name!r} -> tile reads "
              f"{ask_tiles(quotes_by_name[name])[0][1]!r} ({ask_tiles(quotes_by_name[name])[0][2]})")
    print(f"  the five figures for {default_name}, computed here rather than left to the browser:")
    for label, value, sub in default_tiles:
        print(f"    {label:<22s} {value:>12s}  {sub}")
    print(f"  gap paths: {len(by_mode.get('percent', []))} medicine(s) show a percentage, "
          f"{len(by_mode.get('packs', []))} say 'packs differ', "
          f"{len(by_mode.get('single', []))} say 'no second shop'")
    for mode in ("percent", "packs", "single"):
        if by_mode.get(mode):
            example = by_mode[mode][0]
            gap_tile = ask_tiles(quotes_by_name[example])[3]
            print(f"    {mode:<8s} {example} -> {gap_tile[1]} ({gap_tile[2]})")
    print("  every medicine the picker offers, five figures each:")
    for name in medicines:
        print("    " + ask_line(name, quotes_by_name[name]))

    # 6. The charts, the figures and the block are on the page, not only in this dictionary.
    meta = {
        "newest": counts["newest"],
        "medicines": medicines,
        "default": {"name": default_name, "shops": default_shops, "quotes": default_quotes},
        "with_record": sum(1 for r in rows if r["g"]),
        "counts": counts,
        "figures": figs,
        "licence_counts": by_state,
        "flag_note": f"{counts['flagged']} rows carry a registration that is not Active.",
    }
    document = page(rows, meta)

    # 7. The block's own text is in the document: the default's name, the affordability sentence, and
    #    the three words the gap may say instead of a number. A tile that quietly lost its caveat would
    #    still render, which is exactly why it is checked here rather than trusted.
    page_needs = (esc(default_name), "days of minimum wage to buy this pack", "packs differ",
                  "no second shop", "Lagos pays", 'role="combobox"',
                  'role="listbox"', meta["frame"], "no shop has this in stock", "state not stated",
                  "marked out of stock")
    for needed in page_needs:
        if needed not in document:
            problems.append(f"the page does not carry {needed!r}")

    print(f"  sections: {len(SECTIONS)} bands and {len(SECTIONS)} bar items, page order "
          + " ".join(s["n"] for s in SECTIONS))
    print("  band text: white on navy, white on red, ink on gold, ink on paper - four pairs, measured above")
    print("  row heights: " + ", ".join(f"{label.lower()} {px}px" for _v, label, px in DENSITIES))

    # 8. The document's shape. The bar and the bands are both generated from SECTIONS, so what is
    #    checked is that the generated page carries one of each, that the first band's "six numbers"
    #    is true of the figure list, that the three row heights in the list are the three the page
    #    offers and the three its own script knows, and that the chips and both empty states exist.
    if len(figs) != 6:
        problems.append(f"the first band says six numbers and the page builds {len(figs)}")
    bands_on_page = document.count('class="band band-')
    if bands_on_page != len(SECTIONS):
        problems.append(f"the page carries {bands_on_page} bands for {len(SECTIONS)} sections")
    if document.count("<h2>") != len(SECTIONS):
        problems.append(f"the page carries {document.count('<h2>')} section headings for "
                        f"{len(SECTIONS)} sections")
    for s in SECTIONS:
        if document.count(f'id="{s["id"]}"') != 1:
            problems.append(f"the section {s['id']!r} is not on the page exactly once")
        if f'href="#{s["id"]}"' not in document:
            problems.append(f"the jump bar has no item linking to {s['id']!r}")
        if f'data-accent="{s["accent"]}"' not in document:
            problems.append(f"no bar item carries the accent {s['accent']!r}")
        if not s["name"]:
            problems.append(f"the section {s['id']!r} has no name")
    for value, label, px in DENSITIES:
        if f'<option value="{value}"' not in document:
            problems.append(f"the page does not offer the {label!r} row height")
        if f"{label} &mdash; {px} px" not in document:
            problems.append(f"the {label!r} option does not say {px} px")
        if f"{value}: {px}" not in JS:
            problems.append(f"the page offers {value!r} at {px} px and its own script does not")
    if '--row-h:36px' not in document:
        problems.append("the page's starting row height is not the comfortable one")
    for needed in ('id="jump"', 'aria-label="Sections of this page"', 'aria-current',
                   'id="chips"', 'id="clear-all"', 'id="empty-filters"', 'id="empty-none"',
                   'id="density"', 'No price matches those filters', 'There is nothing to show yet'):
        if needed not in document:
            problems.append(f"the page does not carry {needed!r}")

    checked = (len(rows) + len(figs) * 2 + len(counts["runs"]) * 3 + len(CONTRAST_PAIRS) + 4
               + len(medicines) + len(default_tiles) + 3 + len(page_needs)
               + len(medicines) + 3 + len(has_stock) + len(out_only) + len(null_only)
               + len(cheapest_moved) + len(SECTIONS) * 4 + len(DENSITIES) * 3 + 9)
    if problems:
        print(f"{len(problems)} unexplained:", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        print("nothing written: a page whose numbers cannot be re-derived is not published.",
              file=sys.stderr)
        return 1

    SITE.mkdir(exist_ok=True)
    target = SITE / "dashboard.html"
    target.write_text(document, encoding="utf-8")
    weight = target.stat().st_size
    print(f"worst text pair: {worst_label} at {worst:.2f}:1")
    print(f"wrote {target.relative_to(ROOT)} ({weight:,} bytes, {len(rows):,} rows,"
          f" {weight / 1024 / 1024:.2f} MB)")
    print(f"{checked:,} rows and figures checked, 0 unexplained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
