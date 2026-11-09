# T10 evidence — what GitHub says about `schedule`, and what this repo's history says

Collected 2026-11-09 05:10-05:20Z. Verify anything you rely on; do not re-collect it from scratch.

## Repo-side facts

```
gh repo view --json defaultBranchRef      → batestguy/NaijaDrugWatch default=main
gh api repos/.../actions/workflows/daily.yml
  → {"state":"active","path":".github/workflows/daily.yml",
     "created_at":"2026-11-08T08:59:18+01:00"}          # = 2026-11-08T07:59Z
gh api repos/.../actions/permissions       → {"allowed_actions":"all","enabled":true}
git log --diff-filter=A -- .github/workflows/daily.yml
  → 025e804 2026-11-08 08:59:14 +0100 feat(ci): daily pipeline            # first commit on main
```

Run history (`gh run list --limit 100`, grouped by event): **5 × workflow_dispatch, 0 × schedule.**
The last run is 42464123751, 2026-11-08T08:43:20Z, `completed/success`, 1 h 32 m.

First scheduled opportunity: **2026-11-09T03:00Z**. Checked at 05:13Z: no run, and
`select count(*) from scrape_runs where started_at >= '2026-11-09'` = **0**.

So the 60-day-inactivity auto-disable, "file not on the default branch", and "Actions disabled" causes
are all ruled out. The only remaining causes are scheduler delay or drop.

## GitHub's documented position

- `schedule` is **best-effort**, not a guarantee. Runs "can be delayed during periods of high loads of
  GitHub Actions workflow runs"; "high load times include the start of every hour"; "if the load is
  sufficiently high enough, some queued jobs may be dropped". A dropped run produces **no run, no log,
  no notification**.
- `:00` and `:30` are the most contended minutes, because most schedules are configured there.
- Public repositories: scheduled workflows are **auto-disabled after 60 days without repository
  activity**, silently. Not applicable here (commits daily), but it is the other silent killer.
- Timezone is UTC unless a per-schedule `timezone:` field is used.

## 2026 field reports worth knowing (community discussions, not official)

- Discussion #207346 and #206019: since ~2026-08-26, `schedule` runs dropped or delayed **hours**, with
  `workflow_dispatch` still starting in seconds. New repos and new accounts are reported to get the
  lowest scheduler priority.
- Discussion #201738: consistent 8-14 h delays on a new repo; a second fire at a different minute and
  an external trigger were the reported workarounds.
- The consistently recommended escalation, if in-repo mitigations fail: an external free scheduler
  (cron-job.org and similar) hitting `workflow_dispatch` / `repository_dispatch` with a token. That is
  a new dependency and a new secret — **not** in scope for T10; propose it, do not install it.

## What this implies for the fix

1. One fire is not a schedule. A second fire at an odd minute costs ~60 s when the day is already done.
2. The retry must decide from the database, not from GitHub's UI, and `v_pipeline_health` cannot answer
   (never-run sources produce no row).
3. A dropped fire is an **absence**, not a failure — an `if: failure()` notifier cannot see it. The
   retry firing is what converts absence into an event.
