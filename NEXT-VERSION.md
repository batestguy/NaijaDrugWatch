# Next version — what to change, and why, if this project is ever opened again

This is not a wish list. Each item names the measurement that justified it and what it would cost. The
frozen vintage of 2026-11-16 is the baseline every figure below comes from; nothing here is a criticism
of that vintage, which is what it says it is.

**The one-line summary.** The pipeline collects well and attaches badly. 2,800 prices resolve to 335
medicines, and 2,241 prices are attached to nothing at all. Every item below is either a cause of that
or a consequence of it.

---

## 1. Match shop titles to each other, and let the licence be an annotation

**The evidence.** MedPlus's catalogue was widened elevenfold, from 128 products collected to 1,399. The
number of its prices that attached to a named medicine went from 227 to 225. Meanwhile 1,216 of the
2,241 unattached prices state a dose — they are not unreadable, they are unattached — and of the 1,433
products in the catalogue only 335 ever carry a price at all. The catalogue is anchored to the NAFDAC
register, and the register does not contain what pharmacies actually shelve: supplements, sundries,
brands the register names differently.

**The change.** Make the unit of comparison a normalised shop title — name, strength, form and pack
count — matched across two shops. Use the registration number as a flag where one can be found, not as
the gate that has to be passed first. A comparison then means "two shops sell the same thing under the
same description", which is the claim the page actually makes.

**The cost.** About a week, and it changes what `products` means, so the views, the dashboard and the
export all move with it. The risk is real and specific: a string match can pair two different pack sizes
and call it a price gap. That is exactly what the 20 pack cards were designed to catch, so the sample
should be re-run against the new definition before any of it is published.

## 2. Find out why the candidate stage returns nothing

**The evidence.** Of 698 products with no registration linked, **501 never had a candidate at all** above
the similarity floor. No rule change can rescue those; the embedding search simply does not offer them.
The two-stage matcher is the project's own non-negotiable design, so the first stage failing quietly is
the most expensive defect in the pipeline.

**The change.** Measure recall at the candidate stage directly — for a sample of unattached titles, is
the right product in the top 10? — then choose: a better embedding model, a second recall channel
(trigram, or brand-alias expansion), or a lower floor with the rules doing more work.

**The cost.** Two or three days, most of it measurement. No schema change.

## 3. Teach the strength rule about concentration

**The evidence.** 68 products state a mass per volume (`250 mg/5 ml`, `20 mg/ml`) against a register that
states a plain mass. They are rejected as "strength disagrees" when they are the same medicine.

**The cost.** A day, and a bounded gain: 68 products out of 698. Do it after item 2, because item 2 will
change which candidates even reach this rule.

## 4. Decide what belongs in the catalogue at all

**The evidence.** A random sample of unattached titles contained a large share of supplements and
vitamins, and a minority of things that are not medicines: baby diapers, a blood pressure monitor, a
colostomy bag, mouthwash. They are genuinely on pharmacy shelves and genuinely priced. They are not
medicines, and the register can never contain them.

**The decision, which is the author's and not a technical one.** Either the catalogue admits supplements
and the "medicine" claim narrows to "what a pharmacy sells with a price", or the scrapers stop collecting
them and every downstream number gets cleaner. Doing neither leaves the price tables mixing the two, as
they do now.

## 5. Retire the weakest source, or explain why it stays

**The evidence.** Drugstore.ng contributes 200 prices and **10 matches**, and only 13% of its titles state
a dose. Its titles read like a marketplace listing rather than a pharmacy catalogue, and it can never
form a comparison because it is recorded as one national shop.

**The cost.** An hour to remove it from the workflow and the page; one paragraph in the limitations to
keep it.

## 6. Fix the two display collisions

**The evidence.** The comparison table carries 44 rows over 42 distinct name-and-state pairs. Amlodipine
5 mg appears at ₦950 beside Amlodipine 10 mg at ₦400; a Vitamin B Complex 100 ml syrup at ₦1,250 beside a
1,000-tablet pack at ₦2,300. Both pairs are correct as separate products and both read as a price cut.

**The change.** Show strength and pack in the row label, not only in a column a reader skips.

## 7. Finish the unit story

**The evidence.** The page now prints the unit beside each unit price, which fixed the millilitre row.
But 18 of the 88 listings behind a comparison carry a pack count with no unit at all, and one MedPlus
"pack 10" is a strip of ten tablets. The underlying parse is what is missing, not the label.

**The cost.** A day in `parse_pack`, plus a re-scrape to populate it.

---

## Not on this list, deliberately

- **An API.** The spec asked for one. The project is frozen and the data is published as a dated
  export; an API over a database that is switched off would be a promise with nothing behind it.
- **A fourth pharmacy.** More collection would add another thousand unattached prices. Item 1 is the
  lever, not volume.
- **National coverage.** The three sources each publish one price, not a price per state. Nothing in the
  data supports a national claim and no amount of scraping changes that.

## What a reader of the next version should check first

1. Does the 40-card sample survive the change? Re-run it against the new definition of a product before
   publishing anything.
2. Does `scripts/verify_restore.py` still pass, and does `scripts/check_published_match.py` still show the
   two published copies identical?
3. Is the new vintage labelled with a new date, and does `FROZEN.md` state what changed and why? A frozen
   vintage is immutable; corrections ship as a new vintage, never as an edit to the old one.
