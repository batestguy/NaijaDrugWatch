# T1120-a — a way from any page to any page, and a quick index by the mast

**Preview only. Nothing that ships was touched.** No commit, no push, no edit to a tracked file.
Six preview pages live in `site/preview-nav/`, generated from the three built pages by
`site/preview-nav/build_preview.py`. The three sources are byte-for-byte as they were
(`site/index.html` 80,456 bytes, `site/dashboard.html` 896,597, `site/about.html` 45,200; last
written 19 November, before this session), and `git status --short` shows nothing but three
pre-existing untracked PNGs in `.agent/` that belong to another session.

Rebuild the preview with the pinned interpreter:

```
.venv\Scripts\python.exe -X utf8 site\preview-nav\build_preview.py
```

It prints the six page sizes and then the contrast audit, so no colour pair is ever read from the
stylesheet and assumed.

---

## 1. What I built

### Two variants of the same three destinations

Both variants are the same idea with a different mechanism, and both carry the owner's quick index.

**Variant A — a slim site bar.** One hairline bar: the wordmark on the left, three page links on the
right. The current page is marked two ways — a 3px deep-red rule under the label, and
`aria-current="page"` — so the mark does not depend on colour alone. It replaces the
`← Medicine prices and registration status in Nigeria` line on the dashboard and the methods page.
Static on the landing page (the hero is the first thing you should see), sticky on the two inner
pages.

**Variant B — one button that opens the pages.** A single `PAGES` button at the top right opening a
flat card: the three pages, each with a one-line description. Escape closes it, a click outside
closes it, and focus goes back to the button. The card is a 1px near-black rectangle on the page's
own panel tint — no radius, no shadow, no icon, no gradient.

**The three destinations, named identically in both variants:**

| label | goes to | in the card |
|---|---|---|
| **The finding** | the landing page | What a medicine costs, and whether its licence is active |
| **Every price** | the dashboard | Every price we could read, explorable |
| **How this was made** | the methods page | The method, the decisions and the limits |

**On the name.** The methods page is still titled "How this was built" on the page itself; the nav
and the index call it **"How this was made"**. That is the whole of the change — one word, `built`
becomes `made` — and it is now the same word in the bar, in the card and in the quick index, so a
reader never has to learn two names for one page.

### The quick index (landing page only)

Immediately under the masthead, one row, hairline above and below, four items:

> **THE FINDING** — the 154 on this page │ **EVERY PRICE** — 2,800 prices, explorable │
> **GET THE DATA** — the frozen vintage │ **HOW THIS WAS MADE** — the method and the limits

- "The finding" → `#finding`
- "Every price" → the dashboard
- "Get the data" → `#get-the-data`, the section already on the page
- "How this was made" → the methods page

Measured: at 1440 all four items sit on **one row** (all at y=152, the strip is 46px tall). At 375
and 390 it becomes a **2 × 2 grid** (163px tall) with hairline column and row rules, because four
items with a gloss each cannot hold a line at 375.

**One preview-only edit to the landing page:** `id="finding"` added to the existing `.finding` div,
so "The finding" can point at the 154. No copy, no figure, no class and no styling was changed.
"Get the data" already had the anchor it needed.

### The screenshots

`site/preview-nav/shots/` — ten, all taken from `http://localhost:8080/preview-nav/`:

| file | what it shows |
|---|---|
| `a-index-1440.png` | landing page, variant A, 1440 |
| `a-index-390.png` | landing page, variant A, 390 |
| `b-index-1440.png` | landing page, variant B, 1440 |
| `b-index-390.png` | landing page, variant B, 390 |
| `b-index-1440-panel.png` | variant B, the card open, 1440 |
| `b-index-390-panel.png` | variant B, the card open, 390 |
| `a-dashboard-1440.png` | dashboard, variant A, 1440 |
| `a-dashboard-390.png` | dashboard, variant A, 390 |
| `a-about-1440.png` | methods page, variant A, 1440 |
| `b-about-1440.png` | methods page, variant B, 1440 |

---

## 2. Contrast, measured

Two passes. First a 26-pair audit computed from the hex values (printed by every build), then the
same pairs **re-measured in the browser from `getComputedStyle` on the rendered elements**, which is
the number that counts. On the landing page the two agree exactly (16.45, 6.33, 6.77), so the
dashboard and methods pairs, computed by the same formula, are the same kind of number.

**Measured in the browser, on the rendered page:**

