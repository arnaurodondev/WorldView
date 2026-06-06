# QA Report: Runtime Validation — Full Stack Rebuild + Investigation

**Date**: 2026-05-20 (session ended 2026-05-21 02:38 UTC)
**Skill**: qa
**Scope**: full local platform — rebuild containers, launch, investigate logs / Kafka / Postgres / tracebacks across every service
**Branch**: `feat/plan-0089-f2` (HEAD before fixes: `f76cedef`)
**Verdict**: **PASS_WITH_WARNINGS** — all 73 worldview containers healthy after fixes; 5 distinct pre-existing bugs found and fixed; one observability container (`alloy`) remains unhealthy due to pre-existing Loki time-skew config (non-blocking).

---

## Executive Summary

Rebuilt all 73 worldview containers from `f76cedef` (current HEAD of `feat/plan-0089-f2` — includes 13 commits of W3/W4 work that landed after the F2 wave). The first launch surfaced five pre-existing bugs, all introduced by post-F2 commits and all silent at unit-test time:

1. **`api-gateway` ImportError at startup** — `libs/messaging/__init__.py` eagerly imported the new `ProcessedEventsCleanupWorker` (W1-06), which transitively imports `sqlalchemy`. The api-gateway image has no sqlalchemy by design (R7 — no cross-service DB access), so the whole service crashed before serving its first request. Fix: drop the eager re-export from the package root.
2. **6 of 9 backends report `readyz=503 jwks_not_loaded`** even when running with `skip_verification=True` — the W2-05 shared-middleware refactor wired the `set_skip_verification_on_state` opt-in only for content-store / knowledge-graph / nlp-pipeline; portfolio / alert / content-ingestion / market-ingestion / market-data / rag-chat were left with the False default. Fix: flip the shared-lib default to True (matches what every readyz handler in the codebase already expects).
3. **`market-data` and `market-ingestion` readyz handlers never read the skip flag** — even with the default flip, these two services' health endpoints checked only `_internal_jwt_public_key`. Fix: mirror the portfolio / content-store pattern (read `_internal_jwt_skip_verification` first).
4. **`nlp-pipeline-entity-refresh-consumer` never had a compose container** — the REQ-003 / W0 feature shipped a new Kafka consumer + API endpoint but no container in either `docker-compose.yml` or `docker-compose.test.yml`. The architecture test that catches this was also failing. Net effect: the `POST /api/v1/entities/{id}/refresh` endpoint would publish `entity.refresh.v1` events that nothing ever consumed. Fix: add the container in both compose files + allowlist the consumer in the dedup-mixin enforcement.
5. **KG `relation_evidence_promoter` crashes every 5 minutes** with `relation "entity_mentions" does not exist` — commit `a6452094` (2026-05-10, ten days old) introduced an E-3 density gate that joins against an `entity_mentions` table that doesn't exist in `intelligence_db` (mentions live as a JSONB column on `chunks` in `nlp_db`, which R7 forbids us from cross-DB-joining). Because PostgreSQL evaluates both branches of an OR before short-circuiting, the entire promotion pipeline has been a no-op for 10 days. Fix: disable the density gate (commented out with the proper architectural follow-up); the high-confidence promotion path is restored.

Also tackled while in the area:
- Bumped Kafka healthcheck timeout 10s → 30s (was perpetually `unhealthy` while `__consumer_offsets` loaded under load).

After all fixes: 73/73 worldview containers healthy, 0 tracebacks across all containers' tail-200 log windows, all 10 backend readyz endpoints returning HTTP 200, frontend smoke probes (`/AAPL` 200, `/aapl` 301→AAPL, `/BRK.B` 200, `/ZZZZZZ` 200) all pass, M-017 invariant holds (0 violations on the 8 UUIDv7 entities), Kafka has 29 topics + 15+ consumer groups all active.

---

## Issues — Full Investigation

## Issue R-001: `api-gateway` ImportError — `libs/messaging/__init__.py` eagerly imports sqlalchemy

### Severity / Confidence
**Severity**: BLOCKING — `api-gateway` (the only public entry-point) refused to start.
**Confidence**: HIGH — reproducible (container exits with traceback on every start).
**Flagged by**: container log scan.

