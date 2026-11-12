# T2 report — slash-separated strengths compare as one strength, not half of one

## The rule I implemented, in one sentence

**A number followed by `/` and another number and then a unit is *one token per number* sharing that
unit** — so `20/120MG` yields `{20 mg, 120 mg}` and equals the register's `20 mg; 120 mg`, where before
it yielded `{120 mg}` because the `20` had no unit after it and was skipped.

The mechanism is one regex change plus a split:

```python
STRENGTH_TOKEN_RE = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)*)\s*([a-z]+(?:\s*/\s*[a-z]+)?)"
)
STRENGTH_PAIR_SPLIT_RE = re.compile(r"\s*/\s*")
```

The number group collects `A/B/C…`; the loop splits it and attaches the one unit to each part. A pair
with **no** unit after it (`5/5`, `30/70`) still produces **no tokens at all** — the old behaviour —
because the trailing `[a-z]+` is still required. That is deliberate: it is what stops a ratio or a pack
count from being invented into a strength.

## Changed

| File | Lines | What |
|---|---|---|
| `scripts/link_product_nrn.py` | `:65-101` | The defect. `STRENGTH_TOKEN_RE` now collects a slash *chain* of numbers; `STRENGTH_PAIR_SPLIT_RE` added at `:73`; `strength_tokens()` at `:76` splits the chain and adds one token per number (indentation of the `Decimal` parse moved inside the inner loop, logic otherwise unchanged). Docstring now says a slash pair is two tokens and names the strings where a slash is *not* a combination. |
| `scripts/link_product_nrn.py` | `:99-179` | New `--self-test` fixture harness: `SELF_TEST_CASES` (`:109`, 18 strength pairs), `SELF_TEST_CHOOSE_CASES` (`:134`, 4 `choose()` verdicts), `run_self_test()` (`:148`). No database, no network, writes nothing, exits non-zero if a fixture disagrees. It lives inside the script because this ticket was allowed to write no other file. |
| `scripts/link_product_nrn.py` | `:305-309` | `--self-test` flag, short-circuited **before** `db_connect()` so it cannot touch the database. |

Nothing else was written. `PROGRESS.md`, `scrapers/`, `scripts/expand_catalogue.py`, `schema/`, `docs/`,
`.github/` are untouched. One scratch analysis script was written to
`C:\Users\TOSHIBA\AppData\Local\Temp\opencode\t2_sweep.py`, outside the repository, to sweep the
archives for changed strings; it is not part of the project.

## Verified

### 1. The defect, reproduced — before the change

Command: `.venv\Scripts\python.exe -X utf8 scripts\link_product_nrn.py --self-test`

I added the fixture harness **first, with the old parser still in place**, so this is the real
before-state and not a reconstruction. `exit=1`, `self test: FAILED (11 failing)`:

