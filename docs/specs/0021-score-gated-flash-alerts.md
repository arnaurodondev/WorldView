# PRD-0021 — Score-Gated Flash Alerts (AlertSeverity Tiers)

> **Status**: Draft — 2026-04-06
> **Author**: Arnau Rodon
> **Services affected**: S10 (Alert Service), S9 (API Gateway), Frontend
> **Depends on**: PLAN-0020 (PRD-0020 `market_impact_score` field on `nlp.signal.detected.v1`)
> **Plan**: PLAN-0021 (to be generated)

---

## 1. Problem Statement

Worldview's S10 Alert Service currently delivers all alerts with equal visual weight via WebSocket push and the pending-alerts REST API. Users have no way to distinguish a routine signal from a market-moving event that warrants immediate attention. The result is alert fatigue — users stop monitoring the feed because every alert looks the same.

ZeroTerminal competitive research (2026-04-06) showed that their flash alert system uses score thresholds to interrupt users only for high-impact events (scores ≥14/20 trigger alerts; ≥17 trigger full-width flash interrupts). Their flash mechanism is cited as a key differentiator over Bloomberg Terminal's undifferentiated alert feeds.

This PRD adds a `severity` tier to every alert in S10, derived from the `market_impact_score` introduced in PRD-0020, and introduces a score-gated flash overlay in the frontend for CRITICAL-severity alerts.

---

## 2. Target Users

| User | Workflow | Benefit |
|------|----------|---------|
| **Research Analysts** | Monitoring signal feed while multitasking | CRITICAL flash alerts interrupt only for genuinely market-moving events |
| **Retail Investors** | Passive monitoring of portfolio entities | Clear severity colour coding; no need to read every signal |
| **Quantitative Traders** | Programmatic alert consumption | `severity` field enables downstream filtering without re-scoring |
| **Thesis Evaluators** | Demo — live system behaviour | Visually compelling alert tiers demonstrate real-time intelligence pipeline |

---

## 3. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | An `AlertSeverity` enum with values `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` is added to the S10 domain | MUST |
| F-02 | Every `Alert` entity has a `severity: AlertSeverity` field | MUST |
| F-03 | Severity is computed by `AlertFanoutUseCase` at alert creation time from the source event's `market_impact_score` | MUST |
| F-04 | Severity thresholds (configurable via env vars): `CRITICAL ≥ 0.85`, `HIGH ≥ 0.65`, `MEDIUM ≥ 0.40`, `LOW < 0.40` | MUST |
| F-05 | The `severity` field is included in the WebSocket push payload | MUST |
| F-06 | The pending-alerts REST API (`GET /api/v1/alerts/pending`) includes `severity` on each alert | MUST |
| F-07 | The `payload_avro` bytes of DLQ entries will contain `severity` via the updated `alert.delivered.v1` schema; the DLQ admin API does not surface it as a top-level structured field (Avro decoding is required to access it) | SHOULD |
| F-08 | The frontend renders severity as colour-coded badges on alert cards: LOW=grey, MEDIUM=yellow, HIGH=orange, CRITICAL=red | MUST |
| F-09 | CRITICAL-severity alerts trigger a full-width flash overlay in the frontend, auto-dismissing after 12 seconds | MUST |
| F-10 | The flash overlay shows the alert's entity name, question/headline, and severity badge | MUST |
| F-11 | Users can dismiss the flash overlay manually (click or keyboard Escape) | MUST |
| F-12 | The `nlp.signal.detected.v1` consumer in S10 uses `market_impact_score` to derive severity; when `market_impact_score = 0.0` (default), severity defaults to `LOW` | MUST |
| F-13 | Alerts from `graph.state.changed.v1` and `intelligence.contradiction.v1` also receive severity, defaulting to `MEDIUM` in the absence of a `market_impact_score` field | MUST |
| F-14 | Dedup logic is unchanged — same `entity_id:alert_type:time_window` dedup key regardless of severity | MUST |

