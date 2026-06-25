# PRD-0113 — Alerts Rule Engine + 5 User-Creatable Alert Types

> **Status:** Draft · **Author:** Arnau Rodon (+ Claude) · **Date:** 2026-06-20
> **Branch:** `feat/md-reliability-followups` (worktree `worldview-wt-md-reliability`)
> **Primary inputs:** `docs/audits/2026-06-20-alerts-engine-investigation.md`,
> `docs/audits/2026-06-20-alerts-signal-sources.md`,
> `docs/audits/2026-06-20-alerts-ui-investigation.md`
> **Next:** `/plan` → `docs/plans/0113-alerts-rule-engine-plan.md`

---

## 1. Problem Statement

Today S10 (alert service) is an **event fan-out router**, not a rule engine. The only way an
alert fires is: an upstream intelligence event (`nlp.signal.detected.v1`,
`graph.state.changed.v1`, `intelligence.contradiction.v1`) arrives, S10 looks up who *watches
the entity* via S1 watchlists, dedups, and pushes a notification. There is **no standing
`AlertRule`**, no continuous evaluation, and no per-condition firing.

The "create alert" surface is a façade:
- **Frontend** rules are **localStorage-only** (`lib/alerts/rules.ts`, `_localOnly: true`) —
  they never reach a backend.
- **Backend** `POST /api/v1/alerts` writes a **one-shot fired row** with the condition stuffed
  in `payload` JSON and **never re-evaluates it**. Live proof: a user's "price below 150" rule
  wrote a `low`-severity row at creation time and never checked price again.

Users cannot create the alerts a market-intelligence terminal must offer: *price crossings,
news-volume spikes, momentum surges, new graph connections, fundamental thresholds.* This PRD
builds a **real standing-rule engine** and delivers **5 user-creatable alert types end-to-end**
(backend evaluation + a finance-grade creation UI).

## 2. Users & Journeys

- **Primary user:** the retail/prosumer trader using the worldview terminal (per
  `docs/PRODUCT_CONTEXT.md`). They watch instruments and entities and want to be told *when
  something they care about happens* without staring at screens.
- **Journey A (price):** On the AAPL instrument page, click **＋ Alert** → "Price crosses
  above $250" → saved → notified when AAPL's last price first crosses 250.
- **Journey B (news volume):** "Alert me when ≥ 5 articles mention NVDA in 24h."
- **Journey C (momentum):** "Alert me when news momentum on TSLA jumps ≥ +50% vs the prior
  window."
- **Journey D (connection):** From the KG graph / Path panel, "Alert me when a connection
  appears between Apple and Anthropic (within 3 hops)."
- **Journey E (fundamental):** "Alert me when AAPL P/E crosses below 25."
- All five land in the existing notification surface (WebSocket toast + `/alerts` page +
  ack/snooze), owned by the **rule creator** (not fanned out to all watchers).

## 3. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | A persistent `alert_rules` store (one row per standing rule), owned by `(tenant_id, user_id)`. | MUST |
| FR-2 | Full rule CRUD: `POST/GET/PATCH/DELETE /api/v1/alert-rules` on S10, proxied by S9, auth-gated. | MUST |
| FR-3 | Five rule types, each with a **structured, validated** condition (discriminated union), evaluated continuously: `PRICE_CROSS`, `NEWS_COUNT`, `NEWS_MOMENTUM`, `KG_CONNECTION`, `FUNDAMENTAL_CROSS`. | MUST |
| FR-4 | **Edge-triggered** firing: a rule fires on the *transition* into the condition (e.g. below→above), not every evaluation while it holds; with a per-rule **cooldown** re-arm. | MUST |
| FR-5 | A `RuleEvaluator` strategy registry keyed by `rule_type` — one evaluator per type; the single extension seam. | MUST |
| FR-6 | A new **`alert-rule-poller`** process evaluating poll-type rules (price, fundamental, news-count, news-momentum) against S3/S6 internal REST on per-type cadences. | MUST |
| FR-7 | `KG_CONNECTION` evaluated event-driven: the existing intelligence consumer pre-filters on `graph.state.changed.v1` then **confirms the A↔B edge via an S7 read** before firing. | MUST |
| FR-8 | Fired rule alerts reuse the existing `alerts`/`pending_alerts`/outbox transaction + WebSocket delivery, but **target `rule.user_id`** (not the watchlist), with a `rule_id`-based dedup key. | MUST |
| FR-9 | Rules can be **enabled/paused** (`enabled` flag) and per-type **severity** chosen by the user (default `medium`). | MUST |
| FR-10 | Frontend **type-first AlertWizard**: 5 type cards → per-type structured condition editor + entity/instrument picker + live natural-language summary + notify toggles, persisting to the real CRUD API. | MUST |
| FR-11 | New creation entry points: instrument detail header (price/fundamental/news), KG graph / Path panel (connection), plus the existing `/alerts` page. | MUST |
| FR-12 | Replace the localStorage rule layer (`lib/alerts/rules.ts`) with `lib/api/alertRules.ts` calling the real endpoints; migrate the manager/list UIs to server rules. | MUST |
| FR-13 | Natural-language rule summary per type (e.g. "Alert me when AAPL price crosses above $250"). | SHOULD |
| FR-14 | Backtest/preview ("would have fired N times in 30d"). | **OUT OF SCOPE (v2)** — see §5 |