```
product strength     register strength    equal  want  result  why
----------------------------------------------------------------------------------------------------------------------
20/120MG             20 mg; 120 mg        False  True  FAIL    AMATEM -- the reported case
                     {1.2E+2 mg}                                      | {1.2E+2 mg, 2E+1 mg}
80/480MG             80 mg; 480 mg        False  True  FAIL    COARTEM -- first-line antimalarial
                     {4.8E+2 mg}                                      | {4.8E+2 mg, 8E+1 mg}
500/125MG            500 mg; 125 mg       False  True  FAIL    amoxicillin/clavulanate shape
                     {125 mg}                                         | {125 mg, 5E+2 mg}
100/12.5MG           100 mg; 12.5 mg      False  True  FAIL    decimal in the second component
                     {12.5 mg}                                        | {12.5 mg, 1E+2 mg}
20/120 mg            20 mg; 120 mg        False  True  FAIL    space before the unit, no space at the slash
                     {1.2E+2 mg}                                      | {1.2E+2 mg, 2E+1 mg}
100/12,5MG           100 mg; 12.5 mg      False  True  FAIL    comma decimal in the second component
                     {12.5 mg}                                        | {12.5 mg, 1E+2 mg}
80/480MG             480 mg; 80 mg        False  True  FAIL    order-insensitive, as rule 2 requires
                     {4.8E+2 mg}                                      | {4.8E+2 mg, 8E+1 mg}
60mg+30mg            30 mg; 60 mg         True   True  PASS    plus-separated pair, order-insensitive
                     {3E+1 mg, 6E+1 mg}                               | {3E+1 mg, 6E+1 mg}
500MG                500 mg               True   True  PASS    one plain strength
                     {5E+2 mg}                                        | {5E+2 mg}
80MG/480MG           80 mg; 480 mg        True   True  PASS    unit repeated on both sides -- one token each, already
                     {4.8E+2 mg, 8E+1 mg}                             | {4.8E+2 mg, 8E+1 mg}
500MG/5ML            500 mg; 5 ml         True   True  PASS    a concentration, already two tokens -- must stay two
                     {5 ml, 5E+2 mg}                                  | {5 ml, 5E+2 mg}
1/2 TAB              2 TAB                True   False FAIL    a half-tablet dose must not equal a two-tablet one -- it does today
                     {2 tab}                                          | {2 tab}
20/120MG             20 mg                False  False PASS    a combination is not one of its components
                     {1.2E+2 mg}                                      | {2E+1 mg}
80/480MG             480 mg               True   False FAIL    the component-only register row must not win
                     {4.8E+2 mg}                                      | {4.8E+2 mg}
5/5                  5 mg                 False  False PASS    no unit after the pair: not a strength at all
                     (none)                                           | {5 mg}
30/70                30 mg; 70 mg         False  False PASS    an insulin ratio with no unit -- must not invent mg
                     (none)                                           | {3E+1 mg, 7E+1 mg}
250/5 SUSP           250 mg; 5 ml         False  False PASS    'per 5 ml' is a concentration, not two strengths
                     {5 susp}                                         | {2.5E+2 mg, 5 ml}
500MG                250 mg               False  False PASS    plain different strengths never match
                     {5E+2 mg}                                        | {2.5E+2 mg}

strength fixtures: 9/18 pass

--- choose() verdicts (one candidate each) ---
  FAIL  slash strength vs semicolon register             want=link   rejected         (no candidate survived strength/form (1 strength, 0 form))
  PASS  plain strength, passes today                     want=link   linked TEST-0    (active, 1 qualified of 1)
  FAIL  combination vs a component-only register row     want=reject linked TEST-0    (active, 1 qualified of 1)
  PASS  plain strength vs a different strength           want=reject rejected         (no candidate survived strength/form (1 strength, 0 form))

choose fixtures: 2/4 pass

self test: FAILED (11 failing)
```

This is the brief's claim, measured: `20/120MG` → `{120 mg}`, the register → `{20 mg, 120 mg}`. Note the
amounts print as `Decimal.normalize()` renders them (`1.2E+2`, not `120`); both sides go through the
same converter, so the comparison is unaffected — see "Second defect reported, not fixed" below.

### 2. After the change

Same command. `exit=0`, `self test: OK (0 failing)`:

```
strength fixtures: 18/18 pass

--- choose() verdicts (one candidate each) ---
  PASS  slash strength vs semicolon register             want=link   linked TEST-0    (active, 1 qualified of 1)
  PASS  plain strength, passes today                     want=link   linked TEST-0    (active, 1 qualified of 1)
  PASS  combination vs a component-only register row     want=reject rejected         (no candidate survived strength/form (1 strength, 0 form))
  PASS  plain strength vs a different strength           want=reject rejected         (no candidate survived strength/form (1 strength, 0 form))

choose fixtures: 4/4 pass

self test: OK (0 failing)
```

The seven rescues, with the token sets they now produce:

```
20/120MG             20 mg; 120 mg        True   True  PASS    AMATEM -- the reported case
                     {1.2E+2 mg, 2E+1 mg}                             | {1.2E+2 mg, 2E+1 mg}
80/480MG             80 mg; 480 mg        True   True  PASS    COARTEM -- first-line antimalarial
                     {4.8E+2 mg, 8E+1 mg}                             | {4.8E+2 mg, 8E+1 mg}
500/125MG            500 mg; 125 mg       True   True  PASS    amoxicillin/clavulanate shape
                     {125 mg, 5E+2 mg}                                | {125 mg, 5E+2 mg}
100/12.5MG           100 mg; 12.5 mg      True   True  PASS    decimal in the second component
                     {12.5 mg, 1E+2 mg}                               | {12.5 mg, 1E+2 mg}
20/120 mg            20 mg; 120 mg        True   True  PASS    space before the unit, no space at the slash
                     {1.2E+2 mg, 2E+1 mg}                             | {1.2E+2 mg, 2E+1 mg}
100/12,5MG           100 mg; 12.5 mg      True   True  PASS    comma decimal in the second component
                     {12.5 mg, 1E+2 mg}                               | {12.5 mg, 1E+2 mg}
80/480MG             480 mg; 80 mg        True   True  PASS    order-insensitive, as rule 2 requires
                     {4.8E+2 mg, 8E+1 mg}                             | {4.8E+2 mg, 8E+1 mg}
```