---

## 4. Non-Functional Requirements

| Attribute | Target |
|-----------|--------|
| WebSocket latency | < 100ms from alert fan-out to WebSocket push (already met; severity is computed synchronously) |
| Backward compatibility | Existing frontend alert components that don't read `severity` continue to work (optional field in JS until fully integrated) |
| Schema migration | `severity` column added to `alerts` table with DEFAULT `'low'` — existing rows tolerable as LOW |
| Avro schema update | `alert.delivered.v1` gains `severity` field with default `"low"` (R5 forward-compatible) |

---

## 5. Out of Scope

- **User-configurable severity thresholds** — global thresholds only for thesis; per-user preferences deferred
- **Severity-based alert suppression** — "don't notify me for LOW severity" preferences deferred to a future PRD
- **Prediction market probability shifts as severity source** — deferred until PRD-0019 entity linking is in place
- **Flash overlay for HIGH severity** — CRITICAL only for thesis; HIGH is colour-coded only
- **Severity trends / severity history analytics** — deferred

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|-------------|---------|
| **S10 Alert Service** | Domain change + DB migration | `AlertSeverity` enum, `severity` on `Alert`, threshold computation in `AlertFanoutUseCase` |
| **S10 `IntelligenceConsumer`** | Consumer modification | Extract `market_impact_score` from deserialized signal event dict; pass to `AlertFanoutUseCase.execute()` |
| **S9 API Gateway** | No new endpoints | Existing alert proxy endpoints now include `severity` in pass-through responses |
| **Frontend** | New hook + new component + modified alert cards | `useAlertStream` hook (new); `FlashOverlay` component; severity badges on existing alert list |
| **Kafka / Avro** | `alert.delivered.v1` schema update | New `severity` field with default `"low"`; `schema_version` bumped to 2 |

---

### 6.2 API Changes

#### GET /api/v1/alerts/pending — modified response

`PendingAlertResponse` gains one new field:

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| *(existing fields)* | — | — | Unchanged |
| `severity` | string | no | `"low"` / `"medium"` / `"high"` / `"critical"` |

New optional query parameter:

| Param | Type | Required | Default | Validation | Description |
|-------|------|----------|---------|------------|-------------|
| `min_severity` | string | no | — | enum: `low`, `medium`, `high`, `critical` | Return only alerts with severity ≥ value |

Severity ordering for `min_severity` filter: `critical > high > medium > low`.

---

#### WebSocket /api/v1/alerts/stream — modified push payload

Current push payload:
```json
{ "alert_id": "...", "entity_id": "...", "alert_type": "...", "created_at": "..." }
```

New push payload:
```json
{ "alert_id": "...", "entity_id": "...", "alert_type": "...", "created_at": "...", "severity": "critical" }
```

`severity` field is a string enum value: `"low"` / `"medium"` / `"high"` / `"critical"`.

---

### 6.3 Event Changes

#### alert.delivered.v1 — schema update

New field added (forward-compatible, default `"low"`):

| Field | Type | Default | Nullable | Description |
|-------|------|---------|----------|-------------|
| `severity` | string | `"low"` | no | `low` / `medium` / `high` / `critical` |

`schema_version` default is bumped from `1` to `2` in `alert.delivered.v1.avsc`.

---

### 6.4 Database Changes

#### Modified table: `alerts` (`alert_db`)

New column added:

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `severity` | VARCHAR(10) | no | `'low'` | NOT NULL | Values: `low`, `medium`, `high`, `critical` |

- **Index**: `(severity, created_at DESC)` for severity-filtered queries
- **Migration**: `ALTER TABLE alerts ADD COLUMN severity VARCHAR(10) NOT NULL DEFAULT 'low'`
- **Existing rows**: Backfill with `'low'` (via DEFAULT). No data re-processing needed.

#### Modified table: `pending_alerts` (`alert_db`)

