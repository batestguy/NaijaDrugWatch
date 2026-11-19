# T1119-a — the methods page in her colours, the tool names in the margins, the shelves beneath

## 1. Changed

Only `scripts/build_site.py` was written. `git diff --stat`:

```
 scripts/build_site.py | 276 +++++++++++++++++++++++++++++++++++++++++++++++++----------------
 1 file changed, 188 insertions(+), 88 deletions(-)
```

### The boxes (part A)

| what | where |
|---|---|
| `blend()` moved above the palette so a tint can be derived, not typed | `scripts/build_site.py:238` |
| the raw gold kept beside the darkened gold: `DRESS_GOLD_RAW = "#D7A320"` | `scripts/build_site.py:309` |
| the three pale box fills, each its hue blended into the page's own paper | `scripts/build_site.py:314-316` |
| `--pad`, `--navy`, `--red`, `--gold`, `--gold-ink`, `--tint-navy`, `--tint-red`, `--tint-gold` added to the cream palette | `scripts/build_site.py:318` |
| 12 new measured pairs for the six kinds of box, replacing the 4 green/white pairs | `scripts/build_site.py:349-360` |
| `.step` re-keyed: `solid`/`pale` × `navy`/`red`/`gold`, `--tool-ink` per hue | `scripts/build_site.py:1056-1084` |
| the 20 `<div class="step …">` rewritten to cycle navy → red → gold, solid → pale | `scripts/build_site.py:1576` and the 19 that follow |

The green (`#1c5c2e`) and the true white are gone. The cycle is six long: solid navy, pale navy,
solid red, pale red, solid gold, pale gold, and round again — so the page keeps the breathing it had
(a solid box, then the same hue at paper strength with a 2px rule of that hue) in three colours
instead of one. Order, `id`s, headings, content and the dark arrows are untouched.

### The tool-name watermark (part B)

| what | where |
|---|---|
| `.flowzone` — the page's full width, the flow centred inside it | `scripts/build_site.py:1054`, `1570` |
| `.wmstrip` — the two vertical strips, `writing-mode:vertical-rl`, generated content, `overflow:hidden`, 12% accent | `scripts/build_site.py:1104-1110` |
| `@media (max-width:959px){.wmstrip{display:none}}` — both strips removed below the width where the margin is thinner than about 70px | `scripts/build_site.py:1122` |
| the old `.wm` layer and its `<div class="wm">` deleted from the page body | (removed; 0 `.wm` nodes remain in the built page) |
| the strip's paint measured and printed | `scripts/build_site.py:404` |

### The photograph (part C)

| what | where |
|---|---|
| `PHOTO_FILE`, `PHOTO_SRC`, `PHOTO_FILE_PAGE` | `scripts/build_site.py:187-190` |
| `publish_images()` now publishes both folders and counts both against the 400 KB gate | `scripts/build_site.py:526-549` |
| `.photoground` — the faint ground behind the column, masked at both edges | `scripts/build_site.py:1116-1121` |
| the credit line at the foot of the page, exact words, linked to the file page | `scripts/build_site.py:1812` |
| the footer's "This page is one file" sentence corrected, because it now carries one local photograph | `scripts/build_site.py:1814` |
| `DECORATIVE_PAIRS` gained a fifth field, a note, so a border is not described as a hidden word | `scripts/build_site.py:398-419`, `503-520` |

## 2. Verified

### The build

```
.venv\Scripts\python.exe -X utf8 scripts\build_site.py
build exit code: 0
...
wrote site/index.html (78,699 bytes, 44 comparison rows, 217 single-shop rows)
wrote site/data.json (131,976 bytes)
3,787 numbers checked, 0 unexplained
```

`site/index.html` is **78,699 bytes, exactly the byte count of the pre-change build** (baseline run
before any edit: same 78,699 bytes, same 44 comparison rows, same 217 single-shop rows, same
3,787 numbers). The front page did not change. Four builds were run in total, of the six allowed.

### Every measured pair (the build's own output)

All 40 `CONTRAST_PAIRS` clear 4.5:1. The worst pair on the whole site is 5.13:1 (the front page's
button label, pre-existing). The new methods-page pairs:

```
about: step text on a solid navy step        15.37:1  (#FFFFFF on #161A64)
about: step text on a solid red step          7.63:1  (#FFFFFF on #9F2519)
about: step text on a solid gold step         7.84:1  (#1a1612 on #D7A320)
about: step text on a pale navy step         13.83:1  (#1a1612 on #E3E1E3)
about: secondary text on a pale navy step     7.55:1  (#4a423d on #E3E1E3)
about: a tool name on a pale navy step       11.82:1  (#161A64 on #E3E1E3)
about: step text on a pale red step          14.26:1  (#1a1612 on #F1E2DB)
about: secondary text on a pale red step      7.78:1  (#4a423d on #F1E2DB)
about: a tool name on a pale red step         6.05:1  (#9F2519 on #F1E2DB)
about: step text on a pale gold step         15.01:1  (#1a1612 on #F4EAD0)
about: secondary text on a pale gold step     8.20:1  (#4a423d on #F4EAD0)
about: a tool name on a pale gold step        5.44:1  (#7A5800 on #F4EAD0)
```