And the rows that must **not** become equal, still unequal:

```
20/120MG             20 mg                False  False PASS    a combination is not one of its components
80/480MG             480 mg               False  False PASS    the component-only register row must not win
5/5                  5 mg                 False  False PASS    no unit after the pair: not a strength at all
30/70                30 mg; 70 mg         False  False PASS    an insulin ratio with no unit -- must not invent mg
250/5 SUSP           250 mg; 5 ml         False  False PASS    'per 5 ml' is a concentration, not two strengths
1/2 TAB              2 TAB                False  False PASS    a half-tablet dose must not equal a two-tablet one -- it does today
```

The last row is a second wrong pair this change *removes*: `1/2 TAB` equalled `2 TAB` before, and no
longer does. It was not a goal, and no fixture depends on it, but it is a narrowing and is listed.

### 3. `choose()` gives the same verdict for a pair that passes today

Required by the brief. In both runs, "plain strength, passes today" (`500MG` product against a
`500 mg` / `Tablet` / `Active` candidate) returns **linked TEST-0 — active, 1 qualified of 1**. Before
and after, identical. And "plain strength vs a different strength" (`500MG` vs `250 mg`) is rejected in
both. So the change widens nothing outside the slash form.

The one verdict that *does* change is intended: `80/480MG` product against a `480 mg` register row was
**linked before and rejected after**. That is the same defect seen from the other side — the
old parser let a combination product match a register that states only its second component.

### 4. Offline sweep of every real string on disk — the widening test

Fixture tables are written by the person who wrote the change, so I also diffed old against new over
every string available offline: `seed/medprices.csv` (all 88 alias columns) plus every title in
`archives/{healthplus,medplus,drugstore,nafdac_index,nafdac_details}`.

Command: `.venv\Scripts\python.exe -X utf8 C:\Users\TOSHIBA\AppData\Local\Temp\opencode\t2_sweep.py`

```
distinct strings scanned: 14788 (from 53533 values)
strings whose token set changed: 308
  of those, containing a slash: 308
  of those, NO slash in the string: 0
...
changed strings whose EVERY token is a mass/volume unit: 105
changed strings with at least one non-mass unit: 203
```

**Zero strings changed that do not contain a slash.** The blast radius is the slash form and nothing
else — no `500MG`, no `60mg+30mg`, no `500MG/5ML` moved.

The 105 all-mass cases are the rescues, and they are the drugs the ticket named:

```
[nafdac_index] Lumartem 20/120 mg      before {1.2E+2 mg}   after {1.2E+2 mg, 2E+1 mg}
[nafdac_index] Tacen Tablet 80/480 mg  before {4.8E+2 mg}   after {4.8E+2 mg, 8E+1 mg}
[nafdac_index] Cardiotan 40/10 mg      before {1E+1 mg}     after {1E+1 mg, 4E+1 mg}
[nafdac_index] Telduret 40/12.5 mg Tablets  before {12.5 mg}  after {12.5 mg, 4E+1 mg}
[nafdac_index] Valsartil 160/12.5 mg Tablets before {12.5 mg} after {1.6E+2 mg, 12.5 mg}
[seed] Myclav 375/625 Tablets          before {625 tablets} after {375 tablets, 625 tablets}
```

Amatem, Coartem, Lumartem, Mefartem, Lynsunate, Actimax, Salumether — artemether/lumefantrine;
Cardiotan and Valsartil and Telduret and Amlosartan — amlodipine/valsartan/HCTZ combinations. These are
two-ingredient products whose register *name* carries `A/B`, which is the class the linker was
rejecting.

## Over-matching: the risk, in concrete terms

The 203 changed strings with a non-mass unit are the risk, and they are all one shape: **a slash chain
followed by a dosage-form word, where the numbers are a ladder of alternatives or a pack count, not two
active ingredients.**

