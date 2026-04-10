
# PLAN-0021 — Score-Gated Flash Alerts (AlertSeverity tiers — S10 + Frontend)

> **PRD**: `docs/specs/0021-score-gated-flash-alerts.md`
> **Status**: in-progress
> **Created**: 2026-04-10
> **Updated**: 2026-04-10
> **Waves done**: 1 / 6
> **QA**: —

---

## Pre-Flight Check

| Check | Result |
|-------|--------|
| No unresolved BLOCKING OQs | OQ-001 (browser notifications) and OQ-002 (HIGH visual interrupt) are "Before frontend wave" — NOT classified BLOCKING. Frontend waves flagged. **PASS** |
| No external API field risks | `market_impact_score` is internal (nlp.signal.detected.v1 from PLAN-0020). **PASS** |
| No cross-plan conflicts | PLAN-0022 (S1/S9/frontend — SnapTrade), PLAN-0023 (S7) — no overlap with S10 alerts. **PASS** |
| PRD recency | 4 days old — within 14-day window. **PASS** |
| Architecture compliance | R25 + R27 violations in `routes.py` acknowledged in PRD §6.5 and fixed in Wave A-4. **PASS** |

---

## Codebase State Verification

| PRD Reference | Type | Expected | Actual (verified) | Delta |
|--------------|------|----------|-------------------|-------|
| `alerts` table | DB table | exists + needs `severity` col | exists, no `severity` | migration 0004 |
| `AlertSeverity` | enum | new | not in `domain/enums.py` | create |
| `SeverityThresholds` | VO | new | not in `domain/entities.py` | create |
| `Alert.severity` | entity field | new | `Alert` dataclass has no `severity` | add field |
| `ALERT_SEVERITY_*_THRESHOLD` | env vars | new | not in `config.py` | add |
| `alert.delivered.v1.avsc` | Avro schema | needs `severity` field | no `severity`, `schema_version=1` | add field, bump to 2 |
| `_ALERT_DELIVERED_SCHEMA` inline dict | AVRO-FILE-ONLY violation | should load from .avsc | inline dict in `alert_fanout.py:74-90` | fix: load from file |
| `AlertFanoutUseCase.execute()` | use case | needs `market_impact_score` param | no such param | modify |
| `GetPendingAlertsUseCase` | use case | constructor injection + min_severity | repos passed to execute() — R25 violation | refactor |
| `GET /api/v1/alerts/pending` | route | ReadDbSessionDep + DI factory | `DbSessionDep` + lazy infra imports | fix R25+R27 |
| `PendingAlertResponse.severity` | API schema | new field | no `severity` field | add |
| `IntelligenceConsumer.process_message()` | consumer | extracts market_impact_score | no extraction | modify |
| `AlertRepository.save()` + `_to_entity()` | repo | includes severity | no severity in mapping | update |
| `AlertModel.severity` | ORM col | new column | no `severity` col | add |
| `FlashOverlay.tsx` | frontend component | new | `apps/frontend/src/components/alerts/` dir does not exist | create |
| `useAlertStream.ts` | frontend hook | new | no `src/hooks/` dir | create |
| `SeverityBadge.tsx` | frontend component | new | none | create |

---

## Plan Dependency Graph

```
PLAN-0020 (complete: market_impact_score on nlp.signal.detected.v1)
  ↓
Sub-Plan A: S10 Backend
  A-1 (Domain + Config)
    ↓
  A-2 (Avro + Migration + ORM + Repo)
    ↓
  A-3 (Use Cases + Consumer)
    ↓
  A-4 (API layer + integration tests)
    ↓
Sub-Plan B: Frontend
  B-1 (useAlertStream + SeverityBadge + alert card)
    ↓
  B-2 (FlashOverlay + app wiring)
```

**Dependency**: Sub-Plan B depends on Sub-Plan A being deployed (S10 API must return `severity`).

---

## Open Questions — ⚠️ Resolve Before Executing Sub-Plan B

| OQ | Question | Default (if not resolved) |
|----|----------|--------------------------|
| OQ-001 | Should CRITICAL flash overlay also trigger a browser Notification API (requires user permission prompt)? | No browser notification |
| OQ-002 | Should HIGH-severity alerts have a softer visual interrupt (e.g. sidebar slide-in) in addition to orange colour-coding? | Colour-code only, no interrupt |

These do not block Sub-Plan A execution.

---

## Sub-Plan A — S10 Alert Service

---

### Wave A-1: Domain Layer + Configuration ✅

**Goal**: Add `AlertSeverity` enum, `SeverityThresholds` value object, `severity` field on `Alert`, and 3 severity threshold env vars to `Settings`. All domain logic is fully unit-testable before any DB/Avro work.

**Depends on**: none

**Estimated effort**: 20–35 min

**Status**: **DONE** — 2026-04-10 · 66 unit tests pass (18 new) · ruff + mypy clean

**Architecture layer**: domain + config

#### Pre-read (agent must read before starting)
- `services/alert/src/alert/domain/enums.py`
- `services/alert/src/alert/domain/entities.py`
- `services/alert/src/alert/config.py`
- `docs/specs/0021-score-gated-flash-alerts.md` §6.5

#### Tasks

---

##### T-A-1-01: Add `AlertSeverity` enum

**Type**: impl
**depends_on**: none
**blocks**: T-A-1-02, T-A-2-01, T-A-3-01, T-A-3-02
**Target files**:
- `services/alert/src/alert/domain/enums.py` (modify)
- `services/alert/tests/unit/domain/test_enums.py` (modify)

**What to build**:
Add a new `AlertSeverity(StrEnum)` to the domain enums module, following the existing `AlertType` pattern. The enum represents alert severity tiers used throughout the system.

**Entities / Components**:
- **Name**: `AlertSeverity`
- **Purpose**: Represents the severity tier of an alert, derived from `market_impact_score`
- **Key attributes**:
  - `LOW = "low"` — score < 0.40 (or non-signal events without override)
  - `MEDIUM = "medium"` — 0.40 ≤ score < 0.65 (or graph/contradiction events by default)
  - `HIGH = "high"` — 0.65 ≤ score < 0.85
  - `CRITICAL = "critical"` — score ≥ 0.85
