# T1112-b report — the card is now a numbered checklist

**Vintage/registry:** none. This ticket touches no `registry/` directory and writes no data. Every
number below is read from the live database at build time; nothing was frozen.

## 1. Changed

| Path | What changed |
|---|---|
| `scripts/build_verify_desk.py:76` | `LICENCE_QUESTIONS` — the five licence questions, fixed text and order, defined once. The page renders its text from here and the self-check asserts the page carries exactly this list. |
| `scripts/build_verify_desk.py:83` | `PACK_QUESTIONS` — the six pack questions, same treatment. |
| `scripts/build_verify_desk.py:96` | `HEURISTIC_SENTENCE` — the "mass units only" label, printed on every card that shows a strength warning and in the footer. |
| `scripts/build_verify_desk.py:263` | `MASS_RE` / `mass_tokens` — mg, mcg, µg, ug, g, iu, %; grams normalised to milligrams. |
| `scripts/build_verify_desk.py:290` | `strength_contradiction()` — returns a sentence only when both sides carry a mass and share no value, otherwise `None`. Conservative by design. |
| `scripts/build_verify_desk.py:307` | `FORM_PATTERNS` / `form_of()` — the form read from a shop title, because `pharmacy_listings` has no form column. Silent when a title names none. |
| `scripts/build_verify_desk.py:418` | `build_licence()` — now emits `flags` (the red strip) and `questions` (5 lines, each with `evidence` and an optional computed `auto`). Line 5 carries a computed answer: Active + past expiry is a data-fail. |
| `scripts/build_verify_desk.py:533` | `build_pack()` — 6 lines. Line 2 computes same/differs/not stated across title strengths; line 3 same/differs for form; line 4 pack count; line 5 "two different shops" with the pharmacy names; line 6 stock. `same_shop` flag added. |
| `scripts/build_verify_desk.py:511` | `PACK_UNIT_WORDS` / `normalise_pack_unit()` — `tab`, `tabs`, `tablet` compare equal, so one card says `56 tablet vs 25 tablet vs 35 tablet` instead of `56 vs 25 tab vs 56 tab`. |
| `scripts/build_verify_desk.py:726` | CSS — checklist line, focus ring, computed-answer strip, flag strip, outcome box, tally table. Contrast kept at the previous palette's ratios; the focus ring is 4 px `#ffe08a` plus the accent outline. |
| `scripts/build_verify_desk.py:848` | `STORE_KEY = 'ndw.verify.answers.v2'`. The v1 keys are read only to decide whether to show the one-line notice. |
| `scripts/build_verify_desk.py:935` | `load()` — rebuilds each entry line by line, **assigns it before** recomputing the outcome, and writes the corrected outcome back if storage disagreed. |
| `scripts/build_verify_desk.py:1011` | `outcomeOf()` — any `fail` → fail; every `pass` → pass; otherwise incomplete with the offending line numbers. `cannot` counts as not-pass. |
| `scripts/build_verify_desk.py:1492` | `answerFocused()` — sets the focused line, advances, and from the last line moves to the next card. |
| `scripts/build_verify_desk.py:1690` | `buildExport()` — `checklist_version`, `generated_utc`, `data_as_of`, `data_built_utc`, per-card line answers + note + recomputed outcome + `at`, and `line_fail_counts`. |
| `scripts/build_verify_desk.py:1792` | `SHELL` — keyboard list (arrows, p/f/u, o, n, Esc, [ ]), v1 notice element, tally region, no verdict section. |
| `scripts/build_verify_desk.py:~2000` | `self_check()` — 2,466 checks: question count and order per card, evidence present on every line, no answer/outcome key in the payload, flag counts recomputed from rows, line 5 must be a computed Fail where both rows are one shop, v2 key and `checklist_version: 2` present, the heuristic labelled, no `http` outside the data block. |
| `scripts/build_verify_desk.py:~2150` | `write_fixture()` — `--fixture` builds a labelled two-card page from synthetic rows. |
| `site/verify/index.html` | Rebuilt: 419,254 bytes, 89 licence cards, 45 pack cards. |
| `site/verify/demo.html` | New, 59,138 bytes. **Synthetic**, labelled on every card. |
| `site/verify/_selftest.cjs` | New: drives headless Edge over CDP from `file://`, presses real keys, prints what changed. Test harness only; the page never loads it. |

## 2. Verified

**Build (real database, read-only):**

```
> .venv\Scripts\python.exe -X utf8 scripts\build_verify_desk.py
wrote site/verify/index.html (419,254 bytes)
licence cards embedded: 89 products, 163 shop listings, 5 questions each
pack cards embedded:    45 cells, 132 shop rows, 6 questions each
computed warnings: 4 licence cards and 5 pack cards carry a strength disagreement; 0 pack cards have both rows from one shop
data as of: 2026-11-11 11:26 UTC (prices 2026-11-11 11:35 UTC, register 2026-11-11 11:26 UTC)
2,466 checks passed, 0 failed
BUILD_EXIT=0
```

```
> .venv\Scripts\python.exe -X utf8 scripts\build_verify_desk.py --fixture site\verify\demo.html
fixture: wrote site/verify/demo.html (59,138 bytes)
fixture: licence card flag -> HealthPlus: title says 800 mg, product says 400 mg
fixture: pack card line 5 -> Fail - both rows are HealthPlus
fixture: pack card line 4 -> 20 tablet vs 25 tablet - differs
fixture: 51 checks passed, 0 failed
FIXTURE_EXIT=0
```

**Browser (`node site/verify/_selftest.cjs`, exit 0, real Edge, `file://`):**

Done-means 2 — questions in order, evidence beside them, nothing pre-selected:

```
=== licence card, nothing pressed ===
  1. Does the register page open and show this registration number?
  2. Does the page's status match what we recorded?
  3. Does the page's expiry date match what we recorded?
  4. Is this the same medicine - name, strength and form?
  5. Does the register contradict itself - a status of Active with an expiry date already past?
buttons: 1[pass=false fail=false cannot=false] | 2[...] | 3[...] | 4[...] | 5[...]
outcome: Outcome: incomplete computed from the ticks, never asked for / not answered on lines 1, 2, 3, 4 and 5.
```

Pack card, six lines, each computing its own answer where the data settles it:

```
  2. ... :: answered by data differs - MedPlus states a different mass from the product
  3. ... :: answered by data same - tablet in every title that names one
  4. ... :: answered by data 56 tablet vs 25 tablet vs 35 tablet - differs
  5. ... :: answered by data Pass - HealthPlus and MedPlus are different shops
  6. ... :: answered by data in stock at every shop
```

Done-means 3 — same shop twice, computed before any key (on `demo.html`, because the measured data has
**0 of 45** such cells):

```
line 4: answered by data 20 tablet vs 25 tablet - differs
line 5: answered by data Fail - both rows are HealthPlus
```

Done-means 4 — a real licence card whose attached listing contradicts the product, no key pressed:

```
=== licence cards carrying a strength warning: 4 ===
card licence-47 flags, before any key:
["Attached medicine looks wrong. HealthPlus: title says 5 mg, product says 10 mg (Norvasc (Amlodipine) 5mg Blister x 10)"]
```

Done-means 5 — keyboard, what was pressed and what changed:

```
=== after p ===
{"focus":"line-2","pressed":["1:pass=true ..."],"outcomeBody":"not answered on lines 2, 3, 4 and 5."}
=== after ArrowDown ArrowDown ===   focus: line-4
=== after ] then [ ===              card after ]: Card 2 of 89 | card after [: Card 1 of 89, line 1 still answered
=== n, typed a note, Escape ===     focus after n: note, after Escape: BODY
=== after a reload ===              line 1 still pass, note kept, outcome recomputed
=== p, p, p, p, then f on the last line ===
before f - focus: line-5
after f  - Card 2 of 89, focus: BODY
stored: licence-2225 -> {..., "5":"fail", "outcome":"fail"}
filters: ["All (89)","Open (88)","Fail (1)"]
```

Done-means 6 — export parses, carries per-line answers and a computed outcome; an edited line changes it:

```
parses: true | keys: checklist_version,generated_utc,data_as_of,data_built_utc,note,cards,line_fail_counts
generated_utc: 2026-11-12T07:35:15.394Z | data_as_of: 2026-11-11 11:26 UTC | checklist_version: 2
first card: licence-2225 -> {"1":"pass","note":"...","outcome":"incomplete","at":"..."}
=== stored outcome says pass; line 5 stored as fail; a v1 key is present ===
licence outcome on screen: Answered Fail on line 5.
v1 notice shown: true
storage after load: licence-900001 -> {"1":"pass",...,"5":"fail","outcome":"fail"} | pack-900002-Lagos -> {"1":"pass","2":"fail","3":"pass","outcome":"fail"}
pack outcome on screen (stored says pass, line 2 is fail): Answered Fail on line 2.
```

Done-means 7 — `errors and warnings: none`.

**Two defects the harness caught, both fixed before this report:** while answering, the card's own
outcome was correct but the stored string stayed `incomplete` after a reload (the recompute read the
entry before assigning it); and the pack line read `56 vs 25 tab vs 56 tab vs 35 tab` (units not
normalised). Re-ran both after fixing; output above is from the final code.

## 3. Deviations

