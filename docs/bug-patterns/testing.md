# Bug Patterns — Testing

> **Category**: testing
> **Description**: pytest fixtures, AsyncMock, E2E test infrastructure, Vitest, pre-commit hooks, test isolation, CI patterns
> **Count**: 23 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-004 — `fixture 'settings' not found` causes `ERROR at setup` instead of SKIP

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion` (any service with bare `settings` parameter in integration tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

pytest shows `ERROR at setup` (not `FAILED`, not `SKIPPED`) for integration tests:

```
ERROR at setup of test_integration_task_add_and_claim
  fixture 'settings' not found
  available fixtures: app, client, ...
```

Even tests whose first line is `pytest.skip("...")` show as `ERROR` rather than
`SKIPPED` — because fixture resolution happens **before** the test body runs.

### Root cause

Two independent problems, both must be fixed:

**Problem A**: The `settings` pytest fixture is never defined. A helper function
`_make_settings()` (plain function, no decorator) exists in the test file but is
invisible to pytest's fixture system.

**Problem B**: Tests that should always skip use `pytest.skip()` **inside the body**
with a required fixture parameter. Since pytest must resolve all fixture parameters
before entering the body, it errors before it can execute the skip.

```python
# WRONG — fixture resolution fails before skip() can execute
@pytest.mark.integration
async def test_integration_foo(settings):          # 'settings' fixture required
    pytest.skip("Requires live Kafka")             # never reached
    ...

# CORRECT — skip evaluated at collection time, no fixture needed
@pytest.mark.integration
@pytest.mark.skip(reason="Requires live Kafka")    # evaluated before fixture resolution
async def test_integration_foo() -> None:
    ...
```

### Correct implementation pattern

Every service that has integration tests requiring a `Settings()` instance must
have a `conftest.py` in the relevant test subfolder (e.g. `tests/infrastructure/`)
defining a `settings` fixture:

```python
# tests/infrastructure/conftest.py
from __future__ import annotations
import pytest
from my_service.config import Settings

@pytest.fixture(scope="session")
def settings() -> Settings:
    """Real Settings() from MYSERVICE_* env vars.
    Populated by `make test-integration` via:
        set -a && . ./configs/dev.local.env && set +a
    """
    return Settings()
```

For tests that always skip (infrastructure not yet available), use the decorator
form rather than calling `pytest.skip()` in the body:

```python
# CORRECT
@pytest.mark.skip(reason="Requires live Kafka + Schema Registry")
async def test_integration_end_to_end() -> None:
    ...

# Also CORRECT — conditional skip based on env var
import os
_NEEDS_KAFKA = pytest.mark.skipif(
    not os.getenv("MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS"),
    reason="Requires live Kafka (set MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS)",
)

@_NEEDS_KAFKA
async def test_kafka_consumer_roundtrip() -> None:
    ...
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/tests/infrastructure/conftest.py` | Created; defines `settings` fixture |
| `services/market-ingestion/tests/infrastructure/test_dispatcher.py` | Replaced `pytest.skip()` in body + `settings` param with `@pytest.mark.skip` decorator; removed unused parameter |

---

---

## BP-013 — E2E tests appear infinite due to unstable async assertions

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-04.md`

### Symptom

E2E run appears to hang for minutes. Tests are not truly infinite but use long
deadlines while waiting for conditions that are fragile (symbol-specific queue
state, dispatcher timing, scheduler noise).

### Root cause

- Assertions depended on one task/symbol becoming terminal within an arbitrary
    window while scheduler continuously enqueued unrelated tasks.
- Poll loops had broad deadlines and ambiguous success criteria.

### Correct implementation pattern

1. Use bounded polling windows with explicit deadlines.
2. Assert stable, service-level progress conditions (e.g., any task processed),
     not brittle symbol-specific timing.
3. Keep scheduler deterministic in test profiles (short tick; bounded budget).

```yaml
environment:
    MARKET_INGESTION_SCHEDULER_TICK_INTERVAL_SECONDS: "2.0"
    MARKET_INGESTION_SCHEDULER_MAX_TASKS_PER_TICK: "0"
```

### Test to add (prevents regression)

- Add one dedicated async-progress smoke test with a strict upper bound
    (`<= 20-30s`) and fail-fast assertion message.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added deterministic scheduler test env vars |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | Reworked full-flow test to bounded, stable progress assertion |

---

---

## BP-014 — Import guard allowlist `fnmatch` pattern does not match direct children

**Date discovered**: 2026-03-26
**Service affected**: `intelligence-migrations` (found during CI Import Guards job)
**Prompts updated**: `.claude/skills/implement/SKILL.md` Step 4 — added import guards to validation gate

### Symptom

CI Import Guards job fails with 3 net-new violations that should be covered by the allowlist:
```
[IG-OBS-001] services/intelligence-migrations/scripts/populate_embeddings.py:30
    Forbidden call: `logging.getLogger()` (rule IG-OBS-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:129
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
[IG-COMMON-001] services/intelligence-migrations/tests/test_migration.py:130
    Forbidden call: `uuid.uuid4()` (rule IG-COMMON-001)
```

### Root cause

Two independent issues:

