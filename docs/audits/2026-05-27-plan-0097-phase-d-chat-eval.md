# PLAN-0097 Phase D — Live-Stack Chat-Eval Acceptance Gate

**Date:** 2026-05-27
**Branch:** `feat/plan-0089-wi-a`
**Head:** `d2689b79` (`docs(bug-patterns): PLAN-0097 W3 — file BP-581 (ANALYZE post-index) + BP-582 (typed batch reason codes)`)
**Verdict:** **FAIL — BLOCKED at migration step.** Chat-eval gate not executed.

---

## Executive Summary

Phase D acceptance gate was halted at Step 4 (apply migrations 022 + 023). Migration `022_analyze_fundamentals_tables.py` references a table `dividend_summary` that does not exist in `market_data_db`, so `alembic upgrade head` raises `UndefinedTableError` and leaves the schema pinned at revision **021**. Because the migrations PLAN-0097 W4 introduced are the substrate the chat-eval flags depend on (composite fundamentals indexes + ANALYZE-refreshed planner stats), running the chat-eval before migrations apply would produce numbers that cannot legitimately be compared against the ITER-9 baseline. Per the task's "do NOT modify source code; if a step blocks, STOP and report" constraint, the run was aborted at Step 4.

A second, pre-existing live-stack defect surfaced during health verification: market-data emits `screen_fields_refresh_error` once per minute because a `has_fundamentals` row with `field_type='boolean'` violates the `ck_screen_field_metadata_field_type` check constraint.

---

## Step-by-Step Trace

### Step 1 — Branch + head (PASS)

- Branch: `feat/plan-0089-wi-a`
- HEAD: `d2689b79 docs(bug-patterns): PLAN-0097 W3 — file BP-581 (ANALYZE post-index) + BP-582 (typed batch reason codes)`
- All PLAN-0097 W1–W4 commits present (`b422126d` W1, `fb5631c3` W2, `a960d8f7`+`cfe7c01d` W3, `8c3a9249`+`593b3344`+`1a8077ae`+`8906009f`+`88bef8bc` W4).

### Step 2 — Image rebuilds (PASS)

- `worldview-market-data:latest` rebuilt (exit 0).
- `worldview-rag-chat:latest` rebuilt (exit 0).
- `worldview-knowledge-graph:latest` rebuilt (exit 0).
- `worldview-nlp-pipeline:latest` rebuilt (exit 0).

### Step 3 — Container recreate (PASS)

`docker compose ... up -d --no-deps --force-recreate` recreated all four containers. Within ~45s all reported `healthy`:

```
worldview-rag-chat-1        Up 14 seconds (healthy)
worldview-nlp-pipeline-1    Up 14 seconds (healthy)
worldview-knowledge-graph-1 Up 14 seconds (healthy)
worldview-market-data-1     Up 14 seconds (healthy)
```

### Step 4 — Apply migrations (FAIL — BLOCKER)

Pre-state: `alembic current` = **021**.

Running `alembic upgrade head` produces:

```
INFO  [alembic.runtime.migration] Running upgrade 021 -> 022,
      ANALYZE the 18 fundamentals section tables post-019 composite indexes.
asyncpg.exceptions.UndefinedTableError: relation "dividend_summary" does not exist
[SQL: ANALYZE dividend_summary]
```

Post-state: `alembic current` = **021** (transaction aborted; 022 and 023 not applied).

**Root cause.** Migration 022 (`services/market-data/alembic/versions/022_analyze_fundamentals_tables.py`) declares an 18-table `_TABLES` tuple that includes `dividend_summary`. Inspection of `market_data_db` (live and seeded) shows the dividend data is held in `dividend_history` and `splits_dividends`; there is no `dividend_summary` table in the schema, and no prior migration creates it. Migration 019 (whose indexes 022 is supposed to refresh) therefore cannot have indexed `dividend_summary` either — the entry in `_TABLES` looks like a copy-paste artifact from spec drafting.

The author of 022 explicitly used `autocommit_block` so partial progress would not be lost, but the very first iteration of the loop happens to be `analyst_consensus` (sorted alphabetically), so by the time `dividend_summary` raises, no ANALYZEs have committed in a useful order — and more importantly, the subsequent migration **023** (which `1a8077ae` deliberately made idempotent / IF NOT EXISTS so it could ride on top of 019) is never reached. The whole W4 index/stats program is undeployed.