No schema change needed. `severity` is JOIN-resolved from `alerts.severity` in the pending-alerts query.

---

### 6.5 Domain Model Changes

#### New enum: `AlertSeverity` (S10 domain)

```python
class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

Values are lowercase strings stored in DB and serialised in JSON/Avro.

---

#### Modified entity: `Alert` (S10 domain)

Existing `Alert` dataclass gains one field:

| Attribute | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| *(existing fields)* | — | — | Unchanged |
| `severity` | AlertSeverity | yes | enum member | Alert severity tier |

- **Default value for alerts from non-signal sources** (graph changes, contradictions): `AlertSeverity.MEDIUM`
- **Invariant**: `severity` is always set at creation; never null.

---

#### New value object: `SeverityThresholds` (S10 domain)

```python
@dataclass(frozen=True)
class SeverityThresholds:
    critical: float  # default 0.85
    high: float      # default 0.65
    medium: float    # default 0.40
    # below medium → LOW

    def classify(self, market_impact_score: float) -> AlertSeverity:
        if market_impact_score >= self.critical:
            return AlertSeverity.CRITICAL
        if market_impact_score >= self.high:
            return AlertSeverity.HIGH
        if market_impact_score >= self.medium:
            return AlertSeverity.MEDIUM
        return AlertSeverity.LOW
```

- **Invariants**: `critical > high > medium >= 0.0`. Validated at construction.

---

#### Modified consumer: `IntelligenceConsumer` (S10 infrastructure)

`_handle_message()` passes `market_impact_score` to the use case:

```
1. Deserialize Avro event from nlp.signal.detected.v1
2. Extract market_impact_score = event_dict.get("market_impact_score", 0.0)
3. Pass score to AlertFanoutUseCase.execute(event, market_impact_score=score)
   - For graph.state.changed.v1 / intelligence.contradiction.v1: score is absent → 0.0 default
```

**File**: `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`

---

#### Modified use case: `AlertFanoutUseCase` (S10 application)

`execute()` method gains severity computation:

```
1. Receive source event (nlp.signal.detected.v1 | graph.state.changed.v1 | intelligence.contradiction.v1)
   + market_impact_score: float = 0.0 (new parameter)
2. Compute severity = SeverityThresholds.classify(market_impact_score)
   - For graph/contradiction events: score is 0.0 → severity = LOW by threshold default
   - Override: graph/contradiction events force severity = MEDIUM regardless of score (F-13)
3. Create Alert with severity
4. [existing fan-out logic unchanged]
5. Enrich WebSocket push payload with severity
```

---

#### Modified use case: `GetPendingAlertsUseCase` (S10 application)

`execute()` gains an optional `min_severity` parameter for server-side filtering:

```python
async def execute(
    self,
    pending_repo: ...,
    alert_repo: ...,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    min_severity: AlertSeverity | None = None,  # NEW
) -> list[tuple[PendingAlert, Alert]]:
    ...
    # Severity ordering for in-Python filtering (DB stores VARCHAR):
    # SEVERITY_RANK = {LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3}
    # Filter: keep pairs where SEVERITY_RANK[alert.severity] >= SEVERITY_RANK[min_severity]
