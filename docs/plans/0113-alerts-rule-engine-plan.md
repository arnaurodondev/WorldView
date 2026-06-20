---
id: PLAN-0113
title: Alerts Rule Engine + 5 User-Creatable Alert Types
prd: PRD-0113
status: draft
created: 2026-06-20
updated: 2026-06-20
branch: feat/md-reliability-followups
---

# PLAN-0113 — Alerts Rule Engine + 5 User-Creatable Alert Types

## Overview
PRD: [PRD-0113](../specs/0113-alerts-rule-engine.md)
**Services affected:** S10 alert (core), S9 api-gateway (proxy), worldview-web (UI). S3/S6/S7 consumed **read-only** (no code change). infra (new poller compose service).
**Single sub-plan** (the work is tightly coupled around S10's new rule engine). **5 waves.**

Task ID format: `T-<wave>-<seq>` (e.g. T-1-01).

### Codebase-state verification (read-the-code, 2026-06-20)
| PRD ref | Type | Service | Current state | Delta |
|---|---|---|---|---|
| `alert_rules` | DB table | S10 | does not exist (head **0009**) | NEW migration **0010** |
| `RuleType`, `AlertRule`, `condition` VO | domain | S10 | none (only `AlertType`, `Alert` exist in `domain/enums.py`/`entities.py`) | NEW modules |
| `RuleEvaluator` registry + evaluators | application | S10 | none | NEW `application/rules/` |
| `FireRuleAlertUseCase` | application | S10 | none (reuse `AlertFanoutUseCase` txn shape) | NEW |
| `alert-rule-poller` | process | S10 | none (template: `infrastructure/email/scheduler_main.py`) | NEW process |
| `/api/v1/alert-rules` CRUD | API | S10 | none (`api/routes.py` has `/api/v1/alerts*` only) | NEW routes |
| `/v1/alert-rules` proxy | API | S9 | none (`routes/alerts.py` proxies `/v1/alerts*`) | NEW proxies |
| `s3_client.get_price_batch` | infra client | S10 | **only `get_ohlcv_bulk` + `get_fundamentals` exist** in `infrastructure/clients/s3_client.py` | NEW method (or use `get_ohlcv_bulk` last-close) |
| S6 news-rollup/trending client | infra client | S10 | verify — may need NEW `s6_client` (S7 enrichment client exists for fanout) | NEW/verify |
| S7 pairwise-path client | infra client | S10 | S7 enrichment client exists (fanout uses it); confirm path method | verify/extend |
| `KG_CONNECTION` consumer branch | infra | S10 | `intelligence_consumer.py` consumes `graph.state.changed.v1`→GRAPH_CHANGE fanout | EXTEND (additive branch) |
| `lib/api/alertRules.ts` | frontend | web | none (`lib/alerts/rules.ts` = localStorage) | NEW + retire localStorage |
| `AlertWizard`, condition editors, `EntityPicker`, `MetricPicker` | frontend | web | none (`RuleManagerDialog`/`AlertRuleBuilder` = free-text localStorage; `PathBetweenPanel` has an inline EntityPicker to extract; `TickerPicker` exists) | NEW components |

### Name tags (BP-405 guard)
Verified existing: `AlertFanoutUseCase`, `IntelligenceConsumer`, `infrastructure/email/scheduler_main.py`, `s3_client.get_ohlcv_bulk`, `s3_client.get_fundamentals`, `api/routes.py`, `api/schemas.py`, `domain/enums.py`, `domain/entities.py`, S9 `routes/alerts.py`, web `PathBetweenPanel.tsx`, `TickerPicker.tsx`, `RuleManagerDialog.tsx`, `lib/alerts/rules.ts`.
**NEW (created in this plan):** `alert_rules` table, `RuleType`, `AlertRule`, `rule_conditions` VO, `application/rules/` (registry + 5 evaluators), `FireRuleAlertUseCase`, `alert-rule-poller`, `s3_client.get_price_batch` (NEW — only ohlcv/fundamentals exist), `lib/api/alertRules.ts`, `AlertWizard`, `condition-editors/*`, shared `EntityPicker`, `MetricPicker`.

### Pre-flight gate (Phase 0.5)
| Check | Result |
|---|---|
| No BLOCKING OQs | PASS (PRD §15: all resolved or v2-deferred) |
| External API reality | PASS (no external provider; internal S3/S6/S7 endpoints verified in signal-sources audit) |
| Cross-plan conflict | PASS (no active plan touches `alert_db`/alert rules; existing alert PLANs complete) |
| PRD recency | PASS (written today) |
| Architecture compliance | PASS (PRD §12 compliance table, no FAIL) |

---

## Sub-Plans
Single sub-plan **A — Alerts Rule Engine** (S10 + S9 + web). Waves W1–W5.

## Dependency graph
```
W1 (foundation) ──► W2 (poll evaluators) ──► W5 (entry points + obs + QA)
        │           └► W3 (KG-connection)  ──►┘
        └──────────────► W4 (frontend wizard) ─► W5
```
W2 and W3 both depend on W1 and can run in parallel. W4 depends on W1 (the CRUD contract) and can run in parallel with W2/W3. W5 depends on W2+W3+W4.

---

## Wave 1 — Rule-engine foundation (domain + persistence + CRUD + poller scaffold)

**Goal:** Standing-rule store + typed conditions + CRUD API + the evaluator-registry seam + an empty poller process — the codebase can persist/list/edit rules end-to-end (no evaluation yet).
**Depends on:** none
**Estimated effort:** 3–4 h
**Architecture layer:** domain → infrastructure → application → API

#### T-1-01: Domain — `RuleType` enum + `condition` value objects
**Type:** impl · **depends_on:** none · **blocks:** T-1-02,T-1-03,T-1-04
**Target files:** `services/alert/src/alert/domain/enums.py` (extend), `services/alert/src/alert/domain/rule_conditions.py` (NEW)
**PRD ref:** §6.5.1, §6.5.3
**What to build:** `RuleType` StrEnum (`PRICE_CROSS, NEWS_COUNT, NEWS_MOMENTUM, KG_CONNECTION, FUNDAMENTAL_CROSS`) + a Pydantic discriminated union of the 5 condition models (exact fields in PRD §6.5.3) with validators (`value>0`, `node_a≠node_b` enforced at entity level, `metric_key` non-empty, `window`/`window_hours` allow-lists). `parse_condition(rule_type, dict) -> Condition`.
**Invariants:** condition shape matches rule_type; unknown fields rejected (`extra='forbid'`).
**Tests (inline):** `test_condition_discriminated_union_validation` (each type valid + each rejects bad fields), `test_price_cross_value_positive`, `test_news_count_window_allowlist`, `test_kg_max_hops_range`. Min 8.
**Acceptance:** [ ] 5 condition models validate/serialize round-trip; [ ] bad payloads raise; [ ] ruff+mypy clean.

#### T-1-02: Domain — `AlertRule` aggregate (edge-trigger + cooldown logic)
**Type:** impl · **depends_on:** T-1-01 · **blocks:** T-1-03,T-2-*,T-3-*
**Target files:** `services/alert/src/alert/domain/entities.py` (add `AlertRule`)
**PRD ref:** §6.5.2, §6.4
**What to build:** `AlertRule` dataclass (all `alert_rules` columns, PRD §6.4). Methods: `should_fire(eval_result, now) -> bool` (edge transition vs `last_state` + cooldown), `next_state(eval_result, now) -> dict`, `is_due(now, cadence_seconds) -> bool`. Per-type cooldown defaults (PRD §6.5.2). Keying invariant in factory (KG needs node_a≠node_b non-null; others need entity_id). IDs via `common.ids.new_uuid7()` (R10); timestamps `common.time.utc_now()` (R11).
**Tests (inline):** `test_price_cross_edge_below_to_above`, `test_cooldown_suppresses_refire`, `test_news_count_rearm_below_threshold`, `test_kg_connection_latches_once`, `test_fundamental_cross_uses_last_value`, `test_rule_keying_invariant`, `test_is_due_throttles_by_cadence`. Min 10 (PRD §14 Unit).
**Acceptance:** [ ] edge-only fire; [ ] cooldown re-arm; [ ] keying invariant raises; [ ] mypy clean.

#### T-1-03: Infra — `alert_rules` table model + migration 0010 + repository
**Type:** schema · **depends_on:** T-1-02 · **blocks:** T-1-04,T-1-05
**Target files:** `services/alert/src/alert/infrastructure/db/models.py` (add `AlertRuleModel`), `services/alert/alembic/versions/0010_create_alert_rules.py` (NEW), `services/alert/src/alert/infrastructure/db/repositories/` (add `AlertRuleRepository` + ABC `IAlertRuleRepository` in `application/ports/`)
**PRD ref:** §6.4
**What to build:** ORM model + migration (exact columns/indexes/CHECKs in PRD §6.4; head 0009→0010; `rule_type` VARCHAR+CHECK per BP-007; `last_state` JSONB nullable). Repository (save/get/list-by-owner/update/delete/list-enabled-by-type) behind an ABC port (R25).
**Downstream test impact:** none external (new table). Add `services/alert/tests/unit/test_alert_rule_repository.py`.
**Tests:** repo round-trip, tenant/owner filter, list-enabled-by-type, update resets via app layer.
**Acceptance:** [ ] migration applies fwd+rollback; [ ] CHECK rejects bad keying; [ ] indexes present.

#### T-1-04: Application — rule CRUD use cases (R25 ports, R27 read/write split)
**Type:** impl · **depends_on:** T-1-03 · **blocks:** T-1-05
**Target files:** `services/alert/src/alert/application/use_cases/manage_rules.py` (NEW: `CreateRule`, `ListRules`, `GetRule`, `UpdateRule`, `DeleteRule`)
**PRD ref:** §6.2
**Port interfaces:** `IAlertRuleRepository` (ABC, from T-1-03). **Read/Write:** List/Get = `ReadOnlyUnitOfWork` (R27); Create/Update/Delete = `UnitOfWork`. Update with `condition` change resets `last_state=null` (re-arm). Owner-scoped (tenant_id+user_id from caller); cross-owner get → not-found.
**Tests:** `test_crud_roundtrip`, `test_update_condition_resets_last_state`, `test_cross_owner_get_returns_none`, `test_per_user_rule_cap` (default 200, PRD §9).
**Acceptance:** [ ] read uses ReadOnlyUoW; [ ] tenant isolation; [ ] cap enforced.

#### T-1-05: API — S10 `/api/v1/alert-rules` routes + S9 proxy
**Type:** impl · **depends_on:** T-1-04 · **blocks:** T-4-*
**Target files:** `services/alert/src/alert/api/routes.py` (+ `api/schemas.py` request/response models), `services/api-gateway/src/api_gateway/routes/alerts.py` (proxies) + `services/api-gateway/src/api_gateway/clients/` alert client methods
**PRD ref:** §6.2
**What to build:** POST/GET(list)/GET(id)/PATCH/DELETE per PRD §6.2 (status codes, errors 400/401/404/409/422, rate-limit 60/min). Routes call only use cases (R25). S9 proxies auth-gated, inject internal JWT (mirror existing `/v1/alerts*` proxies). `ReadUoWDep` for GETs, `UoWDep` for writes (R27).
**Downstream test impact:** S9 alert client tests (additive). Add `services/alert/tests/api/test_alert_rules_routes.py`, `services/api-gateway/tests/` proxy test.
**Tests:** route happy paths + each error; `test_gateway_proxy_auth` (401 unauth, 404 cross-owner).
**Acceptance:** [ ] full CRUD via S9; [ ] discriminated condition validated at boundary; [ ] auth enforced.

#### T-1-06: Infra/config — `alert-rule-poller` process scaffold + registry + S3 price client
**Type:** impl · **depends_on:** T-1-02 · **blocks:** T-2-*
**Target files:** `services/alert/src/alert/application/rules/__init__.py` + `registry.py` (NEW: `RuleEvaluator` Protocol + `EVALUATOR_REGISTRY`), `services/alert/src/alert/infrastructure/rules/poller_main.py` (NEW, template `infrastructure/email/scheduler_main.py`), `services/alert/src/alert/infrastructure/clients/s3_client.py` (add `get_price_batch` — NEW), config (`config.py` poll cadences + per-user cap + enable flag), `infra/compose/docker-compose.yml` (+ `alert-rule-poller` service, same image, command `python -m alert.infrastructure.rules.poller_main`)
**PRD ref:** §6.5.4, §6.5.6, NFR-2/6
**What to build:** the registry seam (empty), an APScheduler poller loop (base tick 60s, `is_due` throttle, loads enabled poll rules, no evaluators wired yet → no-op), liveness gauge + `runs_total{outcome}` + watchdog (BP-705), `s3_client.get_price_batch(instrument_ids) -> {id: last_price}` calling `POST /internal/v1/price/batch`. Process declared (R22).
**Tests:** `test_poller_loads_due_rules`, `test_get_price_batch_parses`, `test_registry_lookup`.
**Acceptance:** [ ] poller boots healthy as a 5th process; [ ] registry resolvable; [ ] price client batches ≤50.

#### Pre-read (W1)
`services/alert/src/alert/domain/{enums,entities}.py`, `application/use_cases/alert_fanout.py` + `create_alert.py`, `infrastructure/db/models.py`, `alembic/versions/0009_add_user_rule_alert_type.py`, `api/routes.py` + `api/schemas.py`, `infrastructure/email/scheduler_main.py`, `infrastructure/clients/s3_client.py`, `services/api-gateway/src/api_gateway/routes/alerts.py`.

#### Validation Gate (W1)
- [ ] ruff + mypy clean on `services/alert`, `services/api-gateway`
- [ ] migration 0010 applies fwd + rollback; head moves 0009→0010
- [ ] ≥ 30 new unit tests pass; CRUD integration green
- [ ] poller + new compose service boot healthy
- [ ] docs/services/alert.md updated (new table, CRUD endpoints, poller process)

#### Architecture Compliance (W1)
- [ ] R25 ABC ports (`IAlertRuleRepository`); routes → use cases only
- [ ] R27 ReadOnlyUoW for List/Get; UnitOfWork for writes
- [ ] R10 `new_uuid7()` for `rule_id`; R11 `utc_now()` for timestamps
- [ ] R12 structlog in poller/use cases
- [ ] R22 poller declared as a process; R32 migration number from verified head (0010)
- [ ] BP-007 `rule_type` VARCHAR+CHECK (not PG enum)

#### Break Impact (W1)
| Broken file | Why | Fix |
|---|---|---|
| `services/api-gateway` alert client | new proxy methods | add `create_rule/list_rules/get_rule/update_rule/delete_rule` to the alert client |
| docs/services/alert.md | new table/endpoints/process | document `alert_rules`, `/alert-rules`, poller |
| `services/alert/tests` conftest | new repo/UoW fixtures | add `alert_rules` fixtures |

#### Regression Guardrails (W1)
- **BP-007**: store `rule_type` as VARCHAR + CHECK, never a PG enum (zero-DDL future types).
- **BP-705**: poller MUST emit liveness gauge + runs counter + watchdog + wrap work in a timeout (no silent stall).
- **BP-590/R42**: single worktree only — this plan executes in `worldview-wt-md-reliability`.

---

## Wave 2 — Poll evaluators (price, fundamental, news-count, news-momentum) + firing

**Goal:** Four poll-type rules evaluate continuously and fire (edge-triggered) through the poller.
**Depends on:** W1
**Estimated effort:** 5–6 h · **Layer:** application + infrastructure clients

#### T-2-01: `FireRuleAlertUseCase` (shared firing path, outbox)
**Type:** impl · **depends_on:** T-1-04,T-1-06 · **blocks:** T-2-02..05,T-3-02
**Target files:** `services/alert/src/alert/application/use_cases/fire_rule_alert.py` (NEW)
**PRD ref:** §6.5.5, §6.4 (dedup), R8
**What to build:** given `(rule, eval_result)` that passed `should_fire`: one transaction writes `alerts` (`alert_type='user_rule'`, `severity=rule.severity`, `payload={rule_type, rule_id, observed, condition_snapshot}`, `dedup_key=sha256(rule_id:transition_signature)`), a `pending_alerts` row **for `rule.user_id` only**, and an `outbox_events` row (R8 outbox); post-commit WebSocket push via the existing Valkey channel; advance `rule.last_state.last_fired_at` **only on commit**. Reuse `AlertFanoutUseCase` txn shape; ABC ports for repos. **Write** UoW.
**Tests:** `test_fire_targets_owner_not_watchlist`, `test_dedup_key_includes_rule_id`, `test_last_state_persists_only_on_commit`, `test_two_rules_same_entity_no_collision`.
**Acceptance:** [ ] owner-targeted; [ ] outbox used; [ ] rollback doesn't advance last_fired_at.

#### T-2-02: `PriceCrossEvaluator`
**Type:** impl · **depends_on:** T-2-01 · **blocks:** T-2-06
**Target files:** `services/alert/src/alert/application/rules/price_cross.py` (NEW) + register in `registry.py`
**PRD ref:** §6.5.4 (price), §6.5.1 (instrument_id keying)
**What to build:** poll evaluator, `cadence=60s`. Batch instrument_ids via `s3_client.get_price_batch`; `EvalResult{value, observed_at}`; `should_fire` uses `last_state.was_above` vs `operator/value`. Port: `IS3PriceClient` (ABC) impl by `s3_client`.
**Tests:** edge below→above + above→below; no-fire while held; missing price skips (no state change).

#### T-2-03: `FundamentalCrossEvaluator`
**Type:** impl · **depends_on:** T-2-01 · **blocks:** T-2-06
**Target files:** `services/alert/src/alert/application/rules/fundamental_cross.py` (NEW) + register
**PRD ref:** §6.5.4 (fundamental), §6.5.3 (`metric_key` vocab)
**What to build:** poll `cadence=21600s` (6h). Read `GET /api/v1/fundamentals/timeseries?instrument_id=&metric=metric_key` (add `s3_client.get_fundamental_metric` if absent — verify) → latest value; edge vs `last_state.last_value`. `metric_key` validated against S3 vocab (screener catalogue names).
**Tests:** edge cross; unknown metric_key rejected at create (T-1-01); slow-cadence throttle.

#### T-2-04: `NewsCountEvaluator`
**Type:** impl · **depends_on:** T-2-01 · **blocks:** T-2-06
**Target files:** `services/alert/src/alert/application/rules/news_count.py` (NEW) + register, `services/alert/src/alert/infrastructure/clients/s6_client.py` (NEW or extend — verify an S6 client exists)
**PRD ref:** §6.5.4 (news count), signal-sources §Signal 2
**What to build:** poll `cadence=3600s`. `GET /internal/v1/instruments/{id}/news-rollup-7d` for `window=7d`; trending counts for 24/72/168h. Fire when count first ≥ threshold; re-arm when < threshold. Port `IS6NewsClient`.
**Tests:** crosses threshold once; re-arm below; window allow-list.

#### T-2-05: `NewsMomentumEvaluator`
**Type:** impl · **depends_on:** T-2-01 · **blocks:** T-2-06
**Target files:** `services/alert/src/alert/application/rules/news_momentum.py` (NEW) + register
**PRD ref:** §6.5.4 (momentum), signal-sources §Signal 3
**What to build:** poll `cadence=3600s`. `GET /api/v1/news/trending-entities?window_hours=` → find entity → `EvalResult{delta_pct, count}`; fire when `delta_pct ≥ threshold AND count ≥ min_count`; cooldown re-arm.
**Tests:** delta threshold fire; `min_count` gate suppresses 1→2 noise.

#### T-2-06: Wire evaluators into the poller + per-type cadence + observability
**Type:** impl · **depends_on:** T-2-02,T-2-03,T-2-04,T-2-05 · **blocks:** T-5-*
**Target files:** `services/alert/src/alert/infrastructure/rules/poller_main.py`
**What to build:** poller cycle resolves each due rule's evaluator from `EVALUATOR_REGISTRY`, runs `evaluate` → `should_fire` → `FireRuleAlertUseCase`, persists `next_state`. Emit `alert_rule_evaluations_total{rule_type,outcome}`, `alert_rule_fired_total{rule_type}`. Fail-soft per evaluator (skip + error counter, no state change).
**Tests (integration):** `test_poller_price_fires_once` (Postgres + S3 stub), per-type cadence throttling.

#### Pre-read (W2): `application/use_cases/alert_fanout.py`, `infrastructure/clients/s3_client.py`, `infrastructure/rules/poller_main.py`, S3 routers `price_snapshot.py`/`fundamental_metrics.py`, S6 `internal_news_rollup.py`/`trending_entities.py`.
#### Validation Gate (W2): ruff+mypy clean; ≥ 20 new tests; poller fires edge-triggered once in integration; docs/services/alert.md evaluator table.
#### Architecture Compliance (W2): R25 ABC client ports (`IS3PriceClient`,`IS6NewsClient`); R8 outbox in FireRuleAlertUseCase; R9 S3/S6 via REST only; R12 structlog.
#### Break Impact (W2): none external (additive). Update alert conftest with S3/S6 client stubs.
#### Regression Guardrails (W2): **BP-705** (poller obs); **BP-235** (httpx timeout: set `httpx.Timeout` on S3/S6 clients + `asyncio.wait_for`); edge-trigger correctness (no fire-every-tick); **R9** (no cross-service DB — REST only).

---

## Wave 3 — KG-connection (event-driven, S7 confirm)

**Goal:** `KG_CONNECTION` rules fire when an edge/path first appears between A and B, via the existing graph event + an S7 confirm read.
**Depends on:** W1 (and T-2-01 FireRuleAlertUseCase)
**Estimated effort:** 3–4 h · **Layer:** infrastructure consumer + application

#### T-3-01: S7 pairwise-path client method
**Type:** impl · **depends_on:** T-1-06 · **blocks:** T-3-02
**Target files:** `services/alert/src/alert/infrastructure/clients/s7_client.py` (extend; the fanout enrichment S7 client exists — add `confirm_connection(a, b, max_hops, relation_type?) -> bool`)
**PRD ref:** §6.5.4 (KG), signal-sources §Signal 4
**What to build:** call S7's existing pairwise-path endpoint; return whether a path ≤ max_hops (optionally of `relation_type`) exists. Port `IS7GraphClient`. httpx timeout + wait_for (BP-235).
**Tests:** path present→true, absent→false, timeout→fail-closed (false).

#### T-3-02: `KgConnectionEvaluator` + consumer branch
**Type:** impl · **depends_on:** T-3-01,T-2-01 · **blocks:** T-5-*
**Target files:** `services/alert/src/alert/application/rules/kg_connection.py` (NEW) + register, `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer.py` (EXTEND — additive branch after existing GRAPH_CHANGE fanout)
**PRD ref:** §6.5.4, §6.3, §8 (break surface)
**What to build:** on `graph.state.changed.v1`, after the existing fanout, load enabled `KG_CONNECTION` rules whose `node_a/node_b` are both touched by `affected_entity_ids` (cheap pre-filter), then `confirm_connection` via S7; `should_fire` latches `connected=true` (fires once); `FireRuleAlertUseCase`. Respect `is_backfill` suppression (existing AD-10). Idempotent (rule_id dedup).
**Tests:** `test_kg_connection_event_confirm` (Postgres + S7 stub); pre-filter skips unrelated events; latch fires once; backfill suppressed; existing GRAPH_CHANGE fanout unaffected.

#### Pre-read (W3): `infrastructure/messaging/consumers/intelligence_consumer.py` + `_main.py`, `infrastructure/clients/s7_client.py`, `infra/kafka/schemas/graph.state.changed.v1.avsc`, S7 pairwise-path router.
#### Validation Gate (W3): ruff+mypy; ≥ 8 new tests; existing intelligence-consumer tests still green; consumer-group unchanged.
#### Architecture Compliance (W3): R25 ABC `IS7GraphClient`; R9 REST-only; idempotent consumer (rule_id dedup); R28 (no schema change v1).
#### Break Impact (W3): `intelligence_consumer` tests — assert the existing GRAPH_CHANGE path is preserved (additive branch). Fix: add KG-rule branch tests without altering fanout asserts.
#### Regression Guardrails (W3): **BP-235** (S7 httpx timeout, fail-closed); idempotency on replay; **AD-10** backfill suppression; do NOT disturb the existing fanout (additive only).

---

## Wave 4 — Frontend: AlertWizard + condition editors + real CRUD (parallel with W2/W3)

**Goal:** Users create all 5 rule types through a type-first wizard backed by the real API; localStorage retired.
**Depends on:** W1 (the CRUD contract); can run parallel to W2/W3.
**Estimated effort:** 4–5 h · **Layer:** frontend (worldview-web). Heavy comments (user is new to Next.js). pnpm + vitest.

#### T-4-01: `lib/api/alertRules.ts` — real CRUD + types + retire localStorage
**Type:** impl · **depends_on:** T-1-05 · **blocks:** T-4-02..05
**Target files:** `apps/worldview-web/lib/api/alertRules.ts` (NEW), `apps/worldview-web/lib/alerts/rules.ts` (reduce to a one-release import shim, then slated for deletion)
**PRD ref:** §6.6, §6.2 (contract)
**What to build:** typed `AlertRule`/`RuleType`/`condition` TS types mirroring the backend; TanStack hooks `useAlertRules/useCreateAlertRule/useUpdateAlertRule/useDeleteAlertRule` → `/v1/alert-rules`. Map `condition` discriminated union.
**Tests:** `alertRules.api` (hooks hit correct endpoints; payload shape); localStorage path removed.

#### T-4-02: Shared `EntityPicker` + `MetricPicker`
**Type:** impl · **depends_on:** none · **blocks:** T-4-03,T-4-04,T-4-05
**Target files:** `apps/worldview-web/components/common/EntityPicker.tsx` (NEW — extract from `PathBetweenPanel`), `apps/worldview-web/components/alerts/MetricPicker.tsx` (NEW — wrap screener catalogue)
**PRD ref:** §6.6, UI audit §5
**What to build:** `EntityPicker` (debounced `searchFundamentals` → real `entity_id`); `MetricPicker` (screener metric catalogue → backend-valid `metric_key`). Reuse `TickerPicker` for instrument_id types (no new component).
**Tests:** EntityPicker returns entity_id; MetricPicker emits valid metric_key.

#### T-4-03: `AlertWizard` shell (type cards + step controller) + NL summary
**Type:** impl · **depends_on:** T-4-01 · **blocks:** T-4-04,T-4-05
**Target files:** `apps/worldview-web/components/alerts/AlertWizard.tsx` (NEW), `apps/worldview-web/lib/alerts/format.ts` (extend `ruleToNaturalLanguage`)
**PRD ref:** §6.6, FR-10/FR-13
**What to build:** 2-step wizard in the existing Dialog: Step 1 = 5 type cards (icon + "fires when…"); Step 2 = mount the type's editor + severity + notify toggles + **live NL summary** + Save (→ `useCreateAlertRule`). Edit mode reuses the same wizard. Per-type NL formatter.
**Tests:** `AlertWizard.type-selection` (card → correct editor mounts); `ruleToNaturalLanguage` per type.

#### T-4-04: Per-type condition editors (price, fundamental)
**Type:** impl · **depends_on:** T-4-02,T-4-03 · **blocks:** T-5-*
**Target files:** `apps/worldview-web/components/alerts/condition-editors/{PriceCrossEditor,FundamentalCrossEditor}.tsx` (NEW)
**PRD ref:** §6.5.3, §6.6
**What to build:** PriceCross = TickerPicker + operator Select + price Input → `{instrument_id,operator,value}`. FundamentalCross = TickerPicker + MetricPicker + operator + value → `{instrument_id,metric_key,operator,value}`.
**Tests:** each emits the structured condition payload.

#### T-4-05: Per-type condition editors (news-count, news-momentum, kg-connection)
**Type:** impl · **depends_on:** T-4-02,T-4-03 · **blocks:** T-5-*
**Target files:** `apps/worldview-web/components/alerts/condition-editors/{NewsVolumeEditor,NewsMomentumEditor,KgConnectionEditor}.tsx` (NEW)
**PRD ref:** §6.5.3, §6.6
**What to build:** NewsVolume = EntityPicker + count + window Select (+keyword) → `{entity_id,window,threshold,keyword?}`. NewsMomentum = EntityPicker + delta_pct + window_hours + min_count → `{entity_id,window_hours,delta_pct,min_count}`. KgConnection = **two** EntityPickers + max_hops + relation_type? → `{source_entity_id,target_entity_id,max_hops,relation_type?}` (+ optional inline `PathBetweenPanel` current-state preview).
**Tests:** each emits structured payload; KG two-picker; node_a≠node_b guard.

#### T-4-06: Migrate `RuleManagerDialog`/`AlertsList` to server rules
**Type:** impl · **depends_on:** T-4-01,T-4-03 · **blocks:** none
**Target files:** `apps/worldview-web/components/alerts/RuleManagerDialog.tsx`, `AlertRuleBuilder.tsx` (absorb into wizard), `app/(app)/alerts/page.tsx`
**What to build:** list/pause/edit/delete from `useAlertRules`; open `AlertWizard`; drop "local only" badge + the 4-option select.
**Tests:** manager renders server rules; pause/delete call API.

#### Pre-read (W4): `components/alerts/{RuleManagerDialog,AlertRuleBuilder}.tsx`, `lib/alerts/{rules,format}.ts`, `lib/api/alerts.ts`, `components/intelligence/PathBetweenPanel.tsx`, `components/workspace/TickerPicker.tsx`, `components/screener/ScreenerFilterBar.tsx`, `lib/api/search.ts`, `docs/ui/DESIGN_SYSTEM.md`.
#### Validation Gate (W4): pnpm typecheck + lint clean; vitest green (≥ 15 new tests); no localStorage rule path remains.
#### Architecture Compliance (W4): Frontend→S9 only (R14, talks to `/v1/alert-rules`); pnpm only; heavy comments.
#### Break Impact (W4): `lib/alerts/rules` localStorage tests → rewrite to server API; type-enum tests (4→5 + structured); alerts-page tests → wizard entry.
#### Regression Guardrails (W4): CSS `hsl(var())` no-paint class (use tokens, not inline var()); reuse existing pickers (don't duplicate); entity free-text→picker eliminates unresolved-ticker silent failure.

---

## Wave 5 — Entry points + observability + integration QA

**Goal:** Surface creation where users are (instrument page, KG graph), finish observability, end-to-end verify.
**Depends on:** W2, W3, W4
**Estimated effort:** 2–3 h · **Layer:** frontend wiring + integration

#### T-5-01: New creation entry points
**Type:** impl · **depends_on:** T-4-04,T-4-05 · **blocks:** none
**Target files:** instrument detail header (`apps/worldview-web/components/instrument/...`), KG graph / `PathBetweenPanel` (`components/intelligence/...`)
**What to build:** ＋ Alert on the instrument header → wizard pre-scoped to that instrument (price/fundamental/news defaults); ＋ Alert on the Path/graph panel → wizard pre-scoped to `KG_CONNECTION` with both entities prefilled (mirror existing `prefillEntity`).
**Tests:** entry opens wizard with prefill.

#### T-5-02: Observability dashboards/alerts wiring
**Type:** config · **depends_on:** T-2-06,T-3-02 · **blocks:** none
**Target files:** poller metrics already emitted (W1/W2); add staleness alert rule (`alert_rule_poller_last_success > 2× cadence`) + a small Grafana panel set.
**PRD ref:** §13, NFR-6.
**Tests:** metrics exposed on `/metrics`.

#### T-5-03: End-to-end integration QA + docs
**Type:** test/docs · **depends_on:** T-5-01,T-5-02 · **blocks:** none
**What to build:** deploy S10 (api+poller+consumer) + S9 + web; create one rule of each type via the UI; force-evaluate (seed a price cross / news count / graph edge) and confirm a single edge-triggered alert lands for the owner; verify cooldown. Update `docs/services/alert.md`, `services/alert/.claude-context.md`, `services/api-gateway/.claude-context.md`, `docs/apps/worldview-web.md`, TRACKING.md (5/5).
**Acceptance:** [ ] all 5 types fire once end-to-end; [ ] no spam (cooldown/edge); [ ] tenant isolation verified live.

#### Validation Gate (W5): full deploy healthy; all 5 types verified live; docs updated; TRACKING 5/5.
#### Architecture Compliance (W5): R22 poller in topology; obs per BP-705.
#### Break Impact (W5): none new (wiring).
#### Regression Guardrails (W5): verify edge-trigger live (the canonical "fires every tick" risk); confirm owner-only delivery (no watchlist fan-out leak).

---

## Cross-Cutting Concerns
- **Contracts:** no Avro/topic changes v1 (PRD §6.3). Any v2 `new_edges` enrichment = additive (R28).
- **Migrations:** S10 only — `0010_create_alert_rules` (head 0009→0010). No other service migrates.
- **Config (new, `services/alert/.../config.py` + dev env example):** `ALERT_RULE_POLLER_ENABLED` (default true), `ALERT_RULE_POLL_TICK_SECONDS=60`, per-type cadences, `ALERT_RULE_MAX_PER_USER=200`, S6 base URL (if new s6_client).
- **Docs:** `docs/services/alert.md`, `services/alert/.claude-context.md`, `services/api-gateway/.claude-context.md`, `docs/apps/worldview-web.md`, `docs/services/api-gateway.md` (new routes).

## Risk Assessment
- **Critical path:** W1 (foundation) → everything. W2/W3/W4 parallel after W1; W5 last.
- **Highest risk:** W2 edge-trigger/cooldown correctness (the "fires every tick" anti-pattern) + poller↔S3 load; W3 KG pre-filter+confirm semantics (single-entity assumption break).
- **Rollback:** `ALERT_RULE_POLLER_ENABLED=false` disables evaluation instantly; CRUD/UI degrade to "rules stored but dormant"; migration 0010 is additive (drop table to fully revert).
- **Testing gaps:** live signal seeding for integration (price cross / graph edge) — use stubs in CI, manual seed in W5 live QA.

## Recommended execution order
`/implement PLAN-0113 Wave 1` → then W2 ∥ W3 ∥ W4 (separate sessions; W4 frontend-only is conflict-free with W2/W3 backend) → `/implement PLAN-0113 Wave 5`.

*Compounding check: BP candidates to add during /implement — "rule fires every evaluation (no edge-trigger)" and "rule alert leaks to watchlist watchers instead of owner". No RULES.md change (R22/R25/R27 already cover the additions).*
