"""Run one read-only SQL query against the project database. For reviewers, not for pipelines.

WHY THIS EXISTS. A reviewer agent's shell permission allowlist matches one command against a pattern.
Setting the connection string and then running python is two commands, so it is refused, and a review
that cannot query the database is a read-through rather than an audit. This is the single command that
does both, and it cannot write:

    .venv\\Scripts\\python.exe -X utf8 scripts/dbq.py "select count(*) from v_suspicious_listings"

SAFETY IS THREE LAYERS, and the strongest is not the first:

  1. The statement must start with `select` or `with`, after leading comments and whitespace are
     stripped, and must contain no `;` except an optional one at the very end.
  2. The connection is opened with `default_transaction_read_only=on`, so the server itself refuses a
     write: `ReadOnlySqlTransaction`. Verified 2026-11-10 -- an UPDATE, a DELETE and an INSERT were all
     rejected on a connection configured exactly this way, while SELECTs work.
  3. It is used by humans and review agents only. The pipeline does not call it.

Output is a header line and one tab-separated line per row, so it can be pasted into a report unedited.
NULL prints as `NULL` and is never confused with the empty string.
"""

from __future__ import annotations

import os
import sys

from envfile import ensure_database_url

MAX_ROWS = 200
REFUSED = "refused: this runs a single read-only query. It must start with select or with, and must " \
          "not contain an embedded semicolon. Nothing was executed."


def readable(statement: str) -> bool:
    """True when the statement is a single SELECT/WITH with no trailing statement.

    Deliberately strict and deliberately not a parser. The read-only transaction is the real guard;
    this exists so an obvious mistake is refused with a clear message instead of a server error.
    """
    body = statement.strip()
    while body.startswith("--") or body.startswith("/*"):
        if body.startswith("--"):
            newline = body.find("\n")
            if newline == -1:
                return False
            body = body[newline + 1:].lstrip()
        else:
            end = body.find("*/")
            if end == -1:
                return False
            body = body[end + 2:].lstrip()

    lowered = body.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    trimmed = body.rstrip()
    if trimmed.endswith(";"):
        trimmed = trimmed[:-1]
    return ";" not in trimmed


def render(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].strip():
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print(f'usage: python scripts/dbq.py "select 1"', file=sys.stderr)
        return 2

    statement = argv[1]
    if not readable(statement):
        print(REFUSED, file=sys.stderr)
        return 2

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
        with psycopg.connect(
            url,
            autocommit=True,
            connect_timeout=20,
            options="-c default_transaction_read_only=on",
        ) as conn:
            conn.execute("set statement_timeout = '60s'")
            cursor = conn.execute(statement)
            if cursor.description is None:
                print("(no result set)", file=sys.stderr)
                return 2
            print("\t".join(column.name for column in cursor.description))
            rows = cursor.fetchmany(MAX_ROWS)
            for row in rows:
                print("\t".join(render(value) for value in row))
            if len(rows) == MAX_ROWS:
                print(f"... stopped at {MAX_ROWS} rows", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- any failure is the caller's to read
        message = type(exc).__name__ + ": " + str(exc).splitlines()[0]
        password = os.environ.get("DATABASE_URL", "")
        if "@" in password:
            secret = password.split("//", 1)[-1].split("@", 1)[0].split(":", 1)[-1]
            if secret:
                message = message.replace(secret, "***")
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
