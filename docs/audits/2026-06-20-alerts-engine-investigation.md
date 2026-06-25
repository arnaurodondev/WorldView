# Alerts Engine Investigation — S10 Rule/Evaluation/Delivery Core

**Date:** 2026-06-20
**Scope:** `services/alert/` (S10) + `services/api-gateway/` (S9) alert proxy. READ-ONLY.
**Goal:** Map the current alert engine so we can add 5 new alert types:
1. Stock price crossing X
2. Amount of news ≥ N
3. Increase in news momentum
4. Connection appears between two KG nodes
5. A fundamental metric crossing value Y

**Companion investigations:** per-signal data sources (sibling agent), UI (sibling agent). This report owns the **engine / rule model / evaluation pipeline / delivery / extensibility seam**.

---

## TL;DR — the single most important finding

**S10 has no rule engine today.** It is an *event fan-out router*, not a rule evaluator.

- There is **no persistent `AlertRule` entity, table, or evaluator**. The `Alert` entity is a *fired* alert (a materialised notification), never a standing rule.
- Alerts are produced in exactly **one** way: an upstream Kafka event arrives (`nlp.signal.detected.v1`, `graph.state.changed.v1`, `intelligence.contradiction.v1`), S10 looks up who *watches the entity* (via S1 watchlists), dedups, writes an `alerts` row + per-user `pending_alerts` rows + an outbox event, and pushes over WebSocket. The "rule" is implicit: *"this entity is on someone's watchlist AND an intelligence event mentioned it."*
- The `POST /api/v1/alerts` endpoint and its `CreateAlertUseCase` are **misnamed**. They do **not** create a standing rule. They write a single one-shot `alerts` row with `alert_type=user_rule` immediately, store `{condition, threshold}` in the JSONB `payload`, and **nothing ever evaluates that condition again**. Live proof below.
- **No price or fundamentals Kafka topics exist** on the platform (see Topic Inventory). Market data is REST-pull only (S3). So 3 of the 5 new types (price-cross, fundamental-cross, news-count) have **no event stream to react to** — they require a new **scheduled poller** that S10 does not currently have (the only scheduler in S10 is the weekly email digest cron).

**Live DB evidence** (`alert_db`, 2026-06-20):

```
 alert_type  | count
-------------+-------
 SIGNAL      |  528
 GRAPH_CHANGE|  291
 user_rule   |    2     ← one-shot fired rows, never re-evaluated
```

The two `user_rule` rows:

```
 severity | title              | cond        | threshold
----------+--------------------+-------------+------------------
 low      | Alert: price_below | price_below | {"value": 150.0}
 medium   | Alert: price_above | price_above | {"value": 300.0}
```

A user "set an alert for price below 150"; S10 wrote a `low`-severity notification row *at creation time* and never compared the live price to 150 again. **This is the gap the 5 new types must close: standing rules + continuous evaluation.**

---

## 1. Domain model — alert types, entities, severity

### 1.1 Enums (`services/alert/src/alert/domain/enums.py`)

```python
class AlertType(StrEnum):
    SIGNAL        = "SIGNAL"        # ← nlp.signal.detected.v1
    GRAPH_CHANGE  = "GRAPH_CHANGE"  # ← graph.state.changed.v1   (the "GRAPH_CHANGE" the QA saw)
    CONTRADICTION = "CONTRADICTION" # ← intelligence.contradiction.v1
    USER_RULE     = "user_rule"     # ← PLAN-0082 Wave B, one-shot create_alert

class AlertSeverity(StrEnum):  # PRD-0021
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"
```

- `alert_type` is stored as **`VARCHAR(100)`**, *not* a PG enum (deliberate, BP-007). Adding new types is a **zero-DDL** change at the storage layer — migration 0009 is literally a no-op that only updates a column comment. This is a real advantage for us.
- `AlertSeverity` is derived for SIGNAL alerts from `market_impact_score` via `SeverityThresholds.classify()` (critical≥0.85, high≥0.65, medium≥0.40); graph/contradiction are force-MEDIUM (F-13). For user rules, severity is whatever the request says (default `low`).

### 1.2 Entities (`services/alert/src/alert/domain/entities.py`)

- **`Alert`** — the fired alert. Key fields: `alert_id`, `entity_id`, `alert_type`, `severity`, `source_event_id`, `source_topic`, `payload: dict` (JSONB), `dedup_key` (UNIQUE), `created_at`, `tenant_id`, enrichment (`title`, `ticker`, `entity_name`, `signal_label`), ack/snooze (`acknowledged_at`, `acknowledged_by_user_id`, `snooze_until`).
  - `compute_dedup_key(entity_id, alert_type, created_at, window_seconds=300)` = `sha256(entity_id:alert_type:window_bucket)` where `window_bucket = epoch // window_seconds`. **No condition/threshold in the key** — see §5.