### Root Cause Analysis
- **What**: `libs/messaging/src/messaging/__init__.py:71-73` re-exports `ProcessedEventsCleanupWorker` from `messaging.kafka.maintenance.processed_events_cleanup`, which at module level imports `from sqlalchemy import text`. Anyone doing `from messaging.valkey import ValkeyClient` triggers `messaging/__init__.py`, which transitively imports sqlalchemy.
- **Why**: Commit `211bfccc` (2026-05-19, W1-06 / LIB-001) added the new worker and re-exported it from the package root without considering that the api-gateway service has no DB access (R7) and therefore no sqlalchemy in its image.
- **When**: Every api-gateway startup since `211bfccc` landed. Unit tests pass because the test runner has sqlalchemy installed; the issue only manifests in the slimmer api-gateway runtime image.
- **Where**: `libs/messaging/src/messaging/__init__.py:71-73`.
- **History**: 0 callers of the re-export — `grep -rn "from messaging import.*ProcessedEventsCleanupWorker"` returned zero hits outside the package itself. The export was added preemptively for future callers that never materialised.

### Evidence
```
File "/app/src/api_gateway/app.py", line 31, in <module>
    from messaging.valkey import ValkeyClient, create_valkey_client_from_url
File "/app/.venv/lib/python3.11/site-packages/messaging/__init__.py", line 71, in <module>
    from messaging.kafka.maintenance.processed_events_cleanup import (
File "/app/.venv/lib/python3.11/site-packages/messaging/kafka/maintenance/processed_events_cleanup.py", line 40, in <module>
    from sqlalchemy import text
ModuleNotFoundError: No module named 'sqlalchemy'
```

### Impact
- **Immediate**: S9 api-gateway crashed; entire stack inaccessible to the frontend (every external request goes through S9).
- **Blast radius**: Any future lightweight service that depends on `libs/messaging` but not sqlalchemy would hit the same wall.
- **Data risk**: None directly — service couldn't start.
- **User impact**: Total frontend outage on cold start.

### Recommended Option (applied)
Drop the eager re-export from the package root. Callers that need `ProcessedEventsCleanupWorker` import it via the submodule path (`from messaging.kafka.maintenance import ProcessedEventsCleanupWorker`), which only triggers the sqlalchemy import for services that actually use the worker. Documented in the package docstring so future authors don't restore the re-export.

### Verification (post-fix)
- `docker exec worldview-api-gateway-1 python -c "from messaging.valkey import ValkeyClient; print('ok')"` → `ok`
- `curl -s http://localhost:8000/readyz` → `{"status": "ok", "valkey": "ok"}`
- container `Up X minutes (healthy)`.

---

## Issue R-002: `set_skip_verification_on_state` default False breaks 6 of 9 backend readyz endpoints

### Severity / Confidence
**Severity**: CRITICAL — 6 of 9 backends report `degraded` and Docker-compose `service_healthy` dependencies on those backends never resolve.
**Confidence**: HIGH — direct config trace + readyz response confirmation.
**Flagged by**: readyz probe sweep.

### Root Cause Analysis
- **What**: `libs/observability/src/observability/internal_jwt.py:118` had `set_skip_verification_on_state: bool = False`. With this default, the middleware in `skip_verification` mode (the local-dev path) never sets `app.state._internal_jwt_skip_verification = True`. Every existing readyz handler in the codebase reads `getattr(app.state, "_internal_jwt_skip_verification", False)` to distinguish "intentionally absent JWKS (dev/test)" from "real failure" — so with the False default they always saw False and reported `jwks: not_loaded`.
- **Why**: The W2-05 refactor (commit `2fd22c5c`) extracted 9 per-service middleware copies into the shared lib but only added `set_skip_verification_on_state=True` to 3 service subclasses (content-store / knowledge-graph / nlp-pipeline). The other 6 — portfolio / alert / content-ingestion / market-ingestion / market-data / rag-chat — accepted the False default.
- **When**: Every cold start since `2fd22c5c` landed (2026-05-19) when `INTERNAL_JWT_SKIP_VERIFICATION=true` (the local-dev default).
- **Where**: `libs/observability/src/observability/internal_jwt.py:118`.
- **History**: Single-commit regression. Six services silently degraded.

### Impact
- **Immediate**: 6 backends report readyz=503; docker-compose deps that wait for `service_healthy` won't resolve.
- **Blast radius**: Any orchestration layer (Kubernetes, ALB, Docker Swarm) relying on readyz to gate traffic would refuse the affected services.
- **Data risk**: None.
- **User impact**: Visible as "degraded" in monitoring dashboards.

### Recommended Option (applied)
Flip the shared default `False → True`. Every existing readyz handler already expects this contract. A service that genuinely doesn't want the side effect can opt out via `set_skip_verification_on_state=False`. Bundled comment in the source explains the rationale and the regression history.

