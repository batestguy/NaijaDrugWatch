# T1120-h — handoff section

## 1. Written

Added the requested section at the top of `PROGRESS.md`, `PROGRESS.md:5-62`, above the existing 20 November block. No earlier text in `PROGRESS.md` was changed.

## 2. Sources

- Collection dates and published counts — `README.md:5, 27-42`; corroborated by `FROZEN.md:3-8, 103-115`. This supports the 7–15 November collection window, 16 November stop, 2,800 listings, 559 matched, 1,433 products, 335 priced products, 10,967 registrations, 1,856 statuses (16.9%), 154 listings across 86 products, 261 rows, 44 comparisons, 428 index rows, and three week-over-week comparisons with no change.
- Page build counts — `README.md:48-55` and the 20 November block in `PROGRESS.md:104-105`: 3,791 and 3,838 checks, each with zero unexplained.
- Pages workflow and triggers — `.github/workflows/pages.yml:14-23, 56-81`; current publication is also documented in `README.md:57-59` and `PROGRESS.md:114-123`.
- Collection stop and workflow id — `FROZEN.md:6-8`; the supplied brief records the current disabled state at `.agent/T1120-h-brief.md:39-43`.
- The 24-second Pages run — supplied brief, `.agent/T1120-h-brief.md:35`; not independently checked here. The ₦10.99 index minimum and one-under-₦20 row are recorded as re-queried by the secretary on 21 November in `PROGRESS.md:62`; I did not run that query myself.
- Index threshold and definition — `scrapers/common.py:52-58` sets the ₦20 floor; `schema/004_materialized.sql:8-23` defines the index without it; the 20 November block in `PROGRESS.md:136-140` records one row below the floor.
- The dashboard's 288-name count — `scripts/build_dashboard.py:347-350, 411-413`; the 335 product count is in `README.md:34-36`. The front-page mixed counts are recorded in the brief at `.agent/T1120-h-brief.md:79-81` and in `PROGRESS.md:141-144`.
- Greenbook transport — `scrapers/common.py:14-16, 135-146`; the recorded 7 November probe is in the earlier `PROGRESS.md` known-risks section.
- Accessibility qualification — the brief's 5.14:1 build-time contrast figure is at `.agent/T1120-h-brief.md:82-83`; latest changes not audited: `PROGRESS.md:130`; earlier audit: `FROZEN.md:139-148`.
- Screenshot review and misleading patch-script names — `.agent/T1120-h-brief.md:84-90`.
- Rebuild commands — `.agent/T1120-h-brief.md:56-65`. The manual dispatch command is supported by the GitHub CLI manual, https://cli.github.com/manual/gh_workflow_run; the watch option is documented at https://cli.github.com/manual/gh_run_watch (read 20 November 2026).

Shell permission was denied when I tried to check interpreter and CLI availability, so I did not run a database query, build, or Actions check. The index re-check is recorded in `PROGRESS.md:62`, but I did not inspect its command output. The reported Pages run and other published counts remain sourced from the repo and supplied brief, not fresh command output from this session.

## 3. Removed or qualified

- Replaced the brief's blanket “axe was never run” with a version-specific statement. `FROZEN.md` records an earlier axe run, while the 20 November navigation changes remain unaudited. The current limitation was kept.
- Clarified that the `daily` YAML still has cron triggers but the workflow is disabled on GitHub, as recorded in `FROZEN.md`. This avoids implying that removing the cron lines is what disabled collection.
- Removed the initial stale-status note after `AGENTS.md` changed during the task to state that Pages is live and collection is frozen. I did not edit that file.
- Omitted the exact 5.14:1 contrast figure because it was not needed to state the limitation and I did not reproduce it. Kept the caveat that a build-time contrast check is not an accessibility audit.
- Omitted the remote Pages setting and “no `gh-pages` branch” detail because neither is established by the local files I read. The live URL and local deployment workflow are retained.
- Narrowed the concurrent-edit warning to the sequence recorded in the existing 20 November block: T1120-e restored an older `build_site.py` while T1120-b/T1120-c changes were uncommitted. No earlier block was changed.

## 4. Open

No `TODO(source)` placeholders remain. The 24-second Pages run, other published database counts, and remote workflow state were not independently checked by me. The 21 November index re-check is recorded in `PROGRESS.md:62`, but I did not rerun it. The certificate probe is dated 7 November and should be repeated before describing the condition as current.
