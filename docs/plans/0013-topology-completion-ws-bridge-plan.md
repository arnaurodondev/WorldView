# PLAN-0013 — Process Topology Completion + Alert WebSocket Cross-Process Bridge

**Status**: in-progress
**Created**: 2026-04-01
**Updated**: 2026-04-01
**Author**: /plan skill
**Scope**: S3 market-data lifespan cleanup (R22 compliance); entrypoint unit tests for S3/S5/S6/S7/S10; Alert (S10) WebSocket cross-process fan-out via Valkey pub/sub.

---

## Background

PLAN-0011 extracted all Kafka consumers and outbox dispatchers into standalone OS-level processes (R22). However, three open items remain:

| Finding | Severity | Status | This Plan |
|---------|----------|--------|-----------|
| S3 lifespan still starts consumers/dispatcher as background tasks | TOPO-LIFESPAN | Open | Wave A-1 |
| No `test_entrypoints.py` for S3/S5/S6/S7/S10 new entry points | F-QA-002 | Open | Waves B-1…B-3 |
| `intelligence_consumer_main.py` uses an empty in-process `ConnectionManager`; WebSocket push is dead | F-006 | Open | Waves C-1…C-2 |

---

## Open Questions (resolved in this plan)

### Q1 — WebSocket bridge architecture
**Decision**: Use Valkey pub/sub, one channel per user (`alert:{user_id}`).
- At-most-once semantics acceptable — durable delivery already guaranteed by Kafka outbox.
- Consumers publish to Valkey; the FastAPI WebSocket route handler subscribes per-connection (no background task, no R22 violation).
- The `ConnectionManager` in-process registry is retained for the API process; replaced with `INotificationPublisher` port in the standalone consumer.

### Q2 — R22 compliance for WebSocket handlers
**Decision**: The per-connection WebSocket route handler is an async coroutine driven by an active user connection — not a background task. It is not subject to R22 (which targets Kafka consumers and outbox dispatchers). No TOPOLOGY_BASELINE entry required.

### Q3 — Offline delivery
**Decision**: Best-effort. If the user is not connected when an alert fires, the WebSocket push is silently dropped. On reconnect, the client fetches `/api/v1/alerts` (HTTP GET) to catch up. No change to the existing `alert.delivered.v1` Kafka event.

### Q4 — Valkey pub/sub in tests
**Decision**: Use `fakeredis.aioredis.FakeRedis` (already in `libs/messaging` dev deps) for unit tests. Integration tests with real Valkey use the test docker-compose stack.

---

## Dependency Graph

```
Wave A-1 (market-data lifespan cleanup)
     │
     └─→ Wave B-1 (S3 + S5 entrypoint tests)
               │
               └─→ Wave B-2 (S6 + S7 entrypoint tests)
                         │
                         └─→ Wave B-3 (S10 alert entrypoint tests)

Wave C-1 (INotificationPublisher port + ValkeyNotificationPublisher)
     │
     └─→ Wave C-2 (WebSocket route update + integration)
```

A and C can run in parallel. B depends on A (market-data tests verify cleaned-up app.py).

---

## Sub-plan A — Market-Data (S3) Lifespan Cleanup

**Scope**: `services/market-data/`, `tests/architecture/test_process_topology.py`
**Goal**: Remove 4 `asyncio.create_task()` calls from `app.py` lifespan and clear `TOPOLOGY_BASELINE`.

### Wave A-1: Remove Background Tasks from Market-Data Lifespan ✅

**Goal**: Delete consumer + dispatcher startup from `app.py`; the standalone `*_consumer_main.py` and `dispatcher_main.py` processes (already in compose) own those responsibilities.
**Depends on**: none
**Estimated effort**: 30–45 min
**Architecture layer**: API (lifespan)
**Status**: **DONE** — 2026-04-01 · 345 unit tests pass · 94 architecture tests pass · ruff + mypy clean

#### Tasks

##### T-A-1-01: Strip consumers and dispatcher from `app.py` lifespan

**Type**: impl
**depends_on**: none
**blocks**: [T-A-1-02]
**Target files**:
- `services/market-data/src/market_data/app.py`