| Real string on disk | Before | After | What it actually means |
|---|---|---|---|
| `Lisiofil 2.5/5/10 Tablets` | `{10 tablets}` | `{2.5, 5, 10 tablets}` | three pack **sizes** in one cell: 2.5 mg, 5 mg *or* 10 mg — not a combination |
| `Cefuxime 125/250/500 Tablets` | `{500 tablets}` | `{125, 250, 500 tablets}` | same: a strength ladder |
| `CEFUZAR-250/500 Tablets` | `{500 tablets}` | `{250, 500 tablets}` | same |
| `Excelxin 80/640 Suspension` | `{640 suspension}` | `{80, 640 suspension}` | same |
| `250/5 SUSP` | `{5 susp}` | `{250, 5 susp}` | `250 mg per 5 ml`, a concentration |
| `1/2 TAB` | `{2 tab}` | `{1, 2 tab}` | half a tablet |

What happens to a pair if one of these is treated as a strength: **the token set is a set of numbers
with a unit string attached, so two ladder strings with the same numbers now compare equal, and a
ladder no longer compares equal to its own single-strength row.** Concretely, `Cefuxime 125/250/500
Tablets` and `Cefuxime 125/250/500 Tablet` (singular) are now equal on the numbers and differ only by
the unit word, and `Lisiofil 2.5/5/10 Tablets` no longer equals a `Lisiofil 10 Tablets` row that shares
its last number. Both sides are junk tokens — a form word is not a strength unit — but before this
change the junk was one number and now it is up to three, so a fatter set is available to coincide with.

Three things bound the damage:

1. **No unit, no tokens.** `5/5`, `30/70`, `1/2` with nothing after them still produce `(none)`, so a
   bare ratio can never enter a comparison. Only a slash chain *followed by a word* is read.
2. **`expand_catalogue.py` already drops form-word units.** Its `strength_core()` filters anything in
   `FORM_UNITS`, which contains `tablet/tablets/suspension/...`, so for the ladder shape it filters
   **every** token to nothing and returns `None` — "this side states no comparable strength". Its
   *comparison* is therefore unchanged by the ladder case. Its `strength_key()` (the dedupe triple) is
   **not** filtered — see open risks.
3. **Ingredient names are not in the token set at all.** `20/120 mg` equals `20 mg; 120 mg` whether the
   pair is artemether/lumefantrine or anything else with those numbers. That looseness predates this
   ticket (rule 2 is numeric-tokens-only by design) and this change does not add to it, but it now
   applies to two-number sets as well as one-number sets, which is a slightly wider net of numbers that
   can coincide.

**My judgement:** the `mg`/`ml`/`mcg` cases are unambiguous rescues and are worth far more than the
ladder cases cost, because a ladder token already could not compare correctly before (a form word was
its unit) and the linker picks one registration per product, ranked Active first, so a false positive
stays a *suspect* link rather than a price. I did not gate on the unit being a mass unit, because that
means a second closed list of units in the matcher and the register uses `iu`, `%` and `mg/ml` too —
reported as a possible tightening, not done.

## Second defect reported, not fixed

`strength_tokens()` reads a **comma as a decimal point**, so a thousands separator becomes a fraction:

```
Decimal("1,000".replace(",", ".")).normalize()  ->  1
```

`"1,000MG"` therefore yields `('1','mg')` against a register's `('1E+3','mg')` — a rejection for a
1000 mg product. The comma was presumably meant for European decimals (`12,5`), and the offline sweep
shows the register does use `12,5`; both conventions appear in the same field and no rule can tell
`1,000` from `12,5` without context. Not fixed: the brief says a second defect in the same function is
reported, not fixed, and the fix needs a decision about which convention wins.

Also noted, not a defect: amounts are stored as `Decimal.normalize()` renders them, so `120` becomes
`1.2E+2` and `20` becomes `2E+1`. Both sides of every comparison go through the same converter, so
equality is unaffected; it only makes the self-test output uglier. Changing it would change what a
single strength looks like, which the brief puts out of scope.

## Deviations

1. **The fixture table lives inside `scripts/link_product_nrn.py` as `--self-test`**, not in a test
   file. The brief allowed three files and forbade the rest; a test that cannot be written as a file
   has to be a flag, and a flag is re-runnable by whoever reads this. It short-circuits before
   `db_connect()`, so it cannot touch the database.
2. **One scratch script was written to the OS temp directory**, not the repo
   (`...\Temp\opencode\t2_sweep.py`), to diff old against new over the archives. It is throwaway and is
   not committed; the archive sweep it performed is what the numbers in §4 come from.