```

`GET /api/v1/alerts/pending` route passes `min_severity` query parameter to this use case.

**Pre-existing violations to fix in the same wave** (R25 + R27):
- Route currently does lazy imports from `infrastructure.db.repositories` — move to use case constructor injection pattern.
- Route uses `DbSessionDep` (write session) for a read-only endpoint — switch to `ReadDbSessionDep`.

---

#### New config env vars (S10)

| Variable | Default | Description |
|----------|---------|-------------|
| `ALERT_SEVERITY_CRITICAL_THRESHOLD` | `0.85` | `market_impact_score ≥ this → CRITICAL` |
| `ALERT_SEVERITY_HIGH_THRESHOLD` | `0.65` | `market_impact_score ≥ this → HIGH` |
| `ALERT_SEVERITY_MEDIUM_THRESHOLD` | `0.40` | `market_impact_score ≥ this → MEDIUM` |

---

### 6.6 Frontend Changes

#### Modified component: Alert cards (existing J4 alert list)

Each alert card gains a `SeverityBadge` inline component:

| Severity | Colour | Badge text |
|----------|--------|-----------|
| `low` | Grey (#6B7280) | "LOW" |
| `medium` | Yellow (#D97706) | "MED" |
| `high` | Orange (#EA580C) | "HIGH" |
| `critical` | Red (#DC2626) | "CRITICAL" |

---

#### New component: `FlashOverlay` (frontend)

- **Location**: `apps/frontend/src/components/alerts/FlashOverlay.tsx`
- **Trigger**: WebSocket message with `severity === "critical"` arrives
- **Behaviour**:
  - Mounts as a fixed full-viewport overlay with `z-index: 9999`
  - Semi-transparent dark background (rgba 0,0,0,0.75) with blurred content behind
  - Centered card (max-width 600px) showing:
    - "⚡ CRITICAL ALERT" heading in red
    - Entity name
    - Alert type and headline snippet (from `payload.headline` if available, else `alert_type`)
    - Severity badge
    - Auto-dismiss countdown bar (12 seconds)
  - Auto-dismisses after 12 seconds (CSS animation + `setTimeout`)
  - Manual dismiss: click anywhere on overlay or press Escape
  - Queues multiple CRITICAL alerts (shows one at a time, FIFO queue)
  - Does NOT block user interaction with the rest of the app (pointer-events on overlay background only)

**State management** — create a new hook at `apps/frontend/src/hooks/useAlertStream.ts`:
```typescript
// useAlertStream.ts — new WebSocket hook for alert streaming
export function useAlertStream(userId: string) {
  const [criticalQueue, setCriticalQueue] = useState<AlertPayload[]>([]);
  // On new WS message with severity === "critical":
  //   setCriticalQueue(q => [...q, alert]);
  // FlashOverlay dequeues head on dismiss
  // Non-critical alerts are dispatched to a separate alerts feed state
  return { criticalQueue, dequeue: () => setCriticalQueue(q => q.slice(1)) };
}
```

Note: no alert WebSocket hook exists in the frontend yet — `useAlertStream` must be created from scratch as part of this PRD's frontend wave. The `FlashOverlay` and `SeverityBadge` components also go in the new `apps/frontend/src/components/alerts/` directory.

---

### 6.7 Data Flow

#### Severity Assignment Flow (real-time)

```
[Kafka: nlp.signal.detected.v1]
  ↓ IntelligenceConsumer (S10)
[AlertFanoutUseCase.execute(event)]
  → extract market_impact_score (default 0.0 if absent)
  → SeverityThresholds.classify(score) → AlertSeverity
  → create Alert(severity=severity)
  → INSERT alerts (with severity column)
  → INSERT pending_alerts (per watcher)
  → INSERT outbox_event (per watcher)
[Post-commit]
  → ValkeyNotificationPublisher.send_to_user(user_id, {alert_id, ..., severity})
[Frontend WebSocket]
  → if severity === "critical": enqueue to criticalQueue → FlashOverlay renders
  → else: update alert badge in feed
