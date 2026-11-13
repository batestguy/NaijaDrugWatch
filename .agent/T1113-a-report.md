# T1113-a report - the page built as a tribute

**Written by the secretary on 2026-11-13.** The builder (`ses_e2d444ba0ffeFH2VgvK4YmVgcy`) wrote the
code and the images, then could not rebuild because the database was unreachable - the Proton VPN was
on again, and it did not run the control experiment that tells a tunnel apart from a dead database.
I ran the build and every check myself once the tunnel was off.

## Changed

| path | state |
|---|---|
| `docs/assets/dora/` | **new**: the portrait cropped three ways (masthead 480x600, band 640x305, footer mark 220x220), one memorial photograph (480x776), `CREDITS.md`, and `licences.json` holding the raw licence responses |
| `scripts/build_site.py` | tribute constants and a date guard; masthead, band, footer mark and credits; a second page, `about.html`; an image byte budget |
| `site/*` | build output, gitignored |

## Verified - by the secretary

**Build, first attempt, database reachable:**

```
contrast  band text on the band      14.65:1   (#f7f0e6 on #2a1a20)
contrast  gold text on the band       8.49:1
contrast  body text on the page      16.82:1
contrast  secondary text on a panel   8.27:1   <- the worst of the nine
contrast  a warning on its own panel  8.51:1
image     dora-portrait.jpg  51,941 bytes   dora-band.jpg  23,153
image     dora-mark.jpg       6,983 bytes   dora-monument.jpg 56,023
wrote site/index.html (106,094 bytes, 45 comparison rows, 217 single-shop rows)
wrote site/about.html (13,902 bytes)
3,539 numbers checked, 0 unexplained
EXIT=0
```

Total image weight **138,100 bytes**, against a 400 KB budget the build enforces.

**Contrast** is computed at build time for nine text surfaces and printed on every build; the worst is
8.27:1 where WCAG AA asks for 4.5:1.

**The date guard, fired by me** rather than taken on report: setting either date to `None` raises
`UnsetDate` with the message "the page will not print a date from memory". Both directions tested.

**What the pages say - every assertion checked in the emitted HTML:**

present: her birth date, her death date, her name, her honour, "Director-General", the National
Library credit, her own quoted words ("grazed my scalp"), the TIME attribution, her sister's name and
the year 1988, "Agulu", and the NLN and Princeton source URLs.

absent: `cheapest in lagos`, `national price index`, `counterfeit` (on both pages), `70%`, `under 20%`,
`official`.

**In a browser:**

| check | result |
|---|---|
| 375 px | `scrollWidth 375 = clientWidth 375` - no overflow; all three images loaded (natural widths 480, 640, 220) |
| 1280 px | no overflow |
| about.html | loads, 886 words, both photographs loaded |
| console | **0 errors, 0 warnings** |

**External references** are hyperlinks only, never asset loads: on the index, the three pharmacy sites,
the register, and the licence pages; on About, the three sources plus the licence pages. No font, no
script, no stylesheet, no image is fetched from anywhere.

**Alt text**: the portrait and the memorial are described (25 and 34 characters); the band and the
footer mark carry empty alt, because they are the same face repeated and a screen reader gains nothing
from hearing it three times.

## Deviations

- The rebuild was done by me, not the builder: it stopped at an unreachable database without running
  the control test that identifies a tunnel. The VPN was the cause.
- Only one of the three statue photographs is used (on About). Two were licence-checked and dropped for
  variety's sake, not for licensing reasons.
- The About page is written from `.agent/DORA-facts.md` as a factual chronicle with attributed
  quotations, not as an essay. A writer can raise it later; every sentence currently traces to a row
  in that file.

## Open risks - what a reviewer should check hardest

1. **Three crops of one photograph.** The masthead, the band and the footer are the same face. Whether
   that reads as a tribute or as repetition is a judgement no check can make. It needs eyes.
2. **The band sits between the price tables and the registration section.** If it pushes the licence
   findings below the fold on a phone, the tribute is crowding the point of the page.
3. **CC0 needs no attribution, and we give it anyway.** If the credit line is ever cut for space, the
   licence still permits it - but the National Library of Nigeria should stay named.
4. **The About page states her sister's death in TIME's words.** Correct as attribution, but a reader
   may still read it as her own account. The wording is on the page; check it reads as TIME's sentence.
5. **`about.html` is linked from the index**; confirm the link is reachable by keyboard and that the
   page is reachable from the footer as well as the masthead.

## Unproven

- **Whether the tribute reads well.** Verified in a browser, not with a person's eye.
- **No axe run** - contrast and structure are measured, nothing else about accessibility is.
- **The pages have not been seen by anyone but me**, and not at a width between 375 and 1280.