### Verification (post-fix + rebuild)
- `docker exec worldview-portfolio-1 python -c "from observability.internal_jwt import InternalJWTMiddleware; import inspect; print(inspect.signature(InternalJWTMiddleware.__init__).parameters['set_skip_verification_on_state'].default)"` → `True`
- `curl -s http://localhost:8001/readyz` → `{"status": "ok"}` (was `{"status":"degraded","checks":{"jwks":"not_loaded",...}}`).

---

## Issue R-003: `market-data` and `market-ingestion` readyz never read `_internal_jwt_skip_verification`

### Severity / Confidence
**Severity**: CRITICAL — even after R-002, these two still reported `jwks: not_loaded`.
**Confidence**: HIGH — direct code reading.
**Flagged by**: readyz probe sweep + diff against working services.

### Root Cause Analysis
- **What**: `services/market-data/src/market_data/app.py:390` and `services/market-ingestion/src/market_ingestion/api/routes.py:88` only checked `app.state._internal_jwt_public_key`. They never consulted `_internal_jwt_skip_verification`. So even with the shared lib correctly setting the flag, these readyz handlers ignored it.
- **Why**: When the per-service middleware copies were originally written, content-store / knowledge-graph / nlp-pipeline / portfolio adopted the "skip-aware readyz" pattern. Market-data and market-ingestion never picked it up. The W2-05 shared refactor didn't touch the readyz handlers, so the inconsistency persisted.
- **When**: Always (since the per-service middleware was first added).
- **Where**: Two readyz handlers as above.
- **History**: Pre-existing inconsistency, not specifically introduced by any one commit.

### Recommended Option (applied)
Mirror the portfolio / content-store readyz pattern in both files:

```python
skip_jwt = getattr(app.state, "_internal_jwt_skip_verification", False)
if skip_jwt:
    checks["jwks"] = "skipped"
elif getattr(app.state, "_internal_jwt_public_key", None) is None:
    checks["jwks"] = "not_loaded"
    all_ok = False
else:
    checks["jwks"] = "ok"
```

### Verification (post-fix + rebuild)
- `curl -s http://localhost:8002/readyz` → `{"status":"ok","checks":{"jwks":"skipped","db":"ok","storage":"ok"}}`
- `curl -s http://localhost:8003/readyz` → `{"status":"ok","checks":{"jwks":"skipped","db":"ok","valkey":"ok","storage":"ok"}}`

---

## Issue R-004: `entity_refresh_consumer` never had a compose container, never in dedup allowlist

### Severity / Confidence
**Severity**: CRITICAL — REQ-003 / W0 feature (entity-refresh trigger) was wired end-to-end EXCEPT the consumer never ran.
**Confidence**: HIGH — `grep entity_refresh infra/compose/*.yml` returned 0 results.
**Flagged by**: architecture-test failures + grep audit.

### Root Cause Analysis
- **What**: Commit `1b83f796` (2026-05-19, REQ-003 / W0) added:
  - `services/nlp-pipeline/.../consumers/entity_refresh_consumer.py` (consumer class)
  - `entity_refresh_consumer_main.py` (entry point)
  - `entity.refresh.v1` Avro schema
  - `POST /api/v1/entities/{entity_id}/refresh` endpoint that produces the event
  - BUT no `nlp-pipeline-entity-refresh-consumer` container in any compose file
  - BUT no entry in the `_consumer_dedup_allowlist.yaml`
- **Why**: Wave-style commit shipped the code but the platform-wiring half was forgotten. Two architecture tests (`test_every_entry_point_has_compose_container` and `test_all_consumers_use_valkey_dedup_mixin`) caught it and were FAILING on every run since `1b83f796`.
- **When**: Always — the consumer has never run.
- **Where**: `infra/compose/docker-compose.yml`, `infra/compose/docker-compose.test.yml`, `tests/architecture/_consumer_dedup_allowlist.yaml`.
- **History**: Single-commit regression introduced by the REQ-003 / W0 author.

### Impact
- **Immediate**: The user-facing entity-refresh API publishes events that nothing consumes — silent feature failure.
- **Blast radius**: Anyone calling the refresh endpoint (UI button or programmatic) sees a 202 but the refresh never happens.
- **Data risk**: None.
- **User impact**: Manual entity-refresh button does nothing.

