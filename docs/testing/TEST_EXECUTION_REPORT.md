# Test Execution Report

Generated at: 2026-03-25T13:40:53Z
Run ID: 20260325T133514Z
Run artifacts: docs/testing/test-runs/20260325T133514Z
Run duration (sec): 339

## Environment
- git branch: feat/unstructured-data-ingestion-pipeline
- git sha: bd51b08dab872ab0d3f7c679b487ff2c4eeca5e2
- python: Python 3.11.14
- docker: Docker version 29.1.3, build f52814d
- docker compose: Docker Compose version v5.0.0-desktop.1
- retain logs: on-failure
- integration mode: sequential

## Summary
- Test suites passed: 17
- Test suites failed: 4
- Test suites skipped: 27
- Total collected tests: 1055
- Total failed tests: 49
- Note: suite counts and test counts are different units

## Aggregated Metrics
- Collected in passed/failed suites: 1055
- Collected in skipped suites: 0
- Failed tests extracted from JUnit: 49

## Metrics By Layer
| Layer | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| architecture | 1/0/0 | 29 | 0 | 1 |
| contract | 2/0/9 | 17 | 0 | 1 |
| e2e | 0/3/8 | 50 | 48 | 46 |
| infra | 2/0/0 | 0 | 0 | 67 |
| integration | 3/0/8 | 120 | 0 | 31 |
| libs | 1/0/0 | 0 | 0 | 25 |
| unit | 8/1/2 | 839 | 1 | 12 |

## Metrics By Service
| Service | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| alert | 0/0/4 | 0 | 0 | 0 |
| api-gateway | 0/1/3 | 0 | 1 | 0 |
| architecture | 1/0/0 | 29 | 0 | 1 |
| compose | 2/0/0 | 0 | 0 | 67 |
| content-ingestion | 1/0/3 | 24 | 0 | 0 |
| content-store | 1/0/3 | 2 | 0 | 0 |
| intelligence-migrations | 0/0/4 | 0 | 0 | 0 |
| knowledge-graph | 1/0/3 | 2 | 0 | 1 |
| libs | 1/0/0 | 0 | 0 | 25 |
| market-data | 2/1/1 | 339 | 1 | 69 |
| market-ingestion | 3/1/0 | 340 | 1 | 9 |
| nlp-pipeline | 1/0/3 | 2 | 0 | 0 |
| portfolio | 3/1/0 | 315 | 1 | 10 |
| rag-chat | 1/0/3 | 2 | 45 | 1 |

## Failure Hotspots
- rag-chat:e2e: 45 failed tests
- api-gateway:unit: 1 failed tests
- market-data:e2e: 1 failed tests
- market-ingestion:e2e: 1 failed tests
- portfolio:e2e: 1 failed tests

## Infra Status
- Status: passed
- compose ps: docs/testing/test-runs/20260325T133514Z/infra/compose.ps.txt
- compose config: docs/testing/test-runs/20260325T133514Z/infra/compose.config.yaml
- compose all logs: docs/testing/test-runs/20260325T133514Z/infra/compose.all.log
- service logs dir: docs/testing/test-runs/20260325T133514Z/infra/services
- inspect dir: docs/testing/test-runs/20260325T133514Z/infra/inspect