- **Invariant**: Values are lowercase strings (stored in DB, serialised in JSON/Avro)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_alert_severity_values` | LOW/MEDIUM/HIGH/CRITICAL have lowercase string values | unit |
| `test_alert_severity_is_strenum` | `AlertSeverity.LOW` == `"low"` (string equality) | unit |

**Acceptance criteria**:
- [ ] `AlertSeverity` has exactly 4 members: LOW, MEDIUM, HIGH, CRITICAL
- [ ] All values are lowercase strings
- [ ] `from alert.domain.enums import AlertSeverity` works without circular import
- [ ] ruff + mypy pass

---

##### T-A-1-02: Add `SeverityThresholds` VO and `Alert.severity` field

**Type**: impl
**depends_on**: T-A-1-01
**blocks**: T-A-1-03, T-A-3-01
**Target files**:
- `services/alert/src/alert/domain/entities.py` (modify)
- `services/alert/tests/unit/domain/test_entities.py` (modify)

**What to build**:
Add `SeverityThresholds` frozen dataclass (value object) with a `classify()` method. Also add `severity: AlertSeverity = AlertSeverity.LOW` field to the existing `Alert` dataclass (with default to avoid breaking existing constructors).

**Entities / Components**:

- **Name**: `SeverityThresholds`
  - **Purpose**: Classifies a `market_impact_score` float into an `AlertSeverity` enum value
  - **Key attributes**:
    - `critical: float` — threshold for CRITICAL (default 0.85)
    - `high: float` — threshold for HIGH (default 0.65)
    - `medium: float` — threshold for MEDIUM (default 0.40)
  - **Key methods**:
    - `classify(market_impact_score: float) -> AlertSeverity` — returns the severity tier
      ```
      if score >= critical → CRITICAL
      if score >= high     → HIGH
      if score >= medium   → MEDIUM
      else                 → LOW
      ```
  - **Invariants** (validated in `__post_init__`): `critical > high > medium >= 0.0`; raises `ValueError` if violated
  - **Declaration**: `@dataclass(frozen=True)` with `kw_only=True`

- **Name**: `Alert.severity` (field addition)
  - **Purpose**: Stores the pre-computed severity tier of the alert
  - **Type**: `AlertSeverity`
  - **Default**: `AlertSeverity.LOW` (preserves backward compat with existing tests)
  - **Invariant**: Always set at creation by the use case; never null

**Logic & Behavior**:
- `SeverityThresholds.classify()` is a pure function — no side effects, no I/O
- `Alert.severity` default is `AlertSeverity.LOW` to avoid breaking existing test code that creates `Alert()` without severity
- `SeverityThresholds` uses `kw_only=True` to allow keyword-only construction

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_severity_thresholds_classify_critical` | `score=0.90 → CRITICAL` | unit |
| `test_severity_thresholds_classify_high` | `score=0.70 → HIGH` | unit |
| `test_severity_thresholds_classify_medium` | `score=0.50 → MEDIUM` | unit |
| `test_severity_thresholds_classify_low` | `score=0.20 → LOW` | unit |
| `test_severity_thresholds_boundary_critical` | `score=0.85 → CRITICAL` (at boundary) | unit |
| `test_severity_thresholds_boundary_below_critical` | `score=0.849 → HIGH` | unit |
| `test_severity_thresholds_boundary_high` | `score=0.65 → HIGH` (at boundary) | unit |
| `test_severity_thresholds_boundary_below_high` | `score=0.649 → MEDIUM` | unit |
| `test_severity_thresholds_boundary_medium` | `score=0.40 → MEDIUM` (at boundary) | unit |
| `test_severity_thresholds_boundary_below_medium` | `score=0.399 → LOW` | unit |
| `test_severity_thresholds_invalid_critical_below_high` | `critical=0.60, high=0.65` raises ValueError | unit |
| `test_severity_thresholds_invalid_high_below_medium` | `high=0.30, medium=0.40` raises ValueError | unit |
| `test_severity_thresholds_invalid_negative_medium` | `medium=-0.1` raises ValueError | unit |
| `test_alert_has_severity_field` | `Alert()` has `severity=AlertSeverity.LOW` by default | unit |
| `test_alert_severity_assigned` | `Alert(severity=AlertSeverity.CRITICAL)` stores CRITICAL | unit |

**Acceptance criteria**:
- [ ] `SeverityThresholds.classify(0.85)` returns `AlertSeverity.CRITICAL`
- [ ] `SeverityThresholds.classify(0.64)` returns `AlertSeverity.MEDIUM`
- [ ] Invalid threshold order raises `ValueError` at construction
- [ ] `Alert()` without `severity` kwarg creates `severity=AlertSeverity.LOW`
- [ ] `Alert.compute_dedup_key()` is unchanged (no severity in dedup key — F-14)
- [ ] ruff + mypy pass; all new tests pass

---

##### T-A-1-03: Add severity threshold env vars to `config.py`

**Type**: config
**depends_on**: T-A-1-01
**blocks**: T-A-3-01
**Target files**:
- `services/alert/src/alert/config.py` (modify)
- `services/alert/configs/dev.local.env.example` (modify if exists, else skip)

**What to build**:
Add 3 new float settings to `Settings` for severity thresholds, under the `# ── Domain ──` section.

**Logic & Behavior**:
New fields in `Settings`:
```python
# Severity classification thresholds (PRD-0021 §6.5)
alert_severity_critical_threshold: float = 0.85
alert_severity_high_threshold: float = 0.65
alert_severity_medium_threshold: float = 0.40
```
- All three use the `ALERT_` prefix (e.g., `ALERT_ALERT_SEVERITY_CRITICAL_THRESHOLD`)
- Defaults match PRD-0021 §6.5 specification
- No model_validator needed — `SeverityThresholds.__post_init__` validates ordering at construction time

**Acceptance criteria**:
- [ ] `Settings()` has `alert_severity_critical_threshold = 0.85`, `alert_severity_high_threshold = 0.65`, `alert_severity_medium_threshold = 0.40`
- [ ] Fields accept env var `ALERT_ALERT_SEVERITY_CRITICAL_THRESHOLD`, etc.
- [ ] ruff + mypy pass on config.py

---

#### Validation Gate — Wave A-1
- [x] `ruff check services/alert/src/` passes
- [x] `mypy services/alert/src/` passes (strict)
- [x] `python -m pytest services/alert/tests/unit/domain/ -v` — all pass, minimum 15 new tests added (18 new, 66 total)
- [x] No infrastructure imports in `domain/enums.py` or `domain/entities.py`

#### Regression Guardrails — Wave A-1
- **BP-019** (Migration DDL vs ORM column mismatch): Wave A-1 adds `Alert.severity` with a default — ensure `AlertModel` is NOT changed in this wave (ORM update is Wave A-2). Tests that create `Alert()` without `severity` must still pass.
- **BP-126** (Alembic migration NOT NULL column missing server_default): `Alert.severity` defaults to `AlertSeverity.LOW` in Python — this default is safe because migration DDL is Wave A-2 and will include `DEFAULT 'low'`.

---

### Wave A-2: Avro Schema + DB Migration + ORM + Repository Update

**Goal**: Update `alert.delivered.v1.avsc` to add `severity` field (forward-compatible, default "low", schema_version bump to 2), generate Alembic migration `0004_add_severity_to_alerts`, add `severity` column to `AlertModel`, and update `AlertRepository.save()` / `_to_entity()` to handle the new field. Add a contract test for the updated schema.

**Depends on**: Wave A-1

**Estimated effort**: 25–40 min

**Architecture layer**: infrastructure (schema + DB)

#### Pre-read (agent must read before starting)
- `infra/kafka/schemas/alert.delivered.v1.avsc`
- `services/alert/src/alert/infrastructure/db/models.py`
- `services/alert/src/alert/infrastructure/db/repositories/alert.py`
- `services/alert/alembic/versions/0003_email_idempotency_fixes.py` (for migration chaining)
- `services/alert/src/alert/infrastructure/messaging/email_sent_event.py` (AVRO-FILE-ONLY pattern)
- `docs/BUG_PATTERNS.md` BP-017, BP-019, BP-126

#### Tasks

---

##### T-A-2-01: Update `alert.delivered.v1.avsc` — add severity field

**Type**: schema
**depends_on**: T-A-1-01
**blocks**: T-A-3-01
**Target files**:
- `infra/kafka/schemas/alert.delivered.v1.avsc` (modify)
- `services/alert/tests/contract/test_alert_delivered_schema.py` (create)

**What to build**:
Add a `severity` field with default `"low"` to `alert.delivered.v1.avsc`. Bump `schema_version` default from `1` to `2`. The new field goes at the end of the fields array (R5: add with default, never reorder or remove).

**Logic & Behavior**:
New field specification:
```json
{
  "name": "severity",
  "type": "string",
  "default": "low",
  "doc": "Alert severity tier: low | medium | high | critical"
}
```
- Field position: append AFTER `correlation_id` (last field)
- `schema_version` field: change `"default": 1` to `"default": 2`
- Schema remains forward-compatible: consumers on the old schema receive `severity` transparently via default

**Downstream test impact**:
- `services/alert/tests/contract/test_alert_delivered_schema.py` — new file to be created
- `libs/contracts/tests/` — check for any tests asserting on `alert.delivered.v1` field counts (grep before finalizing)