**What to build**:
Remove items 8 and 9 from the lifespan function: the `create_dispatcher()` call, all three consumer instantiations (`OHLCVConsumer`, `QuotesConsumer`, `FundamentalsConsumer`), the four `asyncio.create_task()` calls, and the shutdown loop that calls `consumer.stop()` / `task.cancel()`. Update the readyz endpoint to remove the now-stale `"kafka": "ok"` note. Remove the `asyncio` import if it becomes unused. Remove unused `ConsumerConfig` import.

**What to keep**: DB engines, Valkey client, object storage, quote cache, UoW factory (`app.state.*`). These are still needed by the API request handlers.

**Acceptance criteria**:
- [x] `app.py` has no `asyncio.create_task` call
- [x] `app.py` has no imports of `FundamentalsConsumer`, `OHLCVConsumer`, `QuotesConsumer`, `ConsumerConfig`, `create_dispatcher`
- [x] `ruff check` passes (no unused imports)
- [x] `mypy` passes on `services/market-data/src`

---

##### T-A-1-02: Clear `TOPOLOGY_BASELINE` entry for market-data

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `tests/architecture/test_process_topology.py`

**What to build**:
Remove the `("market-data", "TOPO-LIFESPAN")` entry from `TOPOLOGY_BASELINE`. The entry was a temporary baseline for PLAN-0011; now that app.py is clean, no baseline is needed.
The dict should become empty: `TOPOLOGY_BASELINE: dict[tuple[str, str], str] = {}`.

**Acceptance criteria**:
- [x] `TOPOLOGY_BASELINE` is empty
- [x] `python -m pytest tests/architecture -v` passes with 0 warnings
- [x] Architecture test output shows no TOPOLOGY baseline messages

---

##### T-A-1-03: Update market-data unit tests (lifespan tests)

**Type**: test
**depends_on**: [T-A-1-01]
**blocks**: none
**Target files**:
- `services/market-data/tests/unit/test_app_lifespan.py` (if it exists)

**What to build**:
If `test_app_lifespan.py` exists, update any tests that assert on the presence of consumer tasks or dispatcher tasks in the lifespan. Remove assertions that check `ohlcv_task`, `quotes_task`, etc. The lifespan should now only be tested for DB/Valkey/storage initialisation. If no such test file exists, create a minimal one that verifies the lifespan starts and stops cleanly.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_lifespan_starts_cleanly` | App lifespan initialises DB + Valkey + storage without error | unit |
| `test_lifespan_does_not_start_consumers` | `asyncio.create_task` is never called during lifespan | unit |

**Acceptance criteria**:
- [x] At least 2 unit tests covering the cleaned-up lifespan
- [x] Tests pass

#### Pre-read
- `services/market-data/src/market_data/app.py`
- `tests/architecture/test_process_topology.py`
- `services/market-data/tests/unit/test_app_lifespan.py` (if exists)

#### Validation Gate
- [x] `ruff check services/market-data/src/` passes
- [x] `mypy services/market-data/src/ --config-file services/market-data/mypy.ini` passes
- [x] `python -m pytest services/market-data/tests/ -m unit -v --tb=short` passes
- [x] `python -m pytest tests/architecture -v` passes with 0 warnings

---

## Sub-plan B — Entrypoint Unit Tests

**Scope**: New test files in S3/S5/S6/S7/S10
**Reference pattern**: `services/market-ingestion/tests/test_entrypoints.py` (≥10 test functions per consumer/dispatcher)

Each test file covers: stop-immediately-when-stop-called, run-one-iteration-then-stop, fatal-error-exits, cleanup-resources-on-stop (engine.dispose / valkey.close called).

### Wave B-1: Entrypoint Tests — S3 market-data + S5 content-store ✅

**Goal**: Add `test_entrypoints.py` for market-data (3 consumers + dispatcher) and content-store (1 consumer + dispatcher).
**Depends on**: Wave A-1
**Estimated effort**: 45–60 min
**Architecture layer**: test
**Status**: **DONE** — 2026-04-01 · 10 market-data + 6 content-store unit tests pass · ruff + format clean

#### Tasks

##### T-B-1-01: `test_entrypoints.py` for market-data

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/market-data/tests/unit/test_entrypoints.py` (new)

