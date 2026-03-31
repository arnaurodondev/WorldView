# Test Execution Report

Generated at: 2026-03-31T15:10:56Z
Run ID: 20260331T145855Z
Run artifacts: docs/testing/test-runs/20260331T145855Z
Run duration (sec): 721

## Environment
- git branch: feat/content-ingestion-wave-a1
- git sha: d84e79ff6409c536164be235f53822d0d7eefb3e
- python: Python 3.12.7
- docker: Docker version 29.1.3, build f52814d
- docker compose: Docker Compose version v5.0.0-desktop.1
- retain logs: on-failure
- integration mode: sequential

## Summary
- Test suites passed: 30
- Test suites failed: 4
- Test suites skipped: 15
- Total collected tests: 2744
- Total failed tests: 25
- Note: suite counts and test counts are different units

## Aggregated Metrics
- Collected in passed/failed suites: 2744
- Collected in skipped suites: 0
- Failed tests extracted from JUnit: 25

## Metrics By Layer
| Layer | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| architecture | 1/0/0 | 35 | 0 | 3 |
| contract | 3/0/8 | 20 | 0 | 2 |
| e2e | 6/3/3 | 269 | 24 | 170 |
| infra | 2/0/0 | 0 | 0 | 100 |
| integration | 7/1/3 | 207 | 1 | 36 |
| libs | 1/0/0 | 0 | 0 | 7 |
| unit | 10/0/1 | 2213 | 0 | 22 |

## Metrics By Service
| Service | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| alert | 2/2/0 | 168 | 2 | 10 |
| api-gateway | 1/0/3 | 12 | 0 | 0 |
| architecture | 1/0/0 | 35 | 0 | 3 |
| compose | 2/0/0 | 0 | 0 | 100 |
| content-ingestion | 3/0/1 | 465 | 0 | 5 |
| content-store | 3/0/1 | 275 | 0 | 4 |
| cross-service | 1/0/0 | 97 | 21 | 124 |
| intelligence-migrations | 0/0/4 | 0 | 0 | 1 |
| knowledge-graph | 2/1/1 | 219 | 1 | 8 |
| libs | 1/0/0 | 0 | 0 | 7 |
| market-data | 3/0/1 | 429 | 0 | 39 |
| market-ingestion | 3/1/0 | 428 | 1 | 24 |
| nlp-pipeline | 3/0/1 | 255 | 0 | 5 |
| portfolio | 4/0/0 | 359 | 0 | 9 |
| rag-chat | 1/0/3 | 2 | 0 | 1 |

## Failure Hotspots
- cross-service:e2e: 21 failed tests
- alert:e2e: 1 failed tests
- alert:integration: 1 failed tests
- knowledge-graph:e2e: 1 failed tests
- market-ingestion:e2e: 1 failed tests

## Infra Status
- Status: passed
- compose ps: docs/testing/test-runs/20260331T145855Z/infra/compose.ps.txt
- compose config: docs/testing/test-runs/20260331T145855Z/infra/compose.config.yaml
- compose all logs: docs/testing/test-runs/20260331T145855Z/infra/compose.all.log
- service logs dir: docs/testing/test-runs/20260331T145855Z/infra/services
- inspect dir: docs/testing/test-runs/20260331T145855Z/infra/inspect

