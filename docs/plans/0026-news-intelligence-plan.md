---
id: PLAN-0026
prd: docs/specs/0026-news-intelligence-ranked-feed.md
title: News Intelligence APIs — Ranked News Feed, Multi-Window Impact & LLM Relevance Scoring
status: in-progress
created: 2026-04-22
updated: 2026-04-22
services: [nlp-pipeline, api-gateway, worldview-web]
---

# PLAN-0026 — News Intelligence APIs

> Execution plan for PRD-0026. Replaces `article_price_impacts` with the
> multi-window `article_impact_windows` table, adds `ArticleRelevanceScoringWorker`
> (Qwen2.5:3b), exposes two new S6 endpoints, repoints S9 proxies from S5 → S6,
> and adds frontend types + gateway client methods.

---

## Codebase State Verification

Verified 2026-04-22 by reading actual source files:

| PRD Reference | Type | Service | Actual Current State | PRD Expected State | Delta |
|---|---|---|---|---|---|
| `article_price_impacts` | DB table | S6 | EXISTS — migration 0005, UNIQUE on `article_id` only | DROP and replace with `article_impact_windows` | migration 0009 needed |
| `ArticlePriceImpact` | domain entity | S6 | EXISTS — `services/nlp-pipeline/src/nlp_pipeline/domain/models.py:175` | REPLACE with `ArticleImpactWindow` | new entity; old one removed |
| `ArticlePriceImpactModel` | ORM model | S6 | EXISTS — `infrastructure/nlp_db/models.py:250` | REPLACE with `ArticleImpactWindowModel` | model change |
| `DocumentSourceMetadata` | domain entity | S6 | EXISTS — 7 fields, no `llm_relevance_score` | +2 optional fields | extend |
| `DocumentSourceMetadataModel` | ORM | S6 | EXISTS — no `llm_relevance_score`/`llm_scored_at` | +2 nullable columns | migration 0009 |
| `routing_decisions.doc_id` | index | nlp_db | NO index — only PK on `decision_id` | add index | migration 0009 |
| `PriceImpactLabellingWorker` | worker | S6 | EXISTS — `infrastructure/workers/price_impact_labelling_worker.py` — single window (day_t0 only) | 4 windows, cumulative logic | extend |
| `ArticleRelevanceScoringWorker` | worker | S6 | DOES NOT EXIST | new | create |
| `GET /api/v1/news/top` | endpoint | S6 | DOES NOT EXIST | new | create |
| `GET /api/v1/entities/{id}/articles` | endpoint | S6 | EXISTS (basic, in `signals.py`) | enhance with scoring fields + params | modify |
| `GET /v1/news/top` | S9 proxy | S9 | EXISTS — points to S5 `/v1/articles/relevant` with TODO(PRD-0026) | retarget to S6 | update |
| `GET /v1/news/entity/{id}` | S9 proxy | S9 | EXISTS — points to S5 `/v1/articles` with TODO(PRD-0026) | retarget to S6 `/entities/{id}/articles` | update |
| `llm_usage_log.py` migration | Alembic head | S6 | `0008_create_llm_usage_log.py` | next = `0009` | — |
| Frontend `gateway-client.ts` | types | worldview-web | EXISTS — no `RankedArticle`/news methods | add types + 2 methods | extend |

**Confirmed**: PLAN-0020 is complete (`article_price_impacts` + `PriceImpactLabellingWorker` exist).
**Confirmed**: PLAN-0021 complete (signal scoring pipeline exists).

---

## Plan Structure — 8 Waves

```
Wave 1 (domain)
  ↓
Wave 2 (migration 0009)
  ↓
Wave 3 (infrastructure — ORM + repositories + updated signals_query)
  ↓
Wave 4 (PriceImpactLabellingWorker extension — 4 windows)
Wave 5 (ArticleRelevanceScoringWorker — independent)
  ↓ (both 4 and 5 after wave 3)
Wave 6 (S6 API endpoints + use cases)
  ↓
Wave 7 (S9 proxy retarget)
  ↓
Wave 8 (frontend types + API client)
```

Waves 4 and 5 depend only on Wave 3 (no shared files) and can be executed in parallel worktrees.

---

## Wave 1: Domain Layer — New Entities, Enums & Value Objects ✅
**Status**: **DONE** — 2026-04-22 · 466 tests pass · ruff + mypy clean

**Goal**: Add `ArticleImpactWindow` entity, `DisplayRelevanceScore` value object, `WindowType`/`DataQuality` enums; extend `DocumentSourceMetadata`; update `__all__` exports.
**Depends on**: none
**Architecture layer**: domain
**Estimated effort**: 30–45 min

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/domain/models.py`
- `services/nlp-pipeline/src/nlp_pipeline/domain/enums.py`
- `services/nlp-pipeline/src/nlp_pipeline/domain/errors.py`
- `services/nlp-pipeline/tests/unit/domain/test_models.py`
- PRD §6.5 (full entity specs + invariants)

### Tasks

#### T-A-1-01: New domain enums — WindowType and DataQuality

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02, T-A-1-03]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/domain/enums.py`
**PRD reference**: §6.5 (`ArticleImpactWindow` entity block — WindowType enum + DataQuality enum)

**What to build**:
Append two new `StrEnum` classes to the existing enums module. `WindowType` has six members (four active + two reserved). `DataQuality` has two members.

**Entities**:

`WindowType(StrEnum)`:
- `DAY_T0 = "day_t0"` — publication-day OHLCV bar; cap 5.0%
- `DAY_T1 = "day_t1"` — following-day bar; cap 5.0%
- `DAY_T2 = "day_t2"` — 2-day cumulative (close_t0 → close_t2); cap 7.5%
- `DAY_T5 = "day_t5"` — 5-trading-day cumulative (close_t0 → close_t5); cap 10.0%
- `INTRADAY_1H = "intraday_1h"` — reserved, not computed
- `INTRADAY_4H = "intraday_4h"` — reserved, not computed

`DataQuality(StrEnum)`:
- `DAILY_PROXY = "daily_proxy"` — all rows computed from daily OHLCV
- `EXACT_INTRADAY = "exact_intraday"` — reserved for future intraday data

**Tests to write**:
Add to `tests/unit/domain/test_enums.py`:
| Test | Assertion | Type |
|---|---|---|
| `test_window_type_day_values` | All four day_t* enum members have expected string values | unit |
| `test_window_type_reserved_values_exist` | `intraday_1h` and `intraday_4h` members exist (no AttributeError) | unit |
| `test_data_quality_enum_values` | `daily_proxy` / `exact_intraday` values correct | unit |

**Acceptance criteria**:
- [ ] `WindowType` has 6 members matching PRD values
- [ ] `DataQuality` has 2 members
- [ ] `ruff check` passes on `enums.py`

---