- **`PendingAlert`** — per-user undelivered row (`user_id`, `alert_id`, `delivered_at`).
- **`AlertDelivery`** — per-user/channel delivery record (channel is WEBSOCKET-only).
- **`AlertSubscription`** — `user_id → entity_id` via `watchlist_id`, with an `alert_types: list[str]` array. **Note:** this table exists in the schema but is *not* the thing that drives fan-out — fan-out resolves watchers live from S1 watchlists via a Valkey cache, not from `alert_subscriptions`. There is **no standing condition** on a subscription.
- `OutboxEvent`, `DeadLetterEntry`, `EmailPreference` — supporting plumbing.

**There is no `AlertRule` entity.** The condition/threshold a user submits lives only in `Alert.payload` JSON of a one-shot row.

### 1.3 Tables (`alembic/versions/0001…0009`, `infrastructure/db/models.py`)

`alert_subscriptions`, `alerts`, `alert_deliveries`, `pending_alerts`, `outbox_events`, `dead_letter_queue`, `email_preferences`, `email_log`. **No `alert_rules` table.** Migrations: 0001 base, 0004 severity, 0005 tenant_id, 0006 enrichment cols, 0007 ack/snooze, 0009 user_rule comment-only. Latest head = **0009**; next migration = **0010**.

---

## 2. Evaluation / trigger pipeline (event-driven only)

```
S6/S7 emit Kafka event ──► IntelligenceConsumer.process_message()
  (nlp.signal.detected.v1 / graph.state.changed.v1 / intelligence.contradiction.v1)
        │  resolve topic, clamp market_impact_score
        ▼
  AlertFanoutUseCase.execute(event, topic, market_impact_score)
        1. backfill suppression (AD-10)
        2. extract entity_id from event (per-topic field)
        3. alert_type = TOPIC_ALERT_TYPE[topic]
        4. severity (classify score | force MEDIUM)
        5. watchers = WatchlistCache.get_watchers(entity_id)   ← S1, Valkey cache-aside
        6. dedup check (sha256 key, UNIQUE)
        7. build Alert (enrich entity_name/ticker/signal_label/title via S7)
        8. ONE transaction: alerts row + pending_alerts rows + outbox_events
        9. POST-COMMIT WebSocket push to each watcher (Valkey pub/sub channel alert:{user_id})
       10. metrics
```

**Files:**
- `infrastructure/messaging/consumers/intelligence_consumer.py` — the only signal-side consumer. Topic→type routing lives in `_KNOWN_TOPICS` / `_resolve_topic`. Has liveness watchdog + heartbeat + lag-throttle (43h-wedge hardening, audit 2026-06-16).
- `application/use_cases/alert_fanout.py` — the matching/creation engine. Topic→type map = `TOPIC_ALERT_TYPE` (line ~75). Entity-id extraction = `_extract_entity_id` (per-topic field names). This is **the de-facto "evaluator"**: it is keyed entirely by **topic**, and "matching" = "is this entity watched?".
- `infrastructure/messaging/consumers/watchlist_consumer.py` — consumes `portfolio.watchlist.updated.v1` only to **invalidate the watcher cache**. Not an evaluator.
- `infrastructure/messaging/outbox/dispatcher.py` — topic-agnostic; publishes pre-serialised `payload_avro` bytes keyed by `event.topic`. **Adding a new outbound topic needs no dispatcher change.**

**Scheduling:** the only scheduled process in S10 is `infrastructure/email/scheduler_main.py` (APScheduler hourly cron for the weekly digest). **There is no polling evaluator for continuous signals.**

**Process topology (R22, 4 processes):** `alert` (API), `alert-dispatcher`, `alert-intelligence-consumer`, `alert-watchlist-consumer`. A new poller would be a **5th process**.

---

## 3. Extensibility seam — where a new rule type plugs in

There is **no registry / strategy / per-type evaluator abstraction today.** Type handling is **hardcoded** in two dicts (`TOPIC_ALERT_TYPE`, `_KNOWN_TOPICS`) and a per-topic `if/elif` (`_extract_entity_id`, `_resolve_topic`). The fan-out path is fundamentally *"entity-watched + topic→type"*, which does **not** generalise to threshold conditions.

**Therefore the seam must be built, not reused.** Two distinct trigger mechanisms are needed:

- **(a) Event-reactive types** (news-count, news-momentum, KG-connection) — can hang off existing Kafka streams (`nlp.article.enriched.v1`, `graph.state.changed.v1`, `relation.type.proposed.v1`). These extend the consumer side.
- **(b) Poll-reactive types** (price-cross, fundamental-cross) — **no Kafka stream exists**; need a new scheduled poller hitting S3 REST (`S3MarketDataClient.get_ohlcv_bulk` / `get_fundamentals`, both already present in `infrastructure/clients/s3_client.py`).

**Recommended seam: a `RuleEvaluator` strategy registry keyed by `rule_type`.**

```python
# application/rules/evaluator.py  (new)
class RuleEvaluator(Protocol):
    rule_type: RuleType
    trigger: Literal["event", "poll"]
    def relevant_topics(self) -> frozenset[str]: ...          # for event-driven
    async def evaluate(self, rule: AlertRule, ctx: EvalContext) -> RuleMatch | None: ...

EVALUATOR_REGISTRY: dict[RuleType, RuleEvaluator] = {...}      # one place to register the 5 new types
```

Both the new consumer paths and the new poller resolve evaluators from this single registry. New types = add an enum value + register one evaluator + (if poll) the poller already loops it. This is the clean, compounding extension point.

---

## 4. Rule-creation API contract (current)

**S10** (`api/routes.py`, `api/schemas.py`):
- `POST /api/v1/alerts` → `CreateAlertRequest{ entity_id: UUID, condition: str, threshold: dict, severity: str="low" }` → 201 `AlertCreatedResponse`. `tenant_id`/`user_id` come from the internal JWT, never the body. 409 on dedup collision. **Creates a one-shot alert, not a rule.**
- `GET /api/v1/alerts/pending`, `DELETE /…/ack`, `PATCH /…/acknowledge`, `PATCH /…/snooze`, `GET /…/history`, `WS /…/stream`. **No list/update/delete *rule* endpoints** (there are no rules to manage).
- `GET /internal/v1/instruments/{id}/active-alert-flag` — screener aggregate.

**Validation today is minimal:** `condition` is a free-text `str(min_length=1,max_length=100)`; `threshold` is an unvalidated `dict`. The docstring advertises `price_below | price_above | volume_spike | percent_change` but **nothing enforces the set or the threshold shape**. `CreateAlertUseCase` silently coerces a bad `entity_id` to a fresh UUIDv7 and a bad `severity` to LOW.

**S9 gateway** (`services/api-gateway/src/api_gateway/routes/alerts.py`): thin pass-through proxies for all the above to `clients.alert.*`, auth-gated on `request.state.user`, injecting the internal JWT. `/alerts/stream/ws-url` mints a scoped (`alerts:stream`) RS256 ws-token. Adding rule CRUD = add matching proxy methods (mechanical).

**LLM tool:** `rag-chat` exposes a `create_alert` tool (`application/pipeline/handlers/alerts.py`, `infrastructure/clients/s10_client.py`) that calls the same `POST /api/v1/alerts`. Same one-shot limitation.

---

## 5. Idempotency / re-trigger / cooldown — the critical gap for continuous signals

- **Dedup key** = `sha256(entity_id : alert_type : floor(epoch/300))`. It collapses repeat alerts for the same entity+type into one per **5-minute wall-clock window**, enforced by a UNIQUE constraint on `alerts.dedup_key` (race-safe via `DuplicateAlertError` → rollback).
- **It is time-bucketed, not edge-triggered, and condition-agnostic.** `condition`/`threshold` are **not** in the key. So for a price-cross rule, the current model would fire **once per 5-min window for as long as the condition holds** — exactly the "fires every tick" anti-pattern. And because all `user_rule` alerts share `alert_type=user_rule`, two different rules on the *same entity* would dedup-collide.
- **No cooldown, no edge-trigger, no last-state tracking** anywhere. There is `snooze_until` (manual, per-fired-alert) but no automatic per-rule re-arm.

**For the 5 new continuous types we MUST add edge-triggering + per-rule state.** Recommended: store `last_value` / `last_state` (e.g. `was_above`) on the rule row; only fire on a **transition** (below→above), then optionally a `cooldown_seconds` / re-arm hysteresis band to avoid flapping at the boundary. The dedup key for rule-fired alerts should include `rule_id` (not just entity+type).

---

## 6. Topic inventory (what we can and cannot react to)

All platform Kafka topics (`infra/kafka/init/create-topics.sh`):

