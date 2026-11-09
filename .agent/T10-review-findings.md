# T10 review — pasted by the secretary

The reviewer's shell access was revoked after three calls, so it could not create this file. The text
below is its report, verbatim. Reviewing model: `ship-reviewer`, session `ses_e41315429ffeJyAkQmtysRDY9f`,
2026-11-09.

---

**Verdict: ship-with-caveats** — doubling, boundaries, secret hygiene and issue handling are sound;
the gate's definition of "the day ran" has one real semantic gap.

**Should fix — partial success counts as a run.** `freshness_gate.py:120` + SQL `:59-62` accept *any*
`status='success'` row inside the window. `nafdac_index` lands ~3–5 min into a 1.5 h run, so a night
where it succeeds and everything after fails is graded `fresh`; the 04:17/06:43 retries skip, 4 of 5
sources sit a day old. Not silent (one "pipeline run failed" issue), but healing only engages when
nothing succeeded.

**Should fix — the day's completion has no ledger.** `scripts/match_listings.py` writes no
`scrape_runs` row (grep-verified); `link_product_nrn.py` likewise. A fire that scrapes fine but fails
match/refresh is a fully-run day, never retried, matview stale for 24 h — the state the workflow's own
comment calls indistinguishable from a quiet market. Cheap fix: a completion row from
`match_listings`, required by the gate.

**Sound — double execution.** Workflow-level `concurrency` serialises; GitHub keeps at most one pending
run per group, so the 04:17 gate may be silently discarded by the 06:43 fire (benign — the survivor
re-queries the DB, which is what actually prevents overlap, not queue order).

**Boundaries — sound, one second-exact edge.** 02:59 finish → stale (correct); 03:00:00.000 exactly →
fresh (`>=`), only reachable via a human-dispatch run that *started* before 03:00 — negligible. Late
fire, 03:00 UTC calendar window, no-DST, and naive→UTC coercion (`:115-116`) all correct; `finished_at`
is `timestamptz` (`schema/002_tables.sql:183`) so the naive branch is a dead fallback.

**`missed`** — wrong only in the loud direction (`:124-126`); the quiet direction is the same
any-source-success surface as finding 1, plus the structural limit the secretary recorded: all three
fires dropped ⇒ no workflow, no issue, nothing.

**Notify — clean.** TITLE is a workflow-controlled constant (safe in `--jq`); REASON is newline-stripped
(`:170`), reaches `${REASON}` only via env expansion (no substitution), password masked (`:242-244`);
skipped pipeline → empty TITLE → exit 0.

**Optional** — no committed test pins the 8-case `evaluate()` matrix; `Report the ledger` step-level
`DATABASE_URL` shadows the Preflight normalisation (pre-existing); pending-run replacement is
undocumented in the comment.

**Verified by me:** full `freshness_gate.py` + whole `daily.yml` read; concurrency/queue semantics
reasoning; schema timestamp types; grep for ledger writes; arithmetic cross-check of the secretary's
live output (10:15Z + 19.08 h = 05:20Z window, matching run 42464123751).

**Not checked:** live DB, gate against Actions (GITHUB_OUTPUT pickup, `github.token` issue writes,
pending-run behaviour) — shell denied after three calls, so this was purely static review plus
reasoning.
