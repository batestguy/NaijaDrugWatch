# T1120-b — the approved navigation, in the generators, rebuilt and proved

The owner's decision ("do the most fitting") is in: **variant A's mechanism ships, variant B is
dropped**, with the two changes the preview showed were needed — no second wordmark on the landing
page, and a shorter quick index on a phone. The change is in the two generators, the pages are
rebuilt from them, and every claim below is a number I measured.

---

## 1. What changed, and where

`git status --short` shows exactly two tracked files changed, and nothing committed:

```
 M scripts/build_dashboard.py
 M scripts/build_site.py
```

### `scripts/build_site.py` (+118 / −3)

| where | what |
|---|---|
| `CONTRAST_PAIRS`, line 486 | four new pairs: the navigation link, the current page's rule, the quick index label, the quick index gloss. They are measured on **every** build, not once. |
| `CSS_CREAM`, line 1244 | `:root{--sb-h:49px}` and the site bar's stylesheet, for the methods page. |
| `CSS_ORANGE`, line 1520 | the front page: the masthead links (`.mast-right`, `.mastnav`) and the quick index strip (`.quickidx`, `.qi-list`). |
| `Page.build`, line 2120 | `id="finding"` added to the existing findings block, so the quick index can point at the 154. No class, no copy, no figure touched. |
| `Page.build`, line 2160 | the three links inside the existing masthead row, to the left of the outlined map. No second wordmark. |
| `Page.build`, line 2174 | the quick index strip, immediately under the masthead. Its two figures are the same facts the page already prints — `reg['matched_flagged']` and `overview['latest_listings']` — so nothing is typed. |
| `about_page`, line 1759 | the site bar, and the `← Medicine prices and registration status in Nigeria` line removed. |

### `scripts/build_dashboard.py` (+58 / −2)

| where | what |
|---|---|
| `CONTRAST_PAIRS`, line 212 | two new pairs: a link on the bar, and the current page's rule on the bar. |
| `:root`, line 790 | `--sb-h:49px`. |
| `CSS`, line 953 | the site bar's stylesheet (`--nav-max:76rem`, `--nav-pad:var(--pad-x)` so the bar tracks the page's own column). |
| `CSS`, line 984 | the jump bar's sticky offset becomes `top:var(--sb-h)`, so the two sticky bars cannot overlap. |
| `CSS`, lines 989–990 | a section's scroll margin grows by the site bar's height, so a jumped-to heading still lands **below** the jump bar and not under it. |
| template, line 1795 | the site bar, and the one-line back link removed. |

### No JavaScript was added

The bar's height is a **written-down number** — 49px, and 76px at ≤560px where it stacks — and the
dashboard's jump bar reads it. The landing page and the methods page carry **no `<script>` tag at
all**; the dashboard still carries its own two and no more. Nothing is fetched: no new font, no
image, no stylesheet, no request.

### The built pages

| page | before | after |
|---|---|---|
| `site/index.html` | 80,456 bytes | **84,123 bytes** |
| `site/about.html` | 45,200 bytes | **47,698 bytes** |
| `site/dashboard.html` | 896,597 bytes | **899,381 bytes** |

`site/` is gitignored, so these do not appear in `git status`. The patch was applied by
`.agent/T1120-b-patch.py`, which replaces 11 anchors copied out of the generators themselves and
**stops if any anchor is not found exactly once**; all 11 applied and both generators compile.

---

## 2. Both build outputs, verbatim

