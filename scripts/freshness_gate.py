#!/usr/bin/env python
"""Decide whether the day's pipeline run has already happened, from ``scrape_runs`` alone.

Why this exists
---------------
GitHub's ``schedule`` trigger is best-effort. GitHub documents that scheduled runs "can be delayed
during periods of high loads" and that "if the load is sufficiently high enough, some queued jobs
may be dropped" -- and a dropped run produces no run, no log and no notification. This repo had
zero ``schedule`` events in the first 26 h after ``daily.yml`` landed (PROGRESS.md, 2026-11-09), so
the daily pipeline must not depend on one fire arriving. ``daily.yml`` therefore fires three times a
day and this gate sits in front of the pipeline: the first fire that finds the day unrun runs it,
every later fire exits in well under a minute without scraping anything.

Why ``scrape_runs`` and not ``v_pipeline_health``
------------------------------------------------
The view groups ``scrape_runs`` per source, so a source that has never run produces *no row at all*
-- not ``STALE``. It cannot be asked "did anything succeed today?" without answering "nothing is
wrong" for a pipeline that never ran. This reads the table directly.

The rule, and why it is not "within N hours"
--------------------------------------------
The pipeline is expected to run once per UTC day, opened by the 03:00 UTC fire. The day counts as
run when **every** source in ``REQUIRED_SOURCES`` has a successful ``scrape_runs`` row that
finished at or after the most recent gate window (03:00 UTC).

"Any success" is not enough, and accepting it was a defect fixed on 2026-11-09: the Greenbook index
finishes 3-5 minutes into a 1.5 h pipeline, so a night where the index succeeded and everything
after it died used to grade *fresh* -- the 04:17 and 06:43 fires then skipped, and four of the five
sources sat a day old while the gate reported green.

An age threshold cannot express the window: a 26 h window reports *fresh* at 04:17 for a run that
finished at 04:50 the previous day -- 23.5 h old, and exactly the dropped 03:00 fire this gate
exists to catch. 20 h fails the other way once a run takes 5 h (the job cap): 03:00+5 h finished
08:00, so 03:00 the next day is 19 h old and the day would be skipped. The window is a calendar
question, so it is computed from the calendar.

``missed`` is a separate, stricter question: has a whole UTC day passed with no successful run by
*any* source? The 03:00 fire of a normal day *reads* as stale -- a new day has started and nothing
has run in it yet -- so "stale" alone must never be reported as a miss, or every day would open an
issue.

Read-only. This script never scrapes and never writes to the database.

Exit codes
----------
0  decided (``fresh``, ``stale`` or ``forced``); the decision is written to ``GITHUB_OUTPUT``
2  could not decide -- database unreachable, credentials rejected, or the query failed. The job
   must go red rather than guess "stale" (scraping on top of an unknown state) or "fresh" (green
   while nothing is known).
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

# The primary fire is 03:00 UTC. Every gate window boundary is this hour.
GATE_WINDOW_UTC_HOUR = 3

# Informational only -- printed so the report can say how old the data is. It is deliberately NOT
# the decision; see the module docstring.
DIAGNOSTIC_HOURS = 26

# The sources whose success makes a day "run": exactly the steps `.github/workflows/daily.yml` runs,
# in its order, plus the matcher. `match_listings` is here because a night that scrapes every source
# and then fails at matching leaves `v_latest_listings` and every view a day old -- the same state as
# a night that never scraped, and the state that is indistinguishable from a quiet market.
#
# WHEN YOU ADD A SOURCE TO daily.yml, ADD ITS `scrape_runs.source` VALUE HERE. A source missing from
# this tuple is a source nobody waits for, so the day grades fresh without it. The string must be the
# exact value the script passes to `common.start_run` -- a typo makes the gate permanently stale,
# because no row will ever match.
#
# A source that is NOT in this tuple is ignored, never required: a one-off backfill or a new
# candidate source can write all the ledger rows it likes without changing the decision.
REQUIRED_SOURCES: tuple[str, ...] = (
    "nafdac_greenbook",  # scrapers/nafdac_index.py
    "nafdac_details",  # scrapers/nafdac_details.py
    "healthplus",  # scrapers/healthplus.py
    "medplus",  # scrapers/medplus.py
    "drugstore",  # scrapers/drugstore.py
    "match_listings",  # scripts/match_listings.py
)

# One aggregate, grouped by source, so a single query answers both questions: per-source freshness
# (the decision) and the latest success by anyone (the `missed` trigger and the age in the report).
# `scrape_runs` grows by ~10 rows a day; a grouped aggregate over it stays trivial for years.
LAST_SUCCESS_SQL = """
select source, max(coalesce(finished_at, started_at)) as last_success
from scrape_runs
where status = 'success'
group by source
"""


def normalise_url(raw: str) -> str:
    """Strip a pasted "DATABASE_URL=" key name and wrapping quotes.

    The Preflight step in daily.yml does the same thing for the pipeline; the gate runs before it
    and receives the raw secret, so it needs the same tolerance or it fails where the pipeline
    would not.
    """
    value = (raw or "").strip()
    for prefix in ("DATABASE_URL=", "database_url="):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.strip().strip('"').strip("'").strip()


def describe(url: str) -> str:
    """host and database name only. The password never reaches a log."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "<no host>"
    dbname = (parts.path or "").lstrip("/") or "<no dbname>"
    return f"host={host} db={dbname}"


