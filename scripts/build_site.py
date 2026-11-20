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

# Where the published vintage is described. The page's download block is rendered from this one committed
# file and from nothing else: the two URLs, the vintage date, the licence and the words for what is inside
# all come out of it, so a mistyped link or a remembered date cannot reach the page. The record carries its
# own `verified_note`, saying who checked the live copies and when. Do not copy a value from it into this
# script - read it from the file.
PUBLISHED_RECORD = Path(__file__).resolve().parent.parent / "docs" / "published-vintage.json"

# The keys the block cannot be rendered without. An absent record is not a failure - nothing has been
# published, so there is nothing to link and no block is written. A record missing one of these is a build
# failure that names the key, because a half-written record would put a dead link on a public page.
PUBLISHED_REQUIRED = ("dataset_url", "doi_url", "vintage_date", "licence")

SITE = Path("site")

# Policy, not measurement: the project's own line for "this source has stopped reporting".
# schema/003_views.sql uses the same 48-hour interval in v_pipeline_health. Changing it here does not
# change the view, and the page says which threshold it applied.
STALE_HOURS = 48

# Is this repository a frozen vintage? Read from `freeze.json`, never assumed.
# WHY A FILE. The dates this page prints must come from a record rather than from memory, which is the
# same rule the tribute dates follow. The second reason matters more: a frozen page that keeps measuring
# freshness against the wall clock starts reporting every source as stale a couple of days after the
# last scrape, and that reads as a pipeline failure when it is a decision. With this file present,
# freshness is measured to the freeze instead, so the panel stays a true statement about the vintage.
# Delete the file and the page goes back to describing a live pipeline.
FREEZE_FILE = Path(__file__).resolve().parent.parent / "freeze.json"


def load_freeze() -> dict[str, Any] | None:
    try:
        return json.loads(FREEZE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


FROZEN = load_freeze()


def freeze_reference() -> datetime | None:
    """The moment collection stopped, or None while it is still running."""
    if not FROZEN:
        return None
    return datetime.fromisoformat(str(FROZEN["frozen_at_utc"]))


def human_date(value: str) -> str:
    """2026-11-16 -> 16 November 2026, without a platform-dependent %-d."""
    parsed = datetime.strptime(str(value), "%Y-%m-%d")
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


class PublishedRecordError(Exception):
    """The committed record exists but cannot be rendered from, so the build stops and names why."""


def load_published_vintage() -> dict[str, Any] | None:
    """The published-vintage record, or None when nothing has been published.

    ABSENT IS NOT A FAILURE. A repository that has not published its data must still build, so a missing
    record makes the page carry no download block and prints one line saying so - never a guessed link.
    A record that exists and is incomplete is a failure, because it would put a broken link or a wrong
    date on a public page: a missing key, a non-https URL or a date that is not a date stops the build
    with the offending key named. Nothing here is fetched; the file on disk is the only source.
    """
    try:
        raw = PUBLISHED_RECORD.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"no published vintage: {PUBLISHED_RECORD.name} is absent, so the page renders no "
              "download block", file=sys.stderr)
        return None
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishedRecordError(f"{PUBLISHED_RECORD.name} is not valid JSON: {exc}") from exc
    if not isinstance(record, dict):
        raise PublishedRecordError(f"{PUBLISHED_RECORD.name} is not a JSON object")
    missing = [key for key in PUBLISHED_REQUIRED if not str(record.get(key, "")).strip()]
    if missing:
        raise PublishedRecordError(
            f"{PUBLISHED_RECORD.name} is missing required key(s): {', '.join(missing)}")
    for key in ("dataset_url", "doi_url"):
        if not str(record[key]).startswith("https://"):
            raise PublishedRecordError(
                f"{PUBLISHED_RECORD.name}: {key} must be an https URL, found {record[key]!r}")
    try:
        human_date(str(record["vintage_date"]))
    except ValueError as exc:
        raise PublishedRecordError(
            f"{PUBLISHED_RECORD.name}: vintage_date must be YYYY-MM-DD, found "
            f"{record['vintage_date']!r}") from exc
    return record


def download_block(record: dict[str, Any] | None) -> str:
    """The Get-the-data section, or "" when there is no published vintage to point at.

    Every value is read from the record: the date, the licence, the wording for what is inside, and both
    URLs. Nothing is typed here, and nothing is fetched. The page's own "collection stopped" date is
    printed beside the record's date, so a reader never sees one date for the page and another for the
    download; when the two disagree the build prints a warning and both dates stay in the block rather
    than one being silently chosen.
    """
    if not record:
        return ""
    vintage = str(record["vintage_date"])
    stopped = str(FROZEN["frozen_on"]) if FROZEN else None

    if stopped:
        frozen = (f"Collection stopped on {esc(human_date(stopped))}, and the download is the vintage "
                  f"dated {esc(human_date(vintage))}.")
    else:
        frozen = f"The download is the vintage dated {esc(human_date(vintage))}."

    disagreement = ""
    if stopped and stopped != vintage:
        print(f"WARNING: the two dates disagree - the page says collection stopped on {stopped}, the "
              f"published record says the vintage is {vintage}; both are printed in the block",
              file=sys.stderr)
        disagreement = (
            '<p class="banner" role="note"><strong>Two dates do not agree.</strong> The rest of this '
            f'page says collection stopped on {esc(human_date(stopped))}; the published record is dated '
            f'{esc(human_date(vintage))}. Both are printed here rather than one being chosen.</p>'
        )

    inside = record.get("what_is_inside")
    inside_html = f'<p>Inside: {esc(str(inside).rstrip("."))}.</p>' if inside else ""
    doi = str(record.get("doi") or record["doi_url"])
    return f"""<section class="body" id="get-the-data" aria-labelledby="get-data-h">
  <div class="h2row"><h2 id="get-data-h">Get the data</h2></div>
  {disagreement}
  {inside_html}
  <p>Licence <strong>{esc(record["licence"])}</strong>: share and adapt the data, including for
  commercial use, as long as you credit it.</p>
  <ul>
    <li>Permanent archive, with a DOI: {link(record["doi_url"], f"doi:{doi}")}</li>
    <li>Browsable copy, one file per table: {link(record["dataset_url"], "Hugging Face Datasets")}</li>
    <li>The figures on this page as one machine-readable file, regenerated on every build and always
    current rather than frozen: {link("data.json", "data.json")}</li>
  </ul>
</section>"""


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
# The name as the dedication under her photograph uses it, and the years she led the agency.
# Both are read out of the same National Library of Nigeria item as the dates above: the item
# gives her name as "Dora Nkem Akunyili OFR" and says she "was the Director-General of National
# Agency for Food and Drug Administration and Control (NAFDAC) of Nigeria from 2001 to 2008"
# (.agent/DORA-facts.md, rows 1 and 3). The dedication uses the name she is known by.
DORA_COMMON_NAME = "Dora Akunyili"
DORA_DG_FROM = 2001
DORA_DG_TO = 2008

# The outline of Nigeria, inlined from the design study (docs/mockups/v1/index.html): one SVG path,
# no image file and no network. The study calls it a simplified outline and so does this.
NIGERIA_MAP_PATH = "M24.9 0.6L23.7 0.0L22.2 0.4L21.3 1.2L18.8 1.3L18.2 0.9L16.8 1.1L14.2 2.0L12.8 3.3L12.0 3.6L12.1 6.0L11.8 7.6L10.5 9.7L8.1 11.5L8.1 14.3L7.8 15.0L8.2 16.2L7.7 16.8L8.1 18.1L7.7 18.6L6.8 18.8L6.8 20.1L6.5 20.9L6.6 21.9L8.1 23.3L8.6 23.4L8.5 24.4L9.0 25.4L8.8 26.2L9.6 27.2L9.7 28.1L9.2 29.6L8.3 29.2L7.9 29.5L7.4 30.7L8.3 31.6L7.6 33.5L6.9 34.4L6.5 34.3L5.5 34.5L5.3 35.0L5.5 35.6L3.7 37.8L4.0 39.0L3.4 40.8L0.8 41.2L0.4 43.5L0.6 45.6L0.1 47.2L0.5 48.3L0.0 50.8L0.4 51.8L0.2 53.5L0.5 57.7L0.1 58.9L0.5 59.7L0.3 60.4L0.8 60.7L0.3 61.7L0.4 62.3L0.1 62.7L0.1 63.9L9.7 63.3L13.8 63.9L14.9 64.3L17.2 66.0L18.8 67.7L20.7 70.5L21.3 70.3L22.4 70.5L23.0 70.0L23.4 70.3L23.5 70.5L22.7 70.1L22.5 70.6L21.0 70.5L20.6 71.0L21.3 71.8L22.8 72.3L23.2 72.2L23.6 71.2L24.3 71.2L23.6 71.3L23.6 72.1L23.1 72.4L21.9 72.5L22.2 74.1L23.0 74.4L22.4 74.5L23.0 76.2L23.8 77.8L25.1 79.7L27.4 81.4L28.3 81.8L29.4 81.7L29.6 80.7L29.6 81.0L29.9 80.7L29.9 80.9L29.6 81.5L29.7 81.6L33.4 81.3L33.4 79.6L33.6 78.8L33.4 79.8L33.6 81.1L34.9 81.0L34.8 80.7L36.0 80.9L36.1 80.7L35.7 79.8L35.8 78.8L36.1 80.3L37.3 80.1L37.4 79.7L37.4 78.9L36.6 78.2L36.7 77.9L37.7 79.4L37.1 80.9L38.5 80.6L38.7 80.3L40.8 80.2L40.9 79.9L40.3 79.4L40.5 79.1L40.3 78.7L40.4 78.1L40.3 79.4L41.0 80.1L44.5 79.4L46.7 79.5L47.2 78.9L46.9 77.2L46.6 76.8L47.3 77.4L47.6 77.4L47.6 77.8L47.9 77.9L48.1 77.6L48.3 77.9L48.1 78.1L48.5 78.2L48.8 77.2L49.5 77.1L49.3 76.5L49.7 76.3L50.4 74.9L51.1 74.2L51.5 71.3L52.0 70.5L51.4 69.4L51.5 68.4L54.5 65.8L55.7 64.3L56.3 64.3L56.5 63.6L57.9 62.6L58.5 62.6L59.3 60.2L59.9 60.5L62.3 58.4L62.6 59.2L63.0 59.6L65.3 59.6L65.6 58.4L66.1 58.0L67.4 58.9L68.0 58.9L68.5 60.2L69.7 60.6L70.0 61.1L69.8 62.0L70.4 63.3L72.5 63.2L73.0 62.0L73.6 61.9L74.0 61.4L74.2 60.4L73.9 60.1L74.2 59.5L76.5 57.8L76.7 57.4L75.9 56.4L75.6 56.2L76.0 56.0L76.5 55.2L78.0 53.6L77.9 52.5L79.5 50.1L79.3 49.1L79.8 48.4L79.8 46.6L80.1 46.4L80.5 46.5L82.5 46.1L82.7 45.9L83.3 46.1L84.0 45.2L84.6 45.2L84.5 44.5L85.0 43.7L84.7 41.8L85.4 41.6L85.5 41.0L85.1 38.6L86.2 37.3L87.6 37.1L88.0 36.6L88.2 35.2L88.0 33.8L88.4 33.3L88.0 32.7L88.7 32.2L89.4 32.0L89.9 31.6L89.9 31.2L90.2 31.2L90.1 29.7L90.3 29.7L90.7 27.6L92.4 25.1L92.8 24.1L94.4 22.1L95.7 22.5L97.8 21.1L99.5 20.2L99.7 19.0L99.3 18.7L99.3 18.1L99.4 17.1L99.8 16.4L99.5 15.7L99.8 15.5L99.6 15.2L100.0 14.6L99.8 14.4L99.5 14.5L99.3 14.1L98.9 14.0L98.9 13.6L98.4 13.0L96.2 13.0L95.8 12.6L96.0 11.5L95.0 6.8L91.3 1.5L88.8 1.4L88.0 2.3L88.2 2.5L87.9 2.5L88.0 2.7L87.6 3.2L87.5 3.0L87.2 3.1L87.2 2.9L86.7 3.1L86.5 2.9L85.0 3.4L84.1 4.2L83.8 4.8L83.6 4.8L83.7 4.9L83.3 4.8L83.3 5.2L83.0 4.9L82.9 5.2L82.6 5.1L82.6 5.4L82.1 5.8L82.3 5.8L82.3 6.2L81.9 6.3L81.5 7.0L79.3 6.4L78.4 6.5L76.2 5.2L73.1 4.3L70.2 4.5L67.0 4.2L62.1 5.4L60.2 6.6L57.9 9.2L52.4 8.9L49.8 8.0L48.8 6.9L47.7 6.8L45.3 4.9L42.8 4.5L39.1 6.7L37.8 6.5L36.7 7.6L35.4 7.6L34.3 6.6L33.7 5.1L31.7 2.7L30.1 1.8L28.9 2.0L25.0 0.6Z"

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
IMAGE_FILES = (PORTRAIT_FILE,)
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

