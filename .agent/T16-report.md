# T16 report — *written by the secretary, not the agent*

The `builder` reached its step limit with the script written, backtested and wired, but before writing
this file. It also left one claim unresolved, which turned out to be wrong — see §3. Everything below
was re-run by me on 2026-11-10 between 06:40Z and 07:05Z.

## 1. Changed

| Path | Change |
|---|---|
| `scripts/stock_signal_watch.py` | **New.** Per pharmacy per day: rows written and share with `in_stock is null`. Compares the latest day against the median of prior days, ignoring days under 50 rows. Flags when a prior median below 10% is followed by a day above 25%. Exit 0 clean, 1 alarm, 2 undecided. Read-only. |
| `scripts/stock_signal_watch.py:277-289` | **My edit.** Read-only enforcement did not work as written; see §3. |
| `.github/workflows/daily.yml:83-89` | `pipeline` gains three job outputs: `stock`, `stock_detail`, `stock_outcome`. |
| `.github/workflows/daily.yml:263-279` | New last step `Watch the stock signal`: `continue-on-error: true`, `if: always()`. |
| `.github/workflows/daily.yml:300-306`, `:326-330`, `:347-352` | `notify` reads the three values; new `elif` branch for a lost stock signal; detail line appended to the issue body. |

`git diff --stat`: `daily.yml | 48 +`, `medplus.py | 81 +-`, plus the two new files.

## 2. Verified — by me

**The backtest, the ticket's real test:**

```
$ python -X utf8 scripts/stock_signal_watch.py
MedPlus 2026-11-08  1092 rows   13 unknown   1.2%  prior
MedPlus 2026-11-09   128 rows  128 unknown 100.0%  latest ALARM
                 prior median unknown 0.6%
ALARM: MedPlus went from 0.6% to 100.0% unknown (day 2026-11-09, 128 rows written, 128 unknown)
HealthPlus: ok (prior median 0.0%, latest 0.0%)
EXIT=1
```

`--as-of 2026-11-08` → `ok: no source lost its stock signal`, `EXIT=0`. Both branches seen live.
MedPlus's 43 rows today are correctly ignored by the 50-row floor.

**The workflow:** three `cron:` lines unchanged; `scripts/freshness_gate.py` untouched
(`git diff` empty); YAML parses with `jobs: [freshness, pipeline, notify]` and
`triggers: [schedule, workflow_dispatch]`.

## 3. The agent's open defect was real, and it was mine to fix

The agent wrote that `conn.read_only = True` makes writes an error, and then honestly reported that
its own test showed an `update` succeeding. I reproduced it exactly as the script was configured:

```
psycopg.connect(url, autocommit=True) ; conn.read_only = True
  UPDATE SUCCEEDED   <-- NOT enforced
  DELETE SUCCEEDED   <-- NOT enforced
```

**In autocommit mode that attribute does not apply.** The comment in the code claiming server
enforcement was false. Fixed by setting the session default at connect time:

```
psycopg.connect(url, autocommit=True, options="-c default_transaction_read_only=on")
  default_transaction_read_only -> on
  UPDATE REFUSED: ReadOnlySqlTransaction
  DELETE REFUSED: ReadOnlySqlTransaction
  INSERT REFUSED: ReadOnlySqlTransaction
  reads still work: 260
```

The script still alarms and still exits 0 on the clean branch after the change.

## 4. Unproven

- **GitHub Actions has not run any of this.** That `continue-on-error` keeps the `pipeline` job green
  while the step's outcome becomes `failure` is documented behaviour, not observed here. The first
  night it matters is the first night it is exercised.
- **The notify branch was executed by the agent in six states and not re-executed by me.** I read the
  `elif` chain and confirmed it sorts after pipeline-failure and missed-day, so a bigger problem still
  wins; I did not re-run the shell.
- **The threshold is a judgement, not a measurement.** 10% / 25% / 50 rows fits the one real event we
  have. A source that degrades gradually — 5%, then 12%, then 30% — will not trip it.
- **`stock_quantity` and `stock_evidence` are still archive-only.** The watch uses `in_stock is null`,
  not the evidence string, so a source that reports a count of 0 for everything would read as
  confidently out of stock rather than unknown, and this monitor would not see it.
