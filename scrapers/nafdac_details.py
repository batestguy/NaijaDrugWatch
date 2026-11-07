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
scraping status for all 10,906 costs hours to change nothing on screen. The default covers ~1,474
registrations in ~50 min at the mandatory 2 s/request. Raise or drop the flag for a full sweep --
this is the same file, not a second scraper.

RESUMABILITY
------------
An NRN that already has a snapshot for today is skipped, so an interrupted run resumes by simply
being run again, and a retry never restarts a range. A 500 is retried with backoff and, if it still
fails, is left unsnapshotted so the next run picks it up.

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


def fetch_detail(client: RateLimitedClient, url: str, *, retries: int = 3) -> str:
    """GET a detail page, retrying 5xx and transport errors with backoff."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            body, _final = client.get(url)
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
        print(f"scope: {scope_label} | targets: {len(targets)}")
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
                print(f"time budget reached after {index - 1} registrations; stopping cleanly")
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
                store(connection, parsed)

            if index % 50 == 0:
                elapsed = time.monotonic() - started
                rate = index / elapsed if elapsed else 0
                remaining = (len(targets) - index) / rate if rate else 0
                print(f"  {index}/{len(targets)}  {rate:.2f}/s  eta {remaining / 60:.0f} min  failed {len(failed)}")

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
        if connection is not None and run_id is not None:
            try:
                finish_run(connection, run_id, status="failed", error=message)
                print(f"scrape_runs id={run_id} status=failed", file=sys.stderr)
            except Exception as ledger_exc:  # noqa: BLE001
                print(f"could not write scrape_runs failure: {ledger_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
