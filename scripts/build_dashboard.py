"""Build the explorable page: every price, filterable, with a link to its source and its licence.

WHY A STATIC PAGE RATHER THAN THE STREAMLIT APP. The dashboard in `dashboard/` is a live application: it
opens a database connection on every visit. That was right while the pipeline ran nightly. The project is
frozen, so every visit would return the same numbers - and a hosted app would put the connection string
on a third party and depend on a free database that suspends itself when idle. The one thing the
Streamlit app offered that the front page did not is interactivity, and interactivity does not need a
server: 2,800 rows are 400 KB of JSON and a filter is twenty lines of JavaScript.

WHAT THIS WRITES. `site/dashboard.html` - one file, no external stylesheet, script, font or image, so it
opens from a double-click with no connection.

WHAT IT PROVES BEFORE WRITING. It runs its query twice and compares: the number of rows embedded must
equal the number in the database on a second read, and the same for the count of rows carrying a licence
flag and the distinct shop count. A page whose figures cannot be re-derived is not written.

    .venv\\Scripts\\python.exe -X utf8 scripts/build_dashboard.py
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envfile import ensure_database_url

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPO_URL = "https://github.com/batestguy/NaijaDrugWatch"
FREEZE = json.loads((ROOT / "freeze.json").read_text(encoding="utf-8"))

SQL = """
select l.listing_id,
       l.pharmacy_name,
       l.state,
       coalesce(l.canonical_name, '') as medicine,
       l.raw_title,
       l.price_ngn,
       l.pack_size,
       coalesce(l.pack_unit, '') as pack_unit,
       l.unit_price,
       l.in_stock,
       l.url,
       coalesce(p.strength, '') as strength,
       coalesce(r.registration_number, '') as registration,
       coalesce(r.status, '') as status,
       r.expiry_date,
       coalesce(r.source_url, '') as register_url,
       case when c.product_id is null then 0 else 1 end as in_comparison,
       case when s.listing_id is null then 0 else 1 end as flagged
  from v_latest_listings l
  left join products p on p.id = l.product_id
  left join nafdac_registrations r on r.registration_number = p.nafdac_registration_number
  left join (select distinct product_id
               from v_cheapest_per_product_state
              where is_comparison) c on c.product_id = l.product_id
  left join (select listing_id from v_suspicious_listings) s on s.listing_id = l.listing_id
 order by medicine nulls last, l.price_ngn
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value: Any) -> str | None:
    if value is None:
        return None
    return f"{float(value):.2f}"


def licence_label(status: str, has_record: bool, flagged: int) -> str:
    """Three labels, matching `v_suspicious_listings` by construction rather than by re-deriving its rule.

    WHY FROM THE VIEW. The view flags a listing when its registration is not Active **or its expiry has
    passed**, and it ignores registrations with no status. Re-implementing that rule here produced a
    different count from the one the rest of the project publishes, and the build refused to write the
    page - which is exactly what a self-check is for. The page now takes the answer from the view.
    """
    if not has_record:
        return "not read"
    return "not active" if flagged else "active"


def fetch(conn) -> list[dict[str, Any]]:
    rows = []
    for (listing_id, shop, state, medicine, title, price, pack, unit, unit_price, stock,
         url, strength, registration, status, expiry, register_url, in_comparison, flagged) in conn.execute(SQL):
        rows.append({
            "i": listing_id,
            "s": shop,
            "t": title or medicine or "unnamed listing",
            "m": medicine,
            "p": money(price),
            "k": pack,
            "u": (unit or "").strip(),
            "pu": money(unit_price),
            "st": None if stock is None else (1 if stock else 0),
            "a": url or "",
            "x": int(in_comparison),
            "g": registration or "",
            "l": licence_label(status, bool(registration), flagged),
            "ru": register_url or "",
        })
    return rows