**Contract test to create** (`tests/contract/test_alert_delivered_schema.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_alert_delivered_has_severity_field` | Schema loads and has `severity` field with default `"low"` | contract |
| `test_alert_delivered_schema_version_2` | `schema_version` default is 2 | contract |
| `test_alert_delivered_severity_forward_compat` | Record WITHOUT severity field deserializes successfully (default applied) | contract |
| `test_alert_delivered_roundtrip_with_severity` | Record with `severity="critical"` serializes + deserializes correctly | contract |

**Acceptance criteria**:
- [ ] `alert.delivered.v1.avsc` has `severity` field with `"default": "low"` as the last field
- [ ] `schema_version` default is `2`
- [ ] `fastavro.schema.load_schema(path)` succeeds on the updated schema
- [ ] Old records (without `severity`) deserialize with `severity="low"` applied from default
- [ ] All contract tests pass

---

##### T-A-2-02: Alembic migration `0004_add_severity_to_alerts`

**Type**: schema
**depends_on**: T-A-1-01
**blocks**: T-A-4-03
**Target files**:
- `services/alert/alembic/versions/0004_add_severity_to_alerts.py` (create)

**What to build**:
Generate (or hand-write) Alembic migration that adds `severity VARCHAR(10) NOT NULL DEFAULT 'low'` to the `alerts` table, and creates a `(severity, created_at DESC)` index.

**Logic & Behavior**:
```sql
-- upgrade
ALTER TABLE alerts
  ADD COLUMN severity VARCHAR(10) NOT NULL DEFAULT 'low';

CREATE INDEX idx_alerts_severity ON alerts (severity, created_at DESC);

-- downgrade
DROP INDEX idx_alerts_severity;
ALTER TABLE alerts DROP COLUMN severity;
```
- Migration chain: `down_revision = '0003'` (previous: `0003_email_idempotency_fixes`)
- `NOT NULL DEFAULT 'low'` is safe for zero-downtime deployment (Postgres adds column with server default without a full table rewrite)
- Existing rows get `'low'` via server default — no explicit UPDATE required

**Downstream test impact**:
- Integration tests that run Alembic migrations will automatically pick up this migration
- `tests/integration/conftest.py` — check if it hard-codes migration revision; update if needed

**Acceptance criteria**:
- [ ] Migration runs `upgrade` without error on a test DB with existing `alerts` rows
- [ ] Existing rows get `severity = 'low'` from the server default
- [ ] Migration runs `downgrade` without error
- [ ] `down_revision = '0003...'` matches the previous migration's revision ID
- [ ] ruff + mypy pass on the migration file

---

##### T-A-2-03: Update `AlertModel` + `AlertRepository` for severity

**Type**: impl
**depends_on**: T-A-2-02, T-A-1-01
**blocks**: T-A-3-01
**Target files**:
- `services/alert/src/alert/infrastructure/db/models.py` (modify — `AlertModel`)
- `services/alert/src/alert/infrastructure/db/repositories/alert.py` (modify — `save()` + `_to_entity()`)

**What to build**:
Add `severity` column to `AlertModel`. Update `AlertRepository.save()` to write `alert.severity` to the row. Update `AlertRepository._to_entity()` to read `row.severity` and map to `AlertSeverity` enum.

**Entities / Components**:
- **AlertModel.severity** (new mapped_column):
  ```python
  severity: Mapped[str] = mapped_column(String(10), nullable=False, server_default="low")
  ```
  - Use `String(10)` — matches `VARCHAR(10)` DDL
  - `server_default="low"` — mirrors migration DDL (Belt-and-suspenders: both migration and ORM agree)
  - Add `Index("idx_alerts_severity", "severity", created_at.desc())` to `__table_args__`

- **AlertRepository.save()** change:
  ```python
  row = AlertModel(
      ...existing fields...,
      severity=str(alert.severity),  # NEW: serialize AlertSeverity enum to string
  )
  ```

- **AlertRepository._to_entity()** change:
  ```python
  return Alert(
      ...existing fields...,
      severity=AlertSeverity(row.severity),  # NEW: deserialize string to enum
  )
  ```

**Tests to write**:
- No new unit tests needed for the mapper (covered by integration tests in Wave A-4)
- Verify existing `test_entities.py` tests still pass (Alert constructor unchanged)

**Acceptance criteria**:
- [ ] `AlertModel` has `severity: Mapped[str]` column
- [ ] `AlertRepository.save(alert)` stores `alert.severity.value` in the DB
- [ ] `AlertRepository.get_by_id(id)` returns `Alert` with correct `AlertSeverity` enum value
- [ ] `AlertRepository._to_entity(row)` handles missing `severity` via `AlertSeverity("low")` fallback
- [ ] ruff + mypy pass

---

#### Validation Gate — Wave A-2
- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest services/alert/tests/contract/ -v` — minimum 4 new contract tests pass
- [ ] Alembic `upgrade` + `downgrade` cycle runs without error (tested locally)
- [ ] Forward-compatibility verified: old Avro records without `severity` deserialize successfully

#### Regression Guardrails — Wave A-2
- **BP-017** (Outbox payload fields mismatch Avro schema): The inline `_ALERT_DELIVERED_SCHEMA` in `alert_fanout.py` is NOT updated in this wave — that AVRO-FILE-ONLY fix is Wave A-3. The dispatcher uses pre-serialized bytes from the fanout, not the `.avsc` file directly, so no outbox corruption occurs here. Wave A-3 must sync the inline schema with the new .avsc before any alerts with severity are serialized.
- **BP-019** (Migration DDL vs ORM column mismatch): `AlertModel.severity` uses `String(10)` + `server_default="low"` — MUST match `VARCHAR(10) NOT NULL DEFAULT 'low'` in the migration DDL exactly.
- **BP-126** (Alembic migration NOT NULL column missing server_default): Migration uses `DEFAULT 'low'` — existing rows get the default; zero-downtime safe.

---

### Wave A-3: Application Layer — Use Cases + Consumer

**Goal**: Modify `AlertFanoutUseCase` to accept `market_impact_score`, compute severity (with graph/contradiction override), include severity in WS push and Avro event, and fix the AVRO-FILE-ONLY violation. Refactor `GetPendingAlertsUseCase` to constructor injection + `min_severity` filter. Update `IntelligenceConsumer` to extract `market_impact_score` and pass to fanout. Add metrics counters.

**Depends on**: Wave A-2

**Estimated effort**: 35–50 min

**Architecture layer**: application (use cases) + infrastructure (consumer)

#### Pre-read (agent must read before starting)
- `services/alert/src/alert/application/use_cases/alert_fanout.py` (full file)
- `services/alert/src/alert/application/use_cases/pending_alerts.py`
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`
- `services/alert/src/alert/infrastructure/messaging/email_sent_event.py` (AVRO-FILE-ONLY pattern)
- `services/alert/src/alert/infrastructure/metrics/prometheus.py`
- `services/alert/tests/unit/application/test_alert_fanout.py`
- `services/alert/tests/unit/infrastructure/test_intelligence_consumer.py`
- `docs/BUG_PATTERNS.md` BP-119 (AVRO-FILE-ONLY)

#### Tasks

---

##### T-A-3-01: Modify `AlertFanoutUseCase` — severity computation + AVRO-FILE-ONLY fix + metrics

**Type**: impl
**depends_on**: T-A-1-02, T-A-1-03, T-A-2-01, T-A-2-03
**blocks**: T-A-4-01
**Target files**:
- `services/alert/src/alert/application/use_cases/alert_fanout.py` (modify)
- `services/alert/src/alert/infrastructure/metrics/prometheus.py` (modify)
- `services/alert/tests/unit/application/test_alert_fanout.py` (modify)

**What to build**:
1. **AVRO-FILE-ONLY fix**: Replace the inline `_ALERT_DELIVERED_SCHEMA` dict (lines 74-90) with `fastavro.schema.load_schema()` from `alert.delivered.v1.avsc`. Use the same pattern as `email_sent_event.py` (`Path(__file__).parents[6] / "infra" / "kafka" / "schemas" / "alert.delivered.v1.avsc"`).
2. **Severity thresholds**: `AlertFanoutUseCase.__init__` gains `severity_thresholds: SeverityThresholds | None = None` param (None → default `SeverityThresholds()` with PRD defaults).
3. **Execute flow**: `execute()` gains `market_impact_score: float = 0.0` parameter. Severity computation:
   - For `nlp.signal.detected.v1`: `severity = self._thresholds.classify(market_impact_score)`
   - For `graph.state.changed.v1` and `intelligence.contradiction.v1`: `severity = AlertSeverity.MEDIUM` (F-13 override, regardless of score)
   - Score is clamped to `[0.0, 1.0]` before classify: `score = max(0.0, min(1.0, market_impact_score))`
4. **Alert creation**: `Alert(severity=severity, ...)` — severity stored in entity
5. **Avro event**: `_serialize_alert_delivered()` gains `severity` field: `"severity": str(alert.severity)` added to the record dict
6. **WS push payload**: `ws_payload` dict gains `"severity": str(alert.severity)`
7. **Metrics**: Increment `s10_alerts_by_severity_total` counter (label: severity value + alert_type) after successful fan-out. For CRITICAL severity with watchers > 0: increment `s10_flash_overlays_triggered_total`.

**Logic & Behavior** (execute() changes):
```
1. Backfill suppression [unchanged]
2. Extract entity_id [unchanged]
3. Resolve alert type [unchanged]
4. Extract market_impact_score from event: event.get("market_impact_score", 0.0)
   - Clamp to [0.0, 1.0]
5. Compute severity:
   - if topic in ("graph.state.changed.v1", "intelligence.contradiction.v1"):
       severity = AlertSeverity.MEDIUM  # F-13 override
   - else:
       severity = self._thresholds.classify(score)
6. Resolve watchers [unchanged]
7. Dedup check [unchanged]
8. Build Alert with severity [CHANGED: add severity=severity]
9. Transaction: alert + pending + outbox [unchanged structure]
   - Avro record in outbox gains "severity" field [CHANGED]
10. Post-commit WS push: ws_payload gains "severity" field [CHANGED]
11. Metrics: increment counters [NEW]
```

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_alert_fanout_severity_critical_from_score` | Signal event, score=0.90 → Alert.severity==CRITICAL | unit |
| `test_alert_fanout_severity_low_for_missing_score` | Signal event, no market_impact_score field → Alert.severity==LOW | unit |
| `test_alert_fanout_severity_medium_for_graph_event` | graph.state.changed.v1 → Alert.severity==MEDIUM (F-13) | unit |
| `test_alert_fanout_severity_medium_for_contradiction` | intelligence.contradiction.v1 → Alert.severity==MEDIUM | unit |
| `test_alert_fanout_ws_payload_includes_severity` | WS push payload dict contains "severity" key | unit |
| `test_alert_fanout_dedup_key_unchanged_by_severity` | Two calls with different scores produce same dedup key for same entity/type/window (F-14) | unit |
| `test_alert_fanout_score_clamped_above_1` | market_impact_score=1.5 → clamped to 1.0 → CRITICAL | unit |
| `test_alert_fanout_score_clamped_below_0` | market_impact_score=-0.1 → clamped to 0.0 → LOW | unit |
| `test_alert_fanout_avro_schema_loads_from_file` | `_get_parsed_schema()` loads from `.avsc` file (not inline dict) | unit |

**Acceptance criteria**:
- [ ] `_ALERT_DELIVERED_SCHEMA` inline dict REMOVED; replaced with `fastavro.schema.load_schema(path)` call
- [ ] `AlertFanoutUseCase.execute()` has `market_impact_score: float = 0.0` parameter
- [ ] Graph/contradiction events always get `severity = AlertSeverity.MEDIUM` (score ignored)
- [ ] Signal events get severity from `SeverityThresholds.classify(market_impact_score)`
- [ ] WS push payload includes `"severity"` string field
- [ ] Avro outbox record includes `"severity"` string field
- [ ] ruff + mypy pass

---

##### T-A-3-02: Refactor `GetPendingAlertsUseCase` — constructor injection + min_severity filter

**Type**: impl
**depends_on**: T-A-1-01
**blocks**: T-A-4-01
**Target files**:
- `services/alert/src/alert/application/use_cases/pending_alerts.py` (modify)
- `services/alert/tests/unit/application/test_pending_alerts.py` (create — does not yet exist)

**What to build**:
Refactor `GetPendingAlertsUseCase` to use constructor injection for repos (R25 compliance), and add `min_severity: AlertSeverity | None = None` parameter to `execute()` for server-side filtering. Do the same for `AcknowledgeAlertUseCase`.

**Entities / Components**:
- **`GetPendingAlertsUseCase`** (refactored):
  ```python
  class GetPendingAlertsUseCase:
      def __init__(
          self,
          pending_repo: PendingAlertRepositoryPort,
          alert_repo: AlertRepositoryPort,
      ) -> None: ...

      async def execute(
          self,
          user_id: UUID,
          limit: int,
          offset: int,
          min_severity: AlertSeverity | None = None,
      ) -> list[tuple[PendingAlert, Alert]]:
          ...
          # After fetching pairs, apply in-Python severity filter:
          SEVERITY_RANK = {AlertSeverity.LOW: 0, AlertSeverity.MEDIUM: 1,
                           AlertSeverity.HIGH: 2, AlertSeverity.CRITICAL: 3}
          if min_severity is not None:
              min_rank = SEVERITY_RANK[min_severity]
              pairs = [(p, a) for p, a in pairs
                       if SEVERITY_RANK[a.severity] >= min_rank]
  ```

- **`AcknowledgeAlertUseCase`** (refactored):
  ```python
  class AcknowledgeAlertUseCase:
      def __init__(
          self,
          pending_repo: PendingAlertRepositoryPort,
          session: AsyncSession,  # needed for commit — N-04
      ) -> None: ...

      async def execute(
          self,
          user_id: UUID,
          alert_id: UUID,
      ) -> bool:
          result = await self._pending_repo.acknowledge(user_id, alert_id)
          if result:
              await self._session.commit()
          return result
  ```
  Note: `session` in use case is acceptable here because the session lifecycle matches the request scope — the DI factory manages the session, not the route.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_pending_no_min_severity` | Returns all pairs when min_severity is None | unit |
| `test_get_pending_min_severity_high` | Filters out LOW and MEDIUM, keeps HIGH and CRITICAL | unit |
| `test_get_pending_min_severity_critical` | Keeps only CRITICAL alerts | unit |
| `test_get_pending_min_severity_low` | Returns all (LOW is the minimum) | unit |
| `test_get_pending_empty_after_filter` | All alerts below min_severity → empty list | unit |
| `test_acknowledge_commits_session` | `AcknowledgeAlertUseCase.execute()` calls `session.commit()` when ack succeeds | unit |

**Acceptance criteria**:
- [ ] `GetPendingAlertsUseCase.__init__` takes `pending_repo, alert_repo` (no repos in `execute()`)
- [ ] `execute(user_id, limit, offset, min_severity=None)` returns filtered pairs
- [ ] `AcknowledgeAlertUseCase.__init__` takes `pending_repo, session`
- [ ] `AcknowledgeAlertUseCase.execute()` commits session on success; route does NOT commit
- [ ] ruff + mypy pass

---

##### T-A-3-03: Update `IntelligenceConsumer` — extract `market_impact_score`

**Type**: impl
**depends_on**: T-A-3-01
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py` (modify)
- `services/alert/tests/unit/infrastructure/test_intelligence_consumer.py` (modify)

**What to build**:
In `IntelligenceConsumer.process_message()`, extract `market_impact_score` from the deserialized event dict and pass it to `self._fanout.execute()`.

**Logic & Behavior**:
```python
async def process_message(self, key, value, headers):
    topic = self._resolve_topic(value, headers)
    correlation_id = value.get("correlation_id")
    market_impact_score: float = float(value.get("market_impact_score", 0.0))
    # Clamp score to [0.0, 1.0] — belt and suspenders
    market_impact_score = max(0.0, min(1.0, market_impact_score))
    result = await self._fanout.execute(
        event=value,
        topic=topic,
        correlation_id=correlation_id,
        market_impact_score=market_impact_score,
    )
```
- `float()` cast handles the case where the field is an int (Avro union type)
- Score clamping is belt-and-suspenders (fanout also clamps — F-03 requirement)
- For `graph.state.changed.v1` and `intelligence.contradiction.v1` topics: `market_impact_score` will be `0.0` (field absent) — fanout's topic-based MEDIUM override handles this (F-13)

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_consumer_passes_market_impact_score_to_fanout` | `process_message()` passes `market_impact_score=0.9` from event to fanout | unit |
| `test_consumer_defaults_score_to_zero_if_absent` | Event without `market_impact_score` → `0.0` passed to fanout | unit |
| `test_consumer_clamps_score_above_1` | `market_impact_score=2.0` → clamped to `1.0` before passing to fanout | unit |

**Acceptance criteria**:
- [ ] `process_message()` extracts `market_impact_score` from event dict
- [ ] Passes score to `self._fanout.execute(market_impact_score=score)`
- [ ] Defaults to `0.0` when field is absent
- [ ] Score is clamped to `[0.0, 1.0]`
- [ ] ruff + mypy pass

---

#### Validation Gate — Wave A-3
- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest services/alert/tests/unit/ -v` — all pass, minimum 17 new tests added (9 fanout + 6 pending + 3 consumer = 18 minimum but some may overlap with existing)
- [ ] AVRO-FILE-ONLY: grep for `_ALERT_DELIVERED_SCHEMA` in `alert_fanout.py` → should return 0 hits
- [ ] No lazy infra imports in `pending_alerts.py` (repos are constructor-injected)

#### Regression Guardrails — Wave A-3
- **BP-119** (AVRO-FILE-ONLY): After removing the inline `_ALERT_DELIVERED_SCHEMA`, verify the `.avsc` file path resolution is correct by running `python -c "from alert.application.use_cases.alert_fanout import _get_parsed_schema; _get_parsed_schema()"` from the service directory.
- **BP-017** (Outbox payload fields mismatch Avro schema): The Avro record in `_serialize_alert_delivered()` MUST include the new `"severity"` field, otherwise `fastavro.schemaless_writer` will use the default (`"low"`) — which is functionally correct but silently wrong. Explicitly include `"severity": str(alert.severity)` in the record dict.
- **BP-128** (Missing field crashes fanout): `value.get("market_impact_score", 0.0)` default prevents KeyError when consuming from older nlp.signal.detected.v1 producers that pre-date PRD-0020.
- **R25** (API layer uses only use cases): `GetPendingAlertsUseCase` now takes repos in constructor — do NOT re-add repo params to `execute()`.

---

### Wave A-4: API Layer + DI Wiring + Integration Tests

**Goal**: Fix `GET /api/v1/alerts/pending` (R25 DI factory + R27 ReadDbSessionDep + severity response field + min_severity query param), fix `DELETE /api/v1/alerts/{alert_id}/ack` (R25), update `PendingAlertResponse` schema, add metrics to `prometheus.py`, and write integration tests covering the full severity flow.

**Depends on**: Wave A-3

**Estimated effort**: 35–50 min

**Architecture layer**: API + integration tests

#### Pre-read (agent must read before starting)
- `services/alert/src/alert/api/routes.py` (full file)
- `services/alert/src/alert/api/dependencies.py` (full file)
- `services/alert/src/alert/api/schemas.py`
- `services/alert/src/alert/infrastructure/metrics/prometheus.py`
- `services/alert/tests/unit/api/test_alerts_api.py`
- `services/alert/tests/integration/conftest.py`
- `services/alert/tests/integration/test_fanout.py`

#### Tasks

---

##### T-A-4-01: Update `dependencies.py` — DI factories for pending alerts use cases (R25 fix)

**Type**: impl
**depends_on**: T-A-3-02
**blocks**: T-A-4-02
**Target files**:
- `services/alert/src/alert/api/dependencies.py` (modify)

**What to build**:
Add two new DI factory functions in `dependencies.py` for `GetPendingAlertsUseCase` and `AcknowledgeAlertUseCase`, following the same pattern as `get_email_prefs_get_uc()`. Use `ReadDbSessionDep` for the GET use case (R27).

**Logic & Behavior**:
```python
# GET pending alerts — read-only (R27: use ReadDbSessionDep)
def get_pending_alerts_uc(
    session: Annotated[AsyncSession, Depends(get_read_db_session)],
) -> GetPendingAlertsUseCase:
    from alert.infrastructure.db.repositories.alert import AlertRepository
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
    return GetPendingAlertsUseCase(PendingAlertRepository(session), AlertRepository(session))

GetPendingAlertsUseCaseDep = Annotated[GetPendingAlertsUseCase, Depends(get_pending_alerts_uc)]

# ACK alert — write operation (uses write session)
def get_ack_uc(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcknowledgeAlertUseCase:
    from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
    return AcknowledgeAlertUseCase(PendingAlertRepository(session), session)

AckUseCaseDep = Annotated[AcknowledgeAlertUseCase, Depends(get_ack_uc)]
```
- Import use cases at top of `dependencies.py` (not lazy) — already fine since no circular import
- Lazy repo imports (`from alert.infrastructure.db.repositories...`) are in the factory body (R25 pattern: infra lives in DI, not routes)

**Acceptance criteria**:
- [ ] `GetPendingAlertsUseCaseDep` wired to `get_read_db_session` (R27)
- [ ] `AckUseCaseDep` wired to `get_db_session` (write, correct for mutation)
- [ ] No `from alert.infrastructure...` imports at module level in `dependencies.py` (lazy in factory body is OK per R25)
- [ ] ruff + mypy pass

---

##### T-A-4-02: Fix `routes.py` — R25+R27 compliance + severity response + min_severity param

**Type**: impl
**depends_on**: T-A-4-01
**blocks**: T-A-4-03
**Target files**:
- `services/alert/src/alert/api/routes.py` (modify)
- `services/alert/src/alert/api/schemas.py` (modify)
- `services/alert/tests/unit/api/test_alerts_api.py` (modify)

**What to build**:
1. **`PendingAlertResponse`** in `schemas.py`: add `severity: str` field
2. **`GET /api/v1/alerts/pending`**: use `GetPendingAlertsUseCaseDep` (remove lazy infra imports, remove `DbSessionDep`, switch to `ReadDbSessionDep` via dep), add `min_severity: AlertSeverity | None = Query(None)` query param, add `severity` to `PendingAlertResponse` construction
3. **`DELETE /api/v1/alerts/{alert_id}/ack`**: use `AckUseCaseDep` (remove lazy infra import, remove `session.commit()` from route handler)

**Logic & Behavior**:

`schemas.py` change:
```python
class PendingAlertResponse(BaseModel):
    pending_id: UUID
    alert_id: UUID
    entity_id: UUID
    alert_type: str
    source_topic: str
    payload: dict
    created_at: datetime
    severity: str  # NEW: "low" | "medium" | "high" | "critical"
```

`routes.py` GET endpoint:
```python
@router.get("/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts(
    request: Request,
    uc: GetPendingAlertsUseCaseDep,  # replaces session: DbSessionDep
    user_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_severity: str | None = Query(default=None, description="Minimum severity: low|medium|high|critical"),
) -> PendingAlertsResponse:
    # Parse min_severity to AlertSeverity enum (raise 422 if invalid)
    severity_filter: AlertSeverity | None = None
    if min_severity is not None:
        try:
            severity_filter = AlertSeverity(min_severity)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid min_severity: {min_severity!r}")

    pairs = await uc.execute(user_id=user_id, limit=limit, offset=offset, min_severity=severity_filter)
    alert_responses = [
        PendingAlertResponse(
            ...,
            severity=str(alert.severity),  # NEW
        )
        for p, alert in pairs
    ]
    ...
```

`routes.py` DELETE endpoint:
```python
@router.delete("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: UUID,
    request: Request,
    uc: AckUseCaseDep,  # replaces session: DbSessionDep + lazy import
    user_id: UUID = Query(...),
) -> dict[str, str]:
    updated = await uc.execute(user_id=user_id, alert_id=alert_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    # NO session.commit() here — use case handles it (N-04)
    ...
```

**Tests to write** (update existing `test_alerts_api.py`):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_get_pending_response_has_severity` | Response JSON includes `severity` field | unit |
| `test_get_pending_min_severity_query_param` | `?min_severity=high` filters correctly | unit |
| `test_get_pending_invalid_min_severity` | `?min_severity=extreme` returns 422 | unit |
| `test_ack_route_no_commit_in_route` | Route does NOT call session.commit() | unit |

**Acceptance criteria**:
- [ ] No `from alert.infrastructure.db.repositories.*` imports in `routes.py`
- [ ] GET pending uses `ReadDbSessionDep` (via `get_pending_alerts_uc` factory)
- [ ] DELETE ack uses `AckUseCaseDep`, no `session.commit()` in route
- [ ] `PendingAlertResponse.severity` field present in API response JSON
- [ ] `?min_severity=critical` returns only CRITICAL alerts
- [ ] `?min_severity=invalid` returns HTTP 422
- [ ] ruff + mypy pass

---

##### T-A-4-03: Metrics + Integration Tests

**Type**: test + impl
**depends_on**: T-A-4-02, T-A-2-02
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/metrics/prometheus.py` (modify — add counters)
- `services/alert/tests/integration/test_fanout.py` (modify)
- `services/alert/tests/integration/test_s7_s10_pipeline.py` (modify if applicable)

**What to build**:
1. Add two Prometheus counters to `prometheus.py`:
   - `s10_alerts_by_severity_total` — Counter with labels `severity`, `alert_type`
   - `s10_flash_overlays_triggered_total` — Counter (no labels; represents CRITICAL alerts fanned out with ≥1 watcher)
2. Increment in `AlertFanoutUseCase` after successful fan-out (or in prometheus metrics module)
3. Integration tests covering:
   - Alert stored with severity in DB
   - Pending alerts API returns severity
   - min_severity filter works end-to-end
   - DB migration: existing rows have severity='low'

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_alert_severity_stored_in_db` | Alert with severity=HIGH persisted and retrieved correctly from Postgres | integration |
| `test_pending_alerts_returns_severity` | `GET /api/v1/alerts/pending` includes `severity` on each item | integration |
| `test_pending_alerts_min_severity_filter` | `?min_severity=high` returns only HIGH+CRITICAL alerts from DB | integration |
| `test_db_migration_existing_rows_default_low` | Migration sets severity='low' on pre-existing alert rows | integration |

**Acceptance criteria**:
- [ ] `s10_alerts_by_severity_total` counter exists in `prometheus.py` with correct label names
- [ ] `s10_flash_overlays_triggered_total` counter exists
- [ ] All 4 integration tests pass against a real Postgres test container
- [ ] `python -m pytest services/alert/tests/ -v` — full suite passes (≥332 tests + new ones)

---

#### Validation Gate — Wave A-4
- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed packages
- [ ] `python -m pytest services/alert/tests/unit/ -v` — all pass
- [ ] `python -m pytest services/alert/tests/integration/ -v` — all pass, minimum 4 new integration tests
- [ ] No lazy infra imports in `routes.py` (grep: `from alert.infrastructure` in routes.py → 0 hits)
- [ ] R27: GET pending route does NOT use `DbSessionDep` (grep: `DbSessionDep` in `get_pending_alerts` function body → 0 hits)
- [ ] N-04: `session.commit()` in `routes.py` → 0 hits

#### Regression Guardrails — Wave A-4
- **BP-064** (FastAPI 204 status code): The GET pending endpoint uses `response_model=PendingAlertsResponse` (200 OK) — no 204 involved. The DELETE ack endpoint returns `dict[str, str]` (200 OK). No 204 usage introduced.
- **BP-019** (Migration DDL vs ORM): The new `severity` column in integration tests must be present after `Alembic upgrade head` runs in `conftest.py`. Ensure the integration test conftest does NOT pin a specific migration revision (or update it to include `0004`).
- **R25** Enforcement: After this wave, `routes.py` must have zero lazy `from alert.infrastructure` imports. Verify with grep.
- **R27** Enforcement: Read-only endpoint (`GET /api/v1/alerts/pending`) must use `ReadDbSessionDep`, not `DbSessionDep`.

---

## Sub-Plan B — Frontend

> ⚠️ **Resolve OQ-001 and OQ-002 before executing these waves.**
> Default behavior if not resolved: no browser notifications (OQ-001), no HIGH interrupt (OQ-002).

---

### Wave B-1: useAlertStream Hook + SeverityBadge + Alert Card Integration

**Goal**: Create the `useAlertStream` WebSocket hook that drives the alert feed and CRITICAL queue. Create the `SeverityBadge` component. Integrate severity badges into the existing alert list rendering.

**Depends on**: Wave A-4 (S10 API must return `severity` in WS push payload and REST response)

**Estimated effort**: 30–45 min

**Architecture layer**: frontend (hook + component)

#### Pre-read (agent must read before starting)
- `apps/frontend/src/App.tsx`
- `apps/frontend/src/components/Layout.tsx`
- `apps/frontend/src/pages/DashboardPage.tsx` (check for existing alert feed)
- `apps/frontend/src/components/NewsList.tsx` (check alert card pattern if any)
- `docs/specs/0021-score-gated-flash-alerts.md` §6.6

#### Tasks

---

##### T-B-1-01: Create `useAlertStream.ts` WebSocket hook

**Type**: impl
**depends_on**: none (frontend is independent of sub-plan A during planning)
**blocks**: T-B-2-01
**Target files**:
- `apps/frontend/src/hooks/useAlertStream.ts` (create — directory may need to be created)

**What to build**:
Create a React hook that manages a WebSocket connection to `GET /api/v1/alerts/stream?user_id=<uuid>`, parses incoming messages, and routes them to either the CRITICAL queue (for `FlashOverlay`) or the general alerts feed state.

**Logic & Behavior**:
```typescript
// apps/frontend/src/hooks/useAlertStream.ts
export type AlertSeverity = "low" | "medium" | "high" | "critical";

export interface AlertPayload {
  alert_id: string;
  entity_id: string;
  alert_type: string;
  topic: string;
  occurred_at: string;
  severity: AlertSeverity;
}

export function useAlertStream(userId: string | null) {
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  const [recentAlerts, setRecentAlerts] = useState<AlertPayload[]>([]);

  useEffect(() => {
    if (!userId) return;
    const ws = new WebSocket(`/api/v1/alerts/stream?user_id=${userId}`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "ping") return;
      const alert = data as AlertPayload;
      if (alert.severity === "critical") {
        setCriticalQueue((q) => [...q, alert]);
      } else {
        setRecentAlerts((prev) => [alert, ...prev].slice(0, 50));
      }
    };
    return () => ws.close();
  }, [userId]);

  const dequeueCritical = useCallback(
    () => setCriticalQueue((q) => q.slice(1)),
    []
  );

  return { criticalQueue, recentAlerts, dequeueCritical };
}
```
- **WS URL**: `/api/v1/alerts/stream` (relative — proxied by Vite dev server or Nginx in prod)
- **Ping messages**: `{ "type": "ping" }` — ignored silently
- **CRITICAL queue**: FIFO; `FlashOverlay` dequeues on dismiss
- **Recent alerts**: capped at 50 items, prepended (newest first)
- **Reconnection**: not implemented for thesis; `useEffect` cleanup closes WS on unmount

**Tests to write** (Vitest + @testing-library/react):
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `useAlertStream critical routes to queue` | WS message with severity=critical → criticalQueue grows | unit |
| `useAlertStream non-critical routes to feed` | WS message with severity=high → recentAlerts grows | unit |
| `useAlertStream ignores ping` | `{"type":"ping"}` → no state change | unit |
| `useAlertStream dequeueCritical removes head` | After dequeue, criticalQueue loses first item | unit |

**Acceptance criteria**:
- [ ] Hook connects to WS on mount with `userId` query param
- [ ] `severity === "critical"` → `criticalQueue` (for FlashOverlay)
- [ ] Other severities → `recentAlerts` feed
- [ ] Ping messages cause no state update
- [ ] WS closed on unmount
- [ ] TypeScript strict mode passes

---

##### T-B-1-02: Create `SeverityBadge.tsx` component

**Type**: impl
**depends_on**: T-B-1-01
**blocks**: T-B-1-03
**Target files**:
- `apps/frontend/src/components/alerts/SeverityBadge.tsx` (create)

**What to build**:
A small inline badge component displaying the severity tier with the correct colour from PRD §6.6.

**Logic & Behavior**:
```tsx
// apps/frontend/src/components/alerts/SeverityBadge.tsx
import type { AlertSeverity } from "../../hooks/useAlertStream";

const SEVERITY_STYLE: Record<AlertSeverity, { bg: string; text: string; label: string }> = {
  low:      { bg: "bg-gray-100",   text: "text-gray-600",  label: "LOW" },
  medium:   { bg: "bg-yellow-100", text: "text-yellow-700", label: "MED" },
  high:     { bg: "bg-orange-100", text: "text-orange-700", label: "HIGH" },
  critical: { bg: "bg-red-100",    text: "text-red-700",    label: "CRITICAL" },
};

export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const { bg, text, label } = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.low;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${bg} ${text}`}>
      {label}
    </span>
  );
}
```
- Uses Tailwind CSS classes (matching existing project style)
- Fallback to `low` style for unknown severity values

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `SeverityBadge renders LOW with grey` | severity=low → label "LOW", grey class | unit |
| `SeverityBadge renders MEDIUM with yellow` | severity=medium → label "MED", yellow class | unit |
| `SeverityBadge renders HIGH with orange` | severity=high → label "HIGH", orange class | unit |
| `SeverityBadge renders CRITICAL with red` | severity=critical → label "CRITICAL", red class | unit |

**Acceptance criteria**:
- [ ] All 4 severity values render with correct label text
- [ ] Colours match PRD §6.6: grey/yellow/orange/red
- [ ] TypeScript strict mode passes
- [ ] Snapshot tests created

---

##### T-B-1-03: Wire SeverityBadge into existing alert list components

**Type**: impl
**depends_on**: T-B-1-02
**blocks**: T-B-2-02
**Target files**:
- Whichever component renders the alert list (determined by reading `DashboardPage.tsx` and `PortfolioPage.tsx` at implementation time)
- If no alert list exists yet: create `apps/frontend/src/components/alerts/AlertCard.tsx`

**What to build**:
Find where the alert feed is rendered in the frontend (or create an `AlertCard` if no alert list component exists yet), and add `<SeverityBadge severity={alert.severity} />` to each alert item.

**Logic & Behavior**:
- The REST endpoint `GET /api/v1/alerts/pending` now returns `severity` on each item
- Display the badge inline in each alert card row, alongside `alert_type` and entity name
- If no alert list component exists, create a minimal `AlertCard` that displays: alert_type, entity_id (short), severity badge, and created_at timestamp

**Acceptance criteria**:
- [ ] Each alert item in the UI displays a `SeverityBadge`
- [ ] Badge severity matches the `severity` field from the REST response
- [ ] TypeScript strict mode passes

---

#### Validation Gate — Wave B-1
- [ ] `pnpm typecheck` passes in `apps/frontend/`
- [ ] `pnpm test` passes — minimum 8 new tests (4 hook + 4 badge)
- [ ] `pnpm lint` passes (ESLint)
- [ ] No `any` casts in new TypeScript code without explicit comment

#### Regression Guardrails — Wave B-1
- **Frontend pnpm enforcement**: Use `pnpm` only (not npm/yarn). Exact version pins in `package.json` (no `^`). Run `pnpm audit` after any new dependency (0 CVEs required).
- **WS URL**: Use relative path `/api/v1/alerts/stream` (not hardcoded `localhost:8010`) to work via Vite proxy and Nginx.

---

### Wave B-2: FlashOverlay Component + App Wiring

**Goal**: Create the `FlashOverlay` full-viewport component with auto-dismiss countdown (12s), manual dismiss (click / Escape), FIFO CRITICAL queue rendering, and ErrorBoundary wrapper. Wire it into the root app layout so it renders on top of all pages.

**Depends on**: Wave B-1

**Estimated effort**: 35–50 min

**Architecture layer**: frontend (component + wiring)

#### Pre-read (agent must read before starting)
- `apps/frontend/src/App.tsx`
- `apps/frontend/src/components/Layout.tsx`
- `apps/frontend/src/hooks/useAlertStream.ts` (created in B-1)
- `apps/frontend/src/components/alerts/SeverityBadge.tsx` (created in B-1)
- `docs/specs/0021-score-gated-flash-alerts.md` §6.6 (FlashOverlay behaviour spec)

#### Tasks

---

##### T-B-2-01: Create `FlashOverlay.tsx` component

**Type**: impl
**depends_on**: T-B-1-02
**blocks**: T-B-2-02
**Target files**:
- `apps/frontend/src/components/alerts/FlashOverlay.tsx` (create)

**What to build**:
Full-viewport overlay component triggered by CRITICAL alerts. Wraps itself in a React ErrorBoundary. Shows one alert at a time (FIFO from `criticalQueue`). Auto-dismisses after 12 seconds.

**Logic & Behavior**:
```tsx
interface FlashOverlayProps {
  alert: AlertPayload;        // Current CRITICAL alert to display
  onDismiss: () => void;      // Called when overlay is dismissed (timeout or user action)
}