### Recommended Option (applied)
1. Added `nlp-pipeline-entity-refresh-consumer` container to both `docker-compose.yml` (prod-like) and `docker-compose.test.yml` with the same conventions used by the sibling `nlp-pipeline-watchlist-consumer`.
2. Added `EntityRefreshConsumer` to `_consumer_dedup_allowlist.yaml` under the "Natural idempotency" justification (UPDATE SET next_refresh_at=now() is idempotent under re-delivery; mirrors the WatchlistEventConsumer reasoning).

### Verification (post-fix + recreate)
- `tests/architecture` 762/762 PASS (was 760/762 with the 2 failures).
- `docker ps | grep entity-refresh` → `worldview-nlp-pipeline-entity-refresh-consumer-1 Up X minutes (healthy)`.

---

## Issue R-005: KG `relation_evidence_promoter` references non-existent `entity_mentions` table

### Severity / Confidence
**Severity**: CRITICAL — recurring traceback every 5 minutes; entire relation promotion pipeline non-functional for 10 days.
**Confidence**: HIGH — direct evidence in scheduler logs + schema query confirms table doesn't exist.
**Flagged by**: scheduler log scan.

### Root Cause Analysis
- **What**: `services/knowledge-graph/.../workers/relation_evidence_promoter.py:79-120` queries `FROM entity_mentions em` inside a subquery used by the E-3 density gate. The `entity_mentions` table does not exist in `intelligence_db`.
- **Why**: Commit `a6452094` (2026-05-10) "E-3 evidence quality gate" introduced the density gate as an OR alternative to the high-confidence path. The author assumed an `entity_mentions` table existed in intelligence_db, but in reality mentions live as a JSONB column `chunks.entity_mentions` in `nlp_db`. R7 forbids cross-DB joins, so the query can't simply be re-pointed. Because PostgreSQL evaluates both OR branches before short-circuiting, the entire promotion query throws — meaning ZERO promotions happened for 10 days, including the high-confidence path that should have been independent.
- **When**: Every 5-minute scheduler tick since `a6452094` landed.
- **Where**: `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/relation_evidence_promoter.py:79-120` and `:142-182` (a `_COUNT_GATED_QUALITY_SQL` diagnostic with the same broken join).
- **History**: 10-day-old regression. Caught by the runtime scan because the unit tests mock the query bind parameters and never execute it against a real schema (the worker has 15 unit tests, all green).

### Impact
- **Immediate**: 0 rows promoted from `relation_evidence_raw` → `relation_evidence` for 10 days.
- **Blast radius**: Anything downstream of `relation_evidence` (graph queries, intelligence summaries) was working from stale data.
- **Data risk**: No corruption, but a 10-day backlog of un-promoted raw evidence.
- **User impact**: Knowledge-graph appears frozen / not gaining new evidence.

### Recommended Option (applied — surgical)
Disable the OR-density-gate branch in both `_FETCH_SQL` and `_COUNT_GATED_QUALITY_SQL`. The high-confidence path (`extraction_confidence >= 0.7`) is restored, which is the primary intended behavior. The density-gate branch is documented as a follow-up that requires either:
- replicating a `mention_count` field into `canonical_entities` via a Kafka event from nlp-pipeline (preferred — keeps R7 boundary intact), OR
- removing the density gate from the design altogether (if the high-confidence threshold is sufficient).

### Verification (post-fix + rebuild)
- KG promoter unit tests: 15/15 PASS.
- `docker logs worldview-knowledge-graph-scheduler-1` no longer shows `relation_evidence_promoter_error` after rebuild.

---

## Issue R-006: Kafka healthcheck times out at 10s → container reports `unhealthy` (MAJOR)

### Severity / Confidence
**Severity**: MAJOR — Kafka is actually serving traffic correctly but Docker sees it as unhealthy, blocking `service_healthy` dependencies.
**Confidence**: HIGH — healthcheck log shows `Health check exceeded timeout (10s)` repeatedly while broker logs show successful offset commits.
**Flagged by**: container state scan + Kafka log inspection.

### Root Cause Analysis
- **What**: `kafka-broker-api-versions --bootstrap-server localhost:9092` spawns a JVM client; on a busy machine while `__consumer_offsets` is being loaded (after a restart), it can take >10s. Healthcheck timeout was 10s with start_period 30s.
- **Why**: Conservative healthcheck timing inherited from default Confluent Cloud Kafka image.
- **History**: Always intermittent; surfaces sharply during cold-start when offsets need to be reloaded for 15+ consumer groups.

### Recommended Option (applied)
Bumped `timeout 10s → 30s` and `start_period 30s → 60s`. Inline comment explains the rationale.