**What to build**:
Unit tests for the three consumer entry points (`ohlcv_consumer_main`, `quotes_consumer_main`, `fundamentals_consumer_main`) and the dispatcher entry point (`dispatcher_main`). Use `unittest.mock.patch` to isolate all infrastructure. Minimum 10 test functions.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ohlcv_consumer_main_stop_before_run` | `stop_event` set before `asyncio.run`; consumer.run() is never called | unit |
| `test_ohlcv_consumer_main_graceful_stop` | SIGTERM sets stop_event; wait_for(task, 30) is awaited | unit |
| `test_ohlcv_consumer_main_timeout_cancels` | If task doesn't stop in 30s, cancel() is called | unit |
| `test_quotes_consumer_main_stop_before_run` | Same as above for quotes | unit |
| `test_quotes_consumer_main_graceful_stop` | Graceful stop + valkey.close() called | unit |
| `test_fundamentals_consumer_main_stop_before_run` | Graceful path for fundamentals | unit |
| `test_fundamentals_consumer_main_engine_disposed` | `write_engine.dispose()` called on exit | unit |
| `test_dispatcher_main_stop_delegates_to_dispatcher` | dispatcher.stop() called on signal | unit |
| `test_dispatcher_main_run_delegates_to_dispatcher` | dispatcher.run() is awaited | unit |
| `test_dispatcher_main_cleanup_on_exit` | engine.dispose() and valkey.close() called | unit |

Edge cases: KeyboardInterrupt during run; `_build_factories()` raises.

**Acceptance criteria**:
- [x] ≥10 test functions
- [x] All pass with `pytest -m unit`
- [x] No infrastructure connections in tests

---

##### T-B-1-02: `test_entrypoints.py` for content-store

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/content-store/tests/unit/test_entrypoints.py` (new)

**What to build**:
Unit tests for `article_consumer_main` and `dispatcher_main`. Pattern matches T-B-1-01.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_article_consumer_main_stop_before_run` | stop_event pre-set; consumer never starts | unit |
| `test_article_consumer_main_graceful_stop` | wait_for(30s) used; valkey.close + engine.dispose called | unit |
| `test_article_consumer_main_timeout_cancels` | Task force-cancelled after timeout | unit |
| `test_article_consumer_main_lsh_client_used` | LSHConfig built from settings; ValkeyLSHClient constructed | unit |
| `test_dispatcher_main_stop_delegates` | dispatcher.stop() delegated | unit |
| `test_dispatcher_main_cleanup` | engine.dispose() + valkey.close() on exit | unit |

**Acceptance criteria**:
- [x] ≥6 test functions
- [x] All pass with `pytest -m unit`

#### Validation Gate (B-1)
- [x] `python -m pytest services/market-data/tests/ -m unit -v` passes (new tests included)
- [x] `python -m pytest services/content-store/tests/ -m unit -v` passes
- [x] `ruff check` passes on new test files
- [x] `mypy` passes on new test files

---

### Wave B-2: Entrypoint Tests — S6 nlp-pipeline + S7 knowledge-graph ✅

**Goal**: Add `test_entrypoints.py` for nlp-pipeline (2 consumers + dispatcher) and knowledge-graph (4 consumers + dispatcher + scheduler).
**Depends on**: Wave B-1 (patterns established)
**Estimated effort**: 60–90 min
**Status**: **DONE** — 2026-04-01 · 7 nlp-pipeline + 8 knowledge-graph unit tests pass · ruff + format clean

#### Tasks

##### T-B-2-01: `test_entrypoints.py` for nlp-pipeline

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/nlp-pipeline/tests/unit/test_entrypoints.py` (new)

**What to build**:
Unit tests for `article_consumer_main`, `watchlist_consumer_main`, and `dispatcher_main`. Note: `article_consumer_main` manages TWO engines (`nlp_engine`, `intel_engine`) — tests must verify both are disposed on exit.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_article_consumer_main_two_engines_disposed` | Both `nlp_engine.dispose()` and `intel_engine.dispose()` called | unit |
| `test_article_consumer_main_graceful_stop` | wait_for(30s) on stop signal | unit |
| `test_article_consumer_main_stop_pre_set` | Consumer never started if stop pre-set | unit |
| `test_watchlist_consumer_main_graceful_stop` | valkey.close() called; stop via wait_for | unit |
| `test_watchlist_consumer_main_stop_pre_set` | Consumer never started | unit |
| `test_dispatcher_main_cleanup` | engine.dispose() on exit | unit |
| `test_dispatcher_main_stop` | dispatcher.stop() delegated | unit |

**Acceptance criteria**:
- [x] ≥7 test functions
- [x] Both-engines-disposed test explicitly verifies two `dispose()` calls

---

##### T-B-2-02: `test_entrypoints.py` for knowledge-graph

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/knowledge-graph/tests/unit/test_entrypoints.py` (new)

