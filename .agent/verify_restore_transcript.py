"""Compare a restored database against the frozen vintage's own manifest.

The connection string is read from RESTORE_DSN, so no credential is written into a file.
"""
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(r"D:\NaijaDrugWatch")
DSN = os.environ.get("RESTORE_DSN")
if not DSN:
    print("set RESTORE_DSN first", file=sys.stderr)
    raise SystemExit(2)
manifest = json.loads((ROOT / "vintage" / "2026-11-16" / "MANIFEST.json").read_text(encoding="utf-8"))

expected = {f["table"]: f["db_rows"] for f in manifest["files"] if f.get("db_rows") is not None}

fails = []


def check(label, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
    if not ok:
        fails.append(label)


with psycopg.connect(DSN, options="-c default_transaction_read_only=on") as conn:
    q = lambda sql: conn.execute(sql).fetchone()[0]

    print("== extensions ==")
    exts = sorted(r[0] for r in conn.execute("select extname from pg_extension").fetchall())
    print("  ", ", ".join(exts))
    for need in ("vector", "pg_trgm", "unaccent"):
        check(f"extension {need} present", need in exts)

    print("\n== table row counts against the manifest ==")
    for table, want in sorted(expected.items()):
        try:
            got = q(f'select count(*) from public."{table}"')
        except Exception as exc:
            check(f"{table}", False, f"not restorable: {type(exc).__name__}")
            continue
        check(f"{table}", got == want, f"{got:,} of {want:,}")

    print("\n== the figures the project publishes ==")
    checks = [
        ("latest listings", "select count(*) from v_latest_listings", 2800),
        ("matched to a product", "select count(*) from v_latest_listings where product_id is not null", 559),
        ("products", "select count(*) from products", 1433),
        ("cheapest cells", "select count(*) from v_cheapest_per_product_state", 261),
        ("two-shop comparisons", "select count(*) from v_cheapest_per_product_state where is_comparison", 44),
        ("suspicious listings", "select count(*) from v_suspicious_listings", 154),
        ("registrations", "select count(*) from nafdac_registrations", 10967),
        ("registrations with a status", "select count(*) from nafdac_registrations where status is not null", 1856),
        ("index rows", "select count(*) from mv_drug_price_index", 428),
    ]
    for label, sql, want in checks:
        try:
            got = q(sql)
        except Exception as exc:
            check(label, False, f"{type(exc).__name__}")
            continue
        check(label, got == want, f"{got:,} of {want:,}")

    print("\n== the vector column survived as a vector ==")
    dim = q("select vector_dims(embedding) from products where embedding is not null limit 1")
    nonnull = q("select count(*) from products where embedding is not null")
    check("embeddings are 384-dimensional vectors", dim == 384, f"first row: {dim} dims")
    check("every product kept its embedding", nonnull == 1433, f"{nonnull:,} of 1,433")

    print("\n== the views still answer ==")
    rows = conn.execute(
        "select canonical_name, cheapest_pharmacy, price_ngn from v_cheapest_per_product_state "
        "where is_comparison order by price_ngn desc limit 3"
    ).fetchall()
    for row in rows:
        print(f"   {row[0]} via {row[1]}: {row[2]}")
    check("a comparison view returns rows", len(rows) == 3)

print()
print(f"{len(fails)} failed" if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