#### T-A-1-02: New domain entity — ArticleImpactWindow

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-1-03]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/domain/models.py`
**PRD reference**: §6.5 `ArticleImpactWindow` entity (full attribute table + invariants + factory)

**What to build**:
Add frozen dataclass `ArticleImpactWindow` with a `compute()` class-method factory. Keep `ArticlePriceImpact` in place — it is removed in Wave 3 after the infrastructure layer is updated.

```python
@dataclass(frozen=True)
class ArticleImpactWindow:
    """One price-impact measurement for (article_id, entity_id, window_type).

    Invariants:
      - window_end > window_start
      - impact_score ∈ [0.0, 1.0]
      - price_start > 0; price_end > 0
    """
    id: UUID
    article_id: UUID
    entity_id: UUID
    symbol: str                         # 1–20 chars
    published_at: datetime              # UTC-aware
    window_type: WindowType
    window_start: datetime              # UTC-aware
    window_end: datetime                # UTC-aware, must be > window_start
    price_start: Decimal                # > 0
    price_end: Decimal                  # > 0
    delta_pct: Decimal                  # signed %
    impact_score: Decimal               # 0.0–1.0
    normalisation_cap_pct: Decimal      # > 0; per-window configurable
    data_quality: DataQuality
    high_pct: Decimal | None = None     # from OHLCV high field
    low_pct: Decimal | None = None      # from OHLCV low field
    volume: Decimal | None = None       # from OHLCV volume
    computed_at: datetime | None = None # set by DB server_default

    @classmethod
    def compute(
        cls,
        article_id: UUID,
        entity_id: UUID,
        symbol: str,
        published_at: datetime,
        window_type: WindowType,
        window_start: datetime,
        window_end: datetime,
        price_start: Decimal,
        price_end: Decimal,
        high_pct: Decimal | None,
        low_pct: Decimal | None,
        volume: Decimal | None,
        cap_pct: Decimal,
        data_quality: DataQuality = DataQuality.DAILY_PROXY,
    ) -> "ArticleImpactWindow":
        """Compute delta_pct and impact_score from raw prices."""
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        if price_start <= 0:
            raise ValueError("price_start must be > 0")
        delta = (price_end - price_start) / price_start * Decimal("100")
        score = min(Decimal("1.0"), abs(delta) / cap_pct)
        return cls(
            id=new_uuid7(),
            article_id=article_id,
            entity_id=entity_id,
            symbol=symbol,
            published_at=published_at,
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            price_start=price_start,
            price_end=price_end,
            delta_pct=delta,
            impact_score=score,
            normalisation_cap_pct=cap_pct,
            data_quality=data_quality,
            high_pct=high_pct,
            low_pct=low_pct,
            volume=volume,
        )
```

**Tests to write** (add to `tests/unit/domain/test_models.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_article_impact_window_compute_day_t0` | delta_pct = (close-open)/open*100; impact_score = min(1.0, abs(delta)/5.0) | unit |
| `test_article_impact_window_impact_score_capped` | 10% delta with 5.0 cap → impact_score = 1.0 | unit |
| `test_article_impact_window_negative_delta` | -3% delta → impact_score = 0.6 (abs value used) | unit |
| `test_article_impact_window_window_end_after_start` | window_end <= window_start → ValueError | unit |
| `test_article_impact_window_price_start_zero` | price_start = 0 → ValueError | unit |

**Acceptance criteria**:
- [ ] `ArticleImpactWindow.compute()` raises `ValueError` for invalid windows
- [ ] `impact_score` always in [0.0, 1.0]
- [ ] Frozen dataclass — no mutation possible

---

#### T-A-1-03: New value object — DisplayRelevanceScore; extend DocumentSourceMetadata

**Type**: impl
**depends_on**: [T-A-1-01, T-A-1-02]
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/domain/models.py`
**PRD reference**: §6.5 `DisplayRelevanceScore` + §6.5 `DocumentSourceMetadata` extensions

**What to build**:

1. Add `DisplayRelevanceScore` frozen dataclass with `value` property implementing the 4-branch formula from PRD §6.5. Weights are default args (not env vars at domain level — those live in config and are passed by the use case).

```python
@dataclass(frozen=True)
class DisplayRelevanceScore:
    """Composite relevance score for user-facing article ranking (PRD-0026 §6.5).

    None signals mean "data not yet available", not "zero".
    A zero market impact is factual ground-truth and must not be
    treated identically to an unlabelled article (see AD-5 in PRD).
    """
    market_impact: float | None    # MAX(day_t0, day_t1) impact_score
    llm_relevance: float | None    # LLM score; None for LIGHT or unscored
    routing_score: float | None    # composite_score from routing_decisions
    # Weights — configurable per call; defaults match PRD §6.5
    w_market: float = 0.50
    w_llm: float = 0.40
    w_routing: float = 0.10

    @property
    def value(self) -> float:
        mi = self.market_impact
        llm = self.llm_relevance
        rs = self.routing_score or 0.0
        if mi is not None and mi > 0 and llm is not None:
            return self.w_market * mi + self.w_llm * llm + self.w_routing * rs
        if mi is not None and mi > 0:
            partial_m = self.w_market + self.w_llm  # = 0.90 default → scale to 0.70/0.30
            return (self.w_market / partial_m) * 0.70 / 0.70 * mi + ... # use literal branch
            # Implemented as: 0.70 * mi + 0.30 * rs  (weights set in use case)
        if llm is not None:
            return 0.60 * llm + 0.40 * rs
        return rs * 0.40
```

**Note**: Implement the formula EXACTLY as specified in PRD §6.5. The property uses the exact 4-branch structure:
- Branch 1 (all signals): `w_market*mi + w_llm*llm + w_routing*rs`
- Branch 2 (market only): `0.70*mi + 0.30*rs` (hardcoded ratios in partial-signal branches)
- Branch 3 (llm only): `0.60*llm + 0.40*rs`
- Branch 4 (routing only): `rs * 0.40`

2. Extend `DocumentSourceMetadata` with two optional fields:
```python
llm_relevance_score: Decimal | None = None  # 0.0–1.0; null until worker runs
llm_scored_at: datetime | None = None       # UTC; null until worker runs
```