## 4. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | **Latency bound by ingest cadence.** Price freshness is 2–5 min (no tick stream); poller cadence: price 60 s, news-count/momentum 1 h, fundamental 6 h. Alerts fire within one poll cycle of the underlying data refreshing. |
| NFR-2 | **S3/S6 load budget:** poller batches reads (`POST /internal/v1/price/batch`, ≤ 50 ids/call) and only evaluates `enabled` rules; per-type cadence throttles fundamental/news to hourly+. |
| NFR-3 | **No spam:** edge-trigger + `cooldown_seconds` guarantee a rule fires at most once per transition (and at most once per cooldown window). |
| NFR-4 | **Multi-tenant isolation:** every rule query filters by `tenant_id`; a user may only read/modify their own rules (`user_id`). |
| NFR-5 | **Idempotent evaluation:** the poller and consumer are restart-safe; `last_state` persists edge memory in the DB (not in-process), so a restart cannot double-fire or miss a transition. |
| NFR-6 | **Observability:** per-rule-type Prometheus counters (`alert_rule_evaluations_total{rule_type,outcome}`, `alert_rule_fired_total{rule_type}`), poller liveness gauge + last-success timestamp, evaluator error counter (mirrors the BP-705 worker-observability pattern). |
| NFR-7 | **Forward-compatible events:** any `graph.state.changed.v1` enrichment is additive with defaults (R28/R11). |

## 5. Out of Scope (v1)

- **Backtest/preview endpoint** (FR-14) — "would have fired N times in 30d" requires a
  historical dry-run engine; deferred to v2. The wizard ships with the NL summary instead.
- **Push tick stream for prices** (`market.quote.ticked.v1`) — PULL via `/price/batch` is
  sufficient at the 2–5 min ingest cadence; a push emitter is a future optimisation.
- **Per-metric fundamental event** (`market.fundamental.updated.v1`) — v1 triggers off the
  existing `market.dataset.fetched (fundamentals)` event + re-read; a dedicated event is v2.
- **New news-count windows beyond 7d at the source** — v1 uses S6's 7d rollup + the trending
  endpoint's 24/72/168 h windows; arbitrary windows are v2.
- **Compound/boolean rules** (AND/OR across conditions), **portfolio-scoped** rules, and
  **alert sharing** — v2.
- Migrating the legacy one-shot `POST /api/v1/alerts` away (kept for the rag-chat LLM
  `create_alert` tool back-compat; it will be repointed to create a `PRICE_CROSS` rule in a
  follow-up, not this PRD).

## 6. Technical Design

### 6.1 Affected Services

| Service | Change |
|---------|--------|
| **S10 alert** | New `alert_rules` table (migration 0010) + `AlertRule` entity + `RuleType` enum + discriminated-union condition schema; `RuleEvaluator` registry + 5 evaluators; new `alert-rule-poller` process; extend intelligence consumer for `KG_CONNECTION`; `FireRuleAlertUseCase`; rule CRUD routes; S3/S6/S7 internal clients for evaluation. |
| **S9 api-gateway** | Proxy routes for `/api/v1/alert-rules` CRUD (auth-gated, inject internal JWT) → `clients.alert.*`. |
| **S3 market-data** | **No code change** — consumed read-only via existing `POST /internal/v1/price/batch` (1–50 ids/call), `GET /api/v1/fundamentals/timeseries?instrument_id=&metric=`, and `GET /api/v1/fundamentals/screen/fields` (metric vocabulary). All verified present in `api/routers/{price_snapshot,fundamental_metrics}.py`. |
| **S6 nlp-pipeline** | **No code change** — consumed read-only via `GET /internal/v1/instruments/{id}/news-rollup-7d` (7d count) and `GET /api/v1/news/trending-entities?window_hours=24\|72\|168` (delta_pct + count). Both verified in `api/routes/{internal_news_rollup,trending_entities}.py`. |
| **S7 knowledge-graph** | **No code change for v1** — consumed read-only via the existing `GET /api/v1/paths/between?source=&target=&max_hops=1..3` (returns `connected: bool` + ranked paths; `api/paths.py`) to confirm A↔B edges. (Optional additive `new_edges` enrichment to `graph.state.changed.v1` is v2.) |
| **worldview-web** | `lib/api/alertRules.ts` (real CRUD), `AlertWizard` + per-type condition editors, shared `EntityPicker` + `MetricPicker`, NL summary, new entry points; retire the localStorage rule layer. |
| **infra** | New compose service `alert-rule-poller` (same image as S10, different command); config vars (poll cadences, cooldowns). |

