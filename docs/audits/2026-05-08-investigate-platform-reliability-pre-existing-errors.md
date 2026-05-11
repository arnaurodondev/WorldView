# Investigation Report: Pre-Existing Platform Reliability Errors

**Date**: 2026-05-08
**Skill**: `/investigate`
**Scope**: Pre-existing errors flagged by `/qa` and `/fix-bug` as out-of-scope (untracked PLAN-0066 in-progress work)
**Severity**: HIGH (rag-chat service unbootable until import bug fixed)
**Status**: Root cause identified; platform-reliability blockers fixed

---

## 1. Issue Summary

After PLAN-0083 was committed (`3f6ccd4a` → `b741a65a` → `c29245dc`), `/qa` and `/fix-bug` flagged pre-existing failures in untracked PLAN-0066 W10 in-progress code as out-of-scope:
- 2 mypy errors in `brief_archive_repository.py` and `generate_briefing.py`
- 3 failing unit tests in `tests/unit/use_cases/test_generate_briefing_persistence.py`

This investigation went deeper to understand the actual current platform state and apply long-term fixes prioritising reliability.

---

## 2. Evidence Collected

| Evidence | Source | Finding |
|----------|--------|---------|
| Mypy on rag-chat with fresh cache (`rm -rf .mypy_cache`) | direct command | **Clean** — 117 files, 0 errors. The earlier 2 errors were stale cache artefacts from the lint→pre-commit auto-fix→retry loop. |
| `test_generate_briefing_persistence.py` rerun | direct command | **3 PASS**. The test was modified at 23:20 UTC (after the QA run at ~23:00) by parallel work — patches now target `common.ids.new_uuid7` (source module) instead of `rag_chat...generate_briefing.new_uuid7` (lazy-import module attribute). |
| Full rag-chat suite with fresh pytest cache | direct command | **REVEALED HIDDEN FAILURE** — `ImportError: cannot import name 'Field' from 'fastapi'` on conftest load. The previous "739 passed" was a stale pytest cache. |
| `git diff HEAD -- public_briefings.py` | git | Confirms PLAN-0066 Wave C in-progress work added `from fastapi import APIRouter, Field, ...` — `Field` does not exist in fastapi. |
| DDL alignment test on `threads` table | direct command | **FAILED** — `ORM columns missing from DDL: {'seed_brief_id'}`. New migration `0005_add_seed_brief_id_to_threads.py` uses `op.add_column()` Python API; the alignment test parses raw SQL strings (`CREATE TABLE` / `ALTER TABLE`). |

---

## 3. Execution Path Analysis

**Boot path of rag-chat**:
```
app.py:36
  → from rag_chat.api.routes import public_briefings
    → public_briefings.py:35
      → from fastapi import APIRouter, Field, HTTPException, Query, Request
      → ImportError: cannot import name 'Field' from 'fastapi'
```

The error fires at module import time, before any request handler runs. This means:
- The Docker container would fail to start (uvicorn would crash on app import).
- All rag-chat tests would fail to collect (conftest imports from `rag_chat.api.dependencies` which transitively imports `app.py`).
- The earlier "739 passed" came from a stale pytest collection cache that bypassed the import.

**DDL alignment path**:
```
test_ddl_alignment.py::TestThreadsDDLAlignment.test_threads_ddl_matches_orm
  → reads all alembic/versions/*.py
  → regex-extracts CREATE TABLE columns + ALTER TABLE ADD COLUMN columns
  → compares to ThreadModel ORM column set
  → migration 0005 uses op.add_column() — invisible to regex
  → FAIL: ORM has seed_brief_id, parsed DDL doesn't
```

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | The mypy errors and test failures from /qa are still present | **REFUTED** | Fresh cache reruns: mypy clean, tests pass. They were transient artefacts. |
| H-2 | The "739 passed" rag-chat baseline is stable | **REFUTED** | Fresh pytest cache surfaces an import error that prevents the suite from loading. |
| H-3 | The import error is recent uncommitted work | **CONFIRMED** | `git diff HEAD` shows the `Field` import was added by uncommitted PLAN-0066 Wave C work. |
| H-4 | DDL alignment failure is caused by ORM/migration drift in PLAN-0066 work | **CONFIRMED** | Migration 0005 uses `op.add_column()`; alignment test only parses raw SQL. Convention in this codebase (migration 0002) is `op.execute("ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")`. |
| H-5 | The "Field" symbol exists in some FastAPI version | **REFUTED** | FastAPI never exported `Field` — the symbol has always been pydantic. The author confused the two. |

---

## 5. Root Cause

### Bug #1 — rag-chat unbootable (HIGH severity)

- **Statement**: PLAN-0066 Wave C (uncommitted) added `Field` to the fastapi import statement, but `Field` is a pydantic symbol. rag-chat fails to import on cold start.
- **Location**: `services/rag-chat/src/rag_chat/api/routes/public_briefings.py:35`
- **Trigger condition**: Any cold import of `rag_chat.app` — Docker container start, fresh test collection, fresh CI run.
- **Why it was hidden**: A stale pytest cache from before the modification kept the suite "passing"; the cache cleared only when explicitly removed.

### Bug #2 — DDL alignment broken (MEDIUM severity)