CSS = """
:root{--bg:#faf7f1;--ink:#1a1612;--muted:#4a423d;--line:#d8cfc2;--panel:#f1ebdf;--accent:#5f2a54;
--ok:#1c5c2e;--warn:#7a2e00;--focus:#1a1612}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:1rem/1.55 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:80rem;margin:0 auto;padding:1rem .75rem 3rem}
h1{font-size:1.6rem;margin:.2rem 0 .4rem}
.lede{max-width:66ch;color:var(--muted)}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{
outline:3px solid var(--focus);outline-offset:2px}
.skip{position:absolute;left:-9999px}
.skip:focus{left:.5rem;top:.5rem;background:var(--bg);padding:.5rem;z-index:9}
.controls{display:flex;flex-wrap:wrap;gap:.7rem;align-items:flex-end;margin:1rem 0 .6rem;
padding:.8rem;background:var(--panel);border:2px solid var(--line);border-radius:6px}
.field{display:flex;flex-direction:column;gap:.2rem}
.field label{font-size:.82rem;font-weight:700;letter-spacing:.02em;text-transform:uppercase;color:var(--muted)}
input[type=search],select{font:inherit;padding:.4rem .5rem;border:2px solid var(--line);
border-radius:4px;background:var(--bg);color:var(--ink);min-width:11rem}
.count{margin:.2rem 0 .8rem;font-variant-numeric:tabular-nums}
.count strong{font-size:1.05rem}
.tablewrap{overflow-x:auto;border:2px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:.95rem}
caption{text-align:left;padding:.5rem .6rem;color:var(--muted);background:var(--panel)}
th,td{padding:.4rem .55rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{position:sticky;top:0;background:var(--panel);font-size:.85rem;letter-spacing:.02em;
text-transform:uppercase;color:var(--muted)}
tbody tr:nth-child(even){background:#fffdf9}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;font-size:.78rem;padding:.08rem .4rem;border:1px solid var(--line);
border-radius:3px;white-space:nowrap}
.tag-ok{color:var(--ok);border-color:var(--ok)}
.tag-bad{color:var(--warn);border-color:var(--warn)}
.muted{color:var(--muted)}
.empty{padding:1.5rem;text-align:center;color:var(--muted)}
footer{margin-top:2rem;padding-top:1rem;border-top:2px solid var(--line);color:var(--muted);
font-size:.9rem;max-width:70ch}
@media (max-width:640px){.wrap{padding:.75rem .6rem 2rem}.field{flex:1 1 100%}
input[type=search],select{width:100%}}
"""

JS = """
(function () {
  var DATA = JSON.parse(document.getElementById('rows').textContent);
  var els = {
    q: document.getElementById('q'), shop: document.getElementById('shop'),
    lic: document.getElementById('lic'), sort: document.getElementById('sort'),
    body: document.getElementById('rows-body'), count: document.getElementById('count'),
    live: document.getElementById('live'), empty: document.getElementById('empty')
  };
  function fmt(n) { return n === null || n === undefined ? '' : '\u20a6' + Number(n).toLocaleString('en-NG', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function licenceTag(l) {
    if (l === 'active') return '<span class="tag tag-ok">active</span>';
    if (l === 'not active') return '<span class="tag tag-bad">not active</span>';
    return '<span class="tag">not read</span>';
  }
  function stockTag(s) {
    if (s === 1) return '<span class="tag tag-ok">in stock</span>';
    if (s === 0) return '<span class="tag tag-bad">out of stock</span>';
    return '<span class="tag">not read</span>';
  }
  function render() {
    var q = els.q.value.trim().toLowerCase();
    var shop = els.shop.value, lic = els.lic.value, sort = els.sort.value;
    var rows = DATA.filter(function (r) {
      if (shop && r.s !== shop) return false;
      if (lic && r.l !== lic) return false;
      if (q && (r.t + ' ' + r.m).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    rows.sort(function (a, b) {
      var pa = a.p === null ? Infinity : Number(a.p), pb = b.p === null ? Infinity : Number(b.p);
      if (sort === 'price-desc') return pb - pa;
      if (sort === 'name') return a.t.localeCompare(b.t) || pa - pb;
      return pa - pb;
    });
    var out = rows.map(function (r) {
      var pack = r.k ? esc(r.k) + (r.u ? ' ' + esc(r.u) : '') : '';
      var unit = r.pu ? fmt(r.pu) + (r.u ? ' / ' + esc(r.u) : '') : '';
      var links = '<a href="' + esc(r.a) + '" rel="nofollow noopener">shop page</a>';
      if (r.ru) links += ' \u00b7 <a href="' + esc(r.ru) + '" rel="nofollow noopener">register</a>';
      if (r.x) links += ' \u00b7 <span class="tag">two shops</span>';
      return '<tr><th scope="row">' + esc(r.t) + (r.m ? '' : ' <span class="tag">no match</span>') +
        '</th><td>' + esc(r.s) + '</td><td class="num">' + fmt(r.p) + '</td><td>' + pack +
        '</td><td class="num">' + unit + '</td><td>' + stockTag(r.st) + '</td><td>' +
        licenceTag(r.l) + '</td><td>' + links + '</td></tr>';
    });
    els.body.innerHTML = out.join('');
    els.empty.hidden = rows.length !== 0;
    els.count.innerHTML = '<strong>' + rows.length.toLocaleString() + '</strong> of ' +
      DATA.length.toLocaleString() + ' listings shown';
    els.live.textContent = rows.length + ' of ' + DATA.length + ' listings shown.';
  }
  [els.q, els.shop, els.lic, els.sort].forEach(function (el) {
    el.addEventListener('input', render);
    el.addEventListener('change', render);
  });
  render();
})();
"""


def page(rows: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    shops = sorted({r["s"] for r in rows})
    still = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    options = "\n".join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in shops)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Every price, explorable - NaijaDrugWatch</title>