## Suite Results
- architecture: passed (layer=architecture, type=pytest, collected=35, duration=3s)
- libs: passed (layer=libs, type=script, collected=0, duration=7s) - summarized by scripts/test-libs.sh
- alert:unit: passed (layer=unit, type=pytest, collected=126, duration=1s)
- api-gateway:unit: passed (layer=unit, type=pytest, collected=12, duration=0s)
- content-ingestion:unit: passed (layer=unit, type=pytest, collected=411, duration=3s)
- content-store:unit: passed (layer=unit, type=pytest, collected=241, duration=2s)
- intelligence-migrations:unit: skipped (layer=unit, type=pytest, collected=0, duration=1s, failure_type=no_tests) - no tests collected
- knowledge-graph:unit: passed (layer=unit, type=pytest, collected=177, duration=1s)
- market-data:unit: passed (layer=unit, type=pytest, collected=338, duration=10s)
- market-ingestion:unit: passed (layer=unit, type=pytest, collected=399, duration=1s)
- nlp-pipeline:unit: passed (layer=unit, type=pytest, collected=217, duration=1s)
- portfolio:unit: passed (layer=unit, type=pytest, collected=290, duration=1s)
- rag-chat:unit: passed (layer=unit, type=pytest, collected=2, duration=1s)
- alert:contract: passed (layer=contract, type=pytest, collected=3, duration=1s)
- api-gateway:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-ingestion:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-store:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- intelligence-migrations:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract dir
- knowledge-graph:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-data:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-ingestion:contract: passed (layer=contract, type=pytest, collected=3, duration=0s)
- nlp-pipeline:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- portfolio:contract: passed (layer=contract, type=pytest, collected=14, duration=1s)
- rag-chat:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- compose:up: passed (layer=infra, type=compose_startup, collected=0, duration=98s)
- compose:readiness: passed (layer=infra, type=readiness, collected=0, duration=2s)
- alert:integration: failed (layer=integration, type=pytest, collected=19, duration=5s, failure_type=assertion) - pytest exited with code 1
- alert:e2e: failed (layer=e2e, type=pytest, collected=20, duration=3s, failure_type=assertion) - pytest exited with code 1
- api-gateway:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- api-gateway:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-ingestion:integration: passed (layer=integration, type=pytest, collected=29, duration=1s)
- content-ingestion:e2e: passed (layer=e2e, type=pytest, collected=25, duration=1s)
- content-store:integration: passed (layer=integration, type=pytest, collected=10, duration=1s)
- content-store:e2e: passed (layer=e2e, type=pytest, collected=24, duration=1s)
- intelligence-migrations:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- intelligence-migrations:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- knowledge-graph:integration: passed (layer=integration, type=pytest, collected=22, duration=1s)
- knowledge-graph:e2e: failed (layer=e2e, type=pytest, collected=20, duration=6s, failure_type=assertion) - pytest exited with code 1
- market-data:integration: passed (layer=integration, type=pytest, collected=67, duration=21s)
- market-data:e2e: passed (layer=e2e, type=pytest, collected=24, duration=8s)
- market-ingestion:integration: passed (layer=integration, type=pytest, collected=10, duration=0s)
- market-ingestion:e2e: failed (layer=e2e, type=pytest, collected=16, duration=23s, failure_type=assertion) - pytest exited with code 1
- nlp-pipeline:integration: passed (layer=integration, type=pytest, collected=5, duration=1s)
- nlp-pipeline:e2e: passed (layer=e2e, type=pytest, collected=33, duration=3s)
- portfolio:integration: passed (layer=integration, type=pytest, collected=45, duration=6s)
- portfolio:e2e: passed (layer=e2e, type=pytest, collected=10, duration=1s)
- rag-chat:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- rag-chat:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- cross-service:e2e: passed (layer=e2e, type=pytest, collected=97, duration=124s)

## Failed Tests (Reason + Traceback Excerpt)
### 1. tests.integration.test_s7_s10_pipeline::test_pipeline_api_returns_alert_after_fanout
- suite: alert:integration
- kind: failure
- reason: RuntimeError: Cannot open a client instance more than once.
- log: docs/testing/test-runs/20260331T145855Z/suites/alert_integration.log
```text
integration_app = <fastapi.applications.FastAPI object at 0x113136000>
integration_client = <httpx.AsyncClient object at 0x1131481d0>
db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x113148bf0>
httpserver = <HTTPServer host=localhost port=52213>
    @pytest.mark.integration
    async def test_pipeline_api_returns_alert_after_fanout(
        integration_app: Any,
        integration_client: Any,
        db_session: Any,
        httpserver: Any,
    ) -> None:
        """M7: after fan-out, GET /api/v1/alerts/pending returns the alert for the user."""
        entity_id = str(uuid4())
        user_id = str(uuid4())
        watchlist_id = str(uuid4())
        httpserver.expect_request(
            f"/internal/v1/watchlists/by-entity/{entity_id}",
            method="GET",
        ).respond_with_json(
            {
                "entity_id": entity_id,
                "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
            }
        )
        fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
```

