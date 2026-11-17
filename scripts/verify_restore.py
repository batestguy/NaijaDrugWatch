"""Prove that the frozen vintage restores, and that every published figure comes back with it.

    .venv\\Scripts\\python.exe -X utf8 scripts/verify_restore.py

WHY. A frozen project whose only copy lives in a database that can be suspended has not been frozen,
it has been parked. The export was proven *readable* for two days before anyone proved it *restorable*,
and the difference is the whole point of an archive. This script closes that gap in one command, and it
is written to be run by a stranger who has just cloned the repository.

WHAT IT DOES.

  no --dsn    starts a throwaway PostgreSQL 17 container from the pgvector image, waits for it, restores
              the dump into it, runs the checks, and removes the container. Nothing else on the machine
              is touched. Requires Docker running.
  with --dsn  skips the container and checks an already-restored database instead, which is how CI uses
              it against a service container.

WHAT IT CHECKS. Every base table against the row count in the vintage's own MANIFEST file, then the
figures the project publishes: listings, matched listings, products, comparison cells, suspicious rows,
registrations and index rows. It also proves the vector column came back as a vector of the right
dimension rather than as text - the thing a naive reload silently loses.

EXIT CODE. 0 when everything matches, 1 on any difference, 2 when it cannot run at all (no Docker, no
dump, unknown vintage). A skip is not a pass: if it cannot run it says so and exits non-zero.

THE TRAP THIS AVOIDS. pgvector cannot be installed through conda on Windows for PostgreSQL 17 or 18:
every conda-forge build declares libpq 16.15 and the defaults builds target 14 and 15, so the solver
downgrades the server to 16 - and a dump written by 17 cannot be restored into 16. The container image
carries the extension against the right major, which is why this uses it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VINTAGE = "2026-11-16"
IMAGE = "pgvector/pgvector:pg17"

# The figures this vintage publishes. Stated rather than derived, because the point of the check is to
# compare a restored database against what the project claims, not against itself. A new vintage needs
# its own entry; the script refuses a vintage it does not know.
EXPECTED_FIGURES: dict[str, list[tuple[str, str, int]]] = {
    "2026-11-16": [
        ("latest listings", "select count(*) from v_latest_listings", 2800),
        ("matched to a product",
         "select count(*) from v_latest_listings where product_id is not null", 559),
        ("products", "select count(*) from products", 1433),
        ("cheapest cells", "select count(*) from v_cheapest_per_product_state", 261),
        ("two-shop comparisons",
         "select count(*) from v_cheapest_per_product_state where is_comparison", 44),
        ("suspicious listings", "select count(*) from v_suspicious_listings", 154),
        ("registrations", "select count(*) from nafdac_registrations", 10967),
        ("registrations with a status",
         "select count(*) from nafdac_registrations where status is not null", 1856),
        ("index rows", "select count(*) from mv_drug_price_index", 428),
    ]
}
VECTOR_DIMS = 384
HOST, USER, DBNAME = "127.0.0.1", "postgres", "ndw_verify"


def run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def docker_ready() -> bool:
    try:
        return run(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode == 0
    except (OSError, FileNotFoundError):
        return False


def start_container(name: str, port: int, password: str) -> bool:
    run(["docker", "rm", "-f", name])
    started = run([
        "docker", "run", "-d", "--name", name,
        "-e", f"POSTGRES_PASSWORD={password}",
        "-e", f"POSTGRES_DB={DBNAME}",
        "-p", f"{port}:5432",
        IMAGE,
    ])
    if started.returncode != 0:
        print(f"cannot start {IMAGE}: {started.stderr.strip()[:300]}", file=sys.stderr)
        return False
    for _ in range(45):
        time.sleep(2)
        probe = run(["docker", "exec", name, "pg_isready", "-U", USER, "-d", DBNAME])
        if probe.returncode == 0:
            return True
    print("container never became ready", file=sys.stderr)
    return False


def stop_container(name: str) -> None:
    run(["docker", "rm", "-f", name])


def restore(dump: Path, target: dict) -> bool:
    """pg_restore one archive into `target`, a dict of libpq parameters."""
    tool = which("pg_restore") or which("pg_restore.exe")
    if not tool:
        print("pg_restore is not on PATH - it ships with the postgresql client tools", file=sys.stderr)
        return False
    env = dict(os.environ)
    if target.get("password"):
        env["PGPASSWORD"] = target["password"]
    cmd = [tool, f"--host={target.get('host', HOST)}", f"--port={target.get('port', 5432)}",
           f"--username={target.get('user', USER)}", f"--dbname={target.get('dbname', DBNAME)}",
           "--no-owner", "--no-privileges", str(dump)]
    proc = run(cmd, env=env)
    if proc.returncode != 0:
        print(f"pg_restore failed ({proc.returncode}):", file=sys.stderr)
        print("\n".join((proc.stderr or "").splitlines()[:15]), file=sys.stderr)
        return False
    if (proc.stderr or "").strip():
        print(f"pg_restore exited 0 but said:\n{proc.stderr.strip()[:500]}", file=sys.stderr)
    return True


def connect(port: int | None, password: str | None, dsn: str | None):
    import psycopg

    if dsn:
        return psycopg.connect(dsn, options="-c default_transaction_read_only=on")
    return psycopg.connect(
        host=HOST, port=port, user=USER, password=password, dbname=DBNAME,
        options="-c default_transaction_read_only=on",
    )


def check(conn, vintage: str, manifest: dict) -> int:
    fails: list[str] = []
    expected_tables = {
        entry["table"]: entry["db_rows"]
        for entry in manifest["files"]
        if entry.get("db_rows") is not None
    }

    def report(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
        if not ok:
            fails.append(label)

    with conn:
        scalar = lambda sql: conn.execute(sql).fetchone()[0]

        print("== extensions ==")
        exts = sorted(r[0] for r in conn.execute("select extname from pg_extension").fetchall())
        print("   " + ", ".join(exts))
        for needed in ("vector", "pg_trgm", "unaccent"):
            report(f"extension {needed}", needed in exts)

        print("\n== base tables against the vintage manifest ==")
        for table, want in sorted(expected_tables.items()):
            try:
                got = scalar(f'select count(*) from public."{table}"')
            except Exception as exc:  # noqa: BLE001 - any failure is a finding
                report(table, False, f"not restorable: {type(exc).__name__}")
                continue
            report(table, got == want, f"{got:,} of {want:,}")

        print("\n== the figures this vintage publishes ==")
        for label, sql, want in EXPECTED_FIGURES[vintage]:
            try:
                got = scalar(sql)
            except Exception as exc:  # noqa: BLE001
                report(label, False, type(exc).__name__)
                continue
            report(label, got == want, f"{got:,} of {want:,}")

        print("\n== the vector column is still a vector ==")
        try:
            dims = scalar("select vector_dims(embedding) from products "
                          "where embedding is not null limit 1")
            nonnull = scalar("select count(*) from products where embedding is not null")
            report(f"embeddings are {VECTOR_DIMS}-dimensional", dims == VECTOR_DIMS, f"first row {dims}")
            report("every product kept its embedding", nonnull == 1433, f"{nonnull:,} of 1,433")
        except Exception as exc:  # noqa: BLE001
            report("embeddings survived as vectors", False, type(exc).__name__)

    print()
    if fails:
        print(f"{len(fails)} CHECK(S) FAILED: " + "; ".join(fails[:6]))
        return 1
    print("ALL CHECKS PASSED - the export restores and every published figure comes back")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prove the frozen vintage restores.")
    parser.add_argument("--vintage", default=DEFAULT_VINTAGE)
    parser.add_argument("--dump", default=None, help="path to the .dump file")
    parser.add_argument("--manifest", default=None,
                        help="path to MANIFEST.json, when it is not beside the dump (CI downloads it)")
    parser.add_argument("--dsn", default=None,
                        help="check this database instead of starting a container (read from the "
                             "environment in CI, never written into a file)")
    parser.add_argument("--port", type=int, default=55433)
    parser.add_argument("--container", default="ndw-verify-restore")
    parser.add_argument("--no-restore", action="store_true",
                        help="only check an already-restored database; do not load the dump")
    parser.add_argument("--keep", action="store_true", help="leave the container running")
    args = parser.parse_args(argv[1:])

    if args.vintage not in EXPECTED_FIGURES:
        print(f"no expected figures recorded for vintage {args.vintage}", file=sys.stderr)
        return 2

    vintage_dir = ROOT / "vintage" / args.vintage
    dump = Path(args.dump) if args.dump else vintage_dir / "naijadrugwatch.dump"
    manifest_path = Path(args.manifest) if args.manifest else vintage_dir / "MANIFEST.json"
    if not manifest_path.exists():
        print(f"cannot find the vintage manifest at {manifest_path}", file=sys.stderr)
        print("the vintage folder is gitignored; see FROZEN.md for where it is published", file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # CI passes --dsn for a service container that is empty, so the dump has to be loaded into it.
    # Missing that is how the first CI run reported 21 failures against an empty database.
    if args.dsn:
        conn = connect(None, None, args.dsn)
        if not args.no_restore:
            from psycopg.conninfo import conninfo_to_dict
            if not dump.exists():
                print(f"cannot find the dump at {dump}", file=sys.stderr)
                return 2
            if not restore(dump, conninfo_to_dict(args.dsn)):
                return 1
        return check(conn, args.vintage, manifest)

    if args.no_restore:
        print("--no-restore needs --dsn: there is nothing to check without a database", file=sys.stderr)
        return 2
    if not dump.exists():
        print(f"cannot find the dump at {dump}", file=sys.stderr)
        return 2
    if not docker_ready():
        print("Docker is not answering. Start Docker Desktop, or pass --dsn for an existing database.",
              file=sys.stderr)
        return 2

    password = "verify"
    if not start_container(args.container, args.port, password):
        return 2
    try:
        if not restore(dump, {"host": HOST, "port": args.port, "user": USER,
                              "dbname": DBNAME, "password": password}):
            return 1
        return check(connect(args.port, password, None), args.vintage, manifest)
    finally:
        if args.keep:
            print(f"\ncontainer {args.container} left running on port {args.port}")
        else:
            stop_container(args.container)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