**Tests to write** (add to `tests/unit/domain/test_models.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_display_relevance_score_all_signals` | market=0.8, llm=0.6, routing=0.5 → 0.5*0.8+0.4*0.6+0.1*0.5=0.69 | unit |
| `test_display_relevance_score_market_only` | market=0.8, llm=None, routing=0.5 → 0.7*0.8+0.3*0.5=0.71 | unit |
| `test_display_relevance_score_llm_only` | market=None (not 0.0), llm=0.7, routing=0.4 → 0.6*0.7+0.4*0.4=0.58 | unit |
| `test_display_relevance_score_routing_only` | market=None, llm=None, routing=0.6 → 0.6*0.4=0.24 | unit |
| `test_display_relevance_score_no_signals` | all None/0.0 → 0.0 | unit |
| `test_display_relevance_score_zero_market_vs_none` | market=0.0 (labelled zero, mi not None but == 0) → falls to LLM-only or routing branch; NOT treated as "not available" | unit |
| `test_document_source_metadata_llm_fields_optional` | `DocumentSourceMetadata(doc_id=..., created_at=...)` works without `llm_relevance_score` | unit |

**Acceptance criteria**:
- [ ] `DisplayRelevanceScore.value` uses correct 4-branch formula
- [ ] `DocumentSourceMetadata` accepts optional `llm_relevance_score`/`llm_scored_at`
- [ ] All 12+ new domain tests pass

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/src/nlp_pipeline/domain/`
- [ ] `mypy services/nlp-pipeline/src --config-file mypy.ini`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/domain/ -m unit -v` — minimum 12 new tests pass

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/domain/test_models.py` | New classes added but import list incomplete | Add imports for `ArticleImpactWindow`, `DisplayRelevanceScore`, `WindowType`, `DataQuality` |
| `tests/unit/domain/test_enums.py` | New enum classes need test coverage | Add test cases for `WindowType` and `DataQuality` |

### Regression Guardrails
- **BP-007** (domain import guard): `ArticleImpactWindow` and `DisplayRelevanceScore` MUST NOT import anything from `nlp_pipeline.infrastructure`. Only `common.ids` and `common.time` are allowed.
- **BP-019** (DDL alignment): These domain changes require a corresponding ORM model change in Wave 3. The plan ensures this order.

---

## Wave 2: Alembic Migration 0009 — article_impact_windows + document_source_metadata ✅
**Status**: **DONE** — 2026-04-22 · migration applies cleanly · ruff + mypy clean

**Goal**: Create `article_impact_windows` table, migrate existing `article_price_impacts` data as `day_t0` rows, drop old table, add 2 columns to `document_source_metadata`, add all performance indexes.
**Depends on**: Wave 1
**Architecture layer**: infrastructure (schema)
**Estimated effort**: 30–45 min

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/alembic/versions/0008_create_llm_usage_log.py` — current head revision
- `services/nlp-pipeline/alembic/versions/0005_add_article_price_impacts.py` — old table structure
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py` — ORM models (verify alignment)
- PRD §6.4 full schema specs + §12 Migration Plan SQL

### Tasks

#### T-A-2-01: Alembic migration 0009

**Type**: schema
**depends_on**: none (within wave)
**blocks**: none
**Target files**:
- `services/nlp-pipeline/alembic/versions/0009_article_impact_windows.py` (new)
**PRD reference**: §6.4 (all table specs + index specs) + §12 Migration Plan

**What to build**:

New migration file with `revision = "0009"`, `down_revision = "0008"`.

`upgrade()` must execute in this order:
1. `CREATE TABLE article_impact_windows` — all columns from PRD §6.4 table (id UUID PK with `gen_random_uuid()`, article_id UUID NOT NULL, entity_id UUID NOT NULL, symbol TEXT NOT NULL, published_at TIMESTAMPTZ NOT NULL, window_type VARCHAR(20) NOT NULL, window_start TIMESTAMPTZ NOT NULL, window_end TIMESTAMPTZ NOT NULL, price_start NUMERIC(18,8) NOT NULL, price_end NUMERIC(18,8) NOT NULL, delta_pct NUMERIC(10,6) NOT NULL, high_pct NUMERIC(10,6) NULL, low_pct NUMERIC(10,6) NULL, volume NUMERIC(18,2) NULL, impact_score NUMERIC(6,4) NOT NULL, normalisation_cap_pct NUMERIC(6,2) NOT NULL, data_quality VARCHAR(20) NOT NULL DEFAULT 'daily_proxy', computed_at TIMESTAMPTZ NOT NULL DEFAULT now())

2. Data migration from `article_price_impacts`:
```sql
INSERT INTO article_impact_windows (
  id, article_id, entity_id, symbol, published_at,
  window_type, window_start, window_end,
  price_start, price_end, delta_pct,
  high_pct, low_pct, volume,
  impact_score, normalisation_cap_pct, data_quality, computed_at
)
SELECT
  gen_random_uuid(),
  article_id, entity_id, symbol, published_at,
  'day_t0',
  DATE_TRUNC('day', published_at)::TIMESTAMPTZ,
  (DATE_TRUNC('day', published_at) + INTERVAL '1 day')::TIMESTAMPTZ,
  price_open, price_close, price_delta_pct,
  max_intraday_range_pct, NULL, NULL,
  impact_score, 5.0, 'daily_proxy', computed_at
FROM article_price_impacts
WHERE price_open > 0;
```
**IMPORTANT**: `WHERE price_open > 0` excludes zero-sentinel rows from `ArticlePriceImpact.zero()` (PRD §12 note — zero-sentinel means OHLCV unavailable, not a valid measurement).

3. `DROP TABLE article_price_impacts`

4. Add two nullable columns to `document_source_metadata`:
```sql
ALTER TABLE document_source_metadata
  ADD COLUMN llm_relevance_score NUMERIC(6,4),
  ADD COLUMN llm_scored_at TIMESTAMPTZ;
```

5. Create indexes (use `CREATE INDEX CONCURRENTLY` for non-unique, `CREATE UNIQUE INDEX` for uniqueness constraint):
```sql
CREATE UNIQUE INDEX idx_article_impact_windows_unique
  ON article_impact_windows (article_id, entity_id, window_type);
CREATE INDEX idx_article_impact_windows_entity
  ON article_impact_windows (entity_id, window_type, published_at DESC);
CREATE INDEX idx_article_impact_windows_day_t0_score
  ON article_impact_windows (impact_score DESC)
  WHERE window_type = 'day_t0';
CREATE INDEX idx_article_impact_windows_article_id
  ON article_impact_windows (article_id);
CREATE INDEX idx_dsm_published_at
  ON document_source_metadata (published_at DESC);
CREATE INDEX idx_routing_decisions_doc_id
  ON routing_decisions (doc_id);
```

`downgrade()` must:
1. Drop all new indexes
2. DROP `article_impact_windows`
3. Re-create `article_price_impacts` table (identical to migration 0005)
4. Drop new columns from `document_source_metadata`
**Note**: Data migration is irreversible; downgrade will create empty `article_price_impacts` table.

**Downstream test impact**:
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/infrastructure/test_price_impact_repository.py` | Tests `ArticlePriceImpactRepository` which writes to `article_price_impacts` | Must update in Wave 3 alongside new repository |
| `tests/unit/infrastructure/test_ddl_alignment.py` | May assert column count/names for `document_source_metadata` | Add assertions for new columns; verify coverage (BP-019) |
| `tests/contract/test_nlp_signal_detected_schema.py` | Reads `article_price_impacts` indirectly via signals query | Will be fixed in Wave 3 |

**Acceptance criteria**:
- [ ] Migration applies cleanly on empty DB: `alembic upgrade 0009`
- [ ] Migration is reversible: `alembic downgrade 0008` succeeds
- [ ] `article_price_impacts` data with `price_open > 0` is correctly migrated as `day_t0` rows
- [ ] Unique constraint enforces `(article_id, entity_id, window_type)` — duplicate insert raises IntegrityError

### Validation Gate
- [ ] `cd services/nlp-pipeline && alembic upgrade 0009` — no errors
- [ ] `cd services/nlp-pipeline && alembic downgrade 0008` — succeeds
- [ ] `cd services/nlp-pipeline && alembic upgrade 0009` — re-apply succeeds

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/infrastructure/test_ddl_alignment.py` | `document_source_metadata` gained 2 columns; test may assert exact count | Read test, add assertions for `llm_relevance_score`/`llm_scored_at` |
| Any test fixture that creates `article_price_impacts` rows | Table no longer exists | Fixed in Wave 3 when repositories and fixtures are updated |

### Regression Guardrails
- **BP-007** (migration NOT NULL column): Both new columns on `document_source_metadata` are NULLABLE — no `server_default` needed. Correct.
- **BP-019** (DDL alignment): ORM model must be updated in Wave 3 to match this migration. Agent must verify model alignment test passes after Wave 3.
- **BP-127** (alembic head check): After committing this wave, running `alembic heads` must show exactly `0009` as the head. No branch splits.

---

## Wave 3: Infrastructure — ORM Model, Repositories, Signals Query Update ✅
**Status**: **DONE** — 2026-04-22 · 480 tests pass (+14 new) · ruff + mypy clean

**Goal**: Replace `ArticlePriceImpactModel` with `ArticleImpactWindowModel`, add new `ArticleImpactWindowRepository`, update `SignalsQueryPort` and `SqlaSignalsQueryRepo` to use new table, update DDL alignment tests.
**Depends on**: Wave 2
**Architecture layer**: infrastructure
**Estimated effort**: 45–60 min

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/price_impact.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/signals_query.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py`
- `services/nlp-pipeline/tests/unit/infrastructure/test_price_impact_repository.py`
- `services/nlp-pipeline/tests/unit/infrastructure/test_ddl_alignment.py`
- PRD §6.4 + §6.5

### Tasks

#### T-A-3-01: ORM model — replace ArticlePriceImpactModel with ArticleImpactWindowModel

**Type**: impl
**depends_on**: none (within wave)
**blocks**: [T-A-3-02, T-A-3-03]
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py`
**PRD reference**: §6.4 `article_impact_windows` table spec

**What to build**:
1. Remove `ArticlePriceImpactModel` class
2. Add `ArticleImpactWindowModel` class that maps to `article_impact_windows`:

```python
class ArticleImpactWindowModel(Base):
    """Multi-window price-impact measurements (PRD-0026 §6.4, migration 0009).

    One row per (article_id, entity_id, window_type). Replaces article_price_impacts.
    UNIQUE on (article_id, entity_id, window_type) — enforced by idx_article_impact_windows_unique.
    """
    __tablename__ = "article_impact_windows"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()"))
    article_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_type: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_start: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8), nullable=False)
    price_end: Mapped[Decimal] = mapped_column(sa.Numeric(18, 8), nullable=False)
    delta_pct: Mapped[Decimal] = mapped_column(sa.Numeric(10, 6), nullable=False)
    high_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    low_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    impact_score: Mapped[Decimal] = mapped_column(sa.Numeric(6, 4), nullable=False)
    normalisation_cap_pct: Mapped[Decimal] = mapped_column(sa.Numeric(6, 2), nullable=False)
    data_quality: Mapped[str] = mapped_column(VARCHAR(20), nullable=False, server_default="daily_proxy")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