### `scripts/build_site.py`

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
  contrast  about: step text on a solid navy step        15.37:1  (#FFFFFF on #161A64)
  contrast  about: step text on a solid red step          7.63:1  (#FFFFFF on #9F2519)
  contrast  about: step text on a solid gold step         7.84:1  (#1a1612 on #D7A320)
  contrast  about: step text on a pale navy step         13.83:1  (#1a1612 on #E3E1E3)
  contrast  about: secondary text on a pale navy step     7.55:1  (#4a423d on #E3E1E3)
  contrast  about: a tool name on a pale navy step       11.82:1  (#161A64 on #E3E1E3)
  contrast  about: step text on a pale red step          14.26:1  (#1a1612 on #F1E2DB)
  contrast  about: secondary text on a pale red step      7.78:1  (#4a423d on #F1E2DB)
  contrast  about: a tool name on a pale red step         6.05:1  (#9F2519 on #F1E2DB)
  contrast  about: step text on a pale gold step         15.01:1  (#1a1612 on #F4EAD0)
  contrast  about: secondary text on a pale gold step     8.20:1  (#4a423d on #F4EAD0)
  contrast  about: a tool name on a pale gold step        5.44:1  (#7A5800 on #F4EAD0)
  contrast  front: body text on the page                 17.62:1  (#1C1108 on #FFF8F2)
  contrast  front: secondary text on the page             6.78:1  (#6B5343 on #FFF8F2)
  contrast  front: secondary text on a panel              6.33:1  (#6B5343 on #FDEFE4)
  contrast  front: body text on a panel                  16.45:1  (#1C1108 on #FDEFE4)
  contrast  front: headings and links on the page         5.64:1  (#B23C00 on #FFF8F2)
  contrast  front: headings and links on a panel          5.27:1  (#B23C00 on #FDEFE4)
  contrast  front: headings and links on a tint           5.39:1  (#B23C00 on #FEF2E8)
  contrast  front: a photograph caption                   6.78:1  (#6B5343 on #FFF8F2)
  contrast  front: a photograph caption on a tint         6.48:1  (#6B5343 on #FEF2E8)
  contrast  front: 'not active' on the page              11.98:1  (#4A2C1A on #FFF8F2)
  contrast  front: 'not active' on a panel               11.19:1  (#4A2C1A on #FDEFE4)
  contrast  front: 'active' on the page                   7.62:1  (#1c5c2e on #FFF8F2)
  contrast  front: 'not read' on the page                 6.78:1  (#6B5343 on #FFF8F2)
  contrast  front: band body text on the deep band        5.91:1  (#F6D9C0 on #8F3300)
  contrast  front: band heading on the deep band          7.95:1  (#FFFFFF on #8F3300)
  contrast  front: band tag on the deep band              6.93:1  (#FBEDE2 on #8F3300)
  contrast  front: button text on its warm plate          5.13:1  (#8F3300 on #F7C6A3)
  contrast  front: the button's plate, hovered            6.11:1  (#8F3300 on #FBDCC4)
  contrast  front: white on orange                        5.93:1  (#FFFFFF on #B23C00)
  contrast  front: step figure one on the page           14.61:1  (#161A64 on #FFF8F2)
  contrast  front: step figure two on the page            7.25:1  (#9F2519 on #FFF8F2)
  contrast  front: step figure three on the page          6.19:1  (#7A5800 on #FFF8F2)
  contrast  front: a navigation link on the page         17.62:1  (#1C1108 on #FFF8F2)
  contrast  front: the current page's rule on the page    7.25:1  (#9F2519 on #FFF8F2)
  contrast  front: a quick index label on the page       17.62:1  (#1C1108 on #FFF8F2)
  contrast  front: a quick index gloss on the page        6.78:1  (#6B5343 on #FFF8F2)
  decoration the REGISTER watermark on the page            1.40:1  (#B23C00 at 22% over #FFF8F2 paints as #EECFBD) - hidden from assistive technology, read by nobody
  decoration the tool-name strips on the methods page      1.24:1  (#5f2a54 at 12% over #faf7f1 paints as #E7DEDE) - hidden from assistive technology, read by nobody
  decoration the 2px rule around a pale navy step         11.82:1  (#161A64 at 100% over #E3E1E3 paints as #161A64) - a border, not text: it clears the 3:1 floor for a boundary
  decoration the 2px rule around a pale red step           6.05:1  (#9F2519 at 100% over #F1E2DB paints as #9F2519) - a border, not text: it clears the 3:1 floor for a boundary
  decoration the 2px rule around a pale gold step          5.44:1  (#7A5800 at 100% over #F4EAD0 paints as #7A5800) - a border, not text: it clears the 3:1 floor for a boundary
  decoration the edge of a gold step, against the page     6.09:1  (#7A5800 at 100% over #faf7f1 paints as #7A5800) - the same gold at text strength: this is the edge a reader sees
  decoration the raw gold fill, against the page           2.15:1  (#D7A320 at 100% over #faf7f1 paints as #D7A320) - the fill itself, not the edge: the rule above is what bounds it
  image     dora-portrait.jpg     51,941 bytes
  image     drugs-nigeria.jpg    177,783 bytes
  image     dashboard-demo.gif   313,169 bytes
wrote site/index.html (84,123 bytes, 44 comparison rows, 217 single-shop rows)
wrote site/data.json (131,976 bytes)
3,787 numbers checked, 0 unexplained
```

**The site's own audit is unchanged: `3,787 numbers checked, 0 unexplained`** — the same number the
project has recorded since the freeze. Nothing was loosened.

### `scripts/build_dashboard.py`

The transcript is 460 lines, most of it the per-medicine list the picker renders. The contrast block
and the last lines, verbatim:

```
  contrast  page: body text on the page                        16.82:1  (#1a1612 on #faf7f1)
  contrast  page: secondary text on the page                    9.19:1  (#4a423d on #faf7f1)
  contrast  page: links on the page                            10.09:1  (#5f2a54 on #faf7f1)
  contrast  page: a figure's number on the page                14.38:1  (#161A64 on #faf7f1)
  contrast  page: body text on a panel                         15.15:1  (#1a1612 on #f1ebdf)
  contrast  page: secondary text on a panel                     8.27:1  (#4a423d on #f1ebdf)
  contrast  page: links on a panel                              9.09:1  (#5f2a54 on #f1ebdf)
  contrast  page: the focus ring on the page                   16.82:1  (#1a1612 on #faf7f1)
  contrast  table: header text on the header                    8.27:1  (#4a423d on #f1ebdf)
  contrast  table: body text on a plain row                    16.82:1  (#1a1612 on #faf7f1)
  contrast  table: body text on a tinted row                   17.71:1  (#1a1612 on #fffdf9)
  contrast  table: a link on a tinted row                      10.62:1  (#5f2a54 on #fffdf9)
  contrast  table: a digit on a plain row                      16.82:1  (#1a1612 on #faf7f1)
  contrast  tag: active, on its own tint                       11.82:1  (#161A64 on #E3E1E3)
  contrast  tag: inactive, on its own tint                      5.14:1  (#7A5800 on #EBE4D4)
  contrast  tag: expired, on its own tint                       6.05:1  (#9F2519 on #F1E2DB)
  contrast  tag: never read, on the panel                      15.15:1  (#1a1612 on #f1ebdf)
  contrast  tag: in stock, on the panel                        15.15:1  (#1a1612 on #f1ebdf)
  contrast  tag: out of stock, on its own tint                  6.05:1  (#9F2519 on #F1E2DB)
  contrast  tag: no stock stated, on the panel                 15.15:1  (#1a1612 on #f1ebdf)
  contrast  chart: a label on the chart ground                 15.15:1  (#1a1612 on #f1ebdf)
  contrast  chart: a secondary label on the chart ground        8.27:1  (#4a423d on #f1ebdf)
  contrast  chart: the authored bar, on the chart ground       12.95:1  (#161A64 on #f1ebdf)
  contrast  chart: the inactive fill, on the chart ground       5.49:1  (#7A5800 on #f1ebdf)
  contrast  chart: the expired fill, on the chart ground        6.43:1  (#9F2519 on #f1ebdf)
  contrast  picker: the highlighted match, on its tint         13.83:1  (#1a1612 on #E3E1E3)
  contrast  band: white on the navy band                       15.37:1  (#FFFFFF on #161A64)
  contrast  band: white on the red band                         7.63:1  (#FFFFFF on #9F2519)
  contrast  band: ink on the gold band                          7.84:1  (#1a1612 on #D7A320)
  contrast  band: ink on a paper band                          16.82:1  (#1a1612 on #faf7f1)
  contrast  jump: an item at rest, on the bar                  16.82:1  (#1a1612 on #faf7f1)
  contrast  jump: the active item, navy on the bar             14.38:1  (#161A64 on #faf7f1)
  contrast  jump: the active item, red on the bar               7.13:1  (#9F2519 on #faf7f1)
  contrast  jump: the active item, gold on the bar              6.09:1  (#7A5800 on #faf7f1)
  contrast  row: text on the row under the pointer             15.56:1  (#1a1612 on #F1EEEB)
  contrast  chip: the chip's text on its tint                  13.83:1  (#1a1612 on #E3E1E3)
  contrast  chip: the clear-all label on the panel             15.15:1  (#1a1612 on #f1ebdf)
  contrast  nav: a link on the bar                             16.82:1  (#1a1612 on #faf7f1)
  contrast  nav: the current page's rule on the bar             7.13:1  (#9F2519 on #faf7f1)
  not text  the tinted row against the page                     1.05:1  (#fffdf9 on #faf7f1) - a tint, not a boundary
  not text  the table's hairline against the page               1.45:1  (#d7cfbe on #faf7f1) - a hairline, not a boundary
  not text  a pale tag border against its tint                 11.82:1  (#161A64 on #E3E1E3) - a boundary, floor 3.0:1
  not text  a measure's empty track on the chart ground         4.34:1  (#746C66 on #f1ebdf) - a boundary, floor 3.0:1
  not text  a price bar's fill against its own track           15.15:1  (#1a1612 on #f1ebdf) - a boundary, floor 3.0:1
  not text  a paper band's navy top rule                       14.38:1  (#161A64 on #faf7f1) - a boundary, floor 3.0:1
  not text  a paper band's red top rule                         7.13:1  (#9F2519 on #faf7f1) - a boundary, floor 3.0:1
...
worst text pair: tag: inactive, on its own tint at 5.14:1
wrote site\dashboard.html (899,381 bytes, 2,800 rows, 0.86 MB)
3,838 rows and figures checked, 0 unexplained
```

**The dashboard's count moved from the 3,837 recorded on 19 November to 3,838.** The count is a sum
of everything checked and it includes `len(CONTRAST_PAIRS)`, so the two pairs this build adds are
two of the movement; the rest is the difference between today's script and the 19 November one. I
did not re-run the 19 November script to split that out, and I did not need to: **no guard failed,
and the check got stricter, not looser** — two more colour pairs are now measured on every build.

Full transcripts: `.agent/T1120-b-build1-site.txt`, `.agent/T1120-b-build1-dashboard.txt`,
`.agent/T1120-b-build2-site.txt`, `.agent/T1120-b-build2-dashboard.txt`,
`.agent/T1120-b-build3-site.txt`.

---

## 3. The two `about.html` hashes

```
build 1   73098AD35FBB3A75E6D0A9E2F8110405F882A5DF7F5581A5EBBAB1CCA9CDC8D7
build 2   73098AD35FBB3A75E6D0A9E2F8110405F882A5DF7F5581A5EBBAB1CCA9CDC8D7
```

**Identical.** The methods page is still byte-for-byte reproducible after the change: the bar changes
it once, deliberately, and the second rebuild reproduces it exactly.

`site/index.html` was also identical on both builds (`CBAE81F04DD2316EF98A8E783955C56C0D2E8C47B7E085BB1A9EAC29FD90CEE1`),
then changed once more when I fixed the defect in section 5.

`site/dashboard.html` is **not** identical between builds, and was never meant to be: the page prints
its own build time ("Built 2026-11-20 07:04 UTC"). That is the only reason.

---

## 4. The measurements

Measured in a browser against `http://localhost:8080/`, at 1440 and 390 (and 375 for the checks
that matter). Every page was loaded with a cache-busting query string, because the first measurement
of this ticket came back showing a **stale cached copy** of the landing page — the server returns
the new file (`Invoke-WebRequest` shows `quickidx: True`, 84,125 bytes), but the browser had the old
one. Everything below is from the cache-busted load.

### Layout and overflow

| page | width | `scrollWidth` / `clientWidth` | masthead | quick index | site bar | heading "What a medicine costs." |
|---|---|---|---|---|---|---|
| landing | 1440 | **1440 / 1440** | 102px | **46px, one row** | none (the links are in the masthead) | top at **192px** |
| landing | 390 | **390 / 390** | 184px | **46px, one row, scrolls inside itself** | none | top at **264px** |
| dashboard | 1440 | **1440 / 1440** | — | — | **49px, sticky** | — |
| dashboard | 390 | **390 / 390** | — | — | **76px, sticky** | — |
| methods | 1440 | **1440 / 1440** | — | — | **49px, sticky** | — |

**No sideways scroll on any page at any width measured.**

- The quick index on the landing page at 1440: four items, all on **one row** (their tops are all
  152px), strip 46px tall, and the row does **not** scroll (1192px of content in 1192px).
- At 390 it is **one row of four labels with no glosses**, 46px tall, each item 44px, and it
  **scrolls inside itself**: 503px of content in 358px of room. The glosses are `display:none` at
  that width, as the brief asked.
- The masthead's three links are `display:none` at ≤560px, because the quick index below the
  masthead carries the same three destinations plus "Get the data"; **no destination is lost**.

### The dashboard's two sticky bars

After a 900px scroll:

| width | site bar | jump bar | gap |
|---|---|---|---|
| 1440 | top **0**, height 49 | top **49**, bottom 97 | none — they touch, they do not overlap |
| 390 | top **0**, height 76 | top **76**, bottom 124 | none |

The jump bar **still scrolls inside itself** on a phone: 803px of content in a 371px box at 390px
(1192 = 1192 at 1440, so it does not scroll on a desktop). Its own scroll margin grew by the site
bar's height, so a jumped-to heading lands below it.

### Contrast, measured in the browser on the rendered elements

| what | where | ratio | floor |
|---|---|---|---|
| a navigation link | landing | **17.62:1** | 4.5 |
| the current page's rule | landing | **7.25:1** | 3 (it is a rule) |
| a quick index label | landing | **17.62:1** | 4.5 |
| a quick index gloss | landing | **6.78:1** | 4.5 |
| a link on the bar | dashboard, methods | **16.82:1** | 4.5 |
| the current page's rule on the bar | dashboard, methods | **7.13:1** | 3 (it is a rule) |

The same six pairs are now in the two build-time contrast audits (§2), so they are measured on every
build rather than once.

### The 154 is still the loudest thing

| page | the 154 | the largest thing the navigation adds |
|---|---|---|
| landing at 1440 | **56px** | the quick index label, 11px |
| landing at 390 | **40px** | the quick index label, 11px |

The 154's own contrast is unchanged at **5.64:1**.

### Touch targets and keyboard

Every navigation link is **44px** tall at 1440 and at 390. Every quick index item is **44px**. The
site bar's wordmark link is a 31px row on a phone, but it is a home link that also carries the
name; the three page links are all 44px.

Tab order on the landing page, measured by pressing Tab and reading `document.activeElement`:

```
tab 1  the skip link
tab 2  The finding
tab 3  Every price
tab 4  How this was made
tab 5  the quick index: The finding
tab 6  the quick index: Every price
```

The current page carries `aria-current="page"` on every page. The focus ring is 3px with a 2px
offset, in the page's own focus colour (orange on the landing page, plum on the other two).

**The console is clean: 0 errors, 0 warnings** on all three pages.

---

## 5. A defect I introduced and fixed

The first build of the quick index put it on **two rows at 1440**, and the item widths were about
50px wider than the preview's. The cause was mine: I wrote the separator as a CSS escape,
`content:"\00a0\2014\00a0"`, and the generator's stylesheet is an ordinary Python string, so
**Python ate the escapes** — `\00a0` became a NUL character and `\2014` became a control character.
The browser then rendered them as replacement characters, and the separator became visible junk
between the label and the gloss.

Fixed by writing the escapes as `\u00a0\u2014\u00a0`, which Python converts to the real characters
(non-breaking space, em dash, non-breaking space) before the CSS ever reaches the page. The strip is
now **one row at 1440** and the separator reads " — ".

The lesson is the project's own: a number read from source is not a measurement. The first browser
pass is what caught it.

---

## 6. What a reviewer should check hardest

1. **`--sb-h` is a written-down number, not a measured one.** The bar is 49px and the jump bar
   trusts it. If the bar's real height ever differs from 49px at some width — between 561px and
   about 900px the bar is one row and the links are closest to crowding — the jump bar would sit at
   the wrong height. I measured 1440, 390 and 375; I did not sweep every width between.
2. **The phone quick index is cut off mid-label.** At 390px the fourth item shows only its first
   letter, which is the standard "there is more" signal, but it is a weak one on its own. The
   scrollbar is hidden so that the row stays exactly 44px; the dashboard's own jump bar keeps a
   thin scrollbar instead. Somebody with a phone should say whether the cut reads as "scroll me" or
   as "broken".
3. **The jump bar's scroll margin.** I grew it by the site bar's height so that a jumped-to heading
   lands below the jump bar rather than under it. I verified the numbers (the bar at 0–49, the jump
   bar at 49–97) but I did not click a jump and measure where the heading landed.
4. **"Get the data" points at `#get-the-data`**, which exists only when the published-vintage record
   is present. The record is committed, so the link resolves today; if the record were ever
   removed, the build would render the block empty and that one link would point at nothing.
5. **The 154 is now printed twice on the landing page** — once as the finding, once in the quick
   index's gloss ("the 154 on this page"). Both come from the same fact (`registration.matched_flagged`),
   so they cannot disagree, but the page does say the number twice, which the project has avoided
   elsewhere on purpose.

---

## 7. Unproven

- **axe was not run** on the three rebuilt pages (it is not installed here, and the project's own
  record says the same about the shipped pages). Structure, contrast, overflow and keyboard were
  checked by hand and by script instead.
- **No screen reader** was used. The `aria-current="page"`, the two nav landmarks ("Site" and
  "Quick index") and the skip link are there; nobody has heard them read aloud.
- **No human has seen the result.** The screenshots in `.agent/T1120-b-shots/` (landing page at 1440
  and 390, dashboard at 1440 and 390, methods page at 1440) are what I looked at.
- **Nothing is committed and nothing is pushed.** The two generator files are modified in the working
  tree; the built pages are gitignored.
