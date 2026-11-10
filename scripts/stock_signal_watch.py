#!/usr/bin/env python
"""Watch whether each pharmacy still tells us what is in stock, day over day.

Why this exists
---------------
`pharmacy_listings.in_stock` has three states, not two: ``true``, ``false``, and ``NULL``. ``NULL``
means "the reader found no stock signal on the page" -- it is *not* "not in stock"
(``scrapers/medplus.py:24-33``). That third state is the one that goes wrong quietly: when a shop
republishes its markup, name, price and pack still parse, so every row still lands, every
``scrape_runs`` row still says ``success``, and ``v_pipeline_health`` stays ``OK``. The only visible
trace is a column that has silently become unknown for every row of a source.

On 2026-11-09 that happened to MedPlus: 128 rows written, 128 of them ``in_stock = null``, against
0% the day before. Nothing complained. The price view lost 18 entries and two two-pharmacy
comparisons, and the next morning a person found it by eye. This script is the thing that complains.

The rule
--------
Per pharmacy, per UTC day: how many rows were written, and what share of them has ``in_stock``
``NULL``. Days with fewer than ``MIN_ROWS_PER_DAY`` rows are ignored -- a partial run (a sweep that
stopped early, or a source that holds only 20 products in a category) is a sample of the day, not a
statement about the reader, and letting one in would move the "latest day" backwards to a day that
was never finished.

A source is flagged when its *prior* days were mostly readable and its latest day is not:

    median(prior days) < 10% unknown   AND   latest day > 25% unknown

Both halves are needed. A source that has never reported stock (median 100% unknown) can only stay
as it is, so the rule cannot fire on HealthPlus just for being terse -- only a *loss* is an alarm.
The gap between 10% and 25% is a margin, not a measurement: 13 of MedPlus's 1,092 rows were unknown
on a good day (1.2%), so the tolerable baseline is single digits and a breach has to be an order of
magnitude worse to be worth waking someone.

Read-only. This script never scrapes, never writes to a table, and never touches ``scrape_runs`` --
it must not be able to make the day look run or unrun. It reads ``pharmacy_listings`` and
``pharmacies`` and nothing else.

Exit codes
----------
0  clean: no source lost its stock signal
1  flagged: at least one source went from readable to unknown
2  cannot decide: no database, or no pharmacy has two countable days to compare. The caller must
   treat this as "unknown", not as "ok" -- a watch that cannot see is not a watch that is happy.

Usage
-----
    python -X utf8 scripts/stock_signal_watch.py
    python -X utf8 scripts/stock_signal_watch.py --as-of 2026-11-08   # replay history as it stood
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import date

# A day with fewer rows than this is a partial observation, not a reading of the source's reader.
MIN_ROWS_PER_DAY = 50

# The two halves of the alarm. See the module docstring for why they are 10 and 25.
PRIOR_MEDIAN_MAX_UNKNOWN_PCT = 10.0
LATEST_UNKNOWN_ALARM_PCT = 25.0

# One aggregate over the whole table, grouped so one query answers every pharmacy and every day.
# `at time zone 'UTC'` rather than a bare `::date`: this must not silently change meaning if the
# server's timezone does. The table grows by a few thousand rows a day, so a grouped scan of it
# stays trivial for years.
DAILY_SQL = """
select ph.name as pharmacy,
       (l.scraped_at at time zone 'UTC')::date as day,
       count(*) as rows_written,
       count(*) filter (where l.in_stock is null) as rows_unknown