function FlashOverlayInner({ alert, onDismiss }: FlashOverlayProps) {
  // 12-second auto-dismiss timer
  useEffect(() => {
    const timer = setTimeout(onDismiss, 12_000);
    return () => clearTimeout(timer);
  }, [alert.alert_id, onDismiss]);

  // Keyboard: Escape dismisses
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onDismiss(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onDismiss]);

  return (
    // Fixed overlay: z-9999, semi-transparent dark background
    // Click on background (not card) → dismiss (pointer-events on background div)
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/75 backdrop-blur-sm"
      onClick={onDismiss}
    >
      <div
        className="bg-white rounded-lg p-6 max-w-lg w-full mx-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()} // prevent card click from dismissing
      >
        <h2 className="text-red-600 text-xl font-bold mb-2">⚡ CRITICAL ALERT</h2>
        <p className="text-gray-700 mb-1 font-medium">{alert.alert_type}</p>
        <p className="text-gray-500 text-sm mb-4 font-mono">{alert.entity_id}</p>
        <SeverityBadge severity="critical" />
        {/* Countdown progress bar: CSS animation from 100% to 0% over 12s */}
        <div className="mt-4 h-1 bg-gray-200 rounded overflow-hidden">
          <div className="h-full bg-red-500 animate-countdown" />
        </div>
        <p className="text-xs text-gray-400 mt-1">Auto-dismisses in 12 seconds — press Escape to close</p>
      </div>
    </div>
  );
}

