
---

## Secretary verification — 2026-11-10, after the agent's report

Re-run independently, not taken from the report above.

```
1. row set unchanged          260 cells / 45 comparisons   (same before and after)
2. the three states, cells    active 142 (30 comparisons)
                              not active 70 (12 comparisons)
                              not read 48 (3 comparisons)
3. safety                     flagged with a NULL status: 0
                              "active" label without a literal Active status: 0
4. the twelve                 flagged comparisons: 12 products
                              same set computed from v_suspicious_listings + 2 in-stock pharmacies: 12
                              difference in either direction: 0
5. shape                      25 columns; last two registration_flagged, registration_status
                              duplicate product+state cells: 0
                              null winning prices: 0
```

**The brief was wrong and the agent was right to say so.** It asked for 12 flagged products and the
view returns 70. Twelve is the comparison subset; the other 58 are single-pharmacy cells that are also
priced and also carry an inactive licence. The agent flagged the discrepancy instead of adjusting the
view to match the brief, which is the correct response.

**Deviation from the brief, harmless:** the two columns are appended `registration_flagged` then
`registration_status`, not the order the brief listed. Appending them the other way round would have
needed a drop-and-recreate for no gain; the order is documented in `docs/views.md` and in the file.

**Unproven, unchanged:** nothing has been rendered in a browser, so the three labels are verified as
values in the data and as code in the app, not as pixels. The twelve flagged comparisons now say so in
the table; whether that reads clearly to a person is a question for the eyeball pass.