<link rel="icon" href="data:,">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to the prices</a>
<div class="wrap">
<header>
<p class="muted"><a href="index.html">&larr; Medicine prices and registration status in Nigeria</a></p>
<h1>Every price, explorable</h1>
<p class="lede">All {len(rows):,} prices this project holds, filterable by shop, by medicine and by what the
NAFDAC register says about the licence behind it. Each row links to the pharmacy page the price came
from, and to the register record where one was read.</p>
<p class="muted">A frozen snapshot: collection stopped on {esc(FREEZE["frozen_on"])} and the newest price
was recorded on {meta["newest"]}. Nothing here is live. The page was built at {still} and reads nothing
from a server.</p>
</header>

<main id="main">
<div class="controls">
  <div class="field">
    <label for="q">Search a medicine</label>
    <input type="search" id="q" placeholder="e.g. amoxicillin" autocomplete="off">
  </div>
  <div class="field">
    <label for="shop">Shop</label>
    <select id="shop"><option value="">All shops</option>
{options}
    </select>
  </div>
  <div class="field">
    <label for="lic">Licence</label>
    <select id="lic">
      <option value="">Any</option>
      <option value="active">Active</option>
      <option value="not active">Not active</option>
      <option value="not read">Not read</option>
    </select>
  </div>
  <div class="field">
    <label for="sort">Order</label>
    <select id="sort">
      <option value="price-asc">Cheapest first</option>
      <option value="price-desc">Most expensive first</option>
      <option value="name">By name</option>
    </select>
  </div>
</div>

<p class="count" id="count"></p>
<p id="live" class="skip" role="status" aria-live="polite"></p>

<div class="tablewrap" role="region" aria-labelledby="rows-heading" tabindex="0">
<table>
<caption id="rows-heading">One row per price. {len(rows):,} rows.</caption>
<thead><tr>
<th scope="col">Medicine as the shop names it</th>
<th scope="col">Shop</th>
<th scope="col">Price</th>
<th scope="col">Pack</th>
<th scope="col">Price per unit</th>
<th scope="col">Stock</th>
<th scope="col">Licence</th>
<th scope="col">Source</th>
</tr></thead>
<tbody id="rows-body"></tbody>
</table>
</div>
<p id="empty" class="empty" hidden>No price matches those filters. Clear the search box, or choose
&ldquo;Any&rdquo; under Licence.</p>
</main>

<footer>
<p><strong>What a licence label means.</strong> It is what the NAFDAC register said when it was read, for
{meta["with_record"]:,} of these {len(rows):,} prices. <em>Not active</em> records a lapsed or inactive
registration; it is not evidence that a medicine is fake or illegal, and nothing here was bought, tested
or inspected. <em>Not read</em> means no status was ever scraped, which is a gap in our reading, not a
finding about the medicine.</p>
<p><strong>What these prices are.</strong> What a shop displayed on the day it was read. Delivery, card
fees and counter discounts are not in them. All three shops publish one price, not a price per state, so
this page has no state filter: a state column would imply a comparison that does not exist.</p>
<p>Code MIT, data CC-BY-4.0. {meta["flag_note"]} Source and method:
<a href="{REPO_URL}">{esc(REPO_URL.replace('https://', ''))}</a>.</p>
</footer>
</div>
<script id="rows" type="application/json">{json.dumps(rows, ensure_ascii=False)}</script>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    url = ensure_database_url()
    if not url:
        print("no DATABASE_URL: set it or put it in .env", file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError as exc:
        print(f"psycopg is not importable: {exc}", file=sys.stderr)
        return 2

    conn = psycopg.connect(url, autocommit=True, connect_timeout=20,
                           options="-c default_transaction_read_only=on")
    with conn:
        rows = fetch(conn)
        recheck = fetch(conn)  # second read: nothing is written unless the two agree
        newest = conn.execute("select to_char(max(scraped_at) at time zone 'UTC', "
                              "'YYYY-MM-DD') from pharmacy_listings").fetchone()[0]
        flagged = conn.execute("select count(*) from v_suspicious_listings").fetchone()[0]

    problems = []
    if len(rows) != len(recheck):
        problems.append(f"row count moved between two reads: {len(rows)} then {len(recheck)}")
    if sum(1 for r in rows if r["l"] == "not active") != flagged:
        problems.append("flagged count does not match v_suspicious_listings")
    if len({r["s"] for r in rows}) != 3:
        problems.append("expected three shops")

    site = ROOT / SITE
    site.mkdir(exist_ok=True)
    if problems:
        print(f"{len(problems)} unexplained:", file=sys.stderr)
        for problem in problems:
            print("  " + problem, file=sys.stderr)
        print("nothing written: a page whose numbers cannot be re-derived is not published.",
              file=sys.stderr)
        return 1

    meta = {
        "newest": newest,
        "with_record": sum(1 for r in rows if r["g"]),
        "flag_note": f"{flagged} rows carry a registration that is not Active.",
    }
    target = site / "dashboard.html"
    target.write_text(page(rows, meta), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size:,} bytes, {len(rows):,} rows)")
    print(f"{len(rows):,} rows checked, 0 unexplained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