**What to build**:
Unit tests for 4 consumer entry points (`enriched_consumer_main`, `entity_consumer_main`, `fundamentals_consumer_main`, `instrument_consumer_main`), `dispatcher_main`, and `scheduler_main` (if it exists as a standalone process).

Note for `enriched_consumer_main`: it creates an `OllamaEmbeddingAdapter` using `settings.ollama_base_url` — tests must mock this to prevent real HTTP calls.

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_enriched_consumer_uses_ollama_base_url` | `OllamaEmbeddingAdapter(base_url=settings.ollama_base_url, ...)` called | unit |
| `test_enriched_consumer_graceful_stop` | wait_for + valkey.close + engine.dispose | unit |
| `test_entity_consumer_graceful_stop` | same | unit |
| `test_fundamentals_consumer_group_id_from_settings` | group_id = `f"{settings.kafka_consumer_group}-fundamentals"` | unit |
| `test_instrument_consumer_group_id_from_settings` | group_id = `f"{settings.kafka_consumer_group}-instrument"` | unit |
| `test_dispatcher_main_cleanup` | engine.dispose + valkey.close | unit |
| `test_any_consumer_stop_pre_set` | consumer never started | unit |

**Acceptance criteria**:
- [x] ≥7 test functions
- [x] Ollama mock test explicitly verifies `settings.ollama_base_url` is used (guards against BP-085 regression)

#### Validation Gate (B-2)
- [x] `python -m pytest services/nlp-pipeline/tests/ -m unit -v` passes
- [x] `python -m pytest services/knowledge-graph/tests/ -m unit -v` passes

---

### Wave B-3: Entrypoint Tests — S10 alert

**Goal**: Add `test_entrypoints.py` for alert (2 consumers + dispatcher).
**Depends on**: Wave B-2
**Estimated effort**: 45–60 min

#### Tasks

##### T-B-3-01: `test_entrypoints.py` for alert

**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/alert/tests/unit/test_entrypoints.py` (new)

**What to build**:
Unit tests for `intelligence_consumer_main` and `watchlist_consumer_main` and `dispatcher_main`.
Important: after Wave C-2 lands, `intelligence_consumer_main` will use a `ValkeyNotificationPublisher` instead of `ConnectionManager`. These tests must be written to work with the final architecture (mock the publisher, not the manager). **If Wave C has not yet been implemented, skip the publisher-related assertions and add a `# TODO: add publisher mock after Wave C-2` comment.**

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_intelligence_consumer_graceful_stop` | wait_for(30s) + s1_client.close + valkey.close + engine.dispose | unit |
| `test_intelligence_consumer_stop_pre_set` | Consumer never started | unit |
| `test_intelligence_consumer_cleanup_order` | All resources closed in finally | unit |
| `test_watchlist_consumer_graceful_stop` | wait_for(30s) + valkey.close | unit |
| `test_watchlist_consumer_stop_pre_set` | Consumer never started | unit |
| `test_dispatcher_main_cleanup` | engine.dispose called | unit |
| `test_dispatcher_main_stop` | dispatcher.stop() delegated | unit |

**Acceptance criteria**:
- [ ] ≥7 test functions
- [ ] `python -m pytest services/alert/tests/ -m unit -v` passes

---

## Sub-plan C — Alert WebSocket Cross-Process Bridge

**Scope**: `services/alert/`
**Goal**: Fix F-006 — make WebSocket push work when the intelligence consumer runs as a standalone process. Replace the in-memory `ConnectionManager` dependency in `AlertFanoutUseCase` with an abstract `INotificationPublisher` port, backed by a `ValkeyNotificationPublisher` in the consumer process and a Valkey-subscribed WebSocket route in the FastAPI app.

### Architecture

```
intelligence_consumer_main.py (standalone process)
    │
    │  AlertFanoutUseCase.execute(event)
    │    └─→ INotificationPublisher.send_to_user(user_id, payload)
    │          └─→ ValkeyNotificationPublisher.send_to_user(user_id, payload)
    │                └─→ valkey.publish("alert:{user_id}", json_payload)
    │
    ▼
Valkey pub/sub channel: "alert:{user_id}"
    │
    ▼
alert API process (FastAPI)
    └─→ GET /api/v1/ws (WebSocket endpoint)
          └─→ per-connection Valkey subscriber loop
                └─→ websocket.send_text(payload)