```

---

## 7. Architecture Decisions

### AD-1: Severity computed at fan-out vs at query time

**Option A**: Compute severity when alert is created (fan-out). Stored in DB.
**Option B**: Compute severity dynamically at query time from stored `market_impact_score`.

**Decision**: A — compute at fan-out, store in DB.

**Rationale**: Severity stored in DB enables efficient server-side filtering (`min_severity` query param) without re-processing. It also enables the WebSocket push to include severity immediately without a secondary DB lookup. Downside: if thresholds change, existing alerts have "stale" severity — acceptable for thesis; a re-classification migration can be run if needed.

### AD-2: CRITICAL flash overlay vs HIGH flash overlay

**Decision**: CRITICAL only triggers flash overlay.

**Rationale**: HIGH severity alerts (0.65–0.84 score) are colour-coded orange — visible in the feed without interrupting workflow. CRITICAL (≥0.85) represents rare, major market events (a 4%+ intraday move is a significant event). Triggering flash for HIGH would re-introduce the alert fatigue problem.

---

## 8. Security Analysis

| Threat | Mitigation |
|--------|-----------|
| Severity spoofing by malformed Kafka event | `market_impact_score` is sourced from S6 NLP pipeline, not user input. S10 validates the score is 0.0–1.0 before classifying. |
| Flash overlay clickjacking | Overlay is a local React component, not an iframe. No external content rendered. |
| WebSocket `severity` field injection | S10 builds the WebSocket payload internally; the `severity` field is the string representation of the `AlertSeverity` enum — never interpolated from external data. |
| DB: `severity` column allows arbitrary string | SQLAlchemy model enforces `Enum(AlertSeverity)` type; any value outside the enum raises at the application layer before DB insert. |

---

## 9. Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|---------|
| `market_impact_score` absent from event (old schema version) | Avro deserialisation uses field default `0.0` | Alert created with `severity=LOW` — safe degradation |
| SeverityThresholds misconfigured (critical < medium) | `SeverityThresholds.__post_init__` raises `ValueError` | S10 startup fails fast; fix config and restart |
| Flash overlay JavaScript error | React ErrorBoundary around `FlashOverlay` | Overlay dismisses; alert appears in feed as fallback |
| DB migration adds `severity` column while S10 is running | `ALTER TABLE ... ADD COLUMN ... DEFAULT 'low'` is safe for Postgres running services | Zero downtime migration |

---

## 10. Scalability

Flash overlay is purely client-side. Severity computation is O(1) (threshold comparison). No scalability concerns beyond existing alert fan-out.

---

## 11. Test Strategy

### Unit Tests (S10)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_severity_thresholds_classify_critical` | `score=0.90 → CRITICAL` | HIGH |
| `test_severity_thresholds_classify_high` | `score=0.70 → HIGH` | HIGH |
| `test_severity_thresholds_classify_medium` | `score=0.50 → MEDIUM` | HIGH |
| `test_severity_thresholds_classify_low` | `score=0.20 → LOW` | HIGH |
| `test_severity_thresholds_classify_at_boundaries` | `score=0.85 → CRITICAL`, `score=0.84 → HIGH`, `score=0.65 → HIGH`, `score=0.64 → MEDIUM`, `score=0.40 → MEDIUM`, `score=0.39 → LOW` | HIGH |
| `test_severity_thresholds_invalid_config_critical_below_high` | `critical < high` raises `ValueError` | HIGH |
| `test_severity_thresholds_invalid_config_high_below_medium` | `high < medium` raises `ValueError` | HIGH |
| `test_severity_thresholds_invalid_config_negative_medium` | `medium < 0.0` raises `ValueError` | MEDIUM |
| `test_alert_fanout_sets_severity_from_signal` | Signal with `market_impact_score=0.90` → `Alert(severity=CRITICAL)` | HIGH |
| `test_alert_fanout_defaults_low_for_missing_score` | Signal with no `market_impact_score` field → `Alert(severity=LOW)` | HIGH |
| `test_alert_fanout_defaults_medium_for_graph_event` | `graph.state.changed.v1` event → `Alert(severity=MEDIUM)` | HIGH |
| `test_alert_fanout_dedup_key_unchanged_by_severity` | Same entity/type/time-window produces identical dedup key regardless of severity (F-14) | HIGH |
| `test_websocket_payload_includes_severity` | WS push payload contains `severity` string | HIGH |

