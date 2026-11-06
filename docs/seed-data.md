# Seed data

## Source

**#FixMedPrices — "Medicine Prices"**, Code for Nigeria, published via openAFRICA.
Licence **CC-BY-4.0**; credit is required wherever this data appears.

- Dataset: <https://open.africa/dataset/b48de105-0c93-4f47-a718-a4d54b3c2b9b>
- Resource: `medprices.csv`, 195,009 bytes, vendored at `seed/medprices.csv`
- Retrieved: 2026-11-06

## Shape

1,074 data rows over 597 distinct drug names, with 88 `brand_names/N` columns.

```
strength, name, form, price, brand_names/0 … brand_names/87, id
20 mg/ml, Abacavir, solution, 0.0197, Abavir, 0
```

- 386 of 1,074 rows carry at least one brand alias (average 4.3 when present).
- `form` is a controlled but messy vocabulary: `tab-cap`, `suspen`, `opht oint`, `suppos`,
  `vial`, `ampoule`, `powder`. Normalise before joining to `drug_match_rules.required_form`.
- Class coverage of the stated MVP scope: malaria 28 rows, hypertension 17, diabetes 13,
  antibiotics 51. Diabetes is thin — expect to hand-extend it.

## What it loads

| Table | Rows | Rule |
|---|---|---|
| `products` | 1,074 | one per (name, strength, form); `brand_aliases` from the 88 columns |
| `drug_match_rules` | 1,074 | `match_pattern` = the drug name; strength and form as required filters |

## What it must never load

**`nafdac_registrations`.** The file has no registration number, status, expiry, applicant or
manufacturer. Seeding the regulatory layer from it is impossible, not merely inadvisable.

**`price_history`.** The `price` column spans 0.0007 to 1,877 — fractions of a currency unit
across mixed pack bases, not NGN retail. Loading it would corrupt every comparison in
`v_cheapest_per_product_state` and `mv_drug_price_index`.

## Loader behaviour

`scripts/load_seed.py`:

- `--dry-run` prints the SQL to stdout and a one-line summary to stderr. No database, no driver
  required — this is the check to run in CI.
- Without `--dry-run` it requires `DATABASE_URL` and refuses to start if unset.
- Inserts use `ON CONFLICT DO NOTHING`, so re-running is safe and does not duplicate rows.
- Names and brand aliases are accent-stripped and whitespace-collapsed, so `Paracétamol` and
  `Paracetamol` resolve to the same canonical name.
