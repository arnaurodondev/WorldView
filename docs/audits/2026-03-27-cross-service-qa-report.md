# Cross-Service QA Report

Date: 2026-03-27
Scope: services market-ingestion, market-data, portfolio
Method: deep read-only code audit plus targeted test execution

## Validation Runs

- market-ingestion application plus infrastructure tests: pass with expected integration skips.
- market-data unit tests: pass with runtime warnings related to AsyncMock usage.
- portfolio unit tests: pass.
- combined cross-service pytest run in one command exposed test module name collision.

## Findings Summary

- High: 6
- Medium: 7
- Low: 3

## Market-Ingestion Findings

### High

1. Policy matching ignores exchange, timeframe, and variant despite accepting them in API.
- Evidence: signature includes these filters in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/policy_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/policy_repository.py#L57)
- Evidence: query only filters provider, dataset_type, enabled, symbol in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/policy_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/policy_repository.py#L75)
- Risk: wrong policy selected when multiple stream variants exist for same symbol.
- Status: confirmed.

2. Token bucket refill semantics are incomplete and drift from persistence model.
- Evidence: budget consumption happens in [services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py](services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py#L261)
- Evidence: refill method exists in [services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py](services/market-ingestion/src/market_ingestion/domain/entities/provider_budget.py#L32)
- Evidence: last_refill_at persisted in model in [services/market-ingestion/src/market_ingestion/infrastructure/db/models/provider_budget.py](services/market-ingestion/src/market_ingestion/infrastructure/db/models/provider_budget.py#L33)
- Evidence: repository save does not update last_refill_at in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/budget_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/budget_repository.py#L64)
- Risk: throttle behavior diverges from intended token-bucket logic under sustained load.
- Status: confirmed.

3. Backfill can be disabled before effective enqueue completion.
- Evidence: flag is flipped in build phase in [services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py](services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py#L130)
- Evidence: budget and per-tick cap apply later in [services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py](services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py#L76) and [services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py](services/market-ingestion/src/market_ingestion/application/use_cases/schedule_tasks.py#L81)
- Risk: partial backfill scheduling with premature transition to incremental mode.
- Status: confirmed.

### Medium

4. IngestionTask domain carries result_ref and completed_at but persistence does not.
- Evidence: domain fields in [services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py](services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py#L60) and [services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py](services/market-ingestion/src/market_ingestion/domain/entities/ingestion_task.py#L64)
- Evidence: success path sets these semantics in [services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py](services/market-ingestion/src/market_ingestion/application/use_cases/execute_task.py#L176)
- Evidence: model lacks fields in [services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py](services/market-ingestion/src/market_ingestion/infrastructure/db/models/ingestion_task.py#L13)
- Evidence: save persists only status and retry plus lease fields in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py#L149)
- Risk: runtime state visibility and auditability gap.
- Status: confirmed inconsistency.

5. worker_concurrency setting is defined but not applied in worker execution control.
- Evidence: config has the value in [services/market-ingestion/src/market_ingestion/config.py](services/market-ingestion/src/market_ingestion/config.py#L55)
- Evidence: worker executes batch via gather with no semaphore based on this setting in [services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py](services/market-ingestion/src/market_ingestion/infrastructure/workers/worker.py#L109)
- Risk: operators may assume concurrency cap that is not enforced.
- Status: confirmed.

6. External provider base URL is hardcoded, not routed via configurable proxy or gateway.
- Evidence: base URL constant in [services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py](services/market-ingestion/src/market_ingestion/infrastructure/adapters/providers/eodhd.py#L24)
- Risk: harder egress control, testing, and environment routing.
- Status: confirmed design limitation.

### Low

7. Task repository helper duplication increases drift risk.
- Evidence: helper exists in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py#L50)
- Evidence: write paths do manual mapping in insert and save methods in [services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py](services/market-ingestion/src/market_ingestion/infrastructure/db/repositories/task_repository.py#L92)
- Risk: future field additions may update one path but not another.
- Status: confirmed maintainability issue.

## Market-Data Findings

### High

1. Content-hash dedupe check uses dataset_type while stored event_type uses topic, making dedupe misses likely.
- Evidence: dedupe query passes dataset_type in [services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py#L143), [services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py#L148), [services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py#L229)
- Evidence: mark_processed stores event_type as topic in [services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py#L93)
- Evidence: repository checks exact event_type match in [services/market-data/src/market_data/infrastructure/db/repositories/ingestion_event_repo.py](services/market-data/src/market_data/infrastructure/db/repositories/ingestion_event_repo.py#L27)
- Risk: duplicate materialization work and avoidable storage reads.
- Status: confirmed.

2. Instrument flag updates are read-modify-write and exposed to concurrent stale writes.
- Evidence: consumers update flags from previously read snapshot in [services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py#L197), [services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py#L193), [services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py#L275)
- Evidence: repository update is plain overwrite in [services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py](services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py#L168)
- Risk: one consumer can overwrite flags set by another under concurrency.
- Status: confirmed race susceptibility.

3. Combined test collection in monorepo can fail due duplicate module basenames.
- Evidence: cross-service pytest invocation failed with import mismatch on test_repositories.py from two services.
- Risk: unstable umbrella QA runs and CI fragility for combined invocations.
- Status: confirmed via execution.

### Medium

4. Earnings trend malformed date fallback uses ingested_at, reducing temporal fidelity.
- Evidence: fallback in [services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py#L337)
- Risk: records may be bucketed under ingest time instead of source period.
- Status: confirmed behavior.

5. Quote repository maps null numeric fields to zero values.
- Evidence: mapping defaults in [services/market-data/src/market_data/infrastructure/db/repositories/quote_repo.py](services/market-data/src/market_data/infrastructure/db/repositories/quote_repo.py#L28)
- Risk: inability to distinguish missing data from legitimate zero values.
- Status: confirmed behavior.

6. Consumer unit tests pass with runtime warnings about un-awaited AsyncMock usage.
- Evidence: warnings surfaced in market-data unit run, involving collect_event call sites in [services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/ohlcv_consumer.py#L188), [services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/quotes_consumer.py#L184), [services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py#L266)
- Risk: false confidence from tests with mock contract mismatch.
- Status: confirmed from execution output.

7. Consumer payload assumptions for fundamentals sections are hardcoded and weakly validated.
- Evidence: static section map in [services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py](services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py#L34)
- Risk: silent skips if upstream key names drift.
- Status: suspected operational risk.

### Low

8. Constraint naming in fundamentals upsert is dynamically constructed from table name.
- Evidence: dynamic constraint string in [services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_repo.py](services/market-data/src/market_data/infrastructure/db/repositories/fundamentals_repo.py#L50)
- Risk: migration rename can break at runtime if convention changes.
- Status: low-risk maintainability concern.

## Portfolio Findings

### High

1. Instrument consumer generates a new ID for every sync event.
- Evidence: new ID assignment in [services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py](services/portfolio/src/portfolio/infrastructure/messaging/consumers/instrument_consumer.py#L52)
- Evidence: repository conflict target is symbol plus exchange in [services/portfolio/src/portfolio/infrastructure/db/repositories/instrument.py](services/portfolio/src/portfolio/infrastructure/db/repositories/instrument.py#L73)
- Risk: unstable instrument identity semantics and possible orphan references.
- Status: confirmed.

2. Transaction idempotency path can fail to return prior transaction deterministically.
- Evidence: idempotency check plus proxy lookup in [services/portfolio/src/portfolio/application/use_cases/record_transaction.py](services/portfolio/src/portfolio/application/use_cases/record_transaction.py#L65)
- Evidence: external_ref assignment merges two concepts in [services/portfolio/src/portfolio/application/use_cases/record_transaction.py](services/portfolio/src/portfolio/application/use_cases/record_transaction.py#L129)
- Evidence: idempotency record write at end in [services/portfolio/src/portfolio/application/use_cases/record_transaction.py](services/portfolio/src/portfolio/application/use_cases/record_transaction.py#L203)
- Risk: retries may see duplicate flow or constraint-driven failures instead of strict idempotent return.
- Status: confirmed logic risk.

3. Watchlist delete semantics are inconsistent between use case and repository API.
- Evidence: use case soft-deletes status to deleted in [services/portfolio/src/portfolio/application/use_cases/watchlist.py](services/portfolio/src/portfolio/application/use_cases/watchlist.py#L152)
- Evidence: repository delete physically removes row in [services/portfolio/src/portfolio/infrastructure/db/repositories/watchlist.py](services/portfolio/src/portfolio/infrastructure/db/repositories/watchlist.py#L70)
- Risk: future callers using repository delete may bypass intended lifecycle semantics.
- Status: confirmed inconsistency.

### Medium

4. Watchlist creation uniqueness check is application-level and race-prone.
- Evidence: pre-check in [services/portfolio/src/portfolio/application/use_cases/watchlist.py](services/portfolio/src/portfolio/application/use_cases/watchlist.py#L91)
- Risk: concurrent requests can both pass pre-check before persistence conflict.
- Status: confirmed race susceptibility.

5. Watchlist member add path lacks request idempotency key and can return conflict after partial side effects.
- Evidence: duplicate check plus save path in [services/portfolio/src/portfolio/application/use_cases/watchlist.py](services/portfolio/src/portfolio/application/use_cases/watchlist.py#L188)
- Risk: retried requests after partial failure may not be safely repeatable.
- Status: suspected behavioral gap.

6. Alert preferences default materialization creates fresh IDs for non-persisted defaults each call.
- Evidence: synthetic IDs in [services/portfolio/src/portfolio/application/use_cases/alert_preferences.py](services/portfolio/src/portfolio/application/use_cases/alert_preferences.py#L51)
- Risk: unstable object identity in clients relying on IDs for later updates.
- Status: confirmed behavior.

7. Input precision guards for transactional decimal fields rely mainly on DB constraints.
- Evidence: positive-only checks in [services/portfolio/src/portfolio/api/schemas.py](services/portfolio/src/portfolio/api/schemas.py#L78)
- Risk: overflow scale or precision errors may surface as persistence exceptions.
- Status: suspected validation gap.

### Low

8. Basic email format is not strongly validated at request schema level.
- Evidence: plain email string in [services/portfolio/src/portfolio/api/schemas.py](services/portfolio/src/portfolio/api/schemas.py#L43)
- Risk: malformed values accepted until later layers.
- Status: low-severity validation gap.

## Prioritized Remediation Suggestions

1. Fix market-data content-hash dedupe key consistency by storing and querying comparable event_type values.
2. Complete market-ingestion policy matching filters for exchange, timeframe, and variant.
3. Rework market-ingestion backfill completion criteria to depend on actual enqueue or completion progress rather than early flag flip.
4. Harmonize portfolio instrument sync identity semantics with repository conflict strategy.
5. Harden transaction idempotency in portfolio with atomic persistence-backed retrieval semantics.
6. Address market-data test warning set by aligning mocks with sync method contracts and enabling warning-as-error for relevant categories.