from pharmacy_listings l
join pharmacies ph on ph.id = l.pharmacy_id
group by 1, 2
order by 1, 2
"""


def load_daily(fetch) -> dict[str, list[dict]]:
    """Group the query result into ``{pharmacy: [{day, rows, unknown}, ...]}``, oldest first."""
    grouped: dict[str, list[dict]] = {}
    for pharmacy, day, rows_written, rows_unknown in fetch():
        grouped.setdefault(pharmacy, []).append(
            {"day": day, "rows": int(rows_written), "unknown": int(rows_unknown)}
        )
    for days in grouped.values():
        days.sort(key=lambda item: item["day"])
    return grouped


def unknown_pct(record: dict) -> float:
    if not record["rows"]:
        return 0.0
    return 100.0 * record["unknown"] / record["rows"]


def assess(days: list[dict], *, as_of: date | None = None) -> dict:
    """Decide one pharmacy. Pure: no database, no clock, so it can be replayed against history."""
    counted = [
        record
        for record in days
        if record["rows"] >= MIN_ROWS_PER_DAY and (as_of is None or record["day"] <= as_of)
    ]
    skipped = [record for record in days if record not in counted]

    result = {
        "counted": counted,
        "skipped": skipped,
        "latest": None,
        "prior_median_pct": None,
        "latest_pct": None,
        "verdict": "no-history",  # no-history | one-day | ok | alarm
    }
    if not counted:
        return result

    latest = counted[-1]
    prior = counted[:-1]
    result["latest"] = latest
    result["latest_pct"] = unknown_pct(latest)

    if not prior:
        # One countable day is a state, not a trend. Say so instead of guessing "ok".
        result["verdict"] = "one-day"
        return result

    result["prior_median_pct"] = statistics.median(unknown_pct(item) for item in prior)

    # The baseline is "this source used to tell us", i.e. at least one prior day below the clean
    # threshold -- NOT the median of prior days.
    #
    # Measured 2026-11-10 by feeding synthetic series to this function: with the median as the
    # baseline, a break that persisted silenced its own alarm. Three clean days then 100% unknown
    # alarmed on days 1, 2 and 3, and on day 4 the bad days became the majority of the prior window,
    # the median crossed 10%, and the verdict flipped to `ok` -- while the source was still broken.
    # A monitor whose alarm decays exactly when the fault becomes permanent is worse than none.
    #
    # With "has ever been clean" as the baseline, a permanent break alarms every day until a human
    # resolves it, and the notify job's one-issue-per-title dedup turns that into one issue with
    # comments rather than a new issue each night.
    clean_prior_days = [
        item for item in prior if unknown_pct(item) < PRIOR_MEDIAN_MAX_UNKNOWN_PCT
    ]
    result["clean_prior_days"] = len(clean_prior_days)
    if clean_prior_days and result["latest_pct"] > LATEST_UNKNOWN_ALARM_PCT:
        result["verdict"] = "alarm"
    else:
        result["verdict"] = "ok"
    return result


def note_for(record: dict, assessment: dict, as_of: date | None) -> str:
    if record["rows"] < MIN_ROWS_PER_DAY:
        return f"ignored: fewer than {MIN_ROWS_PER_DAY} rows"
    if as_of is not None and record["day"] > as_of:
        return f"ignored: after --as-of {as_of.isoformat()}"
    latest = assessment["latest"]
    # `latest` is None when no day is countable at all; then every record is in `skipped` and the
    # two branches above have already returned.
    if latest is not None and record["day"] == latest["day"]:
        return "latest ALARM" if assessment["verdict"] == "alarm" else "latest"
    return "prior"


def verdict_lines(name: str, assessment: dict) -> list[str]:
    verdict = assessment["verdict"]
    if verdict == "alarm":
        latest = assessment["latest"]
        return [
            f"ALARM: {name} went from {assessment['prior_median_pct']:.1f}% to "
            f"{assessment['latest_pct']:.1f}% unknown (day {latest['day'].isoformat()}, "
            f"{latest['rows']} rows written, {latest['unknown']} unknown)"
        ]
    if verdict in ("no-history", "one-day"):
        return [f"not judged: {name} has {len(assessment['counted'])} countable day(s)"]
    return []


def render_table(assessments: dict[str, dict], as_of: date | None) -> list[str]:
    header = f"{'pharmacy':<14} {'day':<11} {'rows':>6} {'unknown':>8} {'share':>7}  note"
    lines = [header, "-" * len(header)]
    for name, assessment in assessments.items():
        if not assessment["counted"] and not assessment["skipped"]:
            lines.append(f"{name:<14} {'-':<11} {0:>6} {0:>8} {'-':>7}  no rows at all")
            continue
        for record in assessment["counted"] + assessment["skipped"]:
            lines.append(
                f"{name:<14} {record['day'].isoformat():<11} {record['rows']:>6} "
                f"{record['unknown']:>8} {unknown_pct(record):>6.1f}%  "
                f"{note_for(record, assessment, as_of)}"
            )
        if assessment["prior_median_pct"] is not None:
            lines.append(
                f"{'':<14} {'':<11} prior median unknown {assessment['prior_median_pct']:.1f}%"
            )
    return lines


def render_markdown(assessments: dict[str, dict], verdicts: list[str]) -> str:
    lines = [
        "### Stock signal watch",
        "",
        "| pharmacy | day | rows | unknown | share | note |",
        "|---|---|---:|---:|---:|---|",
    ]
    for name, assessment in assessments.items():
        if not assessment["counted"] and not assessment["skipped"]:
            lines.append(f"| {name} | - | 0 | 0 | - | no rows at all |")
            continue
        for record in assessment["counted"] + assessment["skipped"]:
            lines.append(
                f"| {name} | {record['day'].isoformat()} | {record['rows']} | "
                f"{record['unknown']} | {unknown_pct(record):.1f}% | "
                f"{note_for(record, assessment, None)} |"
            )
    lines += ["", "```", *verdicts, "```", ""]
    return "\n".join(lines)


def write_summary(text: str) -> None:
    """Append to the Actions run page. Absent locally, and that is not a failure."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError as exc:  # noqa: BLE001 -- a run page is nice to have, not part of the decision
        print(f"note: could not write GITHUB_STEP_SUMMARY ({exc})")