```

### Wave C-1: `INotificationPublisher` Port + `ValkeyNotificationPublisher`

**Goal**: Add the application port and infrastructure adapter. Update `AlertFanoutUseCase` to depend on the port. Update `intelligence_consumer_main.py` to use `ValkeyNotificationPublisher`.
**Depends on**: none (can run in parallel with A and B)
**Estimated effort**: 45–60 min
**Architecture layer**: application (port) + infrastructure (adapter)

#### Tasks

##### T-C-1-01: Add `INotificationPublisher` port

**Type**: impl
**depends_on**: none
**blocks**: [T-C-1-02, T-C-1-03]
**Target files**:
- `services/alert/src/alert/application/ports/notification.py` (new)

**What to build**:
Define an abstract `INotificationPublisher` protocol/ABC with a single method:

```python
class INotificationPublisher(Protocol):
    async def send_to_user(self, user_id: UUID, payload: dict[str, Any]) -> None:
        """Publish a real-time notification to a connected user.

        Best-effort: no retry, no durability. Silent no-op if user is not connected.
        """
        ...
```

Use `typing.Protocol` (structural subtyping) so both `ValkeyNotificationPublisher` and the existing `ConnectionManager` satisfy the interface without explicit inheritance.

**Acceptance criteria**:
- [ ] Protocol defined using `typing.Protocol` with `runtime_checkable` decorator
- [ ] `mypy` passes (no protocol violations)

---

##### T-C-1-02: Update `AlertFanoutUseCase` to use the port

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-1-03, T-C-1-04]
**Target files**:
- `services/alert/src/alert/application/use_cases/alert_fanout.py`

**What to build**:
Replace the `ConnectionManager` type annotation on `connection_manager` parameter with `INotificationPublisher`. The `ConnectionManager` class already satisfies the protocol (it has `send_to_user(user_id, payload)`), so no changes are needed to `ConnectionManager` itself or to `app.py` (which still passes `ConnectionManager`).

Changes:
1. Import `INotificationPublisher` from the new port module
2. Change `connection_manager: ConnectionManager` to `connection_manager: INotificationPublisher`
3. Update `self._ws` annotation to `INotificationPublisher`

**Acceptance criteria**:
- [ ] `AlertFanoutUseCase.__init__` signature accepts `INotificationPublisher`
- [ ] `ConnectionManager` still satisfies the protocol (existing tests pass unmodified)
- [ ] `mypy` passes

---

##### T-C-1-03: Add `ValkeyNotificationPublisher`

**Type**: impl
**depends_on**: [T-C-1-01]
**blocks**: [T-C-1-04]
**Target files**:
- `services/alert/src/alert/infrastructure/notification/valkey_publisher.py` (new)

**What to build**:
Implement `ValkeyNotificationPublisher` that satisfies `INotificationPublisher`:

```python
class ValkeyNotificationPublisher:
    """Publishes real-time alert notifications via Valkey pub/sub.

    Each user has a dedicated channel: ``alert:{user_id}``.
    Fire-and-forget — no retry, no durability guarantee.
    """

    def __init__(self, valkey_client: ValkeyClient) -> None:
        self._valkey = valkey_client

    async def send_to_user(self, user_id: UUID, payload: dict[str, Any]) -> None:
        channel = f"alert:{user_id}"
        try:
            await self._valkey.publish(channel, json.dumps(payload, default=str))
        except Exception:
            # Best-effort: log and continue; durability handled by Kafka outbox
            logger.warning("notification_publish_failed", user_id=str(user_id))
```

**Tests to write** (inline with impl):

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_publish_sends_to_correct_channel` | `valkey.publish("alert:{user_id}", ...)` called | unit |
| `test_publish_serialises_payload` | payload is JSON-serialised | unit |
| `test_publish_swallows_valkey_error` | no exception raised if valkey.publish fails | unit |

**Acceptance criteria**:
- [ ] 3 unit tests pass
- [ ] Channel format: `alert:{user_id}` (UUID string)
- [ ] Payload: `json.dumps(payload, default=str)` for UUID/datetime safety

---

##### T-C-1-04: Update `intelligence_consumer_main.py` to use `ValkeyNotificationPublisher`