// ErrorBoundary wrapper — on error, dismiss and log
export function FlashOverlay(props: FlashOverlayProps) {
  return (
    <ErrorBoundary onError={props.onDismiss}>
      <FlashOverlayInner {...props} />
    </ErrorBoundary>
  );
}
```
- `animate-countdown`: add a Tailwind `@keyframes` in `globals.css` or `tailwind.config.ts` if not already present: `from { width: 100% } to { width: 0% }` with `animation-duration: 12s; animation-timing-function: linear`
- The overlay background is clickable (dismiss), the card itself is NOT clickable for dismiss (stopPropagation)
- ErrorBoundary: if any render error occurs, call `onDismiss` and log to console; do not crash the page

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `FlashOverlay renders for critical alert` | Renders with entity_id, alert_type, CRITICAL badge | unit |
| `FlashOverlay auto-dismisses after 12s` | `onDismiss` called after 12s timer fires | unit |
| `FlashOverlay dismisses on Escape` | `keydown` Escape → `onDismiss` called | unit |
| `FlashOverlay dismisses on background click` | Click on overlay div → `onDismiss` called | unit |
| `FlashOverlay does NOT dismiss on card click` | Click on card → `onDismiss` NOT called | unit |
| `FlashOverlay shows alert_type and entity_id` | Correct text rendered from AlertPayload | unit |

**Acceptance criteria**:
- [ ] Overlay renders with `z-[9999]` and `bg-black/75`
- [ ] Auto-dismiss `setTimeout(onDismiss, 12_000)` fires after 12s
- [ ] Escape key calls `onDismiss`
- [ ] Background click calls `onDismiss`; card click does NOT
- [ ] Wrapped in ErrorBoundary — error calls `onDismiss`
- [ ] TypeScript strict mode passes

---

##### T-B-2-02: Wire `FlashOverlay` into app + integrate `useAlertStream`

**Type**: impl
**depends_on**: T-B-2-01, T-B-1-03
**blocks**: none
**Target files**:
- `apps/frontend/src/App.tsx` or `apps/frontend/src/components/Layout.tsx` (modify)

**What to build**:
Call `useAlertStream(userId)` at the app root level. When `criticalQueue.length > 0`, render `<FlashOverlay alert={criticalQueue[0]} onDismiss={dequeueCritical} />` above all page content. Pass `recentAlerts` down to the alert list component (or via a context).

**Logic & Behavior**:
```tsx
// In App.tsx or Layout.tsx (whichever is the root)
const { criticalQueue, recentAlerts, dequeueCritical } = useAlertStream(currentUserId);