# The licensed photograph laid behind the methods page as a faint ground. It is not a portrait and it
# is evidence for nothing: the licence record is docs/assets/photos/CREDITS.md, and the credit words
# printed on the page are the ones that file records.
PHOTO_FILE = "drugs-nigeria.jpg"
PHOTO_SRC = Path("docs/assets/photos")
# The moving picture on the front page: a short recording of the dashboard being used, made from real
# screenshots of the built page rather than a mock-up. It replaces a grey box that said "placeholder",
# so the front page now shows the thing it links to. 313 KB at 128 colours, and the weight gate below
# counts it.
GIF_FILE = "dashboard-demo.gif"
GIF_SRC = Path("docs/assets/gifs")
PHOTO_FILE_PAGE = ("https://commons.wikimedia.org/wiki/"
                   "File:A_display_of_drugs_in_Nigeria.jpg")

# Page weight is a gate, not a wish: every image the pages publish must stay under this many bytes.
IMAGE_BUDGET_BYTES = 800 * 1024

# ---- the typefaces -------------------------------------------------------------------------------
# The 13 November study embedded five faces. Two of them - Instrument Serif, regular and italic - are
# never applied by the study's own CSS, so they are not carried over. The two that are applied are
# kept: the display face, Archivo Black, and the text face, Inter. Both are SIL Open Font License
# 1.1, which permits embedding and redistribution, and both are embedded here as data URIs so the
# published page fetches nothing at all.
#
# The bytes are the study's own faces, subset to the characters this page prints. The study's copies
# are already Google's "latin" subsets; the subsetting here drops the Latin letters this page never
# shows (Archivo Black 18,604 -> 11,788 bytes, Inter 48,256 -> 29,948 bytes) and keeps Inter's weight
# axis, so the semi-bold weight the tables use is a real weight and not a synthesised one.
#
# The naira sign is in neither face - U+20A6 is missing from both - so it is drawn by the system font.
# That is what the study did too, and it is the one glyph on the page that is not Inter.
FONT_ARCHIVO_BLACK = (
    "data:font/woff2;base64,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"
)
FONT_INTER = (
    "data:font/woff2;base64,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"
)

FONT_CSS = (
    '@font-face{font-family:"Archivo Black";src:url(' + FONT_ARCHIVO_BLACK + ') format("woff2");'
    'font-weight:400;font-style:normal;font-display:swap}\n'
    '@font-face{font-family:"Inter";src:url(' + FONT_INTER + ') format("woff2");'
    'font-weight:100 900;font-style:normal;font-display:swap}'
)

# ---- the word REGISTER ---------------------------------------------------------------------------
# The base of the hero carries the word REGISTER, enormous and faint, as the study has it.
#
# WHY IT IS AN OUTLINE AND NOT A TEXT NODE. Set as text at 22% opacity over the paper it measures
# 1.5:1, and WCAG 1.4.3 exempts only text that is pure decoration from the 4.5:1 floor - but an
# automated check cannot see that a word is decoration, and axe-core reads every visible text node
# whatever its role, so the page failed its own accessibility gate on one element. The word is
# therefore the same word in the same face, drawn as an SVG outline: a graphic, not a text node, so
# it is out of the accessibility tree altogether and nothing on the page claims to be readable
# lettering. The build still measures and prints the colour it paints (see DECORATIVE_PAIRS).
#
# The outline is Archivo Black at 1000 units wide, with the study's -0.05em letter spacing, taken
# from the same embedded face the headings use.
REGISTER_WORD_PATH = "M111.7 -54.2 140.5 0.0H93.9L70.9 -47.2H55.5V0.0H13.9V-129.4H93.1Q107.0 -129.4 116.9 -124.1Q126.8 -118.7 131.8 -109.6Q136.8 -100.5 136.8 -89.7Q136.8 -77.9 130.4 -68.3Q124.0 -58.7 111.7 -54.2ZM82.8 -99.9H55.5V-76.0H82.8Q87.7 -76.0 91.0 -79.5Q94.4 -83.0 94.4 -88.0Q94.4 -93.1 91.0 -96.5Q87.7 -99.9 82.8 -99.9Z M150.9 -129.4H262.8V-98.4H192.4V-80.5H252.6V-50.8H192.4V-31.0H264.1V0.0H150.9Z M408.2 -82.6H368.5Q368.5 -90.7 361.4 -95.7Q354.2 -100.6 344.1 -100.6Q329.4 -100.6 321.9 -92.8Q314.3 -85.0 314.3 -70.7V-58.7Q314.3 -44.4 321.9 -36.6Q329.4 -28.8 344.1 -28.8Q354.2 -28.8 361.4 -33.6Q368.5 -38.4 368.5 -45.9H339.2V-72.2H408.2V0.0H386.8L382.6 -12.8Q364.9 2.3 336.3 2.3Q304.2 2.3 288.0 -14.6Q271.8 -31.4 271.8 -64.7Q271.8 -97.6 290.2 -114.7Q308.5 -131.7 342.4 -131.7Q361.0 -131.7 375.8 -126.0Q390.7 -120.4 399.5 -109.4Q408.2 -98.4 408.2 -82.6Z M426.4 0.0V-129.4H468.0V0.0Z M599.9 -91.8V-89.5H560.9V-90.3Q560.9 -95.9 556.8 -99.7Q552.7 -103.5 544.2 -103.5Q535.9 -103.5 531.5 -101.0Q527.1 -98.6 527.1 -95.0Q527.1 -89.9 533.1 -87.5Q539.1 -85.0 552.5 -82.4Q568.1 -79.2 578.2 -75.7Q588.2 -72.2 595.7 -64.3Q603.3 -56.4 603.5 -42.9Q603.5 -19.9 587.9 -8.8Q572.4 2.3 546.5 2.3Q516.2 2.3 499.3 -7.9Q482.5 -18.1 482.5 -43.8H521.8Q521.8 -34.0 526.9 -30.8Q532.0 -27.5 542.7 -27.5Q550.6 -27.5 555.8 -29.2Q560.9 -30.9 560.9 -36.1Q560.9 -40.8 555.2 -43.2Q549.5 -45.5 536.5 -48.2Q520.7 -51.5 510.3 -55.2Q500.0 -58.9 492.3 -67.3Q484.6 -75.8 484.6 -90.3Q484.6 -111.6 501.0 -121.6Q517.5 -131.7 542.7 -131.7Q567.5 -131.7 583.5 -121.6Q599.5 -111.6 599.9 -91.8Z M689.2 -96.3V0.0H647.7V-96.3H605.2V-129.4H731.6V-96.3Z M741.2 -129.4H853.1V-98.4H782.7V-80.5H842.9V-50.8H782.7V-31.0H854.4V0.0H741.2Z M965.4 -54.2 994.2 0.0H947.5L924.6 -47.2H909.1V0.0H867.6V-129.4H946.8Q960.7 -129.4 970.6 -124.1Q980.4 -118.7 985.4 -109.6Q990.4 -100.5 990.4 -89.7Q990.4 -77.9 984.0 -68.3Q977.6 -58.7 965.4 -54.2ZM936.4 -99.9H909.1V-76.0H936.4Q941.3 -76.0 944.7 -79.5Q948.1 -83.0 948.1 -88.0Q948.1 -93.1 944.7 -96.5Q941.3 -99.9 936.4 -99.9Z"

def blend(front: str, back: str, alpha: float) -> str:
    """The colour a reader actually sees when a layer is painted at `alpha` over a background."""
    out = []
    for i in (1, 3, 5):
        f = int(front[i:i + 2], 16)
        b = int(back[i:i + 2], 16)
        out.append(int(round(alpha * f + (1 - alpha) * b)))
    return "#%02X%02X%02X" % tuple(out)


# ---- two palettes, one page each ------------------------------------------------------------------
# The front page uses the palette of the design study committed on 13 November
# (docs/mockups/v1/index.html): a deep accent on warm whites, her photograph as a watermark, the
# word REGISTER set enormous across the base. The study's palette was violet; it was moved to orange on
# 18 November at the author's instruction, and the papers warmed with it. The methods page keeps the
# cream palette it was built with, because only the front page's design was changed. Nothing here is
# red next to green: the price page must never colour a price.

# The cream palette, used by about.html only. Unchanged: two tints and one accent, taken from the one
# photograph rather than from taste. The two tints are the deep plum of the shadow behind her headwrap
# (#4f1f2f, about a tenth of the photograph's pixels) and the warm sand of the wall behind her
# (#dad0b7, about an eighth). The accent is the same plum at link strength; the band is that plum
# taken down to a shadow, so the band reads as the same hue and not as a second brand.
CREAM_INK = "#1a1612"
CREAM_MUTED = "#4a423d"
CREAM_LINE = "#d7cfbe"
CREAM_PAPER = "#faf7f1"
CREAM_PANEL = "#f1ebdf"
CREAM_ACCENT = "#5f2a54"
CREAM_WARN = "#7a2e00"
CREAM_WARN_BG = "#fdf1e3"
CREAM_BAND_BG = "#2a1a20"
CREAM_BAND_TEXT = "#f7f0e6"
CREAM_BAND_ACCENT = "#e2b25c"
# The methods page reads as a flow chart. Its step boxes used to alternate green and white; they now
# wear the three colours of her wrapper and headwrap - see DRESS_NAVY, DRESS_RED and DRESS_GOLD_RAW
# below, and the three tints derived from them. The green and the true white are gone with them.

# The orange palette, used by index.html. The hues are the study's own, moved from violet to orange at
# the author's instruction on 18 November ("make every purple orange, thick bleeding orange"). The
# relative lightness steps are kept, so the pairs measured below keep the ratios they were measured at:
# the accent is dark enough for white to sit on it (5.93:1) and light enough to be read on the page
# (5.64:1). The papers warm with the accent, because orange ink on a lavender sheet reads as two
# colours fighting rather than one page.
ORANGE = "#B23C00"        # headings, links, rules, and the plate behind white text
ORANGE_DEEP = "#8F3300"   # the deep band, and the button's own label inside it
ORANGE_SOFT = "#E2611F"   # DECLARATION ONLY, never set as text: 3.35:1 on the page, below the floor
INK = "#1C1108"
PAPER = "#FFF8F2"
RULE = "#EAD6C6"
MUTED = "#6B5343"
TINT = "#FEF2E8"        # the tribute band's ground, one step off the page
PANEL = "#FDEFE4"       # a flat warm panel, one step down from the page
NOT_ACTIVE = "#4A2C1A"  # a dark chocolate, chosen so a status tag cannot be read as an orange link
BAND_TEXT = "#F6D9C0"   # body text inside the deep band
BAND_PLATE = "#F7C6A3"  # the dashboard button's plate, and the links in the deep band
BAND_PLATE_HOVER = "#FBDCC4"
BAND_TAG = "#FBEDE2"         # the licence tags inside the deep band
BAND_TAG_RULE = "#DDA07C"    # their border: 3.3:1 on the band, above the 3:1 floor for a border

# Three colours read off her photograph, not chosen from taste: the navy and the red of her wrapper and
# the gold of its print, sampled with PIL from the portrait in this repository and darkened only where a
# colour could not be read as text on the page. The pale, raw values are in the comment beside each.
DRESS_NAVY = "#161A64"   # raw #161A64, unchanged - 14.61:1 on the page
DRESS_RED = "#9F2519"    # raw #9F2519, unchanged - 7.25:1 on the page
DRESS_GOLD = "#7A5800"   # raw #D7A320 was 2.18:1 as text; this is the same gold at text strength - 6.19:1

# The raw gold, kept because a box fill is not text. The gold of the wrapper's print measures 2.18:1
# as writing on the page, which is why DRESS_GOLD above is that same gold taken down to text
# strength. As the fill of a box it is the faithful colour, and the dark ink that sits on it
# measures 7.78:1.
DRESS_GOLD_RAW = "#D7A320"

# The pale half of each box: the same hue as the solid box beside it, at paper strength. These are
# not typed - each one is its hue blended into the page's own paper - so a pale box is provably the
# same colour as the solid one and only weaker.
CREAM_NAVY_TINT = blend(DRESS_NAVY, CREAM_PAPER, 0.10)
CREAM_RED_TINT = blend(DRESS_RED, CREAM_PAPER, 0.10)
CREAM_GOLD_TINT = blend(DRESS_GOLD_RAW, CREAM_PAPER, 0.16)

CREAM_PALETTE_CSS = f""":root{{--ink:{CREAM_INK};--muted:{CREAM_MUTED};--line:{CREAM_LINE};--bg:{CREAM_PAPER};
--panel:{CREAM_PANEL};--accent:{CREAM_ACCENT};--warn:{CREAM_WARN};--warn-bg:{CREAM_WARN_BG};
--band:{CREAM_BAND_BG};--band-ink:{CREAM_BAND_TEXT};--band-accent:{CREAM_BAND_ACCENT};
--pad:.75rem;--navy:{DRESS_NAVY};--red:{DRESS_RED};--gold:{DRESS_GOLD_RAW};--gold-ink:{DRESS_GOLD};
--tint-navy:{CREAM_NAVY_TINT};--tint-red:{CREAM_RED_TINT};--tint-gold:{CREAM_GOLD_TINT}}}"""

PALETTE_CSS = f""":root{{--orange:{ORANGE};--orange-deep:{ORANGE_DEEP};--orange-soft:{ORANGE_SOFT};
--ink:{INK};--bg:{PAPER};--rule:{RULE};--muted:{MUTED};--tint:{TINT};--panel:{PANEL};
--not-active:{NOT_ACTIVE};--band-text:{BAND_TEXT};--band-plate:{BAND_PLATE};
--band-plate-hover:{BAND_PLATE_HOVER};--band-tag:{BAND_TAG};--band-tag-rule:{BAND_TAG_RULE};
--dress-navy:{DRESS_NAVY};--dress-red:{DRESS_RED};--dress-gold:{DRESS_GOLD}}}"""

# Every text-on-surface pair the page actually uses, with the ratio WCAG 2.2 AA asks for (4.5:1 for
# body text). Measured at build time and printed; a pair below the floor fails the build.
#
# The pairs are split by the page that uses them, because the two pages carry two palettes. Every
# pair below is a pair of flat colours: no text in this project sits on a photograph, so every ratio
# here is a ratio between two measured values rather than an average over an image.
CONTRAST_FLOOR = 4.5
CONTRAST_PAIRS: list[tuple[str, str, str]] = [
    # about.html, cream palette
    ("about: band text on the band", CREAM_BAND_TEXT, CREAM_BAND_BG),
    ("about: gold text on the band", CREAM_BAND_ACCENT, CREAM_BAND_BG),
    ("about: body text on the page", CREAM_INK, CREAM_PAPER),
    ("about: secondary text on the page", CREAM_MUTED, CREAM_PAPER),
    ("about: secondary text on a panel", CREAM_MUTED, CREAM_PANEL),
    ("about: body text on a panel", CREAM_INK, CREAM_PANEL),
    ("about: links on the page", CREAM_ACCENT, CREAM_PAPER),
    ("about: links on a panel", CREAM_ACCENT, CREAM_PANEL),
    ("about: a warning on its own panel", CREAM_WARN, CREAM_WARN_BG),
    # about.html, the flow chart's step boxes: three colours, each in a solid and a pale form
    ("about: step text on a solid navy step", "#FFFFFF", DRESS_NAVY),
    ("about: step text on a solid red step", "#FFFFFF", DRESS_RED),
    ("about: step text on a solid gold step", CREAM_INK, DRESS_GOLD_RAW),
    ("about: step text on a pale navy step", CREAM_INK, CREAM_NAVY_TINT),
    ("about: secondary text on a pale navy step", CREAM_MUTED, CREAM_NAVY_TINT),
    ("about: a tool name on a pale navy step", DRESS_NAVY, CREAM_NAVY_TINT),
    ("about: step text on a pale red step", CREAM_INK, CREAM_RED_TINT),
    ("about: secondary text on a pale red step", CREAM_MUTED, CREAM_RED_TINT),
    ("about: a tool name on a pale red step", DRESS_RED, CREAM_RED_TINT),
    ("about: step text on a pale gold step", CREAM_INK, CREAM_GOLD_TINT),
    ("about: secondary text on a pale gold step", CREAM_MUTED, CREAM_GOLD_TINT),
    ("about: a tool name on a pale gold step", DRESS_GOLD, CREAM_GOLD_TINT),
    # index.html, orange palette
    ("front: body text on the page", INK, PAPER),
    ("front: secondary text on the page", MUTED, PAPER),
    ("front: secondary text on a panel", MUTED, PANEL),
    ("front: body text on a panel", INK, PANEL),
    ("front: headings and links on the page", ORANGE, PAPER),
    ("front: headings and links on a panel", ORANGE, PANEL),
    ("front: headings and links on a tint", ORANGE, TINT),
    ("front: a photograph caption", MUTED, PAPER),
    ("front: a photograph caption on a tint", MUTED, TINT),
    ("front: 'not active' on the page", NOT_ACTIVE, PAPER),
    ("front: 'not active' on a panel", NOT_ACTIVE, PANEL),
    ("front: 'active' on the page", "#1c5c2e", PAPER),
    ("front: 'not read' on the page", MUTED, PAPER),
    ("front: band body text on the deep band", BAND_TEXT, ORANGE_DEEP),
    ("front: band heading on the deep band", "#FFFFFF", ORANGE_DEEP),
    ("front: band tag on the deep band", BAND_TAG, ORANGE_DEEP),
    ("front: button text on its warm plate", ORANGE_DEEP, BAND_PLATE),
    ("front: the button's plate, hovered", ORANGE_DEEP, BAND_PLATE_HOVER),
    ("front: white on orange", "#FFFFFF", ORANGE),
    # the three figures carried by her dress colours, which are text and are therefore measured
    ("front: step figure one on the page", DRESS_NAVY, PAPER),
    ("front: step figure two on the page", DRESS_RED, PAPER),
    ("front: step figure three on the page", DRESS_GOLD, PAPER),
]

# The one pair on the page that is deliberately below the floor: the enormous word REGISTER across the
# base of the hero. It is decoration, not information - it is aria-hidden, it carries no meaning a
# reader needs, and no number or claim depends on it. It is measured anyway and printed, because a
# value that is not measured is a value nobody can argue with.
#
# The word is drawn in the accent at 22% opacity over the paper, so the colour a reader's eye gets is
# the blend of the two, not the accent. It is the blend that is measured here.
#
# Each entry carries a note, because "decoration" is not one thing. A watermark is a word nobody
# reads; a border is a boundary a reader must be able to see, and it is held to the 3:1 floor that
# WCAG asks of a non-text boundary rather than the 4.5:1 of text. The note says which is which.
DECORATIVE_PAIRS: list[tuple[str, str, str, float, str]] = [
    ("the REGISTER watermark on the page", ORANGE, PAPER, 0.22,
     "hidden from assistive technology, read by nobody"),
    # The methods page's own watermark: the tools that did the work, now in the two side margins
    # rather than behind the flow. It is painted as CSS generated content, so there is no text node
    # for a contrast checker to measure and nothing in the accessibility tree to announce.
    ("the tool-name strips on the methods page", CREAM_ACCENT, CREAM_PAPER, 0.12,
     "hidden from assistive technology, read by nobody"),
    # The rules around the pale boxes, measured against the fill each one bounds.
    ("the 2px rule around a pale navy step", DRESS_NAVY, CREAM_NAVY_TINT, 1.0,
     "a border, not text: it clears the 3:1 floor for a boundary"),
    ("the 2px rule around a pale red step", DRESS_RED, CREAM_RED_TINT, 1.0,
     "a border, not text: it clears the 3:1 floor for a boundary"),
    ("the 2px rule around a pale gold step", DRESS_GOLD, CREAM_GOLD_TINT, 1.0,
     "a border, not text: it clears the 3:1 floor for a boundary"),
    # The gold boxes carry a rule in the same gold at text strength, because the raw gold measures
    # 2.13:1 against the page and a boundary under 3:1 is a boundary a reader cannot find. Both
    # numbers are printed: the one that was rejected, and the one that is used.
    ("the edge of a gold step, against the page", DRESS_GOLD, CREAM_PAPER, 1.0,
     "the same gold at text strength: this is the edge a reader sees"),
    ("the raw gold fill, against the page", DRESS_GOLD_RAW, CREAM_PAPER, 1.0,
     "the fill itself, not the edge: the rule above is what bounds it"),
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


def dora_years() -> str:
    """1954 to 2014, read out of the two sourced dates rather than typed.

    WHY. The dedication under her photograph carries the years, and the years already exist in this
    file as the two dates taken from the National Library of Nigeria item. Typing them again would
    leave a second copy of a fact that can be wrong, so they are parsed out of those two constants.
    A date that is missing or in an unexpected shape stops the build, in the same way `dora_dates()`
    stops.
    """
    if not DORA_BORN or not DORA_DIED:
        raise UnsetDate(
            "her dates are unset (DORA_BORN=%r, DORA_DIED=%r): the dedication would have to print a "
            "year from memory. Fill both from the National Library of Nigeria item before building."
            % (DORA_BORN, DORA_DIED)
        )
    try:
        born = datetime.strptime(DORA_BORN, "%d %B %Y").year
        died = datetime.strptime(DORA_DIED, "%d %B %Y").year
    except ValueError as exc:
        raise UnsetDate(f"the sourced dates are not in the shape this file expects: {exc}") from exc
    return f"{born} to {died}"


def dedication_caption() -> str:
    """The one line that stands under her photograph: a dedication, and three sourced facts.

    WHY IT IS BUILT HERE AND NOT TYPED IN THE TEMPLATE. The years are read out of the sourced dates
    and the years she led NAFDAC are constants next to them, so the line cannot drift away from the
    record it quotes. The sentence itself is the author's, and it is a dedication rather than a
    citation: it is not attributed to anyone and it carries no quotation marks.
    """
    return (
        f"In beloved memory of {DORA_COMMON_NAME}. {dora_years()}. "
        f"Director-General of NAFDAC, {DORA_DG_FROM} to {DORA_DG_TO}."
    )


def dedication_caption_html() -> str:
    """The dedication, ready to drop into a <figcaption>, with the title held on one line.

    The title "Director-General" is one phrase and it must not be broken across two lines by the
    browser hyphen, so it is wrapped in a span that will not wrap. The words are the same words;
    only the line break is prevented.
    """
    head, _, tail = dedication_caption().partition("Director-General")
    return (f"{esc(head)}<span class=\"nowrap\">Director-General</span>{esc(tail)}")


def _luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(front: str, back: str) -> float:
    a, b = _luminance(front), _luminance(back)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def measure_contrast() -> tuple[float, list[str]]:
    """Every pair, measured. Returns the worst ratio and anything under the floor.

    The pairs that carry text a reader must read are held to the floor and fail the build. The
    decorative pairs are measured and printed as well, because a value nobody measured is a value
    nobody can argue with - but they are decoration, and they do not fail the build.
    """
    worst = 99.0
    problems: list[str] = []
    for label, front, back in CONTRAST_PAIRS:
        ratio = contrast_ratio(front, back)
        worst = min(worst, ratio)
        print(f"  contrast  {label:<44s} {ratio:5.2f}:1  ({front} on {back})")
        if ratio < CONTRAST_FLOOR:
            problems.append(f"{label}: {ratio:.2f}:1, below {CONTRAST_FLOOR}:1")
    for label, front, back, alpha, note in DECORATIVE_PAIRS:
        painted = blend(front, back, alpha)
        ratio = contrast_ratio(painted, back)
        print(f"  decoration {label:<44s} {ratio:5.2f}:1  ({front} at {alpha:.0%} over {back} paints "
              f"as {painted}) - {note}")
    return worst, problems


def publish_images() -> int:
    """Copy the repository's images next to the pages and refuse an over-weight page.

    The images live in `docs/assets/dora/` (the tribute) and `docs/assets/photos/` (a licensed
    photograph of a Nigerian chemist's shelves) as source; `site/` is build output and gitignored, so
    the published directory is filled here rather than committed. The weight gate counts both
    folders, because it is the reader's download that matters.
    """
    wanted = [(ASSET_SRC, name, SITE / "assets" / "dora") for name in IMAGE_FILES]
    wanted.append((PHOTO_SRC, PHOTO_FILE, SITE / "assets" / "photos"))
    wanted.append((GIF_SRC, GIF_FILE, SITE / "assets" / "gifs"))
    missing = [str(src / name) for src, name, _ in wanted
               if not (src / name).exists()]
    if missing:
        raise RuntimeError("image missing from the repository: " + ", ".join(missing))
    total = 0
    for src, name, out_dir in wanted:
        out_dir.mkdir(parents=True, exist_ok=True)
        data = (src / name).read_bytes()
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
    cheapest_pack_url,
    (select l.pack_unit from v_latest_listings l where l.url = cheapest_pack_url) as pack_unit
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
         status, flagged, url, pack_unit) in rows:
        out.append({
            "product": name,
            "state": state,
            "state_label": STATE_LABEL.get(state, state),
            "shop": shop,
            "price_ngn": money(price),
            "unit_price_ngn": money(unit_price),
            "pack_size": pack_size,
            "pack_unit": pack_unit,
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
                  stale_hours: float = STALE_HOURS,
                  reference: datetime | None = None) -> dict[str, Any]:
    seen = {}
    for source, last_ok, ok_runs, failed_runs, runs, hours in rows:
        # Frozen vintage: measure the gap to the moment collection stopped, not to now. Otherwise every
        # source crosses `stale_hours` a couple of days later and the page accuses a working pipeline of
        # having failed.
        if reference is not None and last_ok is not None:
            hours = (reference - last_ok).total_seconds() / 3600.0
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


# ---- the collection range ---------------------------------------------------
# WHEN COLLECTION STARTED, AND WHEN IT STOPPED. The front page's stamp says both ends of the range:
# the day the first price was recorded and the day the last one was. Neither end is typed.
# `price_history` is append-only, so `min(recorded_at)` is the moment collection started and
# `max(recorded_at)` is the moment it stopped. The two calendar days are those two values read in
# Lagos time - the clock the rest of this page speaks in - and the page prints the days.
COLLECTION_RANGE_SQL = """
select
    min(recorded_at)                                      as first_price,
    max(recorded_at)                                      as last_price,
    (min(recorded_at) at time zone 'Africa/Lagos')::date  as first_day,
    (max(recorded_at) at time zone 'Africa/Lagos')::date  as last_day
from price_history
"""


class MissingRange(RuntimeError):
    """Raised when the collection range cannot be read. The page will not print a guessed date."""


def derive_collection_range(rows: list[tuple]) -> dict[str, Any]:
    """Both ends of the collection range: the stored timestamps and the days they fall on.

    WHY FOUR VALUES AND NOT TWO. The two timestamps are what the table actually holds, rendered the
    way every other stored timestamp on this page is rendered (`iso()`), and they are compared on the
    re-read at zero tolerance, like every other timestamp here. The two days are the same two values
    read in Lagos time, and they are what the stamp prints. Keeping both means the page cannot print
    a day that the stored timestamp does not support, and neither value is typed.

    AN EMPTY TABLE IS A FAILURE, NOT A BLANK. A range with no end is not a range, and a page that
    says nothing about the range would be hiding the one thing it was asked to say.
    """
    first, last, first_day, last_day = rows[0]
    if first_day is None or last_day is None:
        raise MissingRange(
            "the collection range is empty: price_history holds no price row, so the page cannot say "
            "when collection started."
        )
    return {
        "first_price_utc": iso(first),
        "last_price_utc": iso(last),
        "first_day_lagos": str(first_day),
        "last_day_lagos": str(last_day),
    }


def human_range(first_day: str, last_day: str) -> str:
    """Two ISO days as the range the page prints: 2026-11-07 and 2026-11-15 -> "7 to 15 November 2026".

    WHY THE SHAPE FOLLOWS THE SPAN. Two days in the same month read as "7 to 15 November 2026",
    because the month and the year are shared and naming them twice is noise. Two days in different
    months have to name both months, and two days in different years have to name both years. The
    days themselves come from the query; only this shape is decided here.
    """
    start = datetime.strptime(str(first_day), "%Y-%m-%d")
    end = datetime.strptime(str(last_day), "%Y-%m-%d")
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day} to {end.day} {end.strftime('%B %Y')}"
    if start.year == end.year:
        return f"{start.day} {start.strftime('%B')} to {end.day} {end.strftime('%B %Y')}"
    return f"{start.day} {start.strftime('%B %Y')} to {end.day} {end.strftime('%B %Y')}"


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

