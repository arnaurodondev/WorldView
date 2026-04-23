# PLAN-0033 — Unresolved Entity Re-Resolution & Cross-Service LLM Cost Tracking

**PRD**: [PRD-0029](../specs/0029-unresolved-entity-resolution-llm-cost-tracking.md)
**Created**: 2026-04-22
**Updated**: 2026-04-22
**Status**: completed
**Total waves**: 5
**Total tasks**: 23

---

## Overview

This plan implements two features from PRD-0029:

- **Feature A**: `UnresolvedResolutionWorker` (S6) — two-phase re-resolution of UNRESOLVED entity mentions (cascade re-run → Qwen2.5:3b LLM classification → provisional entity creation or noise marking)
- **Feature B**: Cross-service LLM cost tracking — `LlmUsageLogProtocol` in `libs/ml-clients`, per-service `llm_usage_log` tables (S6 + S8 new, S7 extended), S9 admin cost aggregation endpoint

---

## Codebase State Verification

| PRD Reference | Type | Service | Current State (from code) | PRD Expected State | Delta |
|---|---|---|---|---|---|
| `ResolutionOutcome` enum | domain | S6 | 3 values: auto_resolved, provisional, unresolved | 6 values: + escalated, entity_created, noise | Extend enum |
| `EntityMentionModel.resolution_outcome` | ORM col | S6 | ABSENT | VARCHAR(20) server_default='unresolved' | migration 0007 |
| `EntityMentionModel.resolution_noise_reason` | ORM col | S6 | ABSENT | VARCHAR(200) nullable | migration 0007 |
| `EntityMentionModel.resolution_processed_at` | ORM col | S6 | ABSENT | TIMESTAMPTZ nullable | migration 0007 |
| `nlp_db.llm_usage_log` | DB table | S6 | ABSENT | 11-col table | migration 0008 |
| `rag_chat_db.llm_usage_log` | DB table | S8 | ABSENT | 13-col table | migration 0003 |
| `intelligence_db.llm_usage_log` | DB table | S7 | EXISTS (12 cols, head=0005) | + service_name, tenant_id, error_code | migration 0006 |
| `LlmUsageLogProtocol` | protocol | libs | ABSENT | new in ml-clients | new file |
| `cost.py` | utility | libs | ABSENT | PRICING dict + estimate fns | new file |
| `UnresolvedResolutionWorker` | worker | S6 | ABSENT | new worker class | new file |
| `LLMProviderChain` cost logging | feature | S8 | ABSENT | post-stream cost logging | modify provider_chain.py |
| `FallbackChainClient` constructor | S7 | `LlmUsageLogRepository` directly (calls `.insert()`) | accept `LlmUsageLogProtocol` (renamed to `.log()`) | refactor |
| `GeminiDescriptionAdapter` constructor | libs/ml-clients | no `usage_logger` param | accept `LlmUsageLogProtocol` | refactor |
| `GET /internal/v1/llm-costs` | endpoint | S6,S7,S8 | ABSENT | new per-service internal endpoint | new routers |
| `GET /api/v1/admin/llm-costs` | endpoint | S9 | ABSENT | new admin aggregation endpoint | new router |
| `Settings` (config class) | config | S6 | no unresolved_resolution_* | 10 new fields | extend config.py |

---

## Plan Dependency Graph

```
Wave 1 (libs/ml-clients)
   ├──→ Wave 3 (S6 domain+ORM, S7 refactor, S8 adapter)  [parallel within wave]
   └──→ Wave 2 (DB migrations)  [parallel with Wave 3]
          └──→ Wave 3 (depends on migrations for new tables)

Wave 3 → Wave 4 (S6 worker — depends on S6 domain from Wave 3)
Wave 3 → Wave 5 (internal endpoints — depends on services being ready)
Wave 4 → Wave 5 (S6 internal endpoint needs worker and cost repo)
```

**Simplified execution order:**

```
Wave 1 (libs) → Wave 2 (migrations) → Wave 3 (S6 domain + S7 refactor + S8 adapter) → Wave 4 (S6 worker) → Wave 5 (endpoints + S9)
```

Wave 2 and Wave 3 can overlap if the migration changes are applied first (migration is a separate task with no code dependency on Wave 3 application logic).

---

## Wave 1: Shared Library — LlmUsageLogProtocol & Cost Utilities

**Goal**: Extend `libs/ml-clients` with the `LlmUsageLogProtocol` and cost estimation utilities that all downstream services will depend on.
**Depends on**: none
**Estimated effort**: 30–45 minutes
**Architecture layer**: domain / shared library

### Tasks

#### T-A-1-01: Add `LlmUsageLogProtocol` and `LlmCallUsage` to `libs/ml-clients`

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03, T-C-3-01, T-D-1-01, T-E-1-02]
**Target files**:
- `libs/ml-clients/src/ml_clients/usage_log.py` (NEW)
- `libs/ml-clients/src/ml_clients/__init__.py` (MODIFY)

**What to build**:
Create a new module `usage_log.py` in ml-clients that defines:
1. `LlmUsageLogProtocol` — a `@runtime_checkable Protocol` that all service cost-log repositories must satisfy
2. `LlmCallUsage` — a frozen dataclass summarising the outcome of one LLM call (returned by adapter wrappers)

**Entities / Components**:

- **Name**: `LlmUsageLogProtocol`
  - **Purpose**: Structural interface that service-side repositories implement; allows ml-clients adapters to accept cost loggers without importing service infrastructure
  - **Key method**: `async def log(self, *, model_id: str, provider: str, capability: str, tokens_in: int, tokens_out: int, latency_ms: int, estimated_cost_usd: float = 0.0, success: bool = True, error_code: str | None = None, **context: object) -> None`
  - **Invariant**: Implementations MUST be non-blocking (fire-and-forget); exceptions MUST be swallowed and logged via structlog

