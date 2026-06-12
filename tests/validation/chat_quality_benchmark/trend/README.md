# Chat-Quality Benchmark — Durable Trend Store (PLAN-0110 W4)

This directory holds the **committed, in-repo longitudinal trend store** for the
chat-quality benchmark (PRD-0091 FR-13/14/15, AD-5).

| File | Role |
|------|------|
| `trend.sqlite` | Single-file SQLite store. Tables `runs` + `question_results` (schema in PRD §6.4). One `runs` row + N×R `question_results` rows per benchmark run. Queryable for trend windows. |
| `trend.jsonl`  | Deterministic newline-delimited JSON mirror of the SQLite tables (one line per `runs`/`question_results` row, tagged `"kind"`). Grep-able, zero-tooling, and the lock-free backstop if two parallel sessions ever contend on the SQLite file (F-5). |

Both files are written by `scripts/chat_quality_trend.py` (the `TrendStore`
helper) and appended to by `scripts/run_chat_quality_benchmark.py` after every
run. **Appends are idempotent by `run_ts`** — re-running the same run replaces
its rows rather than duplicating them — and the only timestamps written are the
`run_ts` / `started_at` passed in by the runner, so the committed files are
deterministic and diff-friendly.

## Baseline + regressions

- `--set-baseline <run_ts>` pins an existing run as **the** comparison baseline
  (`is_baseline=1`; only one at a time). The bare `--set-baseline` flag pins the
  run produced by that invocation.
- Each run diffs against the registered baseline **and** the immediately-prior
  run (rolling window), emitting `_regressions.json` into the run directory and a
  regression summary into `_report.md`.