1. **`fnmatch` does not support recursive `**` like `pathlib.Path.glob()`**. The allowlist used patterns like `services/*/tests/**/*.py`, but Python's `fnmatch.fnmatch()` treats `*` as "match any characters" (including `/`). The `**/` in the pattern requires at least one path separator after `tests/`, so files directly in `tests/` (like `tests/test_migration.py`) are NOT matched — only files in subdirectories (like `tests/unit/test_foo.py`) match.

2. **Service-level scripts not covered**. The allowlist had `scripts/**/*.py` for repo-root scripts, but `services/intelligence-migrations/scripts/populate_embeddings.py` is under `services/`, not the root `scripts/` directory.

3. **No pre-commit import guard check**. The pre-commit hook (`pre-commit-validate.sh`) ran ruff + mypy + unit tests but did NOT run import guards, so violations passed local validation and only failed in CI.

### Correct implementation pattern

When writing `fnmatch`-style allowlist patterns, always include **both** direct-child and recursive patterns:

```yaml
# Direct children — fnmatch does NOT support ** recursion
- rule_id: IG-COMMON-001
  path: "services/*/tests/*.py"
  reason: Test code may use uuid4() directly.

# Nested children — still needed for tests/unit/*.py, tests/integration/*.py
- rule_id: IG-COMMON-001
  path: "services/*/tests/**/*.py"
  reason: Test code may use uuid4() directly.
```

When adding new service directories (like `services/*/scripts/`), add corresponding allowlist entries if the files don't follow service-code conventions.

### Test to add (prevents regression)

Import guards now run as Step 3/4 in the pre-commit hook (`scripts/hooks/pre-commit-validate.sh`), so violations are caught before commit — not just in CI.

### Files changed in fix

| File | Change |
|------|--------|
| `scripts/import_guards/allowlist.yaml` | Added `services/*/tests/*.py` patterns alongside existing `**/*.py` patterns; added `services/*/scripts/*.py` entries |
| `services/intelligence-migrations/scripts/populate_embeddings.py` | Replaced `logging.getLogger()` with `structlog.get_logger()` and structlog-style kwargs |
| `scripts/hooks/pre-commit-validate.sh` | Added import guards as Step 3/4 (scoped to changed services) |
| `.claude/skills/implement/SKILL.md` | Added import guards to Step 4 validation gate |

---

---

## BP-023 — pre-commit ruff-format stash conflict loop

**Date discovered**: 2026-03-27
**Service affected**: `nlp-pipeline` (pre-commit hook during Wave C-2 commit)
**Prompts updated**: N/A

### Symptom

`git commit` enters an infinite failure loop:
```
ruff-format...Failed — 1 file reformatted
Stashed changes conflicted with hook auto-fixes... Rolling back fixes
```

The same file is reformatted every attempt; the commit never succeeds.

### Root cause

Two conditions must both be true to trigger this:
1. A staged file has a **different version in the working tree** (`AM` or `MM` git status)
2. The pre-commit hook's ruff version formats the file differently than the local venv's ruff

The hook stashes the working tree, formats the staged content, then tries to restore the stash. The stash's working tree version conflicts with the formatted index version, causing rollback.

### Correct implementation pattern

Before committing, ensure ALL staged Python files have `A ` or `M ` status (no working tree delta):

```bash
# Find partially-staged Python files
git diff --name-only | grep "\.py$"

# For each file listed, check if it's also staged
git status --short <file>  # AM or MM = problem

# Fix: restore working tree from index (use hook's formatted version)
git checkout -- <file>

# OR: format file with system ruff (pre-commit hook version) and re-stage
uvx ruff format <file>
git add <file>
```

**Always use `uvx ruff format` (system/pre-commit ruff), not the service venv's ruff**, since the venv may be pinned to an older version.

### Test to add (prevents regression)

N/A — this is a workflow issue, not a code bug. Add to commit checklist: verify no `AM`/`MM` Python files before committing.

### Files changed in fix

| File | Change |
|------|--------|
| `services/nlp-pipeline/src/nlp_pipeline/application/blocks/routing.py` | Reformatted assert statement to match pre-commit hook's ruff version |

---

---

## BP-028 — AsyncMock used for sync method generates unawaited coroutine warnings

**Date discovered**: 2026-03-27
**Service affected**: `market-data` (ohlcv, quotes, fundamentals consumers)

### Symptom

Tests pass but emit `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` for calls like `uow.collect_event(...)`. The call is sync in production but the test's `AsyncMock()` wraps every attribute as an async mock.

### Root cause

`mock_uow = AsyncMock()` makes ALL attributes `AsyncMock` instances by default. When production code calls a **sync** method (`collect_event`) without `await`, the `AsyncMock` runs but the resulting coroutine is never consumed — generating the warning.

### Fix

Explicitly override sync methods after creating the `AsyncMock`:
```python
mock_uow = AsyncMock()
mock_uow.collect_event = MagicMock()  # sync — must not be AsyncMock
```

### Prevention

After `mock_uow = AsyncMock()`, check the real UoW for sync methods and override them with `MagicMock()`.

---

---

## BP-041 — ruff TCH003→TC003 noqa rename breaks pre-commit hook