3. Add two new columns to `DocumentSourceMetadataModel`:
```python
llm_relevance_score: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 4), nullable=True)
llm_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Acceptance criteria**:
- [ ] `ArticlePriceImpactModel` removed; `ArticleImpactWindowModel` added
- [ ] `DocumentSourceMetadataModel` has `llm_relevance_score` + `llm_scored_at`
- [ ] DDL alignment test passes after update

---

#### T-A-3-02: New repository — ArticleImpactWindowRepository

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/impact_window.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py` (add port ABC)
**PRD reference**: §6.5 worker phases (upsert pattern + get_unlabelled_details)

**What to build**:

Port ABC in `repositories.py`:
```python
class ArticleImpactWindowRepositoryPort(ABC):
    @abstractmethod
    async def upsert_batch(self, windows: list[ArticleImpactWindow]) -> None: ...
    @abstractmethod
    async def get_articles_needing_windows(
        self, min_age_hours: int, batch_size: int
    ) -> list[tuple[UUID, UUID, str, datetime]]: ...  # (doc_id, entity_id, symbol, published_at)
```

Infrastructure implementation in `impact_window.py`:
- `upsert_batch`: bulk INSERT with `ON CONFLICT (article_id, entity_id, window_type) DO NOTHING`
- `get_articles_needing_windows`: complex EXISTS subquery from PRD §6.7 Flow A (Phase 1) — finds article/entity pairs where at least one window (day_t0/t1/t2/t5) is due but missing. Uses the multi-VALUES subquery pattern from PRD.

