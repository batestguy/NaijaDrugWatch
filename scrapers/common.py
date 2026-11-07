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


def db_connect(url: str | None = None):
    import psycopg  # lazy: dry runs do not need the driver

    return psycopg.connect(url or os.environ["DATABASE_URL"])


def start_run(connection, source: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into scrape_runs (source, status) values (%s, 'running') returning id",
            (source,),
        )
        run_id = cursor.fetchone()[0]
    connection.commit()
    return int(run_id)


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
    with connection.cursor() as cursor:
        cursor.execute(
            "update scrape_runs set status = %s, record_count = %s, error_message = %s,"
            " finished_at = now() where id = %s",
            (status, record_count, (error or "")[:2000] or None, run_id),
        )
    connection.commit()


def existing_urls(connection, source: str) -> set[str]:
    """URLs already stored for a pharmacy source, so a rerun can skip refetching pages it has."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select distinct url from pharmacy_listings l"
            " join pharmacies p on p.id = l.pharmacy_id where p.name = %s",
            (source,),
        )
        return {row[0] for row in cursor.fetchall()}