### 2. tests.integration.test_websocket::test_ws_stream_endpoint_connects
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Cannot open a client instance more than once.
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x113163860>
    @pytest.mark.integration
    async def test_ws_stream_endpoint_connects(
        integration_client: Any,
    ) -> None:
        """WebSocket /api/v1/alerts/stream accepts a connection."""
        user_id = str(uuid4())
>       async with integration_client as client:
tests/integration/test_websocket.py:128:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x113163860>
    async def __aenter__(self: U) -> U:
        if self._state != ClientState.UNOPENED:
            msg = {
                ClientState.OPENED: "Cannot open a client instance more than once.",
                ClientState.CLOSED: (
                    "Cannot reopen a client instance, once it has been closed."
                ),
            }[self._state]
>           raise RuntimeError(msg)
E           RuntimeError: Cannot open a client instance more than once.
.venv/lib/python3.12/site-packages/httpx/_client.py:2031: RuntimeError
```

### 3. tests.e2e.test_api_workflows::test_pending_alerts_returns_seeded_alert
- suite: alert:e2e
- kind: failure
- reason: ValueError: 'breakout_signal' is not a valid AlertType
- log: docs/testing/test-runs/20260331T145855Z/suites/alert_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b433cb0>
e2e_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10b4abe00>
    async def test_pending_alerts_returns_seeded_alert(
        e2e_client: AsyncClient,
        e2e_db_session: AsyncSession,
    ) -> None:
        """GET /api/v1/alerts/pending returns seeded pending alert for the correct user."""
        user_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        alert_id = await _seed_alert(e2e_db_session, entity_id=entity_id, alert_type="breakout_signal")
        pending_id = await _seed_pending_alert(e2e_db_session, alert_id, user_id)
>       resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}")
tests/e2e/test_api_workflows.py:160:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b433cb0>
url = '/api/v1/alerts/pending?user_id=485568a6-0a29-49e2-a908-60fbedc3fd76'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
```

### 4. tests.e2e.test_api_workflows::test_pending_alerts_pagination_offset_and_limit
- suite: cross-service:e2e
- kind: failure
- reason: ValueError: 'signal' is not a valid AlertType
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b0cbcb0>
e2e_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10b33ee10>
    async def test_pending_alerts_pagination_offset_and_limit(
        e2e_client: AsyncClient,
        e2e_db_session: AsyncSession,
    ) -> None:
        """Pagination: limit=1 returns only first alert; offset=1 skips it."""
        user_id = uuid.uuid4()
        entity_id1 = uuid.uuid4()
        entity_id2 = uuid.uuid4()
        alert_id1 = await _seed_alert(
            e2e_db_session,
            entity_id=entity_id1,
            dedup_key=f"key:{uuid.uuid4().hex}",
        )
        alert_id2 = await _seed_alert(
            e2e_db_session,
            entity_id=entity_id2,
            dedup_key=f"key:{uuid.uuid4().hex}",
        )
        await _seed_pending_alert(e2e_db_session, alert_id1, user_id)
        await _seed_pending_alert(e2e_db_session, alert_id2, user_id)
>       resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}&limit=1")
tests/e2e/test_api_workflows.py:213:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
```

### 5. tests.e2e.test_api_workflows::test_dlq_pagination
- suite: cross-service:e2e
- kind: failure
- reason: assert 2 == 5
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10bcd6bd0>
e2e_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10bad0b00>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_dlq_pagination(
        e2e_client: AsyncClient,
        e2e_db_session: AsyncSession,
        admin_headers: dict[str, str],
    ) -> None:
        """DLQ list endpoint respects limit/offset pagination."""
        for _ in range(5):
            await e2e_db_session.execute(
                text("""
                    INSERT INTO dead_letter_queue
                        (dlq_id, original_event_id, topic, payload_avro, status, created_at)
                    VALUES (:did, :eid, 'test', E'\\\\x00'::bytea, 'failed', now())
                """),
                {"did": str(uuid.uuid4()), "eid": str(uuid.uuid4())},
            )
        await e2e_db_session.commit()
        resp = await e2e_client.get("/admin/dlq?limit=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 2
>       assert data["total"] == 5
E       assert 2 == 5
```