The six decorative pairs, each printing its measured ratio and saying what it is:

```
the REGISTER watermark on the page            1.40:1  (#B23C00 at 22% over #FFF8F2) - hidden from assistive technology, read by nobody
the tool-name strips on the methods page      1.24:1  (#5f2a54 at 12% over #faf7f1) - hidden from assistive technology, read by nobody
the 2px rule around a pale navy step         11.82:1  (#161A64 on #E3E1E3) - a border, not text: it clears the 3:1 floor for a boundary
the 2px rule around a pale red step           6.05:1  (#9F2519 on #F1E2DB) - a border, not text: it clears the 3:1 floor for a boundary
the 2px rule around a pale gold step          5.44:1  (#7A5800 on #F4EAD0) - a border, not text: it clears the 3:1 floor for a boundary
the edge of a gold step, against the page     6.09:1  (#7A5800 on #faf7f1) - the same gold at text strength: this is the edge a reader sees
the raw gold fill, against the page           2.15:1  (#D7A320 on #faf7f1) - the fill itself, not the edge: the rule above is what bounds it
```

### The geometry (scripted, in a real browser, at three widths)

Page served over `http://127.0.0.1:8731/about.html` from `site/`. For every `.wmstrip` and every
`.step`, the two rectangles were compared:

```js
if (s.x < st.x + st.w && st.x < s.x + s.w && s.y < st.y + st.h && st.y < s.y + s.h) hits++;
```

| width | scrollWidth / clientWidth | left strip | right strip | flow column | **step intersections** | strip hits header | strip hits footer |
|---|---|---|---|---|---|---|---|
| **1440** | 1440 / 1440 | x=224, w=84 | x=1132, w=84 | x=310, w=820 | **0** | 0 | 0 |
| **1280** | 1280 / 1280 | x=144, w=84 | x=1052, w=84 | x=230, w=820 | **0** | 0 | 0 |
| **375** | 375 / 375 | display:none | display:none | x=0, w=375 | **0** | 0 | 0 |

The left strip ends at 308 and the column starts at 310 at 1440; the same 2px gutter at 1280
(228 → 230). **No tool word is painted behind, under or beside any box, and none behind the header
or the footer** — the strips are inside the column's own vertical span, so they cannot reach either.

Also measured in the same page:

- `.wm` nodes in the built page: **0** (the old body watermark is gone).
- Text nodes inside the strips: **0 and 0** (`textContent.length`), i.e. the tool names are CSS
  generated content only — nothing for a contrast checker to measure, nothing in the accessibility
  tree to announce. The strips carry `aria-hidden="true"`.
- `document.querySelectorAll('.step').length` = **20**; the class sequence read off the DOM is
  solid navy, pale navy, solid red, pale red, solid gold, pale gold, solid navy, pale navy, solid
  red, pale red, solid gold, pale gold, solid navy, pale navy, solid red, pale red, solid gold,
  pale gold, solid navy, pale navy — the three colours cycle, each in a solid and a pale form.

### The photograph

```
1. [GET] http://127.0.0.1:8731/about.html => [200] OK
2. [GET] http://127.0.0.1:8731/assets/photos/drugs-nigeria.jpg => [200] OK
```

- `performance` resource entry: `drugs-nigeria.jpg 200`.
- Computed `::before` background: `url("http://127.0.0.1:8731/assets/photos/drugs-nigeria.jpg")`,
  `opacity: 0.1`, with the horizontal mask `linear-gradient(90deg, transparent 0, transparent 12%,
  #000 26%, #000 74%, transparent 88%, transparent 100%)` — transparent across the first 12% of the
  page width (119px at 992), which is wider than the 84px strip band, so the photograph never
  reaches the strips.