**Type**: impl
**depends_on**: [T-C-1-02, T-C-1-03]
**blocks**: none
**Target files**:
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer_main.py`

**What to build**:
Replace the `ConnectionManager()` instantiation with `ValkeyNotificationPublisher(valkey)`. The comment about in-memory limitation becomes obsolete.

```python
# Before:
ws_manager = ConnectionManager()
fanout = AlertFanoutUseCase(..., connection_manager=ws_manager, ...)

# After:
notification_publisher = ValkeyNotificationPublisher(valkey)
fanout = AlertFanoutUseCase(..., connection_manager=notification_publisher, ...)
```

Remove the now-unused `from alert.infrastructure.websocket.manager import ConnectionManager` import.

**Acceptance criteria**:
- [ ] `ConnectionManager` no longer imported in `intelligence_consumer_main.py`
- [ ] `ValkeyNotificationPublisher` used instead
- [ ] `ruff check` passes (no unused imports)
- [ ] Existing alert unit tests still pass (they mock `AlertFanoutUseCase`)

#### Pre-read
- `services/alert/src/alert/application/use_cases/alert_fanout.py`
- `services/alert/src/alert/infrastructure/websocket/manager.py`
- `services/alert/src/alert/infrastructure/messaging/consumers/intelligence_consumer_main.py`
- `libs/messaging/src/messaging/valkey/client.py`

#### Validation Gate (C-1)
- [ ] `ruff check services/alert/src/` passes
- [ ] `mypy services/alert/src/ --config-file services/alert/mypy.ini` passes
- [ ] `python -m pytest services/alert/tests/ -m unit -v` passes (existing + new)

---

### Wave C-2: WebSocket Route — Valkey Subscriber + Integration

**Goal**: Update the WebSocket route in the FastAPI app to subscribe to the user's Valkey channel and forward messages to the connected client.
**Depends on**: Wave C-1
**Estimated effort**: 60–90 min
**Architecture layer**: API + integration test

#### Tasks

##### T-C-2-01: Update WebSocket route to subscribe to Valkey

**Type**: impl
**depends_on**: none (within wave)
**blocks**: [T-C-2-02]
**Target files**:
- `services/alert/src/alert/api/routes.py` (WebSocket endpoint section)
- `services/alert/src/alert/app.py` (ensure `valkey_client` is on `app.state`)

**What to build**:
Update the `/api/v1/ws` WebSocket endpoint to:
1. Register the connection in `ConnectionManager` (keeps existing in-process fan-out for API-process alerts)
2. Subscribe to the user's Valkey channel `alert:{user_id}`
3. Forward Valkey messages to the WebSocket client
4. Unsubscribe and disconnect on client disconnect

```python
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    # ... auth, user_id extraction as before ...
) -> None:
    manager: ConnectionManager = websocket.app.state.ws_manager
    valkey: ValkeyClient = websocket.app.state.valkey_client
    channel = f"alert:{user_id}"

    await manager.connect(user_id, websocket)
    try:
        async with valkey.subscribe(channel) as subscriber:
            async for message in subscriber:
                if message["type"] == "message":
                    try:
                        await websocket.send_text(message["data"])
                    except WebSocketDisconnect:
                        break
    finally:
        manager.disconnect(user_id)