**Tests to write** (new file `tests/unit/infrastructure/test_impact_window_repository.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_upsert_batch_inserts_rows` | Batch of 3 windows → 3 rows in table | unit |
| `test_upsert_batch_idempotent` | Duplicate (article_id, entity_id, window_type) → no error, count unchanged | unit |
| `test_get_articles_needing_windows_returns_due_articles` | Article aged >25h with no day_t0 row → returned | unit |
| `test_get_articles_needing_windows_respects_batch_size` | 5 articles due → returns at most batch_size | unit |

**Acceptance criteria**:
- [ ] Port ABC defined in `repositories.py`
- [ ] `ON CONFLICT DO NOTHING` prevents duplicates
- [ ] Batch size limit respected

---

#### T-A-3-03: Update SqlaSignalsQueryRepo to use ArticleImpactWindowModel

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**: `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/signals_query.py`
**PRD reference**: §6.5 DisplayRelevanceScore formula (market_impact = MAX(day_t0, day_t1))

**What to build**:
Update `list_signal_events` to JOIN `article_impact_windows` (WHERE `window_type = 'day_t0'`) instead of `article_price_impacts`. The `impact_score` column semantics are identical — just the table name changes. Use DISTINCT to avoid duplicate signals if multiple day_t0 rows exist.

Also update the `min_impact_score` filter and `order_by=market_impact_score` sort to use the new table.

**Tests to write**: Update existing `tests/unit/api/test_signals.py` and `tests/unit/application/use_cases/test_signals.py` if they reference `ArticlePriceImpactModel` or `article_price_impacts` directly.

**Acceptance criteria**:
- [ ] Signals query returns correct `impact_score` from `article_impact_windows.window_type = 'day_t0'`
- [ ] No import of `ArticlePriceImpactModel` remains in any file outside migration 0005

---

#### T-A-3-04: Update DDL alignment tests

**Type**: test
**depends_on**: [T-A-3-01]
**blocks**: none
**Target files**: `services/nlp-pipeline/tests/unit/infrastructure/test_ddl_alignment.py`
**PRD reference**: §6.4

**What to build**:
1. Replace `ArticlePriceImpactModel` DDL alignment test with `ArticleImpactWindowModel`
2. Add `document_source_metadata` column count/name assertions for `llm_relevance_score` + `llm_scored_at`
3. Audit ALL other tables in S6 for missing DDL alignment tests (BP rule: add missing ones)

**Acceptance criteria**:
- [ ] `test_ddl_alignment.py` has coverage for `article_impact_windows` (new table)
- [ ] `test_ddl_alignment.py` has coverage for new columns on `document_source_metadata`
- [ ] No references to `article_price_impacts` in alignment tests

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/src/nlp_pipeline/infrastructure/`
- [ ] `mypy services/nlp-pipeline/src --config-file mypy.ini`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/ -m unit -v` — all pass
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/infrastructure/test_ddl_alignment.py -v`

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/infrastructure/test_price_impact_repository.py` | Tests `ArticlePriceImpactRepository` which no longer exists | Replace with `test_impact_window_repository.py` |
| `tests/unit/api/test_signals.py` | `list_signal_events` joins new table | Update mock fixtures to use `ArticleImpactWindowModel` |
| `tests/unit/application/use_cases/test_signals.py` | Same | Update mock |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/price_impact.py` | Old repository; must be deleted or archived | Delete; update all imports |
| `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` entry | Imports `ArticlePriceImpactRepository` | Fixed in Wave 4 |

### Regression Guardrails
- **BP-019** (DDL alignment): After this wave, `ArticleImpactWindowModel` must map 1:1 to migration 0009. Run alignment test.
- **BP-007** (layer isolation): `repositories/signals_query.py` imports only `infrastructure/nlp_db/models.py`. No domain imports in infrastructure allowed.

---

## Wave 4: Updated PriceImpactLabellingWorker — 4 Windows

**Goal**: Extend `PriceImpactLabellingWorker` to compute all 4 daily windows (day_t0, day_t1, day_t2, day_t5) with cumulative logic, switch from writing to `article_price_impacts` → `article_impact_windows`, update worker entrypoint.
**Depends on**: Wave 3
**Architecture layer**: infrastructure (worker)
**Estimated effort**: 45–60 min

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` (entrypoint)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/http/market_data_client.py`
- `services/nlp-pipeline/tests/unit/infrastructure/test_price_impact_labelling_worker.py`
- PRD §6.7 Flow A (full Phase 1/2/3 with cumulative window logic)

### Tasks

#### T-A-4-01: Extend PriceImpactLabellingWorker for 4 windows

**Type**: impl
**depends_on**: none (within wave)
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py`
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (new cap config vars)
**PRD reference**: §6.7 Flow A + §6.5 `PriceImpactLabellingWorker` changes + §3.1 F-05/F-06/F-07/F-09

**What to build**:

**New config vars** (add to `Settings` in `config.py`):
```python
price_impact_cap_day_t0_pct: float = 5.0   # S6_CAP_DAY_T0_PCT
price_impact_cap_day_t1_pct: float = 5.0   # S6_CAP_DAY_T1_PCT
price_impact_cap_day_t2_pct: float = 7.5   # S6_CAP_DAY_T2_PCT
price_impact_cap_day_t5_pct: float = 10.0  # S6_CAP_DAY_T5_PCT
```

**Worker changes**:
1. Replace `ArticlePriceImpactRepository` with `ArticleImpactWindowRepository`
2. Replace `ArticlePriceImpact` with `ArticleImpactWindow`
3. Phase 1 — Read: use `get_articles_needing_windows()` (returns article/entity pairs where at least one window is due but missing)
4. Phase 2 — HTTP (no open DB session, R24):
   - For each (article, entity) pair, compute all due windows:
   - `day_t0` available after `published_at + 25h`: `bar_date = publication_date`; `price_start = bar.open`, `price_end = bar.close`
   - `day_t1` available after `published_at + 49h`: `bar_date = publication_date + 1 trading day`; `price_start = bar.open`, `price_end = bar.close`
   - `day_t2` available after `published_at + 73h`: **cumulative** — fetch day_t0 bar first to get `close_t0`; `bar_date_t2 = publication_date + 2 trading days`; `price_start = close_t0`, `price_end = t2_bar.close`
   - `day_t5` available after `published_at + 145h`: **cumulative** — reuse `close_t0`; `bar_date_t5 = publication_date + 5 trading days`; `price_start = close_t0`, `price_end = t5_bar.close`
   - If day_t0 bar unavailable (404): skip ALL windows for this article/entity (can't compute cumulative without baseline)
   - Throttle: `asyncio.sleep(0.1)` between per-symbol HTTP calls
5. Phase 3 — Write: batch INSERT via `upsert_batch()` with `ON CONFLICT DO NOTHING`

**Key logic detail — trading day offset**: Use calendar days as a proxy (`timedelta(days=N)`) for simplicity at thesis scale. OHLCV endpoint returns 404 for non-trading days; worker skips those windows. No need to compute exact NYSE/LSE trading day calendars.

**Tests to write** (add to `tests/unit/infrastructure/test_price_impact_labelling_worker.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_labelling_worker_computes_all_four_windows` | Article aged 200h → 4 `ArticleImpactWindow` objects created | unit |
| `test_labelling_worker_defers_day_t1_if_too_soon` | Article aged 30h → only day_t0 created | unit |
| `test_labelling_worker_defers_day_t2_day_t5_if_too_soon` | Article aged 50h → day_t0 + day_t1 only | unit |
| `test_labelling_worker_cumulative_window_uses_t0_close` | day_t2 `price_start = close_t0` (bar.close of day_t0); NOT bar.open of day_t2 | unit |
| `test_labelling_worker_skips_cumulative_if_t0_unavailable` | day_t0 returns 404 → day_t2 and day_t5 also skipped | unit |
| `test_labelling_worker_idempotent_multi_window` | Calling twice produces no duplicate windows | unit |
| `test_labelling_worker_r24_no_session_during_http` | DB session is closed before HTTP calls (use session factory mock to verify open/close order) | unit |

**Acceptance criteria**:
- [ ] 4 windows computed for aged article
- [ ] Cumulative windows use `close_t0` as `price_start`
- [ ] `ON CONFLICT DO NOTHING` prevents duplicates
- [ ] R24: session closed before any `asyncio.sleep(0.1)` HTTP calls

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/src/`
- [ ] `mypy services/nlp-pipeline/src --config-file mypy.ini`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/ -m unit -v`

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/infrastructure/test_price_impact_labelling_worker.py` | Old tests reference `ArticlePriceImpact`/`ArticlePriceImpactRepository` | Replace all references with new classes |
| `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/price_impact.py` | Old file, now orphaned | Delete file |

### Regression Guardrails
- **BP-069** (asyncpg None binding): Worker uses conditional WHERE clauses via `get_articles_needing_windows()`. Never bind `None` as a named param in equality expressions.
- **BP-019** (DDL alignment): `ArticleImpactWindowModel` must have been added in Wave 3. Confirm import works before running.
- **R24** (no DB session across external I/O): DB session MUST be closed before HTTP calls. Verify via test mock.

---

## Wave 5: ArticleRelevanceScoringWorker — LLM Relevance Scoring

**Goal**: Implement `ArticleRelevanceScoringWorker` (new independent process, R22) using Qwen2.5:3b via Ollama. Three-phase loop (read → score via Ollama → write). Add config vars, docker-compose entry.
**Depends on**: Wave 3
**Architecture layer**: infrastructure (worker)
**Estimated effort**: 45–60 min
**Note**: Wave 4 and Wave 5 can be executed in parallel (no shared files).

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/price_impact_labelling_worker.py` (pattern)
- `services/nlp-pipeline/src/nlp_pipeline/workers/price_impact_labelling_worker.py` (entrypoint pattern)
- `services/nlp-pipeline/src/nlp_pipeline/config.py`
- `infra/compose/docker-compose.yml` — existing S6 service entries
- PRD §6.5 `ArticleRelevanceScoringWorker` + §6.7 Flow B + §3.2 F-10..F-18

### Tasks

#### T-A-5-01: ArticleRelevanceScoringWorker implementation

**Type**: impl
**depends_on**: none (within wave)
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/workers/article_relevance_scoring_worker.py` (new entrypoint)
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (new config vars)
- `infra/compose/docker-compose.yml` (new service entry for relevance scoring worker)
**PRD reference**: §6.5 worker spec + prompt spec + §6.7 Flow B

**What to build**:

**New config vars** (append to `Settings`):
```python
relevance_scoring_cycle_seconds: int = 1800       # RELEVANCE_SCORING_CYCLE_SECONDS
relevance_scoring_batch_size: int = 50             # RELEVANCE_SCORING_BATCH_SIZE
relevance_scoring_ollama_url: str = "http://ollama:11434"  # RELEVANCE_SCORING_OLLAMA_URL
relevance_scoring_model: str = "qwen2.5:3b"       # RELEVANCE_SCORING_MODEL
relevance_scoring_timeout_seconds: int = 30        # RELEVANCE_SCORING_TIMEOUT_SECONDS
s6_display_weight_market: float = 0.50             # S6_DISPLAY_WEIGHT_MARKET
s6_display_weight_llm: float = 0.40               # S6_DISPLAY_WEIGHT_LLM
s6_display_weight_routing: float = 0.10           # S6_DISPLAY_WEIGHT_ROUTING
```

**Worker class** `ArticleRelevanceScoringWorker`:
- Constructor: `__init__(nlp_session_factory, ollama_url, model, batch_size, timeout_seconds, cycle_seconds)`
- Three-phase `scoring_cycle()` (R24: no DB session open during Ollama calls):

  **Phase 1 — Read** (open session → close):
  ```sql
  SELECT dsm.doc_id, dsm.title, dsm.source_type
  FROM document_source_metadata dsm
  JOIN routing_decisions rd ON rd.doc_id = dsm.doc_id
  WHERE dsm.llm_relevance_score IS NULL
    AND COALESCE(rd.final_routing_tier, rd.routing_tier) IN ('MEDIUM', 'DEEP')
  ORDER BY dsm.published_at DESC
  LIMIT :batch_size
  ```
  Collect `[(doc_id, title, source_type)]` and close session.

  **Phase 2 — Score** (no open sessions):
  For each article, build prompt and POST to Ollama:
  - `POST {ollama_url}/api/generate` with `{"model": model, "prompt": "...", "format": "json", "stream": false}`
  - Timeout: `timeout_seconds`
  - Parse JSON: `{"score": <float>, "reason": "<str>"}`
  - Clamp score: `max(0.0, min(1.0, score))`
  - On `json.JSONDecodeError`: log warning with `article_id + raw_response[:200]`; skip article
  - On `httpx.ConnectError` or timeout: skip entire cycle, log warning

  **LLM Prompt** (exact from PRD §6.5):
  ```
  System: You are a financial news relevance assessor. Rate the market impact of this news article from 0.0 to 1.0.
  [scoring scale as in PRD]
  Respond with ONLY valid JSON: {"score": <float 0.0-1.0>, "reason": "<max 10 words>"}
  User: Title: {title}
  Source: {source_type}
  ```

  **Phase 3 — Write** (open new session → commit → close):
  ```sql
  UPDATE document_source_metadata
  SET llm_relevance_score = :score, llm_scored_at = NOW()
  WHERE doc_id = :doc_id
  ```

- `run_forever(stop_event)`: run `scoring_cycle()` immediately, then loop on `cycle_seconds`

**Entrypoint** `workers/article_relevance_scoring_worker.py`:
Follow exact same pattern as `price_impact_labelling_worker.py` entrypoint — SIGTERM handler, structured logging, exit code 0 on clean shutdown / 1 on startup failure.

**docker-compose.yml**: Add new service entry in S6 section:
```yaml
nlp-pipeline-relevance-scoring:
  <<: *nlp-pipeline-common
  command: python -m nlp_pipeline.workers.article_relevance_scoring_worker
  depends_on:
    nlp-pipeline-db:
      condition: service_healthy
    ollama:
      condition: service_healthy
```

**Tests to write** (new file `tests/unit/infrastructure/workers/test_article_relevance_scoring_worker.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_relevance_worker_parses_valid_json` | `{"score": 0.75, "reason": "CEO change"}` → `llm_relevance_score = 0.75` | unit |
| `test_relevance_worker_clamps_out_of_range_score` | `{"score": 1.5}` → clamped to `1.0` | unit |
| `test_relevance_worker_clamps_negative_score` | `{"score": -0.2}` → clamped to `0.0` | unit |
| `test_relevance_worker_skips_on_json_error` | `"not json"` → article skipped, no DB update | unit |
| `test_relevance_worker_skips_light_tier` | LIGHT tier article not in Phase 1 query results | unit |
| `test_relevance_worker_uses_effective_routing_tier` | Article with `routing_tier='DEEP', final_routing_tier='LIGHT'` excluded (uses COALESCE) | unit |
| `test_relevance_worker_r24_no_session_during_ollama` | DB session closed before `POST /api/generate` (mock session factory) | unit |
| `test_relevance_worker_handles_ollama_connect_error` | `httpx.ConnectError` → skip cycle, log warning, no exception raised | unit |

**Acceptance criteria**:
- [ ] Three-phase loop with R24 compliance (no session during HTTP)
- [ ] JSON parse failure gracefully skips article
- [ ] Score clamped to [0.0, 1.0] always
- [ ] `COALESCE(rd.final_routing_tier, rd.routing_tier)` used for tier check (not just `routing_tier`)
- [ ] docker-compose.yml updated with new service

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/src/nlp_pipeline/infrastructure/workers/article_relevance_scoring_worker.py`
- [ ] `mypy services/nlp-pipeline/src --config-file mypy.ini`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/infrastructure/workers/ -m unit -v` — 8+ new tests pass
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/test_entrypoints.py -v` — new entrypoint detected

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/test_entrypoints.py` | May check list of entrypoint modules | Add `article_relevance_scoring_worker` to expected list |
| `services/nlp-pipeline/configs/dev.local.env.example` | New env vars not documented | Add all 8 new config vars with defaults |

### Regression Guardrails
- **R22** (independent process): Worker must be a standalone process with its own entrypoint (`__main__`), not a background thread in the API process.
- **R24** (no blocking I/O in async with open session): Phase 2 must run with no open DB sessions. Verify via test.
- **BP-025** (external HTTP timeouts): All Ollama calls must have explicit timeout (30s configured).

---

## Wave 6: S6 API Endpoints — GetTopNewsUseCase + Enhanced GetEntityArticlesUseCase

**Goal**: Implement `GetTopNewsUseCase` (new), enhance `GetEntityArticlesUseCase` with scoring fields, add `GET /api/v1/news/top` router, update `GET /api/v1/entities/{id}/articles` router and schemas.
**Depends on**: Wave 4 (repository in place) and Wave 5 (scoring columns exist)
**Architecture layer**: application + API
**Estimated effort**: 60–90 min

### Pre-read (agent must read before starting)
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/signals.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py`
- `services/nlp-pipeline/src/nlp_pipeline/api/dependencies.py`
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/signals_query.py`
- PRD §6.2 (full API spec — both endpoints + RankedArticle schema) + §6.7 Flow C + §6.7 Flow D

### Tasks

#### T-A-6-01: Port interfaces and use case DTOs

**Type**: impl
**depends_on**: none (within wave)
**blocks**: [T-A-6-02, T-A-6-03]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/application/ports/repositories.py`
- `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/signals.py`
**PRD reference**: §6.2 `RankedArticle` schema + §6.7 Flow C + Flow D

**What to build**:

Add port ABC for news queries:
```python
class NewsQueryPort(ABC):
    @abstractmethod
    async def get_top_news(
        self, hours: int, limit: int, offset: int,
        min_display_score: float | None, routing_tier: str | None,
    ) -> tuple[list[RankedArticleData], int]: ...

    @abstractmethod
    async def get_entity_articles(
        self, entity_id: UUID, start_date: datetime, end_date: datetime,
        order_by: str, limit: int, offset: int,
    ) -> tuple[list[RankedArticleData], int]: ...
```

Add result DTO:
```python
@dataclasses.dataclass(frozen=True)
class RankedArticleData:
    article_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_type: str | None
    source_name: str | None
    routing_tier: str | None
    routing_score: float | None
    market_impact_score: float | None
    llm_relevance_score: float | None
    display_relevance_score: float
    day_t0_score: float | None
    day_t1_score: float | None
    day_t2_score: float | None
    day_t5_score: float | None
    primary_entity_id: UUID | None = None      # global feed only
    primary_entity_symbol: str | None = None   # global feed only
```

Add two use cases:
- `GetTopNewsUseCase(news_query_port: NewsQueryPort)` — calls `port.get_top_news(...)`, no business logic
- `GetEntityArticlesUseCase` (enhance existing) — add scoring fields to result

**Acceptance criteria**:
- [ ] Port ABCs defined
- [ ] Use cases only import from domain + application layers (R25)
- [ ] Both use cases accept `ReadOnlyUnitOfWork` (R27)

---

#### T-A-6-02: SQL implementation — SqlaNewsQueryRepo

**Type**: impl
**depends_on**: [T-A-6-01]
**blocks**: [T-A-6-03]
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/repositories/news_query.py` (new)
**PRD reference**: §6.7 Flow C (top news CTE SQL) + §6.7 Flow D (entity articles CTE SQL)

**What to build**:
Implement `SqlaNewsQueryRepo` with two methods using raw SQL via `text()`:

**`get_top_news()`**: Execute the 3-CTE query from PRD §6.7 Flow C:
- CTE 1: `article_market_impact` — pivot all 4 windows; compute `GREATEST(day_t0, day_t1)` as `market_impact_score`
- CTE 2: `article_primary_entity` — DISTINCT ON to find entity with highest day_t0 score per article
- Main query: SELECT from `document_source_metadata` LEFT JOIN CTEs + `routing_decisions`; compute `display_relevance_score` CASE; COUNT(*) OVER(); ORDER BY `display_relevance_score DESC, published_at DESC`; LIMIT/OFFSET
- Bind params: `:hours` (interval), `:routing_tier` (nullable — use `(:routing_tier IS NULL OR ...)` pattern per BP-069), `:min_display_score` (nullable — same pattern), `:limit`, `:offset`

**`get_entity_articles()`**: Execute the 2-CTE query from PRD §6.7 Flow D:
- CTE 1: `entity_article_ids` — DISTINCT doc_id from `entity_mentions` WHERE `resolved_entity_id = :entity_id`
- CTE 2: `article_windows` — same pivot as Flow C for articles in entity scope
- Main query: JOIN `document_source_metadata` + `routing_decisions`; same CASE formula; ORDER BY conditional (published_at vs display_relevance_score); COUNT(*) OVER()
- Bind params: `:entity_id`, `:start_date`, `:end_date`, `:order_by`, `:limit`, `:offset`

**Critical**: Never bind `None` as a param in `=` equality expressions (BP-069). Use conditional WHERE clause building for nullable filters.

**Tests to write** (new file `tests/unit/infrastructure/test_news_query_repo.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_get_top_news_sql_hour_filter` | SQL contains `published_at >= now() - :hours * interval '1 hour'` or equivalent | unit |
| `test_get_top_news_routing_tier_null_not_bound` | When `routing_tier=None`, SQL has no `:routing_tier` equality expression | unit |
| `test_get_entity_articles_uses_entity_cte` | SQL contains `entity_mentions` CTE join | unit |

**Acceptance criteria**:
- [ ] BP-069 compliant — no `None` in equality params
- [ ] Both CTEs use DISTINCT ON pattern for `article_primary_entity`

---

#### T-A-6-03: Router + Schemas

**Type**: impl
**depends_on**: [T-A-6-01, T-A-6-02]
**blocks**: none
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/news.py` (new)
- `services/nlp-pipeline/src/nlp_pipeline/api/routes/signals.py` (update entity articles endpoint)
- `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` (new response models)
- `services/nlp-pipeline/src/nlp_pipeline/api/dependencies.py` (new NewsQueryRepoDep)
- `services/nlp-pipeline/src/nlp_pipeline/main.py` (register news router)
**PRD reference**: §6.2 both endpoints — full param tables, response model, error responses

**What to build**:

**New Pydantic schemas** in `schemas.py`:
```python
class ImpactWindows(BaseModel):
    day_t0: float | None
    day_t1: float | None
    day_t2: float | None
    day_t5: float | None

class RankedArticleResponse(BaseModel):
    article_id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_type: str | None
    source_name: str | None
    routing_tier: str | None
    routing_score: float | None
    market_impact_score: float | None
    llm_relevance_score: float | None
    display_relevance_score: float
    primary_entity_id: UUID | None = None
    primary_entity_symbol: str | None = None
    impact_windows: ImpactWindows | None

class RankedNewsResponse(BaseModel):
    articles: list[RankedArticleResponse]
    total: int
```

**New router** `api/routes/news.py`:
```python
@router.get("/news/top", response_model=RankedNewsResponse)
async def get_top_news(
    repo: NewsQueryRepoDep,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    min_display_score: float | None = Query(default=None, ge=0.0, le=1.0),
    routing_tier: str | None = Query(default=None, pattern="^(LIGHT|MEDIUM|DEEP)$"),
) -> RankedNewsResponse:
    ...
```
No authentication required (public endpoint, consistent with existing S9 proxy config).

**Update `signals.py`** entity articles endpoint:
- Replace `GetEntityArticlesUseCase` call to use enhanced version with scoring
- Update response model to `RankedNewsResponse`
- Add `start_date`, `end_date`, `order_by` query params per PRD §6.2

**Register router** in `main.py`.

**Tests to write** (new file `tests/unit/api/test_news.py`):
| Test | Assertion | Type |
|---|---|---|
| `test_get_top_news_returns_200` | `GET /api/v1/news/top` → 200 with `articles` + `total` | unit |
| `test_get_top_news_hours_validation` | `hours=200` → 422 | unit |
| `test_get_top_news_limit_validation` | `limit=0` → 422; `limit=101` → 422 | unit |
| `test_get_top_news_routing_tier_invalid` | `routing_tier=INVALID` → 422 | unit |
| `test_get_entity_articles_date_range` | `start_date > end_date` → 422 | unit |
| `test_get_entity_articles_empty_returns_zero` | Unknown entity_id → `{articles: [], total: 0}` (not 404) | unit |
| `test_get_entity_articles_order_by_published_at` | `order_by=published_at` accepted | unit |

**Acceptance criteria**:
- [ ] `GET /api/v1/news/top` registered and returns `RankedNewsResponse`
- [ ] `GET /api/v1/entities/{id}/articles` enhanced with new params + scoring fields
- [ ] Both use `ReadOnlyUnitOfWork` (R27)

### Validation Gate
- [ ] `ruff check services/nlp-pipeline/src/nlp_pipeline/api/`
- [ ] `mypy services/nlp-pipeline/src --config-file mypy.ini`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/api/ -m unit -v`
- [ ] `python -m pytest services/nlp-pipeline/tests/unit/ -m unit -v` — no regressions

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `tests/unit/api/test_entities.py` | `GET /entities/{id}/articles` response schema changed | Update assertions to include new scoring fields |
| `services/nlp-pipeline/src/nlp_pipeline/api/schemas.py` | `EntityArticleResponse` / `EntityArticlesResponse` now replaced by `RankedArticleResponse` | Update or retain old schemas with migration note |

### Regression Guardrails
- **R25** (API layer isolation): `news.py` router MUST NOT import from `infrastructure/`. Use port + dependency injection via `NewsQueryRepoDep`.
- **R27** (read-only UoW for reads): Both endpoints are read-only → use `ReadOnlyUnitOfWork`.
- **BP-069** (asyncpg None param): `SqlaNewsQueryRepo` must build conditional WHERE clauses for nullable params.

---

## Wave 7: S9 Proxy Retarget — news/top and news/entity

**Goal**: Retarget S9's `GET /v1/news/top` and `GET /v1/news/entity/{entity_id}` from S5 (Content Store) to S6 (NLP Pipeline). Update auth handling (public vs authenticated). Update tests.
**Depends on**: Wave 6 (S6 endpoints exist)
**Architecture layer**: API (gateway)
**Estimated effort**: 20–30 min

### Pre-read (agent must read before starting)
- `services/api-gateway/src/api_gateway/routes/proxy.py` lines 699–745 (current TODO stubs)
- `services/api-gateway/tests/test_s9_wave1_proxy.py` lines 240–470 (existing news proxy tests)
- PRD §6.2 S9 proxy table + §3.4 F-25/F-26

### Tasks

#### T-A-7-01: Retarget S9 news proxy routes

**Type**: impl
**depends_on**: none (within wave)
**blocks**: none
**Target files**:
- `services/api-gateway/src/api_gateway/routes/proxy.py`
- `services/api-gateway/tests/test_s9_wave1_proxy.py`
**PRD reference**: §3.4 F-25/F-26 + §6.2 S9 Proxy Routes table

**What to build**:

Update `get_news_top()` (line ~702):
- Remove TODO(PRD-0026) comment
- Change backend from `clients.content_store` to `clients.nlp_pipeline` (or equivalent S6 client name — check `_clients()` function)
- Change path from `/v1/articles/relevant` to `/api/v1/news/top`
- Keep public (no auth required) — system JWT only

Update `get_news_entity()` (line ~722):
- Remove TODO(PRD-0026) comment
- Change backend from `clients.content_store` to `clients.nlp_pipeline`
- Change path from `/v1/articles` with `entity_id` query param to `/api/v1/entities/{entity_id}/articles` (path-based)
- Keep auth required (`request.state.user` check)
- Forward all query params unchanged (start_date, end_date, order_by, limit, offset)

**Tests to update** in `test_s9_wave1_proxy.py`:
- `test_news_top_no_auth`: update mock from `content_store` to S6 client; verify new path `/api/v1/news/top`
- `test_news_entity_proxied`: update mock from `content_store` to S6 client; verify path `/api/v1/entities/{entity_id}/articles` (NOT query param)
- `test_news_top_backend_error`: update client mock
- `test_news_top_system_jwt`: update path assertion

**Acceptance criteria**:
- [ ] `GET /v1/news/top` → S6 `/api/v1/news/top` (no path change)
- [ ] `GET /v1/news/entity/{id}` → S6 `/api/v1/entities/{id}/articles` (path rewrite, not query param)
- [ ] TODO(PRD-0026) comments removed
- [ ] All `test_s9_wave1_proxy.py` news tests pass

### Validation Gate
- [ ] `ruff check services/api-gateway/src/`
- [ ] `mypy services/api-gateway/src --config-file mypy.ini`
- [ ] `python -m pytest services/api-gateway/tests/test_s9_wave1_proxy.py -v`
- [ ] `python -m pytest services/api-gateway/tests/ -m unit -v` — no regressions

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| `services/api-gateway/tests/test_s9_wave1_proxy.py` | All news proxy tests assert S5 backend and old paths | Update all 5 news proxy tests |

### Regression Guardrails
- **BP-026** (path rewrite correctness): The entity path rewrite from `/news/entity/{id}` → `/entities/{id}/articles` must not pass `entity_id` as a query param. Verify no `params["entity_id"]` in the updated code.
- Confirm the S6 client name in `_clients()` — check `proxy.py` to find how NLP Pipeline is referenced.

---

## Wave 8: Frontend Types and API Client

**Goal**: Add `RankedArticle`, `ImpactWindows`, `RankedNewsResponse`, `TopNewsParams`, `EntityNewsParams` TypeScript interfaces and `getTopNews()`, `getEntityNews()` methods to `apps/worldview-web/lib/gateway-client.ts`.
**Depends on**: Wave 7 (S9 routes available)
**Architecture layer**: frontend
**Estimated effort**: 20–30 min

### Pre-read (agent must read before starting)
- `apps/worldview-web/lib/gateway-client.ts` — existing pattern for `request<T>()` + `buildQuery()`
- `apps/worldview-web/__tests__/` — existing test patterns
- PRD §6.6 Frontend Changes (exact TypeScript interface definitions)

### Tasks

#### T-A-8-01: Frontend types + API client methods

**Type**: impl
**depends_on**: none (within wave)
**blocks**: none
**Target files**:
- `apps/worldview-web/lib/gateway-client.ts`
**PRD reference**: §6.6 full TypeScript interface definitions + method signatures

**What to build**:

Add exactly these interfaces and methods from PRD §6.6 (with heavy inline comments explaining each field — user is new to Next.js):

```typescript
// Represents per-window price impact scores.
// null = window not yet computed (article too recent or OHLCV unavailable).
export interface ImpactWindows {
  day_t0: number | null;   // Publication-day OHLCV impact
  day_t1: number | null;   // Following-day impact
  day_t2: number | null;   // 2-day cumulative impact
  day_t5: number | null;   // 5-trading-day cumulative impact
}

// A news article with computed relevance scores.
// display_relevance_score = weighted composite of market, LLM, and routing signals.
export interface RankedArticle {
  article_id: string;
  title: string | null;
  url: string | null;
  published_at: string | null;          // ISO-8601 UTC
  source_type: string | null;           // e.g. "eodhd_news"
  source_name: string | null;           // e.g. "EODHD"
  routing_tier: string | null;          // "LIGHT" | "MEDIUM" | "DEEP"
  routing_score: number | null;
  market_impact_score: number | null;   // null if no windows computed yet
  llm_relevance_score: number | null;   // null for LIGHT tier or unscored
  display_relevance_score: number;      // always 0.0–1.0
  primary_entity_id: string | null;     // global feed only — top entity
  primary_entity_symbol: string | null; // global feed only — ticker of top entity
  impact_windows: ImpactWindows | null;
}

export interface RankedNewsResponse {
  articles: RankedArticle[];
  total: number;
}

export interface TopNewsParams {
  hours?: number;               // 1–168, default 24
  limit?: number;               // 1–100, default 20
  offset?: number;
  min_display_score?: number;   // 0.0–1.0
  routing_tier?: 'LIGHT' | 'MEDIUM' | 'DEEP';
}

export interface EntityNewsParams {
  start_date?: string;          // ISO-8601 UTC
  end_date?: string;            // ISO-8601 UTC
  order_by?: 'display_relevance_score' | 'published_at';
  limit?: number;
  offset?: number;
}
```

Methods on `gateway` object (add alongside existing methods):
```typescript
getTopNews: (params?: TopNewsParams) =>
  request<RankedNewsResponse>(`/v1/news/top?${buildQuery(params)}`),

getEntityNews: (entityId: string, params?: EntityNewsParams) =>
  request<RankedNewsResponse>(`/v1/news/entity/${entityId}?${buildQuery(params)}`),
```

**Tests to write** (add to `apps/worldview-web/__tests__/utils.test.ts` or new file):
| Test | Assertion | Type |
|---|---|---|
| `test_get_top_news_builds_correct_url` | `getTopNews({hours: 48, limit: 10})` calls correct S9 path with params | unit |
| `test_get_entity_news_includes_entity_id_in_path` | `getEntityNews('abc-123', {limit: 5})` calls `/v1/news/entity/abc-123?limit=5` | unit |
| `test_ranked_article_type_has_all_fields` | TypeScript compilation verifies interface completeness | type |

**Acceptance criteria**:
- [ ] All 5 TypeScript interfaces added
- [ ] `getTopNews()` and `getEntityNews()` methods added to `gateway` object
- [ ] Heavy inline comments on each field (user is new to Next.js — memory feedback)
- [ ] TypeScript compiles: `pnpm type-check` passes
- [ ] Tests pass: `pnpm test`

### Validation Gate
- [ ] `pnpm --filter worldview-web type-check`
- [ ] `pnpm --filter worldview-web test`
- [ ] `pnpm --filter worldview-web lint`

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| None | Pure additions — no existing code changed | — |

### Regression Guardrails
- **Memory: Frontend pnpm enforcement** — use exact versions, `pnpm` only, no `^` prefix. If adding any packages, ensure `pnpm audit 0 CVEs`.
- **Memory: Frontend code comment density** — ALL interface fields must have JSDoc comments explaining the "why" (what this field means, not just what it is).

---

## Cross-Cutting Concerns

### Configuration Changes
New env vars — add to `services/nlp-pipeline/configs/dev.local.env.example`:
```
# Wave 4 — Price Impact Labelling
S6_CAP_DAY_T0_PCT=5.0
S6_CAP_DAY_T1_PCT=5.0
S6_CAP_DAY_T2_PCT=7.5
S6_CAP_DAY_T5_PCT=10.0

# Wave 5 — LLM Relevance Scoring
RELEVANCE_SCORING_CYCLE_SECONDS=1800
RELEVANCE_SCORING_BATCH_SIZE=50
RELEVANCE_SCORING_OLLAMA_URL=http://ollama:11434
RELEVANCE_SCORING_MODEL=qwen2.5:3b
RELEVANCE_SCORING_TIMEOUT_SECONDS=30
S6_DISPLAY_WEIGHT_MARKET=0.50
S6_DISPLAY_WEIGHT_LLM=0.40
S6_DISPLAY_WEIGHT_ROUTING=0.10
```

### Documentation Updates (each wave must update)
- `docs/services/api-gateway.md` — update Wave 7: `/v1/news/top` and `/v1/news/entity/{id}` now proxy to S6 not S5
- `services/nlp-pipeline/.claude-context.md` — update: 2 new endpoints, 2 new workers, new table
- `services/api-gateway/.claude-context.md` — update news proxy notes
- `docs/MASTER_PLAN.md` — no service status changes needed (S6 already mature)

### No Kafka Changes
PRD §6.3 confirms: no new Kafka events. `nlp.signal.detected.v1` continues using `article_impact_windows WHERE window_type = 'day_t0'` (same semantics as old `article_price_impacts`). Wave 3 task T-A-3-03 updates the signals query.

---

## Risk Assessment

**Critical path**: Wave 1 → Wave 2 → Wave 3 → (Wave 4 ∥ Wave 5) → Wave 6 → Wave 7 → Wave 8

**Highest risk**: Wave 2 (migration 0009) — drops `article_price_impacts` table that existing code references. Agent must ensure ALL uses of `ArticlePriceImpactModel` and `ArticlePriceImpact` are updated in Wave 3 before tests run.

**Rollback**: If Wave 2 needs rollback, run `alembic downgrade 0008`. Data is migrated one-way; existing `article_price_impacts` data is preserved in migration SQL for reference.

**Testing gaps**: Integration tests (Waves 4/5 workers, Wave 6 endpoint query) require a live Postgres DB. Unit tests mock the session factory. Full integration coverage is deferred to a QA pass.

---

## Recommended Execution Order

1. **Wave 1** — domain layer (no infra deps; fastest to validate)
2. **Wave 2** — migration (requires infra running to test alembic)
3. **Wave 3** — infrastructure (ORM + repos; fixes all blast-radius from migration)
4. **Waves 4 + 5 in parallel** (independent worktrees; both depend on Wave 3)
5. **Wave 6** — API layer (depends on both workers being wired)
6. **Wave 7** — S9 retarget (depends on S6 endpoints)
7. **Wave 8** — frontend (can be done anytime after Wave 7)