```
alert.delivered.v1            market.instrument.discovered.v1
content.article.raw.v1        market.prediction.v1
content.article.stored.v1     nlp.article.enriched.v1   ← per-article enrichment (news)
entity.canonical.created.v1   nlp.signal.detected.v1    ← already consumed
entity.dirtied.v1             portfolio.events.v1
entity.refresh.v1             portfolio.watchlist.updated.v1
graph.state.changed.v1   ←    relation.type.proposed.v1 ← KG relation proposals
intelligence.contradiction.v1
```

**There is NO `market.price.*`, `ohlcv`, `quote`, or `fundamentals` topic.** Price + fundamentals are REST-only (S3). `news momentum` is not a topic either — the momentum signal is computed elsewhere (sibling data-source agent owns this; momentum likely derivable from `nlp.article.enriched.v1` counts or an S6/S3 query).

---

## 7. Proposed backend design for the 5 new rule types

### 7.0 Shared foundation (do this first)

1. **New `alert_rules` table** (migration 0010) — the missing standing-rule store:

   | column | type | notes |
   |---|---|---|
   | `rule_id` | UUID PK (uuidv7) | |
   | `tenant_id`, `user_id` | UUID | from JWT |
   | `rule_type` | VARCHAR(50) | new `RuleType` enum (see below) |
   | `entity_id` | UUID NULL | NULL for the 2-node KG-connection type (uses node_a/node_b) |
   | `params` | JSONB | per-type condition schema (§7.1) |
   | `severity` | VARCHAR(10) | default per type |
   | `enabled` | bool | pause without delete |
   | `cooldown_seconds` | int | re-arm after fire (default per type) |
   | `last_state` | JSONB NULL | edge-trigger memory (last_value, was_above, last_count, last_fired_at) |
   | `created_at`, `updated_at` | timestamptz | |

   Indexes: `(rule_type) WHERE enabled`, `(entity_id) WHERE enabled`, `(tenant_id, user_id)`.

2. **`RuleType` enum** (new): `PRICE_CROSS`, `NEWS_COUNT`, `NEWS_MOMENTUM`, `KG_CONNECTION`, `FUNDAMENTAL_CROSS`. Keep `AlertType` for the *fired* row; introduce `AlertType.USER_RULE` (already exists) as the fired-alert type, with `payload.rule_type` carrying the specific kind. (Avoids touching the dedup/severity logic of the legacy types.)

3. **`RuleEvaluator` registry** (§3) — `application/rules/`. One evaluator per `RuleType`.

4. **Two new trigger processes:**
   - **`alert-rule-poller`** (new APScheduler process, mirror `email/scheduler_main.py`): every N seconds, load enabled poll-type rules, batch-query S3, run evaluators, fire on edge transition. Covers PRICE_CROSS + FUNDAMENTAL_CROSS (+ NEWS_COUNT if count is queried rather than streamed).
   - Extend **`alert-intelligence-consumer`** (or a sibling consumer) to also subscribe to `nlp.article.enriched.v1` and `relation.type.proposed.v1` for event-reactive rule types.

5. **Rule firing path:** evaluators produce a `RuleMatch`; a shared `FireRuleAlertUseCase` writes the `alerts` + `pending_alerts` + outbox rows (reuse the existing transaction shape from `AlertFanoutUseCase`) and pushes WebSocket. **Dedup key for rule alerts = `sha256(rule_id : transition_id)`** so edge-triggering, not time-bucketing, governs re-fire; respect `cooldown_seconds` via `last_state.last_fired_at`.