def window_start(now: datetime, hour: int = GATE_WINDOW_UTC_HOUR) -> datetime:
    """The most recent ``hour:00`` UTC at or before ``now``."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate > now:
        candidate -= timedelta(days=1)
    return candidate


def query_last_success(conn) -> dict[str, datetime]:
    """Latest finish time of a successful run, per source. A source absent from the mapping has
    never succeeded."""
    rows = conn.execute(LAST_SUCCESS_SQL).fetchall()
    return {row[0]: row[1] for row in rows if row[1] is not None}


def evaluate(
    fetch,
    *,
    now: datetime,
    window_hour: int = GATE_WINDOW_UTC_HOUR,
    forced: bool = False,
) -> dict:
    """Turn "when did each source last succeed" into a decision. No database access here.

    ``fetch`` is a zero-argument callable returning a ``{source: datetime}`` mapping, which is what
    makes the decision testable against stubbed states.
    """
    start = window_start(now, window_hour)
    observed = {
        source: (last if last.tzinfo else last.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        for source, last in (fetch() or {}).items()
        if last is not None
    }

    last = max(observed.values()) if observed else None

    # A required source is satisfied only by a success that finished inside THIS window. "Yesterday
    # at 10:15" is a day old, which is the whole point of the gate.
    missing = [s for s in REQUIRED_SOURCES if observed.get(s) is None or observed[s] < start]
    fresh = not missing

    # A whole UTC day with no successful run by anyone. The boundary is the start of yesterday's UTC
    # day, not yesterday's gate window: a fire that arrived late and finished at 02:40 yesterday did
    # serve yesterday, so it counts.
    yesterday_utc = start - timedelta(days=1)
    yesterday_start = yesterday_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    missed = last is None or last < yesterday_start

    if forced:
        decision, run = "forced", True
    elif fresh:
        decision, run = "fresh", False
    else:
        decision, run = "stale", True

    age_hours = None if last is None else round((now - last).total_seconds() / 3600.0, 2)
    return {
        "decision": decision,
        "run": run,
        "missed": missed,
        "last_success": last,
        "age_hours": age_hours,
        "window_start": start,
        "today": now.date().isoformat(),
        "missing_sources": missing,
        "required_sources": list(REQUIRED_SOURCES),
    }


def render(result: dict) -> str:
    last = result["last_success"]
    last_s = "never" if last is None else last.strftime("%Y-%m-%dT%H:%M:%SZ")
    age = "n/a" if result["age_hours"] is None else f"{result['age_hours']} h"
    required = result["required_sources"]
    missing = result["missing_sources"]
    if missing:
        tail = (
            f"{len(missing)} of {len(required)} required sources have no success inside the window: "
            + ", ".join(missing)
        )
    else:
        tail = f"all {len(required)} required sources succeeded inside the window"
    return (
        f"decision={result['decision']} run={str(result['run']).lower()} "
        f"missed={str(result['missed']).lower()} | last successful run {last_s} ({age} ago, "
        f"diagnostic window {DIAGNOSTIC_HOURS} h) | gate window opened "
        f"{result['window_start'].strftime('%Y-%m-%dT%H:%M:%SZ')} | {tail}"
    )


def emit_outputs(result: dict, summary: str) -> None:
    values = {
        "decision": result["decision"],
        "run": "true" if result["run"] else "false",
        "missed": "true" if result["missed"] else "false",
        "last_success": (
            "never"
            if result["last_success"] is None
            else result["last_success"].strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
        "age_hours": "" if result["age_hours"] is None else str(result["age_hours"]),
        "missing_sources": ",".join(result["missing_sources"]),
        "reason": summary.replace("\n", " "),
    }
    for key, value in values.items():
        print(f"{key}={value}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--event",
        default=os.environ.get("GITHUB_EVENT_NAME", "schedule"),
        help="the event that started the run; anything other than 'schedule' forces a run",
    )
    parser.add_argument(
        "--window-hour",
        type=int,
        default=GATE_WINDOW_UTC_HOUR,
        help=f"UTC hour that opens the day's window (default {GATE_WINDOW_UTC_HOUR}, the 03:00 fire)",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="ISO-8601 timestamp to evaluate against instead of the wall clock (for testing)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=10,
        help="seconds to wait for the database before failing the job (default 10)",
    )
    args = parser.parse_args(argv)

    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    raw = os.environ.get("DATABASE_URL", "")
    url = normalise_url(raw)
    if not url:
        print(
            "::error title=freshness gate::DATABASE_URL is empty or unset, so the gate cannot ask "
            "the database whether the day has run. Refusing to guess.",
            file=sys.stderr,
        )
        return 2

    try:
        import psycopg
    except Exception as exc:  # noqa: BLE001 -- any import failure means nobody can decide
        print(f"::error title=freshness gate::psycopg is not importable: {exc}", file=sys.stderr)
        return 2

    where = describe(url)
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=args.connect_timeout) as conn:
            conn.execute("set statement_timeout = '20s'")
            result = evaluate(
                lambda: query_last_success(conn),
                now=now,
                window_hour=args.window_hour,
                forced=args.event != "schedule",
            )
    except Exception as exc:  # noqa: BLE001 -- unreachable DB, bad credentials, broken query
        message = f"{type(exc).__name__}: {exc}"
        password = urllib.parse.urlsplit(url).password
        if password:  # belt and braces: no conninfo password reaches a log
            message = message.replace(password, "***")
        print(
            f"::error title=freshness gate::cannot reach or read the database ({where}): "
            f"{message}. The job fails rather than run the pipeline against an "
            "unknown state or report it green.",
            file=sys.stderr,
        )
        return 2

    summary = render(result)
    print(summary)
    emit_outputs(result, summary)

    if result["missed"]:
        print(
            "::warning title=missed day::a whole UTC day passed with no successful run - "
            + summary,
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
