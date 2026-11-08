"""NaijaDrugWatch dashboard.

Reads the five contract views over the pooled Neon connection. The rule this file exists to
enforce: a price quoted by ONE pharmacy in a state is not a comparison, so the two are never
shown in the same column as if they were the same claim.

Run locally:
    .venv\\Scripts\\streamlit.exe run dashboard/app.py

The connection string is read from DATABASE_URL_POOLED (preferred) or DATABASE_URL, or from
Streamlit secrets when deployed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import psycopg
import streamlit as st

st.set_page_config(page_title="NaijaDrugWatch", page_icon="💊", layout="wide")

# Streamlit renders captions as its body text colour at 60% opacity. Measured 2026-11-08 with
# axe-core 4.10.2: that blends #2f2d2b to #828180 on white, i.e. 3.88:1, against the 4.5:1 that
# WCAG 2.2 AA requires at this size (14px normal). Changing the colour alone does nothing visible,
# because the blend reproduces the same grey -- the opacity is the defect, not the colour.
#
# Both are therefore reset here, once, instead of at nine `st.caption` call sites. Full opacity on
# #2f2d2b measures ~12.6:1. Captions keep their smaller font size, which is what carries the
# hierarchy now that they are no longer faded.
st.markdown(
    """
    <style>
    [data-testid="stCaptionContainer"] {
        opacity: 1 !important;
        color: #2f2d2b !important;
    }
    [data-testid="stCaptionContainer"] p {
        color: #2f2d2b !important;
    }
    [data-testid="stCaptionContainer"] code {
        color: #2f2d2b !important;
        background-color: #e8e8e8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def connection_string() -> str:
    """Pooled host for the app; the direct host is for DDL and long loads."""
    try:
        secret = st.secrets.get("DATABASE_URL_POOLED") or st.secrets.get("DATABASE_URL")
        if secret:
            return str(secret)
    except Exception:  # no secrets.toml locally; env vars are the normal path
        pass
    url = os.environ.get("DATABASE_URL_POOLED") or os.environ.get("DATABASE_URL")
    if not url:
        st.error("No database connection configured (DATABASE_URL_POOLED / DATABASE_URL).")
        st.stop()
    return url


@st.cache_resource(show_spinner=False)
def _connection():
    """One connection per session. Opening eleven (one per query) cost ~40 s on first paint."""
    return psycopg.connect(connection_string(), autocommit=True)


def _live_connection():
    connection = _connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
        return connection
    except Exception:  # noqa: BLE001 - a dead socket must not blank the page
        try:
            connection.close()
        except Exception:
            pass
        _connection.clear()
        return _connection()


@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    connection = _live_connection()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [d.name for d in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=columns)


@st.cache_data(ttl=300, show_spinner=False)
def scalar(sql: str, params: tuple = ()):
    connection = _live_connection()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def naira(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"₦{float(value):,.0f}"


def naira_unit(value) -> str:
    """A cost per unit, or the word `unknown` -- never a number we cannot justify.

    `unit_price` is NULL where the pack size could not be parsed. Dividing the pack price by a
    size whose unit is missing would invent a per-unit figure, so there is deliberately no
    fallback to `price_ngn / pack_size` here. Two decimals because a per-tablet price is a
    fraction of a naira and rounding to whole naira would lose the ranking.
    """
    if value is None or pd.isna(value):
        return "unknown"
    return f"₦{float(value):,.2f}"


def cheapest_table(
    frame: pd.DataFrame, pharmacy_column: str, show_pharmacy_count: bool = False
) -> pd.DataFrame:
    """Display frame shared by the comparison and the single-pharmacy table.

    The two price columns say different things and the headers carry that: "Pack price" is what
    the pack costs, "Lowest known unit price" is the lowest cost per unit *among the rows whose
    pack size could be parsed*. It is not "best value" -- where the cheapest pack's size is
    unknown, a pricier, larger pack wins that ranking and the cheaper one is invisible. The
    `unknown` strings are the other half of that: they mark a claim we cannot make.

    `show_pharmacy_count` keeps the "Pharmacies" column on the comparison table only, where the
    count is what makes a comparison a comparison.
    """
    rows = frame.reset_index(drop=True)
    table = pd.DataFrame(
        {
            "Product": rows["canonical_name"],
            "State": rows["state"],
            pharmacy_column: rows["cheapest_pharmacy"],
            "Pack price": rows["cheapest_pack_price"].map(naira),
            "Cheapest pack per unit": rows["unit_price"].map(naira_unit),
            "Lowest known unit price": rows["best_unit_unit_price"].map(naira_unit),
            "Lowest unit price from": rows["best_unit_pharmacy"].map(
                lambda name: "unknown" if name is None or pd.isna(name) else name
            ),
        }
    )
    if show_pharmacy_count:
        table["Pharmacies"] = rows["pharmacy_count"]
    return table


# ------------------------------------------------------------------------------ header
st.title("NaijaDrugWatch")
st.caption(
    "NAFDAC registration status × live Nigerian pharmacy prices. "
    "Every figure below comes from the database, not from a document."
)

try:
    counts = {
        "listings": scalar("select count(*) from v_latest_listings"),
        "pharmacies": scalar("select count(distinct pharmacy_id) from v_latest_listings"),
        "registrations": scalar("select count(*) from nafdac_registrations"),
        "with_status": scalar("select count(*) from nafdac_registrations where status is not null"),
        "suspicious": scalar("select count(*) from v_suspicious_listings"),
        "comparisons": scalar(
            "select count(*) from v_cheapest_per_product_state where is_comparison"
        ),
    }
except Exception as exc:  # noqa: BLE001 - surface the real reason, never a blank page
    st.error(f"Database unavailable: {type(exc).__name__}: {exc}")
    st.stop()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Listings", f"{counts['listings']:,}")
col2.metric("Pharmacies", counts["pharmacies"])
col3.metric("Registrations", f"{counts['registrations']:,}")
col4.metric("Status scraped", f"{counts['with_status']:,}")
col5.metric("Suspicious listings", f"{counts['suspicious']:,}")

tabs = st.tabs(
    ["Price index", "Cheapest by state", "Suspicious registrations", "Pipeline health", "Limits"]
)

# ------------------------------------------------------------------------ price index
with tabs[0]:
    st.subheader("Daily price index")
    st.caption(
        "`mv_drug_price_index` — average, minimum and maximum price per day, product and state, "
        "refreshed by the pipeline. A high `pharmacy_count` means more than one shop is quoting it."
    )
    index = query(
        "select day, canonical_name, state, avg_price_ngn, min_price_ngn, max_price_ngn,"
        " pharmacy_count, stock_rate from mv_drug_price_index"
        " order by avg_price_ngn desc"
    )
    if index.empty:
        st.info("No rows yet. The materialised view is refreshed after prices are loaded.")
    else:
        products = sorted(index["canonical_name"].unique())
        chosen = st.multiselect("Filter by product", products, default=products[:10])
        shown = index[index["canonical_name"].isin(chosen)] if chosen else index
        st.dataframe(
            shown.rename(
                columns={
                    "day": "Day",
                    "canonical_name": "Product",
                    "state": "State",
                    "avg_price_ngn": "Average",
                    "min_price_ngn": "Minimum",
                    "max_price_ngn": "Maximum",
                    "pharmacy_count": "Pharmacies",
                    "stock_rate": "In stock",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(f"{len(shown):,} rows shown of {len(index):,}.")

# ------------------------------------------------------------------ cheapest per state
with tabs[1]:
    st.subheader("Cheapest per state")
    st.caption(
        "`v_cheapest_per_product_state`, split by `is_comparison`. Every row carries two answers: "
        "the lowest sticker price (`cheapest_pack_*`) and the lowest cost per unit among the rows "
        "whose pack size could be parsed (`best_unit_*`). The comparison table is a real "
        "comparison: two or more pharmacies quote the same product in that state. The "
        "single-pharmacy table below it is ONE pharmacy's price — a national price, not a "
        "comparison, and it is not labelled cheapest."
    )
    cheapest = query(
        "select canonical_name, state, cheapest_pharmacy, cheapest_pack_price, unit_price,"
        " best_unit_unit_price, best_unit_pharmacy, pharmacy_count, is_comparison"
        " from v_cheapest_per_product_state"
        " order by canonical_name, state, cheapest_pack_price"
    )
    if cheapest.empty:
        st.info("No matched listings yet, so no price can be attributed to a product.")
    else:
        comparable = cheapest[cheapest["is_comparison"]]
        single = cheapest[~cheapest["is_comparison"]]
        st.markdown(f"**Comparisons ({len(comparable)})**")
        if comparable.empty:
            st.warning(
                "None yet. A comparison needs two pharmacies quoting the same product in the "
                "same state; with one pharmacy every row is a single-shop price."
            )
        else:
            st.dataframe(
                cheapest_table(comparable, "Cheapest", show_pharmacy_count=True),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Cheapest in state means: lowest quoted price among the pharmacies we scrape "
                "for that product there — not among all pharmacies in Nigeria."
            )
        st.markdown(f"**Single-pharmacy prices ({len(single)})** — not a comparison")
        st.dataframe(
            cheapest_table(single, "Pharmacy"),
            width="stretch",
            hide_index=True,
        )
        known_unit = int(cheapest["best_unit_unit_price"].notna().sum())
        st.caption(
            f"{known_unit} of {len(cheapest)} cells shown have a known unit price "
            f"({int(comparable['best_unit_unit_price'].notna().sum())} of {len(comparable)} "
            f"comparisons, {int(single['best_unit_unit_price'].notna().sum())} of {len(single)} "
            f"single-pharmacy); the other {len(cheapest) - known_unit} show `unknown` because the "
            "pack size could not be read. Ranked only where pack size could be read; where the "
            "cheapest pack's size is unknown this is the lowest known price per unit, not "
            "necessarily the best value."
        )

# ------------------------------------------------------------------------ suspicious
with tabs[2]:
    st.subheader("Listings with no active registration")
    st.caption(
        "`v_suspicious_listings` — a listing whose matched NAFDAC registration is not Active, or "
        "has an expiry date in the past. `status` is only checked where we have scraped the "
        "registration's detail page; unknown status is excluded, never treated as suspicious."
    )
    suspicious = query(
        "select canonical_name, raw_title, pharmacy_name, state, price_ngn,"
        " registration_number, nafdac_status, expiry_date, suspicion_reason, url"
        " from v_suspicious_listings order by canonical_name, raw_title"
    )
    if suspicious.empty:
        st.info("No suspicious listings under the current matched set.")
    else:
        statuses = sorted(suspicious["nafdac_status"].dropna().unique())
        picked = st.multiselect("Status", statuses, default=statuses)
        shown = suspicious[suspicious["nafdac_status"].isin(picked)] if picked else suspicious
        st.dataframe(
            shown.rename(
                columns={
                    "canonical_name": "Matched product",
                    "raw_title": "Listing title",
                    "pharmacy_name": "Pharmacy",
                    "state": "State",
                    "price_ngn": "Price",
                    "registration_number": "NRN",
                    "nafdac_status": "Status",
                    "expiry_date": "Expiry",
                    "suspicion_reason": "Reason",
                    "url": "URL",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"{len(shown):,} of {len(suspicious):,}. This flags a product only when NO active "
            "registration was found among the candidates that passed the strength and form rules — "
            "it is not a statement that the medicine is counterfeit."
        )

# --------------------------------------------------------------------- pipeline health
with tabs[3]:
    st.subheader("Pipeline health")
    st.caption(
        "`v_pipeline_health` — a source is STALE after 48 hours without a successful run. A source "
        "that has never run at all does not appear here, which is a known blind spot."
    )
    health = query(
        "select source, last_success_at, hours_since_success, status from v_pipeline_health"
        " order by source"
    )
    if health.empty:
        st.warning("No scrape runs recorded yet.")
    else:
        st.dataframe(
            health.rename(
                columns={
                    "source": "Source",
                    "last_success_at": "Last success",
                    "hours_since_success": "Hours since",
                    "status": "Status",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        stale = health[health["status"] != "OK"]
        if not stale.empty:
            st.error(f"{len(stale)} source(s) STALE: {', '.join(stale['source'])}")
        else:
            st.success("All recorded sources have succeeded within 48 hours.")

    runs = query(
        "select source, status, record_count, started_at, finished_at, error_message"
        " from scrape_runs order by id desc limit 15"
    )
    st.markdown("**Last 15 runs**")
    st.dataframe(runs, width="stretch", hide_index=True)

# ------------------------------------------------------------------------------ limits
with tabs[4]:
    st.subheader("What this data does and does not claim")
    st.markdown(
        """
- **Coverage is partial.** NAFDAC status was scraped for the registrations behind the seeded
  catalogue, not for all 10,906 registrations. It is not national regulatory coverage.
- **Prices are from two pharmacies, both in Lagos.** "Cheapest" means cheapest among the
  pharmacies we scrape — not among all pharmacies in Nigeria.
- **A single-pharmacy row is not a comparison.** It is a national price shown per state because
  the schema is state-partitioned.
- **"Suspicious" is about registration status, not authenticity.** A product whose registration is
  expired or inactive is flagged; that is not evidence of counterfeiting.
- **Stock may be inferred.** HealthPlus reports availability per variant; MedPlus exposes no stock
  flag, so it is inferred from the product page and recorded as `stock_evidence`.
- **The regulatory source is fetched over plain HTTP** because `greenbook.nafdac.gov.ng` serves an
  expired TLS certificate (observed 2026-11-07). Archive integrity therefore rests on our own
  sha256 sidecars, not on transport.
- **MedPlus robots.txt** publishes Cloudflare content signals (`search=yes, ai-train=no,
  use=reference`). This project is reference use; embeddings are inference, not training.
        """
    )
    st.caption(
        "Data: NAFDAC Greenbook, HealthPlus, MedPlus. Catalogue seed: #FixMedPrices (CC-BY-4.0). "
        "Code MIT. Refreshed: " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )
