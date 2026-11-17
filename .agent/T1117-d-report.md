# T1117-d — the 13 November purple study is now the front page

**One file changed: `scripts/build_site.py`.** The page it builds, `site/index.html`, is the purple
design study of 13 November with every number taken from the database. `about.html`, the database,
the schema and `build_dashboard.py` were not touched.

The author committed this work as `65dcaca` with three fixes of their own on top of it (the hero
caption's right edge, an invisible dashboard button, and the deep block sitting outside the `main`
landmark). Those three are recorded, and the correction to one of my own claims, in §1.

---

## 1. What the build says

```
$ $env:DATABASE_URL='postgresql://postgres:build@127.0.0.1:55440/ndw'
$ .venv\Scripts\python.exe -X utf8 scripts\build_site.py
...
wrote site/index.html (176,076 bytes, 44 comparison rows, 217 single-shop rows)
wrote site/data.json (131,976 bytes)
3,787 numbers checked, 0 unexplained
```

Exit code 0. The last line is the audit: every query behind the page was run twice, once to render and
once to re-read, and the two were compared leaf by leaf. **3,787 numbers, 0 unexplained** — the same
count the cream page reported, because the same seven facts are read and the same numbers are
printed.

### The contrast lines it prints

```
  contrast  about: band text on the band                 14.65:1  (#f7f0e6 on #2a1a20)
  contrast  about: gold text on the band                  8.49:1  (#e2b25c on #2a1a20)
  contrast  about: body text on the page                 16.82:1  (#1a1612 on #faf7f1)
  contrast  about: secondary text on the page             9.19:1  (#4a423d on #faf7f1)
  contrast  about: secondary text on a panel              8.27:1  (#4a423d on #f1ebdf)
  contrast  about: body text on a panel                  15.15:1  (#1a1612 on #f1ebdf)
  contrast  about: links on the page                     10.09:1  (#5f2a54 on #faf7f1)
  contrast  about: links on a panel                       9.09:1  (#5f2a54 on #f1ebdf)
  contrast  about: a warning on its own panel             8.51:1  (#7a2e00 on #fdf1e3)
  contrast  front: body text on the page                 17.79:1  (#120C19 on #F8F5FA)
  contrast  front: secondary text on the page             6.73:1  (#5B5270 on #F8F5FA)
  contrast  front: secondary text on a panel              6.15:1  (#5B5270 on #EFEAF5)
  contrast  front: body text on a panel                  16.26:1  (#120C19 on #EFEAF5)
  contrast  front: headings and links on the page        10.86:1  (#4A1E80 on #F8F5FA)
  contrast  front: headings and links on a panel          9.93:1  (#4A1E80 on #EFEAF5)
  contrast  front: headings and links on a tint          10.38:1  (#4A1E80 on #F4EFFA)
  contrast  front: a photograph caption                   6.73:1  (#5B5270 on #F8F5FA)
  contrast  front: a photograph caption on a tint         6.44:1  (#5B5270 on #F4EFFA)
  contrast  front: 'not active' on the page               9.08:1  (#7B1F4B on #F8F5FA)
  contrast  front: 'not active' on a panel                8.30:1  (#7B1F4B on #EFEAF5)
  contrast  front: 'active' on the page                   7.42:1  (#1c5c2e on #F8F5FA)
  contrast  front: 'not read' on the page                 6.73:1  (#5B5270 on #F8F5FA)
  contrast  front: band body text on the deep band        8.80:1  (#C3B7D2 on #2A0F45)
  contrast  front: band heading on the deep band         16.76:1  (#FFFFFF on #2A0F45)
  contrast  front: band tag on the deep band             12.76:1  (#E6DDF2 on #2A0F45)
  contrast  front: button text on its lavender plate      8.40:1  (#2A0F45 on #C6AEDF)
  contrast  front: white on purple                       11.74:1  (#FFFFFF on #4A1E80)
  decoration the REGISTER watermark on the page            1.51:1  (#4A1E80 at 22% over #F8F5FA paints as #D2C6DF) - hidden from assistive technology, read by nobody
```

Every pair a reader must read clears 4.5:1. The worst is 6.15:1 (secondary text on a panel). The
cream pairs are still measured, because `about.html` still wears the cream sheet: its content is
untouched and its stylesheet is the same one, renamed to `CSS_CREAM` so the front page can have a
sheet of its own.

The one line below the floor is the REGISTER watermark, and it is printed rather than hidden. See
§5.

### In a browser

| check | 1440 px | 375 px |
|---|---|---|
| axe-core 4.10.2, wcag2a/aa + wcag21a/aa + wcag22aa | **0 violations**, 27 passes | **0 violations**, 28 passes |
| `document.documentElement.scrollWidth` vs `innerWidth` | 1440 = 1440 | 375 = 375 |
| elements wider than the viewport outside a `.tablewrap` | none | none |
| embedded faces | Archivo Black: loaded, Inter: loaded | same |

The "incomplete" rows axe leaves are the ones it cannot resolve by itself: at 1440 px the six texts in
the three nav cards, at 375 px every cell inside the horizontally scrolling tables. Each of them was
checked by hand against the pair the build measures: nav-card heading 10.86:1 on the page and 9.93:1
on the panel, nav-card text 6.15:1, and in the tables the price in ink on paper 17.79:1, the unit and
note text 6.73:1, the *active* tag 7.42:1, the *not active* tag 9.08:1 and the *not read* tag 6.73:1.

**Correction, after the author's review.** This paragraph originally claimed the deep-block button
also measured 8.40:1. It did not: the button is an `<a>` inside the deep block, and the block's
`a { color: #C6AEDF }` beat the button's own `color`, so its label was painted the same violet as
its own plate and was invisible. The claim was wrong because the pair was read out of the CSS
instead of out of the computed style. The author's commit fixed it
(`.built a.dash{color:#2A0F45;background:#C6AEDF}`, now measured at rgb(42,15,69) on
rgb(198,174,223) = 8.40:1), and the button is no longer among axe's incomplete nodes. The lesson
belongs here: a contrast claim on this page is worth nothing unless the computed colour is the one
being claimed.

### Three defects the author's review found, and what changed

The author's commit `65dcaca` ("feat(index): the 13 November purple design is now the shipped main
page") carries this work and three fixes to it:

1. **The hero caption ran off the right edge at 1440 px.** Fixed with padding; the caption's text
   now ends 20 px inside the viewport (the box itself is flush with the edge, which is what makes
   the photograph bleed).
2. **The dashboard button in the deep block was invisible** — its label was the same violet as its
   own background, described above and fixed.
3. **The deep block sat outside any landmark.** It is now inside `<main>`, so the page has one
   `main` landmark and the block's heading, tags and link are inside it.

All three were found by running the checks, not by reading the code, and all three are fixed in the
committed file. The build still reports `3,787 numbers checked, 0 unexplained` on that state.

---

## 2. What changed, file by file

### `scripts/build_site.py` — the only file written

| where | what |
|---|---|
| palette block | The cream constants renamed `CREAM_*` (values unchanged, `about.html` unaffected) and a new purple palette added: `#4A1E80` purple, `#2A0F45` deep, `#7A4FB0` soft, `#120C19` ink, `#F8F5FA` paper, `#D9D0E4` rule, `#5B5270` muted, `#F4EFFA` tint, `#EFEAF5` panel, `#7B1F4B` not-active. These are the study's own colours, read off its CSS. |
| `FONT_ARCHIVO_BLACK`, `FONT_INTER`, `FONT_CSS` | The two typefaces, embedded as data URIs. |
| `REGISTER_WORD_PATH` | The word REGISTER as an SVG outline. |
| `NIGERIA_MAP_PATH` | The outline of Nigeria, one SVG path lifted from the study. |
| `DORA_COMMON_NAME`, `DORA_DG_FROM`, `DORA_DG_TO` | The name as the dedication uses it and the years she led NAFDAC, from the same National Library of Nigeria item as the dates. |
| `dora_years()`, `dedication_caption()`, `dedication_caption_html()` | The years, parsed out of `DORA_BORN`/`DORA_DIED` rather than typed; the dedication built from them. |
| `figure()` | One figure in the panel under the headline. |
| `CONTRAST_PAIRS`, `DECORATIVE_PAIRS`, `blend()`, `measure_contrast()` | The pairs are split by the page that uses them; the decorative pair is measured as the colour it actually paints. |
| `CSS_CREAM` / `CSS_PURPLE` | The old shared sheet is now `CSS_CREAM` (about.html); the new purple sheet is `CSS_PURPLE` (index.html). |
| `Page.build()` | Rewritten in the study's structure. |
| `main()` | The date guard now also calls `dora_years()`, so a build with an unset date stops before the database is opened. |