**Affects**: All SQLAlchemy ORM models using `Mapped[datetime]` (or other stdlib types only used in annotations)

### Symptom

Pre-commit hook fails with:

```
ruff.....................................................................Failed
services/.../models.py:9:22: TCH003 Move standard library import `datetime.datetime` into a type-checking block
Found 2 errors (1 fixed, 1 remaining).
```

After the hook auto-fixes the import (moves it to `TYPE_CHECKING`), SQLAlchemy raises at runtime:

```
sqlalchemy.exc.ArgumentError: Could not resolve all types within mapped annotation: "Mapped[datetime]"
```

### Root cause

- The pre-commit hook pins ruff at `v0.4.0`, which uses rule code `TCH003`.
- Newer local ruff (≥v0.6.0) renames it to `TC003` and auto-converts `# noqa: TCH003` → `# noqa: TC003` in staged files.
- The hook's ruff v0.4.0 doesn't recognize `# noqa: TC003` as suppressing `TCH003` → auto-fixes the import → breaks SQLAlchemy → circular failure.

### Fix

Add the models path glob to `ruff.toml`'s `[lint.per-file-ignores]` to suppress the rule globally (no noqa comment needed):

```toml
# SQLAlchemy calls get_type_hints() at runtime — datetime must be importable
"services/*/src/*/infrastructure/db/models/*.py" = ["TCH003"]
"services/*/src/*/infrastructure/*/models.py" = ["TCH003"]   # non-standard subdirs (e.g. nlp_db/)
```

Do NOT use `# noqa: TCH003` or `# noqa: TC003` — they are unstable across ruff versions. The `per-file-ignores` approach is version-agnostic.

---

---

## BP-067

**Category**: pytest configuration — `--strict-markers` + missing marker registration

**Date discovered**: 2026-03-30
**Service affected**: `alert` (discovered during QA-S4S5S6S7S10-001)

### Symptom

```
ERRORS
ERROR services/alert/tests/e2e/test_api_workflows.py - Failed: 'e2e' not found in `markers` configuration option
```

All tests in the service fail to collect, not just the e2e tests.

### Root cause

The service's `pyproject.toml` uses `addopts = "--strict-markers"` which turns any unregistered marker into a hard error at collection time. When new e2e test files are added with `pytestmark = [pytest.mark.e2e, ...]` but `e2e` is not listed in `[tool.pytest.ini_options] markers`, every test in the service's `testpaths` fails to collect.

### Fix

Add the `e2e` marker to the markers list in `pyproject.toml` before committing new e2e test files:

```toml
[tool.pytest.ini_options]
markers = [
    "unit: ...",
    "integration: ...",
    "contract: ...",
    "e2e: end-to-end tests against a real database",  # ← ADD THIS
]
```

### Affected areas

Any service using `--strict-markers` (currently: alert, content-ingestion) when e2e tests are first added. Check `addopts` in `pyproject.toml` before adding new marker types to tests.

---

---

## BP-068

**Category**: Docker Compose infrastructure — missing pgvector extension in postgres image

**Date discovered**: 2026-03-30
**Service affected**: S6 (nlp-pipeline), S7 (knowledge-graph) test infrastructure

### Symptom

```
ERROR:  could not open extension control file
"/usr/share/postgresql/16/extension/vector.control": No such file or directory
```

When `init-test-databases.sh` runs `CREATE EXTENSION IF NOT EXISTS vector` in the docker-entrypoint-initdb.d script, the `postgres:16-alpine` image does not include pgvector. The database creation succeeds but pgvector is missing.

### Root cause

`postgres:16-alpine` is a minimal PostgreSQL image with no third-party extensions. The `nlp_db` and `intelligence_db` databases require pgvector for `VECTOR(1024)` column types and HNSW indexes used by S6 and S7.

### Fix

Replace `postgres:16-alpine` with `pgvector/pgvector:pg16` in `docker-compose.test.yml`. This is an official image that is functionally identical to `postgres:16` but with pgvector pre-installed:

```yaml
# WRONG — no pgvector support
postgres:
  image: postgres:16-alpine

# CORRECT — pgvector pre-installed
postgres:
  image: pgvector/pgvector:pg16
```

The init script can then call `CREATE EXTENSION IF NOT EXISTS vector` without error.

### Affected areas

All test profiles using the shared `postgres` service in `docker-compose.test.yml` when S6 or S7 databases are being initialized. The `pgvector/pgvector:pg16` image is a drop-in replacement and works for all other services too.

---

## BP-078 — Cross-service E2E `ImportError` when service package not installed

**Date discovered**: 2026-03-31
**Service affected**: `tests/e2e/test_security_isolation.py`, `tests/e2e/test_market_data_pipeline.py`

### Symptom

Cross-service E2E tests collect and fail with:

```
ImportError: No module named 'portfolio'
```

or

```
ImportError: No module named 'market_ingestion'
```

even though the test is decorated with a skip marker like:

```python
@pytest.mark.skipif(not _S1_UP, reason="S1 not reachable")
async def test_cross_tenant_holdings_isolation(...):
    from portfolio.infrastructure.db.models.instrument import InstrumentModel
    ...
```

The skip marker fires correctly when the service is unreachable, but the import still executes because Python processes the function body before `pytest.skip()` can run within the test function.

