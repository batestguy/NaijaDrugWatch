import sys
import pathlib

sys.path.insert(0, "scripts")
from envfile import ensure_database_url
import psycopg

url = ensure_database_url()
sql = pathlib.Path("schema/009_index_price_floor.sql").read_text(encoding="utf-8")

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "select count(*), count(*) filter (where min_price_ngn < 20), "
            "min(min_price_ngn), max(max_price_ngn) from mv_drug_price_index"
        )
        rows, under, low, high = cur.fetchone()
        cur.execute(
            "select count(*) from pg_indexes where tablename = 'mv_drug_price_index'"
        )
        idx = cur.fetchone()[0]
        cur.execute("select count(distinct day) from mv_drug_price_index")
        days = cur.fetchone()[0]

print(
    "rows:", rows,
    "| rows with min under 20:", under,
    "| lowest min:", low,
    "| highest max:", high,
    "| days:", days,
    "| indexes on the view:", idx,
)
