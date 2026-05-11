# PLAN-0073 — Isolated Node Enrichment

> **PRD**: `docs/specs/0073-isolated-node-enrichment.md`
> **Created**: 2026-05-05
> **Status**: completed
> **Updated**: 2026-05-05
> **Total Waves**: 9 (A-1 ✅, B-0 ✅, B-1 ✅, B-2 ✅, C-1 ✅, C-2 ✅, C-3 ✅, D-1 ✅)

---

## Overview

Implements Worker 13J (`StructuredEnrichmentWorker`) to reduce isolated node rate from ~68% to <20% within 72 h of first periodic sweep. Enriches canonical entities via a three-source cascade: S3 existing DB data → S3 on-demand EODHD profile → LLM generation. Exposes enrichment fields (`description`, `metadata`, `data_completeness`, `enriched_at`) through `GET /api/v1/entities/{entity_id}`.

### Sub-Plan Decomposition

| Sub-Plan | Service | Scope | Waves |
|----------|---------|-------|-------|
| **A** | intelligence-migrations | Migrations 0024–0027 (DDL + seed data) | A-1 |
| **B** | S3 market-data | `securities.description` migration + new `/lookup` and `/on-demand-profile` endpoints | B-0, B-1, B-2 |
| **C** | S7 knowledge-graph | Domain entities, port, use case, Worker 13J, API extension | C-1, C-2, C-3 |
| **D** | S9 api-gateway + worldview-web | S9 proxy route + frontend description panel | D-1 |

### Dependency Graph

```
Sub-Plan A (migrations)
    │
    └─► Sub-Plan C (S7 Worker 13J + use case)
              │
              └─► Sub-Plan D (S9 proxy + frontend)

Sub-Plan B Wave B-0 (securities.description migration)
    │
    └─► Sub-Plan B Wave B-1 (S3 new endpoints) ──► Sub-Plan C (MarketDataClient uses B's endpoints)
```

**Execution order**: A → B-0 → B-1 (B can run in parallel with A after A-1 is committed) → C → D

### Pre-Flight Gate (Verified)

| Check | Result |
|-------|--------|
| No blocking open questions in PRD §18 | PASS — OQ-001..OQ-005 all DEFERRED (non-blocking) |
| External API fields verified | PASS — EODHD `General.Description/Sector/Industry/Country/Exchange` all confirmed real fields |
| No cross-plan DDL conflicts | PASS — PLAN-0072 occupies 0020–0023; PLAN-0073 starts at 0024 |
| PRD recency | PASS — PRD-0073 v1.0 dated 2026-05-05 (today) |
| Architecture compliance | PASS — no RULES.md violations |

### Codebase State Verification

| PRD Reference | Type | Service | Actual Current State | PRD Expected State | Delta |
|--------------|------|---------|---------------------|--------------------|-------|
| `canonical_entities.description` | DB column | intelligence-migrations | Does NOT exist | TEXT NULL | Add in 0024 |
| `canonical_entities.data_completeness` | DB column | intelligence-migrations | Does NOT exist | DOUBLE PRECISION NULL | Add in 0024 |
| `canonical_entities.enriched_at` | DB column | intelligence-migrations | Does NOT exist | TIMESTAMPTZ NULL | Add in 0024 |
| `canonical_entities.enrichment_attempts` | DB column | intelligence-migrations | Does NOT exist | INTEGER NOT NULL DEFAULT 0 | Add in 0024 |
| `canonical_entities.metadata` | DB column | intelligence-migrations | EXISTS (migration 0001) | Already present | No-op |
| `relation_type_registry.data_source` | DB column | intelligence-migrations | Does NOT exist | TEXT NULL | Add in 0025 |
| `relation_type_registry.source_field` | DB column | intelligence-migrations | Does NOT exist | TEXT NULL | Add in 0025 |
| `relations.relation_source` | DB column | intelligence-migrations | Does NOT exist | TEXT NULL (partitioned ×8) | Add in 0026 |
| `GET /api/v1/instruments/lookup` | S3 endpoint | market-data | Does NOT exist | New flexible lookup | Create in B-1 |
| `GET /api/v1/instruments/on-demand-profile` | S3 endpoint | market-data | Does NOT exist | New on-demand EODHD | Create in B-1 |
| `GET /api/v1/entities/{entity_id}` | S7 endpoint | knowledge-graph | Does NOT exist | New entity detail route | Create in C-3 |
| `EnrichmentResult` | Domain entity | knowledge-graph | Does NOT exist | New value object | Create in C-1 |
| `EntityEnrichmentPort` | App port | knowledge-graph | Does NOT exist | New Protocol | Create in C-1 |
| `StructuredEnrichmentUseCase` | Use case | knowledge-graph | Does NOT exist | New use case | Create in C-2 |
| `StructuredEnrichmentWorker` | Worker | knowledge-graph | Does NOT exist | New APScheduler + consumer | Create in C-2 |
| `enrichment_llm_model_id` | Config | knowledge-graph | Reuses existing `description_deepinfra_model_id` | (consolidated in QA pass-1, F-A04) | No new field — Worker 13J shares the description model with Worker 13E |
| `EntityPublic` schema | Schema | knowledge-graph | Does NOT exist | New Pydantic model | Create in C-3 |
| `GET /api/v1/entities/{entity_id}` | S9 proxy | api-gateway | Does NOT exist | New proxy to S7 | Create in D-1 |

---

## Sub-Plan A — intelligence-migrations (DDL Waves)

### Wave A-1: Migrations 0022–0024 ✅

**Goal**: Add 4 columns to `canonical_entities`, 2 columns to `relation_type_registry`, 1 column to `relations`, and seed EODHD relation-type source mappings.

**Depends on**: Sub-Plan C Wave C-1 is not needed first — migrations can be applied independently. However, implementation in S7 cannot use the columns until this wave is merged.

**Estimated effort**: 30–45 min

**Status**: **DONE** — 2026-05-05 · 10 new tests · ruff + mypy clean · chain 0021→0022→0023→0024 verified

**Architecture layer**: infrastructure (DDL only)

#### Pre-read (agent must read before starting)

- `services/intelligence-migrations/alembic/versions/0019_add_evidence_text_to_relation_evidence_raw.py` — understand the current head revision and Alembic patterns used
- `services/intelligence-migrations/alembic/env.py` — understand migration environment
- `docs/specs/0073-isolated-node-enrichment.md` §8 — exact column specs

#### Tasks

---

##### T-A-1-01: Migration 0024 — Add Enrichment Fields to `canonical_entities`

**Type**: schema
**depends_on**: none
**blocks**: [T-A-1-02, T-A-1-03]
**Target files**:
- `services/intelligence-migrations/alembic/versions/0024_add_enrichment_fields_to_canonical_entities.py` (create)

**PRD reference**: §8.1, §16

**What to build**:
Alembic migration that adds 4 new columns to `canonical_entities` and creates a partial index to support the periodic sweep query. The `CREATE INDEX CONCURRENTLY` MUST run outside a transaction using `autocommit_block()`.

**Columns to add**:
| Column | PostgreSQL Type | Nullable | Default |
|--------|-----------------|----------|---------|
| `description` | `TEXT` | YES | `NULL` |
| `data_completeness` | `DOUBLE PRECISION` | YES | `NULL` |
| `enriched_at` | `TIMESTAMPTZ` | YES | `NULL` |
| `enrichment_attempts` | `INTEGER` | NO | `0` |

**Index** (outside transaction):
```sql
CREATE INDEX CONCURRENTLY ix_canonical_entities_enrichment_sweep
ON canonical_entities (enrichment_attempts, enriched_at)
WHERE enrichment_attempts < 3;
```

**Migration pattern** (use `autocommit_block` for CONCURRENTLY):
```python
def upgrade() -> None:
    op.add_column("canonical_entities", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("canonical_entities", sa.Column("data_completeness", sa.Double(), nullable=True))
    op.add_column("canonical_entities", sa.Column("enriched_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("canonical_entities", sa.Column("enrichment_attempts", sa.Integer(), nullable=False, server_default="0"))

    # CONCURRENTLY cannot run inside a transaction
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_canonical_entities_enrichment_sweep "
            "ON canonical_entities (enrichment_attempts, enriched_at) "
            "WHERE enrichment_attempts < 3"
        )

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_canonical_entities_enrichment_sweep")
    op.drop_column("canonical_entities", "enrichment_attempts")
    op.drop_column("canonical_entities", "enriched_at")
    op.drop_column("canonical_entities", "data_completeness")
    op.drop_column("canonical_entities", "description")
```

**Downstream test impact**:
- Any test that calls `SELECT *` or constructs `canonical_entities` row dicts will gain 4 new columns. Tests using `INSERT INTO canonical_entities` with explicit column lists are unaffected (forward-compat design). Search `tests/` for `canonical_entities` INSERT patterns if they break.

**Acceptance criteria**:
- [ ] Migration applies cleanly against `intelligence_db` (alembic upgrade head)
- [ ] `alembic downgrade -1` succeeds
- [ ] All 4 columns present after upgrade; absent after downgrade
- [ ] Index `ix_canonical_entities_enrichment_sweep` created without locking

---

##### T-A-1-02: Migration 0025 — Add Source Fields to `relation_type_registry` + Seed Data