def emit_outputs(signal: str, detail: str) -> None:
    print(f"stock_signal={signal}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"signal={signal}\n")
            handle.write(f"detail={detail.replace(chr(10), ' ')}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="judge history as it stood at the end of this UTC day (for replaying the 2026-11-09 "
        "event and for demonstrating the clean branch)",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=10,
        help="seconds to wait for the database before giving up (default 10)",
    )
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else None

    # Reuse the gate's connection-string tolerance and its password-free description rather than
    # growing a second, subtly different copy of the same handling.
    try:
        from freshness_gate import describe, normalise_url
    except Exception as exc:  # noqa: BLE001 -- cannot read the environment safely without them
        print(f"::error title=stock watch::cannot import freshness_gate: {exc}", file=sys.stderr)
        return 2

    raw = os.environ.get("DATABASE_URL", "")
    url = normalise_url(raw)
    if not url:
        print(
            "::error title=stock watch::DATABASE_URL is empty or unset, so no source can be "
            "checked. Refusing to report ok.",
            file=sys.stderr,
        )
        emit_outputs("undecided", "DATABASE_URL is empty or unset")
        return 2

    try:
        import psycopg
    except Exception as exc:  # noqa: BLE001 -- any import failure means nobody can decide
        print(f"::error title=stock watch::psycopg is not importable: {exc}", file=sys.stderr)
        emit_outputs("undecided", f"psycopg is not importable: {exc}")
        return 2

    where = describe(url)
    try:
        with psycopg.connect(
            url,
            autocommit=True,
            connect_timeout=args.connect_timeout,
            # Read-only is enforced by the server, not by us remembering: a write from this
            # connection raises ReadOnlySqlTransaction.
            #
            # `conn.read_only = True` after connecting does NOT do that in autocommit mode. Measured
            # 2026-11-10 against the live database: with autocommit plus the attribute set, both
            # `update pharmacy_listings ...` and `delete from pharmacy_listings ...` succeeded. The
            # session default below does block them, so that is what this uses.
            options="-c default_transaction_read_only=on",
        ) as conn:
            conn.execute("set statement_timeout = '30s'")
            daily = load_daily(lambda: conn.execute(DAILY_SQL).fetchall())
    except Exception as exc:  # noqa: BLE001 -- unreachable DB, bad credentials, broken query
        message = f"{type(exc).__name__}: {exc}"
        import urllib.parse

        password = urllib.parse.urlsplit(url).password
        if password:  # belt and braces: no conninfo password reaches a log
            message = message.replace(password, "***")
        print(
            f"::error title=stock watch::cannot read the database ({where}): {message}. "
            "Reporting undecided rather than ok.",
            file=sys.stderr,
        )
        emit_outputs("undecided", f"database unreachable ({where}): {message}")
        return 2

    if not daily:
        print("cannot decide: pharmacy_listings holds no rows")
        emit_outputs("undecided", "pharmacy_listings holds no rows")
        return 2

    assessments = {name: assess(days, as_of=as_of) for name, days in daily.items()}
    if as_of is not None:
        print(f"# judging history as it stood at the end of {as_of.isoformat()}\n")

    table = render_table(assessments, as_of)
    for line in table:
        print(line)
    print()

    alarms = [name for name, a in assessments.items() if a["verdict"] == "alarm"]
    judged = [name for name, a in assessments.items() if a["verdict"] in ("ok", "alarm")]

    if alarms:
        verdicts = []
        for name in alarms:
            verdicts += verdict_lines(name, assessments[name])
        for name, a in assessments.items():
            if a["verdict"] in ("ok", "no-history", "one-day"):
                verdicts += [
                    f"{name}: {a['verdict'].replace('-', ' ')}"
                    + (
                        f" (prior median {a['prior_median_pct']:.1f}%, latest "
                        f"{a['latest_pct']:.1f}%)"
                        if a["verdict"] == "ok"
                        else ""
                    )
                ]
        for line in verdicts:
            print(line)
        for name in alarms:
            print(f"::warning title=stock signal::{' '.join(verdict_lines(name, assessments[name]))}")
        write_summary(render_markdown(assessments, verdicts))
        emit_outputs("alarm", " | ".join(verdicts))
        return 1

    if not judged:
        line = (
            "cannot decide: no pharmacy has two countable days "
            f"(>= {MIN_ROWS_PER_DAY} rows) to compare"
        )
        print(line)
        write_summary(render_markdown(assessments, [line]))
        emit_outputs("undecided", line)
        return 2

    line = "ok: no source lost its stock signal"
    print(line)
    verdicts = [line]
    for name, a in assessments.items():
        if a["verdict"] == "ok":
            verdicts.append(
                f"{name}: prior median {a['prior_median_pct']:.1f}% unknown, latest day "
                f"{a['latest']['day'].isoformat()} {a['latest_pct']:.1f}%"
            )
        else:
            verdicts.append(f"{name}: not judged ({a['verdict'].replace('-', ' ')})")
    write_summary(render_markdown(assessments, verdicts))
    emit_outputs("ok", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