### Integration Tests (S10)

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_alert_severity_stored_in_db` | Postgres | `Alert` with `severity=HIGH` is correctly persisted and retrieved |
| `test_pending_alerts_api_returns_severity` | Postgres | `GET /api/v1/alerts/pending` includes `severity` on each item |
| `test_pending_alerts_api_min_severity_filter` | Postgres | `min_severity=high` returns only HIGH and CRITICAL alerts |
| `test_db_migration_existing_rows_default_low` | Postgres | Migration sets `severity='low'` on pre-existing rows |

### Frontend Tests

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `FlashOverlay renders for critical severity` | WS message with `severity=critical` shows overlay | HIGH |
| `FlashOverlay does not render for high severity` | WS message with `severity=high` → no overlay | HIGH |
| `FlashOverlay auto-dismisses after 12s` | Timer fires and unmounts overlay | HIGH |
| `FlashOverlay dismiss on Escape` | Keydown Escape unmounts overlay | HIGH |
| `FlashOverlay queues multiple criticals` | Two CRITICAL messages → first shown, second queued | MEDIUM |
| `SeverityBadge renders correct colour for each tier` | Snapshot tests for all 4 severity values | MEDIUM |

### Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_alert_delivered_v1_severity_field` | `alert.delivered.v1` Avro schema includes `severity` with default `"low"` and is forward-compatible |

---

## 12. Migration Plan

1. **DB migration** (S10 alert_db): `ALTER TABLE alerts ADD COLUMN severity VARCHAR(10) NOT NULL DEFAULT 'low'`. Existing rows get `'low'` — acceptable.
2. **Avro schema**: Update `alert.delivered.v1.avsc` with `severity` field (default `"low"`). Register before deploying S10.
3. **Env vars**: Add `ALERT_SEVERITY_*_THRESHOLD` vars to S10 config; defaults match PRD values.
4. **Deployment order**: S10 can be deployed independently. The `market_impact_score` field on `nlp.signal.detected.v1` (PRD-0020) must be deployed first; if absent (old schema), severity defaults to `LOW` safely.
5. **Frontend**: Flash overlay is additive; does not affect existing alert rendering.
6. **Architecture fixes** (same wave as route changes): Fix pre-existing R25 violation in `GET /api/v1/alerts/pending` (remove lazy infra imports from route handler); fix R27 violation (switch `DbSessionDep` → `ReadDbSessionDep` on GET endpoint).

---

## 13. Observability

| Metric | Labels | Description |
|--------|--------|-------------|
| `s10_alerts_by_severity_total` | `severity={low,medium,high,critical}`, `alert_type` | Distribution of alert severity |
| `s10_flash_overlays_triggered_total` | — | CRITICAL alerts delivered to WS-connected users |

### Log fields

- S10: `severity`, `market_impact_score` on every fan-out log entry

---

## 14. Open Questions

| ID | Question | Owner | Deadline |
|----|----------|-------|----------|
| OQ-001 | Should the flash overlay also trigger a browser notification (Notification API) for CRITICAL alerts? Browser permission required. | Arnau | Before frontend wave |
| OQ-002 | Should HIGH-severity alerts have a softer visual interrupt (e.g. sidebar slide-in) rather than nothing? | Arnau | Before frontend wave |

---

## 15. Effort Estimation

| Area | Waves | Complexity |
|------|-------|-----------|
| S10 domain: `AlertSeverity`, `SeverityThresholds`, `Alert.severity` | 0.5 wave | Low |
| S10 `AlertFanoutUseCase` severity computation | 0.5 wave | Low |
| S10 DB migration + ORM + API response update | 1 wave | Low-Medium |
| Avro schema update + WebSocket payload update | 0.5 wave | Low |
| Frontend `SeverityBadge` + alert card update | 0.5 wave | Low |
| Frontend `FlashOverlay` component | 1 wave | Medium |
| Tests + docs | 1 wave | Medium |
| **Total** | **~5 waves** | — |