The `about.html` template is otherwise byte-for-byte the same file as before; the only edit inside it
is the name of the stylesheet it includes.

---

## 3. The numbers on the page, and where each one comes from

Nothing in the template is a literal. The panel of figures under the headline is the study's own
layout — three figures, then four — and every figure is a fact the audit re-reads:

| figure | value | fact |
|---|---|---|
| Prices read | 2,800 | `overview.latest_listings` |
| Prices matched to a medicine | 559 | `overview.matched_listings` |
| Two-shop comparisons | 44 | `overview.cells_comparison` |
| On an active registration | 298 | `registration.matched_active` |
| On a registration that is not active | 154 | `registration.matched_flagged` |
| On a status never read | 46 | `registration.matched_status_not_read` |
| Registrations in the register | 10,967 | `registration.registrations_total` |

The study's own figures — 2,793 prices, 342 matched, 43 comparisons, 10,925 registrations — are four
days stale and appear nowhere on the page.

One line was added under the panel so the three registration figures cannot be misread as a
partition of the 559: *"The three registration figures are the price rows whose medicine carries a
registration number. 61 of the 559 matched rows carry none."* Both numbers are existing facts
(`matched_no_registration_number`, `matched_listings`).

Nothing else changed in the numbers: the 44 comparison rows, the 217 single-shop rows, the four
registration buckets that add to 559, the 1,856 of 10,967 registrations with a status, the pipeline
panel and the six limitations are printed from the same facts as before.

---

## 4. The caption, and which photographs carry it

The author's wording: **"In beloved memory of Dora Akunyili. 1954 to 2014. Director-General of
NAFDAC, 2001 to 2008."** It is set in small muted type (12.5 px, `#5B5270`) directly beneath the
photograph, on the flat background, and it never overlaps the image.

- **Years.** `1954 to 2014` is not typed anywhere. `dora_years()` parses the year out of
  `DORA_BORN` ("14 July 1954") and `DORA_DIED` ("7 June 2014"), both from the National Library of
  Nigeria item, and the build refuses to run if either is unset. `2001 to 2008` are constants
  (`DORA_DG_FROM`, `DORA_DG_TO`) carrying the same source, quoted in `.agent/DORA-facts.md` row 3.
- **Hero portrait** (`assets/dora/dora-portrait.jpg`): captioned. The caption stands on the paper
  below the image — the image ends at y=898 and the caption runs from y=908 to y=944 at 1440 px.
- **Band photograph** (`assets/dora/dora-band.jpg`): captioned, and the band's own name-and-dates
  block was removed to make room for it. The band used to carry a display-face heading reading
  "Dora Nkem Akunyili OFR" with the dates underneath; keeping both would print the same sentence
  twice in one visual block, which is what the instruction forbids. The band now carries the caption
  and a heading that repeats neither the name nor the years ("The register she led") plus the same
  "where our reading falls short, the page says so" paragraph. **That was the choice: one treatment
  in the band, the caption.**
- **Footer mark** (`assets/dora/dora-mark.jpg`): no caption, as instructed. It is a decorative crop of
  the same photograph, not a photograph in its own right, and the footer already names her and the
  dates next to it.

The caption's own text is not attributed to anyone and carries no quotation marks: it is a
dedication, and the years and the title inside it are the sourced facts.

---

## 5. What the study asked for that could not be done as asked, and why

**The REGISTER word is drawn, not typed.** As a text node in the study's own style — purple at 22%
opacity over the paper — it measures 1.51:1, and axe-core reads every visible text node whatever
its role, so the page failed its own accessibility gate on that one element (confirmed: one
`color-contrast` violation, `.bleedword`). WCAG 1.4.3 exempts pure decoration from the 4.5:1 floor,
but an automated check cannot see that a word is decoration. So the word is now the same word in the
same face, drawn as an SVG outline and clipped by the base of the hero: a graphic, not a text node,
out of the accessibility tree entirely, with nothing on the page claiming to be readable lettering.
The build still measures and prints the colour it paints (1.51:1), because a value nobody measured is
a value nobody can argue with. The visible result is the study's: enormous, faint, cut off by the
base of the hero.

**Two of the five embedded faces are not carried over.** The study embeds five `@font-face` blocks:
Archivo Black, Instrument Serif regular, Instrument Serif italic, and two Inter subsets. The study's
own CSS never applies Instrument Serif — it is applied to nothing — so those two are not carried
over (43 KB of woff2 that would have been paid for in page weight and used for nothing). The display
face and the text face are both kept, embedded as data URIs, so the published page fetches nothing.
They are also subset to the characters this page prints: Archivo Black 18,604 → 11,788 bytes, Inter
48,256 → 29,948 bytes, with Inter's weight axis kept so the semi-bold in the tables is a real weight.

