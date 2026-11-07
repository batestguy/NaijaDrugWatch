#!/usr/bin/env python3
"""NAFDAC Greenbook detail scraper: status, approval date and expiry per registration.

Stage P3. `nafdac_index.py` gives the registration list; this file adds the lifecycle. Both fields
are stored twice on purpose:

    nafdac_registrations.status/expiry_date  current value, convenient for joins
    nafdac_status_snapshots                  one row per registration per day, append-only

Status history is the product, so the snapshot ledger is written even when nothing changed. A
registration is never updated in place to erase history.

SCOPE IS A FLAG, NOT AN ARCHITECTURE
------------------------------------
    --min-similarity 0.40   (default) only NRNs whose name resembles a seeded product
    --all                   every registration with a detail URL (the full sweep)

The restricted pass is deliberate: no view can consume an NRN that no product can match, so
scraping status for all 10,906 costs hours to change nothing on screen. Raise or drop the flag for
a full sweep -- this is the same file, not a second scraper.

Measured 2026-11-07: the server takes ~2.5 s per page on top of the mandatory 2 s floor, so the real
rate is ~0.22 pages/s, NOT 0.5. Budget accordingly: ~2,800 NRNs at 0.30 is ~3.5 h, 1,474 at 0.40 is
~110 min, 576 at 0.50 is ~45 min, and the full 10,906 is ~14 h -- which is why the full sweep must
be sharded across days, not run in one job.

RESUMABILITY
------------
An NRN that already has a snapshot for today is skipped, so an interrupted run resumes by simply
being run again, and a retry never restarts a range. A 500 is retried with backoff and, if it still
fails, is left unsnapshotted so the next run picks it up.

Commits are batched (`--commit-every`, default 50) and the connection is re-established once if the
database drops the socket. Without that, a single Neon disconnect mid-run rolled back every page
fetched in that transaction -- which happened on 2026-11-07 at 50/1,464 and lost the lot.

A partial sweep is a partial vintage. Never describe its output as national regulatory coverage.

Usage
-----
    python scrapers/nafdac_details.py --dry-run --limit 5
    python scrapers/nafdac_details.py                 # restricted scope, ~50 min
    python scrapers/nafdac_details.py --all           # full sweep, shard to stay under 6 h
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import threading
import time
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# Importable both as `python scrapers/nafdac_details.py` and as `python -m scrapers.nafdac_details`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    RateLimitedClient,
    archive_jsonl,
    db_connect,
    finish_run,
    start_run,
)

SOURCE = "nafdac_details"
DEFAULT_MIN_SIMILARITY = 0.40
DEFAULT_MAX_SECONDS = 5.5 * 3600  # stay under the 6 h job cap with room to write the ledger
BACKOFF_SECONDS = (5, 15, 45)
# urllib's timeout bounds each socket read, not the whole request, so a server that trickles
# bytes can hold a fetch open indefinitely -- which is exactly how the 2026-11-07 run hung for
# 22 minutes at 150/571 with no database writes. A wall-clock deadline in a worker thread bounds
# the request itself; the abandoned thread is a daemon and dies with the process.
HARD_TIMEOUT_S = 30

# Each field is an <h1 class="... bg-gray-200 ...">label</h1> followed by a <p ... text-justify>value</p>.
PAIR_RE = re.compile(
    r'<h1[^>]*class="[^"]*bg-gray-200[^"]*"[^>]*>\s*(.*?)\s*</h1>'
    r'\s*<p[^>]*class="[^"]*text-justify[^"]*"[^>]*>\s*(.*?)\s*</p>',
    re.S,
)
TAG_RE = re.compile(r"<[^>]+>")

LABELS = {
    "nrn": "registration_number",
    "status": "status",
    "approval date": "approval_date",
    "expiry date": "expiry_date",
    "packsize": "pack_description",
    "pack size": "pack_description",
    "product category": "product_category",
    "applicant name": "applicant",
}

UPDATE_SQL = """
update nafdac_registrations
set status            = coalesce(%(status)s, status),
    approval_date     = coalesce(%(approval_date)s, approval_date),
    expiry_date       = coalesce(%(expiry_date)s, expiry_date),
    pack_description  = coalesce(%(pack_description)s, pack_description),
    product_category  = coalesce(%(product_category)s, product_category),
    applicant         = coalesce(%(applicant)s, applicant),
    scraped_at        = now()