## Suite Results
- architecture: passed (layer=architecture, type=pytest, collected=29, duration=1s)
- libs: passed (layer=libs, type=script, collected=0, duration=25s) - summarized by scripts/test-libs.sh
- alert:unit: skipped (layer=unit, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no unit tests
- api-gateway:unit: failed (layer=unit, type=pytest, collected=0, duration=0s, failure_type=script_failure) - pytest exited with code 4
- content-ingestion:unit: passed (layer=unit, type=pytest, collected=24, duration=0s)
- content-store:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- intelligence-migrations:unit: skipped (layer=unit, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no tests dir
- knowledge-graph:unit: passed (layer=unit, type=pytest, collected=2, duration=1s)
- market-data:unit: passed (layer=unit, type=pytest, collected=248, duration=7s)
- market-ingestion:unit: passed (layer=unit, type=pytest, collected=311, duration=2s)
- nlp-pipeline:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- portfolio:unit: passed (layer=unit, type=pytest, collected=248, duration=1s)
- rag-chat:unit: passed (layer=unit, type=pytest, collected=2, duration=1s)
- alert:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
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
- compose:up: passed (layer=infra, type=compose_startup, collected=0, duration=65s)
- compose:readiness: passed (layer=infra, type=readiness, collected=0, duration=2s)
- alert:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- alert:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- api-gateway:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- api-gateway:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-ingestion:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- content-ingestion:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-store:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- content-store:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- intelligence-migrations:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- intelligence-migrations:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- knowledge-graph:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- knowledge-graph:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- market-data:integration: passed (layer=integration, type=pytest, collected=67, duration=24s)
- market-data:e2e: failed (layer=e2e, type=pytest, collected=24, duration=38s, failure_type=assertion) - pytest exited with code 1
- market-ingestion:integration: passed (layer=integration, type=pytest, collected=10, duration=1s)
- market-ingestion:e2e: failed (layer=e2e, type=pytest, collected=16, duration=6s, failure_type=assertion) - pytest exited with code 1
- nlp-pipeline:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- nlp-pipeline:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- portfolio:integration: passed (layer=integration, type=pytest, collected=43, duration=6s)
- portfolio:e2e: failed (layer=e2e, type=pytest, collected=10, duration=2s, failure_type=assertion) - pytest exited with code 1
- rag-chat:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- rag-chat:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests

## Failed Tests (Reason + Traceback Excerpt)
### 1. <suite-level failure>
- suite: api-gateway:unit
- kind: script_failure
- reason: pytest exited with code 4
- log: docs/testing/test-runs/20260325T133514Z/suites/api-gateway_unit.log

### 2. tests.e2e.test_api_e2e::test_instruments_list_contains_seeded
- suite: market-data:e2e
- kind: failure
- reason: httpx.ReadError
- log: docs/testing/test-runs/20260325T133514Z/suites/market-data_e2e.log
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x10b55a790>
request = <Request('GET', 'http://localhost:8003/api/v1/instruments')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 3. tests.e2e.test_api_e2e::test_instrument_lookup_by_symbol
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_instrument_lookup_by_symbol>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x1128728e0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x10b539b20>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 4. tests.e2e.test_api_e2e::test_instrument_lookup_by_id
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_instrument_lookup_by_id>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112873600>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e4a660>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 5. tests.e2e.test_api_e2e::test_instrument_unknown_id_returns_404
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x113ce4610>
request = <Request('GET', 'http://localhost:8003/api/v1/instruments/00000000-0000-0000-0000-000000000000')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 6. tests.e2e.test_api_e2e::test_ohlcv_returns_seeded_bars
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_returns_seeded_bars>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10aa32fc0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e1b1a0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 7. tests.e2e.test_api_e2e::test_ohlcv_reversed_range_returns_422
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_reversed_range_returns_422>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e1b7e0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1128889a0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 8. tests.e2e.test_api_e2e::test_ohlcv_empty_range_returns_empty_list
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_empty_range_returns_empty_list>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112888860>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e4b2e0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 9. tests.e2e.test_api_e2e::test_ohlcv_available_timeframes
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_available_timeframes>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10b53ab60>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e4bba0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 10. tests.e2e.test_api_e2e::test_ohlcv_date_range_endpoint
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_date_range_endpoint>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e4b6a0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112860d60>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 11. tests.e2e.test_api_e2e::test_ohlcv_bulk_multiple_instruments
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_bulk_multiple_instruments>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112888ae0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x10b539300>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 12. tests.e2e.test_api_e2e::test_quote_cache_aside_first_call_hits_db
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_quote_cache_aside_first_call_hits_db>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10b5396c0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e1b920>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 13. tests.e2e.test_api_e2e::test_quote_second_call_served_from_cache
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_quote_second_call_served_from_cache>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10b53aca0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e4b240>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 14. tests.e2e.test_api_e2e::test_quote_missing_returns_404
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1139d9f50>
request = <Request('GET', 'http://localhost:8003/api/v1/quotes/00000000-0000-0000-0000-000000000000')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 15. tests.e2e.test_api_e2e::test_batch_quotes_post
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_batch_quotes_post>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e1a2a0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1134f18a0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 16. tests.e2e.test_api_e2e::test_batch_quotes_get_latest
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_batch_quotes_get_latest>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10a9dcb80>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x10b53ac00>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 17. tests.e2e.test_api_e2e::test_securities_list_contains_seeded
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_securities_list_contains_seeded>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e4a7a0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1134f2b60>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 18. tests.e2e.test_api_e2e::test_security_detail_by_id
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_security_detail_by_id>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10a9dcb80>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1128727a0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 19. tests.e2e.test_api_e2e::test_security_unknown_id_returns_404
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x114414590>
request = <Request('GET', 'http://localhost:8003/api/v1/securities/00000000-0000-0000-0000-000000000000')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 20. tests.e2e.test_pipeline_e2e::test_ohlcv_priority_resolution_visible_via_api
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_ohlcv_priority_resolution_visible_via_api>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x10b538d60>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1134f32e0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 21. tests.e2e.test_pipeline_e2e::test_quote_update_reflected_via_api
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_quote_update_reflected_via_api>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x1128736a0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e1a520>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 22. tests.e2e.test_pipeline_e2e::test_instrument_flags_promoted_by_data_ingest
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_instrument_flags_promoted_by_data_ingest>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e1a5c0>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x1134f31a0>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 23. tests.e2e.test_pipeline_e2e::test_fundamentals_income_statement_accessible
- suite: rag-chat:e2e
- kind: error
- reason: failed on setup with "OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5433)"
```text
request = <SubRequest 'e2e_db_session' for <Coroutine test_fundamentals_income_statement_accessible>>
kwargs = {}, func = <function e2e_db_session at 0x10b0d0040>
setup = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.setup at 0x112e1a340>
finalizer = <function _wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer at 0x112e4b380>
    @functools.wraps(fixture)
    def _asyncgen_fixture_wrapper(request: SubRequest, **kwargs: Any):
        func = _perhaps_rebind_fixture_func(
            fixture, request.instance, fixturedef.unittest
        )
        event_loop = kwargs.pop(event_loop_fixture_id)
        gen_obj = func(
            **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
        )
        async def setup():
            res = await gen_obj.__anext__()
            return res
        def finalizer() -> None:
            """Yield again, to finalize."""
            async def async_finalizer() -> None:
                try:
                    await gen_obj.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    msg = "Async generator fixture didn't stop."
```

### 24. tests.e2e.test_api_workflows::test_healthz_always_ok
- suite: market-ingestion:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
- log: docs/testing/test-runs/20260325T133514Z/suites/market-ingestion_e2e.log
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('GET', 'http://localhost:8002/healthz')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 25. tests.e2e.test_api_workflows::test_readyz_db_ok
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('GET', 'http://localhost:8002/readyz')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 26. tests.e2e.test_api_workflows::test_trigger_single_symbol_creates_task
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 27. tests.e2e.test_api_workflows::test_trigger_multiple_symbols
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 28. tests.e2e.test_api_workflows::test_trigger_idempotent
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 29. tests.e2e.test_api_workflows::test_trigger_invalid_provider_returns_422
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 30. tests.e2e.test_api_workflows::test_backfill_90_days_produces_3_chunks
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/backfill')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 31. tests.e2e.test_api_workflows::test_backfill_single_day_one_chunk
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/backfill')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 32. tests.e2e.test_api_workflows::test_backfill_exceeds_max_chunks_returns_422
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/backfill')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 33. tests.e2e.test_api_workflows::test_backfill_idempotent
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/backfill')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 34. tests.e2e.test_api_workflows::test_ingest_status_returns_counts
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('GET', 'http://localhost:8002/api/v1/ingest/status')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 35. tests.e2e.test_api_workflows::test_list_policies_returns_list
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('GET', 'http://localhost:8002/api/v1/policies')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 36. tests.e2e.test_api_workflows::test_trigger_then_status_reflects_pending_task
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 37. tests.e2e.test_api_workflows::test_trigger_full_async_pipeline_reaches_terminal_states
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 38. tests.e2e.test_api_workflows::test_scheduler_active_guard_prevents_duplicate_active_tasks
- suite: rag-chat:e2e
- kind: failure
- reason: OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 55433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 55433)
```text
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x110517010>
    async def test_scheduler_active_guard_prevents_duplicate_active_tasks(
        e2e_db_session: AsyncSession,
    ) -> None:
        """Scheduler should not keep more than one active task per stream tuple.
        Validates the guard behind `scheduler_skip_active_task` for incremental
        streams where variant is not used (OHLCV/QUOTES), checking there are no
        duplicate active rows (PENDING/RUNNING/RETRY) for the same:
        provider + dataset_type + symbol + exchange + timeframe + variant.
        """
        from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
        from sqlalchemy import func, select
        await asyncio.sleep(5)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            duplicates = (
>               await e2e_db_session.execute(
                    select(
                        IngestionTaskModel.provider,
                        IngestionTaskModel.dataset_type,
                        IngestionTaskModel.symbol,
                        IngestionTaskModel.exchange,
                        IngestionTaskModel.timeframe,
                        IngestionTaskModel.dataset_variant,
                        func.count().label("n"),
```

### 39. tests.e2e.test_api_workflows::test_triggered_task_progresses_out_of_pending
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1089e2250>
request = <Request('POST', 'http://localhost:8002/api/v1/ingest/trigger')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 40. tests.e2e.test_full_flow::test_full_transaction_flow
- suite: portfolio:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
- log: docs/testing/test-runs/20260325T133514Z/suites/portfolio_e2e.log
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x10b0b7290>
request = <Request('POST', 'http://localhost:8001/api/v1/tenants')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 41. tests.e2e.test_full_flow::test_readyz_returns_ok
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x112b88090>
request = <Request('GET', 'http://localhost:8001/readyz')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 42. tests.e2e.test_full_flow::test_healthz_returns_ok
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x11297b390>
request = <Request('GET', 'http://localhost:8001/healthz')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 43. tests.e2e.test_full_flow::test_create_tenant_returns_valid_id
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x112838b10>
request = <Request('POST', 'http://localhost:8001/api/v1/tenants')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 44. tests.e2e.test_full_flow::test_duplicate_portfolio_name_rejected
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x112b903d0>
request = <Request('POST', 'http://localhost:8001/api/v1/tenants')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 45. tests.e2e.test_full_flow::test_sell_exceeding_holdings_rejected
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x112c08cd0>
request = <Request('POST', 'http://localhost:8001/api/v1/tenants')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 46. tests.e2e.test_full_flow::test_archive_portfolio
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x112c1f090>
request = <Request('POST', 'http://localhost:8001/api/v1/tenants')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```

### 47. tests.e2e.test_instrument_sync::test_instrument_consumer_upserts_instrument
- suite: rag-chat:e2e
- kind: failure
- reason: OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 55433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 55433)
```text
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112c38f90>
    async def test_instrument_consumer_upserts_instrument(e2e_db_session: AsyncSession) -> None:
        """InstrumentEventConsumer.process_message() upserts an InstrumentRef row."""
        from portfolio.infrastructure.db.session import create_session_factory
        from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer
        from sqlalchemy import select
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        engine, session_factory = create_session_factory(_DB_URL)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",  # not used in direct-call path
            group_id="e2e-test-consumer",
            topics=["market.instrument.created"],
        )
        consumer = InstrumentEventConsumer(config, session_factory)
        event_id = str(uuid.uuid4())
        symbol = f"E2E_{event_id[:6].upper()}"
        exchange = "NASDAQ"