**The study's Inter at weight 400 could not be used as-is.** Its subset carries two ASCII characters
(157 glyphs, mostly Cyrillic), so in the study the body text silently fell back to the system stack
and only the bold text was Inter. The front page here uses the same family's Latin subset for both
weights, which is what the study meant.

**The study's "Pack" column is not in the tables.** The project's own record (`PROGRESS.md`, the
16 November check) says 18 of the 88 comparison listings carry a pack count with no unit recorded,
so a bare number under the heading "Pack" would print a figure the project has already recorded as
ambiguous. The tables keep their six columns — product, shop, price, stock tag, licence tag, price
per unit — and the unit that *is* known is printed beside every unit price, as before.

**The photographs are the project's own, not the study's CSIS ones.** The study's `img/face.jpg`,
`img/hero.jpg` and `img/band.jpg` are credited in the study's footer as CSIS, CC BY-NC-SA 2.0 — a
licence that forbids commercial use and is not recorded anywhere in this project's licence records
(`docs/assets/dora/CREDITS.md` holds the four Wikimedia files only). The project's own crop of the
National Library of Nigeria's CC0 portrait is used instead, in the study's arrangement. The hero's
watermark and the band's photograph are that CC0 file (`dora-portrait.jpg`, `dora-band.jpg`), credited
on the page as before.

**One smaller change.** The hero's headline is the study's ("What a medicine costs. Whether its
licence is active.") and the study's own `.cap` line under it was removed: the dedication now stands
under the photograph instead, and printing the same sentence twice in the hero is what the instruction
forbids.

---

## 6. What is on the page, in order

Masthead (wordmark, "Lagos. Prices read on 15 November 2026; collection stopped on 16 November
2026.", Nigeria outline) → hero (headline, frozen-snapshot stamp, the seven figures, the photograph,
the dedication, REGISTER across the base) → the three nav cards (dashboard.html, about.html, #data) →
Prices (the two kinds of row, the stock and licence note) → Two shops, compared (44 rows) → One shop
only (217 rows) → the tribute band → Registration status of what is sold (154 flagged, the four
buckets, and "not active records a lapsed or inactive registration, and is not evidence that the
medicine is fake or illegal") → The data behind this page (both published URLs) → Pipeline health
(with the "Age at freeze" column and the age-at-freeze wording) → What this page does not claim (all
six bullets) → Sources, licences and independence → How to check this page → the deep-purple block
(how the numbers were produced, the tags, the dashboard button) → footer (mark, her name and dates,
the image credit, the typeface credit).

Nothing from the cream page was dropped. The only words that went are the band's name-and-dates
block, replaced by the caption, and the header's tribute line, which the caption now carries.

---

## 7. Left alone, deliberately

- `about.html` keeps the cream palette and its exact content; the brief said only the front page's
  design changes.
- The `dashboard.html` link points at the page `build_dashboard.py` writes; that script was not
  touched.
- `site/` stays gitignored build output. Nothing under `site/` is committed.
- The database, the schema files and `PROGRESS.md` were not touched. `PROGRESS.md` says the purple
  study "is to become the main page" with "work not yet delivered"; that line is now out of date and
  is the author's or the secretary's to change, not mine.

---

## 8. Unproven

- **The page has not been read by a person at 375 px.** It was measured (no horizontal scroll, tables
  scrolling inside their own boxes) and screenshotted, not read.
- **The naira sign is not Inter.** Neither face has U+20A6, so `₦` is drawn by the system font in
  every price. That is what the study did too, and the study's faces were carried over as they are;
  adding a face that has the sign was judged a scope increase, not a fix.
- **The characters outside the two subsets fall back to the system font.** The subsets were cut to the
  characters this page prints, which for a frozen vintage is the whole set of characters the page can
  show. If the vintage is ever replaced by one carrying a character outside the subset (an accented
  letter in a product name), that glyph falls back — visible, but in the wrong face.
- **axe was run on `index.html` only.** `about.html` was not re-scanned in this session; its
  stylesheet is unchanged apart from the name of the variable that holds it, and its palette pairs
  were measured and printed by this build.
- **Nothing is deployed.** The page is build output; whether it is published is the owner's step.