### Root Cause

`pytest.mark.skipif` evaluated at collection time prevents the test from being *scheduled*, but when `skipif` evaluates to `False` (service IS reachable) the test body runs, and a service that is reachable over HTTP may still not have its Python package installed in the test runner environment. The import fails with `ImportError` before any assertion.

Additionally, even when `skipif` is `True`, pytest collects the test function and evaluates skip markers; however, imports inside the function body can still surface during collection in some configurations.

### Fix

Wrap all service-package imports inside the test body with a `try/except ImportError` guard:

```python
async def test_cross_tenant_holdings_isolation(...):
    try:
        from portfolio.infrastructure.db.models.instrument import InstrumentModel
    except ImportError:
        pytest.skip("portfolio package not installed in cross-service test environment")
    ...
```

### Prevention

- All cross-service tests that import from another service's package MUST use `try/except ImportError: pytest.skip(...)` guards
- Never use bare top-level service-package imports in `tests/e2e/` files — only inside test functions with the guard
- Add this pattern to the review checklist for any new cross-service E2E test file

---

---

## BP-080 — pytest-asyncio 0.24 loop scope mismatch: `session` loop + function-scoped async fixtures

**Affected areas**: Any service using pytest-asyncio 0.24 with async fixtures

**Symptom**

Test teardown raises:

```
RuntimeError: Event loop is closed
```

after all tests pass, causing the overall test run to fail with a non-zero exit code.

**Root Cause**

`asyncio_default_fixture_loop_scope = "session"` with pytest-asyncio 0.24 creates a single event loop shared across the test session. When async generator fixtures have function scope (the default), their teardown (`yield`-after cleanup) executes after the test function completes but may run after the session loop has been torn down, causing `RuntimeError: Event loop is closed`.

This is especially common after changing a fixture from `session`-scoped to `function`-scoped (e.g., to fix a different isolation bug) without updating the pyproject.toml loop scope settings.

**Fix**

