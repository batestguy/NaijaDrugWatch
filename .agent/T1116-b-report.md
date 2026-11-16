# T1116-b report — machine re-read of the licence sample

## Result

All 20 sampled pages returned readable page text over HTTPS. The six registration fields checked were status, expiry date, approval date, product name, strength, and registration number.

- **20** records opened and read
- **20** agreed on all six fields
- **0** disagreed
- **0** could not be read

There are no disagreement records. The item-by-item values and page text are in `.agent/T1116-b-records.jsonl`.

## What was compared

Stored name and strength mean `nafdac_registrations.product_name` and `nafdac_registrations.strength` on the row linked to the sampled product. They are not the separate product-table display name and strength.

The page shows the product name and strength in its “Product Details” block, but does not give those two lines their own field labels. The recorded values are the text shown in that block; the evidence line for each record says this. Status, NRN, approval date, and expiry date are shown with labels.

The visible text matched the stored text exactly for all six fields. One source spelling worth noting: the page and stored registration both say **“Erythromycin Supension”** for registration `B4-1535`; that is a match, not a disagreement.

## Disagreements and page failures

None. Each of the 20 page requests returned page text. The fetch tool did not expose numeric response codes for successful pages, so this report does not claim a specific success code. No page returned an error response.

## What this does not establish

- This is a machine re-read of the same NAFDAC Greenbook source, not the pre-registered human check and not an independent source.
- It checks what the page displayed during this read. It does not establish that the register itself is correct, or that a medicine is genuine, safe, sold, or legal.
- The strength is visible in the product-details block but is not separately labelled on the page.

## Evidence and verification

The stored values were read with the pinned interpreter and `scripts/dbq.py`, using a read-only join from the 20 sampled product ids to their linked registration rows:

```powershell
.venv\Scripts\python.exe -X utf8 scripts\dbq.py "select p.id, p.canonical_name, p.strength as product_strength, p.nafdac_registration_number, r.registration_number, r.product_name, r.strength as registration_strength, r.status, r.expiry_date, r.approval_date, r.source_url from products p left join nafdac_registrations r on r.registration_number = p.nafdac_registration_number where p.id in (150,21,2232,2243,2302,231,2330,2446,2458,2488,2493,2494,365,44,440,490,491,578,599,869) order by p.id"
```

The records file was checked against the pre-registered sample and all six stored/page values:

```powershell
.venv\Scripts\python.exe -X utf8 -c "import json,pathlib; s=json.loads(pathlib.Path('.agent/verify-sample-2026-11-16.json').read_text(encoding='utf-8')); ids=[x['id'] for x in s['lists']['licence']['items']]; r=[json.loads(x) for x in pathlib.Path('.agent/T1116-b-records.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]; rid=[x['id'] for x in r]; keys=[('registration','page_registration'),('stored_status','page_status'),('stored_expiry','page_expiry'),('stored_approval','page_approval'),('stored_name','page_name'),('stored_strength','page_strength')]; print('sample_ids_match=',ids==rid,'records=',len(r),'all_six_equal=',all(all(x[a]==x[b] for a,b in keys) for x in r),'all_agrees_flags_true=',all(x['agrees'] is True for x in r),'all_source_pages_https=',all(x['page_url'].startswith('https://') for x in r))"
```

Actual output:

```text
sample_ids_match= True records= 20 all_six_equal= True all_agrees_flags_true= True all_source_pages_https= True
```

`robots.txt` was read first and returned `User-agent: *` with an empty `Disallow:` rule. Page requests were made one at a time. The fetch tool did not expose per-request timestamps, so exact spacing is not independently recorded here.