>       await consumer.process_message(
            key=symbol,
            value={
                "event_id": event_id,
                "symbol": symbol,
                "exchange": exchange,
                "name": "E2E Test Corp",
                "currency": "USD",
```

### 48. tests.e2e.test_instrument_sync::test_instrument_consumer_idempotent
- suite: rag-chat:e2e
- kind: failure
- reason: OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 55433, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 55433)
```text
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x113a3aa50>
    async def test_instrument_consumer_idempotent(e2e_db_session: AsyncSession) -> None:
        """Duplicate events (same event_id) do NOT create duplicate InstrumentRef rows."""
        from portfolio.infrastructure.db.session import create_session_factory
        from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer
        from sqlalchemy import func, select
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        engine, session_factory = create_session_factory(_DB_URL)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="e2e-test-idem",
            topics=["market.instrument.created"],
        )
        consumer = InstrumentEventConsumer(config, session_factory)
        event_id = str(uuid.uuid4())
        symbol = f"IDEM_{event_id[:4].upper()}"
        exchange = "NYSE"
        payload = {"event_id": event_id, "symbol": symbol, "exchange": exchange}
        # Process the same event twice
>       await consumer.process_message(key=symbol, value=payload, headers={})
tests/e2e/test_instrument_sync.py:104:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <portfolio.infrastructure.messaging.consumers.instrument_consumer.InstrumentEventConsumer object at 0x113abf190>
key = 'IDEM_6604'
value = {'event_id': '6604e6d7-3cd7-4a2c-bc9a-af6237957365', 'exchange': 'NYSE', 'symbol': 'IDEM_6604'}
```

### 49. tests.e2e.test_instrument_sync::test_list_instruments_endpoint
- suite: rag-chat:e2e
- kind: failure
- reason: httpx.ConnectError: All connection attempts failed
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.11/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x1130b8510>
request = <Request('GET', 'http://localhost:8001/api/v1/instruments')>
    async def handle_async_request(
        self,
        request: Request,
    ) -> Response:
        assert isinstance(request.stream, AsyncByteStream)
        req = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
```