return (
  <>
    {/* Flash overlay — renders on top of everything */}
    {criticalQueue.length > 0 && (
      <FlashOverlay
        alert={criticalQueue[0]}
        onDismiss={dequeueCritical}
      />
    )}
    {/* Rest of app layout */}
    <Layout recentAlerts={recentAlerts}>
      {children}
    </Layout>
  </>
);
```
- `currentUserId`: sourced from existing auth context or user state (read the existing pattern in `App.tsx` to determine where userId is stored)
- `recentAlerts`: passed down to existing alert display components, or stored in a React context for cross-component access
- Multiple CRITICAL alerts: only `criticalQueue[0]` shown at a time; each dismiss dequeues and shows the next

**Acceptance criteria**:
- [ ] `useAlertStream` called at root level with authenticated user ID
- [ ] `FlashOverlay` renders when `criticalQueue.length > 0`
- [ ] Dismiss dequeues and shows next CRITICAL alert (if any)
- [ ] Non-CRITICAL alerts flow to `recentAlerts` which feeds existing alert list
- [ ] TypeScript strict mode passes
- [ ] `pnpm build` produces no type errors

---

#### Validation Gate — Wave B-2
- [ ] `pnpm typecheck` passes
- [ ] `pnpm test` passes — minimum 10 new tests (6 FlashOverlay + 4 wiring/integration)
- [ ] `pnpm lint` passes
- [ ] `pnpm build` succeeds (no TS compilation errors)
- [ ] Manual smoke test: mock WS message with `severity=critical` → FlashOverlay appears

#### Regression Guardrails — Wave B-2
- **React ErrorBoundary**: `FlashOverlay` must be wrapped in an ErrorBoundary. Render errors in the overlay must NOT propagate to the root app tree and crash the entire page.
- **WS cleanup**: `useAlertStream` `useEffect` must return a cleanup function that calls `ws.close()` — memory leak if not cleaned up on unmount.
- **Multiple overlays**: Only `criticalQueue[0]` is rendered at a time. Do NOT render all CRITICAL alerts simultaneously.

---

## Cross-Cutting Concerns

### Contract Changes
- `alert.delivered.v1`: New `severity` field with default `"low"` — consumers receive field transparently via default
- REST `GET /api/v1/alerts/pending`: New `severity` field in each item; new `min_severity` query param (optional)
- REST WebSocket payload: New `severity` field in push messages

### Migration
- `0004_add_severity_to_alerts.py`: `ALTER TABLE alerts ADD COLUMN severity VARCHAR(10) NOT NULL DEFAULT 'low'`
- Zero-downtime safe — Postgres adds column with server default without table rewrite

### Event Flow
- No new Kafka topics; `alert.delivered.v1` schema updated (backward-compatible)

### Configuration
- New env vars: `ALERT_ALERT_SEVERITY_CRITICAL_THRESHOLD=0.85`, `ALERT_ALERT_SEVERITY_HIGH_THRESHOLD=0.65`, `ALERT_ALERT_SEVERITY_MEDIUM_THRESHOLD=0.40`
- Add to `services/alert/configs/dev.local.env.example` if it exists

### Documentation Updates (mandatory — run before closing the plan)
- `docs/services/alert.md` — add `severity` column to schema table, update API surface table (add `severity` + `min_severity`), add `AlertSeverity` to enums list, add new env vars
- `services/alert/.claude-context.md` — add `AlertSeverity` to enums section, add `SeverityThresholds` to domain section, update REST API table with `severity` + `min_severity`, add migration 0004 to history
- `infra/kafka/schemas/alert.delivered.v1.avsc` (done in Wave A-2)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AVRO-FILE-ONLY fix breaks existing tests | Medium | High | Wave A-3 must verify schema file path resolution with a direct Python import test |
| Alembic migration fails on existing data | Low | High | `DEFAULT 'low'` is always safe; no NOT NULL without default (BP-126) |
| `GetPendingAlertsUseCase` refactor breaks existing unit tests | Medium | Medium | Old tests pass repos to `execute()` — must update ALL callers |
| Frontend WS URL not proxied in dev | Low | Low | Use relative URL `/api/v1/alerts/stream`; confirm Vite proxy config covers it |
| OQ-001/OQ-002 resolved AFTER frontend waves — requires rework | Low | Low | Frontend waves are self-contained; adding browser notifications is additive |

**Critical Path**: A-1 → A-2 → A-3 → A-4 → B-1 → B-2

**Highest Risk Wave**: A-3 (AVRO-FILE-ONLY migration + use case refactor + consumer change — most files touched simultaneously)

**Rollback**: Each wave is a clean commit. Rollback = revert the wave's commit. DB migration rollback runs `downgrade` (drops severity column — acceptable, no data loss).

---

## Wave Status Tracking

| Wave | Title | Status | Commit |
|------|-------|--------|--------|
| A-1 | Domain + Config | pending | — |
| A-2 | Avro + Migration + ORM | pending | — |
| A-3 | Use Cases + Consumer | pending | — |
| A-4 | API layer + integration tests | pending | — |
| B-1 | useAlertStream + SeverityBadge + alert card | pending | — |
| B-2 | FlashOverlay + app wiring | pending | — |

---