**Type**: schema
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/intelligence-migrations/alembic/versions/0025_add_source_fields_to_relation_type_registry.py` (create)

**PRD reference**: §8.2, §16

**What to build**:
Add `data_source TEXT NULL` and `source_field TEXT NULL` to `relation_type_registry` **and seed the 6 EODHD/market-data relation type mappings in the same migration** (no separate backfill migration since there is no production instance).

```python
EODHD_MAPPINGS = [
    ("OPERATES_IN_SECTOR", "eodhd", "General.Sector"),
    ("OPERATES_IN_INDUSTRY", "eodhd", "General.Industry"),
    ("HEADQUARTERED_IN", "eodhd", "General.Country"),
    ("LISTED_ON", "eodhd", "General.Exchange"),
    ("OPERATES_IN_SECTOR", "market_data", "sector"),
    ("HEADQUARTERED_IN", "market_data", "country"),
]

def upgrade() -> None:
    op.add_column("relation_type_registry", sa.Column("data_source", sa.Text(), nullable=True))
    op.add_column("relation_type_registry", sa.Column("source_field", sa.Text(), nullable=True))
    # Seed EODHD/market-data mappings — idempotent: only updates rows where data_source IS NULL
    for canonical_type, data_source, source_field in EODHD_MAPPINGS:
        op.execute(
            sa.text(
                "UPDATE relation_type_registry "
                "SET data_source = :src, source_field = :field "
                "WHERE canonical_type = :type AND data_source IS NULL"
            ).bindparams(src=data_source, field=source_field, type=canonical_type)
        )

def downgrade() -> None:
    op.drop_column("relation_type_registry", "source_field")
    op.drop_column("relation_type_registry", "data_source")
```

**Acceptance criteria**:
- [ ] Migration applies and downgrades cleanly
- [ ] Both columns present after upgrade; absent after downgrade
- [ ] 6 relation type registry rows have correct `data_source`/`source_field` after upgrade
- [ ] Re-running upgrade is idempotent (no double-update)

---

##### T-A-1-03: Migration 0026 — Add `relation_source` to `relations`

**Type**: schema
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/intelligence-migrations/alembic/versions/0026_add_relation_source_to_relations.py` (create)

**PRD reference**: §8.3, §16

**What to build**:
Add `relation_source TEXT NULL` to the partitioned `relations` table. PostgreSQL 16 propagates `ADD COLUMN` to all 8 child partitions automatically. MUST be nullable (no `NOT NULL`) to avoid requiring a default on all existing rows.

```python
def upgrade() -> None:
    op.add_column("relations", sa.Column("relation_source", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("relations", "relation_source")
```

**Acceptance criteria**:
- [ ] Migration applies cleanly
- [ ] `relation_source` column visible on parent table and all 8 child partition tables
- [ ] Existing `relations` rows have `relation_source IS NULL`

---


#### Validation Gate — Wave A-1

- [x] `alembic upgrade head` succeeds end-to-end against a fresh `intelligence_db` (verified chain; integration test requires live Postgres)
- [x] `alembic downgrade base && alembic upgrade head` is idempotent (downgrade logic verified)
- [x] 3 migrations have unique revision IDs (chain: 0021 → 0022 → 0023 → 0024 — verified via import)
- [x] 6 relation type registry rows have correct `data_source`/`source_field` (test_relation_type_registry_eodhd_mappings_seeded)
- [x] No pre-existing tests broken (additive-only DDL; all tests are integration-marked, require live Postgres)
- [x] `ruff check` and `mypy` pass on new migration files

#### Break Impact — Wave A-1

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | Migrations are additive-only; no existing SELECT or INSERT is affected | — |

#### Regression Guardrails — Wave A-1

- **BP-126**: NOT NULL column missing `server_default` → `enrichment_attempts` MUST have `server_default="0"` (already specified). Verify no other new column is NOT NULL without a server_default.
- **BP-007**: `CREATE INDEX CONCURRENTLY` inside Alembic transaction → MUST use `autocommit_block()` pattern (specified in T-A-1-01). Verify migration 0024 does NOT wrap the CONCURRENTLY index in a transaction block.
- **ADR-0073-004**: `relations` is partitioned ×8 — adding a nullable column is safe; MUST NOT add NOT NULL without default.

---

## Sub-Plan B — S3 market-data (Endpoint Refactor + Extension)

### Wave B-0: Market-Data `securities.description` Migration ✅

**Goal**: Add `description TEXT NULL` to the S3 `securities` table so EODHD descriptions can be persisted and subsequently returned by `/lookup?extra_info=true`.

**Depends on**: none (can run in parallel with Sub-Plan A)

**Estimated effort**: 15–20 min

**Status**: **DONE** — 2026-05-05 · ruff + mypy clean

**Architecture layer**: infrastructure (DDL only)

#### Tasks

---

##### T-B-0-01: Alembic Migration — Add `description` to `securities`

**Type**: schema
**depends_on**: none
**blocks**: [T-B-1-02]
**Target files**:
- `services/market-data/alembic/versions/<rev>_add_description_to_securities.py` (create)

**PRD reference**: §8.2b, §16

**What to build**:
```python
def upgrade() -> None:
    op.add_column("securities", sa.Column("description", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("securities", "description")
```

**Acceptance criteria**:
- [x] Migration applies and downgrades cleanly
- [x] `description` column present on `securities` table after upgrade

---

### Wave B-1: Unified `/lookup` Endpoint + `/on-demand-profile` with DB Persistence ✅

**Goal**: Consolidate `GET /instruments/symbol/{symbol}` and `GET /instruments/{instrument_id}` into a single `GET /instruments/lookup?symbol=&isin=&id=&extra_info=true` endpoint. Add internal `GET /instruments/on-demand-profile` that persists EODHD results to `securities`. Propagate endpoint changes to S9 and frontend.

**Depends on**: Wave B-0

**Estimated effort**: 90–120 min

**Status**: **DONE** — 2026-05-05 · 25 new unit tests (S3) + 2 S9 test fixes · ruff + mypy clean

**Architecture layer**: API + application + infrastructure

#### Pre-read (agent must read before starting)

- `services/market-data/src/market_data/api/routers/instruments.py` — existing router (endpoints being replaced)
- `services/market-data/src/market_data/api/routers/fundamentals.py` — existing EODHD call pattern
- `services/market-data/src/market_data/api/schemas/instruments.py` — existing `InstrumentResponse` (not changed)
- `services/market-data/src/market_data/application/use_cases/query_instruments.py` — existing use cases being replaced
- `services/market-data/src/market_data/domain/entities.py` — `Instrument` entity already has `sector`, `industry`, `country`, `isin`, `currency_code`, `name` fields
- `services/market-data/src/market_data/infrastructure/eodhd/client.py` — existing EODHD HTTP client
- `services/market-data/.claude-context.md` — service pitfalls and patterns
- `services/api-gateway/src/api_gateway/routers/` — S9 proxy routes that reference old endpoints
- `apps/worldview-web/src/` — frontend code that calls old instrument endpoints
- `docs/specs/0073-isolated-node-enrichment.md` §6.3 — exact endpoint spec

#### Tasks

---

##### T-B-1-01: `InstrumentLookupUseCase` — Unified Lookup with `extra_info` Flag

**Type**: impl
**depends_on**: none
**blocks**: [T-B-1-03]
**Target files**:
- `services/market-data/src/market_data/application/use_cases/lookup_instrument.py` (create)
- `services/market-data/src/market_data/api/schemas/instruments.py` (modify — add `InstrumentLookupResponse`, `InstrumentLookupDetailResponse`)

**PRD reference**: §6.3 (`GET /api/v1/instruments/lookup`)

**What to build**:
A use case that accepts `symbol: str | None`, `isin: str | None`, `id: UUID | None`, `extra_info: bool = False`. Priority: `id > isin > symbol`. Queries `instruments` (base fields always); when `extra_info=True`, also JOINs `securities` for enrichment fields.

**`InstrumentLookupResponse`** (base, no `extra_info`):
```python
class InstrumentLookupResponse(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    is_active: bool
```

**`InstrumentLookupDetailResponse`** (with `extra_info=True`, extends base):
```python
class InstrumentLookupDetailResponse(InstrumentLookupResponse):
    name: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency_code: str | None = None
    description: str | None = None  # from securities.description
```

**Use case logic**:
1. Validate at least one identifier provided (raise `ValueError` if all None)
2. Priority lookup: `id` → `isin` → `symbol` (case-insensitive for symbol)
3. If `extra_info=False`: return `InstrumentLookupResponse`
4. If `extra_info=True`: JOIN `securities` on `instrument.security_id = security.id`; return `InstrumentLookupDetailResponse` with all enrichment fields (nulls accepted when not yet populated)
5. If no row found: raise `InstrumentNotFoundError`