3. **The `.agent/T2-report.md` and `.agent/T2-progress.md` files already existed** from a *different*
   ticket that used the number T2 on 2026-11-08 (the `parse_pack`/HealthPlus `unit_price` scope, which
   `PROGRESS.md` still cites). I appended to the progress file and kept the older report below this
   one rather than overwriting it — deleting the artifact a state file points at would have been a
   worse outcome than a file holding two reports.
4. **One fixture row of my own was wrong and I corrected it before the before-run I report.** I first
   asserted `1/2 TAB` equals `1/2 Tablet`; it does not, because the unit token is the raw word and
   `tab` != `tablet`. That is a unit-synonym defect in the same function, not a slash defect, so the
   row was replaced with `1/2 TAB` vs `2 TAB` and the synonym issue is named below instead.

5. **Another session wrote `scrapers/medplus.py` during this ticket.** `git status --short` was clean
   of it when I started and shows `M scrapers/medplus.py` (+167 lines, written 04:11:49) now; that is
   the ticket the brief said owns that file, not me. Reported, not touched, and it is unrelated to the
   strength parser. **A reviewer reading a combined diff should not attribute it to this ticket.**

## Open risks

1. **The ladder over-match, above.** 203 real strings now carry more tokens than they did, including
   three-number chains. Nothing gates on the unit being a mass or volume unit.
2. **`expand_catalogue.py` inherits the new behaviour and was not run.** It imports `choose`,
   `compatible`, `form_families` and `strength_tokens` directly. Two specific consequences I did not
   measure: its `strength_core()` should be unaffected (form-word units are filtered out), but its
   `strength_key()` feeds `triple_key()`, the dedupe key for new products, and the key's *text* changes
   for every slash title — `Cefuxime 125/250/500 Tablets` goes from one key string to another. Whether
   that can create a duplicate product depends on whether the existing side of that comparison is
   recomputed from the register/titles or read back from `products.strength`, which I could not check
   without the database. **Check this before the next `--apply` of the expander.**
3. **The 610 figure is unmeasured.** It comes from `PROGRESS.md`, was measured on 2026-11-09/10, and
   this ticket did not re-measure it. Nothing here confirms that 610 is the number of pairs the fix
   rescues.
4. **Existing links are not recomputed.** The change affects the next run of the linker, and only for
   products `where nafdac_registration_number is null` unless `--refresh` is passed. Products already
   linked, or already given up on, keep whatever the old parser decided. A re-link of the antimalarials
   needs `--refresh --min-similarity 0.35` deliberately.
5. **A narrowing nobody asked for.** Any pair where the *register* states only one component and the
   shop states the combination (`80/480MG` vs `480 mg`) stops linking. That is the correct reading of
   rule 2, and the brief's fixture table requires it, but it is a behaviour change in the
   rejecting direction and it is not free: a register row that only ever records the second component
   was previously reachable and now is not.
6. **Unit strings are not normalised.** `tab` != `tablet`, `Tablets` != `tablet`. Pre-existing, outside
   this ticket, and it is why several fixture rows compare unequal for a reason that has nothing to do
   with strengths.

## Unproven

- **How many of the 610 "strength disagrees" rejections are actually rescued is not established by
  this ticket.** It needs a database run of `scripts/link_product_nrn.py --refresh --dry-run
  --min-similarity 0.35` and a comparison of the rejection counts before and after. The change is
  only proven at the parser level.
- **No pair was linked, and no stored row was recomputed.** By design: no database was reachable, and
  the brief's own constraint says the change cannot take effect until someone next runs the linker.
- **The real register's `strength` column values were not available offline.** My sweep covers register
  *names* from `archives/nafdac_index` and shop titles, not the 1,848 status-bearing rows' `strength`
  field. The distribution of `A/B` strings in that column is therefore assumed, not measured.
- **The over-match risk is bounded by reasoning, not by a measured false-positive count.** No
  cross-check exists yet for "did this new link attach the wrong registration". `v_suspicious_listings`
  would move if it did, and that has to be watched on the first run.


---

# Earlier report under the same ticket number (2026-11-08) - parse_pack / HealthPlus unit_price scope

Kept verbatim: PROGRESS.md cites this file for that finding. It is a different defect from the one above.

# T2 report — `unit_price` defect scope

**Written by the secretary, not the agent.** `data-explorer` hit its **20-step** cap (raised from 8
earlier the same session) after establishing the headline number but before writing this file. Every
figure below was re-run by the secretary; the agent's own claims are marked where they were confirmed
or corrected.