### 6.2 API Changes (S10, proxied by S9)

Base path S10: `/api/v1/alert-rules`. S9 proxy: `/v1/alert-rules` (auth-gated). All inject the
internal JWT; `tenant_id`/`user_id` come from the JWT, never the body.

#### POST /api/v1/alert-rules
- **Purpose:** create a standing rule.
- **Auth:** required (user JWT at S9 → internal JWT to S10).
- **Request body:**
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | `rule_type` | enum | yes | — | one of the 5 `RuleType` values | discriminator |
  | `name` | string | no | auto from NL summary | 1–255, no HTML | display name |
  | `condition` | object | yes | — | discriminated union by `rule_type` (§6.5.3) | structured params |
  | `severity` | enum | no | `medium` | LOW/MEDIUM/HIGH/CRITICAL | fired-alert severity |
  | `enabled` | bool | no | `true` | — | active flag |
  | `cooldown_seconds` | int | no | per-type default (§6.5.2) | ≥ 0, ≤ 604800 | re-arm window |
  | `notify_in_app` | bool | no | `true` | — | delivery pref |
  | `notify_email` | bool | no | `false` | — | delivery pref |
- **Response (201):** full `AlertRuleResponse` (all stored columns incl. `rule_id`, `created_at`, `last_state=null`).
- **Errors:** 400 (schema/condition validation — e.g. unknown metric_key, missing node_b for KG), 401 (auth), 409 (duplicate identical rule for the user), 422 (semantic — e.g. node_a == node_b).
- **Rate limit:** 60/min/user.

#### GET /api/v1/alert-rules
- **Purpose:** list the caller's rules. Query: `?enabled=true|false`, `?rule_type=`, pagination `?limit=&offset=`.
- **Response (200):** `{ items: AlertRuleResponse[], total: int }`. Filtered to caller's `tenant_id`+`user_id`.

#### GET /api/v1/alert-rules/{rule_id}
- **Response (200):** `AlertRuleResponse`. 404 if not owned by caller.

#### PATCH /api/v1/alert-rules/{rule_id}
- **Purpose:** partial update (`name`, `condition`, `severity`, `enabled`, `cooldown_seconds`, notify flags). Changing `condition` **resets `last_state` to null** (re-arm). `rule_type` is immutable.
- **Response (200):** updated `AlertRuleResponse`. 404 / 400 / 422 as POST.

#### DELETE /api/v1/alert-rules/{rule_id}
- **Response (204).** 404 if not owned.

#### (unchanged, for context) `GET /api/v1/alerts/pending`, `PATCH .../acknowledge`, `PATCH .../snooze`, `GET .../history`, `WS .../stream` — fired-alert lifecycle, reused as-is. The new rules feed `pending_alerts`/WebSocket through `FireRuleAlertUseCase`.

### 6.3 Event Changes

**No new Kafka topics in v1.** The engine reads existing streams + REST:
- **Consume (existing):** `graph.state.changed.v1` (already subscribed) — pre-filter for `KG_CONNECTION`; `market.dataset.fetched` (filter `dataset_type=fundamentals`) — optional trigger to wake the fundamental evaluator early (the poller also covers it on cadence); `nlp.article.enriched.v1` — optional trigger to wake news-count re-check (poller covers it on cadence too).
- **Produce (existing):** fired rule alerts emit the existing outbox `alert.delivered.v1` path (topic-agnostic dispatcher — no change).
- **v2 (out of scope):** additive `new_edges: array<{subject_id, object_id, relation_type}>` (default `[]`) on `graph.state.changed.v1` to make KG-connection exact-match without an S7 confirm read; `market.fundamental.updated.v1`; `market.quote.ticked.v1`.

> Consumer note (R28/idempotency): the `KG_CONNECTION` path extends the **existing**
> `alert-intelligence-consumer` group; firing remains idempotent via the `rule_id`-based dedup
> key (§6.5.4), so event replay cannot double-fire.

### 6.4 Database Changes