| what | foreground | background | ratio | needed |
|---|---|---|---|---|
| site bar link text (landing) | `rgb(28,17,8)` | `rgb(255,248,242)` | **17.62:1** | 4.5 |
| site bar link text (dashboard, methods) | `rgb(26,22,18)` | `rgb(250,247,241)` | **16.82:1** | 4.5 |
| wordmark (both grounds) | ink | cream | **17.62 / 16.82:1** | 4.5 |
| current-page rule (landing) | `rgb(159,37,25)` | `rgb(255,248,242)` | **7.25:1** | 3 (non-text) |
| current-page rule (dashboard, methods) | `rgb(159,37,25)` | `rgb(250,247,241)` | **7.13:1** | 3 (non-text) |
| quick index label | ink | cream | **17.62:1** | 4.5 |
| quick index gloss | `rgb(107,83,67)` | `rgb(255,248,242)` | **6.78:1** | 4.5 |
| card title (landing) | ink | `rgb(253,239,228)` | **16.45:1** | 4.5 |
| card current title | `rgb(159,37,25)` | `rgb(253,239,228)` | **6.77:1** | 4.5 |
| card description | `rgb(107,83,67)` | `rgb(253,239,228)` | **6.33:1** | 4.5 |
| button label | ink | cream | **17.62 / 16.82:1** | 4.5 |
| button border | near-black | cream | **17.62 / 16.82:1** | 3 (non-text) |
| card border | near-black | cream | **17.62 / 16.82:1** | 3 (non-text) |
| the 154 (unchanged page figure) | `rgb(178,60,0)` | `rgb(255,248,242)` | **5.64:1** | 4.5 |

**From the build-time audit** (26 pairs, **0 failures**, worst text pair **6.33:1**, worst pair of
any kind **5.64:1** — the focus ring on the landing page): the same table for the dashboard and
methods pages reads card title 15.15:1, card description 8.27:1, card current title 6.43:1, focus
ring `rgb(95,42,84)` on cream 10.09:1, and the landing page's focus ring `rgb(178,60,0)` on cream
5.64:1.

The two decorative hairlines (the bar's own rule and the quick index's column rules) measure 1.45:1
and 1.34:1. They carry no meaning — the current page is marked by the red rule, which is 7:1 — so
they are recorded as decoration and are not counted as failures.

**Nothing new was introduced:** the deep red `#9F2519` is already a house colour on all three pages
(`--dress-red` on the landing page, `--red` on the other two), the cream ground, the near-black ink
and the hairline rules are each page's own variables, and the wordmark uses the display family the
page's own headings use, with the same fallback. No new typeface, no new accent, no icon, no
gradient, no rounded card, no shadow.

---

## 3. Layout, overflow and keyboard, measured

**No sideways scroll.** `scrollWidth == clientWidth` on all six pages at **375** (375 = 375), **390**
(390 = 390) and **1440** (1440 = 1440).

**The 154 is still the loudest thing.** At 1440 the `154` is 56px and the largest thing I added is
the quick index label at **11px**; at 375 the `154` is **40px** against a quick index label of 11px.
Nothing new competes with it.

**Touch targets.** Every bar link is **44px** tall at 1440, 390 and 375. The `PAGES` button is
**44px** tall. The quick index items are **44px** at 1440 and **66–90px** at 375 and 390. The three
card links are **64–82px**.

**Keyboard, measured by pressing Tab and reading `document.activeElement`:**

| key | focus lands on |
|---|---|
| Tab 1 | the skip link (`#main`) — still first |
| Tab 2 | the wordmark (home) |
| Tab 3 | the `PAGES` button |
| Tab 4 | the quick index, "The finding" |
| Tab 5 | the quick index, "Every price" |

- **Escape** with the card open: the card closes, `aria-expanded` returns to `false`, and focus is
  back on the `PAGES` button — measured.
- **A click outside** the card closes it — measured.
- **No focus trap**: Tab moves on into the page content in both variants.
- The current page carries `aria-current="page"` in both variants (on the link in the bar, and on
  the item in the card).
- The focus ring is 3px with a 2px offset, in the page's own focus colour (orange on the landing
  page, plum on the other two, so it matches the ring the rest of that page already uses). It is
  5.64:1 and 10.09:1 against the ground.

**The dashboard's own sticky jump bar.** It was `top: 0`; it now sticks at **49px**, exactly the
height of the site bar above it — measured after scrolling 900px: the bar sits at `top 0`, 49px tall,
and the jump bar occupies 49–97px with no overlap. At 375 the bar is 76px tall and the jump bar
sticks at 76px. The jump bar was **not moved, restyled or broken**: it still scrolls inside itself
(its list measures 803px of content in a 356px box at 375px) and it is still its own nav.