6. **Rule CRUD API:** `POST/GET/PATCH/DELETE /api/v1/alert-rules` on S10 + S9 proxies. Per-type `params` validation via a discriminated Pydantic union keyed on `rule_type` (replaces today's free-text `condition`/unvalidated `threshold`). **Deprecate the misleading one-shot `POST /api/v1/alerts`** (or repoint it to create a PRICE_CROSS rule for back-compat with the LLM tool).

### 7.1 Per-type design, effort, risk

| # | Type | `RuleType` | Trigger | `params` schema | Edge / cooldown | Effort | Risk |
|---|------|-----------|---------|-----------------|-----------------|--------|------|
| 1 | Price crossing X | `PRICE_CROSS` | **Poll** S3 `get_ohlcv_bulk` | `{operator: above\|below, value: float}` | fire on below→above (or above→below) transition; `last_state.was_above`; cooldown ~1h default | **M** | Poll latency vs intraday gaps; no price topic ⇒ new poller is mandatory; S3 freshness/last-close vs live |
| 2 | News count ≥ N | `NEWS_COUNT` | **Event** (`nlp.article.enriched.v1`, incr per-entity rolling counter in Valkey) **or Poll** (count query over window) | `{window: 24h, threshold: N}` | fire once when rolling count first crosses N in window; re-arm when count drops below | **M** | Counting source of truth (Valkey rolling vs DB query); window semantics; per-entity fan-in volume |
| 3 | News momentum increase | `NEWS_MOMENTUM` | **Event/Poll** (depends on where momentum is computed — sibling agent) | `{lookback, baseline, delta_pct\|zscore}` | edge on momentum crossing threshold; cooldown to avoid flap | **M–L** | Momentum metric is not a topic; needs sibling's data source; noisiest signal ⇒ hysteresis essential |
| 4 | Connection between 2 KG nodes | `KG_CONNECTION` | **Event** (`graph.state.changed.v1` / `relation.type.proposed.v1`) **+** optional S7 confirm query | `{node_a: UUID, node_b: UUID, relation_type?: str, max_hops?: int}` | fire **once** when the edge/path first appears; `last_state.connected=true` latches it | **M–L** | `entity_id` model is single-entity — needs node_a/node_b on the rule; "connection appears" may require an S7 path query (existing pairwise VLE endpoint, ~60–800ms) not just the event; dedup must key on the pair |
| 5 | Fundamental metric crossing Y | `FUNDAMENTAL_CROSS` | **Poll** S3 `get_fundamentals` | `{metric: str, operator: above\|below, value: float}` | edge transition on metric; cooldown long (~24h, fundamentals update slowly) | **S–M** | Metric naming/availability in S3 fundamentals payload; very low update frequency ⇒ poll interval can be hourly+ |

**Effort legend:** S ≈ ½–1 day, M ≈ 1–2 days, L ≈ 3+ days (per type, excluding shared foundation which is ~3–4 days).

### 7.2 Cross-cutting risks / decisions to flag

- **No price/fundamentals event bus** → a polling process is unavoidable. This is the biggest architectural addition (new process, S3 rate-limit budget, edge-state persistence). Decide poll cadence vs S3 load early.
- **Edge-triggering is mandatory** for types 1, 3, 5 (continuous signals) and strongly advised for 2, 4. The current time-bucket dedup will spam users; do **not** reuse it for rule alerts.
- **Per-rule dedup key** (`rule_id`-based) — current key collides across rules on the same entity+type.
- **2-entity rule (type 4)** breaks the single-`entity_id` assumption baked into fan-out and the schema; add `node_a/node_b` to `alert_rules` and a pair-aware evaluator + dedup.
- **Validation debt:** today `condition`/`threshold` are unvalidated free-text/dict; the new discriminated-union schema fixes a latent silent-drop class.
- **Watcher model divergence:** legacy alerts fan out to *all watchlist watchers of an entity*; new rules are owned by *one user* (the rule creator). Firing must target `rule.user_id`, not the watchlist — a different delivery target than the existing path.
- **Severity:** new rules carry user/explicit severity (no `market_impact_score`); keep them out of the `SeverityThresholds.classify` path.

---

## 8. Key files (absolute paths)

Engine / domain:
- `/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/services/alert/src/alert/domain/enums.py`
- `/…/services/alert/src/alert/domain/entities.py`
- `/…/services/alert/src/alert/application/use_cases/alert_fanout.py` (the de-facto evaluator)
- `/…/services/alert/src/alert/application/use_cases/create_alert.py` (one-shot, misnamed)

Consumers / triggers:
- `/…/services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py`
- `/…/services/alert/src/alert/infrastructure/messaging/consumers/watchlist_consumer.py`
- `/…/services/alert/src/alert/infrastructure/messaging/outbox/dispatcher.py` (topic-agnostic — no change needed for new outbound)
- `/…/services/alert/src/alert/infrastructure/email/scheduler_main.py` (the only existing scheduler — template for the new poller)

API / persistence:
- `/…/services/alert/src/alert/api/routes.py`, `/…/api/schemas.py`, `/…/api/dependencies.py`
- `/…/services/alert/src/alert/infrastructure/db/models.py`
- `/…/services/alert/alembic/versions/0001_create_alert_db.py` … `0009_add_user_rule_alert_type.py` (next = 0010)
- `/…/services/alert/src/alert/infrastructure/clients/s3_client.py` (`get_ohlcv_bulk`, `get_fundamentals` — already present for poll types)

Gateway / LLM:
- `/…/services/api-gateway/src/api_gateway/routes/alerts.py` (S9 proxies)
- `/…/services/rag-chat/src/rag_chat/application/pipeline/handlers/alerts.py`, `/…/infrastructure/clients/s10_client.py` (LLM `create_alert` tool → same one-shot endpoint)

Topics: `/…/infra/kafka/init/create-topics.sh`