1. **Done-means 3 could not be met on real data.** I measured it first: `0 of 45` comparison cells
   have fewer than two distinct shops, and `is_comparison` is defined as two pharmacies, so this case
   cannot appear until the view's rule changes or a scrape collapses two shops into one. I did not
   fake a card inside `index.html`. Instead `--fixture` builds a separate, loudly labelled page from
   synthetic rows through the same builders and the same self-check, and the main build still prints
   `0 pack cards have both rows from one shop`. **Line 5 is nonetheless live code on every real card**
   — the harness confirms it computes `Pass - HealthPlus and MedPlus are different shops` there — and
   the self-check fails the build if a same-shop card ever appears without the computed Fail.
2. **Question 3 (same form) is a heuristic, not a reading.** `pharmacy_listings` has no form column,
   so the form comes from the shop's own title by keyword. Where a title names none the line says
   `title names no form` and the computed answer says `not stated` rather than guessing. Say so if a
   reader asks why the form line is often blank.
3. **A third file was added under `site/verify/`** — `_selftest.cjs`. The brief allowed "files under
   `site/verify/`" and forbade touching anything else, so the harness lives beside the page rather
   than in `scripts/`. It needs `node` and a local Edge; it installs nothing.
4. **`--fixture` was not in the brief.** It exists only because of deviation 1, and it writes only
   when asked for by that flag.
5. **Two smaller decisions:** `cannot tell` counts as not-pass, so a card cannot pass with unanswered
   questions; and clicking a Pass/Fail button sets that line without advancing, while the keys
   advance. Both are stated on the page.
6. **The old filters were kept and renamed** (`All` / `Open` / `Fail`) rather than dropped, since v1
   had them and the computed outcome gives them a sharper meaning.

## 4. Open risks

- **Which question cannot be answered from the data shown:** line 2 of the licence card ("does the
  page's status match what we recorded?") and line 3 ("does the expiry date match?") show only *our*
  recorded value. The reader must open the register and compare by eye; the card cannot pre-answer
  them and does not pretend to. The same is true of pack line 1 (does the page show this price) and
  licence line 1 (does the page open at all). Four of eleven lines are pure observation.
- **The computed outcome can disagree with what the reader believes they answered**, in two ways.
  (a) A card with `cannot tell` on one line is `incomplete`, not "I looked and could not decide" — the
  page says which lines, but the word "incomplete" may read as "you did not finish". (b) Line 5 on a
  licence card can be a data-computed `Fail` (Active with a past expiry) while the reader, having
  looked at a page that now says Inactive, answers `Pass`. The tick wins; the data answer is only a
  badge. That is deliberate, but it means the strip and the ticks can point opposite ways.
- **The strength heuristic over-reports in one class:** a concentration. `228mg/5ml` against a product
  of `1000+200 mg` is flagged, and that one is a genuine defect, but a legitimate `250 mg/5 ml` against
  `250 mg` would also be flagged if the numbers differed only by the volume. It uses mass units only
  and says so on every card; it must not be read as "these are different medicines".
- **`is_comparison` cells can carry up to 12 shop rows** (measured max). A six-line checklist over 12
  rows of evidence is long on a phone; the evidence is one line per shop, so it does not become a
  table, but it is the longest card on the page.
- **`localStorage` is per file path.** A reader who moves the HTML to another folder starts with an
  empty store, and the export is the only way across. Unchanged from v1, still true.
- **A `v1` key is reported, not migrated.** Deliberate: turning one verdict into five answers would be
  inventing answers. The notice says so.

## 5. Unproven

- **Whether six lines is the right number.** Nothing here measures completion. On the evidence of one
  session the pack card takes six key presses per card, and 45 cards is 270 presses; the licence card
  is 445. Whether a person finishes six lines honestly or starts pressing `p` to make the card go away
  is not something a build can answer — it needs a real sitting, and the per-line tally is the only
  instrument that would show it (a question with a suspiciously high pass rate and no note is the
  signal).
- **Screen-reader reading order.** The lines are focusable groups with the question in their label and
  the evidence inside; NVDA and VoiceOver were not run. The accessibility claim here is structural
  (focus, labels, live region, contrast, 44 px targets), not audited.
- **axe.** Not run on the rebuilt page; v1's zero-violation result does not carry over to a new
  checklist layout.
- **Mobile at 430 px.** Measured for overflow in CSS only (evidence lines wrap, the tally scrolls in a
  `role="region"`), never looked at.
- **The two computed answers' accuracy as a set.** The harness proves they render and agree with the
  rows; nobody has checked the 5 pack cards and 4 licence cards they flag against the real pages. The
  27-listing strength finding of 2026-11-12 is the reason the check exists, not proof that its verdicts
  are right.
- **Nothing is committed, pushed or deployed.** Both builds write local files; no database row was
  written (the connection is `default_transaction_read_only=on`); no other file in the repo was
  touched.