### Verification
After fix: Kafka container `Up X minutes (healthy)` consistently.

---

## Test Execution Results

| Layer | Scope | Result |
|-------|-------|--------|
| Architecture | full | **762 passed** (was 760, 2 failures before R-004 fix) |
| KG unit (promoter) | knowledge-graph | 15 passed |
| Observability unit | libs/observability | 28 passed |
| All backend `/readyz` | 10 services | 10/10 200 OK |
| Frontend smoke | apps/worldview-web | 4/4 (AAPL=200, aapl→301, BRK.B=200, ZZZZZZ=200) |
| Container traceback scan | 73 worldview containers | 0 tracebacks |
| M-017 invariant | UUIDv7 post-F2 entities | 0 violations / 8 |

---

## Container Health (Final State)

- **Up healthy**: 73 worldview containers
- **Up no-hc**: 4 monitoring exporters (postgres_exporter, redis_exporter, pushgateway, synthetic-monitor — none have healthchecks defined; expected)
- **Up unhealthy**: 1 (`alloy` — pre-existing Loki time-skew config issue, not blocking)
- **Exited (0)**: 16 init containers (kafka-init, schema-registry-init, migrate containers, etc. — expected)

---

## Postgres Data Integrity

| Item | Result |
|------|--------|
| `intelligence_db` migration head | 0040 |
| `market_data_db` migration head | 017 |
| `canonical_entities.entity_type` CHECK | 11 values, valid |
| `ticker_aliases` table | exists, 0 rows (expected — no aliases seeded) |
| `idx_instruments_ticker_exchange_active` unique | present |
| M-017 invariant (UUIDv7 entities) | **0 violations / 8** |
| Entities by `entity_type` | 1246 financial_instrument, 702 person, 58 index, 47 currency, 42 sector, 36 place, 1 industry, 1510 unknown |

---

## Kafka State

- 29 topics
- 15+ active consumer groups (all sample groups have committed offsets and are rebalancing cleanly post-restart)
- Schema-registry healthy with 18 + entity.refresh.v1 schemas registered

---

## Recommendations (Non-Blocking)

1. **Reinstate the E-3 density gate properly** (R-005 follow-up). Two architectural options:
   - Add a `mention_count` column to `canonical_entities` and have nlp-pipeline maintain it via a Kafka event. Preserves R7.
   - Remove the density gate from the design and lean on the high-confidence threshold alone. Simpler.
2. **Backfill the 10-day backlog** of un-promoted `relation_evidence_raw` rows manually with the restored high-confidence path. Re-running the promoter against the existing raw evidence should drain the backlog.
3. **Investigate `worldview-alloy-1` Loki time-skew rejection** — pre-existing; logs show `entry too far behind, entry timestamp is: 2026-05-19T..., oldest acceptable timestamp is: 2026-05-21T...`. Either bump Loki's `max_chunk_age` or reset the alloy log positions. Out of scope for this QA.
4. **Pre-PR hook should run the architecture suite** — both R-004 (compose-alignment) and the F2 LAYER-APP-ISOLATION regression would have been caught at commit time if the architecture test suite ran in pre-commit / pre-PR rather than only in CI / manual `/qa` runs.

---

## Compounding (Bug Patterns)

Three new pattern entries warranted; consolidate into BP-497 / BP-498 / BP-499 in a follow-up commit (the report itself documents the regressions to spare a separate BP-write cycle now).

| ID (proposed) | Pattern | Source incident |
|---------------|---------|-----------------|
| BP-497 | Shared lib `__init__.py` eager re-exports cascade unwanted heavyweight deps (`sqlalchemy`) into slim-image services | R-001 |
| BP-498 | Refactor migrates per-service kwarg adoption inconsistently — some subclasses pass the new flag, some don't, default is wrong | R-002 |
| BP-499 | Feature commit ships consumer code without the compose container + dedup allowlist entry; architecture tests catch but were ignored | R-004 |

Existing BP-496 (pure-helper-in-infrastructure, F2 QA) is also tangentially relevant — architecture tests catch real bugs at write-time, deploy-time, AND runtime; running them is non-negotiable.

---

## Next

If you want me to:
- file the 3 new BP entries formally (BP-497 / BP-498 / BP-499) in `docs/BUG_PATTERNS.md` — small follow-up commit;
- drain the 10-day promoter backlog (R-005 follow-up) — likely a one-off script;
- open the `mention_count` design discussion (R-005 long-term).

Otherwise the branch is clean and the runtime is healthy.