## Answer

**No stored HealthPlus listing carries a wrong `unit_price` from slash-strength parsing. The count is
zero, and it is a real zero, not a vacuous one.**

| Measure | Value |
|---|---|
| HealthPlus latest listings | 1,197 (2,396 rows all-time) |
| Titles containing a slash pair `\d+/\d+` | **31** |
| Of those, stored `(pack_size, pack_unit)` differs from the guarded parse | **0** |
| Of those, where the stored pack is non-null | 30 of 31 |
| Slash-titled rows reaching `v_cheapest_per_product_state` | **1** |
| Of those, `is_comparison = true` | **0** |

The reason is in the titles themselves. HealthPlus writes strengths with the unit attached —
`80/480Mg`, `500/125mg`, `150/5mg` — and `parse_pack` then takes the explicit pack count instead:
`Atacand Plus 16/12.5mg x28 Tablets` → `(28, tab)` both with and without the guard. The bug fires on
the *other* shape, `80/480 Tablets` (space, then a form word, no count), which HealthPlus does not
appear to use. Proven synthetic case: `Coartem 80/480 Tablets x6` → `(480, tab)` unguarded,
`(6, tab)` guarded.

**Verdict: not a publication blocker today.** The guard is still worth adding to `healthplus.py`
eventually, because the vulnerability is live for the next title that uses the bare form.

## The finding that matters more

The scan surfaced a defect that is **already live in the published claim**, and it is not the one the
ticket was about.

`schema/003_views.sql:78-83` ranks with `order by b.price_ngn asc` — it compares **sticker price**,
not `unit_price`. `PLAN.md:70` states the pack columns exist so the view does not "compare a 12-tablet
pack to a 500-tablet jar". They exist and are selected, but the ranking never uses them.

| Measure | Value |
|---|---|
| Cells in `v_cheapest_per_product_state` | 85 |
| Cells where the product has more than one pack size in-stock | **15** |
| Of those, the chosen row is **not** the best per unit | **9** |

Two unambiguous cases, both Lagos, both single-pharmacy:

- **Ciprofloxacin** — chosen `₦5,180` for a **10**-pack (`₦518.00`/unit). A **14**-pack at `₦7,060`
  is `₦504.29`/unit, i.e. cheaper per tablet. The view calls the 10-pack cheapest.
- **Cefixime** — chosen `₦4,100` for a **60**-pack (`₦68.33`/unit). A **100**-pack at `₦5,160` is
  `₦51.60`/unit. Same error, larger.

A related data-quality signal fell out of the same query: **Atorvastatin, Lagos** has nine in-stock
listings at two pack sizes with prices from `₦2,760` to `₦35,460` for what the catalogue treats as
one product — a 13× spread. Either the matching is over-merging distinct strengths, or the listings
include different products. Not investigated here.

## Verified

```powershell
# 31 slash-titled latest HealthPlus rows, stored vs guarded, one by one
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -X utf8 "$env:TEMP\opencode\verify_t2.py"
# -> slash-titled latest HealthPlus rows: 31
#    stored pack non-null: 30 of 31
#    stored != guarded: 0
#    slash-titled rows reaching v_cheapest_per_product_state: 1, of which comparisons: 0

# pack-size-blindness of the ranking
.venv\Scripts\python.exe -X utf8 "$env:TEMP\opencode\arenax_check.py"
# -> cells: 85 | cells with >1 pack size: 15 | of those, chosen row is NOT the best per-unit: 9
```

Read directly: `schema/003_views.sql:80` — `order by b.price_ngn asc, b.pharmacy_id asc`.

## Deviations

- The agent did not write this report; it hit its 20-step cap at the falsification check. Its progress
  file (`.agent/T2-progress.md`) worked as designed — four lines, and it named the exact gap it had
  left rather than claiming completion.
- The agent's provisional verdict ("not a blocker today, guard still required") was **correct**, and
  its reading of the ranking column was **correct** — `PLAN.md:70` is the document that is wrong.

## Unproven

- Whether any HealthPlus title in the *catalogue* (not the latest 1,197) uses the bare `80/480 Tablets`
  form. Only the latest set was scanned.
- Whether ranking on `unit_price` is even viable: `unit_price` is populated on 52.7% of HealthPlus
  listings, and several cheapest cells have `unit_price IS NULL`.
- The Atorvastatin price spread — over-merged product, or genuinely different items.