### 6. tests.e2e.test_api_workflows::test_entity_graph_with_seeded_entity
- suite: knowledge-graph:e2e
- kind: failure
- reason: sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) <class 'asyncpg.exceptions.AmbiguousParameterError'>: could not determine data type of parameter $3
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE (r.subject_entity_id = $1 OR r.object_entity_id = $1)
  AND (r.confidence IS NULL OR r.confidence >= $2)
  AND ($3 IS NULL OR r.semantic_mode = $3)
ORDER BY r.latest_evidence_at DESC
LIMIT $4
]
[parameters: ('a37f0c11-2183-49e3-8fae-fa8e24dfdcac', 0.0, None, 50)]
(Background on this error at: https://sqlalche.me/e/20/f405)
- log: docs/testing/test-runs/20260331T145855Z/suites/knowledge-graph_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x10b1c7b80>
operation = '\nSELECT r.relation_id, r.subject_entity_id, r.object_entity_id,\n       r.canonical_type, r.semantic_mode, r.decay_c...ULL OR r.confidence >= $2)\n  AND ($3 IS NULL OR r.semantic_mode = $3)\nORDER BY r.latest_evidence_at DESC\nLIMIT $4\n'
parameters = ('a37f0c11-2183-49e3-8fae-fa8e24dfdcac', 0.0, None, 50)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
>               prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:458:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10b0ef4c0>>
operation = '\nSELECT r.relation_id, r.subject_entity_id, r.object_entity_id,\n       r.canonical_type, r.semantic_mode, r.decay_c...ULL OR r.confidence >= $2)\n  AND ($3 IS NULL OR r.semantic_mode = $3)\nORDER BY r.latest_evidence_at DESC\nLIMIT $4\n'
invalidate_timestamp = 0
    async def _prepare(self, operation, invalidate_timestamp):
        await self._check_type_cache_invalidation(invalidate_timestamp)
        cache = self._prepared_statement_cache
        if cache is None:
            prepared_stmt = await self._connection.prepare(operation)
            attributes = prepared_stmt.get_attributes()
```

### 7. tests.e2e.test_api_workflows::test_entity_graph_semantic_mode_filter
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.ProgrammingError: (sqlalchemy.dialects.postgresql.asyncpg.ProgrammingError) <class 'asyncpg.exceptions.AmbiguousParameterError'>: could not determine data type of parameter $3
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE (r.subject_entity_id = $1 OR r.object_entity_id = $1)
  AND (r.confidence IS NULL OR r.confidence >= $2)
  AND ($3 IS NULL OR r.semantic_mode = $3)
ORDER BY r.latest_evidence_at DESC
LIMIT $4
]
[parameters: ('27689585-d5c3-461d-8c52-3b50ea5f2c12', 0.0, 'RELATION_STATE', 50)]
(Background on this error at: https://sqlalche.me/e/20/f405)
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x10b72f880>
operation = '\nSELECT r.relation_id, r.subject_entity_id, r.object_entity_id,\n       r.canonical_type, r.semantic_mode, r.decay_c...ULL OR r.confidence >= $2)\n  AND ($3 IS NULL OR r.semantic_mode = $3)\nORDER BY r.latest_evidence_at DESC\nLIMIT $4\n'
parameters = ('27689585-d5c3-461d-8c52-3b50ea5f2c12', 0.0, 'RELATION_STATE', 50)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
>               prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:458:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10b7de7a0>>
operation = '\nSELECT r.relation_id, r.subject_entity_id, r.object_entity_id,\n       r.canonical_type, r.semantic_mode, r.decay_c...ULL OR r.confidence >= $2)\n  AND ($3 IS NULL OR r.semantic_mode = $3)\nORDER BY r.latest_evidence_at DESC\nLIMIT $4\n'
invalidate_timestamp = 0
    async def _prepare(self, operation, invalidate_timestamp):
        await self._check_type_cache_invalidation(invalidate_timestamp)
        cache = self._prepared_statement_cache
        if cache is None:
            prepared_stmt = await self._connection.prepare(operation)
            attributes = prepared_stmt.get_attributes()
```

### 8. tests.e2e.test_api_workflows::test_healthz_always_ok
- suite: market-ingestion:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/market-ingestion_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-4' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<local...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 9. tests.e2e.test_api_workflows::test_readyz_db_ok
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-8' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<local...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 10. tests.e2e.test_api_workflows::test_trigger_single_symbol_creates_task
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "ExceptionGroup: errors while tearing down <Coroutine test_trigger_single_symbol_creates_task> (2 sub-exceptions)"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
+ Exception Group Traceback (most recent call last):
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/_pytest/runner.py", line 341, in from_call
  |     result: Optional[TResult] = func()
  |                                 ^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/_pytest/runner.py", line 241, in <lambda>
  |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise
  |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
  |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
  |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall
  |     raise exception
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
  |     teardown.throw(exception)
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/_pytest/threadexception.py", line 92, in pytest_runtest_teardown
  |     yield from thread_exception_runtest_hook()
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/_pytest/threadexception.py", line 63, in thread_exception_runtest_hook
  |     yield
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
  |     teardown.throw(exception)
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/services/market-ingestion/.venv/lib/python3.11/site-packages/_pytest/unraisableexception.py", line 95, in pytest_runtest_teardown
  |     yield from unraisable_exception_runtest_hook()
```

### 11. tests.e2e.test_api_workflows::test_trigger_multiple_symbols
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":[{"type":"value_error","loc":["body","symbols"],"msg":"Value error, Symbol 'E2E_MULTI_1774969645_A' must be 1-20 characters","input":["E2E_MULTI_1774969645_A","E2E_MULTI_1774969645_B","E2E_MULTI_1774969645_C"],"ctx":{"error":{}}}]}
assert 422 == 202
 +  where 422 = <Response [422 Unprocessable Entity]>.status_code
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10adb4a50>
    async def test_trigger_multiple_symbols(e2e_client: AsyncClient) -> None:
        """POST /api/v1/ingest/trigger with multiple symbols creates N tasks."""
        ts = int(time.time())
        symbols = [f"E2E_MULTI_{ts}_A", f"E2E_MULTI_{ts}_B", f"E2E_MULTI_{ts}_C"]
        resp = await e2e_client.post(
            "/api/v1/ingest/trigger",
            json={
                "provider": "eodhd",
                "symbols": symbols,
                "dataset_type": "ohlcv",
                "timeframe": "1d",
            },
            headers=_AUTH_HEADERS,
        )
>       assert resp.status_code == 202, resp.text
E       AssertionError: {"detail":[{"type":"value_error","loc":["body","symbols"],"msg":"Value error, Symbol 'E2E_MULTI_1774969645_A' must be 1-20 characters","input":["E2E_MULTI_1774969645_A","E2E_MULTI_1774969645_B","E2E_MULTI_1774969645_C"],"ctx":{"error":{}}}]}
E       assert 422 == 202
E        +  where 422 = <Response [422 Unprocessable Entity]>.status_code
tests/e2e/test_api_workflows.py:105: AssertionError
```

### 12. tests.e2e.test_api_workflows::test_trigger_multiple_symbols
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-19' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 13. tests.e2e.test_api_workflows::test_trigger_idempotent
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-23' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 14. tests.e2e.test_api_workflows::test_trigger_invalid_provider_returns_422
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-27' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 15. tests.e2e.test_api_workflows::test_backfill_90_days_produces_3_chunks
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-31' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 16. tests.e2e.test_api_workflows::test_backfill_single_day_one_chunk
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-35' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 17. tests.e2e.test_api_workflows::test_backfill_exceeds_max_chunks_returns_422
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-39' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 18. tests.e2e.test_api_workflows::test_backfill_idempotent
- suite: cross-service:e2e
- kind: failure
- reason: assert 422 == 202
 +  where 422 = <Response [422 Unprocessable Entity]>.status_code
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x11283d650>
    async def test_backfill_idempotent(e2e_client: AsyncClient) -> None:
        """Same backfill request twice: second call has tasks_created=0."""
        symbol = f"E2E_BFIDEM_{int(time.time())}"
        payload = {
            "provider": "eodhd",
            "symbol": symbol,
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "timeframe": "1d",
            "chunk_days": 30,
        }
        resp1 = await e2e_client.post("/api/v1/ingest/backfill", json=payload, headers=_AUTH_HEADERS)
>       assert resp1.status_code == 202
E       assert 422 == 202
E        +  where 422 = <Response [422 Unprocessable Entity]>.status_code
tests/e2e/test_api_workflows.py:224: AssertionError
```

### 19. tests.e2e.test_api_workflows::test_backfill_idempotent
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-43' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 20. tests.e2e.test_api_workflows::test_ingest_status_returns_counts
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-47' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 21. tests.e2e.test_api_workflows::test_list_policies_returns_list
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-51' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 22. tests.e2e.test_api_workflows::test_trigger_then_status_reflects_pending_task
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-55' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 23. tests.e2e.test_api_workflows::test_trigger_full_async_pipeline_reaches_terminal_states
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-62' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```

### 24. tests.e2e.test_api_workflows::test_triggered_task_progresses_out_of_pending
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":[{"type":"value_error","loc":["body","symbols"],"msg":"Value error, Symbol 'E2E_LIFECYCLE_1774969667' must be 1-20 characters","input":["E2E_LIFECYCLE_1774969667"],"ctx":{"error":{}}}]}
assert 422 == 202
 +  where 422 = <Response [422 Unprocessable Entity]>.status_code
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x11269fc10>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x10aba5910>
    async def test_triggered_task_progresses_out_of_pending(
        e2e_client: AsyncClient,
        e2e_db_session: AsyncSession,
    ) -> None:
        """A manually-triggered task should be claimed/processed by worker pipeline.
        We do not require success (provider/network may retry/fail), only that the
        task leaves PENDING and enters processing lifecycle states.
        """
        from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
        from sqlalchemy import select
        symbol = f"E2E_LIFECYCLE_{int(time.time())}"
        resp = await e2e_client.post(
            "/api/v1/ingest/trigger",
            json={
                "provider": "eodhd",
                "symbols": [symbol],
                "dataset_type": "ohlcv",
                "timeframe": "1d",
            },
            headers=_AUTH_HEADERS,
        )
>       assert resp.status_code == 202, resp.text
E       AssertionError: {"detail":[{"type":"value_error","loc":["body","symbols"],"msg":"Value error, Symbol 'E2E_LIFECYCLE_1774969667' must be 1-20 characters","input":["E2E_LIFECYCLE_1774969667"],"ctx":{"error":{}}}]}
```

### 25. tests.e2e.test_api_workflows::test_triggered_task_progresses_out_of_pending
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T145855Z/suites/cross-service_e2e.log
```text
def finalizer() -> None:
        """Yield again, to finalize."""
        async def async_finalizer() -> None:
            try:
                await gen_obj.__anext__()  # type: ignore[union-attr]
            except StopAsyncIteration:
                pass
            else:
                msg = "Async generator fixture didn't stop."
                msg += "Yield only once."
                raise ValueError(msg)
>       event_loop.run_until_complete(async_finalizer())
.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:341:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=True debug=False>
future = <Task finished name='Task-73' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
        Return the Future's result, or raise its exception.
        """
        self._check_closed()
```