#### Table: `alert_rules` (alert_db) — NEW (migration 0010; current head 0009)

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `rule_id` | UUID | no | `new_uuid7()` | PK | UUIDv7 (R10) |
| `tenant_id` | UUID | no | — | — | from JWT |
| `user_id` | UUID | no | — | — | rule owner (delivery target) |
| `rule_type` | VARCHAR(50) | no | — | CHECK in enum set | `RuleType` (stored as string, not PG enum — BP-007) |
| `name` | VARCHAR(255) | no | — | — | display name |
| `entity_id` | UUID | yes | — | — | instrument_id (price/fundamental) or entity_id (news/momentum); NULL for KG_CONNECTION |
| `node_a_entity_id` | UUID | yes | — | — | KG_CONNECTION source; NULL otherwise |
| `node_b_entity_id` | UUID | yes | — | — | KG_CONNECTION target; NULL otherwise |
| `condition` | JSONB | no | — | — | structured per-type params (§6.5.3) |
| `severity` | VARCHAR(10) | no | `'medium'` | in AlertSeverity | fired severity |
| `enabled` | BOOLEAN | no | `true` | — | pause without delete |
| `cooldown_seconds` | INTEGER | no | per-type (§6.5.2) | ≥ 0 | re-arm window |
| `notify_in_app` | BOOLEAN | no | `true` | — | delivery pref |
| `notify_email` | BOOLEAN | no | `false` | — | delivery pref |
| `last_state` | JSONB | yes | NULL | — | edge memory: `{last_value?, was_above?, last_count?, connected?, last_fired_at?, last_checked_at?}` |
| `created_at` | TIMESTAMPTZ | no | `utc_now()` | — | UTC (R11) |
| `updated_at` | TIMESTAMPTZ | no | `utc_now()` | — | UTC |

- **Indexes:** `(rule_type) WHERE enabled` (poller scan), `(entity_id) WHERE enabled` (event pre-filter), `(node_a_entity_id, node_b_entity_id) WHERE enabled` (KG), `(tenant_id, user_id)` (CRUD list).
- **CHECK constraints:** `rule_type IN (...)`; `severity IN (...)`; for `KG_CONNECTION` → `node_a_entity_id IS NOT NULL AND node_b_entity_id IS NOT NULL AND node_a_entity_id <> node_b_entity_id`; for other types → `entity_id IS NOT NULL`. (Enforced in domain + a partial CHECK where feasible.)
- **Estimated rows:** ≤ a few thousand (one per user-rule); trivial.
- **`alerts` table change:** none structurally — fired rule alerts reuse `alerts` with `alert_type='user_rule'` and `payload.rule_type`/`payload.rule_id`. (Migration 0010 only adds `alert_rules`.)

### 6.5 Domain Model Changes

#### 6.5.1 Enum: `RuleType` (NEW, `domain/enums.py`)
| Value | Meaning | Trigger | Keying |
|-------|---------|---------|--------|
| `PRICE_CROSS` | last price crosses a level | poll (60 s) | `entity_id` = instrument_id |
| `NEWS_COUNT` | article count over window ≥ N | poll (1 h) | `entity_id` |
| `NEWS_MOMENTUM` | momentum `delta_pct` ≥ threshold | poll (1 h) | `entity_id` |
| `KG_CONNECTION` | edge/path appears between A and B | event (`graph.state.changed.v1`) + S7 confirm | `node_a_entity_id`, `node_b_entity_id` |
| `FUNDAMENTAL_CROSS` | a fundamental metric crosses Y | poll (6 h) + optional dataset-fetched wake | `entity_id` = instrument_id |

#### 6.5.2 Entity: `AlertRule` (NEW, frozen-ish aggregate, `domain/entities.py`)
- **Attributes:** all `alert_rules` columns. `condition` is a typed value object (the discriminated union below). Invariants: keying constraint (§6.4 CHECK) enforced in `__post_init__`/factory; `cooldown_seconds ≥ 0`; severity valid.
- **Per-type cooldown defaults:** PRICE_CROSS 3600 s; NEWS_COUNT 21600 s; NEWS_MOMENTUM 21600 s; KG_CONNECTION 0 (latching, fires once via `connected=true`); FUNDAMENTAL_CROSS 86400 s.
- **Methods:** `should_fire(eval_result, now) -> bool` (edge + cooldown logic against `last_state`); `next_state(eval_result, now) -> dict` (compute new `last_state`); `is_due(now, cadence) -> bool` (poller throttle via `last_state.last_checked_at`).