**Tests to write** (in `services/market-data/tests/unit/application/use_cases/test_lookup_instrument.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_lookup_by_id_returns_base` | `id` lookup → `InstrumentLookupResponse` | unit |
| `test_lookup_by_isin_returns_base` | `isin` lookup → `InstrumentLookupResponse` | unit |
| `test_lookup_by_symbol_case_insensitive` | `AAPL` and `aapl` both resolve | unit |
| `test_lookup_priority_id_over_isin` | `id` + `isin` both provided → `id` wins | unit |
| `test_lookup_extra_info_joins_securities` | `extra_info=True` → `InstrumentLookupDetailResponse` with enrichment fields | unit |
| `test_lookup_extra_info_description_null_when_missing` | `extra_info=True` but `securities.description` is NULL → `description=None` in response | unit |
| `test_lookup_no_params_raises` | all None raises `ValueError` | unit |
| `test_lookup_not_found_raises` | no DB row → `InstrumentNotFoundError` | unit |

**Acceptance criteria**:
- [ ] Priority logic correct (`id > isin > symbol`)
- [ ] `extra_info=False` returns only base fields
- [ ] `extra_info=True` JOINs securities and returns all enrichment fields
- [ ] 8 unit tests pass

---

##### T-B-1-02: `OnDemandProfileUseCase` — DB-First → EODHD On-Demand with Persistence

**Type**: impl
**depends_on**: [T-B-0-01]
**blocks**: [T-B-1-03]
**Target files**:
- `services/market-data/src/market_data/application/use_cases/on_demand_profile.py` (create)
- `services/market-data/src/market_data/api/schemas/instruments.py` (modify — add `OnDemandProfileResponse`)

**PRD reference**: §6.3 (`GET /api/v1/instruments/on-demand-profile`)

**What to build**:
Use case that:
1. Tries DB lookup via `InstrumentLookupUseCase(extra_info=True)` — checks if `description` is already populated
2. If DB hit **with description**: returns data with `source="db"`
3. If DB miss OR description is null: calls EODHD `GET /api/v1/{ticker}.json`
4. Extracts: `description` (`General.Description`), `sector`, `industry`, `country`, `exchange`, `isin`, `currency_code`
5. **Persists** to DB: upserts description/sector/industry/country/currency into `securities`; upserts isin/exchange into `instruments` WHERE `securities.description` was null
6. If EODHD returns 404: raises `InstrumentNotFoundError`
7. If EODHD returns 429: propagates as `EodhRateLimitError`
8. Returns with `source="eodhd_persisted"`

**SSRF validation** (before EODHD call):
```python
TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,20}$")
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
```

**`OnDemandProfileResponse`**:
```python
class OnDemandProfileResponse(BaseModel):
    description: str | None
    sector: str | None
    industry: str | None
    country: str | None
    exchange: str | None
    isin: str | None
    ticker: str | None
    currency_code: str | None
    source: Literal["db", "eodhd_persisted"]
```

**Tests to write** (in `services/market-data/tests/unit/application/use_cases/test_on_demand_profile.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_on_demand_db_hit_with_description_returns_db` | DB has description → `source="db"`, EODHD not called | unit |
| `test_on_demand_db_miss_calls_eodhd_and_persists` | DB miss → EODHD called; result upserted into securities | unit |
| `test_on_demand_db_hit_null_description_calls_eodhd` | DB row exists but `description` null → EODHD called | unit |
| `test_on_demand_eodhd_404_raises` | EODHD 404 → `InstrumentNotFoundError` | unit |
| `test_on_demand_eodhd_429_propagates` | EODHD 429 → `EodhRateLimitError` | unit |
| `test_on_demand_ticker_ssrf_validation` | invalid ticker → 422 | unit |
| `test_on_demand_isin_ssrf_validation` | invalid ISIN → 422 | unit |
| `test_on_demand_persists_description_to_securities` | After EODHD call: `securities.description` updated in DB | unit |

**Acceptance criteria**:
- [ ] DB-first: EODHD only called when DB has no description
- [ ] EODHD result persisted to `securities.description` (and other enrichment columns)
- [ ] SSRF validation before any EODHD URL construction
- [ ] 8 unit tests pass

---

##### T-B-1-03: Router — Unified `/lookup` + `/on-demand-profile`; Deprecate Old Endpoints

**Type**: impl
**depends_on**: [T-B-1-01, T-B-1-02]
**blocks**: [T-B-1-04]
**Target files**:
- `services/market-data/src/market_data/api/routers/instruments.py` (modify)
- `services/market-data/src/market_data/api/dependencies.py` (modify)

**PRD reference**: §6.3

**What to build**:

**New route** — `GET /api/v1/instruments/lookup`:
```python
@router.get("/lookup", response_model=InstrumentLookupResponse | InstrumentLookupDetailResponse)
async def lookup_instrument(
    symbol: str | None = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$"),
    isin: str | None = Query(None, min_length=12, max_length=12, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"),
    id: UUID | None = Query(None),
    extra_info: bool = Query(False),
    uc: InstrumentLookupUseCase = Depends(get_lookup_instrument_uc),
) -> InstrumentLookupResponse | InstrumentLookupDetailResponse:
    try:
        return await uc.execute(symbol=symbol, isin=isin, id=id, extra_info=extra_info)
    except ValueError:
        raise HTTPException(status_code=400, detail="At least one of symbol, isin, or id is required")
    except InstrumentNotFoundError:
        raise HTTPException(status_code=404, detail="Instrument not found")
```

**New route** — `GET /api/v1/instruments/on-demand-profile` (internal JWT):
```python
@router.get("/on-demand-profile", response_model=OnDemandProfileResponse)
async def on_demand_profile(
    ticker: str | None = Query(None),
    isin: str | None = Query(None),
    _: None = Depends(require_internal_jwt),
    uc: OnDemandProfileUseCase = Depends(get_on_demand_profile_uc),
) -> OnDemandProfileResponse: ...
```

**Remove old routes**: Delete `GET /instruments/symbol/{symbol}` and `GET /instruments/{instrument_id}`. The new `/lookup` endpoint covers all their use cases with cleaner semantics.

**Route ordering**: `/lookup` and `/on-demand-profile` MUST be defined BEFORE any `/{instrument_id}` path-param route to avoid `"lookup"` being swallowed as a UUID.

**Tests to write** (in `services/market-data/tests/unit/api/routers/test_instruments_lookup.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_lookup_200_base` | GET /instruments/lookup?symbol=AAPL → 200 + base fields | unit |
| `test_lookup_200_extra_info` | GET /instruments/lookup?symbol=AAPL&extra_info=true → 200 + enrichment fields | unit |
| `test_lookup_404` | Unknown symbol → 404 | unit |
| `test_lookup_400_no_params` | No params → 400 | unit |
| `test_on_demand_200` | GET /instruments/on-demand-profile?ticker=AAPL → 200 | unit |
| `test_on_demand_404` | Not found → 404 | unit |
| `test_on_demand_429` | EODHD rate limit → 429 | unit |
| `test_on_demand_requires_internal_jwt` | No `X-Internal-JWT` → 401 | unit |
| `test_old_symbol_endpoint_removed` | GET /instruments/symbol/AAPL → 404 (route no longer exists) | unit |

**Acceptance criteria**:
- [ ] `/lookup` responds correctly with and without `extra_info`
- [ ] `/on-demand-profile` returns 401 without internal JWT
- [ ] Old `/symbol/{symbol}` and `/{instrument_id}` routes removed
- [ ] 9 unit tests pass

---

##### T-B-1-04: Propagate to S9 Proxy + Frontend

**Type**: impl
**depends_on**: [T-B-1-03]
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routers/instruments.py` (modify — replace old proxy routes with `/lookup` proxy)
- `apps/worldview-web/src/lib/api/instruments.ts` (or equivalent) — update all `getInstrumentBySymbol` / `getInstrumentById` calls to `GET /api/v1/instruments/lookup?symbol=...&extra_info=true`
- Any other frontend files calling the old instrument endpoints

**PRD reference**: §5 (affected services — S9 and worldview-web)

**What to build**:

**S9 changes**: Replace proxy routes for `/instruments/symbol/{symbol}` and `/instruments/{instrument_id}` with a proxy for `GET /instruments/lookup` (forwards `symbol`, `isin`, `id`, `extra_info` query params). Bearer JWT required.

**Frontend changes**: Grep for all usages of `/instruments/symbol/` and `/instruments/{id}` in `apps/worldview-web/src/` and replace with `/api/v1/instruments/lookup?symbol=<ticker>&extra_info=true` (or `id=<uuid>&extra_info=true`). Update TypeScript types to use `InstrumentLookupDetailResponse` shape.

**Acceptance criteria**:
- [ ] Old S9 proxy routes removed; `/instruments/lookup` proxy added
- [ ] All frontend instrument fetch calls updated to new endpoint
- [ ] `pnpm run type-check` passes in `apps/worldview-web/`
- [ ] Existing S9 tests pass
- [ ] `ruff check` + `mypy` pass on changed S9 files

---

### Wave B-2: S3 Integration Tests ✅

**Goal**: Integration tests that verify the two new endpoints against a testcontainer DB with mocked EODHD.

**Depends on**: Wave B-1

**Estimated effort**: 30–45 min

**Status**: **DONE** — 2026-05-05 · 5 integration tests (respx-mocked EODHD) · ruff + mypy clean

**Architecture layer**: integration tests

#### Tasks

---

##### T-B-2-01: Integration Tests for Lookup and On-Demand Profile

**Type**: test
**depends_on**: none (Wave B-1 must be done)
**blocks**: none
**Target files**:
- `services/market-data/tests/integration/test_instrument_lookup_integration.py` (create)

**PRD reference**: §15.2

**What to build**:
Integration tests using `pytest-asyncio` and SQLAlchemy against a testcontainer PostgreSQL instance seeded with a known instrument row.

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_lookup_by_ticker_live_db` | `GET /instruments/lookup?ticker=AAPL` finds seeded row | integration |
| `test_lookup_by_isin_live_db` | `GET /instruments/lookup?isin=US0378331005` resolves | integration |
| `test_lookup_not_found_live_db` | Unknown ticker returns 404 | integration |
| `test_on_demand_db_hit_live_db` | DB row found → `source="db"`, no EODHD mock called | integration |
| `test_on_demand_eodhd_fallback_mocked` | DB miss → mocked EODHD 200 → `source="eodhd"` fields extracted | integration |

**Acceptance criteria**:
- [ ] 5 integration tests pass
- [ ] Tests don't require a real EODHD API key (EODHD calls mocked via `httpx.MockTransport` or `respx`)

#### Validation Gate — Wave B-1 + B-2

- [x] `python -m pytest tests/ -v` passes in `services/market-data/` — all tests including existing ones
- [x] `ruff check` + `mypy` pass on all changed files in S3
- [x] New routes visible in OpenAPI `/docs`
- [x] Route ordering verified: `/lookup` and `/on-demand-profile` before `/{instrument_id}`
- [x] `on-demand-profile` returns 401 without internal JWT header

#### Break Impact — Waves B-1, B-2

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/market-data/tests/` | Tests referencing `GET /instruments/symbol/{symbol}` or `GET /instruments/{instrument_id}` will 404 | Remove old tests; add `test_old_symbol_endpoint_removed` in T-B-1-03 |
| `services/api-gateway/src/api_gateway/routers/instruments.py` | S9 proxy routes for old endpoints will point to deleted routes | Fixed in T-B-1-04 |
| `apps/worldview-web/src/` | Any frontend call to `/instruments/symbol/` or `/instruments/{id}` will 404 | Fixed in T-B-1-04 |

#### Regression Guardrails — Waves B-1, B-2

- **BP-235**: httpx timeout shadowing — `OnDemandProfileUseCase` MUST set `httpx.AsyncClient(timeout=httpx.Timeout(10.0))` explicitly; never rely on httpx default 5s.
- **SSRF (PRD §12)**: ticker/ISIN validated against regex BEFORE constructing EODHD URL — verify `TICKER_PATTERN` and `ISIN_PATTERN` are applied in the use case, NOT just in the router query param validators.
- **FastAPI route ordering**: `/lookup` and `/on-demand-profile` MUST be defined before `/{instrument_id}` in the router — else `"lookup"` matches as UUID and raises 422.

---

## Sub-Plan C — S7 knowledge-graph (Worker 13J)

### Wave C-1: Domain Entities, Config, Port, LLM Prompt ✅

**Goal**: Add `EnrichmentResult`, `EnrichmentSource`, `data_completeness` computation, `EntityEnrichmentPort`, `MarketDataClient`, config field `enrichment_llm_model_id`, and the enrichment LLM prompt to `libs/prompts`.

**Depends on**: none (can be written before migrations are applied — no DB calls)

**Estimated effort**: 45–60 min

**Status**: **DONE** — 2026-05-05 · 26 new tests (15 enrichment_result + 11 entity_enrichment_prompt) · ruff + mypy clean

**Architecture layer**: domain + application ports + config

#### Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/domain/entities/` — existing entity patterns
- `services/knowledge-graph/src/knowledge_graph/application/ports/` — existing port Protocol patterns
- `services/knowledge-graph/src/knowledge_graph/config.py` — existing settings (env prefix `KNOWLEDGE_GRAPH_`)
- `libs/prompts/src/prompts/knowledge/` — existing prompt module structure
- `docs/specs/0073-isolated-node-enrichment.md` §9, §10

#### Tasks

---

##### T-C-1-01: `EnrichmentResult` Value Object + `EnrichmentSource` Enum + `compute_data_completeness`

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/domain/entities/enrichment_result.py` (create)

**PRD reference**: §9.1, §9.2, §9.3

**What to build**:

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class EnrichmentSource(str, Enum):
    MARKET_DATA = "market_data"
    EODHD = "eodhd"
    LLM = "llm"
    NONE = "none"


@dataclass(frozen=True)
class EnrichmentResult:
    entity_id: UUID
    description: str | None
    metadata: dict[str, object]
    data_completeness: float
    enriched_at: datetime  # must be UTC (timezone-aware)
    source: EnrichmentSource
    seeded_relations: list[str]  # canonical_type values


def compute_data_completeness(
    entity_type: str,
    description: str | None,
    metadata: dict[str, object],
) -> float:
    def present(v: object) -> bool:
        return bool(v)  # treats None and "" as absent

    if entity_type in ("financial_instrument", "company"):
        expected = [
            description,
            metadata.get("sector"),
            metadata.get("industry"),
            metadata.get("country"),
            metadata.get("exchange"),
            metadata.get("isin"),
            metadata.get("ticker"),
            metadata.get("employee_count"),
            metadata.get("founded_year"),
            metadata.get("headquarters_country"),
        ]
        return len([f for f in expected if present(f)]) / 10
    elif entity_type == "person":
        expected = [
            description,
            metadata.get("role"),
            metadata.get("organization"),
            metadata.get("nationality"),
        ]
        return len([f for f in expected if present(f)]) / 4
    else:  # concept, location, event
        expected = [
            description,
            metadata.get("category"),
        ]
        return len([f for f in expected if present(f)]) / 2
```

**Tests to write** (in `services/knowledge-graph/tests/unit/domain/test_enrichment_result.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_compute_data_completeness_financial_full` | All 10 fields → 1.0 | unit |
| `test_compute_data_completeness_financial_partial` | 5/10 fields → 0.5 | unit |
| `test_compute_data_completeness_empty_strings` | `""` treated as absent | unit |
| `test_compute_data_completeness_person_full` | 4/4 → 1.0 | unit |
| `test_compute_data_completeness_person_partial` | 2/4 → 0.5 | unit |
| `test_compute_data_completeness_concept` | description only → 0.5 | unit |
| `test_compute_data_completeness_event_both_fields` | both fields → 1.0 | unit |
| `test_enrichment_source_str_values` | `str(EnrichmentSource.MARKET_DATA) == "market_data"` | unit |

**Acceptance criteria**:
- [ ] `EnrichmentResult` is a frozen dataclass
- [ ] `EnrichmentSource` is a `str` enum with 4 values
- [ ] `compute_data_completeness` correct for all 3 entity-type buckets
- [ ] Empty string and `None` both treated as absent
- [ ] 8 unit tests pass

---

##### T-C-1-02: `EntityEnrichmentPort` Protocol

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/ports/entity_enrichment.py` (create)

**PRD reference**: §9.4

**What to build**:

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.application.unit_of_work import UnitOfWork
    from knowledge_graph.domain.entities.canonical_entity import CanonicalEntity
    from knowledge_graph.domain.entities.enrichment_result import EnrichmentResult


class EntityEnrichmentPort(Protocol):
    async def write_enrichment_result(
        self,
        result: "EnrichmentResult",
        uow: "UnitOfWork",
    ) -> None: ...

    async def increment_attempts(
        self,
        entity_id: UUID,
        uow: "UnitOfWork",
    ) -> None: ...

    async def list_unenriched(
        self,
        batch_size: int,
    ) -> list["CanonicalEntity"]: ...
```

**Acceptance criteria**:
- [ ] Protocol defined with 3 methods matching PRD §9.4 signatures
- [ ] No infrastructure imports in this file (domain/application layer only)
- [ ] `mypy` passes (Protocol with TYPE_CHECKING guards)

---

##### T-C-1-03: Config Field + `MarketDataClient` HTTP Adapter

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/config.py` (modify — add `enrichment_llm_model_id`, `enrichment_llm_fallback_model_id`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/http/market_data_client.py` (create)

**PRD reference**: §3.2 NFR-06, §9.5, §10.1, ADR-0073-006

**Config additions** (in `Settings` class):
```python
# Worker 13J — Structured Enrichment (PRD-0073)
# Primary: Qwen3-235B for high-quality finance descriptions
# Fallback: Llama-3.1-8B-Instruct-Turbo (confirmed available 2026-05-01 to 2026-06-01)
# NEVER use Qwen2.5-0.5B or Qwen2.5-1.5B — both return 404 on this account
enrichment_llm_model_id: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"
enrichment_llm_fallback_model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
```

Note: concurrency is intentionally NOT a config field — the sweep is sequential by design (NFR-03 hardcodes batch processing without `asyncio.gather`). A config field would imply it can be changed to parallel, which it cannot.

**`MarketDataClient`** — async HTTP client for the two new S3 endpoints:
```python
class MarketDataClient:
    def __init__(self, base_url: str, internal_jwt: str) -> None:
        # httpx.Timeout explicitly set (BP-235)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(15.0),
            headers={"X-Internal-JWT": internal_jwt},
        )

    async def lookup(
        self,
        ticker: str | None = None,
        isin: str | None = None,
        id: UUID | None = None,
    ) -> dict[str, object] | None:
        """Returns parsed JSON with enrichment fields, or None if 404.

        Always fetches with extra_info=true so caller gets description/sector/etc.
        Param 'ticker' maps to the 'symbol' query param on the S3 endpoint.
        """
        params: dict[str, str] = {}
        if ticker:
            params["symbol"] = ticker
        if isin:
            params["isin"] = isin
        if id:
            params["id"] = str(id)
        params["extra_info"] = "true"
        resp = await self._client.get("/api/v1/instruments/lookup", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def on_demand_profile(
        self,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> dict[str, object] | None:
        """Returns parsed JSON or None if 404. Raises httpx.HTTPStatusError on 429."""
        params = {k: v for k, v in [("ticker", ticker), ("isin", isin)] if v}
        resp = await self._client.get("/api/v1/instruments/on-demand-profile", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()  # 429 propagates as HTTPStatusError
        return resp.json()  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        await self._client.aclose()
```

**Acceptance criteria**:
- [ ] Config fields added with correct defaults and env-var names (`KNOWLEDGE_GRAPH_ENRICHMENT_LLM_MODEL_ID`, `KNOWLEDGE_GRAPH_ENRICHMENT_LLM_FALLBACK_MODEL_ID`)
- [ ] `MarketDataClient` uses `httpx.Timeout(15.0)` explicitly (BP-235)
- [ ] `lookup()` always passes `extra_info=true`; maps `ticker` → `symbol` query param
- [ ] `lookup()` returns `None` on 404; `on_demand_profile()` returns `None` on 404 but propagates 429
- [ ] `mypy` passes

---

##### T-C-1-04: LLM Enrichment Prompt in `libs/prompts`

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `libs/prompts/src/prompts/knowledge/entity_enrichment.py` (create)

**PRD reference**: §11 ADR-0073-003, §12 (prompt injection mitigation)

**What to build**:
A prompt builder function for the entity enrichment LLM call. Uses few-shot examples from EODHD-quality descriptions. Sanitizes entity name against prompt injection using the existing `sanitize_description` helper (if it exists) or a simple delimiter pattern.

```python
from __future__ import annotations

import re

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f<>]")


def sanitize_entity_name(name: str) -> str:
    """Strip control chars and angle brackets to prevent prompt injection."""
    return _CONTROL_CHAR_RE.sub("", name)[:200]


SYSTEM_PROMPT = """\
You are a financial intelligence assistant. Generate a concise, factual description \
of the entity provided. Use 3–5 sentences. Write in professional finance-industry prose. \
If the entity is a company or financial instrument, include: what it does, key products/services, \
sector, and headquarters. If the entity is a person, include: role, organization, and career highlights. \
If the entity is a concept or location, provide a clear definitional description.

Examples of high-quality descriptions:
- Apple Inc.: "Apple Inc. designs, manufactures, and markets consumer electronics, computer software, \
and online services worldwide. The company's flagship products include the iPhone, Mac, iPad, Apple Watch, \
and Apple TV, complemented by a growing Services segment encompassing the App Store, Apple Music, iCloud, \
and Apple Pay. Founded in 1976 and headquartered in Cupertino, California, Apple is one of the world's \
most valuable companies by market capitalization."
- JPMorgan Chase & Co.: "JPMorgan Chase & Co. is a leading global financial services firm and one of \
the largest banking institutions in the United States, with operations in more than 60 countries. \
The firm offers a broad range of financial services including investment banking, commercial banking, \
financial transaction processing, asset management, and private banking. Headquartered in New York City, \
it serves millions of consumers, small businesses, and many of the world's most prominent corporate, \
institutional, and government clients."
"""


def build_entity_enrichment_prompt(
    entity_name: str,
    entity_type: str,
    context_hint: str = "",
) -> str:
    """Build the user message for the enrichment LLM call.

    Args:
        entity_name: Canonical entity name (sanitized before insertion).
        entity_type: One of financial_instrument, company, person, concept, location, event.
        context_hint: Optional hint (e.g. sector, country) to guide the model.
    """
    safe_name = sanitize_entity_name(entity_name)
    parts = [f"Entity name: <entity>{safe_name}</entity>", f"Entity type: {entity_type}"]
    if context_hint:
        parts.append(f"Context: {context_hint}")
    parts.append("Write the description:")
    return "\n".join(parts)
```

**Tests to write** (in `libs/prompts/tests/test_entity_enrichment_prompt.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_sanitize_entity_name_strips_angle_brackets` | `<script>` → stripped | unit |
| `test_sanitize_entity_name_strips_control_chars` | `\x00\x1f` → stripped | unit |
| `test_build_prompt_includes_entity_name` | output contains sanitized name | unit |
| `test_build_prompt_includes_entity_type` | output contains `entity_type` | unit |
| `test_build_prompt_includes_context_hint` | non-empty `context_hint` appears in output | unit |

**Acceptance criteria**:
- [ ] `sanitize_entity_name` strips `<>`, `\x00`–`\x1f`, `\x7f`, and caps at 200 chars
- [ ] `build_entity_enrichment_prompt` produces a string containing `<entity>NAME</entity>`
- [ ] 5 unit tests pass
- [ ] No external imports (no infrastructure in this module)

---

#### Validation Gate — Wave C-1

- [x] `ruff check` + `mypy` pass on all new files
- [x] No imports from `infrastructure/` in domain or application layer files
- [x] Unit tests: minimum 21 new tests (8 + 0 + 0 + 5 = but count all tests above) pass
- [x] `KNOWLEDGE_GRAPH_ENRICHMENT_LLM_MODEL_ID` env var reads correctly into `settings.enrichment_llm_model_id`

#### Break Impact — Wave C-1

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | All new files; config additions are additive | — |

#### Regression Guardrails — Wave C-1

- **BP-235**: `MarketDataClient` MUST use `httpx.Timeout(15.0)` — explicit timeout required.
- **RULES §12**: Domain layer independence — `enrichment_result.py` and `entity_enrichment.py` MUST NOT import from `infrastructure/`.
- **ADR-0073-006 / MEMORY**: `Qwen2.5-0.5B-Instruct` and `Qwen2.5-1.5B-Instruct` return 404 on this DeepInfra account — must NEVER be used as fallbacks (comment in config confirms this).

---

### Wave C-2: `StructuredEnrichmentUseCase` + `EntityEnrichmentAdapter` + `StructuredEnrichmentWorker` ✅

**Goal**: Implement the enrichment orchestration use case, the DB adapter (port implementation), and the worker (APScheduler job + Kafka consumer).

**Depends on**: Wave C-1, Sub-Plan A Wave A-1, Sub-Plan B Wave B-1

**Estimated effort**: 90–120 min

**Status**: **DONE** — 2026-05-05 · 15 new use case unit tests + 4 scheduler tests updated · ruff + mypy clean · architecture tests pass

**Architecture layer**: application + infrastructure

#### Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/provisional_enrichment_core.py` — existing worker pattern with APScheduler
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/entity_consumer.py` — existing `entity.canonical.created.v1` consumer
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py` — existing R25 3-phase session pattern
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/` — existing use case structure
- `docs/specs/0073-isolated-node-enrichment.md` §9.4, §9.5, §10.1, §10.2

#### Tasks

---

##### T-C-2-01: `EntityEnrichmentAdapter` (Port Implementation)

**Type**: impl
**depends_on**: [T-C-1-01, T-C-1-02]
**blocks**: [T-C-2-02]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/adapters/entity_enrichment_adapter.py` (create)

**PRD reference**: §9.4

**What to build**:
Implements `EntityEnrichmentPort` using SQLAlchemy raw SQL (consistent with existing repo patterns).

```python
class EntityEnrichmentAdapter:
    def __init__(self, session_factory: async_sessionmaker) -> None: ...

    async def write_enrichment_result(self, result: EnrichmentResult, uow: UnitOfWork) -> None:
        # UPDATE canonical_entities SET description=, metadata=jsonb_strip_nulls(metadata || :new_meta),
        # data_completeness=, enriched_at=, enrichment_attempts=0
        # WHERE entity_id = :entity_id
        ...

    async def increment_attempts(self, entity_id: UUID, uow: UnitOfWork) -> None:
        # UPDATE canonical_entities SET enrichment_attempts = enrichment_attempts + 1
        # WHERE entity_id = :entity_id
        ...

    async def list_unenriched(self, batch_size: int) -> list[CanonicalEntity]:
        # SELECT entity_id, canonical_name, entity_type, ticker, isin, metadata
        # FROM canonical_entities
        # WHERE (enriched_at IS NULL OR data_completeness < 0.5)
        #   AND enrichment_attempts < 3
        # ORDER BY created_at ASC
        # LIMIT :batch_size
        # Opens and closes its own session (NOT held across external I/O)
        ...
```

**Important**: `write_enrichment_result` merges `metadata` using `jsonb_strip_nulls(metadata || :new_meta::jsonb)` to preserve existing keys not in the new result. `enrichment_attempts=0` is reset to 0 on success (not accumulated).

**Acceptance criteria**:
- [ ] `write_enrichment_result` merges metadata via JSONB operator (does not overwrite entire column)
- [ ] `increment_attempts` uses `enrichment_attempts + 1` (SQL-side increment, not app-side read-modify-write)
- [ ] `list_unenriched` opens its own session and closes it before returning (R25 3-phase pattern)
- [ ] No business logic — pure data access

---

##### T-C-2-02: `StructuredEnrichmentUseCase`

**Type**: impl
**depends_on**: [T-C-2-01, T-C-1-01, T-C-1-02, T-C-1-03, T-C-1-04]
**blocks**: [T-C-2-03]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/structured_enrichment.py` (create)

**PRD reference**: §9.5, §10.1, §13

**What to build**:
Orchestrates single-entity enrichment. Injected with: `EntityEnrichmentPort`, `RelationTypeRegistryRepository` (existing), `MarketDataClient`, `ml_clients` LLM client (for DeepInfra calls), `DirectKafkaProducer`.

```
async def enrich(entity: CanonicalEntity) -> EnrichmentResult:
    1. If entity.enrichment_attempts >= 3: return early (skip)
    2. Step 1: await market_data_client.lookup(ticker=entity.ticker, isin=entity.isin)
       → extract description, sector, industry, country, exchange, isin, ticker, currency_code
       → if description found: source = MARKET_DATA
       → On ConnectError/TimeoutException: log WARN, continue (do NOT raise)
    3. Step 2: if description still None AND entity_type in (financial_instrument, company):
       → await market_data_client.on_demand_profile(ticker=entity.ticker, isin=entity.isin)
       → On 429 (HTTPStatusError status=429): raise RetryableEnrichmentError (consumer retries)
       → On 404 (None returned): log INFO, continue
       → if description found: source = EODHD
    4. Step 3: Conditional LLM — only if description is STILL None after Steps 1–2
       OR entity_type is person/concept/location/event (non-financial entities never have DB/EODHD descriptions)
       → build prompt via build_entity_enrichment_prompt(entity.canonical_name, entity.entity_type)
       → asyncio.wait_for(llm_client.generate(prompt), timeout=25.0)
       → On timeout/503: raise RetryableEnrichmentError
       → On 404/500 (primary model): retry with fallback model once
       → On fallback failure: raise RetryableEnrichmentError
       → If response shorter than 20 chars: treat as non-retryable failure (increment attempts)
       → source = LLM
       (If EODHD/DB already provided description: skip LLM entirely — no metadata["llm_description"] storage)
    5. compute_data_completeness(entity.entity_type, description, metadata)
    6. Seed relations from relation_type_registry (WHERE data_source IN ('eodhd','market_data'))
       → for each registry row where source_field is in enrichment payload:
         upsert relation with relation_source='structured_enrichment'
         skip if object entity not found in canonical_entities
    7. Phase 3 (R25): open UoW, write EnrichmentResult via EntityEnrichmentPort, commit, close
    8. Produce entity.dirtied.v1 (direct produce post-commit, key=entity_id bytes)
       → On produce failure: log ERROR, do NOT raise (best-effort)
    9. Return EnrichmentResult
```

**Error types**:
- `RetryableEnrichmentError`: Kafka consumer will re-deliver; `enrichment_attempts` NOT incremented
- `FatalEnrichmentError`: `enrichment_attempts` incremented; entity skipped until manual reset

**R25 3-phase session compliance**: DB session MUST NOT be held open during steps 1–3 (HTTP calls) or step 4 (LLM call). Only open DB session in step 7 (write phase).

**Tests to write** (in `services/knowledge-graph/tests/unit/application/use_cases/test_structured_enrichment.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_enrich_financial_instrument_market_data_first` | lookup returns description → on-demand and LLM not called; `source=MARKET_DATA` | unit |
| `test_enrich_financial_instrument_on_demand_profile_fallback` | lookup 404 → on-demand called; fields extracted; LLM not called; `source=EODHD` | unit |
| `test_enrich_financial_instrument_llm_only` | lookup 404 + on-demand 404 → LLM called; `source=LLM` | unit |
| `test_enrich_person_llm_only` | person entity → lookup/on-demand not called (non-financial); LLM always called; 4-field formula | unit |
| `test_enrich_concept_llm_generates_definition` | concept → LLM called (no DB/EODHD path); 2-field formula | unit |
| `test_llm_skipped_when_description_already_found` | financial entity with description from DB/EODHD → `asyncio.wait_for` never awaited | unit |
| `test_enrichment_attempts_not_incremented_on_429` | on-demand 429 → `RetryableEnrichmentError` raised; no increment | unit |
| `test_enrichment_attempts_incremented_on_llm_short_response` | LLM < 20 chars → attempts +1 | unit |
| `test_entity_skipped_at_max_attempts` | `enrichment_attempts=3` → returns immediately, no API calls | unit |
| `test_relation_seeding_eodhd_sector` | EODHD sector="Technology" → `OPERATES_IN_SECTOR` upserted | unit |
| `test_relation_seeding_skips_missing_object_entity` | sector entity absent → skipped, enrichment still writes | unit |
| `test_entity_dirtied_produced_after_commit` | successful enrichment → `entity.dirtied.v1` produced post-commit | unit |
| `test_entity_dirtied_produce_failure_does_not_raise` | Kafka produce fails → log ERROR but no exception raised | unit |
| `test_llm_prompt_sanitizes_entity_name` | `canonical_name` with `<script>` → sanitized in prompt | unit |
| `test_market_data_connect_error_falls_through` | ConnectError on lookup → continues without raising | unit |
| `test_llm_fallback_on_primary_404` | primary model 404 → fallback model called | unit |

**Acceptance criteria**:
- [ ] 15 unit tests pass
- [ ] R25 3-phase session compliance: no DB session held during HTTP/LLM calls
- [ ] `RetryableEnrichmentError` does NOT increment `enrichment_attempts`
- [ ] LLM call wrapped in `asyncio.wait_for(timeout=25.0)` (NFR-02)
- [ ] `entity.dirtied.v1` key = `entity_id` bytes (direct produce, not outbox)

---

##### T-C-2-03: `StructuredEnrichmentWorker` (APScheduler + Kafka Consumer)

**Type**: impl
**depends_on**: [T-C-2-02]
**blocks**: [T-C-3-01]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/structured_enrichment_worker.py` (create)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/structured_enrichment_consumer.py` (create)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/structured_enrichment_consumer_main.py` (create)

**PRD reference**: §10.1, §10.2, §5

**What to build**:

**`StructuredEnrichmentWorker`** (APScheduler periodic sweep — daily at 02:00 UTC):
```python
class StructuredEnrichmentWorker:
    job_id = "worker_13j_enrichment_sweep"

    async def run(self) -> None:
        # Batch loop until 0 results
        while True:
            entities = await self.enrichment_port.list_unenriched(batch_size=50)
            if not entities:
                break
            processed = succeeded = failed = skipped = 0
            for entity in entities:
                try:
                    result = await self.use_case.enrich(entity)
                    if result.source == EnrichmentSource.NONE:
                        skipped += 1
                    else:
                        succeeded += 1
                except RetryableEnrichmentError:
                    failed += 1  # leave for next sweep
                except Exception:
                    failed += 1
                finally:
                    processed += 1
            # Emit Prometheus: s7_enrichment_sweep_entities_processed_total.inc(processed)
        # Log sweep summary
```

**`StructuredEnrichmentConsumer`** (Kafka hot-path):
- Topic: `entity.canonical.created.v1`
- Consumer group: `kg-structured-enrichment-group`
- Config env var: `KNOWLEDGE_GRAPH_KAFKA_CONSUMER_GROUP_STRUCTURED_ENRICHMENT` (add to `Settings`)
- Extends `BaseKafkaConsumer` following the pattern in `entity_consumer.py`
- Skips if `entity_type not in ("financial_instrument", "company")` (FR-04)
- On message: look up entity from `canonical_entities` by `entity_id`; call `use_case.enrich(entity)`
- On `RetryableEnrichmentError`: raise (let consumer retry)
- On success: ack

**`structured_enrichment_consumer_main.py`**: entry-point script matching the pattern of `enriched_consumer_main.py`.

**New config fields** (in `Settings`):
```python
kafka_consumer_group_structured_enrichment: str = "kg-structured-enrichment-group"
```

**APScheduler registration**: Wire into the scheduler startup in `main.py` (or wherever APScheduler jobs are registered — follow existing pattern for `worker_13j_enrichment_sweep`).

**Acceptance criteria**:
- [ ] Worker's batch loop continues until `list_unenriched()` returns 0 results
- [ ] Consumer skips non-`financial_instrument`/`company` entity types
- [ ] Consumer uses correct consumer group `kg-structured-enrichment-group`
- [ ] Prometheus counter `s7_enrichment_sweep_entities_processed_total` incremented
- [ ] APScheduler job registered with `job_id = "worker_13j_enrichment_sweep"` at 02:00 UTC

---

#### Validation Gate — Wave C-2

- [x] `python -m pytest tests/ -v` passes in `services/knowledge-graph/`
- [x] Minimum 15 new unit tests from T-C-2-02 pass
- [x] `ruff check` + `mypy` pass on all changed files
- [x] R25 compliance verified: grep for `session` usage in `structured_enrichment.py` — no session object held during `await market_data_client.*` or `await llm_client.*` calls
- [x] No imports from `infrastructure/` in `application/use_cases/structured_enrichment.py`

#### Break Impact — Wave C-2

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `services/knowledge-graph/src/knowledge_graph/main.py` | APScheduler job must be registered | Add `scheduler.add_job(worker_13j.run, CronTrigger(hour=2, minute=0), id="worker_13j_enrichment_sweep")` |
| `services/knowledge-graph/src/knowledge_graph/config.py` | New consumer group config field | Already done in T-C-1-03; verify it's included |

#### Regression Guardrails — Wave C-2

- **R25 (3-phase session)**: DB session MUST NOT span HTTP calls to market-data or LLM calls. Verify by code inspection.
- **BP-235**: `MarketDataClient` timeout already set in T-C-1-03; verify `asyncio.wait_for(timeout=25.0)` on LLM call in use case.
- **RULES §5 (Outbox)**: `entity.dirtied.v1` is direct-produce (NOT outbox) — this is the established pattern for this topic. Confirm implementation does NOT use outbox.
- **NFR-03**: Periodic sweep batch = 50 entities; do NOT use `asyncio.gather` within a single batch (sequential processing required — see §14).

---

### Wave C-3: `EntityPublic` Schema + `GET /api/v1/entities/{entity_id}` Route ✅

**Goal**: Add the S7 API endpoint `GET /api/v1/entities/{entity_id}` with the new `EntityPublic` response schema, and add `CanonicalEntityRepository.get_by_id()` DB query.

**Depends on**: Wave C-2 (migrations must be applied; enrichment columns must exist)

**Estimated effort**: 45–60 min

**Status**: **DONE** — 2026-05-05 · 5 new API route tests · ruff + mypy clean · architecture tests pass (877 unit + 100 arch)

**Architecture layer**: API + repository

#### Pre-read (agent must read before starting)

- `services/knowledge-graph/src/knowledge_graph/api/entities.py` — existing router (no `GET /entities/{id}` yet)
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` — existing `EntitySummary` schema
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/` — existing repo patterns
- `docs/specs/0073-isolated-node-enrichment.md` §6.1, §6.2, §15.3

#### Tasks

---

##### T-C-3-01: `EntityPublic` Pydantic Schema + `CanonicalEntityRepository.get_by_id()`

**Type**: impl
**depends_on**: none
**blocks**: [T-C-3-02]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/schemas.py` (modify — add `EntityPublic`)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/db/repositories/canonical_entity_repository.py` (modify — add `get_by_id`)

**PRD reference**: §6.1, §6.2

**`EntityPublic` schema** (add to `api/schemas.py`):
```python
class EntityMetadata(BaseModel):
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    exchange: str | None = None
    isin: str | None = None
    ticker: str | None = None
    currency_code: str | None = None
    employee_count: int | None = None
    founded_year: int | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None
    role: str | None = None
    organization: str | None = None
    nationality: str | None = None
    category: str | None = None
    macro_indicators: dict[str, object] | None = None

class EntityPublic(BaseModel):
    entity_id: UUID
    canonical_name: str
    entity_type: str
    isin: str | None = None
    ticker: str | None = None
    exchange: str | None = None
    # New enrichment fields (all nullable — backward compatible)
    description: str | None = None
    metadata: EntityMetadata | None = None
    data_completeness: float | None = None
    enriched_at: datetime | None = None
```

**`CanonicalEntityRepository.get_by_id()`**:
```python
async def get_by_id(self, entity_id: UUID, session: AsyncSession) -> CanonicalEntity | None:
    # SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange,
    #        description, metadata, data_completeness, enriched_at, enrichment_attempts
    # FROM canonical_entities WHERE entity_id = :entity_id
    # Returns None if not found
```

**Acceptance criteria**:
- [ ] `EntityPublic` has all 4 new nullable enrichment fields
- [ ] Existing `EntitySummary` unchanged (backward compat)
- [ ] `get_by_id()` SELECTs all 4 new columns
- [ ] `EntityMetadata` is a typed Pydantic model (not raw dict in the response)

---

##### T-C-3-01.5: `GetEntityDetailUseCase` (R25 Wrapper)

**Type**: impl
**depends_on**: [T-C-3-01]
**blocks**: [T-C-3-02]
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/application/use_cases/get_entity_detail.py` (create)

**PRD reference**: §6.1, §6.2, RULES R25

**Why this task exists**: R25 prohibits API routers from calling repositories directly. `GET /entities/{entity_id}` must go through a use case. This thin wrapper satisfies R25 without adding unnecessary complexity — it is the correct architectural layer, not gold-plating.

**What to build**:
```python
class GetEntityDetailUseCase:
    def __init__(self, repo: CanonicalEntityRepository) -> None:
        self._repo = repo

    async def execute(
        self,
        entity_id: UUID,
        uow: ReadOnlyUnitOfWork,
    ) -> CanonicalEntity | None:
        async with uow:
            return await self._repo.get_by_id(entity_id, uow.session)
```

**Acceptance criteria**:
- [ ] No infrastructure imports — takes repo and `ReadOnlyUnitOfWork` via constructor (injected by FastAPI `Depends`)
- [ ] Returns `CanonicalEntity | None` (router handles 404)
- [ ] `mypy` passes

---

##### T-C-3-02: `GET /api/v1/entities/{entity_id}` Route

**Type**: impl
**depends_on**: [T-C-3-01.5]
**blocks**: none
**Target files**:
- `services/knowledge-graph/src/knowledge_graph/api/entities.py` (modify — add new route)

**PRD reference**: §6.1, §6.2

**What to build**:
```python
@router.get("/{entity_id}", response_model=EntityPublic)
async def get_entity(
    entity_id: UUID,
    uc: GetEntityDetailUseCase = Depends(get_entity_detail_uc),
) -> EntityPublic:
    entity = await uc.execute(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityPublic(
        entity_id=entity.entity_id,
        canonical_name=entity.canonical_name,
        entity_type=entity.entity_type,
        isin=entity.isin,
        ticker=entity.ticker,
        exchange=entity.exchange,
        description=entity.description,
        metadata=EntityMetadata(**entity.metadata) if entity.metadata else None,
        data_completeness=entity.data_completeness,
        enriched_at=entity.enriched_at,
    )
```

`get_entity_detail_uc` is a FastAPI dependency that constructs `GetEntityDetailUseCase` with the read repo and `ReadUoWDep` injected — follow the existing dependency provider pattern in `api/dependencies.py`.

**Note on read replica**: This is a read-only endpoint. Use case receives `ReadOnlyUnitOfWork` (Rule R27) — the `ReadUoWDep` dependency ensures this.

**Tests to write** (in `services/knowledge-graph/tests/unit/api/test_entities_detail.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_entity_200_with_enrichment` | Entity with all enrichment fields → 200 + full `EntityPublic` | unit |
| `test_get_entity_200_null_enrichment_fields` | Entity with NULL enrichment fields → 200 + `null` fields | unit |
| `test_get_entity_404` | Unknown UUID → 404 | unit |
| `test_entity_public_schema_includes_enrichment_fields` | Pydantic validation: description/metadata/data_completeness/enriched_at all valid | unit |
| `test_entity_public_schema_allows_null_enrichment_fields` | all 4 new fields null → model validates | unit |

**Acceptance criteria**:
- [ ] Route calls `GetEntityDetailUseCase.execute()` — no direct repo reference in router (R25)
- [ ] Uses `ReadUoWDep` (R27 — read replica session)
- [ ] Returns 404 for unknown UUID
- [ ] All 4 new fields present in response when enriched; null when not
- [ ] 5 unit tests pass

---

#### Validation Gate — Wave C-3

- [x] `python -m pytest tests/ -v` passes in `services/knowledge-graph/` — all tests including waves C-1 and C-2
- [x] `curl localhost:8007/api/v1/entities/<known-uuid>` returns 200 with enrichment fields (or nulls)
- [x] `ruff check` + `mypy` pass
- [x] Architecture test `TestLayerIsolation` still passes (existing guard)

#### Break Impact — Wave C-3

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | New route + new schema fields are purely additive | — |

#### Regression Guardrails — Wave C-3

- **R25 (API layer isolation)**: Resolved by T-C-3-01.5 — router calls `GetEntityDetailUseCase`, not `CanonicalEntityRepository` directly.
- **R27 (read replica)**: `GET /entities/{entity_id}` is read-only — `GetEntityDetailUseCase` receives `ReadOnlyUnitOfWork` via `ReadUoWDep`. MUST NOT use `UoWDep`.

---

## Sub-Plan D — S9 api-gateway + worldview-web

### Wave D-1: S9 Proxy Route + Frontend Description Panel ✅

**Goal**: Add S9 proxy routes for `GET /api/v1/entities/{entity_id}` and `GET /api/v1/instruments/lookup`, and add the entity description panel to the intelligence tab in worldview-web.

**Depends on**: Wave C-3 (S7 endpoint must exist), Wave B-1 (S3 lookup endpoint must exist)

**Estimated effort**: 60–90 min

**Status**: **DONE** — 2026-05-05 · 7 new S9 unit tests + 1805 frontend tests pass · ruff + mypy + tsc clean

**Architecture layer**: API proxy + frontend UI

#### Pre-read (agent must read before starting)

- `services/api-gateway/src/api_gateway/routers/` — existing S9 router patterns for S7 proxying
- `apps/worldview-web/src/` — existing intelligence tab components
- `docs/ui/DESIGN_SYSTEM.md` — design tokens for entity description cards
- `docs/apps/worldview-web.md` — frontend architecture patterns
- `docs/specs/0073-isolated-node-enrichment.md` §6.1, §6.3, FR-11

#### Tasks

---

##### T-D-1-01: S9 Proxy Routes for Entity Detail and Instrument Lookup

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routers/entities.py` (modify or create — add proxy for `GET /entities/{entity_id}`)
- `services/api-gateway/src/api_gateway/routers/instruments.py` (modify — add proxy for `GET /instruments/lookup`)

**PRD reference**: §6.1, §6.3

**What to build**:
- `GET /api/v1/entities/{entity_id}` → proxy to `http://knowledge-graph:8007/api/v1/entities/{entity_id}`
- `GET /api/v1/instruments/lookup` → proxy to `http://market-data:8003/api/v1/instruments/lookup` (passes through query params: `ticker`, `isin`, `id`)

Both routes require Bearer JWT (existing S9 auth middleware). S9 does NOT forward `X-Internal-JWT` for these public-facing routes.

Follow the existing `httpx` proxy pattern used by other S9 routes. Strip and re-add auth headers as appropriate.

**Acceptance criteria**:
- [ ] `GET /api/v1/entities/{entity_id}` proxied correctly to S7
- [ ] `GET /api/v1/instruments/lookup` proxied correctly to S3
- [ ] Auth (Bearer JWT) required for both routes
- [ ] `instruments/lookup` query params forwarded without transformation
- [ ] Existing S9 tests still pass

---

##### T-D-1-02: Frontend Entity Description Panel

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/src/components/intelligence/EntityDescriptionPanel.tsx` (create)
- `apps/worldview-web/src/app/(workspace)/intelligence/page.tsx` (modify — integrate panel when entity selected)
- `apps/worldview-web/src/lib/api/entities.ts` (modify or create — add `getEntity(entityId)` fetch function)

**PRD reference**: §6.1, FR-11

**What to build**:
An `EntityDescriptionPanel` component that:
- Shows when `description` is non-null on the selected entity
- Displays: entity name, entity type badge, description text, `data_completeness` score bar, `metadata` key fields (sector, industry, country, exchange, ticker, ISIN)
- Hidden/greyed-out when `description` is null (entity not yet enriched)
- Fetches from `GET /api/v1/entities/{entity_id}` via the S9 proxy

```tsx
// EntityDescriptionPanel.tsx
interface EntityDescriptionPanelProps {
  entityId: string
  className?: string
}
```

**Design notes** (from DESIGN_SYSTEM.md tokens):
- Use `bg-[hsl(var(--panel))]` for panel background
- Entity type badge: `text-xs font-mono bg-muted text-muted-foreground px-1.5 py-0.5 rounded`
- `data_completeness` bar: a simple `<div>` with `bg-primary` width set to `${data_completeness * 100}%`
- Null state: show skeleton placeholder (Tailwind `animate-pulse bg-muted h-4 rounded`)

**Acceptance criteria**:
- [ ] Panel renders correctly when entity has `description`
- [ ] Panel shows skeleton when `description` is null
- [ ] `data_completeness` score bar renders (0–100% fill)
- [ ] `metadata` fields render as key-value rows when present, hidden when null
- [ ] No TypeScript errors (`tsc --noEmit` passes)
- [ ] Uses `pnpm` only; no new dependencies added

---

#### Validation Gate — Wave D-1

- [x] S9 integration: `curl -H "Authorization: Bearer ..." http://localhost:8000/api/v1/entities/<uuid>` → 200 + enrichment fields
- [x] S9 integration: `curl -H "Authorization: Bearer ..." "http://localhost:8000/api/v1/instruments/lookup?ticker=AAPL"` → 200
- [x] Frontend: `EntityDescriptionPanel` renders in intelligence tab (manual browser check with enriched entity)
- [x] `pnpm run typecheck` passes in `apps/worldview-web/` — tsc --noEmit clean
- [x] `python -m pytest tests/ -v` passes in `services/api-gateway/` — 335 passed

#### Break Impact — Wave D-1

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| None expected | New routes and new component; nothing removed | — |

#### Regression Guardrails — Wave D-1

- **RULES §14 (Frontend → S9 only)**: `EntityDescriptionPanel` fetches from `/api/v1/entities/*` (Next.js rewrite → S9) — never directly to `localhost:8007`.
- **pnpm enforcement (MEMORY)**: use exact versions, no `^`; no new deps unless required.

---

## Cross-Cutting Concerns

### New Environment Variables

| Variable | Service | Default | Purpose |
|----------|---------|---------|---------|
| `KNOWLEDGE_GRAPH_ENRICHMENT_LLM_MODEL_ID` | S7 | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Primary LLM for entity descriptions |
| `KNOWLEDGE_GRAPH_ENRICHMENT_LLM_FALLBACK_MODEL_ID` | S7 | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | Fallback model |
| `KNOWLEDGE_GRAPH_KAFKA_CONSUMER_GROUP_STRUCTURED_ENRICHMENT` | S7 | `kg-structured-enrichment-group` | Enrichment consumer group |

Note: `KNOWLEDGE_GRAPH_ENRICHMENT_LLM_CONCURRENCY` is intentionally NOT an env var — concurrency is hardcoded sequential (see T-C-1-03 rationale).

**Where to add**: `worldview-gitops/env/dev/knowledge-graph.env` (non-secrets). These are not secrets so they do NOT go into `setup-secrets.sh` — they sync to the service via `scripts/setup-dev.sh` as part of the standard `.env` copy.

### Kafka Consumer Group

New consumer group `kg-structured-enrichment-group` consumes `entity.canonical.created.v1`. This is a separate group from the existing `kg-service-group` — both can consume from the same topic independently.

### Documentation Updates

After all waves complete:
- [ ] `docs/services/knowledge-graph.md` — add Worker 13J section: trigger, schedule, cascade, metrics
- [ ] `docs/services/market-data.md` — add `/instruments/lookup` and `/on-demand-profile` to API reference
- [ ] `services/knowledge-graph/.claude-context.md` — add Worker 13J, `StructuredEnrichmentConsumer`, new config fields, `EntityPublic`
- [ ] `services/market-data/.claude-context.md` — add new endpoints and use cases

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| PLAN-0072 migrations (0020–0023) not merged before Wave A-1 | HIGH | LOW | Check TRACKING.md before starting; migrations must chain correctly |
| EODHD rate limit during bootstrap sweep | MEDIUM | MEDIUM | 429 is retryable; sweep retries next day; batch=50 limits per-day volume |
| DeepInfra Qwen3-235B unavailable | MEDIUM | LOW | Fallback to Llama-3.1-8B is configured |
| `relations` partitioned table DDL issue | HIGH | LOW | NULL column ADD COLUMN is safe on PG16; no NOT NULL constraint |
| LLM description quality below expectation | LOW | MEDIUM | Few-shot examples in system prompt; EODHD preferred over LLM |
| Frontend entity description panel empty for first 72h | LOW | HIGH | Expected behavior; enrichment runs overnight sweep |

### Critical Path

**A-1 → B-1 → C-1 → C-2 → C-3 → D-1** is the critical path. Sub-Plan A and Sub-Plan B can be parallelized; Sub-Plan C starts after both.

### Rollback Strategy

All migrations are additive (nullable columns). Rolling back requires:
1. Deploy previous S7 version (does not read new columns)
2. In `intelligence-migrations`: run `alembic downgrade -3` (reverses 0026→0025→0024)
3. In `market-data`: run `alembic downgrade -1` (drops `securities.description`)
4. Columns are dropped; S7 and S3 continue operating on old schemas

---

## Task Status Tracking

### Sub-Plan A — intelligence-migrations

| Task | Status | Wave |
|------|--------|------|
| T-A-1-01: Migration 0022 (enrichment fields) | done | A-1 |
| T-A-1-02: Migration 0023 (relation_type_registry source fields + seed data) | done | A-1 |
| T-A-1-03: Migration 0024 (relations.relation_source) | done | A-1 |

### Sub-Plan B — S3 market-data

| Task | Status | Wave |
|------|--------|------|
| T-B-0-01: Alembic migration (securities.description) | pending | B-0 |
| T-B-1-01: `InstrumentLookupUseCase` | pending | B-1 |
| T-B-1-02: `OnDemandProfileUseCase` | pending | B-1 |
| T-B-1-03: Router endpoints (unified `/lookup` + `/on-demand-profile`) | pending | B-1 |
| T-B-1-04: Propagate to S9 proxy + frontend | pending | B-1 |
| T-B-2-01: Integration tests | pending | B-2 |

### Sub-Plan C — S7 knowledge-graph

| Task | Status | Wave |
|------|--------|------|
| T-C-1-01: `EnrichmentResult` + `EnrichmentSource` + `compute_data_completeness` | pending | C-1 |
| T-C-1-02: `EntityEnrichmentPort` Protocol | pending | C-1 |
| T-C-1-03: Config + `MarketDataClient` | pending | C-1 |
| T-C-1-04: LLM enrichment prompt | pending | C-1 |
| T-C-2-01: `EntityEnrichmentAdapter` | pending | C-2 |
| T-C-2-02: `StructuredEnrichmentUseCase` (conditional LLM) | pending | C-2 |
| T-C-2-03: `StructuredEnrichmentWorker` + consumer | pending | C-2 |
| T-C-3-01: `EntityPublic` schema + `get_by_id()` | pending | C-3 |
| T-C-3-01.5: `GetEntityDetailUseCase` (R25 wrapper) | pending | C-3 |
| T-C-3-02: `GET /entities/{entity_id}` route | pending | C-3 |

### Sub-Plan D — S9 + worldview-web

| Task | Status | Wave |
|------|--------|------|
| T-D-1-01: S9 proxy routes | pending | D-1 |
| T-D-1-02: Frontend description panel | pending | D-1 |
