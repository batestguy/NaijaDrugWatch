#!/usr/bin/env python3
"""Shared fetch, archive and ledger helpers for every NaijaDrugWatch scraper.

Only three things live here, because only three are genuinely common:

    RateLimitedClient  one request per domain every 2 s, robots.txt aware, HTTP fallback
    archive_jsonl      dated full dump + sha256, so a block costs freshness and not history
    start_run/finish_run  a scrape_runs row on success AND failure

Anything source-specific (selectors, pagination, pack-size parsing) belongs in that source's
module. Do not grow this file into a framework.

Known live condition (probed 2026-11-07): the NAFDAC Greenbook serves an EXPIRED TLS
certificate, so https:// fails with SEC_E_CERT_EXPIRED while http:// answers 200. The client
falls back per host and records the downgrade, rather than disabling verification globally.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPO_ROOT / "archives"

# Names the project, the product and a contact path, per the scraping rules in AGENTS.md.
USER_AGENT = (
    "NaijaDrugWatch/0.1 (+https://github.com/batestguy/NaijaDrugWatch; "
    "public-interest drug price and registration data; contact via repository issues)"
)

MIN_INTERVAL_S = 2.0
TIMEOUT_S = 45


class RateLimitedClient:
    """One request per domain per `min_interval` seconds, robots.txt honest.

    Usage:
        client = RateLimitedClient()
        text, final_url = client.get("http://greenbook.nafdac.gov.ng/productCategories")
    """

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_S,
        user_agent: str = USER_AGENT,
        timeout: int = TIMEOUT_S,
    ) -> None:
        self.min_interval = min_interval
        self.user_agent = user_agent
        self.timeout = timeout
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, list[str]] = {}
        # Hosts where we had to drop from https to http, kept so a caller can report it.
        self.downgraded_hosts: set[str] = set()

    # ------------------------------------------------------------------ internals

    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _fetch_once(self, url: str) -> str:
        host = urlsplit(url).netloc
        self._throttle(host)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        encoding = response.headers.get("Content-Encoding", "")
        if "gzip" in encoding:
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")

    def _fetch(self, url: str) -> tuple[str, str]:
        """GET with a per-host https->http fallback for an expired certificate."""
        try:
            return self._fetch_once(url), url
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            cert_failure = isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper()
            if not cert_failure or not url.startswith("https://"):
                raise
            fallback = "http://" + url[len("https://"):]
            self.downgraded_hosts.add(urlsplit(url).netloc)
            return self._fetch_once(fallback), fallback

    def _robots_rules(self, url: str) -> list[str]:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        if key not in self._robots:
            try:
                body, _ = self._fetch(f"{key}/robots.txt")
                self._robots[key] = body.splitlines()
            except Exception:
                # Unreachable robots.txt is not consent, but it is also not a block; the
                # caller's own throttle is the backstop. Record an empty rule set.
                self._robots[key] = []
        return self._robots[key]

    def robots_allows(self, url: str) -> bool:
        """Allow-all unless a matching Disallow is present. `Disallow:` empty means allow."""
        parts = urlsplit(url)
        path = parts.path or "/"
        applies = False
        for line in self._robots_rules(url):
            stripped = line.split("#", 1)[0].strip()
            if not stripped or ":" not in stripped:
                continue
            field, _, value = stripped.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                applies = value == "*" or value.lower() in self.user_agent.lower()
            elif field == "disallow" and applies and value:
                if value == "/" or path.startswith(value):
                    return False
        return True

    # --------------------------------------------------------------------- public

    def get(self, url: str, *, check_robots: bool = True) -> tuple[str, str]:
        """Return (body, final_url). Raises if robots.txt disallows the path."""
        if check_robots and not self.robots_allows(url):
            raise PermissionError(f"robots.txt disallows {url}")
        return self._fetch(url)


def archive_jsonl(
    source: str,
    records: Iterable[dict[str, Any]],
    *,
    when: datetime | None = None,
    root: Path = ARCHIVE_ROOT,
) -> tuple[Path, str]:
    """Write a dated, gzipped JSONL dump and return (path, sha256 of the file).

    A second run on the same day does not overwrite the first: it gets a `-02` suffix, so a
    correction is additive and the original dump stays checkable.
    """
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    directory = root / source
    directory.mkdir(parents=True, exist_ok=True)

    base = directory / f"{source}-{stamp}.jsonl.gz"
    path, suffix = base, 2
    while path.exists():
        path = directory / f"{source}-{stamp}-{suffix:02d}.jsonl.gz"
        suffix += 1

    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return path, digest


# ------------------------------------------------------------------------- ledger
#
# The database is optional: a scraper must be able to dry-run without Neon. When a connection
# is passed, every run leaves a scrape_runs row, including failures, because v_pipeline_health
# reads that table and cannot see a source that never wrote one.


def db_connect(url: str | None = None, *, attempts: int = 3, delay: float = 5.0):
    """Connect to Neon, retrying transient resolver/connection failures.

    This machine's DNS intermittently returns `getaddrinfo failed` for the Neon host (observed
    three times on 2026-11-07). A scrape that has already spent twenty minutes fetching should not
    die because a lookup blipped, and neither should a scheduled run.
    """
    import psycopg  # lazy: dry runs do not need the driver

    target = url or os.environ["DATABASE_URL"]
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return psycopg.connect(target)
        except Exception as exc:  # noqa: BLE001 - retried, then raised
            last = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last  # type: ignore[misc]


def start_run(connection, source: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into scrape_runs (source, status) values (%s, 'running') returning id",
            (source,),
        )
        run_id = cursor.fetchone()[0]
    connection.commit()
    return int(run_id)


def clear_failed_transaction(connection) -> None:
    """Roll back an aborted transaction so the ledger write itself can still succeed.

    psycopg3 is not in autocommit mode. When the statement that failed ran inside
    `store_records`, the transaction is already aborted and the next UPDATE raises
    InFailedSqlTransaction -- leaving the run stuck at 'running' forever, which is the one
    state the ledger must never keep. Callers must commit their real work first: this
    discards anything still uncommitted.
    """
    try:
        connection.rollback()
    except Exception:  # a dead connection must not mask the original error
        pass


def ensure_connection(connection):
    """Return a live connection, reconnecting if Neon closed the socket while we were fetching.

    Neon terminated an idle connection with `AdminShutdown: terminating connection due to
    administrator command` after a ten-minute fetch on 2026-11-07, discarding the whole write.
    Callers that fetch for minutes between database touches must pass through here first.
    """
    if connection is not None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("select 1")
            return connection
        except Exception:  # noqa: BLE001 - any failure means reconnect
            try:
                connection.close()
            except Exception:
                pass
    return db_connect()


def record_price_history(connection, listing_ids: list[int]) -> int:
    """Append one price_history row per listing that has none, from the listing's own values.

    Listings are immutable observations: a changed price produces a NEW listing row, never an
    update, so a listing_id only ever gains this single price row. That is enough for
    `mv_drug_price_index`, which aggregates by day/product/state, but it is NOT enough for a
    per-listing time series -- which is why `v_price_change_7d` compares across listings for the
    same (pharmacy_id, url) rather than within a listing_id.

    Idempotent: a listing that already has a price row is skipped.
    """
    if not listing_ids:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into price_history (listing_id, price_ngn, in_stock, unit_price, recorded_at)"
            " select l.id, l.price_ngn, l.in_stock, l.unit_price, l.scraped_at"
            " from pharmacy_listings l"
            " where l.id = any(%s)"
            "   and l.price_ngn is not null"
            "   and not exists (select 1 from price_history h where h.listing_id = l.id)",
            (listing_ids,),
        )
        return cursor.rowcount


def finish_run(
    connection,
    run_id: int,
    *,
    status: str,
    record_count: int | None = None,
    error: str | None = None,
) -> None:
    if status not in {"success", "failed"}:
        raise ValueError("status must be 'success' or 'failed'")
    clear_failed_transaction(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "update scrape_runs set status = %s, record_count = %s, error_message = %s,"
            " finished_at = now() where id = %s",
            (status, record_count, (error or "")[:2000] or None, run_id),
        )
    connection.commit()
