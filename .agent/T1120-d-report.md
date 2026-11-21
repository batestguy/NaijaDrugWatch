# T1120-d report

## Written

- `README.md:1-249` — rewrote the front door. The data table and build-check scope are at `README.md:23-53`; the generated pages and screenshots are at `README.md:55-101`; the process and tools are at `README.md:103-132`; quickstart at `README.md:134-179`; archive, licence and sourcing at `README.md:181-199`; limitations and untested claims at `README.md:201-221`; repository map at `README.md:223-249`.
- `.agent/T1120-d-progress.md:1-6` — work log.

## Sources

- `README.md:27-53`: measured price, catalogue, registration, comparison, index and build-check values come from `.agent/T1120-d-brief.md:19-42`.
- `README.md:29-31`: collection dates, daily coverage, first-day count and last-day count come from the user's steering update, measured against the database this session.
- `README.md:183-193`: archive counts, sizes, checksum, release and DOI come from the brief's table; `docs/published-vintage.json:3-15` also records the archive metadata.
- `README.md:57-101`: page count and labels come from `.agent/T1120-d-brief.md:68-80`. The screenshot names and order come from lines 47-66; all supplied image files were found and left unchanged.
- `README.md:125,141`: the model identifier is in `requirements.txt:2-3` and the brief. The pinned Python command is retained from the prior README quickstart and the brief's quickstart instructions. License names come from the prior README and the brief.

## Removed

- Replaced the old daily-update and “where is it cheapest” framing with the frozen status and the comparison rule.
- Corrected the old two-page description and the methods-page label. The README now describes all three generated pages and does not present them as deployed pages.
- Removed older run timings, stale registration counts, narrow unit-price breakdowns and previous build-check totals. They were either outside the allowed source table or no longer current.
- Kept the limitations but left some exact quantities qualitative: the unit-price share, human-review sample size and request interval are not stated as figures. The README still says unit prices are often unknown, the human review is incomplete, and requests are limited per domain.
- The technology list names PostgreSQL, pgvector, Python and psycopg without adding numeric database or embedding specifications outside the allowed table.

## Open

- No `TODO(source)` remains.
- The final shell-based diff check and post-edit status check were blocked by shell permission denial. I read back the README, checked the required image references, and searched for prohibited terms. The pre-edit status showed other working-tree changes; my patch operations edited only `README.md` and the requested ticket files.