# The collection range is a statement about a period that has closed, so it is collected - and the
# page prints it - only while the page describes a frozen vintage. While the pipeline is live the
# stamp already says when the newest price was recorded and how old it is; a range would be a range
# with no end, and the live page must not say what it cannot support.
if FROZEN:
    SPECS.append(Spec("collection_range", COLLECTION_RANGE_SQL, derive_collection_range))


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
    reference = freeze_reference()
    facts["health"] = derive_health(facts["health"], facts["ledger"], reference=reference)
    if reference is not None:
        newest = facts["overview"].get("newest_scrape_utc")
        if newest:
            # `iso()` renders timestamps for the page in "YYYY-MM-DD HH:MM UTC", so parse that shape
            # rather than inventing a second format. A change to `iso()` fails here, loudly.
            moments = datetime.strptime(str(newest), "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            facts["overview"]["hours_since_newest_scrape"] = (reference - moments).total_seconds() / 3600.0
    return facts


# Queries whose result is consumed by a compose function rather than printed on its own.
CONSUMED = {"breakdown", "ledger"}


# --------------------------------------------------------------------------- the page
# Two stylesheets, one page each. The cream sheet is the methods page, unchanged. The orange sheet is
# the front page, ported from the design study committed on 13 November.
# The tools that did the work, for the watermark behind the methods page's flow. Only tools that are
# actually in this project: the register, the database, its three extensions, the language and driver,
# the two models, the scheduler, the seed catalogue, the two places the frozen export is published,
# the source of her photograph, and the app that was built and never deployed - which is why the word
# beside it is "unused" rather than a claim that it runs.
CREAM_TOOLS = (
    "Neon Postgres \u00b7 PostgreSQL \u00b7 pgvector \u00b7 pg_trgm \u00b7 unaccent \u00b7 SQL \u00b7 "
    "Python \u00b7 psycopg \u00b7 fastembed \u00b7 bge-small-en-v1.5 \u00b7 GitHub Actions \u00b7 "
    "NAFDAC Greenbook \u00b7 #FixMedPrices \u00b7 Hugging Face \u00b7 Wikimedia Commons \u00b7 "
    "Streamlit (unused) \u00b7 "
)

# The cream sheet carries the display face it uses for the flow's headings and its watermark. The bytes
# are the same embedded Archivo Black the front page uses, not a second copy of the font: only the
# @font-face rule is repeated here, because a stylesheet cannot borrow another stylesheet's rules.
# The pointer, on every page. A capsule, half her red, half white, dark rim so it stays visible on the
# cream paper and on a white panel: 24x24 with the hotspot at the centre, and an arrow fallback for a
# browser that refuses an SVG cursor. It is decoration, nothing depends on it, and it is set on the
# document root so it is the default everywhere, tables included. The author will tune the artwork
# later; this is applied as-is.
CURSOR_CSS = """
html{cursor:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24'%3E%3Cdefs%3E%3CclipPath id='c'%3E%3Crect x='4' y='8' width='16' height='8' rx='4'/%3E%3C/clipPath%3E%3C/defs%3E%3Cg transform='rotate(-45 12 12)'%3E%3Crect x='4' y='8' width='16' height='8' rx='4' fill='%23ffffff'/%3E%3Crect x='4' y='8' width='8' height='8' fill='%239F2519' clip-path='url(%23c)'/%3E%3Crect x='4' y='8' width='16' height='8' rx='4' fill='none' stroke='%231a1612' stroke-width='1.5'/%3E%3C/g%3E%3C/svg%3E") 12 12,auto}
table,tbody,tr,td,th{cursor:inherit}
a,button,summary,input[type=checkbox],select{cursor:pointer}
"""

CSS_CREAM = r""":root{--ink:#1a1612;--muted:#4a423d;--line:#d7cfbe;--bg:#faf7f1;
--panel:#f1ebdf;--accent:#5f2a54;--warn:#7a2e00;--warn-bg:#fdf1e3;
--band:#2a1a20;--band-ink:#f7f0e6;--band-accent:#e2b25c;
--pad:.75rem;--navy:#161A64;--red:#9F2519;--gold:#D7A320;--gold-ink:#7A5800;
--tint-navy:#E3E1E3;--tint-red:#F1E2DB;--tint-gold:#F4EAD0}@font-face{font-family:"Archivo Black";src:url(data:font/woff2;base64,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) format("woff2");font-weight:400;font-style:normal;font-display:swap}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:1rem/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:62rem;margin:0 auto;padding:1rem var(--pad) 3rem}
/* Prose keeps a readable measure; tables are allowed the full width. */
.wrap p,.wrap li{max-width:68ch}.wrap .tablewrap,.wrap table{max-width:none}
/* The front door's links to the rest of the site: three cards, because there are three things to do
   after reading the prices - look at one price, understand the method, or take the data. */
.pagenav{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin:.9rem 0 .4rem}
.pagenav a{display:block;border:2px solid var(--line);border-radius:6px;padding:.6rem .7rem;
background:var(--panel);text-decoration:none;color:var(--ink)}
.pagenav a:hover,.pagenav a:focus{border-color:var(--ink)}
.pagenav strong{display:block;color:var(--accent)}
.pagenav span{display:block;font-size:.9rem;color:var(--muted);margin-top:.15rem}
@media (max-width:760px){.pagenav{grid-template-columns:1fr}}
/* The unit a price is per, printed beside the money. Smaller and muted so the number stays the loud
   thing while the unit cannot be lost. */
.unit{font-size:.86em;color:var(--muted);white-space:nowrap}
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
 :root{--pad:.6rem}
 .wrap{padding:.75rem var(--pad) 2rem}
 h1{font-size:1.35rem}
 table{font-size:.86rem}
 th,td{padding:.35rem .4rem}
 .masthead{gap:.7rem}
 .masthead-mark{width:4.6rem;flex-basis:4.6rem}
}
/* ---- the flow ---------------------------------------------------------------------------------
   The page is one flow chart: a box, a pale box of the same hue, down a dark arrow, in the order the
   work happened, cycling through the three colours of her wrapper and headwrap - navy, red, gold.
   Each box is still a step with its own <h2>, so the page is navigable by heading; the arrow between
   two boxes is decoration and is hidden from assistive technology. Every word in a box sits on a
   flat fill, solid or pale, so its contrast is a measured pair (see CONTRAST_PAIRS) rather than a
   hope. The arrows take the page's ink, so they are dark in both kinds of gap. */
.wrap{position:relative}
.wrap>header,.wrap>main,.wrap>footer{position:relative;z-index:1}
/* The zone is the page's full width - it is pulled out of the wrap's padding by exactly that padding
   - and the flow inside it is the 820px column, centred. The two margin strips and the photograph are
   placed against this zone, so each of them knows where the column begins without being told: the
   strip takes the margin the column leaves, and the photograph takes the column and the margins. */
.flowzone{position:relative;z-index:0;margin:1rem calc(-1 * var(--pad)) 2rem}
.flow{position:relative;z-index:2;max-width:820px;margin:0 auto}
.step{position:relative;border-radius:8px;padding:.9rem 1.05rem 1rem;overflow-wrap:break-word;
 border:2px solid transparent}
/* A solid box and a pale box of the same hue, in turn, so the page breathes the way it always did
   (a green box, then a white one with a green rule) but in three colours instead of one. */
.step.solid{color:#fff}
.step.pale{color:var(--ink)}
.step.navy{--tool-ink:var(--navy)}
.step.red{--tool-ink:var(--red)}
.step.gold{--tool-ink:var(--gold-ink)}
.step.navy.solid{background:var(--navy);border-color:var(--navy)}
.step.navy.pale{background:var(--tint-navy);border-color:var(--navy)}
.step.red.solid{background:var(--red);border-color:var(--red)}
.step.red.pale{background:var(--tint-red);border-color:var(--red)}
/* The gold boxes carry a rule in the same gold at text strength, because the raw gold measures
   2.15:1 against this page's paper (see DECORATIVE_PAIRS) and a boundary under 3:1 is a boundary a
   reader cannot find. The fill is still the raw gold, and the ink on it is the page's own ink. */
.step.gold.solid{background:var(--gold);border-color:var(--gold-ink);color:var(--ink)}
.step.gold.pale{background:var(--tint-gold);border-color:var(--gold-ink)}
.step h2{font-family:"Archivo Black",Impact,sans-serif;font-weight:400;font-size:1.08rem;
 line-height:1.25;letter-spacing:-.01em;border:0;padding:0;margin:0 0 .45rem;color:inherit}
.step h2 .n{display:block;font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;
 font-family:inherit;margin:0 0 .2rem}
.step ul{margin:.2rem 0 0;padding-left:1.05rem}
.step ol{margin:.2rem 0 0;padding-left:1.15rem}
.step .tablewrap{margin:.2rem 0 .1rem}
.step li{margin:.3rem 0;max-width:64ch}
.step p{margin:.45rem 0 0;max-width:64ch}
.step .tool{font-weight:700}
.step.pale .tool{color:var(--tool-ink)}
.step .fig{font-weight:700;font-variant-numeric:tabular-nums}
.step .sub{color:inherit}
.step.pale .sub{color:var(--muted)}
.step code{font-size:.9em;overflow-wrap:anywhere}
.arrow{position:relative;height:1.75rem}
.arrow::before{content:"";position:absolute;left:50%;margin-left:-1.5px;top:0;bottom:.55rem;width:3px;
 background:var(--ink)}
.arrow::after{content:"";position:absolute;left:50%;bottom:0;margin-left:-7px;
 border-left:7px solid transparent;border-right:7px solid transparent;border-top:9px solid var(--ink)}
/* ---- the tool names leave the page body ------------------------------------------------------------
   The tool names used to be one enormous watermark across the whole wrap, which meant every box
   covered most of it and the rest leaked out into the gaps and behind the header. They are now two
   vertical strips, one hard against each edge of the page, each inside the empty margin between
   that edge and the 820px column - the margin only, so no tool word can sit behind a box, behind
   the header or beside the text. They are painted as generated content, so there is no text node
   for a checker to measure and nothing in the accessibility tree to announce, and the layer clips
   them so they can never widen the page. Below the width where the margin is thinner than about
   70px both strips are removed outright: at 375px there is no strip, no clipped word and no
   sideways scroll. */
.wmstrip{position:absolute;top:0;bottom:0;z-index:1;overflow:hidden;pointer-events:none;
 user-select:none;writing-mode:vertical-rl;font-family:"Archivo Black",Impact,sans-serif;
 font-weight:400;font-size:.9rem;line-height:1.1;letter-spacing:.04em;color:var(--accent);
 opacity:.12;width:calc(max(0px, (100% - 820px)/2) - 2px)}
.wmstrip-l{left:0}
.wmstrip-r{right:0}
.wmstrip::before{content:"TOOLS";white-space:nowrap;display:block}
/* ---- the photograph -------------------------------------------------------------------------------
   A licensed photograph of a Nigerian chemist's shelves, laid as a faint ground behind the column.
   It carries no figure and no claim, no text sits on it (the header, every box and the footer are
   on opaque surfaces above it), and it is masked so that it fades out towards both edges and never
   reaches the tool-name strips in the margins. */
.photoground{position:absolute;top:0;bottom:0;z-index:0;pointer-events:none;overflow:hidden;
 background-color:var(--bg);left:0;right:0}
.photoground::before{content:"";position:absolute;inset:0;
 background:url("assets/photos/drugs-nigeria.jpg") center top/100% auto repeat-y;opacity:.1;
 -webkit-mask-image:linear-gradient(90deg,transparent 0,transparent 12%,#000 26%,#000 74%,transparent 88%,transparent 100%);
 mask-image:linear-gradient(90deg,transparent 0,transparent 12%,#000 26%,#000 74%,transparent 88%,transparent 100%)}
@media (max-width:959px){.wmstrip{display:none}}
@media (max-width:420px){
 .step{padding:.8rem .8rem .9rem}
 .step h2{font-size:1rem}
}
:root{--sb-h:49px}

/* ---- the site bar: one row of links, on every page but the front one --------------------
   The front page carries its three links inside its own masthead, so this bar is for the two
   inner pages. It is a fixed 49px, and `--sb-h` is that height and nothing else: the dashboard's
   jump bar is told to stick directly under it with no script, because a number that is written
   down cannot drift from the number that was measured. */
.sitebar{--nav-max:62rem;--nav-pad:.75rem;background:var(--bg);border-bottom:1px solid var(--line);
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
.wmstrip::before{content:"Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) ·  Neon Postgres · PostgreSQL · pgvector · pg_trgm · unaccent · SQL · Python · psycopg · fastembed · bge-small-en-v1.5 · GitHub Actions · NAFDAC Greenbook · #FixMedPrices · Hugging Face · Wikimedia Commons · Streamlit (unused) · "}"""


# The front page's stylesheet: the design study of 13 November, ported and recoloured orange.
#
# WHAT THE STUDY DID AND WHAT IS KEPT. The slim masthead with the wordmark and the Nigeria outline;
# the display headline on flat paper on the left with her photograph fading in from the right; the
# word REGISTER set enormous and faint across the base; a panel of figures under the headline; the
# deep block at the foot; the tables with the medicine, shop, price and registration status on
# one row. What is added is everything the study did not have: the frozen-snapshot stamp, the price
# tables with their stock and licence tags, the registration findings, pipeline health, the limits and
# the sources.
#
# WHERE TEXT SITS. Every piece of text on this page sits on a flat colour. Her photograph is a
# watermark on the right of the hero, masked so that it is fully transparent across the whole left
# column where the headline and the figures stand, and it carries no text of its own. The caption
# under it stands on the paper below it. The REGISTER word is decoration, is hidden from assistive
# technology, and is measured and printed anyway (see DECORATIVE_PAIRS).
CSS_ORANGE = PALETTE_CSS + """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
 font:1rem/1.55 "Inter",system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:0 24px}
a{color:var(--orange);text-underline-offset:3px}
a:focus-visible,:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
.skip{position:absolute;left:-9999px;top:0;background:var(--bg);padding:.6rem 1rem;z-index:10}
.skip:focus{left:.5rem;top:.5rem;border:2px solid var(--ink)}
h1,h2,h3{font-family:"Archivo Black",Impact,sans-serif;font-weight:400;margin:0;letter-spacing:-.025em}
p,li{margin:.5rem 0;overflow-wrap:break-word}
.note{color:var(--muted)}
strong{font-weight:600}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.92em}

/* ---- the masthead: wordmark, one line of place and date, the outline of the country ---------- */
.top{background:var(--bg);border-bottom:2px solid var(--orange)}
.top .wrap{display:flex;align-items:flex-start;justify-content:space-between;gap:32px;
 padding-top:20px;padding-bottom:18px}
.brand{font-family:"Archivo Black",Impact,sans-serif;font-size:26px;letter-spacing:-.03em;line-height:1;
 color:var(--orange)}
.brand b{font-weight:400;color:var(--ink)}
.tagline{font-size:14px;color:var(--muted);max-width:52ch;margin-top:8px;line-height:1.45}
.map{width:58px;height:auto;fill:var(--orange);flex:0 0 auto}
/* The map is decoration. On a phone it sat on a line of its own under the tagline, about 85 px
   of nothing between the reader and the headline, so it goes below this width, the same way the
   methods page hides its tool-name strips below 960 px. The desktop keeps it. This rule has to
   come after the base .map rule above, or the base rule wins and the map stays. */

/* ---- the hero: headline and figures on the left, her photograph fading in on the right -------- */
.hero{position:relative;overflow:hidden;background:var(--bg);border-bottom:1px solid var(--rule)}
.hero-grid{display:grid;grid-template-columns:minmax(0,1fr);padding:44px 24px 0;
 padding-left:max(24px,calc((100% - 1240px)/2));padding-right:24px}
.hero h1{font-size:clamp(34px,4.4vw,62px);line-height:.95;color:var(--orange);max-width:16ch}
/* The second half of the old headline, set as a paragraph on its own line: the same display face, the
   same black it had inside the headline, and the same size as the headline itself, so the split changes
   the line break and the colour, not the weight of the sentence. Ink on paper, 17.62:1. */
.hero .deck{font-family:"Archivo Black",Impact,sans-serif;font-size:clamp(34px,4.4vw,62px);
 line-height:.95;letter-spacing:-.025em;color:var(--ink);margin:8px 0 0;max-width:18ch}
.stamp{font-size:14px;color:var(--muted);margin:18px 0 0;max-width:54ch;line-height:1.5}
/* ---- the finding: one figure carries the claim, the line beneath is the receipt ------------------ */
.finding{margin:38px 0 0;max-width:56ch}
.finding .n{font-family:"Archivo Black",Impact,sans-serif;font-size:clamp(40px,4.2vw,56px);
 line-height:.86;letter-spacing:-.045em;color:var(--orange);margin:0}
.finding .k{font-size:17px;line-height:1.5;color:var(--ink);margin:12px 0 0;max-width:44ch}
.finding .k strong{font-weight:700;color:var(--orange)}
/* The receipt: four steps, the figures in her dress colours, in the order the work happened. The arrow
   takes the colour of the step it leads into, at the same small size: it is punctuation, not a figure. */
.finding .chain{margin:24px 0 0;border-top:2px solid var(--orange);padding-top:14px;
 display:flex;flex-wrap:wrap;align-items:flex-start;gap:0 14px;max-width:66ch}
.finding .st{display:flex;flex-direction:column;gap:6px;--c:var(--ink);min-width:6rem}
.finding .st::before{content:"";display:block;width:20px;height:3px;background:var(--c);margin-bottom:4px}
.finding .st.d1{--c:var(--dress-navy)}
.finding .st.d2{--c:var(--dress-red)}
.finding .st.d3{--c:var(--dress-gold)}
.finding .st.d4{--c:var(--orange)}
.finding .st b{font-family:"Archivo Black",Impact,sans-serif;font-size:clamp(25px,2.9vw,40px);
 line-height:1;letter-spacing:-.04em;color:var(--c)}
.finding .st i{font-style:normal;font-size:10px;letter-spacing:.07em;text-transform:uppercase;
 color:var(--muted);line-height:1.4;max-width:12ch;min-height:2.8em}
.finding .arw{font-size:17px;line-height:1;padding-top:23px;color:var(--rule)}
.finding .arw.d2{color:var(--dress-red)}
.finding .arw.d3{color:var(--dress-gold)}
.finding .arw.d4{color:var(--orange)}
.finding .rest{font-size:12.5px;line-height:1.6;color:var(--muted);margin:10px 0 0;max-width:52ch}
.finding .rest b{font-weight:700;color:var(--ink)}

/* The photograph. It is a watermark: masked so the whole left column stands on flat paper, and it
   carries no text. The caption under it stands on the paper below the image, never on the image. */
.hero-figure{margin:0;display:flex;flex-direction:column}
.hero-figure img{display:block;width:100%;height:100%;min-height:0;object-fit:cover;
 object-position:60% 16%;opacity:.62;
 -webkit-mask-image:linear-gradient(to right,transparent 0%,rgba(0,0,0,.35) 26%,#000 62%);
 mask-image:linear-gradient(to right,transparent 0%,rgba(0,0,0,.35) 26%,#000 62%)}
.photocaption{margin:10px 0 0;font-size:12.5px;line-height:1.45;color:var(--muted);max-width:46ch}
.nowrap{white-space:nowrap}

/* The base of the hero: REGISTER, enormous and faint. Decoration, hidden from assistive technology,
   measured and printed by the build. */
.hero-base{position:relative;height:104px;overflow:hidden;margin-top:30px}
.bleedword{position:absolute;left:-2vw;top:0;width:calc(clamp(110px,18vw,270px)*5.316);
 height:auto;fill:var(--orange);opacity:.22;pointer-events:none;user-select:none}

/* ---- the three doors to the rest of the site -------------------------------------------------- */
/* Reserved space for one recording: the dashboard in use. One frame, full content width and tall enough
   that a screen recording of a real session can sit in it without being shrunk to illegibility. Dashed so
   it cannot be mistaken for a finished element. */
.placeholder-row{display:block;margin:2.2rem 0 0}
.shot{margin:0}
.shot img{display:block;width:100%;height:auto;border:1px solid var(--rule);border-radius:6px;background:var(--panel)}
.shot figcaption{margin-top:.5rem;font-size:.9rem;color:var(--muted)}
.ph{min-height:440px;border:2px dashed var(--rule);border-radius:6px;
 background:var(--tint);display:flex;align-items:center;justify-content:center;padding:1.2rem;
 text-align:center}
.ph span{font-size:11.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
 line-height:1.5;max-width:24ch}
.dashrow{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
.dashrow .dash{margin-top:0}
.dl{font-size:13.5px;line-height:1.7;color:var(--muted);margin:14px 0 0}
.dl strong{color:var(--ink)}
.dl .fig{font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums}
@media (max-width:760px){.ph{min-height:240px}}

/* ---- sections -------------------------------------------------------------------------------- */
section.body{padding:40px 0 0}
.h2row{display:flex;align-items:end;justify-content:space-between;gap:24px;
 border-bottom:2px solid var(--orange);padding-bottom:10px}
h2{font-size:clamp(22px,2.4vw,30px);line-height:1.02;color:var(--orange);max-width:26ch}
h3{font-size:clamp(18px,1.8vw,22px);line-height:1.1;color:var(--orange);margin-top:2.2rem}
.sub{font-size:15px;color:var(--muted);margin:12px 0 0;max-width:64ch}
.fact{background:var(--panel);border-left:4px solid var(--orange);padding:.8rem .9rem;margin:1rem 0;
 border-radius:0 4px 4px 0}
.banner{background:var(--panel);border:2px solid var(--orange-deep);color:var(--ink);
 padding:.8rem .95rem;margin:1rem 0;border-radius:4px}

/* ---- tables ---------------------------------------------------------------------------------- */
.tablewrap{overflow-x:auto;border:1px solid var(--rule);border-radius:4px;margin:.6rem 0 1.2rem}
table{border-collapse:collapse;width:100%;font-size:.95rem}
caption{text-align:left;padding:.55rem .6rem;background:var(--panel);color:var(--muted);
 border-bottom:1px solid var(--rule);font-size:.9rem}
.tablelabel{font-weight:600;margin:.9rem 0 .3rem;font-size:.98rem;overflow-wrap:break-word}
td.desc{min-width:11rem}
th,td{padding:.45rem .55rem;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
thead th{background:var(--panel);white-space:nowrap;color:var(--muted);font-size:.82rem;
 letter-spacing:.06em;text-transform:uppercase;font-weight:600}
tbody th{font-weight:600}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.unit{font-size:.86em;color:var(--muted);white-space:nowrap}
.tag{display:inline-block;font-size:.8rem;line-height:1.4;padding:0 .3rem;border:1px solid;
 border-radius:3px;white-space:nowrap}
.tag-ok{border-color:#1c5c2e;color:#1c5c2e}
.tag-bad{border-color:var(--not-active);color:var(--not-active)}
.tag-unknown{border-color:var(--muted);color:var(--muted)}
ol.limits{padding-left:1.15rem}
ol.limits li{margin:.75rem 0}

/* ---- the tribute band: her photograph, its caption, and what the page owes her ---------------- */
.band{background:var(--tint);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
 margin:2.6rem 0}
.band-inner{max-width:1240px;margin:0 auto;padding:1.6rem 24px;display:grid;
 grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:36px;align-items:center}
.band-photo{margin:0}
.band-photo img{display:block;width:100%;height:260px;object-fit:cover;object-position:50% 26%;
 border:1px solid var(--rule)}
.band-text h2{font-size:clamp(20px,2vw,26px)}
.band-text p{font-size:15px;color:var(--muted);margin:.6rem 0 0;max-width:46ch}
.band-text a{color:var(--orange)}

/* ---- the deep block: how the numbers were produced -------------------------------------------- */
.built{background:var(--orange-deep);color:var(--tint);margin-top:3rem}
.built .wrap{display:grid;grid-template-columns:5fr 7fr;gap:40px;padding-top:36px;padding-bottom:40px;
 align-items:start}
.built h2{color:#fff;font-size:clamp(22px,2.2vw,28px)}
.built p{font-size:14px;color:var(--band-text);margin:12px 0 0;max-width:46ch}
.built a{color:var(--band-plate)}
/* The dashboard button is a link inside the dark block, so the block's link colour painted its label the
   same colour as its own background: 1:1, invisible. axe reported it as "incomplete" rather than a
   failure, and reading the computed style confirmed axe was right about the ratio. */
.built a.dash{color:var(--orange-deep);background:var(--band-plate)}
.built a.dash:hover{background:var(--band-plate-hover)}
.tags{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.tags li{font-size:12px;letter-spacing:.08em;text-transform:uppercase;border:1px solid var(--band-tag-rule);
 color:var(--band-tag);padding:7px 10px}
.dash{display:inline-block;margin-top:20px;font-family:"Archivo Black",Impact,sans-serif;font-size:13px;
 letter-spacing:.02em;color:var(--orange-deep);background:var(--band-plate);text-decoration:none;padding:11px 16px}
.dash:hover{background:var(--band-plate-hover)}

/* ---- the footer ------------------------------------------------------------------------------- */
footer{background:var(--bg);border-top:2px solid var(--orange);padding:24px 0 46px;font-size:12.5px;
 color:var(--muted)}
footer .wrap{max-width:1240px;margin:0 auto;padding:0 24px}
.footer-mark{width:4rem;height:4rem;float:left;margin:0 .8rem .5rem 0;border-radius:3px;
 box-shadow:0 0 0 1px var(--rule);display:block}
.credits{clear:both;padding-top:.6rem}
.credits p{margin:.4rem 0}

@media (min-width:981px){
  /* The photograph reaches the right-hand edge of the screen, and the left column stops well
     before the picture becomes visible, so no text ever stands on the photograph. */
  .hero-grid{grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);column-gap:40px;padding-right:0}
  .hero-copy{grid-column:1;grid-row:1}
  .hero-figure{grid-column:2;grid-row:1;align-self:stretch;justify-content:flex-end}
  .hero-figure .photocaption{text-align:right;margin-left:auto;padding-right:20px}
}
@media (max-width:1180px){
  .fig .n{font-size:26px}
}
@media (max-width:980px){
  .hero-grid{padding:34px 24px 0}
  .hero-figure{margin-top:26px}
  .hero-figure img{height:300px;object-position:50% 12%;opacity:.55}
  .hero-base{height:72px;margin-top:22px}
  .bleedword{width:calc(clamp(64px,20vw,130px)*5.316);left:-6vw}
  .pagenav{grid-template-columns:1fr}
  .figs{flex-wrap:wrap}
  .fig{flex:1 1 45%}
  .fig:nth-child(3){border-left:0;padding-left:0}
  .band-inner{grid-template-columns:1fr;gap:20px}
  .built .wrap{grid-template-columns:1fr}
  .top .wrap{flex-direction:column;gap:14px}
}
@media (max-width:560px){
  .fig{flex:1 1 50%}
  .fig .n{font-size:24px}
  /* The tally wraps to two rows, so a trailing arrow would point at nothing: the row order carries the
     sequence on a narrow screen instead. */
  .finding .arw{display:none}
  .finding .chain{gap:14px 22px}
  .finding .st{min-width:7rem}
  table{font-size:.88rem}
  th,td{padding:.35rem .4rem}
  .num{padding-right:.6rem}
  .hero h1{max-width:12ch}
  .hero-figure img{height:230px}
  .wrap{padding-left:16px;padding-right:16px}
  .hero-grid{padding-left:16px;padding-right:16px}
}

/* ---- the navigation on the front page: three links in the masthead row, and a quick index
   under it. No second wordmark: the masthead already carries the name, so the links join the
   row that is already there, to the left of the map. */
.mast-right{display:flex;align-items:center;gap:28px}
.mastnav ul{list-style:none;display:flex;align-items:center;margin:0;padding:0;overflow-x:auto;
 overscroll-behavior-x:contain;scrollbar-width:none}
.mastnav ul::-webkit-scrollbar{display:none}
.mastnav li{margin:0;padding:0;flex:0 0 auto}
.mastnav a{position:relative;display:block;padding:12px 11px;min-height:44px;line-height:20px;
 font-size:13.5px;font-weight:600;color:var(--ink);text-decoration:none;white-space:nowrap}
.mastnav a::after{content:"";position:absolute;left:11px;right:11px;bottom:9px;height:3px;
 background:transparent}
.mastnav a:hover{color:var(--dress-red)}
.mastnav a[aria-current="page"]{font-weight:700}
.mastnav a[aria-current="page"]::after{background:var(--dress-red)}
.mastnav a:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
/* ---- the quick index: four places to go from the front page, one row under the masthead --- */
.quickidx{background:var(--bg);border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.qi-inner{max-width:1240px;margin:0 auto;padding:0 24px}
.qi-list{list-style:none;display:flex;flex-wrap:wrap;margin:0;padding:0}
.qi-list li{margin:0;padding:0;border-left:1px solid var(--rule)}
.qi-list li:first-child{border-left:0}
.qi-list a{display:block;padding:10px 14px;min-height:44px;text-decoration:none;line-height:1.5}
.qi-t{font-size:11px;letter-spacing:.11em;text-transform:uppercase;font-weight:700;color:var(--ink)}
.qi-d{font-size:12.5px;color:var(--muted)}
.qi-d::before{content:"\u00a0\u2014\u00a0"}
.quickidx a:hover .qi-t{color:var(--dress-red)}
.quickidx a:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
@media (max-width:560px){
 /* On a phone the masthead stacks, so the three links move into the quick index, which becomes
    one row of four labels that scrolls inside itself - the pattern the dashboard's jump bar
    already uses - and the glosses go, because four of them cannot sit above the heading on a
    phone without costing more room than the heading is worth. */
 .mastnav{display:none}
 .qi-inner{--qi-pad:16px;padding:0 var(--qi-pad);position:relative}
     of nothing between the reader and the headline, so it goes below this width. The three nav
     links have already moved into the quick index, so the right-hand block the map sat in is empty
     without it, and the empty row and its gap go with it. This rule has to sit after the base
     .mast-right rule below, or the base rule wins and the map stays. */
     of nothing between the reader and the headline, so it goes below this width, the same way the
 .qi-list{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none}
     methods page hides its tool-name strips below 960 px. The desktop keeps it. The three nav
 .qi-list::-webkit-scrollbar{display:none}
     links have already moved into the quick index, so the right-hand block the map sat in is empty
 .qi-list li{border-left:0;border-right:1px solid var(--rule)}
     without it, and the empty row and its gap go with it. */
 .qi-list a{height:44px;min-height:44px;padding:0 12px;display:flex;align-items:center;
  white-space:nowrap}
 .qi-d{display:none}
  /* The map is decoration: on a phone it sat on a line of its own under the tagline, about 85 px
     of nothing between the reader and the headline, so it goes below this width, the same way the
     methods page hides its tool-name strips below 960 px. The desktop keeps it. The three nav
     links have already moved into the quick index, so the right-hand block the map sat in is empty
     without it, and the empty row and its gap go with it. */
  .mast-right{display:none}
  /* The strip scrolls inside itself, and the label at the cut used to be sliced through the middle
     of a letter: a cut with nothing to say so reads as a bug, not as an invitation to scroll. This
     is a 24 px fade over the last 24 px of the strip, in the ground colour the page already uses,
     with no new colour and no shadow. It is drawn on the strip and not inside the scrolling list,
     so it stays put while the list moves, and it is drawn at this width only: above it the list
     wraps and nothing is cut. The script at the foot of the page puts the class on while there is
     more to the right, and takes it off at the end of the list, where nothing is cut. */
  .qi-inner::after{content:"";position:absolute;top:0;bottom:0;right:var(--qi-pad);width:24px;
   background:var(--bg);pointer-events:none;opacity:0;
   -webkit-mask-image:linear-gradient(to right,rgba(0,0,0,0),#000);
   mask-image:linear-gradient(to right,rgba(0,0,0,0),#000)}
  .qi-inner.qi-more::after{opacity:1}
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


UNIT_WORD = {"tab": "tablet", "cap": "capsule", "ml": "ml", "g": "g", "mcg": "mcg", "iu": "iu"}


def unit_price_cell(row: dict[str, Any]) -> str:
    """A unit price without its unit is not a number a reader can use.

    WHY THIS EXISTS. One row on the comparison table is a 100 ml syrup recorded with pack size 100 and
    pack unit `ml`, so its unit price is per millilitre. Under a column headed "per pack unit" it read
    as a per-tablet price and sat directly above a per-tablet row, which looks like a 5x saving and is
    not one. The unit is printed beside the money wherever we recorded one; where none was recorded the
    money is left unannotated rather than implied.
    """
    value = row["unit_price_ngn"]
    if value is None:
        return naira(None)
    unit = UNIT_WORD.get(str(row.get("pack_unit") or "").strip().lower())
    if unit:
        return f'{naira(value)}<span class="unit"> per {esc(unit)}</span>'
    return naira(value)


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
            f'<td class="num">{unit_price_cell(row)}</td>',
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


# The figures the methods page states. Kept in one place so that `about_drift` can check the ones that
# come from the database against it, rather than trusting prose typed once and never re-read.
ABOUT: dict[str, Any] = {
    "listings": 2800,
    "attached": 559,
    "unattached": 2241,
    "products": 1433,
    "priced": 335,
    "cells": 261,
    "comparisons": 44,
    "flagged": 154,
    "regs": 10967,
    "with_status": 1856,
    "coverage": "16.9",
    "index_rows": 428,
    "changes": 3,
    # Records of the build itself, not re-derivable from the database.
    "seed_products": 1074,
    "added_products": 359,
    "cleared_links": 54,
    "lost_links": 28,
    "audit_numbers": 3791,
    "exported_rows": 36936,
    "exported_tables": 8,
    "restore_checks": 22,
}

ABOUT_DRIFT_SQL: list[tuple[str, str]] = [
    ("listings", "select count(*) from v_latest_listings"),
    ("attached", "select count(*) from v_latest_listings where product_id is not null"),
    ("products", "select count(*) from products"),
    ("priced", "select count(distinct product_id) from v_latest_listings where product_id is not null"),
    ("cells", "select count(*) from v_cheapest_per_product_state"),
    ("comparisons", "select count(*) from v_cheapest_per_product_state where is_comparison"),
    ("flagged", "select count(*) from v_suspicious_listings"),
    ("regs", "select count(*) from nafdac_registrations"),
    ("with_status", "select count(*) from nafdac_registrations where status is not null"),
    ("index_rows", "select count(*) from mv_drug_price_index"),
    ("changes", "select count(*) from v_price_change_7d"),
]


def about_drift(conn: Any) -> list[str]:
    """The methods page states figures as prose; this checks the ones a query can answer.

    WHY. Prose is the one place a stale number can hide in this project: the front page is audited by
    re-running its queries, and the methods page is not. These eleven queries are cheap, and they turn
    "the page says 2,800" into a build failure when it stops being true.
    """
    problems = []
    for key, sql in ABOUT_DRIFT_SQL:
        try:
            actual = conn.execute(sql).fetchone()[0]
        except Exception as exc:  # noqa: BLE001 - a failing query is itself a finding
            problems.append(f"methods page: cannot check {key}: {type(exc).__name__}")
            continue
        if int(actual) != int(ABOUT[key]):
            problems.append(f"methods page says {key}={ABOUT[key]}, database says {actual}")
    return problems


def about_page() -> str:
    """The methods page: how the deliverable was built, and what it cannot claim.

    WHY THIS PAGE EXISTS. It used to be a biography of Dora Akunyili. The tribute to her belongs on the
    front page, where it is; a reader who follows a link from a price table wants to know how the price
    was obtained and what has been checked, not who founded the register. So this page is the account of
    the work: eight stages in the order they happened, the decisions with what each one cost, and the
    limits stated rather than buried.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>How this was made - NaijaDrugWatch</title>
<link rel="icon" href="data:,">
<style>{CSS_CREAM}{CURSOR_CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>
<nav class="sitebar" aria-label="Site">
  <div class="sb-inner">
    <a class="sb-mark" href="index.html" aria-label="NaijaDrugWatch, home page">NaijaDrugWatch</a>
    <ul class="sb-links">
      <li><a href="index.html">The finding</a></li>
      <li><a href="dashboard.html">Every price</a></li>
      <li><a href="about.html" aria-current="page">How this was made</a></li>
    </ul>
  </div>
</nav>
<div class="wrap">
<header>
<h1>How this was made</h1>
<p class="lede">NAFDAC status, joined to Nigerian pharmacy prices. Independent, $0 a month, not endorsed by
NAFDAC or any pharmacy here. Code MIT, data CC-BY-4.0. The register: the agency Dora Akunyili led,
2001&ndash;2008. Her tribute is on the <a href="index.html">front page</a>.</p>
</header>
<main id="main">
<div class="flowzone">
<div class="photoground" aria-hidden="true"></div>
<div class="wmstrip wmstrip-l" aria-hidden="true"></div>
<div class="wmstrip wmstrip-r" aria-hidden="true"></div>
<div class="flow">

<div class="step solid navy" id="register">
<h2><span class="n">01 &middot; register</span> Register first. No API.</h2>
<ul>
<li><span class="tool">NAFDAC Greenbook</span>. No API. <code>/api/*</code> &rarr; 404. No mirror.</li>
<li>HTML. 6 category pages: name, form, strength, number. Detail: status, expiry.</li>
<li>Frozen: <span class="fig">{ABOUT["regs"]:,}</span> registrations. <span class="fig">{ABOUT["with_status"]:,}</span> readable (<span class="fig">{ABOUT["coverage"]}%</span>).</li>
<li>Unread &ne; clean. Expired certificates. HTTP only: local checksums.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale navy" id="catalogue">
<h2><span class="n">02 &middot; seed</span> Seed list. Borrowed.</h2>
<ul>
<li><span class="tool">#FixMedPrices</span>, CC-BY-4.0. <span class="fig">{ABOUT["seed_products"]:,}</span> products.</li>
<li>Herbal. Reproductive health. Almost none of what a pharmacy shelves.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid red">
<h2><span class="n">03 &middot; catalogue</span> Rebuild. Register is judge.</h2>
<ul>
<li>Linker tool. Rules: name overlaps, strength agrees, form compatible.</li>
<li>Authority: the <span class="tool">register</span>. Not the shop's wording.</li>
<li>+<span class="fig">{ABOUT["added_products"]}</span> products &rarr; <span class="fig">{ABOUT["products"]:,}</span>.</li>
<li>Priced at freeze: <span class="fig">{ABOUT["priced"]}</span>. A catalogue is not a shop shelf.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale red" id="scraping">
<h2><span class="n">04 &middot; scrape</span> Scrape. API first.</h2>
<ul>
<li>API first: <span class="tool">WooCommerce Store API</span>, <span class="tool">Shopify /products.json</span>.</li>
<li>No API? HTML.</li>
<li>Polite: 2 s per host. <span class="tool">Python</span>, <span class="tool">psycopg</span>. Named User-Agent.</li>
<li>Product and price fields only.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid gold">
<h2><span class="n">05 &middot; route</span> MedPlus. Wrong door, right door.</h2>
<ul>
<li>Category pages: same 20 links, every page. Dead end.</li>
<li>Drugs route: 20 per page. Page 70: 16 links. Page 71: empty.</li>
<li><span class="fig">128</span> &rarr; <span class="fig">1,396</span> products.</li>
<li>Night run: 1 h 50 m &rarr; 2 h 50 m.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale gold">
<h2><span class="n">06 &middot; refusals</span> Refusal = failure.</h2>
<ul>
<li>403, 429: stop. Failed row written.</li>
<li>Night fails: over 10% of pages fail, or a full sweep returns under 1,000 records.</li>
<li>Both thresholds: judgement, not measurement. The code says so.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid navy" id="matching">
<h2><span class="n">07 &middot; match</span> Two stages. Never similarity alone.</h2>
<ul>
<li><span class="tool">fastembed</span> and <span class="tool">bge-small-en-v1.5</span>, 384 dims, <span class="tool">pgvector</span>: top 10.</li>
<li>Then rules: strength, form, ingredient. <span class="tool">pg_trgm</span>, <span class="tool">unaccent</span>.</li>
<li>Similarity alone: rejected.</li>
<li>Attached <span class="fig">{ABOUT["attached"]:,}</span> of <span class="fig">{ABOUT["listings"]:,}</span>. <span class="fig">{ABOUT["unattached"]:,}</span> not.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale navy">
<h2><span class="n">08 &middot; guard</span> Strength guard. Late. Costly.</h2>
<ul>
<li>No listing attached to a different strength.</li>
<li>Cleared <span class="fig">{ABOUT["cleared_links"]}</span> wrong links across 22 products. No contradictions under the strict check.</li>
<li>Cost: <span class="fig">{ABOUT["lost_links"]}</span> matched listings.</li>
<li>One known false refusal: Augmentin 1 g against 875 mg + 125 mg. 1,000 mg is the sum of the parts.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid red" id="views">
<h2><span class="n">09 &middot; views</span> Answers are views.</h2>
<ul>
<li><span class="tool">SQL</span> on <span class="tool">PostgreSQL</span>: latest, cheapest, two-shop, not-active, 7-day.</li>
<li><span class="fig">{ABOUT["listings"]:,}</span> listings. <span class="fig">{ABOUT["attached"]:,}</span> attached. <span class="fig">{ABOUT["cells"]}</span> price cells. <span class="fig">{ABOUT["comparisons"]}</span> comparisons. <span class="fig">{ABOUT["flagged"]}</span> not active.</li>
<li>7-day: <span class="fig">{ABOUT["changes"]}</span> products. Works. Market quiet.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale red">
<h2><span class="n">10 &middot; index</span> Index refreshed by machine.</h2>
<ul>
<li><span class="tool">mv_drug_price_index</span>. <span class="fig">{ABOUT["index_rows"]}</span> rows.</li>
<li>Refresh: pipeline, not person. A stale index looks like a quiet market.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid gold" id="audit">
<h2><span class="n">11 &middot; audit</span> Page proves itself.</h2>
<ul>
<li>Build renders. Re-reads every query. Compares. Disagreement: nothing written.</li>
<li>Last line of the build: <span class="fig">{ABOUT["audit_numbers"]:,} numbers checked, 0 unexplained</span>.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale gold">
<h2><span class="n">12 &middot; every price</span> Second page. Every price.</h2>
<ul>
<li>Filters on. Each row &rarr; the shop page it came from, the register record behind it.</li>
<li>Links: sources inspectable. Parsing: not proven.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid navy" id="checked">
<h2><span class="n">13 &middot; human check</span> Rule first. Verdict after.</h2>
<ul>
<li>20 licence cards. 20 pack cards. Seeded draw. No substitution.</li>
<li>Licence: <span class="fig">18 of 20</span> judged. All pass. 82&ndash;100%.</li>
<li>Pack: <span class="fig">3 of 20</span> judged. Too few for a rate.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale navy">
<h2><span class="n">14 &middot; re-read</span> Machine re-read. Narrow reach.</h2>
<ul>
<li>Register: <span class="fig">20 of 20</span> equal.</li>
<li>Prices: <span class="fig">{ABOUT["comparisons"]}</span> comparisons, <span class="fig">88</span> page reads. No difference.</li>
<li>Same channels as the scrapers. One shop refused its endpoint.</li>
<li>Proves no drift. Not parser correctness. Not a human check.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid red" id="freeze">
<h2><span class="n">15 &middot; freeze</span> Then frozen.</h2>
<ul>
<li>Nightly run = standing promise. Unwatched free tier: stale, unnamed.</li>
<li>12&ndash;15 Nov: <span class="fig">5 to 42</span> changes a night, against <span class="fig">{ABOUT["listings"]:,}</span>.</li>
<li>Stopped 16 Nov 2026. Newest price 15 Nov. Schedule off.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale red">
<h2><span class="n">16 &middot; export</span> Export before switch-off.</h2>
<ul>
<li><span class="fig">{ABOUT["exported_tables"]}</span> tables, <span class="fig">{ABOUT["exported_rows"]:,}</span> rows.</li>
<li><span class="tool">PostgreSQL</span> dump. CSV per table. Written schema record. Manifest: one checksum per file.</li>
<li>Published twice: a release on the code repository, a dataset on <span class="tool">Hugging Face</span>. Both checked against the manifest on every push.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid gold">
<h2><span class="n">17 &middot; restore</span> Restore. Then trust the archive.</h2>
<ul>
<li>Every push: empty <span class="tool">PostgreSQL 17</span>, restore, compare manifest. <span class="fig">{ABOUT["restore_checks"]}</span> checks.</li>
<li><span class="fig">{ABOUT["products"]:,}</span> embeddings return as 384-dim vectors.</li>
<li><span class="tool">Docker</span>, then the restore check. Throwaway database.</li>
<li>Proves the archive works. Not parser correctness. That is 13.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale gold" id="decisions">
<h2><span class="n">18 &middot; decisions</span> Decisions. Each with its cost.</h2>
<div class="tablewrap" role="region" aria-label="Decisions and their costs" tabindex="0">
<table>
<caption>One decision per row.</caption>
<thead><tr><th scope="col">Decision</th><th scope="col">Chosen</th><th scope="col">Cost</th></tr></thead>
<tbody>
<tr><th scope="row">Scheduler</th><td>GitHub Actions cron, not Prefect</td><td>Free and unlimited on a public
repository. No retry engine. No run history beyond the workflow page.</td></tr>
<tr><th scope="row">Database</th><td>Neon, not Supabase</td><td>The free tier does not pause after idle
days. It does suspend on inactivity &mdash; hence the export.</td></tr>
<tr><th scope="row">MedPlus coverage</th><td>A full sweep every night, not a rotating window</td><td>About
68 minutes a night. The whole catalogue, not a quarter.</td></tr>
<tr><th scope="row">What a comparison means</th><td>Two pharmacies publishing a price for the same
product</td><td>Unconfirmed stock still counts. A caveat on the page, not a narrower count.</td></tr>
<tr><th scope="row">Inactive licences</th><td>Labelled, not hidden</td><td>The finding stays visible, and
so does the reading it rests on.</td></tr>
<tr><th scope="row">What was not built</th><td>No warehouse layer, no ORM, no API</td><td>SQL files and
scripts. A rebuild means running them in order.</td></tr>
</tbody>
</table>
</div>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step solid navy" id="limits">
<h2><span class="n">19 &middot; limits</span> What it does not claim.</h2>
<ul>
<li>Not a market index. Not a national price survey. Lagos, three online pharmacies,
<span class="fig">{ABOUT["priced"]}</span> medicines carrying a price at freeze.</li>
<li>Register status readable for <span class="fig">{ABOUT["coverage"]}%</span>. A flagged listing: a
fraction of a fraction.</li>
<li>A lapsed licence is not a fake drug. Nothing was bought, tested or inspected.</li>
<li>Supplements and pharmacy sundries are in the price data. They are not medicines.</li>
<li>One unit price is per millilitre: a 100 ml syrup. The rest are per tablet. The unit is printed beside
every unit price.</li>
<li><span class="fig">{ABOUT["comparisons"]}</span> comparisons rest on a machine re-read and a small
recorded human sample. Not a complete human audit.</li>
<li>Nothing is deployed. A repository, a dated export, generated pages. Not a live service.</li>
<li><span class="tool">Streamlit</span> dashboard: built, never deployed. Unused.</li>
</ul>
</div>
<div class="arrow" aria-hidden="true"></div>

<div class="step pale navy" id="reproduce">
<h2><span class="n">20 &middot; rebuild</span> Rebuild it yourself.</h2>
<ol>
<li>Pinned <span class="tool">Python</span>. Not the system interpreter.</li>
<li>Schema in numbered order: 001 to 008.</li>
<li>Then: seed, collect listings, link registrations, match products, build the pages.</li>
<li><span class="tool">Docker</span> running, then the restore check. Throwaway PostgreSQL 17, removed after.</li>
</ol>
</div>

</div>
</div>
</main>
<footer>
<p><strong>Independence and licence.</strong> Not endorsed by NAFDAC and not affiliated with, or paid by,
any pharmacy named in the data. Code MIT; data CC-BY-4.0. The medicine list descends from #FixMedPrices,
CC-BY-4.0, credited as its licence requires. Source and issue tracker:
{link(REPO_URL, "github.com/batestguy/NaijaDrugWatch")}.</p>
<p class="credit"><a href="{PHOTO_FILE_PAGE}">Photograph: Tolatheart, CC BY-SA 4.0, via Wikimedia
Commons.</a></p>
<p>This page is one HTML file and one local photograph, both in this directory. No external stylesheet,
script, font or image is fetched, so it works with no network. It is generated from the database, and the
figures above that a query can answer are checked against the database again on every build.</p>
</footer>
</div>
</body>
</html>
"""
    portrait = CREDIT_PORTRAIT
    monument = CREDIT_MONUMENT


class Page:
    """Renders the document and records which facts it actually printed."""

    def __init__(self, facts: dict[str, Any], dates: str,
                 published: dict[str, Any] | None = None) -> None:
        self.facts = facts
        self.dates = dates
        self.published = published
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

        if FROZEN:
            # The range is queried, not typed: the days come out of `collection_range`, which the
            # audit re-reads and compares at zero tolerance. The second sentence is the owner's,
            # word for word.
            span = self.f("collection_range")
            collected = human_range(span["first_day_lagos"], span["last_day_lagos"])
            stamp = (
                f'<p class="stamp">Collected {esc(collected)}. '
                f'Collection stopped on {esc(human_date(FROZEN["frozen_on"]))}.</p>'
            )
            health_note = (
                f' Because collection stopped on {esc(human_date(FROZEN["frozen_on"]))}, every age '
                'below is measured to that moment, not to the day you are reading this.'
            )
            age_header = "Age at freeze"
            masthead_line = "Three online pharmacies checked against one national register."
        else:
            stamp = (
                f'<p class="stamp">Read from the database at {esc(overview["database_now_utc"])} '
                f'({esc(overview["lagos_today"])} in Lagos). The newest price on the page was recorded '
                f'at {esc(overview["newest_scrape_utc"])} ({esc(overview["lagos_newest_date"])} in '
                f'Lagos), which is {hours_text} before the page was built.</p>'
            )
            health_note = ""
            age_header = "Age"
            masthead_line = (
                f'Lagos. Read from the database on {esc(overview["lagos_today"])}; the newest price was '
                f'recorded on {esc(human_date(str(overview["lagos_newest_date"])))}.'
            )

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

        # The finding under the headline. Every number in it is a fact the audit re-reads; none is
        # written here. The shape is a receipt, not a dashboard: one figure carries the claim, and the
        # small line beneath is the arithmetic that makes it checkable, in the order the work happened.
        # 298 + 154 + 46 = 498, and 498 + 61 (the matched rows that carry no licence number) = 559, so
        # the receipt closes. The figure is taken from the flagged set rather than typed.
        checkable = reg["matched_active"] + reg["matched_flagged"] + reg["matched_status_not_read"]
        finding = f"""<div class="finding" id="finding">
        <p class="n">{reg["matched_flagged"]:,}</p>
        <p class="k">of the {checkable:,} prices we could trace to a licence record sit on a
        registration that is <strong>not active</strong>.</p>
        <p class="chain">
        <span class="st d1"><b>{overview["latest_listings"]:,}</b><i>prices read</i></span>
        <span class="arw d2">&rarr;</span>
        <span class="st d2"><b>{overview["matched_listings"]:,}</b><i>matched to a medicine</i></span>
        <span class="arw d3">&rarr;</span>
        <span class="st d3"><b>{checkable:,}</b><i>carry a licence</i></span>
        <span class="arw d4">&rarr;</span>
        <span class="st d4"><b>{reg["matched_flagged"]:,}</b><i>not active</i></span>
        </p>
        <p class="rest"><b>{reg["matched_active"]:,}</b> active, <b>{reg["matched_status_not_read"]:,}</b> never read,
        out of <b>{reg["registrations_total"]:,}</b> registrations in the register.</p>
        </div>"""

        dedication = dedication_caption_html()
        data_block = download_block(self.published)

        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What a medicine costs, and whether its licence is active - NaijaDrugWatch</title>
<link rel="icon" href="data:,">
<style>{FONT_CSS}
{CSS_ORANGE}{CURSOR_CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the content</a>

<header class="top">
  <div class="wrap">
    <div>
      <div class="brand">Naija<b>Drug</b>Watch</div>
      <p class="tagline">{masthead_line}</p>
    </div>
    <div class="mast-right">
      <nav class="mastnav" aria-label="Site">
        <ul class="sb-links">
          <li><a href="index.html" aria-current="page">The finding</a></li>
          <li><a href="dashboard.html">Every price</a></li>
          <li><a href="about.html">How this was made</a></li>
        </ul>
      </nav>
      <svg class="map" viewBox="0 0 100 82" role="img" aria-label="Outline of Nigeria">
      <path d="{NIGERIA_MAP_PATH}"/>
    </svg>
    </div>
  </div>
</header>

<nav class="quickidx" aria-label="Quick index">
  <div class="qi-inner">
    <ul class="qi-list">
      <li><a href="#finding"><span class="qi-t">The finding</span><span class="qi-d">the {reg['matched_flagged']:,} on this page</span></a></li>
      <li><a href="dashboard.html"><span class="qi-t">Every price</span><span class="qi-d">{overview['latest_listings']:,} prices, explorable</span></a></li>
      <li><a href="#get-the-data"><span class="qi-t">Get the data</span><span class="qi-d">the frozen vintage</span></a></li>
      <li><a href="about.html"><span class="qi-t">How this was made</span><span class="qi-d">the method and the limits</span></a></li>
    </ul>
  </div>
</nav>

<section class="hero" aria-label="What this page is about">
  <div class="hero-grid">
    <div class="hero-copy">
      <h1>What a medicine costs.</h1>
      <p class="deck">Whether its licence is active.</p>
      {finding}
      {stamp}
    </div>
    <figure class="hero-figure">
      <img src="assets/dora/{PORTRAIT_FILE}" width="480" height="600" alt="">
      <figcaption class="photocaption">{dedication}</figcaption>
    </figure>
  </div>
  <div class="hero-base" aria-hidden="true"><svg class="bleedword" viewBox="0 -134 1000 140" role="presentation" focusable="false"><path d="{REGISTER_WORD_PATH}"/></svg></div>
</section>

<main id="main">
<div class="wrap">

<div class="placeholder-row">
  <figure class="shot">
    <img src="assets/gifs/{GIF_FILE}" alt="The dashboard in use: the six figures, the funnel, then a medicine typed into the search box and its prices appearing - Amoxicillin at 29,540 naira with a 590 naira listing marked out of stock - and the full price table." width="880" height="514" loading="lazy">
    <figcaption>Every price, every licence, and any medicine you ask for.</figcaption>
  </figure>
</div>
{banner}
{data_block}
</div>

<div class="built">
  <div class="wrap">
    <div>
      <h2>How the numbers were produced</h2>
      <p>Collected nightly while the project ran, then frozen on
      {esc(human_date(FROZEN["frozen_on"])) if FROZEN else "the day this page was built"}. Stored in one
      relational database, published as a dated export, and read a second time on every build to prove
      that every figure above still comes from the data.</p>
    </div>
    <div>
      <ul class="tags">
        <li>PostgreSQL</li>
        <li>SQL views</li>
        <li>Python</li>
        <li>GitHub Actions</li>
        <li>Frozen vintage</li>
        <li>Open data</li>
      </ul>
      <div class="dashrow">
        <a class="dash" href="dashboard.html">Open the price dashboard</a>
        <a class="dash" href="about.html">How this was made</a>
      </div>
    </div>
  </div>
</div>
</main>

<script>
/* The quick index scrolls inside itself on a phone, and the label at the cut used to be sliced
   through the middle of a letter. The fade over the last 24 px of the strip says there is more.
   This is the only script on this page: it changes no text, no number and no layout. It only puts
   the fade on while the list has more to the right, and takes it off at the end of the list,
   where nothing is cut. */
(function(){{
  var strip=document.querySelector('.qi-inner');
  var list=document.querySelector('.qi-list');
  if(!strip||!list){{return;}}
  function update(){{
    var more=list.scrollWidth-list.clientWidth-list.scrollLeft>1;
    if(strip.classList.contains('qi-more')!==more){{strip.classList.toggle('qi-more',more);}}
  }}
  list.addEventListener('scroll',update,{{passive:true}});
  window.addEventListener('resize',update);
  window.addEventListener('load',update);
  update();
}})();
</script>
<footer>
  <div class="wrap">
    <p><strong>Licence.</strong> Prices from HealthPlus, MedPlus and Drugstore.ng, read from their public
    product pages. Licence status from the NAFDAC Greenbook. The medicine list descends from the
    #FixMedPrices catalogue, released CC-BY-4.0 and credited here as that licence requires. This page's
    data is CC-BY-4.0; its code is MIT.</p>
    <p><strong>Portrait.</strong>
    <a href="{esc(CREDIT_PORTRAIT['page'])}">{esc(CREDIT_PORTRAIT['title'])}</a> on Wikimedia Commons,
    credited to the {esc(CREDIT_PORTRAIT['author'])} and released under
    <a href="{esc(CREDIT_PORTRAIT['licence_url'])}">CC0 1.0</a>, a public domain dedication. That licence
    requires no attribution; it is given here anyway.</p>
    <p class="built-by">Built by <a href="https://github.com/batestguy">batestguy</a>. Source and issue
    tracker: <a href="https://github.com/batestguy/NaijaDrugWatch">github.com/batestguy/NaijaDrugWatch</a>.</p>
  </div>
</footer>
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
        dora_years()
    except UnsetDate as exc:
        print(str(exc), file=sys.stderr)
        return 3

    # The published-vintage record is read before the database is opened, so a record that cannot be
    # rendered from stops the build with the missing key named rather than halfway through a page.
    try:
        published = load_published_vintage()
    except PublishedRecordError as exc:
        print(f"published vintage: {exc}", file=sys.stderr)
        return 4

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

        try:
            facts = read_facts(conn)
            page = Page(facts, dates, published)
            document = page.build()
        except MissingRange as exc:
            print(str(exc), file=sys.stderr)
            print("nothing written: the page will not print a date it cannot derive.", file=sys.stderr)
            return 5

        checked, problems = audit(conn, facts, page.used)
        # The methods page states figures as prose, which the fact audit cannot see. These eleven queries
        # are the ones a query can answer; a stale number there fails the build like any other.
        problems += about_drift(conn)
        # The methods page quotes the landing page's own audit count, which cannot be known until the
        # audit has run - so it is a literal. Left unguarded it silently fell four behind when four
        # dates were added to this build; it is now checked against the count this build actually made.
        if checked != ABOUT["audit_numbers"]:
            problems.append(
                f"the methods page states {ABOUT['audit_numbers']:,} numbers checked; this build checked "
                f"{checked:,}. Set ABOUT['audit_numbers'] to {checked:,}."
            )

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
    about_bytes = about_page().encode("utf-8")
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