Set both loop scope settings to `"function"` in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_default_fixture_loop_scope = "function"
asyncio_default_test_loop_scope = "function"
```

Each test function then gets its own event loop, and fixture teardown always runs within an active loop.

**Prevention**

- `asyncio_default_fixture_loop_scope` and `asyncio_default_test_loop_scope` must always match the narrowest scope of any async fixture in the test suite
- Prefer `"function"` scope for both settings unless there is a strong measured performance reason to use `"session"`
- When adding or changing fixture scopes, verify both pyproject.toml settings remain consistent

---

---

## BP-084 — `.gitignore` `src/` rule blocks new service source files from being tracked

**Category**: git — untracked files silently ignored

**Symptom**: `git add services/<service>/src/<new_file>.py` appears to succeed but `git diff --cached --name-only` returns empty. `git status` shows the file as untracked. New `*_main.py` entry points or other new source files under `services/*/src/` cannot be staged normally.

**Root cause**: `.gitignore` contains a bare `src/` rule (line 66 in this repo — added as a "Local attached source folder" marker). This rule matches **any directory named `src/` anywhere in the repo tree**, which includes every `services/*/src/` directory. New (untracked) files in those directories are silently ignored by git.

**Fix**: Use `git add -f` (force) to stage ignored files:

```bash
git add -f services/<service>/src/<new_file>.py
```

Or, if adding many new files in a service:

```bash
git add -f services/<service>/src/
```

**Prevention**

- When adding new source files under any `services/*/src/` path and `git status` does not show them as staged, check with `git check-ignore -v <path>` before assuming staging failed.
- The `src/` entry in `.gitignore` is intentional (for local IDE source-attachment workflows) — do not remove it. Always use `git add -f` for new files in service `src/` directories.

---

---

## BP-089 — Tautology assertions in entry-point tests: `assert X == f"{X}"`

**Services affected**: knowledge-graph, (any service with standalone consumer entry point tests)
**Detected**: PLAN-0013 QA pass (2026-04-01)

### Symptom

A test that is supposed to verify a constructor argument (e.g., `group_id`) passes
unconditionally because the assertion compares a variable to the identical expression
used to define it:

```python
expected_group = f"{settings.kafka_consumer_group}-fundamentals"
assert expected_group == f"{settings.kafka_consumer_group}-fundamentals"  # always True
```

The test passes even if the production code never constructs a `ConsumerConfig` at all.

### Root Cause

When the mock class is captured (`as mock_consumer_cls`) but the assertion is written
with the literal formula instead of inspecting `mock_consumer_cls.call_args`, the test
becomes a no-op.

### Fix

Capture the mock class with `as mock_cls` and assert on `call_args`:

```python
) as mock_cls,
...

call_kwargs = mock_cls.call_args
assert call_kwargs is not None
config_arg = call_kwargs.kwargs.get("config") or (
    call_kwargs.args[0] if call_kwargs.args else None
)
assert config_arg is not None
assert config_arg.group_id == f"{settings.kafka_consumer_group}-fundamentals"
```

### Prevention

In entrypoint tests, every constructor-argument assertion must reference
`mock_cls.call_args`, not restate the expected value formula.
Review checklist item: "Does the assertion inspect production behaviour, or does
it merely compare two identical expressions?"

---

---

## BP-111 — `aiosmtplib.SMTPConnectError` Constructor Changed in v3

**Category**: Dependency API change · **Severity**: Test failure (TypeError)
**Affected areas**: Any test constructing `aiosmtplib.SMTPException` subclasses directly

**Symptom**: `TypeError: SMTPException.__init__() takes 2 positional arguments but 3 were given` when constructing `aiosmtplib.SMTPConnectError(code, message)` in tests.

**Root cause**: `aiosmtplib` v3 changed the `SMTPException` base class constructor from `(code: int, message: str)` to `(message: str)` only. The error code is no longer a positional argument.

**Fix**: Use the single-argument form:
```python
# v2 (wrong in v3)
aiosmtplib.SMTPConnectError(421, "Service unavailable")

# v3 (correct)
aiosmtplib.SMTPConnectError("Service unavailable")
```

**Prevention**: Pin `aiosmtplib>=3.0,<4` in `pyproject.toml` and use single-argument form consistently in tests.

**First seen**: PLAN-0016 Wave C-2 (2026-04-07), alert S10.

---

---

## BP-114 — EODHD Demo Key Rate-Limits Silent `[]` for EOD OHLCV Under Concurrent Load

**Date discovered**: 2026-04-07
**Category**: External API / demo key behavior · **Severity**: MEDIUM (test data gap)
**Affected areas**: S2 market-ingestion worker, E2E tests asserting bar counts

**Symptom**: EODHD `/api/eod/AAPL.US?api_token=demo&period=d` returns HTTP 200 with body `[]` (empty JSON array, 2 bytes). Task succeeds, canonical NDJSON is 0 bytes. Tests that assert `bar_count > 0` skip.

**Root cause**: The EODHD demo API key has a low concurrent request rate limit. When the worker processes 30 tasks simultaneously (concurrency=4), the first 4-6 requests succeed with real data; subsequent requests for the same session receive empty `[]`. The EOD endpoint (daily/weekly/monthly) is more affected than real-time quotes, which use a separate endpoint.

**Evidence**: Worker logs show `row_count=1` for the first few quotes tasks and `row_count=0` for all subsequent EOD OHLCV tasks. Bronze objects contain `b'[]'`.

**Distinguishing from BP-112/BP-113**: This is NOT a bug in the codebase — the task correctly succeeds with 0 rows. It is a demo-key operational limitation.

**Mitigation options**:
1. Use a real (paid) EODHD API key for E2E tests — provides full data
2. Set `WORKER_CONCURRENCY=1` in test docker.env to serialize requests
3. Add a per-provider rate limiter in the worker (token bucket, 1 req/s for demo key)
4. In test assertions, skip on `row_count=0` rather than failing (already done in E2E tests)

**Prevention**: Document that E2E tests requiring EODHD OHLCV bar data need a real API key. The demo key is only reliable for quotes and fundamentals under low concurrency.

**First seen**: E2E investigation (2026-04-07), S2 market-ingestion full pipeline test.

---

---

## BP-127 — pre-commit ruff-format Version Mismatch Causes Phantom Reformat Loop

**Symptom**: `git commit` fails with `ruff-format: 1 file reformatted, N files left unchanged` even after running `uvx ruff format` on all staged files. The hook passes when run via `pre-commit run ruff-format` standalone but fails on commit. Re-staging after formatting doesn't help if the wrong ruff version is used.

**Root cause**: The pre-commit config pins `ruff-pre-commit` to a specific version (e.g., `v0.4.0`) in `.pre-commit-config.yaml`. Running `uvx ruff format` uses a newer version of ruff from the default uvx cache. When the two versions produce different formatting for the same file, `uvx ruff format` marks the file as clean but the hook's pinned version reformats it again on commit.

**Fix**:
1. Identify the pinned ruff binary: `find ~/.cache/pre-commit -name "ruff" -path "*ruff-pre-commit*"`.
2. Use the pinned binary to format before staging: `~/.cache/pre-commit/repo*/py_env-python3.14/bin/ruff format <file>`.
3. Verify staged content is clean: `git show ":$file" | <pinned-ruff> format --stdin-filename "$file" -` should produce no diff.

**Prevention**: Always format using the same version as the pre-commit hook. Either pin `uvx ruff` to match (`uvx ruff@0.4.0 format`), or add a Makefile target that uses the pre-commit-managed binary.

**Affected areas**: Any Python file in any service/lib when the pre-commit ruff version differs from the local/uvx ruff version.

**First seen**: nlp-pipeline Issues 1–3 commit, 2026-04-08.

---

## BP-132 — Hardcoded StrEnum Count Test Breaks When Shared Lib Enum Is Extended

**Symptom**: A downstream service unit test fails with `AssertionError` after adding a new member to `ContentSourceType` (or any other shared-lib StrEnum). The test in the downstream service hardcodes the expected set of values as an exact frozenset.

**Root cause**: Tests like `assert {v.value for v in SourceType} == {"eodhd", "sec_edgar", ...}` are membership-exact: they fail if any new value is added. When `libs/contracts.ContentSourceType` is extended with a new member (e.g., `POLYMARKET`), the test in `content-store`, `nlp-pipeline`, or any service that re-exports `ContentSourceType` as `SourceType` will fail.

**Example (PLAN-0019)**: `services/content-store/tests/unit/domain/test_enums.py::test_all_five_sources` hardcoded 5 values. Adding `POLYMARKET` in Wave A-1 caused an extra `"polymarket"` value that was not in the expected set.

**Fix**: Update the expected set to include the new value, and rename the test to avoid encoding the count in the test name (e.g., `test_all_five_sources` → `test_all_sources`).

**Prevention**: When adding a member to any StrEnum in `libs/contracts`, `libs/messaging`, or any shared library, search for `{v.value for v in SourceType}` / `== expected` patterns in ALL service test directories and update every hardcoded expected set in one atomic PR. Prefer additive assertions (`assert "polymarket" in {v.value for v in SourceType}`) over equality assertions for extensible enums.

**Affected areas**: `services/content-store/tests/unit/domain/test_enums.py`, any service that aliases or re-exports `ContentSourceType`.

**First seen**: PLAN-0019 QA pass, 2026-04-09.

---

## BP-134 — Live/Network Tests Missing `pytest.mark.live` Causes Fixture Scope Mismatch

**Symptom**: Running `pytest tests/ -m "not integration and not e2e"` still collects tests from `tests/live/` that fail with `ScopeMismatch: You tried to access the function scoped fixture _function_scoped_runner with a module scoped request object`. 55 errors in market-ingestion, 11 in market-data.

**Root cause**: Tests in `tests/live/` use `pytestmark = [pytest.mark.skipif(...)]` for network gating but are not decorated with `@pytest.mark.live`. Without a `live` marker, the `-m "not live"` filter does not exclude them. The fixture uses `scope="module"` on an asyncio fixture that pytest-asyncio resolves at function scope, causing a scope mismatch error.

**Fix**: Add `pytest.mark.live` to `pytestmark` in all `tests/live/*.py` files:
```python
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not _is_network_available(), reason="No network connectivity"),
]
```
Then register `live` as a custom marker in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["live: requires live network access to external APIs"]
```

**Prevention**: Include `@pytest.mark.live` as a required marker in the `/test-feature` skill and REVIEW_CHECKLIST when writing tests in `tests/live/`.

**Affected**: `services/market-ingestion/tests/live/`, `services/market-data/tests/live/`.

**First seen**: Pre-Hetzner deployment QA pass, 2026-04-09.

---

## BP-142 — E2E Test Assumes Endpoint Convention Without Verifying Actual Path

**Category**: Test Correctness
**Severity**: CRITICAL (silent test failure in deployment validation)

**Pattern**: An E2E or smoke test hardcodes an endpoint path based on common convention (e.g., `/health`, `/status`, `/ping`) without checking what paths the service actually exposes. The test fails with HTTP 404 whenever the service uses a different convention (e.g., `/healthz`, `/api/v1/health`), producing false negatives that look identical to a real outage.

**Symptom**: Deployment readiness tests report service failure with `HTTP 404` even though the service is perfectly healthy and running on the expected port.

**Root cause**: The worldview scaffold generates `/healthz` (Kubernetes liveness probe convention) but the test was written using the generic HTTP health endpoint convention `/health`. No cross-reference with OpenAPI or `.claude-context.md` was done when writing the test.

**Fix**: Always derive test endpoint paths from the canonical source:
1. Check `services/<service>/.claude-context.md` for documented endpoints.
2. Or verify against the service's OpenAPI spec: `GET /openapi.json → .paths | keys[]`.
3. For worldview specifically: all services expose `/healthz` (not `/health`) and `/metrics` for Prometheus.

**Prevention**:
- When writing E2E/smoke tests against services, validate the endpoint path against the service's OpenAPI spec or `.claude-context.md` first.
- Add a comment in the test citing where the path convention is documented: `# /healthz per PRD-0024 §6.4 and scaffold convention`.

**First seen**: `tests/e2e/test_deployment_readiness.py`, commit `964f06a`, found and fixed 2026-04-11.

---

## BP-160 — jsdom localStorage.clear() Not a Function in Vitest + Node.js

**Category**: Frontend / Testing
**Affected areas**: Any Vitest test that calls `localStorage.clear()` in `beforeEach`
**First seen**: PLAN-0028 Wave F-2 (2026-04-18)

### Symptom

```
TypeError: localStorage.clear is not a function
```

Also preceded by:
```
Warning: '--localstorage-file' was provided without a valid path
```

### Root Cause

Node.js 22+ has experimental `localStorage` support via `--experimental-webstorage`. When Vitest
runs under Node.js ≥22, Node intercepts `--localstorage-file` CLI arguments and installs its own
`localStorage` global — a non-standard object that does not implement the full `Storage` interface
(notably missing `.clear()`). This replaces jsdom's proper `Storage` object before tests run.

### Fix

Use `vi.stubGlobal` to install a fully-mocked localStorage in `beforeEach`:

```ts
const localStorageMock = {
  getItem: vi.fn<(key: string) => string | null>(() => null),
  setItem: vi.fn<(key: string, value: string) => void>(),
  removeItem: vi.fn<(key: string) => void>(),
  clear: vi.fn<() => void>(),
  length: 0 as number,
  key: vi.fn<(index: number) => string | null>(() => null),
};

beforeEach(() => {
  vi.stubGlobal("localStorage", localStorageMock as unknown as Storage);
  localStorageMock.getItem.mockReturnValue(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});
```

### Why vi.fn() generic syntax matters

Vitest v1+ changed the `vi.fn()` generic signature from `vi.fn<[Args], Return>()` (v0 style)
to `vi.fn<FunctionSignature>()`. Using the old 2-arg form causes TS2558. Use single-arg form.

### Prevention

Never call `localStorage.clear()` directly in test setup. Always stub localStorage explicitly.
Do NOT type the mock object as `Storage` — this strips Vitest's `Mock<...>` methods like
`mockReturnValue`. Keep the inferred type and cast with `as unknown as Storage` only where needed.

---

---

## BP-172 — Integration Tests Using X-Tenant-ID/X-Owner-ID Headers After Auth Middleware Migration

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 |
| **Severity** | HIGH (silent test false-positives and 24 integration test failures) |
| **Affected areas** | `services/portfolio/tests/integration/` (5 test files) |
| **Root cause** | PLAN-0025 migrated all portfolio API routes to read `tenant_id` and `user_id` from `request.state` (set by `InternalJWTMiddleware` from `X-Internal-JWT` header). The old `X-Tenant-ID` and `X-Owner-ID` headers are completely ignored. Integration tests were not fully updated: they still called `make_tenant()/make_user()` to create dynamic identities under freshly-created UUIDs, then passed `X-Tenant-ID`/`X-Owner-ID` headers — which routes silently ignore. The JWT in the test client carries fixed `INTEGRATION_TENANT_ID`/`INTEGRATION_USER_ID`. Result: route uses `INTEGRATION_TENANT_ID` to look up the dynamically-created user → `uow.users.get(U_dynamic, INTEGRATION_TENANT_ID)` returns `None` → `UserInactiveError` → 409. |
| **Symptom** | Four failure modes: (A) 409 USER_INACTIVE on portfolio/watchlist/transaction creation; (B) `user_id` assertion mismatch (`INTEGRATION_USER_ID` ≠ dynamically-created user); (C) WATCHLIST_ALREADY_EXISTS collision across tests (all watchlists created for same `INTEGRATION_USER_ID`, duplicate name triggers 409 on second test); (D) 404 on `GET /users/{id}` (user created under `T_dynamic`, JWT lookup uses `INTEGRATION_TENANT_ID`). |
| **Fix** | Replace `make_tenant()/make_user()` API calls with DB-seeding helpers (`seed_tenant()`, `seed_user()`). Use `INTEGRATION_TENANT_ID`/`INTEGRATION_USER_ID` directly in all requests. For isolation tests (cross-user, cross-tenant), seed additional identities in DB and use `make_jwt_headers(tenant_id, user_id)` for per-request JWT injection. Use unique watchlist names (uuid4 suffix) to prevent cross-test name collisions in shared session-scoped DB. |

### Prevention

- After any auth middleware migration that changes how routes extract identity (header → JWT state), run a full integration test suite immediately to detect orphaned header patterns.
- Watchlist/collection endpoints with name uniqueness constraints MUST use unique names per test (e.g., `f"WL-{uuid4().hex[:8]}"`) when sharing a session-scoped DB.
- When a JWT carries a fixed test identity, ALL test data (tenants, users) that routes validate against MUST be seeded under that same identity. Never mix dynamic tenant/user creation with fixed-JWT test clients.
- Add to integration test review checklist: "Do any tests pass `X-Tenant-ID` or `X-Owner-ID` headers? If so, are routes guaranteed to read these headers (not JWT state)?"

---

---

## BP-198 — Setting `_internal_jwt_public_key` in Shared Test Fixture Breaks `skip_verification=True`

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (remediation wave — market-ingestion readyz test drift) |
| **Severity** | LOW (test-only) — all protected routes return 401 when fixture sets a fake key |
| **Affected areas** | `services/market-ingestion/tests/api/test_routes.py` `app_with_overrides` fixture; any service whose test fixture sets `app.state._internal_jwt_public_key` to a non-RSA string while `InternalJWTMiddleware` is in the middleware stack with `skip_verification=True` |
| **Root cause** | `InternalJWTMiddleware.dispatch()` reads `_internal_jwt_public_key` from `app.state` first. When non-None (even a fake string), it bypasses the `skip_verification` branch and calls `jwt.decode(token, "fake-test-key", algorithms=["RS256"])`. PyJWT raises `InvalidKeyError` since the key is not a valid RSA PEM — the middleware returns 401. |
| **Symptom** | Tests that send `X-Internal-JWT` headers to protected routes receive unexpected 401 responses after the shared fixture adds a fake JWKS key. Unprotected paths (e.g. `/readyz`) are unaffected because they are in `_SKIP_PREFIXES`. |
| **Fix** | Set `app.state._internal_jwt_public_key` ONLY in the specific test that needs the JWKS readiness check (e.g. `test_readyz_returns_200_when_all_ok`), not in the shared fixture. The `skip_verification=True` path requires `_internal_jwt_public_key is None` to activate. |

### Prevention

- Never set `app.state._internal_jwt_public_key` to a non-RSA string in a shared test fixture — doing so silently disables `skip_verification` for all protected routes.
- For tests that check `/readyz` JWKS readiness: set the key locally inside the test, not in the fixture.
- See also: BP-197 (JWKS readiness drift), BP-187 (skip_verification safety guard).


---

---

## BP-301 — Test IDs Not Updated After UUID Pattern Constraint Added to FastAPI Path Parameter

**Category**: Testing / API
**Severity**: MEDIUM
**Affected areas**: `market-data` fundamentals API tests; any FastAPI route that adds a `pattern=` constraint to a path parameter.
**First seen**: 2026-04-30 (PLAN-0059-B QA, pre-existing failure).

**Symptoms**:
- Tests that previously passed with short non-UUID IDs (`"instr-001"`, `"unknown-id"`) start returning 422 instead of expected 200/404 after a `pattern=` constraint is added to the path parameter.
- `assert resp.status_code == 404` fails with `422 == 404`.

**Root Cause**:
A UUID pattern constraint (`pattern=r"^[0-9a-fA-F]{8}-..."`) was added to prevent a route collision (where a literal path segment like `/screen` was being matched as `instrument_id`). The constraint is correct in production but breaks existing tests that use short non-UUID test IDs.

**Fix**:
Replace all test IDs with valid UUID-format strings. Add a module-level constant for reuse:
```python
INSTR_UUID = "00000000-0000-0000-0000-000000000001"
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000099"
```

**Prevention**:
- When adding `pattern=` to a FastAPI `Path(...)`, immediately update all unit tests to use IDs matching the new pattern.
- Use a module-level UUID constant in test files rather than inline literals — makes bulk-updates easier.

---

## BP-318 — AsyncMock Session Returns AsyncMock: scalar_one_or_none() Yields Coroutine

**Category**: Test Infrastructure | **Severity**: High (silent wrong behavior)
**Introduced by**: Test mock setup for SQLAlchemy async sessions
**Discovered**: 2026-05-03 (PLAN-0062 deferred follow-up)

### Problem

When a test session factory is built as `AsyncMock()`, all auto-attributes
(including `execute`) become `AsyncMock` instances. Awaiting `session.execute(stmt)`
returns `session.execute.return_value`, which is also an `AsyncMock`. Calling
`.scalar_one_or_none()` or `.all()` on an `AsyncMock` returns a **new coroutine**
rather than a value, because `AsyncMock.__call__` creates coroutines.

The downstream code then receives a coroutine object where it expects `None` or a
scalar value, causing:
- `Decimal(str(<coroutine>))` → `decimal.InvalidOperation`
- `>= float_threshold` comparisons → `TypeError: unsupported operand`
- Silent wrong values propagating through the pipeline

The failure only manifests when repositories that call `result.scalar_one_or_none()`
are exercised through the real implementation (not patched out).

### Fix

Configure `execute.return_value` explicitly as a synchronous `MagicMock`:

```python
result_mock = MagicMock()
result_mock.scalar_one_or_none.return_value = None
result_mock.all.return_value = []
session.execute = AsyncMock(return_value=result_mock)
```

The `execute()` coroutine is still async (awaitable), but its resolved value is
a sync `Result`-like mock, which matches SQLAlchemy's actual behavior.

### Prevention

- **Rule**: When creating mock sessions for integration tests, always set
  `session.execute = AsyncMock(return_value=MagicMock(...))` explicitly.
- **Audit**: If a test file has `session = AsyncMock()` without an explicit
  `execute.return_value`, any repository that calls `scalar_one_or_none()` or
  `all()` on the result is a latent bug.

---

## BP-404 — `prometheus_client` `MetricFamily.name` Strips `_total` Suffix in ≥0.16

### Symptom

Tests asserting `m.name == "foo_total"` always fail after calling `counter.labels(...).inc()` even though the counter is registered and incremented correctly. `REGISTRY.collect()` returns samples but none match the filter.

### Root Cause

`prometheus_client` ≥0.16 changed the `MetricFamily.name` for Counters: the `_total` suffix is stripped from the MetricFamily name (`m.name == "foo"`) but preserved on individual `Sample.name` values (`s.name == "foo_total"`). Code that filters on `m.name == "foo_total"` never matches.

### Fix

Query `Sample.name` rather than `MetricFamily.name`:

```python
# WRONG — m.name strips _total in newer prometheus_client
for m in REGISTRY.collect():
    if m.name == "my_counter_total":  # never matches
        ...

# CORRECT — s.name retains _total
for m in REGISTRY.collect():
    for s in m.samples:
        if s.name == "my_counter_total" and s.labels.get("source") == "x":
            return s.value
```

### Additional Pitfall: Counter Accumulation Across Test Session

The Prometheus `REGISTRY` is a process-wide singleton. Counter values accumulate across all tests in a session. Tests using `assert count == 1` will fail on the second run if the counter was already incremented earlier in the session. **Fix**: use unique label values per test (e.g. `source="unit_test_w55"`) and compare relative changes (`after > before`) rather than absolute values.

---