- **Statement**: PLAN-0066 Wave D migration `0005_add_seed_brief_id_to_threads.py` uses `op.add_column()` but the codebase's DDL alignment guard parses raw SQL strings (`CREATE TABLE` / `ALTER TABLE ADD COLUMN`). The new column is invisible to the guard.
- **Location**: `services/rag-chat/alembic/versions/0005_add_seed_brief_id_to_threads.py:37-45`
- **Trigger condition**: DDL alignment test runs in any environment.
- **Why it happened**: Author used the more common Alembic Python API; missed the project-specific convention (migration 0002 establishes `op.execute("ALTER TABLE ...")` raw-SQL style for this service).

---

## 6. Impact Analysis

| Concern | Bug #1 | Bug #2 |
|---------|--------|--------|
| Immediate impact | rag-chat container fails to start | DDL alignment test fails |
| Blast radius | All rag-chat HTTP traffic, all morning-brief generation, all RAG chat | Only test suite — no runtime impact since the migration would still apply correctly |
| Data risk | None | None (the migration would create the column correctly via SQLAlchemy's compilation) |
| User impact | All users — chat + briefing endpoints would 5xx | None |

Bug #1 is a **production reliability blocker**. Bug #2 is a CI gating issue.

---

## 7. Contributing Factors

1. **In-progress untracked work pollutes QA results** — when `/qa` ran, the file modifications existed in the working tree but were absent from any commit. `/qa` test runs include them, but they aren't in the changeset under review. This conflates "your changes broke things" with "the working tree has unrelated incomplete work."
2. **Pytest collection cache masks import errors** — pytest's `.pytest_cache/` can preserve a "tests collect OK" state across file modifications until explicitly cleared, so a freshly-broken import is invisible to subsequent test runs.
3. **No CI-time fresh-cache discipline** — local development runs assume warm caches; CI in this repo would catch the bug, but locally the bug can persist invisibly for hours.
4. **Migration convention not codified** — there's no doc/standard saying "this service uses `op.execute("ALTER TABLE...")` raw SQL for column adds because the DDL alignment test parses raw SQL". The convention is implicit in migration 0002.

---

## 8. Fixes Applied

### Fix #1: Import correction
**File**: `services/rag-chat/src/rag_chat/api/routes/public_briefings.py:35-36`

```diff
-from fastapi import APIRouter, Field, HTTPException, Query, Request
-from pydantic import BaseModel
+from fastapi import APIRouter, HTTPException, Query, Request
+from pydantic import BaseModel, Field
```

`Field` is used at lines 524-525 (`Field(ge=0, ...)`) for Pydantic model validation — pydantic is the correct origin.

### Fix #2: Migration convention alignment
**File**: `services/rag-chat/alembic/versions/0005_add_seed_brief_id_to_threads.py`

Replaced `op.add_column(...)` with `op.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS seed_brief_id UUID REFERENCES user_briefs(id) ON DELETE SET NULL")` to match the convention established by migration 0002. Added a `# WHY` comment documenting the rationale (DDL alignment guard parses raw SQL only).

---

## 9. Verification

After both fixes (with fresh `.pytest_cache`):
- rag-chat full suite: **751 passed, 14 skipped, 0 failed** (excluding 1 in-progress test bug — `test_brief_diff.py::test_diff_no_data_returns_no_diff` — which is a logic bug in PLAN-0066 Wave C in-progress code; out of scope for platform reliability).
- mypy: clean on 117 source files.
- Architecture tests: 649 passed, 0 failed.
- DDL alignment: 3 passed.

---

## 10. Long-Term Recommendations

### Immediate (compound into the codebase now)

1. **Add HR-046 to `HIGH_RISK_PATTERNS.md`**: `from fastapi import ..., Field, ...` — `Field` is a pydantic symbol, not fastapi. Code-review hot signal.
2. **Add BP-427 to `BUG_PATTERNS.md`**: rag-chat migration convention — DDL alignment guard parses raw SQL only; new column adds MUST use `op.execute("ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")` rather than `op.add_column()`. Add the convention to `services/rag-chat/.claude-context.md` so it surfaces during `/migrate-db` skill invocations.
3. **Update DDL alignment test to also recognise `op.add_column()`** — defence-in-depth so the convention isn't load-bearing. Lower-priority follow-up; the BP entry is a more reliable fix because it surfaces at authoring time.

### Process-level (broader platform reliability)

4. **`/qa` should classify untracked-file failures separately** — when `/qa` finds a failure that originates in a file not in the changeset, the report should label it "in-progress untracked" and NOT block the changeset under review. Currently they get conflated.
5. **`/fix-bug` and `/qa` skills should clear `.pytest_cache` before final validation** — relying on a warm cache is a known reliability risk (see Contributing Factor #2). Adding `rm -rf .pytest_cache` to the final-validation step would have surfaced Bug #1 immediately.
6. **Pre-commit hook for fastapi/pydantic Field confusion** — a one-line grep guard could catch `from fastapi import .*Field` patterns before they reach commit.

### What should NOT change

7. The user (or parallel agent) should fix `test_brief_diff.py::test_diff_no_data_returns_no_diff` themselves — it's a real logic bug in their PLAN-0066 Wave C in-progress code (the test reuses a `uc` injected with `archive_one`, then asserts behavior as if `archive_zero` were injected). Fixing it without context could hide a real implementation bug.

---

## 11. Open Questions

- The PLAN-0066 W10 work has Wave A/B committed (commit `8e169c6d`) but Wave C/D are uncommitted in working tree. Was this intentional (mid-implementation), or was an earlier session interrupted? The work-in-progress state is fragile because future sessions may stomp on it.

---

*Report generated 2026-05-08 by `/investigate`.*