**Per task constraint, no source-code fix was attempted.**

### Steps 5–7 — Chat-eval + artifact inspection + baseline comparison (NOT RUN)

Running `pytest tests/validation/chat_eval/...` against a stack pinned at migration 021 would exercise a system without the PLAN-0097 W3/W4 fundamentals composite indexes and without the W3 ANALYZE refresh — i.e. it would measure the **ITER-9 baseline plus W1 + W2 only**, not the gated PLAN-0097 deliverable. The result would not be a valid acceptance signal against the table in the task prompt. The run was skipped.

| Metric | Baseline (ITER-9) | Now | Pass? |
|---|---|---|---|
| USEFUL count | 5/9 | not measured | n/a (gate not reached) |
| HARMFUL | 1 | not measured | n/a |
| p99 latency | 207s | not measured | n/a |
| Q8 status | 400 INPUT_REJECTED | not measured | n/a |
| Q4 fabrication | $26.4B leak | not measured | n/a |

### Step 8 — Container-health scan post-deploy

All four PLAN-0097 containers report `healthy`. No errors in `rag-chat`, `knowledge-graph`, or `nlp-pipeline` logs since restart.

`market-data` logs surface a **second, pre-existing defect** unrelated to the migration blocker but worth filing:

```
event=screen_fields_refresh_error
DETAIL: Failing row contains (has_fundamentals, Has Fundamentals, boolean, ...)
CheckViolationError: new row for relation "screen_field_metadata"
                     violates check constraint "ck_screen_field_metadata_field_type"
```

The `ScreenFieldsRefresh` job emits a `has_fundamentals` field with `field_type='boolean'`, but the `ck_screen_field_metadata_field_type` constraint admits only the (presumably) numeric/text/percent enum. The job retries every ~60s and fails every time, so `screen_field_metadata` never gets refreshed and the screener's field catalogue silently drifts.

The only other non-healthy container in the project is `worldview-synthetic-monitor-1` (no healthcheck declared; status `Up 29 hours`), which is independent of this gate.

---

## Proposed PLAN-0098 Followups

1. **MD-W4-FIX-1 (BLOCKER for Phase D rerun).** Remove `"dividend_summary"` from `_TABLES` in `services/market-data/alembic/versions/022_analyze_fundamentals_tables.py`, or, if the intent was to ANALYZE a denormalised summary view, add an upstream migration that actually creates that table. Either fix unblocks `alembic upgrade head` and allows 023 to ride. New BP entry: "BP-58x: ANALYZE migration referenced table never created — Alembic transaction aborts and leaves stats stale on all subsequent tables in the list." Related: BP-581.
2. **MD-W4-FIX-2.** Extend the `ck_screen_field_metadata_field_type` constraint to permit `'boolean'`, or change `has_fundamentals` to emit a typed value the existing enum accepts (e.g. `numeric` 0/1). Today the `has_fundamentals` screener filter — which the W4 batch-resolve work assumes — has no catalogue row, so screener UIs cannot advertise it.
3. **MD-W4-TEST.** Add a unit-level alembic test that runs `upgrade head` against a freshly-seeded `market_data_db` in CI. The current pre-commit hook only validates schema files, not that migrations apply against a real schema; this exact regression would have been caught.
4. **Phase D rerun.** Once #1 lands and migration `023` is `head`, re-execute Steps 5–7 of this gate. The W1 periodicity fix, W2 classifier/grader fix, and W3 ANALYZE+batch-resolve all remain deployed in the rebuilt images, so the rerun should be a single-shot pytest invocation against this same container set.

---

## Overall Verdict

**FAIL.** The acceptance gate is not satisfied. Cause: a single typo-class bug in migration 022 (`dividend_summary`) prevents the PLAN-0097 W4 schema migrations from applying, which transitively blocks any honest measurement against the ITER-9 baseline. A second latent defect (screen-fields check-constraint violation) is documented for PLAN-0098 but does not by itself block the gate.

No source code was modified during this gate run.