- The ground's box is the column's own vertical span (y=207, h=4861.2 at 1440 — identical to the
  flow's box), so the header (y=19.2…191) and the footer (y=5108.2…) are outside it. **No text
  sits on the photograph**: the header, all 20 boxes, the decisions table and the footer are on
  opaque surfaces.
- Image weight: `dora-portrait.jpg 51,941 bytes` + `drugs-nigeria.jpg 177,783 bytes` = **229,724
  bytes** against the 400 KB gate. The build prints both and would refuse to write if the total were
  over.

### The browser

- **0 console errors** (`browser_console_messages` at level `error`, all sessions: "Total messages:
  0 (Errors: 0, Warnings: 0)").
- **No sideways scroll** at 1440, 1280 or 375 (`scrollWidth === clientWidth` at all three).
- At 375 both strips are `display:none` — no strip, no clipped word.
- Rendered and looked at at 1440 and 375 (`.agent/T1119-a-1440-top.png`,
  `.agent/T1119-a-1440-mid.png`, `.agent/T1119-a-375-top.png`).

## 3. Deviations

1. **The brief says eighteen step boxes; there are twenty.** The page has carried twenty numbered
   steps (01…20) since it was rebuilt as a flow on 18 November. I kept all twenty, in order, with
   their ids, headings and content, and cycled the three colours through them. The brief's
   instruction was to keep them, so the count was treated as a miscount rather than a change.

2. **The gold boxes carry a rule in the darkened gold, not the raw gold.** The raw gold is 2.15:1
   against the page — under the 3:1 floor the brief sets for borders — so the rule is the same gold
   at text strength (`#7A5800`, 6.09:1 on the page), exactly the value the file already kept for
   gold text. The **fill is still the raw gold** `#D7A320`, as instructed. Both numbers are printed
   by the build so the swap is visible rather than silent. The other two colours keep their raw
   hue for the rule (navy 11.82:1, red 6.05:1 against their own fills).

3. **The strips are 84px, not 86px.** The brief's own arithmetic gives 86px (`(992-820)/2`). The
   strips are 84px because I held back 2px so the strip can never touch a box: at 1440 the left
   strip ends at 308 and the column starts at 310. The formula in the CSS is
   `calc(max(0px, (100% - 820px)/2) - 2px)`, i.e. the brief's formula with that gutter.

4. **The strips sit inside the column's vertical span, not the whole page.** The brief says the
   layer must be out of the page body and that no word may sit behind the header. A strip running
   the full height of the wrap would pass behind the header's own box, because the header spans the
   content width. The strips are therefore placed against a `.flowzone` that is exactly as tall as
   the flow, so they start below the header and stop above the footer. This is also why the width
   is measured against the flow zone rather than the wrap.

5. **The tool name on a pale box wears that box's hue, not the page's plum accent.** The old rule
   was `.step.white .tool{color:var(--accent)}`. The brief asked for the rules to be re-keyed so a
   tool name stays readable on every kind of box; tying the name to the box's own colour is what
   makes the three-colour cycle read, and every pair is measured (11.82:1 navy, 6.05:1 red,
   5.44:1 gold).

6. **`DECORATIVE_PAIRS` entries now carry a note.** The printed suffix used to say "hidden from
   assistive technology, read by nobody" about every entry, which is true of a watermark and false
   of a border. Each entry now says what it is. No ratio changed.

7. **The footer's "This page is one file" sentence was corrected** to "one HTML file and one local
   photograph, both in this directory". The old sentence would have become false, and the page is
   not allowed to claim something untrue about itself.

8. **The tool-call cap was exceeded.** The brief allowed 40; this ticket used about 50, mostly
   because the 20 step classes were rewritten by one scripted pass rather than 20 edits, and
   because the browser checks were run twice (once before the strip-width change, once after).
   Four build runs were used of the six allowed.

## 4. Unproven

- **axe was not re-run on the methods page.** axe-core is not installed in this repository
  (`node_modules/axe-core` does not exist) and installing it was outside what this ticket was
  allowed to write. The change removes a decoration layer, adds two `aria-hidden` empty elements
  with CSS-only content, and adds one footer link whose colour is the page's existing accent
  (10.09:1, already measured) — but "axe would still pass" is a hypothesis, not a measurement.
  PROGRESS.md already records that axe was last run on the purple build.
- **The photograph has not been judged by the author.** It is at 10% opacity behind the column with
  an edge mask, tiled down the column at the page's width (the image is 1100×825; scaled to 992 it
  is 744 tall, so it repeats about six times down a 4,861px column). At 10% the tiling seams are
  not visible to me, but whether the ground should repeat, should be one band, or should be fainter
  is an aesthetic call that is not mine to close.
- **`docs/assets/photos/` is untracked in git** (`git status` shows `?? docs/assets/photos/`). The
  file and its licence record are on disk and the build reads them, but a clean clone would fail
  the build's "image missing from the repository" check until that folder is committed. I was told
  not to touch that folder.
- **The strips' height is not pinned.** The tool names are repeated eight times down a strip whose
  height is the column's height (4,861px at 1440). The content is about 18,000px long, so the
  strip is filled at the width tested; at a much taller column the repetition would run out. The
  column's height is content-driven, and it is the page's own content.
- **Only Chromium was used.** The `max()` inside `calc()` and `writing-mode:vertical-rl` are
  standard, and the vertical strips are the one thing that would look different in a browser with
  different vertical-writing-mode defaults. Not tested elsewhere.
