# T10 report — *written by the secretary, not the agent*

The `builder` hit its 40-call cap with the code complete and `.agent/T10-report.md` unwritten.
Everything below was re-run by me on 2026-11-09 between 05:35Z and 05:55Z. Where I quote the agent's
claim I mark it as such; where I paste output, I ran it.

## 1. Changed

| File | Change |
|---|---|
| `.github/workflows/daily.yml` | **+116, −0** (`git diff --numstat`). Two extra `schedule` entries; a `freshness` job; `pipeline` gains `needs` + `if`; a `notify` job on `always()`. |
| `scripts/freshness_gate.py` | New, 267 lines. Read-only. Decides "has the day run?" from `scrape_runs`; never touches `v_pipeline_health`. |
| `.agent/T10-evidence.md` | My input packet (docs quotes + run history). |

`PROGRESS.md` shows as modified but that is **my** edit from earlier in the session, not the agent's.

## 2. Verified — commands and real output

**YAML still describes the same pipeline.** All eight original steps present, in order:

```
steps_pipeline ['actions/checkout@v4', 'actions/setup-python@v5', 'Cache the embedding model',
 'Install dependencies', 'Preflight', 'Pipeline', 'Keep the archives', 'Report the ledger']
cron ['0 3 * * *', '17 4 * * *', '43 6 * * *']
pipeline_if needs.freshness.outputs.run == 'true'
notify_if always()
notify_perms {'contents': 'read', 'issues': 'write'}
```

**The decision rule, re-run by me against eight stubbed states** (`evaluate()` called directly):

```
PASS  live today, nothing run      got=('stale', True, False)   age=19.08h
PASS  same day already ran         got=('fresh', False, False)  age=1.75h
PASS  26h-hole: 23.45h old         got=('stale', True, False)   age=23.45h
PASS  late fire served yday        got=('stale', True, False)   age=24.5h
PASS  whole day skipped            got=('stale', True, True)    age=43.33h
PASS  never ran                    got=('stale', True, True)    age=None
PASS  manual dispatch forces run   forced/True
PASS  naive timestamp read as UTC  fresh
```

The third case is the one that matters: a 26-hour threshold would have called a 23.45-hour-old run
*fresh* and skipped exactly the missed fire this ticket exists to catch. The UTC-day window is
correct; the briefed 26 h was wrong, and the deviation is justified in the script docstring.

**Live database, real clock:**

```
decision=stale run=true missed=false | last successful run 2026-11-08T10:15:13Z (19.08 h ago)
                                     | gate window opened 2026-11-09T03:00:00Z
EXIT=0
```

**Simulated already-run day** (`--now 2026-11-08T12:00:00Z`): `decision=fresh run=false`, `EXIT=0`.

**Refuses to guess** — both failure modes exit 2, name the target, leak no password:

```
::error title=freshness gate::DATABASE_URL is empty or unset ... Refusing to guess.        EXIT=2
::error title=freshness gate::cannot reach or read the database (host=127.0.0.1 db=db):
  ConnectionTimeout: connection timeout expired ...                                        EXIT=2
```
(That test ran with the literal password `secret` in the URL; it does not appear in the output.)

**The notify job's decision matrix**, exact `run:` block extracted from the YAML and executed under
bash with a stub `gh`:

```
--- a healthy day             nothing to report: gate=stale missed=false pipeline=success
--- b pipeline failed         opening issue: daily: the pipeline run failed
--- c whole day missed        opening issue: daily: a day passed with no run
--- d gate could not decide   opening issue: daily: the freshness gate could not decide
--- e failure, issue exists   commenting on issue #42: daily: the pipeline run failed
--- f fresh, pipeline skipped nothing to report: gate=stale missed=false pipeline=skipped
```

Deduplication by exact title works: case *e* commented on the existing issue instead of opening a
second one.

## 3. Deviations

1. **The gate decides on a UTC day window (03:00 boundary), not the briefed 26 h age threshold.**
   Correct, and demonstrated above.
2. **Three fires, not two** — 03:00, 04:17, 06:43 UTC. The 04:17 one exists so a merely *late* 03:00
   fire is usually already running; `concurrency` then makes the retry wait rather than overlap.
3. **`.agent/T10-report.md` was not written by the agent** — it ran out of steps first. Progress lines
   for work after 06:05 are missing for the same reason.

## 4. Unproven

- **A real scheduled fire.** Cannot be tested from here; the first honest evidence is 2026-11-10
  03:00Z or a hand dispatch after this is pushed.
- **All Actions-side wiring**: `$GITHUB_OUTPUT` pickup, job-level `permissions` overriding the
  workflow's `contents: read`, `needs.pipeline.result == 'skipped'` behaviour, and whether
  `github.token` can open an issue on this repo.
- **Whether three fires materially beat one.** Same best-effort scheduler. Three at uncongested
  minutes is better odds, not a guarantee, and nothing measures the odds.

## 5. The limit worth stating plainly

**If all three fires are dropped, this still says nothing.** The notifier runs when the workflow runs;
a day where GitHub delivers nothing produces no job, no issue and no comment. Three fires narrow that
gap; they do not close it. Closing it needs something outside GitHub's scheduler — a free external
heartbeat hitting `workflow_dispatch` — which is a new third-party dependency and a token, so it is a
decision for the user, not for this ticket.