```

Note: `ValkeyClient.subscribe()` may need a new async context manager method if one doesn't exist. Check `libs/messaging/src/messaging/valkey/client.py` first; add if needed.

**Acceptance criteria**:
- [ ] WebSocket handler subscribes to `alert:{user_id}` Valkey channel
- [ ] Messages forwarded to client as-is (JSON string)
- [ ] Disconnect triggers cleanup (unsubscribe + `manager.disconnect`)
- [ ] `ruff check` and `mypy` pass

---

##### T-C-2-02: Add `ValkeyClient.subscribe()` async context manager (if missing)

**Type**: impl
**depends_on**: none
**blocks**: [T-C-2-01]
**Target files**:
- `libs/messaging/src/messaging/valkey/client.py` (if subscribe method is missing)

**What to build**:
If `ValkeyClient` does not have a pub/sub subscription method, add:

```python
@asynccontextmanager
async def subscribe(self, *channels: str) -> AsyncIterator[aioredis.client.PubSub]:
    """Async context manager that subscribes to the given channels and yields
    a ``PubSub`` object. Unsubscribes and closes on exit."""
    pubsub = self._redis.pubsub()
    await pubsub.subscribe(*channels)
    try:
        yield pubsub
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()
```

Also add a `publish(channel: str, message: str) -> int` method if missing (needed by `ValkeyNotificationPublisher`).

**Acceptance criteria**:
- [ ] `ValkeyClient.subscribe()` async context manager exists
- [ ] `ValkeyClient.publish()` method exists
- [ ] Tests in `libs/messaging/tests/unit/test_valkey_client.py` updated to cover new methods

---

##### T-C-2-03: Integration test — Valkey pub/sub → WebSocket round-trip

**Type**: test
**depends_on**: [T-C-2-01]
**blocks**: none
**Target files**:
- `services/alert/tests/integration/test_ws_valkey_bridge.py` (new)

**What to build**:
Integration test using `fakeredis.aioredis.FakeRedis` (no real Valkey) and FastAPI's `TestClient`/`WebSocketTestClient` to verify end-to-end:
1. Client connects to `/api/v1/ws`
2. A separate coroutine publishes to `alert:{user_id}` via Valkey
3. The connected WebSocket client receives the message

**Tests to write**:

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_ws_receives_published_notification` | Publish → WebSocket client receives message | integration |
| `test_ws_disconnect_cleans_up_subscription` | After disconnect, no further messages sent | integration |
| `test_ws_swallows_valkey_down` | If Valkey errors during subscribe, client is disconnected cleanly | integration |

**Acceptance criteria**:
- [ ] 3 integration tests pass with `pytest -m integration`
- [ ] Tests use `fakeredis` — no real Valkey required
- [ ] `pytest.mark.integration` marker applied

#### Pre-read
- `services/alert/src/alert/api/routes.py`
- `services/alert/src/alert/app.py`
- `libs/messaging/src/messaging/valkey/client.py`
- `libs/messaging/tests/unit/test_valkey_client.py`

#### Validation Gate (C-2)
- [ ] `ruff check services/alert/src/ libs/messaging/src/` passes
- [ ] `mypy services/alert/src/ --config-file services/alert/mypy.ini` passes
- [ ] `python -m pytest services/alert/tests/ -m unit -v` passes
- [ ] `python -m pytest services/alert/tests/ -m integration -v` passes (fakeredis-backed)
- [ ] `python -m pytest tests/architecture -v` — 0 warnings
- [ ] Existing `alert` integration tests still pass

---

## Cross-Cutting Concerns

| Concern | Action |
|---------|--------|
| No new Kafka topics | None |
| No new Avro schemas | None |
| No DB migrations | None |
| New `INotificationPublisher` port | Adds `services/alert/src/alert/application/ports/` directory |
| `libs/messaging` change (if needed) | `ValkeyClient.subscribe()` / `.publish()` — run `libs/messaging` unit tests |
| Docker Compose | No changes needed (compose already complete after PLAN-0011 follow-up) |
| Env vars | No new env vars; channel key `alert:{user_id}` is derived at runtime |
| Docs | Update `docs/services/alert-service.md` to describe cross-process WebSocket architecture |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `ValkeyClient` lacks `publish()`/`subscribe()` | Medium | High | Check before Wave C-1; add if missing |
| `fakeredis` pub/sub API differs from real redis | Low | Medium | Use `fakeredis[aioredis]` which mirrors `redis.asyncio` API |
| WebSocket test client doesn't support async subscribe | Medium | Medium | Use `anyio` + `httpx.AsyncClient` for WebSocket testing |
| Market-data lifespan tests break after consumer removal | Low | Low | Update assertions in existing `test_app_lifespan.py` |

**Critical path**: A-1 → B-1 → B-2 → B-3 (linear, all must pass tests)
**Parallelisable**: C-1 runs independently of A and B; C-2 runs after C-1.

---

## Wave Summary

| Wave | Goal | Effort | Blocks |
|------|------|--------|--------|
| A-1 | Market-data lifespan cleanup | 30-45 min | B-1 |
| B-1 | Entrypoint tests S3+S5 | 45-60 min | B-2 |
| B-2 | Entrypoint tests S6+S7 | 60-90 min | B-3 |
| B-3 | Entrypoint tests S10 | 45-60 min | — |
| C-1 | INotificationPublisher + ValkeyNotificationPublisher | 45-60 min | C-2 |
| C-2 | WebSocket Valkey subscriber + integration test | 60-90 min | — |

**Total estimated effort**: 5–7 hours
**Total tasks**: 15
**Total waves**: 6