where registration_number = %(registration_number)s
"""

SNAPSHOT_SQL = """
insert into nafdac_status_snapshots (registration_number, status, expiry_date, snapshot_date, observed_at)
values (%(registration_number)s, %(status)s, %(expiry_date)s, current_date, now())
on conflict (registration_number, snapshot_date) do update
set status = excluded.status,
    expiry_date = excluded.expiry_date,
    observed_at = excluded.observed_at
"""


# ------------------------------------------------------------------------------------ parsing


def clean(value: str) -> str:
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str) -> str | None:
    """ISO date as published, or None. Anything unparseable is dropped rather than guessed."""
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def parse_detail(body: str) -> dict[str, Any]:
    """Label/value pairs from one detail page, mapped onto column names."""
    found: dict[str, Any] = {}
    for raw_label, raw_value in PAIR_RE.findall(body):
        column = LABELS.get(clean(raw_label).lower())
        if column is None:
            continue
        value = clean(raw_value)
        if column == "registration_number":
            found[column] = value or None
        elif column in {"approval_date", "expiry_date"}:
            found[column] = parse_date(value)
        else:
            found[column] = value or None
    return found


# ------------------------------------------------------------------------------------ fetching


class DetailUnavailable(RuntimeError):
    """The page could not be read after retries. Left unsnapshotted so a later run retries it."""


def _with_deadline(callable_, seconds: float):
    """Run `callable_` in a daemon thread and abandon it if it exceeds a wall-clock deadline.

    Needed because `urllib`'s timeout is per socket operation: a server sending one byte at a
    time never trips it. On timeout the thread is left to die with the process.
    """
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["value"] = callable_()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"no response within {seconds:.0f}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def fetch_detail(client: RateLimitedClient, url: str, *, retries: int = 2) -> str:
    """GET a detail page, retrying 5xx and transport errors with backoff.

    Two retries, not three: with a 30 s hard deadline each, a permanently broken page must not
    cost six minutes of a sweep that has an hour of budget.
    """
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body, _final = _with_deadline(lambda: client.get(url), HARD_TIMEOUT_S)
            return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500:
                raise DetailUnavailable(f"HTTP {exc.code} (not retryable)") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise DetailUnavailable(f"{type(last_error).__name__}: {last_error}")


# ------------------------------------------------------------------------------------ database


def select_scope(connection, *, min_similarity: float | None, limit: int | None) -> list[tuple[str, str]]:
    """NRNs still without a snapshot today, optionally restricted to product-like names."""
    clauses = [
        "r.source_url is not null",
        "not exists (select 1 from nafdac_status_snapshots s"
        " where s.registration_number = r.registration_number and s.snapshot_date = current_date)",
    ]
    params: list[Any] = []
    if min_similarity is not None:
        clauses.append(
            "exists (select 1 from products p"
            " where similarity(p.canonical_name, r.product_name) > %s)"
        )
        params.append(min_similarity)
    sql = (
        "select r.registration_number, r.source_url from nafdac_registrations r where "
        + " and ".join(clauses)
        + " order by r.registration_number"
    )
    if limit is not None:
        sql += " limit %s"
        params.append(limit)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [(row[0], row[1]) for row in cursor.fetchall()]


def store(connection, record: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(UPDATE_SQL, record)
        cursor.execute(SNAPSHOT_SQL, record)


def store_with_reconnect(connection, record: dict[str, Any]):
    """Store one record, reconnecting once if the database dropped the socket.

    Neon closes an idle or long-lived connection without warning; a single uncommitted
    transaction spanning an hour would lose every page fetched so far. Batched commits make the
    loss window `--commit-every` records, and resume then refetches only what has no snapshot.
    """
    try:
        store(connection, record)
        return connection
    except Exception:
        try:
            connection.close()
        except Exception:
            pass
        fresh = db_connect()
        store(fresh, record)
        return fresh


# ------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape NAFDAC Greenbook detail pages.")
    parser.add_argument("--dry-run", action="store_true", help="fetch and parse, write no rows")
    parser.add_argument("--limit", type=int, default=None, help="stop after N registrations")
    parser.add_argument("--all", action="store_true", help="full sweep, ignore the product scope")
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=DEFAULT_MIN_SIMILARITY,
        help=f"product-name similarity floor for the restricted scope (default {DEFAULT_MIN_SIMILARITY})",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=DEFAULT_MAX_SECONDS,
        help="stop gracefully after this many seconds (default 5.5 h)",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=50,
        help="commit every N registrations so a dropped connection costs at most N pages (default 50)",
    )
    args = parser.parse_args(argv)

    min_similarity = None if args.all else args.min_similarity
    scope_label = "all registrations" if args.all else f"products similar > {min_similarity}"

    connection = None
    run_id = None
    started = time.monotonic()
    observed_at = datetime.now(timezone.utc)

    try:
        # The target list lives in the database, so both modes need a connection; --dry-run
        # only skips the ledger row and the writes.
        connection = db_connect()
        if not args.dry_run:
            run_id = start_run(connection, SOURCE)

        targets = select_scope(connection, min_similarity=min_similarity, limit=args.limit)
        print(f"scope: {scope_label} | targets: {len(targets)}", flush=True)
        if not targets:
            print("nothing to do: every target already has a snapshot for today")
            if not args.dry_run and run_id is not None:
                finish_run(connection, run_id, status="success", record_count=0)
            return 0

        client = RateLimitedClient()
        records: list[dict[str, Any]] = []
        failed: list[tuple[str, str]] = []
        unparsed = 0
        budget_hit = False

        for index, (nrn, url) in enumerate(targets, start=1):
            if time.monotonic() - started > args.max_seconds:
                budget_hit = True
                print(f"time budget reached after {index - 1} registrations; stopping cleanly", flush=True)
                break
            try:
                body = fetch_detail(client, url)
            except DetailUnavailable as exc:
                failed.append((nrn, str(exc)[:120]))
                continue

            parsed = parse_detail(body)
            parsed["registration_number"] = nrn
            parsed["source_url"] = url
            parsed["observed_at"] = observed_at.isoformat()
            records.append(parsed)

            if not parsed.get("status"):
                unparsed += 1
            if not args.dry_run:
                connection = store_with_reconnect(connection, parsed)
                if index % args.commit_every == 0:
                    connection.commit()

            if index % 50 == 0:
                elapsed = time.monotonic() - started
                rate = index / elapsed if elapsed else 0
                remaining = (len(targets) - index) / rate if rate else 0
                print(
                    f"  {index}/{len(targets)}  {rate:.2f}/s  eta {remaining / 60:.0f} min"
                    f"  failed {len(failed)}",
                    flush=True,
                )

        if not args.dry_run:
            connection.commit()

        archive_path, archive_sha = archive_jsonl(SOURCE, records, when=observed_at)
        total = len(records)
        with_status = sum(1 for r in records if r.get("status"))
        with_expiry = sum(1 for r in records if r.get("expiry_date"))
        print(f"\n--- {'dry run' if args.dry_run else 'detail run'} ---")
        print(f"targets              {len(targets)}")
        print(f"records              {total}")
        print(f"status populated     {with_status} ({100.0 * with_status / total:.1f}%)" if total else "status populated     0")
        print(f"expiry populated     {with_expiry} ({100.0 * with_expiry / total:.1f}%)" if total else "expiry populated     0")
        print(f"status unparsed      {unparsed}")
        print(f"failed after retries {len(failed)}")
        for nrn, reason in failed[:5]:
            print(f"  {nrn}: {reason}")
        print(f"archive              {archive_path.name} sha256={archive_sha[:16]}")
        if budget_hit:
            print("NOTE: stopped on the time budget; rerun to resume the remaining registrations")

        if args.dry_run:
            print("dry run: no database rows written")
            return 0

        note = "time budget reached" if budget_hit else None
        finish_run(connection, run_id, status="success", record_count=total, error=note)
        print(f"scrape_runs id={run_id} status=success record_count={total}")
        return 0
    except Exception as exc:  # noqa: BLE001 - the ledger row is the point of this except
        message = f"{type(exc).__name__}: {exc}"
        print(f"\nFAILED: {message}", file=sys.stderr)
        if run_id is not None:
            try:
                finish_run(connection, run_id, status="failed", error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                # The socket may be the thing that died, so try a fresh connection before
                # giving up: a run left at 'running' is the state the ledger must never keep.
                try:
                    fresh = db_connect()
                    finish_run(fresh, run_id, status="failed", error=message)
                    print(f"scrape_runs id={run_id} status=failed (reconnected)", file=sys.stderr)
                except Exception:  # noqa: BLE001
                    print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