#### 6.5.3 Value Object: `condition` discriminated union (`domain/rule_conditions.py`, Pydantic)
```
PriceCrossCondition       { instrument_id: UUID, operator: "above"|"below", value: float>0 }
NewsCountCondition        { entity_id: UUID, window: "1h"|"6h"|"24h"|"7d", threshold: int>=1, keyword?: str }
NewsMomentumCondition     { entity_id: UUID, window_hours: 24|72|168, delta_pct: float, min_count: int=2 }
KgConnectionCondition     { source_entity_id: UUID, target_entity_id: UUID, max_hops: int(1..3)=3, relation_type?: str }
FundamentalCrossCondition { instrument_id: UUID, metric_key: str, operator: "above"|"below", value: float }
```
- Validated at the API boundary (replaces today's free-text `condition` + unvalidated `threshold`). `metric_key` validated against the S3 fundamentals metric vocabulary returned by `GET /api/v1/fundamentals/screen/fields` (the canonical screener field metadata; the frontend `MetricPicker` reads the same source). `window_hours` for NEWS_MOMENTUM is restricted to the trending endpoint's supported set `{24, 72, 168}`. NEWS_COUNT `window` v1 supports `7d` exactly (source rollup) + `24h/72h/168h` via trending; others 422 until v2.

#### 6.5.4 Evaluation: `RuleEvaluator` registry (`application/rules/`)
```
class RuleEvaluator(Protocol):
    rule_type: RuleType
    trigger: Literal["event","poll"]
    cadence_seconds: int | None             # poll types
    def relevant_topics(self) -> frozenset[str]   # event types
    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> EvalResult | None
EVALUATOR_REGISTRY: dict[RuleType, RuleEvaluator]   # the single registration point
```
- `EvalResult` = `{ value | count | delta_pct | connected, observed_at }`. The shared
  `should_fire`/`next_state` on `AlertRule` turn an `EvalResult` into a fire/no-fire + new
  `last_state` (edge transition + cooldown). One evaluator per type:
  - **PriceCrossEvaluator** (poll): batch `POST /internal/v1/price/batch`; fire on
    `was_above` transition matching `operator`.
  - **NewsCountEvaluator** (poll): `GET /internal/v1/instruments/{id}/news-rollup-7d`
    (7d) or trending counts (24/72/168 h); fire when count first ≥ threshold; re-arm when < threshold.
  - **NewsMomentumEvaluator** (poll): `GET /api/v1/news/trending-entities?window_hours=`;
    fire when `delta_pct ≥ threshold AND count ≥ min_count`.
  - **KgConnectionEvaluator** (event): on `graph.state.changed.v1`, pre-filter
    `affected_entity_ids` touches A and/or B, then confirm via S7
    `GET /api/v1/paths/between?source=A&target=B&max_hops=` (read its `connected` flag;
    if `relation_type` set, require a matching edge in the returned paths); latch
    `connected=true` (fires once).
  - **FundamentalCrossEvaluator** (poll): `GET /api/v1/fundamentals/timeseries?instrument_id=&metric=`
    → latest `value_numeric`; fire on metric edge transition vs `last_value`.

#### 6.5.5 Use case: `FireRuleAlertUseCase` (NEW)
Given a rule + `EvalResult` that passed `should_fire`: in **one transaction** write an `alerts`
row (`alert_type='user_rule'`, `severity=rule.severity`, `payload={rule_type, rule_id,
observed, condition_snapshot}`, `dedup_key=sha256(rule_id : transition_signature)`), a
`pending_alerts` row **for `rule.user_id` only**, and an `outbox_events` row; post-commit push
over the existing Valkey WebSocket channel; update `rule.last_state` (fired_at). Reuses the
transaction shape of `AlertFanoutUseCase` but targets the owner, not watchlist watchers.

#### 6.5.6 Process: `alert-rule-poller` (NEW, 5th S10 process — R22)
APScheduler loop (template: `infrastructure/email/scheduler_main.py`). Base tick 60 s. Each
cycle: load `enabled` poll-type rules whose `is_due(now)` per type cadence; group by service;
batch-read; run evaluators from the registry; fire via `FireRuleAlertUseCase`; persist
`last_state`. Watchdog + liveness gauge + `runs_total{outcome}` (NFR-6). Restart-safe (edge
memory in DB).

### 6.6 Frontend Changes (worldview-web)

- **`lib/api/alertRules.ts`** (NEW) — typed CRUD against `/v1/alert-rules` (TanStack Query
  hooks `useAlertRules`, `useCreateAlertRule`, `useUpdateAlertRule`, `useDeleteAlertRule`).
  Replaces `lib/alerts/rules.ts` localStorage layer (kept only as a one-release fallback shim,
  then deleted).
- **`components/alerts/AlertWizard.tsx`** (NEW) — type-first 2-step wizard inside the existing
  Dialog: Step 1 = grid of 5 type cards (icon + "fires when…"); Step 2 = per-type condition
  editor + entity scope + live NL summary + severity + notify toggles + Back/Save. Absorbs
  `AlertRuleBuilder` and the Edit tab of `RuleManagerDialog`.
- **`components/alerts/condition-editors/`** (NEW) — `PriceCrossEditor`, `NewsVolumeEditor`,
  `NewsMomentumEditor`, `KgConnectionEditor`, `FundamentalCrossEditor`. Each renders the
  structured fields from §6.5.3.
- **`components/common/EntityPicker.tsx`** (NEW, extracted from the inline `EntityPicker`
  function in `components/intelligence/PathBetweenPanel.tsx`) — debounced `searchFundamentals`
  (from `lib/api/search.ts`, which enriches to a real KG `entity_id`). Used by
  news/momentum/connection editors (two instances for connection). `TickerPicker`
  (`components/workspace/TickerPicker.tsx`, uses `searchInstruments`) reused for
  price/fundamental (instrument_id).
- **`components/alerts/MetricPicker.tsx`** (NEW) — fetches the S3 metric vocabulary from
  `GET /api/v1/fundamentals/screen/fields` (via the gateway) and emits a backend-valid
  `metric_key`. (Same source the backend validates against; do not hard-code from the
  screener `FilterState`.)
- **`lib/alerts/format.ts`** (EXTEND) — add a NEW per-type `ruleToNaturalLanguage(rule)` for the
  live summary + list rendering (the file currently exports only `formatAlertTitle`).
- **Entry points (NEW):** ＋ Alert on the instrument detail header (opens wizard pre-scoped to
  the instrument, defaulting to price/fundamental/news types); ＋ Alert on the KG graph / Path
  panel (opens wizard pre-scoped to KG_CONNECTION with the two entities prefilled); existing
  `/alerts` page buttons re-pointed to `AlertWizard`.
- **`RuleManagerDialog` / `AlertsList`** — read rules from the server API; show real
  enabled/paused + last-fired; drop the "local only" badge.

### 6.7 Data Flow

- **Create (all types):** wizard → `POST /v1/alert-rules` (S9, user JWT) → S10 validates the
  discriminated `condition` → inserts `alert_rules` row → 201. UI invalidates `useAlertRules`.
- **Evaluate (poll types):** `alert-rule-poller` tick → load due rules → batch S3/S6 read →
  evaluator → `should_fire` (edge+cooldown) → `FireRuleAlertUseCase` → `alerts`+`pending`+outbox
  → WebSocket to owner → `/alerts` toast + list.
- **Evaluate (KG_CONNECTION):** `graph.state.changed.v1` → intelligence consumer pre-filter
  (A,B touched) → S7 pairwise-path confirm → `should_fire` (latch) → `FireRuleAlertUseCase`.
- **Manage:** list/pause/edit/delete via CRUD; editing `condition` resets `last_state` (re-arm).

## 7. Architecture Decisions & Trade-offs

| Decision | Alternatives | Choice & rationale |
|----------|-------------|--------------------|
| **AD-1 Poll vs push for price/fundamental/news** | (a) PULL poller; (b) new Kafka emitters | **PULL.** No price/fundamental/momentum topic exists; ingest cadence is 2–5 min/6 days anyway, so a push stream can't fire faster. Poller rides existing REST with zero upstream change. Emitters deferred to v2. |
| **AD-2 Edge-trigger + per-rule `last_state` in DB** | (a) reuse time-bucket dedup; (b) in-process state | **DB `last_state`.** The current 5-min time-bucket dedup is condition-agnostic and would spam ("fires every tick"). DB-persisted edge memory is the only restart-safe way to fire once per transition (NFR-5). |
| **AD-3 KG connection: event + S7 confirm** | (a) periodic S7 path poll; (b) enrich event with `new_edges` | **Event + confirm (v1).** `graph.state.changed.v1` already flows and S10 already consumes it; pre-filter cheaply, confirm the exact A↔B edge via the existing pairwise-path API. `new_edges` enrichment is the v2 optimisation (avoids the confirm read). |
| **AD-4 Single poller process for all poll types** | (a) one process per type; (b) reuse intelligence consumer | **One `alert-rule-poller`.** Simplest topology addition (5th process, R22); per-type cadence throttling inside one loop. KG stays on the event consumer. |
| **AD-5 New `/alert-rules` resource (keep one-shot `/alerts`)** | (a) overload `/alerts`; (b) breaking replace | **New resource.** Clean separation of *rules* (standing) vs *alerts* (fired); avoids breaking the rag-chat LLM `create_alert` tool (repointed later). |
| **AD-6 Discriminated-union `condition`** | (a) keep free-text; (b) per-type columns | **Discriminated union (JSONB + Pydantic).** Validated at the boundary, flexible per type, fixes the silent-drop class from unvalidated free-text. |

## 8. Break-Surface Analysis (per skill §2.7)

| Change | Currently exists | What breaks | Migration strategy |
|--------|------------------|-------------|--------------------|
| Add `alert_rules` table | head 0009 | nothing (new table) | migration 0010, additive; no backfill |
| New S10 CRUD routes `/api/v1/alert-rules` | only `/api/v1/alerts*` | nothing | additive routes + tests |
| New S9 proxy `/v1/alert-rules` | `/v1/alerts*` proxies | nothing | additive proxy methods |
| New `RuleType` enum + `condition` VO | none | nothing | new modules |
| Extend `alert-intelligence-consumer` for KG_CONNECTION | consumes graph.state.changed → GRAPH_CHANGE fan-out | must not disturb existing GRAPH_CHANGE path; same consumer group, idempotent | add rule-eval branch after existing fan-out; dedup by rule_id |
| New `alert-rule-poller` process | 4 S10 processes | compose + deploy topology | new compose service, gated by config; same image |
| Frontend: replace localStorage rules | `lib/alerts/rules.ts` localStorage; `RuleManagerDialog`/`AlertRuleBuilder` | components reading localStorage; tests asserting localStorage; existing rule list | `lib/api/alertRules.ts` swap (file-swap anticipated by the header); keep a one-release localStorage→server import shim; update component tests |
| Frontend: 4-option type select → 5 typed cards | type enum in 3 files | tests asserting the 4 options | update the type source-of-truth + tests |

**Existing tests at risk:** S10 `create_alert`/routes tests (additive — unaffected); frontend
`RuleManagerDialog`/`AlertRuleBuilder`/`lib/alerts/rules` tests (rewritten to server API);
alerts-page tests (entry points). No existing fired-alert delivery test changes.

## 9. Security

- **Multi-tenant:** every rule query filters `tenant_id` AND `user_id` (from JWT); a user can
  never read/modify another user's rules (404 on cross-owner access). Firing targets only
  `rule.user_id`.
- **Input validation:** discriminated-union `condition` (Pydantic) rejects malformed params;
  `metric_key` allow-listed against the S3 vocabulary; UUIDs validated (no silent coercion —
  fixes the current `CreateAlertUseCase` UUID-coercion footgun).
- **Authz:** all `/alert-rules` endpoints require an authenticated user at S9; internal JWT to
  S10 (existing `InternalJWTMiddleware`). Poller/consumer use the service account.
- **Resource abuse:** per-user rule cap (config, default 200) + CRUD rate limit (60/min);
  poller only reads enabled rules; batch reads bounded (≤ 50 ids/call).
- **No secrets in rules;** S3/S6/S7 reads go through internal clients with the service-account
  signed JWT (S3 client extends the existing `S3MarketDataClient`; S6 + S7 graph-path clients are
  NEW — the existing `S7EntityResolver` only resolves names, not paths).

## 10. Failure Modes (cross-ref BUG_PATTERNS.md)

| Dependency / step | Failure | Handling |
|-------------------|---------|----------|
| S3 `/price/batch` down | poller read fails | evaluator skips this cycle, increments error counter, retries next tick; no state change (no false fire/clear) |
| S6 rollup/trending down | news evaluators fail | same: skip + retry; `last_state` untouched |
| S7 path confirm down | KG eval can't confirm | do **not** fire (fail-closed); log + retry on next event |
| Poller crash mid-cycle | partial evaluation | `last_state` persisted per-rule transactionally; restart resumes; no double-fire (edge memory in DB) — NFR-5 |
| DB write fails in `FireRuleAlertUseCase` | alert not persisted | transaction rollback; `last_state.last_fired_at` not advanced → retried next cycle (BP-705 family: must persist edge state only on commit) |
| Dedup collision (rule fires twice same transition) | race | UNIQUE `dedup_key=sha256(rule_id:transition_sig)` → `DuplicateAlertError` → swallow |
| Flapping at boundary | price oscillates around level | cooldown_seconds re-arm; edge-only fire; (optional hysteresis band v2) |
| `graph.state.changed.v1` replay/backfill | re-fire | `is_backfill` suppression (existing AD-10) + rule_id dedup |

## 11. Scalability

- Rules: thousands max; poller scan is an indexed `WHERE enabled` query. Price cycle (60 s)
  batches all PRICE_CROSS instrument_ids into ≤ 50-id `/price/batch` calls. News/fundamental on
  hourly+ cadence. Well within S3/S6 budgets (NFR-2).
- WebSocket delivery reuses the existing per-user Valkey pub/sub channel.

## 12. Architecture Compliance Gate (RULES.md)

| Rule | Applies | Decision | Compliant |
|------|---------|----------|-----------|
| R7/R9 — no cross-service DB | yes | S10 reads S3/S6/S7 via internal REST only | PASS |
| R8 — no dual writes (outbox) | yes | `FireRuleAlertUseCase` writes alerts+pending+outbox in one txn | PASS |
| R10 — UUIDv7 | yes | `rule_id = new_uuid7()` | PASS |
| R11 — UTC timestamps | yes | all timestamptz via `utc_now()` | PASS |
| R22 — process topology | yes | new `alert-rule-poller` declared as a process | PASS |
| R25 — API uses only use cases | yes | routes → CRUD use cases, no infra import | PASS |
| R27 — ReadOnlyUoW for reads | yes | rule list/get use `ReadOnlyUnitOfWork`; create/update/fire use write UoW | PASS |
| R28 — Avro forward-compat | yes | no new topic v1; any v2 enrichment additive w/ default | PASS |
| BP-007 — type as VARCHAR not PG enum | yes | `rule_type` VARCHAR + CHECK | PASS |
| BP-705 — worker observability | yes | poller liveness gauge + runs counter + watchdog | PASS |

No FAIL rows → cleared to write/plan.

## 13. Observability

- Counters: `alert_rule_evaluations_total{rule_type,outcome=fired|nofire|error}`,
  `alert_rule_fired_total{rule_type}`, `alert_rules_active{rule_type}` (gauge).
- Poller: `alert_rule_poller_last_success_timestamp_seconds`, `alert_rule_poller_runs_total{outcome}`, watchdog.
- structlog events: `alert_rule_created/updated/deleted`, `alert_rule_fired` (rule_id, rule_type, transition), `alert_rule_eval_failed` (service, error).

## 14. Test Strategy

### Unit
| Test | Verifies | Pri |
|------|----------|-----|
| `test_price_cross_edge_below_to_above` | fires only on transition, not while held | HIGH |
| `test_cooldown_suppresses_refire` | no re-fire within cooldown_seconds | HIGH |
| `test_news_count_rearm_below_threshold` | re-arms when count drops < N | HIGH |
| `test_news_momentum_min_count_gate` | suppresses 1→2 noise | MED |
| `test_kg_connection_latches_once` | fires once on connect, `connected=true` | HIGH |
| `test_fundamental_cross_uses_last_value` | edge vs stored last_value | HIGH |
| `test_condition_discriminated_union_validation` | bad metric_key/missing node_b → 400 | HIGH |
| `test_rule_keying_invariant` | KG needs node_a≠node_b; others need entity_id | HIGH |
| `test_fire_targets_owner_not_watchlist` | pending_alerts for rule.user_id only | HIGH |
| `test_dedup_key_includes_rule_id` | two rules same entity don't collide | HIGH |
| `test_last_state_persists_only_on_commit` | rollback doesn't advance last_fired_at | HIGH |

### Integration
| Test | Infra | Verifies |
|------|-------|----------|
| `test_crud_roundtrip` | Postgres | create→get→patch(reset last_state)→delete, tenant isolation |
| `test_poller_price_fires_once` | Postgres + S3 stub | poll → edge fire → no refire next cycle |
| `test_kg_connection_event_confirm` | Postgres + S7 stub | graph event pre-filter + confirm → fire |
| `test_gateway_proxy_auth` | S9 | unauth 401; cross-owner 404 |

### Frontend (vitest)
| Test | Verifies |
|------|----------|
| `AlertWizard.type-selection` | 5 cards → correct editor mounts |
| `condition-editors.*` | each editor emits the structured `condition` payload |
| `ruleToNaturalLanguage` | per-type NL summary strings |
| `alertRules.api` | CRUD hooks call the right endpoints; localStorage removed |
| `EntityPicker` | returns real entity_id; two-instance (connection) |

## 15. Open Questions & Decisions

All BLOCKING OQs resolved (decisions baked into the design):
- **OQ-1 [RESOLVED]** Push vs pull → PULL poller (AD-1).
- **OQ-2 [RESOLVED]** id keying → instrument_id (price/fundamental), entity_id (news/momentum), node_a/node_b (KG). §6.5.1.
- **OQ-3 [RESOLVED]** news-momentum metric → S6 `trending-entities.delta_pct` with `min_count` gate. §6.5.4.
- **OQ-4 [RESOLVED]** KG-connection trigger → "path appears within `max_hops` (≤3), optional `relation_type`", latching once. §6.5.3.
- **OQ-5 [RESOLVED]** fundamental `metric_key` vocabulary → S3 screener catalogue names. §6.5.3.
- **OQ-6 [DEFERRED→v2]** backtest/preview endpoint → out of scope (§5); NL summary ships instead.
- **OQ-7 [DEFERRED→v2]** news windows beyond 7d/24/72/168h, compound rules, push emitters.

## 16. Estimation (rough)

| Block | Effort |
|-------|--------|
| Shared foundation (table 0010, enum, condition VO, registry, FireRuleAlertUseCase, CRUD API S10+S9, poller scaffold) | ~3–4 d |
| 5 evaluators (price M, fundamental S–M, news-count M, momentum M, kg-connection M–L) | ~5–7 d |
| Frontend (alertRules API, AlertWizard, 5 editors, EntityPicker, MetricPicker, NL summary, entry points, test migration) | ~4–5 d |
| Observability + integration tests + deploy | ~2 d |

Suggested waves in `/plan`: **W1** foundation (table+enum+VO+registry+CRUD+poller scaffold);
**W2** poll evaluators (price, fundamental, news-count, news-momentum) + poller wiring;
**W3** KG-connection (consumer extension + S7 confirm); **W4** frontend wizard + editors +
pickers + API swap; **W5** entry points + NL summary + observability + QA.

---
*Compounding check: add BP entries during /implement for (a) "rule fired every tick" if
edge-trigger is skipped, (b) cross-owner rule leakage if tenant/user filter is missed. No
RULES.md change needed (R22/R27 already cover the new process/reads).*