- **Name**: `LlmCallUsage`
  - **Purpose**: Immutable value object returned by cost-aware adapter calls
  - **Key attributes**:
    - `tokens_in: int` — input tokens (exact if available, word-count estimate otherwise)
    - `tokens_out: int` — output tokens
    - `estimated_cost_usd: float` — computed by `estimate_cost()`
    - `provider: str` — "deepinfra" | "openrouter" | "gemini" | "ollama"
    - `model_id: str` — model string passed to provider
    - `latency_ms: int` — wall-clock duration of API call
    - `success: bool` — True on 2xx, False on exception/timeout
    - `error_code: str | None` — "timeout" | "rate_limit" | "auth" | "model_error" | None

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_llm_usage_log_protocol_structural_check` | A mock class with the right signature satisfies `isinstance(x, LlmUsageLogProtocol)` | unit |
| `test_llm_usage_log_protocol_missing_method_fails` | A class without `log()` does NOT satisfy the protocol | unit |
| `test_llm_call_usage_frozen` | `LlmCallUsage` is immutable (frozen dataclass) | unit |
| `test_none_logger_accepted` | Passing `None` as logger to any adapter does not raise | unit |

**Acceptance criteria**:
- [ ] `LlmUsageLogProtocol` defined with `@runtime_checkable`
- [ ] `LlmCallUsage` is a `@dataclass(frozen=True)`
- [ ] `isinstance(mock_impl, LlmUsageLogProtocol)` returns True for a class with the correct `log` signature
- [ ] mypy passes with strict Protocol checks

---

#### T-A-1-02: Add `cost.py` — pricing constants and estimation utilities

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-03, T-C-3-01, T-E-1-02]
**Target files**:
- `libs/ml-clients/src/ml_clients/cost.py` (NEW)

**What to build**:
A standalone utility module with no external imports (besides `__future__` and typing) that provides:
1. `PRICING` — dict of provider → model → input/output cost per 1M tokens
2. `estimate_cost(provider, model_id, tokens_in, tokens_out) -> float` — returns USD cost, 0.0 for unknown
3. `estimate_tokens_from_text(text) -> int` — word-count heuristic for Ollama (no token API)

**Logic & Behavior**:
```python
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "deepinfra": {
        "deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    },
    "openrouter": {
        "deepseek/deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    },
    "gemini": {
        # Match model ID used in gemini_description.py: _DEFAULT_MODEL_ID = "gemini-3.1-flash-lite"
        "gemini-3.1-flash-lite": {"input": 0.075, "output": 0.30},
    },
    "ollama": {
        # All Ollama models are local — zero external cost
        "*": {"input": 0.0, "output": 0.0},
    },
}

def estimate_cost(provider: str, model_id: str, tokens_in: int, tokens_out: int) -> float:
    # Try exact match, then "*" wildcard; return 0.0 for unknown
    ...

def estimate_tokens_from_text(text: str) -> int:
    # 1 token ≈ 0.75 words → tokens = ceil(word_count / 0.75); min 1
    ...
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_estimate_cost_deepinfra` | 1000 in + 500 out = (1000/1M)*0.69 + (500/1M)*2.19 | unit |
| `test_estimate_cost_gemini` | correct gemini-3.1-flash-lite pricing | unit |
| `test_estimate_cost_ollama_any_model` | always 0.0 regardless of model_id | unit |
| `test_estimate_cost_unknown_provider` | returns 0.0, no exception | unit |
| `test_estimate_tokens_from_text_100_words` | 100-word text → ~133 tokens | unit |
| `test_estimate_tokens_from_text_empty` | empty string → 1 (min) | unit |

**Acceptance criteria**:
- [ ] `estimate_cost("deepinfra", "deepseek-r1-distill-qwen-32b", 1_000_000, 1_000_000)` == 0.69 + 2.19 = 2.88
- [ ] `estimate_cost("ollama", "anything", 9999, 9999)` == 0.0
- [ ] `estimate_cost("unknown", "unknown", 100, 100)` == 0.0 (no exception)
- [ ] All 6 unit tests pass

---

#### T-A-1-03: Update `libs/ml-clients/__init__.py` exports

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: none
**Target files**:
- `libs/ml-clients/src/ml_clients/__init__.py` (MODIFY)

**What to build**:
Add `LlmUsageLogProtocol`, `LlmCallUsage`, `estimate_cost`, `estimate_tokens_from_text` to the public exports in `__init__.py`.

**Downstream test impact**:
- `libs/ml-clients/tests/test_protocols.py` — add assertion that new protocol and dataclass are exported

**Acceptance criteria**:
- [ ] `from ml_clients import LlmUsageLogProtocol, LlmCallUsage, estimate_cost, estimate_tokens_from_text` works
- [ ] `__all__` is alphabetically sorted (RUF022)

---

### Pre-read (agent must read before starting)
- `libs/ml-clients/src/ml_clients/__init__.py`
- `libs/ml-clients/src/ml_clients/protocols.py`
- `libs/ml-clients/src/ml_clients/dataclasses.py`
- `libs/ml-clients/tests/test_protocols.py`

### Validation Gate
- [ ] `ruff check libs/ml-clients/` passes
- [ ] `mypy libs/ml-clients/` passes (strict Protocol checks)
- [ ] All 10+ unit tests pass (6 for cost.py + 4 for protocol)
- [ ] No architecture violations (ml-clients has no service infrastructure imports)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | Wave 1 only adds new exports; no existing code modified | — |

### Regression Guardrails
- **BP-126**: New modules must not introduce mutable class-level defaults — `LlmCallUsage` must be `@dataclass(frozen=True)`, `PRICING` dict is module-level constant (acceptable)
- **RUF022**: `__all__` in `__init__.py` must be alphabetically sorted after adding new exports

---

## Wave 2: DB Migrations — All Four Services

**Goal**: Apply all four database migrations in parallel (different DBs, no interdependency).
**Depends on**: Wave 1 (protocol defined before services implement it)
**Estimated effort**: 30–45 minutes
**Architecture layer**: infrastructure / schema

### Tasks

#### T-B-1-01: nlp_db migration 0007 — resolution outcome columns on entity_mentions

**Type**: schema
**depends_on**: none (within wave)
**blocks**: [T-C-1-01, T-C-2-01]
**Target files**:
- `services/nlp-pipeline/alembic/versions/0007_add_resolution_outcome_to_entity_mentions.py` (NEW)

**What to build**:
Alembic migration that adds three columns to `entity_mentions` plus one partial index. Includes a two-step data backfill.

**Schema changes**:
```sql
-- Step 1: Add columns with server_default
ALTER TABLE entity_mentions
  ADD COLUMN resolution_outcome      VARCHAR(20)  DEFAULT 'unresolved',
  ADD COLUMN resolution_noise_reason VARCHAR(200),
  ADD COLUMN resolution_processed_at TIMESTAMPTZ;

-- Step 2: Backfill — rows with resolved_entity_id → auto_resolved
UPDATE entity_mentions
SET resolution_outcome = 'auto_resolved'
WHERE resolved_entity_id IS NOT NULL;

-- Step 3: Partial index for worker polling
CREATE INDEX idx_entity_mentions_unresolved
ON entity_mentions (created_at ASC)
WHERE resolution_outcome = 'unresolved';
```

**Downgrade**: `DROP INDEX idx_entity_mentions_unresolved; DROP COLUMN resolution_outcome, resolution_noise_reason, resolution_processed_at`

**Downstream test impact**:
- `services/nlp-pipeline/tests/unit/infrastructure/` — any test asserting column count on EntityMentionModel will need updating

**Acceptance criteria**:
- [ ] Migration runs forward without error on empty and populated `entity_mentions`
- [ ] `resolution_outcome` defaults to 'unresolved' on new inserts that omit it
- [ ] Rows with `resolved_entity_id IS NOT NULL` have `resolution_outcome='auto_resolved'` after backfill
- [ ] Downgrade removes all three columns and the index

---

#### T-B-1-02: nlp_db migration 0008 — create `llm_usage_log` table

**Type**: schema
**depends_on**: [T-B-1-01]
**blocks**: [T-C-3-01]
**Target files**:
- `services/nlp-pipeline/alembic/versions/0008_create_llm_usage_log.py` (NEW)

**What to build**:
```sql
CREATE TABLE llm_usage_log (
    log_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id           VARCHAR(200) NOT NULL,
    provider           VARCHAR(50)  NOT NULL,
    capability         VARCHAR(50)  NOT NULL,
    service_name       VARCHAR(50)  NOT NULL DEFAULT 'nlp-pipeline',
    tenant_id          UUID,
    tokens_in          INT          NOT NULL DEFAULT 0,
    tokens_out         INT          NOT NULL DEFAULT 0,
    estimated_cost_usd FLOAT        NOT NULL DEFAULT 0.0,
    latency_ms         INT          NOT NULL DEFAULT 0,
    success            BOOLEAN      NOT NULL DEFAULT true,
    error_code         VARCHAR(50),
    doc_id             UUID,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_nlp_llm_usage_period   ON llm_usage_log (created_at DESC);
CREATE INDEX idx_nlp_llm_usage_provider ON llm_usage_log (provider, created_at DESC);
```

**Acceptance criteria**:
- [ ] Table created with all 13 columns
- [ ] Both indexes created
- [ ] Downgrade: `DROP TABLE llm_usage_log`

---

#### T-B-1-03: rag_chat_db migration 0003 — create `llm_usage_log` table

**Type**: schema
**depends_on**: none (within wave, different DB)
**blocks**: [T-E-1-01]
**Target files**:
- `services/rag-chat/alembic/versions/0003_create_llm_usage_log.py` (NEW)

**What to build**:
Same schema as nlp_db version plus two extra columns specific to S8:
```sql
CREATE TABLE llm_usage_log (
    log_id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id           VARCHAR(200) NOT NULL,
    provider           VARCHAR(50)  NOT NULL,
    capability         VARCHAR(50)  NOT NULL,
    service_name       VARCHAR(50)  NOT NULL DEFAULT 'rag-chat',
    tenant_id          UUID,
    tokens_in          INT          NOT NULL DEFAULT 0,
    tokens_out         INT          NOT NULL DEFAULT 0,
    estimated_cost_usd FLOAT        NOT NULL DEFAULT 0.0,
    latency_ms         INT          NOT NULL DEFAULT 0,
    success            BOOLEAN      NOT NULL DEFAULT true,
    error_code         VARCHAR(50),
    session_id         UUID,
    chat_thread_id     UUID,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_rag_llm_usage_period   ON llm_usage_log (created_at DESC);
CREATE INDEX idx_rag_llm_usage_provider ON llm_usage_log (provider, created_at DESC);
CREATE INDEX idx_rag_llm_usage_session  ON llm_usage_log (session_id) WHERE session_id IS NOT NULL;
```

**Downstream test impact**:
- `services/rag-chat/tests/unit/infrastructure/test_ddl_alignment.py` — if this test asserts table list for rag_chat_db, add `"llm_usage_log"` to expected set

**Acceptance criteria**:
- [ ] Table and all 15 columns created
- [ ] Three indexes created
- [ ] Downgrade: `DROP TABLE llm_usage_log`

---

#### T-B-1-04: intelligence_db migration 0006 — extend existing `llm_usage_log`

**Type**: schema
**depends_on**: none (within wave, different DB)
**blocks**: [T-D-1-02]
**Target files**:
- `services/intelligence-migrations/alembic/versions/0006_extend_llm_usage_log.py` (NEW)

**What to build**:
```sql
ALTER TABLE llm_usage_log
  ADD COLUMN service_name VARCHAR(50) NOT NULL DEFAULT 'knowledge-graph',
  ADD COLUMN tenant_id    UUID,
  ADD COLUMN error_code   VARCHAR(50);
```

**Downstream test impact**:
- `services/intelligence-migrations/tests/test_migration.py` — asserts `llm_usage_log` in table list; this migration doesn't add a table, just columns — verify test still passes
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/llm_usage_log.py` — INSERT statement needs updating in Wave 3 (T-D-1-02)

**Acceptance criteria**:
- [ ] Three columns added to existing `llm_usage_log`
- [ ] Existing S7 `log()` still works (new columns have server defaults)
- [ ] Downgrade: drop the three columns

---

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/alembic/versions/0006_add_ner_model_id_to_entity_mentions.py`
- `services/rag-chat/alembic/versions/0002_add_context_valkey_keys.py`
- `services/intelligence-migrations/alembic/versions/0005_add_extraction_model_id_to_claims.py`
- `services/intelligence-migrations/tests/test_migration.py`

### Validation Gate
- [ ] All 4 migrations apply forward without error (test with Alembic upgrade head)
- [ ] All 4 migrations downgrade cleanly
- [ ] BP-126 compliance: all new columns have `server_default` or are nullable
- [ ] `services/intelligence-migrations/tests/test_migration.py` still passes

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/rag-chat/tests/unit/infrastructure/test_ddl_alignment.py` | New table in rag_chat_db | Add `"llm_usage_log"` to expected tables set |

### Regression Guardrails
- **BP-126**: All new NOT NULL columns must have `server_default` — verified above for all 4 migrations
- **BP-007**: Alembic migration must not use `op.execute()` for DDL that alembic auto-generates — use `op.add_column()` / `op.create_table()` / `op.create_index()`

---

## Wave 3: S6 Domain + S7 Refactor + S8 Adapter (Parallel)

**Goal**: Implement domain/ORM extensions in S6, refactor S7 FallbackChainClient to use the new protocol, and add post-stream cost logging to S8's LLMProviderChain.
**Depends on**: Wave 1 (protocol), Wave 2 (migration columns must exist before ORM model is updated)
**Estimated effort**: 60–90 minutes
**Architecture layer**: domain + infrastructure

Tasks in this wave touch three **different** services and can be executed in parallel worktrees.

---

### Tasks

#### T-C-1-01: S6 — Extend `ResolutionOutcome` enum and `EntityMention` domain entity

**Type**: impl
**depends_on**: none (within wave)
**blocks**: [T-C-2-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/domain/entities/entity_mention.py` (MODIFY)

**What to build**:
Extend the existing `ResolutionOutcome` enum from 3 values to 6, and add **2** new optional fields to `EntityMention`.

Note: `resolution_outcome: ResolutionOutcome | None = None` **already exists** in `domain/models.py:73` — do NOT add it again. Only `resolution_noise_reason` and `resolution_processed_at` are new.

**Entities / Components**:
- **Name**: `ResolutionOutcome` (enum, in `domain/enums.py`)
  - **Current values**: `auto_resolved`, `provisional`, `unresolved`
  - **New values to add**:
    - `escalated` — mention is currently being processed by the worker (transient lock state)
    - `entity_created` — LLM confirmed it is a genuine entity; provisional_entity_queue row inserted
    - `noise` — LLM classified it as not a real entity; kept permanently for audit trail

- **Name**: `EntityMention` (dataclass, in `domain/models.py`)
  - **New fields to add** (both optional, default `None`):
    - `resolution_noise_reason: str | None = None` — LLM-provided reason when classified as noise
    - `resolution_processed_at: datetime | None = None` — UTC timestamp of when worker processed it

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_resolution_outcome_all_six_values` | Enum has exactly 6 members | unit |
| `test_entity_mention_new_fields_default_none` | Constructing EntityMention without new fields leaves them None | unit |
| `test_entity_mention_with_noise_outcome` | Can set outcome=noise, noise_reason="...", processed_at=datetime | unit |

**Acceptance criteria**:
- [ ] `ResolutionOutcome` has 6 members: auto_resolved, provisional, unresolved, escalated, entity_created, noise
- [ ] `EntityMention` gains exactly 2 new optional fields (`resolution_noise_reason`, `resolution_processed_at`) with `None` defaults
- [ ] Existing `EntityMention(...)` construction calls in tests still compile (new fields have defaults)
- [ ] `domain/enums.py` modified; `domain/models.py` modified — no infrastructure imports added
- [ ] mypy passes

---

#### T-C-1-02: S6 — Update `EntityMentionModel` ORM model and repository

**Type**: impl
**depends_on**: [T-B-1-01] (migration 0007 must exist first)
**blocks**: [T-C-2-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/models/entity_mention.py` (MODIFY)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/entity_mention.py` (MODIFY)

**What to build**:

Add 3 new mapped columns to `EntityMentionModel` matching the migration 0007 schema:
```python
resolution_outcome: Mapped[str | None] = mapped_column(
    String(20), server_default="unresolved", nullable=False
)
resolution_noise_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
resolution_processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
```

Add two new repository methods:
1. `async def get_unresolved_batch(self, batch_size: int, lock: bool = True) -> list[EntityMentionModel]`
   — `SELECT ... WHERE resolution_outcome = 'unresolved' ORDER BY created_at ASC LIMIT :batch_size FOR UPDATE SKIP LOCKED`
2. `async def update_resolution_outcome(self, mention_id: UUID, outcome: str, noise_reason: str | None = None) -> None`
   — UPDATE with `resolution_processed_at = utc_now()`

**Also fix existing methods** (R-005):
3. Update `EntityMentionRepository.resolve()` to also set `resolution_outcome = 'auto_resolved'` in its UPDATE statement — otherwise Block 9 successes won't be tracked in the new column.
4. Update `EntityMentionRepository.add()` to pass `resolution_outcome=str(mention.resolution_outcome)` when `mention.resolution_outcome is not None` — so in-memory outcome is persisted on initial INSERT.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_unresolved_batch_returns_only_unresolved` | Only rows with outcome='unresolved' returned | unit (mock session) |
| `test_update_resolution_outcome_sets_processed_at` | processed_at is set to non-None after update | unit (mock session) |
| `test_update_resolution_outcome_noise_stores_reason` | noise_reason stored when outcome=noise | unit |
| `test_resolve_sets_auto_resolved_outcome` | Existing `resolve()` method now also sets `resolution_outcome='auto_resolved'` | unit |

**Acceptance criteria**:
- [ ] ORM model has 3 new columns matching migration types exactly
- [ ] `get_unresolved_batch` uses `FOR UPDATE SKIP LOCKED`
- [ ] `update_resolution_outcome` sets `resolution_processed_at = utc_now()`
- [ ] Existing `resolve()` method updated to set `resolution_outcome='auto_resolved'`
- [ ] mypy passes on model and repository

---

#### T-C-1-03: S6 — Create `NlpUsageLogRepository` (implements `LlmUsageLogProtocol`)

**Type**: impl
**depends_on**: [T-B-1-02, T-A-1-01]
**blocks**: [T-C-2-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/db/repositories/llm_usage_log.py` (NEW)

**What to build**:
A repository class that satisfies `LlmUsageLogProtocol` and writes to `nlp_db.llm_usage_log`.

```python
class NlpUsageLogRepository:
    """Implements LlmUsageLogProtocol for the nlp-pipeline service."""

    def __init__(self, session: AsyncSession) -> None: ...

    async def log(
        self,
        *,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
        error_code: str | None = None,
        **context: object,  # accepts doc_id, tenant_id, etc.
    ) -> None:
        """Insert one row; swallow all exceptions to prevent observer affecting subject."""
```

**Logic**:
- Extract `doc_id` and `tenant_id` from `**context` if present
- `service_name` is hardcoded to `"nlp-pipeline"` (constant, not configurable)
- Catch ALL exceptions inside `log()` and emit `structlog.warning("nlp_usage_log_failed", error=str(e))`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_nlp_usage_log_inserts_row` | Happy path: INSERT succeeds | unit (mock session) |
| `test_nlp_usage_log_swallows_db_error` | DB failure does not propagate | unit |
| `test_nlp_usage_log_isinstance_check` | `isinstance(repo, LlmUsageLogProtocol)` is True | unit |

**Acceptance criteria**:
- [ ] `isinstance(NlpUsageLogRepository(mock_session), LlmUsageLogProtocol)` is True
- [ ] All DB exceptions are swallowed (no exception propagates from `log()`)
- [ ] `doc_id` extracted from kwargs if present
- [ ] mypy passes

---

#### T-C-1-04: S6 — Extend `Settings` with worker configuration

**Type**: impl + config
**depends_on**: none (within wave)
**blocks**: [T-C-2-02]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (MODIFY)

**What to build**:
Add 10 new settings fields to `Settings` (class is named `Settings`, **not** `NlpPipelineSettings`; env prefix is `NLP_PIPELINE_`):

```python
# UnresolvedResolutionWorker settings (NLP_PIPELINE_ prefix in env)
unresolved_resolution_enabled: bool = True
unresolved_resolution_interval_s: int = 1800          # 30 minutes
unresolved_resolution_batch_size: int = 500
unresolved_resolution_lookback_days: int = 90
unresolved_resolution_llm_timeout_s: float = 10.0
unresolved_resolution_llm_retries: int = 2
unresolved_resolution_stale_escalated_minutes: int = 30
unresolved_resolution_ollama_base_url: str = "http://ollama:11434"
unresolved_resolution_classification_model: str = "qwen2.5:3b"
unresolved_resolution_max_llm_batch: int = 20          # max mentions per Ollama call
```

Also add corresponding env var documentation in `services/nlp-pipeline/.claude-context.md`.

**Acceptance criteria**:
- [ ] All 10 settings fields added with correct types and defaults
- [ ] Pydantic validation passes (no bare `str` without constraints where a positive int is expected)
- [ ] `mypy` passes

---

#### T-D-1-01: S7 — Refactor `FallbackChainClient` to accept `LlmUsageLogProtocol`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-F-1-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py` (MODIFY)

**What to build**:
Change `FallbackChainClient.__init__` to accept `usage_logger: LlmUsageLogProtocol | None = None` instead of the current concrete `LlmUsageLogRepository`. Update the private `_log()` helper to call `await self._log_repo.log(...)` (renamed from `.insert()` — see T-D-1-02).

**Logic & Behavior**:
- Current: `self._log_repo: LlmUsageLogRepository | None` — concrete type from S7 infrastructure; calls `self._log_repo.insert(**kwargs)`
- New: `self._usage_logger: LlmUsageLogProtocol | None` — rename attribute; calls `self._usage_logger.log(**kwargs)`
- Rename `_log_repo` attribute to `_usage_logger` in `__init__` and `_log()`
- Change `_log()` body: `await self._log_repo.insert(**kwargs)` → `await self._usage_logger.log(**kwargs)`
- `entity_id` and `relation_id` are currently passed as named kwargs from `_log()`; they become part of `**context` in the protocol call (the protocol accepts `**context: object`) — no other changes needed at call sites
- The `KgUsageLogRepository` (renamed to use `.log()` in T-D-1-02) still satisfies the protocol; existing S7 wiring passes the same object

**Downstream test impact**:
- `services/knowledge-graph/tests/unit/infrastructure/llm/test_fallback_chain.py` — update mock from `LlmUsageLogRepository` to any duck-typed object satisfying `LlmUsageLogProtocol`; rename `.insert()` calls to `.log()` in mock assertions

**Acceptance criteria**:
- [ ] `FallbackChainClient.__init__` signature: `usage_logger: LlmUsageLogProtocol | None = None`
- [ ] `_log()` calls `self._usage_logger.log(...)` (not `.insert()`)
- [ ] No direct import of `LlmUsageLogRepository` in `fallback_chain.py`
- [ ] mypy passes (Protocol is `@runtime_checkable`)

---

#### T-D-1-02: S7 — Rename `KgUsageLogRepository.insert()` → `log()` and add new columns

**Type**: impl
**depends_on**: [T-B-1-04, T-A-1-01]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/llm_usage_log.py` (MODIFY)

**What to build**:
1. Rename method `insert()` → `log()` to satisfy `LlmUsageLogProtocol`
2. Change signature to use `**context: object` for service-specific fields (replacing the current named `entity_id` and `relation_id` params)
3. Update the INSERT statement to include the three new columns added by migration 0006 (`service_name`, `tenant_id`, `error_code`)

New signature:
```python
async def log(
    self,
    *,
    model_id: str,
    provider: str,
    capability: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    estimated_cost_usd: float = 0.0,
    success: bool = True,
    error_code: str | None = None,
    **context: object,  # entity_id, relation_id, tenant_id
) -> None:
    entity_id = context.get("entity_id")
    relation_id = context.get("relation_id")
    tenant_id = context.get("tenant_id")
    # INSERT with service_name='knowledge-graph', tenant_id, error_code
```

The return type changes from `UUID` to `None` — RETURNING clause is removed (not needed; protocol returns None).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_kg_usage_log_isinstance_check` | `isinstance(KgUsageLogRepository(mock), LlmUsageLogProtocol)` is True | unit |
| `test_kg_usage_log_new_columns_written` | service_name, error_code extracted from context and in INSERT | unit |
| `test_kg_usage_log_entity_id_from_context` | entity_id and relation_id extracted from **context | unit |

**Acceptance criteria**:
- [ ] Method renamed from `insert()` to `log()`; return type is `None`
- [ ] `entity_id` and `relation_id` extracted from `**context`
- [ ] INSERT includes `service_name='knowledge-graph'`, `tenant_id`, `error_code`
- [ ] Protocol check passes at runtime: `isinstance(KgUsageLogRepository(...), LlmUsageLogProtocol)` is True
- [ ] mypy passes

---

#### T-D-1-03: libs/ml-clients — Inject `LlmUsageLogProtocol` into `GeminiDescriptionAdapter`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `libs/ml-clients/src/ml_clients/adapters/gemini_description.py` (MODIFY)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py` (MODIFY — wire logger)

**What to build**:

Add an optional `usage_logger: LlmUsageLogProtocol | None = None` parameter to `GeminiDescriptionAdapter.__init__`. After a successful `generate_description()` call (in `_adjust_cost()`), fire a non-blocking cost log.

`GeminiDescriptionAdapter` already extracts `input_tokens` and `output_tokens` from `response.usage_metadata` in `_adjust_cost()`. Reuse these values for the log:

```python
# At end of _adjust_cost(), after computing actual cost:
if self._usage_logger is not None:
    import asyncio
    asyncio.create_task(
        self._usage_logger.log(
            model_id=self._model_id,
            provider="gemini",
            capability="description",
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            latency_ms=0,          # GeminiDescriptionAdapter doesn't track wall-clock time
            estimated_cost_usd=actual,
            success=True,
        )
    )
```

On failure (in `generate_description()` exception handler), log with `success=False`:
```python
if self._usage_logger is not None:
    import asyncio
    asyncio.create_task(
        self._usage_logger.log(
            model_id=self._model_id,
            provider="gemini",
            capability="description",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            estimated_cost_usd=0.0,
            success=False,
            error_code="model_error",
        )
    )
```

**Wiring in S7 (`definition_refresh.py`)**:
`DefinitionRefreshWorker` constructs `EntityDescriptionClient` which wraps `GeminiDescriptionAdapter`. To thread the logger:
- Add `usage_logger: LlmUsageLogProtocol | None = None` param to `DefinitionRefreshWorker.__init__`
- Pass it to `GeminiDescriptionAdapter` constructor at construction time (or check if `description_client` is a `GeminiDescriptionAdapter` and set `_usage_logger` post-construction)
- The wiring caller in `main.py` / container passes `KgUsageLogRepository(session)` as the logger

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_gemini_adapter_logs_cost_on_success` | `usage_logger.log()` called once after successful generation | unit (mock logger) |
| `test_gemini_adapter_logs_failure_on_error` | `usage_logger.log(success=False)` called on API error | unit |
| `test_gemini_adapter_no_logger_no_error` | `usage_logger=None` → no exception, generation works | unit |

**Acceptance criteria**:
- [ ] `GeminiDescriptionAdapter.__init__` gains `usage_logger: LlmUsageLogProtocol | None = None`
- [ ] Cost logged (fire-and-forget `asyncio.create_task`) on both success and failure paths
- [ ] No import of `LlmUsageLogRepository` in `gemini_description.py` (protocol only)
- [ ] All 3 tests pass
- [ ] mypy passes

---

#### T-E-1-01: S8 — Create `RagChatUsageLogRepository` (implements `LlmUsageLogProtocol`)

**Type**: impl
**depends_on**: [T-B-1-03, T-A-1-01]
**blocks**: [T-E-1-02]
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/db/repositories/llm_usage_log.py` (NEW)

**What to build**:
Same pattern as `NlpUsageLogRepository` but writes to `rag_chat_db.llm_usage_log`, extracts `session_id` and `chat_thread_id` from `**context`.

```python
class RagChatUsageLogRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def log(self, *, model_id, provider, capability, tokens_in, tokens_out,
                  latency_ms, estimated_cost_usd=0.0, success=True,
                  error_code=None, **context) -> None:
        # Extract session_id, chat_thread_id, tenant_id from context
        # INSERT into rag_chat_db.llm_usage_log
        # Swallow all exceptions
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_rag_usage_log_inserts_with_session_id` | session_id and chat_thread_id extracted and persisted | unit |
| `test_rag_usage_log_swallows_error` | DB failure does not propagate | unit |
| `test_rag_usage_log_isinstance_protocol` | `isinstance(repo, LlmUsageLogProtocol)` is True | unit |

**Acceptance criteria**:
- [ ] Protocol check passes at runtime
- [ ] `session_id` and `chat_thread_id` extracted from kwargs
- [ ] All DB exceptions swallowed
- [ ] mypy passes

---

#### T-E-1-02: S8 — Add post-stream cost logging to `LLMProviderChain`

**Type**: impl
**depends_on**: [T-E-1-01, T-A-1-01, T-A-1-02]
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/llm/provider_chain.py` (MODIFY)

**What to build**:
After a successful stream completes, estimate token counts from the prompt and collected output using `estimate_tokens_from_text()` (word-count heuristic — the current `DeepInfraCompletionAdapter` yields only text strings and discards the raw SSE usage data, so exact token counts are not available without adapter refactoring, which is out of scope). Log cost via a fire-and-forget `asyncio.create_task`.

**Logic & Behavior** (step-by-step):
1. `LLMProviderChain.__init__` gains `usage_logger: LlmUsageLogProtocol | None = None`
2. In `stream()`, track: `t0 = time.monotonic()` at start, accumulate `_output_chunks: list[str] = []` as chunks are yielded
3. After the loop exits normally (all chunks yielded), fire:
   ```python
   if self._usage_logger is not None:
       tokens_in = estimate_tokens_from_text(prompt)
       tokens_out = estimate_tokens_from_text("".join(_output_chunks))
       cost = estimate_cost(active_provider, active_model_id, tokens_in, tokens_out)
       asyncio.create_task(
           self._usage_logger.log(
               model_id=active_model_id,
               provider=active_provider,
               capability="chat_completion",
               tokens_in=tokens_in,
               tokens_out=tokens_out,
               latency_ms=int((time.monotonic() - t0) * 1000),
               estimated_cost_usd=cost,
               success=True,
           )
       )
   ```
   where `active_provider = provider.name` (the provider that successfully served) and `active_model_id` is read from `getattr(provider, 'model_id', provider.name)`.
4. On stream failure (`ProviderUnavailableError` raised): log with `success=False`, `error_code="model_error"`, `tokens_in=estimate_tokens_from_text(prompt)`, `tokens_out=0`

Note: Token counts are approximate (word-count heuristic). This is acceptable — DeepInfra/OpenRouter calls have negligible external cost tracking error vs Ollama ($0) calls, and the word-count estimate is consistent with how Ollama calls are tracked in S7.

**Error classification** (on `ProviderUnavailableError`):
- All providers exhausted → `error_code="model_error"` (provider chain already logs individual failures via structlog)

**Imports to add**: `import asyncio`, `import time` (if not present), `from ml_clients.cost import estimate_cost, estimate_tokens_from_text`

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_provider_chain_logs_cost_after_stream` | usage_logger.log called once after stream completes with estimated tokens | unit (mock logger) |
| `test_provider_chain_logs_failure_on_unavailable` | error_code="model_error", success=False on ProviderUnavailableError | unit |
| `test_provider_chain_no_logger_no_error` | usage_logger=None → no exception, stream works normally | unit |
| `test_provider_chain_cost_estimate_deepinfra` | tokens_in/out estimated from prompt/output text; cost computed correctly | unit |

**Acceptance criteria**:
- [ ] `usage_logger` is optional (default None)
- [ ] `asyncio.create_task` used (fire-and-forget, non-blocking)
- [ ] `estimate_tokens_from_text()` and `estimate_cost()` from `ml_clients.cost` used
- [ ] `active_provider` resolved from the provider that served the request
- [ ] On `ProviderUnavailableError`, `success=False` and `error_code="model_error"` logged
- [ ] No import of concrete `RagChatUsageLogRepository` in `provider_chain.py` (only protocol)
- [ ] All 4 tests pass

---

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py` — EntityMention dataclass (line 57-74)
- `services/nlp-pipeline/src/nlp_pipeline/domain/enums.py` — ResolutionOutcome enum
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` — EntityMentionModel ORM
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/entity_mention.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py` — Settings class (note: named `Settings`, not `NlpPipelineSettings`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/llm/fallback_chain.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/llm_usage_log.py`
- `libs/ml-clients/src/ml_clients/adapters/gemini_description.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/definition_refresh.py`
- `services/rag-chat/src/rag_chat/infrastructure/llm/provider_chain.py`

### Validation Gate
- [ ] `ruff check` passes on all 3 services + libs/ml-clients
- [ ] `mypy` passes on all 3 services + libs/ml-clients
- [ ] New unit tests pass: ≥13 new tests across S6+S7+S8+ml-clients
- [ ] `isinstance(NlpUsageLogRepository(...), LlmUsageLogProtocol)` True at runtime
- [ ] `isinstance(KgUsageLogRepository(...), LlmUsageLogProtocol)` True at runtime
- [ ] `isinstance(RagChatUsageLogRepository(...), LlmUsageLogProtocol)` True at runtime
- [ ] No cross-service DB imports (domain has no infrastructure imports)
- [ ] `FallbackChainClient._log()` calls `.log()` not `.insert()`

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/knowledge-graph/tests/unit/infrastructure/llm/test_fallback_chain.py` | FallbackChainClient constructor now accepts `LlmUsageLogProtocol` type | Update mock type annotation from `LlmUsageLogRepository` to `LlmUsageLogProtocol` (duck-typed mock still works) |
| `services/nlp-pipeline/tests/unit/domain/test_entity_mention.py` | EntityMention gains 3 new optional fields | Existing tests still pass (new fields have defaults); add 3 new tests |

### Regression Guardrails
- **BP-170**: This wave does NOT yet fix UNRESOLVED orphaning (that's Wave 4) — ensure no code in this wave marks mentions as noise without the LLM classification
- **BP-025**: `LLMProviderChain` external I/O — must not block stream on cost log; `asyncio.create_task` ensures this
- **BP-126**: ORM columns added in T-C-1-02 must match exact types from migration 0007 (`VARCHAR(20)`, `VARCHAR(200)`, `TIMESTAMPTZ`)

---

## Wave 4: S6 — `UnresolvedResolutionWorker` Implementation ✅

**Goal**: Implement the two-phase `UnresolvedResolutionWorker` in S6: free cascade re-run (Phase 1), LLM noise/entity classification (Phase 2), and stale-lock recovery.
**Depends on**: Wave 2 (migration 0007 must exist), Wave 3 (S6 domain + ORM + config + NlpUsageLogRepository)
**Estimated effort**: 60–90 minutes
**Architecture layer**: application / infrastructure (worker)
**Status**: **DONE** — 2026-04-22 · ruff + mypy clean

---

### Tasks

#### T-C-2-01: S6 — Implement `UnresolvedResolutionWorker`

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-02, T-C-1-03, T-C-1-04, T-B-1-01, T-B-1-02]
**blocks**: [T-C-2-02, T-C-3-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/workers/unresolved_resolution_worker.py` (NEW)

**What to build**:
A periodic polling worker that processes UNRESOLVED entity mentions in two phases.

**Entities / Components**:
- **Name**: `UnresolvedResolutionWorker`
  - **Purpose**: Re-resolve entity mentions that fell below the AUTO_RESOLVE threshold in Block 9
  - **Key attributes**:
    - `_session_factory: async_sessionmaker[AsyncSession]`
    - `_settings: Settings`  # from nlp_pipeline.config
    - `_usage_logger: LlmUsageLogProtocol | None`
    - `_ollama_client: httpx.AsyncClient` (for Qwen2.5:3b)
    - `_entity_mention_repo: EntityMentionRepository`
  - **Key methods**:
    - `async def run_once(self) -> WorkerStats`
    - `async def run_loop(self) -> None` (infinite loop with sleep)
    - `async def recover_stale_escalated(self) -> int` (called at startup)
    - `async def _phase1_cascade(self, mention: EntityMentionModel) -> bool`
    - `async def _phase2_llm_classify(self, mentions: list[EntityMentionModel]) -> None`

**Logic & Behavior** (step-by-step):

**Startup** (called before `run_loop`):
1. Call `recover_stale_escalated()` — UPDATE entity_mentions SET resolution_outcome='unresolved' WHERE resolution_outcome='escalated' AND resolution_processed_at < utc_now() - interval '30 minutes'`; log count recovered

**`run_once()` flow**:
1. Fetch batch: `mention_repo.get_unresolved_batch(batch_size=settings.unresolved_resolution_batch_size, lookback_days=settings.unresolved_resolution_lookback_days)` — `FOR UPDATE SKIP LOCKED`
2. Mark all fetched mentions as 'escalated' atomically (UPDATE before releasing the lock — within the same transaction)
3. Commit
4. **Phase 1** — for each mention, run the free cascade re-run:
   - Import and call `EntityResolutionBlock._attempt_cascade_resolution(mention)` (the existing 4-stage cascade from entity_resolution.py)
   - If cascade resolves (score ≥ AUTO_RESOLVE threshold): mark `resolution_outcome='auto_resolved'`, set `resolved_entity_id`
   - Collect mentions where Phase 1 DID NOT resolve → `unresolved_after_phase1`
5. **Phase 2** — filter `unresolved_after_phase1` for entity-creating mention classes: `MentionClass.ORGANIZATION`, `MentionClass.FINANCIAL_INSTRUMENT`, `MentionClass.PERSON`, `MentionClass.FINANCIAL_INSTITUTION`, `MentionClass.GOVERNMENT_BODY`, `MentionClass.REGULATORY_BODY` (PRD §3, A-8)
   - Non-eligible classes (`MentionClass.LOCATION`, `MentionClass.COMMODITY`, `MentionClass.INDEX`, `MentionClass.CURRENCY`, `MentionClass.MACROECONOMIC_INDICATOR`): mark directly as `noise`, reason=`"non_entity_creating_class"`
   - For eligible classes: build classification prompt and call Qwen2.5:3b via Ollama:
     ```
     Classify whether the following mention refers to a real-world entity
     (organization, person, government, or product) that would have its own
     Wikipedia article. Surface: "{mention.surface_form}". Context: "{mention.context[:200]}".
     Respond with JSON: {"is_entity": true/false, "reason": "..."}.
     ```
   - Parse JSON response; if `is_entity=True`: mark `resolution_outcome='entity_created'`; insert into `provisional_entity_queue` (same logic as existing Block 9 _insert_provisional)
   - If `is_entity=False`: mark `resolution_outcome='noise'`, store reason from LLM response
6. Log `LlmCallUsage` via `_usage_logger.log(...)` for each Qwen batch call
7. Commit all changes
8. Return `WorkerStats(processed=N, auto_resolved=M, entity_created=K, noise=J, errors=E)`

**`run_loop()` flow**:
- Infinite: `while True: await run_once(); await asyncio.sleep(settings.unresolved_resolution_interval_s)`
- On exception in `run_once()`: log error, sleep poll_interval, continue (never crash loop)

**Idempotency**:
- `FOR UPDATE SKIP LOCKED` ensures no two worker instances process the same mention
- If worker crashes mid-batch, mentions remain 'escalated'; `recover_stale_escalated()` resets them on next startup
- `provisional_entity_queue` has UNIQUE(normalized_surface, mention_class) — ON CONFLICT DO NOTHING (existing behaviour)

**Error classification** (`resolution_outcome` on Ollama failure):
- Ollama unavailable: mentions remain 'escalated' (not promoted to noise); set error log + sleep
- JSON parse failure: retry up to 1 time with a simplified prompt; on second failure: mark `resolution_outcome='unresolved'` (not noise), log warning

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_run_once_phase1_resolves` | Mention resolved by cascade → outcome='auto_resolved' | unit |
| `test_run_once_phase2_entity_created` | Qwen says is_entity=True → outcome='entity_created' | unit |
| `test_run_once_phase2_noise` | Qwen says is_entity=False → outcome='noise', reason stored | unit |
| `test_run_once_non_eligible_class_noise` | `MentionClass.LOCATION` → noise directly (no LLM call) | unit |
| `test_recover_stale_escalated` | Mentions stuck as 'escalated' >30min reset to 'unresolved' | unit |
| `test_run_loop_continues_on_exception` | Exception in run_once does not crash loop | unit |
| `test_llm_call_logged_on_phase2` | usage_logger.log() called exactly once per batch | unit |
| `test_json_parse_failure_leaves_unresolved` | Malformed JSON → mention stays unresolved, not noise | unit |

**Acceptance criteria**:
- [ ] Phase 1 uses existing cascade logic (no duplication)
- [ ] Phase 2 only calls Ollama for ORGANIZATION, FINANCIAL_INSTRUMENT, PERSON, FINANCIAL_INSTITUTION, GOVERNMENT_BODY, REGULATORY_BODY
- [ ] Stale-lock recovery runs on startup (called from wire-up in T-C-2-02)
- [ ] `asyncio.sleep` used between polls (not `time.sleep`)
- [ ] All 8 tests pass
- [ ] mypy passes

---

#### T-C-2-02: S6 — Wire up `UnresolvedResolutionWorker` in service container

**Type**: impl
**depends_on**: [T-C-1-04, T-C-2-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/main.py` (MODIFY)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/container.py` (MODIFY, if DI container exists)

**What to build**:
- Instantiate `UnresolvedResolutionWorker` with session factory, settings, and `NlpUsageLogRepository`
- Call `await worker.recover_stale_escalated()` on application startup (before `run_loop`)
- Schedule `worker.run_loop()` as a background `asyncio.Task` in the FastAPI lifespan context manager

**Logic**:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    unresolved_worker = UnresolvedResolutionWorker(
        session_factory=session_factory,
        settings=settings,
        usage_logger=NlpUsageLogRepository(session_factory),
    )
    await unresolved_worker.recover_stale_escalated()
    worker_task = asyncio.create_task(unresolved_worker.run_loop())
    yield
    worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await worker_task
    # ... existing shutdown ...
```

**Acceptance criteria**:
- [ ] Worker task created and cancelled gracefully on shutdown
- [ ] `recover_stale_escalated()` called before `run_loop()`
- [ ] Worker not started if `not settings.unresolved_resolution_enabled` (primary disable switch)
- [ ] mypy passes

---

#### T-C-2-03: S6 — Integration tests for `UnresolvedResolutionWorker`

**Type**: test
**depends_on**: [T-C-2-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/tests/integration/test_unresolved_resolution_worker.py` (NEW)

**What to build**:
Integration tests using a real Postgres test database (via `pytest-asyncio` + `sqlalchemy` test fixtures).

**Tests to write**:
| Test Name | Infrastructure | What It Verifies |
|-----------|---------------|-----------------|
| `test_worker_processes_batch_end_to_end` | Postgres | Insert 5 unresolved mentions; run_once(); assert 5 outcomes set |
| `test_worker_skips_already_escalated` | Postgres | Escalated mention not picked up by second worker instance (SKIP LOCKED) |
| `test_stale_recovery_resets_escalated` | Postgres | Insert escalated mention with processed_at 60min ago; recover_stale_escalated() resets it |
| `test_worker_handles_empty_batch` | Postgres | run_once() with no unresolved rows completes without error |

**Acceptance criteria**:
- [ ] Tests use real DB (no mocks for DB layer)
- [ ] All 4 integration tests pass
- [ ] Tests clean up after themselves (truncate tables in teardown)

---

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/entity_resolution.py` (cascade logic to reuse)
- `services/nlp-pipeline/src/nlp_pipeline/application/workers/` (existing worker patterns)
- `services/nlp-pipeline/src/nlp_pipeline/main.py`
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment.py` (Worker 13E for reference pattern)

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/` passes
- [ ] `mypy services/nlp-pipeline/` passes
- [ ] All 8 unit tests pass
- [ ] All 4 integration tests pass (requires Postgres)
- [ ] Worker shuts down gracefully (no asyncio warnings on cancellation)

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None | Wave 4 only adds new files and modifies main.py lifespan | — |

### Regression Guardrails
- **BP-170**: After this wave, UNRESOLVED mentions DO have a re-resolution pathway — guard: assert that `run_once()` with an empty DB completes cleanly (test_worker_handles_empty_batch)
- **BP-171**: ON CONFLICT DO NOTHING for provisional_entity_queue is INTENTIONAL — mention linkage gap is a known trade-off (documented in ADR-B of PRD-0029); do not change this behaviour
- **BP-001**: Worker must not use `asyncio.sleep(0)` in tight loops — use `settings.unresolved_resolution_interval_s` (minimum 60; default 1800)
- **BP-025**: Ollama HTTP call — use a configured timeout (default 30s); never wait indefinitely

---

## Wave 5: Internal Cost Endpoints + S9 Admin Aggregation ✅

**Goal**: Expose `GET /internal/v1/llm-costs` on S6, S7, S8; aggregate them on S9 `GET /api/v1/admin/llm-costs` with parallel fan-out.
**Depends on**: Wave 3 (repositories must exist), Wave 4 (S6 worker and usage logging must be wired)
**Estimated effort**: 45–60 minutes
**Architecture layer**: API
**Status**: **DONE** — 2026-04-22 · 18 tests pass (4 S6 + 4 S7 + 4 S8 + 6 S9) · ruff + mypy clean

---

### Tasks

#### T-C-3-01: S6 — `GET /internal/v1/llm-costs` endpoint

**Type**: impl
**depends_on**: [T-C-1-03, T-B-1-02]
**blocks**: [T-F-1-01]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routers/internal_costs.py` (NEW)
- `services/nlp-pipeline/src/nlp_pipeline/api/routers/__init__.py` (MODIFY — register router)

**What to build**:
```
GET /internal/v1/llm-costs?period=2026-04&provider=all&breakdown=provider
```

**Request query params**:

| Param | Type | Default | Validation |
|-------|------|---------|-----------|
| `period` | string | current UTC month | `YYYY-MM` format; reject other formats with 400 |
| `provider` | string | `all` | `all \| deepinfra \| openrouter \| gemini \| ollama` |
| `breakdown` | string | `provider` | `provider \| capability \| day` |

**Response** (200) — same structure as PRD §6.2 breakdown array:
```json
{
  "service": "nlp-pipeline",
  "period": "2026-04",
  "total_estimated_cost_usd": 0.042,
  "total_calls": 312,
  "total_tokens_in": 450000,
  "total_tokens_out": 48000,
  "success_rate": 0.997,
  "breakdown": [
    {
      "dimension": "ollama",
      "calls": 312,
      "tokens_in": 450000,
      "tokens_out": 48000,
      "estimated_cost_usd": 0.0,
      "success_rate": 0.997
    }
  ]
}
```

**Auth**: Internal endpoint — validate `X-Internal-JWT` header (same pattern as all other internal endpoints in S6)

**Query** (on `nlp_db.llm_usage_log`, breakdown=provider example):
```sql
SELECT provider AS dimension,
       COUNT(*) AS calls,
       SUM(tokens_in) AS tokens_in,
       SUM(tokens_out) AS tokens_out,
       SUM(estimated_cost_usd) AS estimated_cost_usd,
       AVG(success::int) AS success_rate
FROM llm_usage_log
WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC') = DATE_TRUNC('month', :period_date::date)
  AND (:provider = 'all' OR provider = :provider)
GROUP BY dimension
ORDER BY estimated_cost_usd DESC;
```

For `breakdown=day`: group by `DATE(created_at AT TIME ZONE 'UTC')` as dimension.
For `breakdown=capability`: group by `capability` as dimension.

**Use case**: Implement as a read-only use case class `GetNlpLlmCostsUseCase` (R25 compliance — router imports only use case, not repository directly). Use `ReadOnlyUnitOfWork` (R27).

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_llm_costs_200` | Returns 200 with correct structure for `breakdown=provider` | unit (mock use case) |
| `test_get_llm_costs_default_period_is_current_month` | Omitting `period` → uses current UTC month | unit |
| `test_get_llm_costs_invalid_period_400` | `period=not-a-month` → 400 | unit |
| `test_get_llm_costs_requires_jwt` | No X-Internal-JWT → 401 | unit |

**Acceptance criteria**:
- [ ] Endpoint requires valid internal JWT
- [ ] `period` validated as `YYYY-MM`; 400 on invalid format
- [ ] Response matches structure above
- [ ] Router imports only `GetNlpLlmCostsUseCase` (R25); use case uses `ReadOnlyUnitOfWork` (R27)
- [ ] All 4 tests pass

---

#### T-D-2-01: S7 — `GET /internal/v1/llm-costs` endpoint

**Type**: impl
**depends_on**: [T-D-1-02, T-B-1-04]
**blocks**: [T-F-1-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/routers/internal_costs.py` (NEW)
- `services/knowledge-graph/src/knowledge_graph/api/routers/__init__.py` (MODIFY)

**What to build**:
Identical structure to T-C-3-01 but queries `intelligence_db.llm_usage_log` with `service_name='knowledge-graph'` filter.

**Response**: Same schema as S6 but `"service": "knowledge-graph"`

**Query** (same structure as T-C-3-01; add WHERE filter for service isolation):
```sql
WHERE DATE_TRUNC('month', created_at AT TIME ZONE 'UTC') = DATE_TRUNC('month', :period_date::date)
  AND service_name = 'knowledge-graph'
  AND (:provider = 'all' OR provider = :provider)
```

**Tests to write**: Same 4 tests as T-C-3-01, targeting S7 router.

**Acceptance criteria**:
- [ ] Filters by `service_name='knowledge-graph'` (intelligence_db is shared with S6 and potentially S7)
- [ ] Identical response structure to S6 endpoint
- [ ] Uses `ReadOnlyUnitOfWork` (R27)
- [ ] 4 tests pass

---

#### T-E-2-01: S8 — `GET /internal/v1/llm-costs` endpoint

**Type**: impl
**depends_on**: [T-E-1-01, T-B-1-03]
**blocks**: [T-F-1-01]
**Target files**:
- `services/rag-chat/src/rag_chat/api/routers/internal_costs.py` (NEW)
- `services/rag-chat/src/rag_chat/api/routers/__init__.py` (MODIFY)

**What to build**:
Same structure as T-C-3-01, queries `rag_chat_db.llm_usage_log`. No `service_name` filter needed (rag_chat_db is owned exclusively by S8).

**Tests to write**: Same 4 tests targeting S8 router.

**Acceptance criteria**:
- [ ] 4 tests pass
- [ ] Queries rag_chat_db (not intelligence_db or nlp_db)
- [ ] Uses `ReadOnlyUnitOfWork` (R27)

---

#### T-F-1-01: S9 — `GET /api/v1/admin/llm-costs` aggregation endpoint

**Type**: impl
**depends_on**: [T-C-3-01, T-D-2-01, T-E-2-01]
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/api/routers/admin_costs.py` (NEW)
- `services/api-gateway/src/api_gateway/api/routers/__init__.py` (MODIFY)
- `services/api-gateway/src/api_gateway/application/use_cases/get_llm_costs.py` (NEW)

**What to build**:
```
GET /api/v1/admin/llm-costs?period=2026-04&service=all&provider=all&breakdown=provider
```

**Auth**: Requires admin JWT (check `role=admin` in the internal JWT claims). Return 403 if non-admin.

**Request query params**: Forward directly from PRD §6.2 — `period (YYYY-MM)`, `service (all|nlp-pipeline|rag-chat|knowledge-graph)`, `provider (all|...)`, `breakdown (provider|capability|service|day)`. 400 on invalid period format.

**Logic** (in `GetLlmCostsUseCase`):
1. Determine which services to query (all 3 by default, or just the filtered one)
2. Fan out `httpx.AsyncClient.get()` calls in parallel with 5s timeout per call:
   ```python
   results = await asyncio.gather(
       _fetch_service_costs(settings.nlp_pipeline_url, period, provider, breakdown, headers),
       _fetch_service_costs(settings.knowledge_graph_url, period, provider, breakdown, headers),
       _fetch_service_costs(settings.rag_chat_url, period, provider, breakdown, headers),
       return_exceptions=True,
   )
   ```
   Uses **existing** `settings.nlp_pipeline_url` (`http://localhost:8006`), `settings.knowledge_graph_url` (`http://localhost:8007`), `settings.rag_chat_url` (`http://localhost:8008`) — **no new config vars needed**.
3. For each result:
   - If `Exception` or HTTP error: add to `services_failed`
   - If successful: merge into aggregated breakdown
4. Aggregate: `total_estimated_cost_usd = sum(r.total_estimated_cost_usd for r in successful)`; merge `breakdown[]` by dimension; compute aggregate `success_rate` and token totals
5. If ALL services failed → 503; if partial → 200 with `services_failed` populated

**Response** (200) — matches PRD §6.2 exactly:
```json
{
  "period": "2026-04",
  "total_estimated_cost_usd": 0.183,
  "total_calls": 359,
  "total_tokens_in": 2400000,
  "total_tokens_out": 380000,
  "success_rate": 0.995,
  "breakdown": [
    {"dimension": "gemini", "calls": 47, "tokens_in": 1950000, "tokens_out": 330000, "estimated_cost_usd": 0.183, "success_rate": 0.98},
    {"dimension": "ollama", "calls": 312, "tokens_in": 450000, "tokens_out": 48000, "estimated_cost_usd": 0.0, "success_rate": 1.0}
  ],
  "services_queried": ["nlp-pipeline", "knowledge-graph", "rag-chat"],
  "services_failed": []
}
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_admin_costs_200_all_services_healthy` | All 3 services respond → merged breakdown, correct totals | unit (mock httpx) |
| `test_admin_costs_200_one_service_degraded` | One service fails → 200 with `services_failed` populated | unit |
| `test_admin_costs_requires_admin_role` | Non-admin JWT → 403 | unit |
| `test_admin_costs_invalid_period_400` | `period=badformat` → 400 | unit |
| `test_admin_costs_all_services_down_503` | All 3 services fail → 503 | unit |
| `test_admin_costs_total_cost_sum_correct` | `total_estimated_cost_usd` = sum of per-service totals | unit |

**Acceptance criteria**:
- [ ] Fan-out uses `asyncio.gather(return_exceptions=True)` with 5s timeout per service
- [ ] Uses **existing** `settings.nlp_pipeline_url`, `settings.knowledge_graph_url`, `settings.rag_chat_url` — no new config vars
- [ ] HTTP 200 returned when at least one service responds; 503 when all fail
- [ ] 403 for non-admin; 401 for no JWT; 400 for invalid period
- [ ] `period`, `provider`, `breakdown` forwarded to each internal endpoint in query params
- [ ] Router imports only `GetLlmCostsUseCase` (R25); use case is read-only (no DB writes, R27)
- [ ] All 6 tests pass

---

### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/api/routers/` (existing router patterns)
- `services/api-gateway/src/api_gateway/application/use_cases/` (existing use case patterns with internal HTTP calls)
- `services/api-gateway/src/api_gateway/config.py` — note existing `nlp_pipeline_url` (8006), `knowledge_graph_url` (8007), `rag_chat_url` (8008); no new URL vars needed
- `services/nlp-pipeline/src/nlp_pipeline/api/routers/` (existing internal endpoint pattern)
- `services/knowledge-graph/src/knowledge_graph/api/routers/` (existing internal endpoint pattern)

### Validation Gate
- [ ] `ruff check` passes on S6, S7, S8, S9
- [ ] `mypy` passes on all 4 services
- [ ] All endpoint tests pass (≥18 new tests across all 4 services)
- [ ] S9 admin endpoint returns HTTP 200 when ≥1 service responds; 503 when all fail
- [ ] Admin role check enforced (403 for non-admin)
- [ ] `period=YYYY-MM` validation enforced (400 on bad format) in all 4 endpoints
- [ ] S9 uses existing `settings.nlp_pipeline_url` / `knowledge_graph_url` / `rag_chat_url`

### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/api-gateway/src/api_gateway/config.py` | No change needed — `nlp_pipeline_url`, `knowledge_graph_url`, `rag_chat_url` already exist | — |
| `services/api-gateway/tests/api/test_admin_costs.py` | New file — must be created | Covered by T-F-1-01 test tasks |

### Regression Guardrails
- **BP-025**: Fan-out httpx calls must have a timeout (suggest 5s per service call); `asyncio.gather(return_exceptions=True)` must be used — never `asyncio.gather()` without it
- **R25**: S9 router must not import from `infrastructure/` directly — only from `application/use_cases/`
- **R27**: `GetLlmCostsUseCase` is read-only — must use `ReadOnlyUnitOfWork` (no DB writes in this use case)

---

## Cross-Cutting Concerns

### Contract Changes
- No Avro schema changes in this plan
- `GET /internal/v1/llm-costs` is a new internal REST contract (not in existing API gateway swagger) — must be documented in `docs/services/nlp-pipeline.md`, `docs/services/knowledge-graph.md`, `docs/services/rag-chat.md`
- `GET /api/v1/admin/llm-costs` must be added to `docs/services/api-gateway.md`

### Migration Needs
| Service | DB | Migration | Direction | Alembic Head Before |
|---------|-----|-----------|-----------|-------------------|
| S6 (nlp-pipeline) | nlp_db | 0007_add_resolution_outcome | forward | 0006 |
| S6 (nlp-pipeline) | nlp_db | 0008_create_llm_usage_log | forward | 0007 |
| S8 (rag-chat) | rag_chat_db | 0003_create_llm_usage_log | forward | 0002 |
| S7 (knowledge-graph) | intelligence_db | 0006_extend_llm_usage_log | forward | 0005 |

All four migrations are in separate databases — no ordering dependency between them.

### Event Flow Changes
- No new Kafka topics introduced
- `UnresolvedResolutionWorker` produces to `provisional_entity_queue` table (existing pattern from Block 9); existing Worker 13E in S7 consumes this queue — no change to Worker 13E required

### Configuration Changes

All S6 vars use `NLP_PIPELINE_` prefix (e.g. `NLP_PIPELINE_UNRESOLVED_RESOLUTION_ENABLED`).
S9 needs **no new env vars** — existing `nlp_pipeline_url`, `knowledge_graph_url`, `rag_chat_url` are reused.

| Service | Env Var (with prefix) | Default | Description |
|---------|----------------------|---------|-------------|
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_ENABLED` | `true` | Master on/off switch |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_INTERVAL_S` | `1800` | Poll frequency in seconds (30 min) |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_BATCH_SIZE` | `500` | Rows per poll cycle |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_LOOKBACK_DAYS` | `90` | Max age of mentions to re-process |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_LLM_TIMEOUT_S` | `10.0` | Ollama per-call timeout (s) |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_LLM_RETRIES` | `2` | Ollama retries before giving up |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_STALE_ESCALATED_MINUTES` | `30` | Stale lock recovery threshold |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama endpoint |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_CLASSIFICATION_MODEL` | `qwen2.5:3b` | Ollama model for noise classification |
| S6 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_MAX_LLM_BATCH` | `20` | Max mentions per Ollama call |

These must be added to `infra/docker/dev.local.env.example` (or the project's equivalent env example file).

### Documentation Updates
- `docs/services/nlp-pipeline.md` — add `UnresolvedResolutionWorker` section, new endpoint, new config vars
- `docs/services/knowledge-graph.md` — add new internal endpoint, refactored FallbackChainClient note
- `docs/services/rag-chat.md` — add new internal endpoint, cost logging note
- `docs/services/api-gateway.md` — add `GET /api/v1/admin/llm-costs` to endpoint list
- `services/nlp-pipeline/.claude-context.md` — note UnresolvedResolutionWorker + new worker config vars

---

## Risk Assessment

### Critical Path
```
Wave 1 (libs, ~40min) → Wave 2 (migrations, ~40min) → Wave 3 (domain+refactor+adapter, ~75min) → Wave 4 (worker, ~75min) → Wave 5 (endpoints, ~55min)
```
Total estimated: ~5 hours of agent work. The critical path runs through Wave 4 (`UnresolvedResolutionWorker`) as it has the most complex logic and most tests.

### Highest Risk: Wave 4 (`UnresolvedResolutionWorker`)
- **Risk 1 — Cascade reuse**: Phase 1 imports from `entity_resolution.py`; if those functions are not easily importable (e.g., bound to a class instance), the agent may need to extract the cascade logic into a shared utility. Read `entity_resolution.py` carefully before implementing.
- **Risk 2 — Ollama availability**: Integration tests in Wave 4 that call Ollama require the Ollama container running. Tests should be skipped if Ollama is not available (`pytest.mark.skipif`), with a note in the test file.
- **Risk 3 — Stale lock recovery timing**: The 30-minute threshold is a constant in config; if tests use a real DB, they cannot wait 30 minutes — tests must manipulate `resolution_processed_at` directly.

### Rollback Strategy
- **Wave 1**: No DB changes — delete new files in `libs/ml-clients`, revert `__init__.py`
- **Wave 2**: Run `alembic downgrade -1` per service; all migrations are reversible
- **Wave 3**: Revert `fallback_chain.py` change (git revert); delete new repository files
- **Wave 4**: Delete `unresolved_resolution_worker.py`; remove lifespan wiring from `main.py`
- **Wave 5**: Delete router files; revert `__init__.py` registrations

If a partial rollback is needed, waves can be rolled back independently since each wave depends on the prior one (rollback in reverse order: 5 → 4 → 3 → 2 → 1).

### Testing Gaps
- **Ollama Qwen2.5:3b**: Phase 2 LLM classification requires Ollama running locally. Unit tests mock the HTTP call; no full E2E test is required for this plan (existing E2E test suite covers the broader pipeline).
- **DeepInfra streaming**: Token extraction from final SSE chunk requires a real DeepInfra response. Unit tests use a mock response fixture; no live DeepInfra call in tests.
- **S9 admin aggregation**: Fan-out tests use mock httpx — no real service-to-service call tested in this plan. The inter-service contract is tested via S9's internal HTTP call unit tests.

---

## Task Summary

| Wave | Tasks | Services | Effort |
|------|-------|---------|--------|
| 1 — Shared library | T-A-1-01, T-A-1-02, T-A-1-03 | libs/ml-clients | 30–45 min |
| 2 — DB Migrations | T-B-1-01, T-B-1-02, T-B-1-03, T-B-1-04 | S6, S8, S7 | 30–45 min |
| 3 — Domain + Refactor + Adapter | T-C-1-01..04, T-D-1-01..03, T-E-1-01..02 | S6, S7, S8, libs/ml-clients | 75–105 min |
| 4 — Worker | T-C-2-01, T-C-2-02, T-C-2-03 | S6 | 60–90 min |
| 5 — Endpoints | T-C-3-01, T-D-2-01, T-E-2-01, T-F-1-01 | S6, S7, S8, S9 | 45–60 min |
| **Total** | **23 tasks** | **4 services + 1 lib** | **~5–6 hours** |

**Recommended execution order**: Waves 1 and 2 can be started in parallel (Wave 2 has no code dependency on Wave 1's protocol for the migration SQL itself). Wave 3 requires both Wave 1 (protocol import) and Wave 2 (migration columns for ORM). Waves 4 and 5 are strictly sequential after Wave 3.