**The console is clean:** 0 errors, 0 warnings on the pages measured.

**The card fits.** At 1440 it is 300 × 219px, bottom at 273 in a 900px window. At 375 it is 330px
wide, inside the viewport (left 29, right 359), bottom at 300 in an 812px window — **26% of the
screen**, never taller than the viewport.

---

## 4. Which one I would ship, and why

**Variant A, the slim site bar.**

1. **Three pages do not need a menu.** With three destinations, a visible row of labels is honest:
   nothing is hidden, so a reader never has to wonder whether a control is a menu. Variant B spends
   a disclosure step — click, then tab into the card — to reach two of the three pages.
2. **Where you are, without a click.** The red rule and the bold weight under the current label are
   visible at rest. Variant B's equivalent lives inside a card that is closed until you open it.
3. **The landing page would contradict itself.** The owner asked for both a quick index *and* a nav.
   On the landing page the quick index already sits open under the masthead with those three
   destinations written out. Putting a button above it to reveal what is already open two
   centimetres below is the weaker arrangement.
4. **Less machinery that can break.** Variant B needs four behaviours to keep working — the toggle,
   `aria-expanded`, outside-click and focus-return. Variant A needs one `aria-current` and a CSS
   rule. For a three-page site, that is a poor trade.

**Where B is better, and it is not nothing:** the bar costs the hero less, and on the landing page
it could be a single row instead of two. As built, B's phone bar is **76px** tall, the same as A's,
because my narrow-screen rule stacks the bar for both variants; scoping that stacking to variant A
alone would bring B's phone bar to **49px**. I did not make that change — it would have cost calls
past the cap, and A is the one I would ship. If the owner prefers B, that change is the first thing
to make.

---

## 5. Deviations from the brief, each with a reason

1. **The brief's palette is the cream-and-red one; the live landing page is orange.** The brief
   names cream ground, deep red `#9F2519`, navy, gold and near-black. The landing page's own accent
   was moved to orange `#B23C00` on 18 November, and the other two pages' accent is plum `#5f2a54`.
   I used the brief's shared house constants — the deep red for the current-page rule and the mark,
   which exists on all three pages — and each page's own background, ink and muted colours for the
   text, so the bar sits flush with its page with no seam. The focus ring uses each page's own
   accent so it matches the ring the rest of that page already draws. No new colour was invented
   either way.
2. **The wordmark in the bar is small, letterspaced and near-black, not the page's big coloured
   wordmark.** The landing page already carries a 26px orange wordmark in its masthead, about 90px
   below the bar. A second coloured wordmark directly above it would fight it.
3. **The dashboard's jump bar's sticky offset changed** from `top: 0` to `top: var(--sb-h)`. It had
   to, or the two sticky bars would overlap. Nothing else about it changed.
4. **The quick index's fourth gloss was shortened** from "the method, the decisions, the limits" to
   "the method and the limits", and its horizontal padding from 16px to 14px, so that the four
   items hold **one row** at 1440 instead of wrapping the fourth onto a second line.

---

## 6. The thing I am least sure of

**The wordmark repeated twice on the landing page.** The bar carries a small letterspaced
`NAIJADRUGWATCH` and the masthead carries the page's own 26px orange one, roughly 90 pixels apart.
I judged that a quiet utility bar above a mast reads as one site, and I judged that the small mark
being near-black rather than orange stops the two from arguing. But I have not seen it on the
owner's screen, and a reader may well read the repetition as an accident rather than as a pattern.

The related risk: the deep red `#9F2519` that the brief asked for sits on a page whose accent is
now orange. Red is already on that page (it is the colour of the "559 matched to a medicine" figure
in the receipt), so it is not a stranger — but the red rule under "The finding" is the only red
thing on the first screen, and whether that reads as a deliberate mark or as a stray accent is a
judgement no measurement can make.

**Unproven, and I could not measure it:** axe was not run on these pages (it is not installed here,
and the project's own record says the same about the shipped pages); I checked structure, contrast,
overflow and keyboard by hand and by script instead. No screen reader was used. The preview uses two
small inline scripts — one to measure the bar's height so the jump bar can sit under it, one for the
card — which in the real change would live inside the two generators. The six preview pages are
generated copies: the real change has not been made anywhere.
