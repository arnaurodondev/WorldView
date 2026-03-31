# Test Execution Report

Generated at: 2026-03-31T08:33:44Z
Run ID: 20260331T082221Z
Run artifacts: docs/testing/test-runs/20260331T082221Z
Run duration (sec): 683

## Environment
- git branch: feat/content-ingestion-wave-a1
- git sha: f07f9c67d6a660529650af117dbe425633c666df
- python: Python 3.12.7
- docker: Docker version 29.1.3, build f52814d
- docker compose: Docker Compose version v5.0.0-desktop.1
- retain logs: on-failure
- integration mode: sequential

## Summary
- Test suites passed: 23
- Test suites failed: 11
- Test suites skipped: 15
- Total collected tests: 2719
- Total failed tests: 201
- Note: suite counts and test counts are different units

## Aggregated Metrics
- Collected in passed/failed suites: 2719
- Collected in skipped suites: 0
- Failed tests extracted from JUnit: 201

## Metrics By Layer
| Layer | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| architecture | 1/0/0 | 35 | 0 | 2 |
| contract | 3/0/8 | 20 | 0 | 1 |
| e2e | 1/8/3 | 266 | 198 | 192 |
| infra | 2/0/0 | 0 | 0 | 65 |
| integration | 5/3/3 | 202 | 3 | 37 |
| libs | 1/0/0 | 0 | 0 | 6 |
| unit | 10/0/1 | 2196 | 0 | 16 |

## Metrics By Service
| Service | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| alert | 2/2/0 | 168 | 2 | 10 |
| api-gateway | 1/0/3 | 12 | 0 | 1 |
| architecture | 1/0/0 | 35 | 0 | 2 |
| compose | 2/0/0 | 0 | 0 | 65 |
| content-ingestion | 2/1/1 | 447 | 1 | 7 |
| content-store | 2/1/1 | 275 | 1 | 7 |
| cross-service | 0/1/0 | 97 | 191 | 132 |
| intelligence-migrations | 0/0/4 | 0 | 0 | 0 |
| knowledge-graph | 2/1/1 | 219 | 1 | 15 |
| libs | 1/0/0 | 0 | 0 | 6 |
| market-data | 2/1/1 | 429 | 1 | 38 |
| market-ingestion | 3/1/0 | 421 | 1 | 23 |
| nlp-pipeline | 2/1/1 | 255 | 1 | 7 |
| portfolio | 2/2/0 | 359 | 2 | 6 |
| rag-chat | 1/0/3 | 2 | 0 | 0 |

## Failure Hotspots
- cross-service:e2e: 191 failed tests
- alert:e2e: 1 failed tests
- alert:integration: 1 failed tests
- content-ingestion:e2e: 1 failed tests
- content-store:e2e: 1 failed tests
- knowledge-graph:e2e: 1 failed tests
- market-data:integration: 1 failed tests
- market-ingestion:e2e: 1 failed tests
- nlp-pipeline:e2e: 1 failed tests
- portfolio:e2e: 1 failed tests
- portfolio:integration: 1 failed tests

## Infra Status
- Status: passed
- compose ps: docs/testing/test-runs/20260331T082221Z/infra/compose.ps.txt
- compose config: docs/testing/test-runs/20260331T082221Z/infra/compose.config.yaml
- compose all logs: docs/testing/test-runs/20260331T082221Z/infra/compose.all.log
- service logs dir: docs/testing/test-runs/20260331T082221Z/infra/services
- inspect dir: docs/testing/test-runs/20260331T082221Z/infra/inspect

## Suite Results
- architecture: passed (layer=architecture, type=pytest, collected=35, duration=2s)
- libs: passed (layer=libs, type=script, collected=0, duration=6s) - summarized by scripts/test-libs.sh
- alert:unit: passed (layer=unit, type=pytest, collected=126, duration=1s)
- api-gateway:unit: passed (layer=unit, type=pytest, collected=12, duration=1s)
- content-ingestion:unit: passed (layer=unit, type=pytest, collected=401, duration=2s)
- content-store:unit: passed (layer=unit, type=pytest, collected=241, duration=2s)
- intelligence-migrations:unit: skipped (layer=unit, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no tests collected
- knowledge-graph:unit: passed (layer=unit, type=pytest, collected=177, duration=1s)
- market-data:unit: passed (layer=unit, type=pytest, collected=338, duration=7s)
- market-ingestion:unit: passed (layer=unit, type=pytest, collected=392, duration=1s)
- nlp-pipeline:unit: passed (layer=unit, type=pytest, collected=217, duration=1s)
- portfolio:unit: passed (layer=unit, type=pytest, collected=290, duration=0s)
- rag-chat:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- alert:contract: passed (layer=contract, type=pytest, collected=3, duration=1s)
- api-gateway:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-ingestion:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-store:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- intelligence-migrations:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract dir
- knowledge-graph:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-data:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-ingestion:contract: passed (layer=contract, type=pytest, collected=3, duration=0s)
- nlp-pipeline:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- portfolio:contract: passed (layer=contract, type=pytest, collected=14, duration=0s)
- rag-chat:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- compose:up: passed (layer=infra, type=compose_startup, collected=0, duration=62s)
- compose:readiness: passed (layer=infra, type=readiness, collected=0, duration=3s)
- alert:integration: failed (layer=integration, type=pytest, collected=19, duration=5s, failure_type=assertion) - pytest exited with code 1
- alert:e2e: failed (layer=e2e, type=pytest, collected=20, duration=3s, failure_type=assertion) - pytest exited with code 1
- api-gateway:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- api-gateway:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-ingestion:integration: passed (layer=integration, type=pytest, collected=24, duration=1s)
- content-ingestion:e2e: failed (layer=e2e, type=pytest, collected=22, duration=4s, failure_type=assertion) - pytest exited with code 1
- content-store:integration: passed (layer=integration, type=pytest, collected=10, duration=1s)
- content-store:e2e: failed (layer=e2e, type=pytest, collected=24, duration=4s, failure_type=assertion) - pytest exited with code 1
- intelligence-migrations:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- intelligence-migrations:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- knowledge-graph:integration: passed (layer=integration, type=pytest, collected=22, duration=1s)
- knowledge-graph:e2e: failed (layer=e2e, type=pytest, collected=20, duration=13s, failure_type=assertion) - pytest exited with code 1
- market-data:integration: failed (layer=integration, type=pytest, collected=67, duration=23s, failure_type=assertion) - pytest exited with code 1
- market-data:e2e: passed (layer=e2e, type=pytest, collected=24, duration=8s)
- market-ingestion:integration: passed (layer=integration, type=pytest, collected=10, duration=0s)
- market-ingestion:e2e: failed (layer=e2e, type=pytest, collected=16, duration=22s, failure_type=assertion) - pytest exited with code 1
- nlp-pipeline:integration: passed (layer=integration, type=pytest, collected=5, duration=1s)
- nlp-pipeline:e2e: failed (layer=e2e, type=pytest, collected=33, duration=5s, failure_type=assertion) - pytest exited with code 1
- portfolio:integration: failed (layer=integration, type=pytest, collected=45, duration=5s, failure_type=assertion) - pytest exited with code 1
- portfolio:e2e: failed (layer=e2e, type=pytest, collected=10, duration=1s, failure_type=assertion) - pytest exited with code 1
- rag-chat:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- rag-chat:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- cross-service:e2e: failed (layer=e2e, type=pytest, collected=97, duration=132s, failure_type=assertion) - pytest exited with code 1

## Failed Tests (Reason + Traceback Excerpt)
### 1. tests.integration.test_dedup::test_dedup_suppresses_second_event_in_same_window
- suite: alert:integration
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/alert_integration.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_dedup_suppresses_second_event_in_same_window>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x10955aae0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109a1d760>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-1' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 2. tests.integration.test_dedup::test_different_alert_types_not_deduped
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_different_alert_types_not_deduped>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109cd95e0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d27a60>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-2' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 3. tests.integration.test_dedup::test_different_entities_not_deduped
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_different_entities_not_deduped>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109cb12b0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109f09f80>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-3' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 4. tests.integration.test_fanout::test_fanout_creates_alert_in_db
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_creates_alert_in_db>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109469970>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109cb60c0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-4' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 5. tests.integration.test_fanout::test_fanout_creates_pending_row_in_db
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_creates_pending_row_in_db>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x10957c8f0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109f0ba60>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-5' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 6. tests.integration.test_fanout::test_fanout_creates_outbox_event
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_creates_outbox_event>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109a20140>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d72a20>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-6' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 7. tests.integration.test_fanout::test_fanout_suppresses_backfill
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_suppresses_backfill>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109695130>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109f094e0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-7' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 8. tests.integration.test_fanout::test_fanout_no_watchers_writes_nothing
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_no_watchers_writes_nothing>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109e4e1e0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d70d60>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-8' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 9. tests.integration.test_s7_s10_pipeline::test_s7_graph_event_creates_alert
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_s7_graph_event_creates_alert>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109fe73e0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d70cc0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-9' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined ...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 10. tests.integration.test_s7_s10_pipeline::test_s7_graph_event_creates_pending_alert
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_s7_graph_event_creates_pending_alert>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109d7c4d0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d71080>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-10' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 11. tests.integration.test_s7_s10_pipeline::test_s7_backfill_graph_event_suppressed
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_s7_backfill_graph_event_suppressed>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109faf890>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d70ea0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-11' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 12. tests.integration.test_s7_s10_pipeline::test_pipeline_api_returns_alert_after_fanout
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_pipeline_api_returns_alert_after_fanout>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109decbc0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109f899e0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-12' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 13. tests.integration.test_websocket::test_fanout_pushes_to_connected_user
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_pushes_to_connected_user>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109fb2ea0>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109fdf9c0>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-23' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 14. tests.integration.test_websocket::test_fanout_offline_user_no_error
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_fanout_offline_user_no_error>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109fdb050>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109d73a60>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-24' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 15. tests.integration.test_websocket::test_ws_stream_endpoint_connects
- suite: cross-service:e2e
- kind: error
- reason: failed on setup with "TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
request = <SubRequest 'integration_app' for <Coroutine test_ws_stream_endpoint_connects>>
kwargs = {'db_session_factory': (async_sessionmaker(class_='AsyncSession', bind=<sqlalchemy.ext.asyncio.engine.AsyncEngine obje...nnectionPool(<fakeredis.aioredis.FakeConnection(server=<fakeredis._server.FakeServer object at 0x109fdbe60>,db=0)>)>)>}
unittest = False
setup = <function _wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup at 0x109fdca40>
    @functools.wraps(fixture)
    def _async_fixture_wrapper(request: FixtureRequest, **kwargs: Any):
        unittest = False if pytest.version_tuple >= (8, 2) else fixturedef.unittest
        func = _perhaps_rebind_fixture_func(fixture, request.instance, unittest)
        event_loop = kwargs.pop(event_loop_fixture_id)
        async def setup():
            res = await func(
                **_add_kwargs(func, kwargs, event_loop_fixture_id, event_loop, request)
            )
            return res
>       return event_loop.run_until_complete(setup())
.venv/lib/python3.12/site-packages/pytest_asyncio/plugin.py:369:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <_UnixSelectorEventLoop running=False closed=False debug=False>
future = <Task finished name='Task-25' coro=<_wrap_async_fixture.<locals>._async_fixture_wrapper.<locals>.setup() done, defined...in.py:363> exception=TypeError("AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'")>
    def run_until_complete(self, future):
        """Run until the Future is done.
        If the argument is a coroutine, it is wrapped in a Task.
        WARNING: It would be disastrous to call run_until_complete()
        with the same coroutine twice -- it would wrap it in two
        different Tasks and that can't be good.
```

### 16. tests.e2e.test_api_workflows::test_pending_alerts_empty_for_new_user
- suite: alert:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT pending_alerts.pending_id, pending_alerts.user_id, pending_alerts.alert_id, pending_alerts.created_at, pending_alerts.delivered_at
FROM pending_alerts
WHERE pending_alerts.user_id = $1::UUID AND pending_alerts.delivered_at IS NULL ORDER BY pending_alerts.created_at DESC
 LIMIT $2::INTEGER OFFSET $3::INTEGER]
[parameters: (UUID('9bc84132-aea5-4c82-8911-aea4c0933eb8'), 50, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/alert_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x109f5f450>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 17. tests.e2e.test_api_workflows::test_pending_alerts_returns_seeded_alert
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('8d419e30-5840-4b34-93ad-63e4c670ab06', '27fce4ce-44e1-447d-b24a-0d0d4494d7f5', 'breakout_signal', 'cad05f09-5c37-43ea-ae69-30ee38c2e6c0', 'nlp.signal.detected.v1', 'signal:27fce4ce-44e1-447d-b24a-0d0d4494d7f5:02d1b8cd', datetime.datetime(2026, 3, 31, 8, 26, 50, 29879, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x109f19a10>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 18. tests.e2e.test_api_workflows::test_pending_alerts_tenant_isolation
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('123b756c-2088-4a79-b62b-595c1b673faf', '8446b00f-e01b-4312-9d93-04df17cf8e1c', 'signal', 'a3bd3276-e1b1-4111-8797-e1642f7f4d84', 'nlp.signal.detected.v1', 'signal:8446b00f-e01b-4312-9d93-04df17cf8e1c:fe40926a', datetime.datetime(2026, 3, 31, 8, 26, 50, 148999, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x109b51150>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 19. tests.e2e.test_api_workflows::test_pending_alerts_pagination_offset_and_limit
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('5724902d-4b2f-4052-9224-efe54e43b817', 'a86da7d7-11f4-4c25-a9fb-9f8bb15aca9b', 'signal', '6e2c85d7-20c7-468d-822b-c3a1a0eb70ab', 'nlp.signal.detected.v1', 'key:15dbd0811c1a4b539be025ae56a83609', datetime.datetime(2026, 3, 31, 8, 26, 50, 261848, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10ad03e60>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 20. tests.e2e.test_api_workflows::test_acknowledge_unknown_alert_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: UPDATE pending_alerts SET delivered_at=$1::TIMESTAMP WITH TIME ZONE WHERE pending_alerts.user_id = $2::UUID AND pending_alerts.alert_id = $3::UUID AND pending_alerts.delivered_at IS NULL]
[parameters: (datetime.datetime(2026, 3, 31, 8, 26, 50, 383195, tzinfo=datetime.timezone.utc), UUID('b5b23029-7e0e-40db-a9cc-c70fe760f079'), UUID('1345c8cb-38ea-492a-8f1a-26161d30cd74'))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a91a2d0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 21. tests.e2e.test_api_workflows::test_acknowledge_other_users_alert_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('9b5e3708-132d-41d8-a313-81a28500f711', 'a335aeba-7a98-488b-9d4e-6dbc085e39a1', 'signal', 'd0db61a0-284f-4d2c-be6b-01ee534cbdc0', 'nlp.signal.detected.v1', 'key:eb0428261c5140c2bc91fb77cd737f0e', datetime.datetime(2026, 3, 31, 8, 26, 50, 584953, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a968820>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 22. tests.e2e.test_api_workflows::test_acknowledge_own_alert_succeeds
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('d9b79d99-eb74-47a0-8999-0bca675bd801', 'c414b56b-1006-4319-8f31-ae4efa6cf225', 'signal', 'e720e43c-ea88-4c4f-bb8f-60adcf331d59', 'nlp.signal.detected.v1', 'key:14ac4bc277844c47b352ed3f26aac53c', datetime.datetime(2026, 3, 31, 8, 26, 50, 692711, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a9787b0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 23. tests.e2e.test_api_workflows::test_acknowledge_already_acknowledged_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES ($1, $2, $3, $4, $5, :payload::jsonb, $6, $7)
        ]
[parameters: ('ca44b611-e430-40a3-918d-011863d12ae0', '724a36a7-3791-4a51-bb67-95a2a59b8431', 'signal', 'a161d8a0-8b16-4f1e-88e2-882c498844e0', 'nlp.signal.detected.v1', 'key:f28a4c23e4cb4c129513cda01f113a26', datetime.datetime(2026, 3, 31, 8, 26, 50, 801571, tzinfo=datetime.timezone.utc))]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a8ae3b0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 24. tests.e2e.test_api_workflows::test_dlq_list_empty_on_clean_db
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.status = $1::VARCHAR(20) ORDER BY dead_letter_queue.created_at DESC
 LIMIT $2::INTEGER OFFSET $3::INTEGER]
[parameters: (<DLQStatus.FAILED: 'failed'>, 100, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a76fdf0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 25. tests.e2e.test_api_workflows::test_dlq_seeded_entry_visible_to_admin
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_bytes, error_detail, status, created_at)
            VALUES ($1, $2, 'alert.dead-letter.v1', E'\\x00'::bytea,
                    'unknown alert_type: INVALID', 'failed', now())
        ]
[parameters: ('57e4308b-85ba-4016-a0b7-d82bcd13b869', '4a8b368c-5dda-4710-8747-7f6bca3423c6')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a6c51c0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 26. tests.e2e.test_api_workflows::test_dlq_resolve_note_too_long_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_bytes, status, created_at)
            VALUES ($1, $2, 'test', E'\\x00'::bytea, 'failed', now())
        ]
[parameters: ('a0f83506-c53a-4cdf-a15a-494d09cbc9f0', 'd7292884-e575-4a3f-8962-e12490b6d800')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a21e1f0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 27. tests.e2e.test_api_workflows::test_dlq_pagination
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, payload_bytes, status, created_at)
                VALUES ($1, $2, 'test', E'\\x00'::bytea, 'failed', now())
            ]
[parameters: ('42420748-6ae3-462e-a3e2-ee9ecf0ee933', 'ac6a27b7-2294-4943-b120-d8b8d9e0f438')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x109b55f40>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10a21f4c0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 28. tests.e2e.test_api_workflows::test_admin_list_sources_empty_on_fresh_db
- suite: content-ingestion:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'read_uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/content-ingestion_e2e.log
```text
self = <starlette.datastructures.State object at 0x10b33abd0>
key = 'read_uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'read_uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b3cc8d0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_list_sources_empty_on_fresh_db(e2e_client, admin_headers):
        """GET /api/v1/sources on a clean DB returns an empty list."""
>       resp = await e2e_client.get("/api/v1/sources", headers=admin_headers)
tests/e2e/test_api_workflows.py:71:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b3cc8d0>, url = '/api/v1/sources'
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

### 29. tests.e2e.test_api_workflows::test_admin_create_source_returns_201
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bec0590>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b679650>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_create_source_returns_201(e2e_client, admin_headers):
        """POST /api/v1/sources with a valid body → 201 and the created resource."""
        unique_name = f"e2e-eodhd-{uuid.uuid4().hex[:8]}"
>       resp = await e2e_client.post(
            "/api/v1/sources",
            json={
                "name": unique_name,
                "source_type": "eodhd",
                "config": {"symbols": ["AAPL", "MSFT"]},
                "enabled": True,
            },
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:81:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
```

### 30. tests.e2e.test_api_workflows::test_admin_create_duplicate_source_name_returns_409_or_422
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bb17ed0>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b509d50>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_create_duplicate_source_name_returns_409_or_422(e2e_client, admin_headers):
        """POST /api/v1/sources with a duplicate name → 409 Conflict or 422 Unprocessable."""
        unique_name = f"e2e-dup-{uuid.uuid4().hex[:8]}"
        payload = {"name": unique_name, "source_type": "finnhub"}
>       first = await e2e_client.post("/api/v1/sources", json=payload, headers=admin_headers)
tests/e2e/test_api_workflows.py:106:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b509d50>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
```

### 31. tests.e2e.test_api_workflows::test_admin_update_source_returns_200
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bbb4710>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10ba73fd0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_update_source_returns_200(e2e_client, admin_headers):
        """PUT /api/v1/sources/{id} updates source fields and returns the updated resource."""
        unique_name = f"e2e-upd-{uuid.uuid4().hex[:8]}"
>       create_resp = await e2e_client.post(
            "/api/v1/sources",
            json={"name": unique_name, "source_type": "newsapi", "enabled": True},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:117:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10ba73fd0>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
```

### 32. tests.e2e.test_api_workflows::test_admin_update_nonexistent_source_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bfb0650>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b9bc8d0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_update_nonexistent_source_returns_404(e2e_client, admin_headers):
        """PUT /api/v1/sources/{id} for a non-existent source → 404."""
        nonexistent_id = str(uuid.uuid4())
>       resp = await e2e_client.put(
            f"/api/v1/sources/{nonexistent_id}",
            json={"enabled": False},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:139:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b9bc8d0>
url = '/api/v1/sources/326c7ea9-e034-4b0f-9b0d-5ebaa07cbb71'
    async def put(
        self,
        url: URLTypes,
```

### 33. tests.e2e.test_api_workflows::test_admin_pipeline_status_returns_counts
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bfa2d90>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b885350>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_pipeline_status_returns_counts(e2e_client, admin_headers):
        """GET /api/v1/status returns a status summary with the expected keys."""
        # Seed one source so the status isn't completely empty
>       await e2e_client.post(
            "/api/v1/sources",
            json={"name": f"e2e-status-{uuid.uuid4().hex[:8]}", "source_type": "sec_edgar"},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:150:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b885350>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
```

### 34. tests.e2e.test_api_workflows::test_admin_trigger_source_returns_202
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10be30650>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10ba4b390>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_trigger_source_returns_202(e2e_client, admin_headers):
        """POST /api/v1/sources/{id}/trigger → 202 Accepted with triggered status."""
        unique_name = f"e2e-trigger-{uuid.uuid4().hex[:8]}"
>       create_resp = await e2e_client.post(
            "/api/v1/sources",
            json={"name": unique_name, "source_type": "eodhd"},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:171:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10ba4b390>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
```

### 35. tests.e2e.test_api_workflows::test_admin_trigger_nonexistent_source_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10bed4410>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10bb036d0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_admin_trigger_nonexistent_source_returns_404(e2e_client, admin_headers):
        """POST /api/v1/sources/{id}/trigger for a non-existent source → 404."""
        nonexistent_id = str(uuid.uuid4())
>       resp = await e2e_client.post(
            f"/api/v1/sources/{nonexistent_id}/trigger",
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:192:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10bb036d0>
url = '/api/v1/sources/8bd1768f-6da8-4f6c-b39f-d09b86aed9b3/trigger'
    async def post(
        self,
        url: URLTypes,
        *,
```

### 36. tests.e2e.test_api_workflows::test_dlq_list_empty_on_fresh_db
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'read_uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10c0724d0>
key = 'read_uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'read_uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10bb86cd0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_dlq_list_empty_on_fresh_db(e2e_client, admin_headers):
        """GET /admin/dlq on a clean DB returns an empty entry list."""
>       resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
tests/e2e/test_api_workflows.py:204:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10bb86cd0>, url = '/admin/dlq'
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

### 37. tests.e2e.test_api_workflows::test_dlq_get_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'read_uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10c1aefd0>
key = 'read_uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'read_uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b92a590>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_dlq_get_nonexistent_entry_returns_404(e2e_client, admin_headers):
        """GET /admin/dlq/{id} for a non-existent entry → 404."""
        nonexistent_id = str(uuid.uuid4())
>       resp = await e2e_client.get(f"/admin/dlq/{nonexistent_id}", headers=admin_headers)
tests/e2e/test_api_workflows.py:214:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b92a590>
url = '/admin/dlq/6de89154-f4e2-4932-8511-577730ed1471'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
```

### 38. tests.e2e.test_api_workflows::test_dlq_retry_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10be46790>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10bb865d0>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_dlq_retry_nonexistent_entry_returns_404(e2e_client, admin_headers):
        """POST /admin/dlq/{id}/retry for a non-existent entry → 404."""
        nonexistent_id = str(uuid.uuid4())
>       resp = await e2e_client.post(f"/admin/dlq/{nonexistent_id}/retry", headers=admin_headers)
tests/e2e/test_api_workflows.py:227:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10bb865d0>
url = '/admin/dlq/120cda6f-945f-47c1-a2a1-d9d9c2cf39a9/retry'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
```

### 39. tests.e2e.test_api_workflows::test_dlq_resolve_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10c233610>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10af1cc90>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_dlq_resolve_nonexistent_entry_returns_404(e2e_client, admin_headers):
        """POST /admin/dlq/{id}/resolve for a non-existent entry → 404."""
        nonexistent_id = str(uuid.uuid4())
>       resp = await e2e_client.post(
            f"/admin/dlq/{nonexistent_id}/resolve",
            json={"note": "Manual resolution of missing entry"},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:234:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10af1cc90>
url = '/admin/dlq/274e7e09-fb46-4660-abfa-00a86cd9f1fc/resolve'
    async def post(
        self,
        url: URLTypes,
```

### 40. tests.e2e.test_api_workflows::test_create_source_with_invalid_type_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10c217350>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10b417650>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_create_source_with_invalid_type_returns_422(e2e_client, admin_headers):
        """POST /api/v1/sources with an invalid source_type value → 422.
        The route validates source_type against the SourceType enum on create.
        Invalid values must be rejected before any DB write.
        """
>       resp = await e2e_client.post(
            "/api/v1/sources",
            json={
                "name": f"e2e-bad-type-{uuid.uuid4().hex[:8]}",
                "source_type": "totally_invalid_provider",
            },
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:273:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
```

### 41. tests.e2e.test_api_workflows::test_create_source_with_missing_name_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'State' object has no attribute 'uow_factory'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <starlette.datastructures.State object at 0x10c32a750>
key = 'uow_factory'
    def __getattr__(self, key: typing.Any) -> typing.Any:
        try:
>           return self._state[key]
E           KeyError: 'uow_factory'
.venv/lib/python3.11/site-packages/starlette/datastructures.py:699: KeyError
During handling of the above exception, another exception occurred:
e2e_client = <httpx.AsyncClient object at 0x10c079010>
admin_headers = {'X-Admin-Token': 'e2e-admin-token'}
    async def test_create_source_with_missing_name_returns_422(e2e_client, admin_headers):
        """POST /api/v1/sources without the required 'name' field → 422."""
>       resp = await e2e_client.post(
            "/api/v1/sources",
            json={"source_type": "eodhd"},
            headers=admin_headers,
        )
tests/e2e/test_api_workflows.py:291:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10c079010>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
```

### 42. tests.e2e.test_api_workflows.TestHealthEndpoints::test_readyz_with_healthy_db
- suite: content-store:e2e
- kind: failure
- reason: AssertionError: assert 'error' == 'ok'

  - ok
  + error
- log: docs/testing/test-runs/20260331T082221Z/suites/content-store_e2e.log
```text
self = <e2e.test_api_workflows.TestHealthEndpoints object at 0x10d9c37d0>
e2e_client = <httpx.AsyncClient object at 0x10dd94910>
    async def test_readyz_with_healthy_db(self, e2e_client: AsyncClient) -> None:
        """GET /readyz returns a JSON body with at least a 'status' field.
        With a real DB and consumer_alive=True the status should be 'ok'.
        Valkey is None so the health check skips the ping (returns ok).
        """
        response = await e2e_client.get("/readyz")
        # Status is either 200 (all checks pass) or 503 (degraded).
        # With real DB + consumer_alive=True + valkey=None → 200 expected.
        assert response.status_code in {200, 503}
        body = response.json()
        assert "status" in body
        # Database check must be ok because we have a real DB
>       assert body.get("database") == "ok"
E       AssertionError: assert 'error' == 'ok'
E
E         - ok
E         + error
tests/e2e/test_api_workflows.py:140: AssertionError
```

### 43. tests.e2e.test_api_workflows.TestDLQAuthentication::test_dlq_list_with_valid_token_returns_200
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM dead_letter_queue
WHERE dead_letter_queue.status = $1::VARCHAR]
[parameters: ('failed',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10def4580>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 44. tests.e2e.test_api_workflows.TestDLQNotFound::test_dlq_get_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.aggregate_type, dead_letter_queue.aggregate_id, dead_letter_queue.event_type, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.payload_json, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('cff5d1d4-625a-4201-a6c5-f969cdde4f6b'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e5ef990>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 45. tests.e2e.test_api_workflows.TestDLQNotFound::test_dlq_retry_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.aggregate_type, dead_letter_queue.aggregate_id, dead_letter_queue.event_type, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.payload_json, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('974b8344-1039-4115-9e19-9850454e3d2f'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e117a70>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 46. tests.e2e.test_api_workflows.TestDLQNotFound::test_dlq_resolve_nonexistent_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.aggregate_type, dead_letter_queue.aggregate_id, dead_letter_queue.event_type, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.payload_json, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('8f73a362-ce9b-4fc8-8c44-f013d30a5be4'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e7fdbd0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 47. tests.e2e.test_api_workflows.TestDLQWorkflows::test_dlq_full_workflow_seed_list_resolve
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail)
                VALUES
                    (:dlq_id::uuid, :original_event_id::uuid, $1, $2, $3)
                ]
[parameters: ('content.article.raw.v1', 'failed', 'simulated timeout')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10ecd1310>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 48. tests.e2e.test_api_workflows.TestDLQWorkflows::test_dlq_retry_workflow
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail, payload_json)
                VALUES
                    (:dlq_id::uuid, :original_event_id::uuid, $1, $2, $3,
                     :payload::jsonb)
                ]
[parameters: ('content.article.raw.v1', 'failed', 'simulated dispatch error')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e3475a0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 49. tests.e2e.test_api_workflows.TestDLQInputValidation::test_dlq_resolve_with_long_note_accepted
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail)
                VALUES
                    (:dlq_id::uuid, :original_event_id::uuid, $1, $2, $3)
                ]
[parameters: ('content.article.raw.v1', 'failed', 'simulated dispatch error')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e3e1690>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 50. tests.e2e.test_api_workflows.TestDLQInputValidation::test_dlq_list_pagination_params
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail)
                VALUES
                    (:dlq_id::uuid, :original_event_id::uuid, $1, $2, $3)
                ]
[parameters: ('content.article.raw.v1', 'failed', 'simulated dispatch error')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e42f060>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 51. tests.e2e.test_api_workflows.TestDLQInputValidation::test_dlq_list_offset_zero_is_valid
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM dead_letter_queue
WHERE dead_letter_queue.status = $1::VARCHAR]
[parameters: ('failed',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10dd4bf10>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e3e2500>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 52. tests.e2e.test_api_workflows::test_graph_stats_empty_db
- suite: knowledge-graph:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT
    (SELECT COUNT(*) FROM canonical_entities)            AS entity_count,
    (SELECT COUNT(*) FROM relations)                     AS relation_count,
    (SELECT COUNT(*) FROM relation_evidence_raw)         AS evidence_count,
    (SELECT COUNT(*) FROM relations WHERE confidence_stale = true)
                                                         AS stale_confidence_count,
    (SELECT COUNT(*) FROM relation_contradiction_links WHERE invalidated_at IS NULL)
                                                         AS contradiction_link_count
]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/knowledge-graph_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10d80c190>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 53. tests.e2e.test_api_workflows::test_relations_list_empty_db
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE ($1 IS NULL OR r.subject_entity_id = $1)
  AND ($2  IS NULL OR r.object_entity_id  = $2)
  AND ($3    IS NULL OR r.canonical_type    = $3)
  AND ($4     IS NULL OR r.semantic_mode     = $4)
  AND ($5    IS NULL OR r.confidence IS NULL OR r.confidence >= $5)
ORDER BY r.latest_evidence_at DESC
LIMIT $6 OFFSET $7
]
[parameters: (None, None, None, None, None, 100, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10d80fb50>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 54. tests.e2e.test_api_workflows::test_entity_graph_unknown_entity_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE entity_id = $1
]
[parameters: ('99f9bdee-445b-4698-8193-7a4b5cfab7a6',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dc82dc0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 55. tests.e2e.test_api_workflows::test_relations_list_with_valid_params
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE ($1 IS NULL OR r.subject_entity_id = $1)
  AND ($2  IS NULL OR r.object_entity_id  = $2)
  AND ($3    IS NULL OR r.canonical_type    = $3)
  AND ($4     IS NULL OR r.semantic_mode     = $4)
  AND ($5    IS NULL OR r.confidence IS NULL OR r.confidence >= $5)
ORDER BY r.latest_evidence_at DESC
LIMIT $6 OFFSET $7
]
[parameters: (None, None, None, None, None, 10, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dd14430>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 56. tests.e2e.test_api_workflows::test_relations_list_filtered_by_nonexistent_entity
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE ($1 IS NULL OR r.subject_entity_id = $1)
  AND ($2  IS NULL OR r.object_entity_id  = $2)
  AND ($3    IS NULL OR r.canonical_type    = $3)
  AND ($4     IS NULL OR r.semantic_mode     = $4)
  AND ($5    IS NULL OR r.confidence IS NULL OR r.confidence >= $5)
ORDER BY r.latest_evidence_at DESC
LIMIT $6 OFFSET $7
]
[parameters: ('e90df4c1-3caa-4a52-acee-a5dda6f35944', None, None, None, None, 100, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dd884a0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 57. tests.e2e.test_api_workflows::test_dlq_list_with_valid_token_returns_200
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT COUNT(*) FROM dead_letter_queue WHERE status = 'failed']
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dd27450>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 58. tests.e2e.test_api_workflows::test_dlq_get_nonexistent_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT dlq_id, original_event_id, topic, error_detail, status,
       created_at, resolved_at, resolution_note
FROM dead_letter_queue
WHERE dlq_id = $1
]
[parameters: ('e5522dd3-bb5b-4e61-b5cc-4d3e82588235',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10ddc5310>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 59. tests.e2e.test_api_workflows::test_dlq_resolve_nonexistent_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
UPDATE dead_letter_queue
SET status = 'resolved', resolved_at = $1, resolution_note = $2
WHERE dlq_id = $3 AND status = 'failed'
RETURNING dlq_id
]
[parameters: (datetime.datetime(2026, 3, 31, 8, 28, 35, 471785, tzinfo=datetime.timezone.utc), 'e2e resolution attempt', '81aada61-6ef2-4b1f-9729-0546d0539ee3')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10de07530>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 60. tests.e2e.test_api_workflows::test_entity_graph_with_seeded_entity
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
INSERT INTO canonical_entities (canonical_name, entity_type, ticker, exchange, metadata)
VALUES ($1, $2, $3, $4, :metadata::jsonb)
RETURNING entity_id
]
[parameters: ('E2E Corp', 'COMPANY', 'E2E', 'NASDAQ')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e5a22d0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 61. tests.e2e.test_api_workflows::test_entity_graph_min_confidence_boundary
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE entity_id = $1
]
[parameters: ('ec090746-ce0a-416c-9fae-e10e08f795a0',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e5fd070>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 62. tests.e2e.test_api_workflows::test_entity_graph_semantic_mode_filter
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
INSERT INTO canonical_entities (canonical_name, entity_type, metadata)
VALUES ($1, $2, :metadata::jsonb)
RETURNING entity_id
]
[parameters: ('SemanticMode Corp', 'COMPANY')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dd26960>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 63. tests.e2e.test_api_workflows::test_relations_semantic_mode_invalid_value
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
SELECT r.relation_id, r.subject_entity_id, r.object_entity_id,
       r.canonical_type, r.semantic_mode, r.decay_class,
       r.confidence, r.confidence_stale,
       r.evidence_count, r.first_evidence_at, r.latest_evidence_at
FROM relations r
WHERE ($1 IS NULL OR r.subject_entity_id = $1)
  AND ($2  IS NULL OR r.object_entity_id  = $2)
  AND ($3    IS NULL OR r.canonical_type    = $3)
  AND ($4     IS NULL OR r.semantic_mode     = $4)
  AND ($5    IS NULL OR r.confidence IS NULL OR r.confidence >= $5)
ORDER BY r.latest_evidence_at DESC
LIMIT $6 OFFSET $7
]
[parameters: (None, None, None, 'INVALID', None, 100, 0)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10d770040>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.11/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10dd8a340>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 64. tests.integration.test_e2e_pipeline.TestOHLCVPipeline::test_ohlcv_event_persists_bars_and_sets_flag
- suite: market-data:integration
- kind: failure
- reason: assert None is not None
- log: docs/testing/test-runs/20260331T082221Z/suites/market-data_integration.log
```text
self = <tests.integration.test_e2e_pipeline.TestOHLCVPipeline object at 0x10a539410>
_migrated_db = 'postgresql+asyncpg://postgres:postgres@localhost:54705/market_data_db'
    async def test_ohlcv_event_persists_bars_and_sets_flag(self, _migrated_db: str) -> None:
        """process_message → bars stored, has_ohlcv=True on instrument."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)
        storage = _make_storage_mock(_SAMPLE_OHLCV_JSONL)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-ohlcv",
            topics=["market.dataset.fetched"],
        )
        consumer = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=storage,
            config=config,
        )
        event = _make_event("ohlcv")
        # Inject UoW directly as the consumer accesses self._current_uow
```

### 65. tests.integration.test_e2e_pipeline.TestQuotesPipeline::test_quote_event_persists_quote
- suite: cross-service:e2e
- kind: failure
- reason: assert None is not None
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <tests.integration.test_e2e_pipeline.TestQuotesPipeline object at 0x10a53a650>
_migrated_db = 'postgresql+asyncpg://postgres:postgres@localhost:54705/market_data_db'
    async def test_quote_event_persists_quote(self, _migrated_db: str) -> None:
        """process_message → quote stored in DB."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)
        storage = _make_storage_mock(_SAMPLE_QUOTE_JSONL)
        # Mock Valkey client (cache invalidation, no real container needed)
        mock_valkey = MagicMock(spec=ValkeyClient)
        mock_valkey.delete = AsyncMock()
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-quotes",
            topics=["market.dataset.fetched"],
        )
        consumer = QuotesConsumer(
            uow_factory=uow_factory,
            object_storage=storage,
```

### 66. tests.integration.test_e2e_pipeline.TestInstrumentLifecycle::test_sequential_ingestion_sets_all_flags
- suite: cross-service:e2e
- kind: failure
- reason: assert None is not None
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <tests.integration.test_e2e_pipeline.TestInstrumentLifecycle object at 0x10a5395d0>
_migrated_db = 'postgresql+asyncpg://postgres:postgres@localhost:54705/market_data_db'
    async def test_sequential_ingestion_sets_all_flags(self, _migrated_db: str) -> None:
        """OHLCV then QUOTE ingest → instrument ends with both flags set."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from market_data.infrastructure.messaging.consumers.quotes_consumer import QuotesConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-lifecycle",
            topics=["market.dataset.fetched"],
        )
        # Step 1: OHLCV ingest
        ohlcv_consumer = OHLCVConsumer(
            uow_factory=uow_factory,
            object_storage=_make_storage_mock(_SAMPLE_OHLCV_JSONL),
            config=config,
        )
```

### 67. tests.integration.test_e2e_pipeline.TestPriorityResolutionE2E::test_high_priority_survives_low_priority_re_ingest
- suite: cross-service:e2e
- kind: failure
- reason: assert None is not None
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <tests.integration.test_e2e_pipeline.TestPriorityResolutionE2E object at 0x10a548190>
_migrated_db = 'postgresql+asyncpg://postgres:postgres@localhost:54705/market_data_db'
    async def test_high_priority_survives_low_priority_re_ingest(
        self,
        _migrated_db: str,
    ) -> None:
        """Polygon data (priority=100) must survive a Yahoo re-ingest (priority=80)."""
        from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer import OHLCVConsumer
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
        engine = create_async_engine(_migrated_db, echo=False)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(factory, factory)
        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test-priority",
            topics=["market.dataset.fetched"],
        )
        # Polygon bar: close=200.00
        polygon_jsonl = json.dumps(
            {
                "provider": "polygon",
                "symbol": "NVDA",
```

### 68. tests.e2e.test_api_workflows::test_readyz_db_ok
- suite: market-ingestion:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/market-ingestion_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:45:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
>       return await self.request(
            "GET",
            url,
            params=params,
```

### 69. tests.e2e.test_api_workflows::test_trigger_single_symbol_creates_task
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x10b4c5250>
>   ???
E   AssertionError: {"detail":"Invalid or missing internal token"}
E   assert 401 == 202
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:69: AssertionError
```

### 70. tests.e2e.test_api_workflows::test_trigger_multiple_symbols
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:90:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>, url = '/api/v1/ingest/trigger'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `POST` request.
        **Parameters**: See `httpx.request`.
        """
```

### 71. tests.e2e.test_api_workflows::test_trigger_idempotent
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
E   assert 401 == 202
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:115: AssertionError
```

### 72. tests.e2e.test_api_workflows::test_trigger_invalid_provider_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:128:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>, url = '/api/v1/ingest/trigger'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `POST` request.
        **Parameters**: See `httpx.request`.
        """
```

### 73. tests.e2e.test_api_workflows::test_backfill_90_days_produces_3_chunks
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
E   AssertionError: {"detail":"Invalid or missing internal token"}
E   assert 401 == 202
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:158: AssertionError
```

### 74. tests.e2e.test_api_workflows::test_backfill_single_day_one_chunk
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:168:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>
url = '/api/v1/ingest/backfill'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `POST` request.
        **Parameters**: See `httpx.request`.
```

### 75. tests.e2e.test_api_workflows::test_backfill_exceeds_max_chunks_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 422
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
E   AssertionError: {"detail":"Invalid or missing internal token"}
E   assert 401 == 422
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:198: AssertionError
```

### 76. tests.e2e.test_api_workflows::test_backfill_idempotent
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:213:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>
url = '/api/v1/ingest/backfill'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `POST` request.
        **Parameters**: See `httpx.request`.
```

### 77. tests.e2e.test_api_workflows::test_list_policies_returns_list
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:238:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>, url = '/api/v1/policies'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
>       return await self.request(
            "GET",
            url,
            params=params,
```

### 78. tests.e2e.test_api_workflows::test_trigger_then_status_reflects_pending_task
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
>   ???
E   assert 401 == 202
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:254: AssertionError
```

### 79. tests.e2e.test_api_workflows::test_trigger_full_async_pipeline_reaches_terminal_states
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x10b6b0150>
>   ???
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:272:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10b18fed0>, url = '/api/v1/ingest/trigger'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `POST` request.
        **Parameters**: See `httpx.request`.
```

### 80. tests.e2e.test_api_workflows::test_triggered_task_progresses_out_of_pending
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10b18fed0>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x11289ccd0>
>   ???
E   AssertionError: {"detail":"Invalid or missing internal token"}
E   assert 401 == 202
E    +  where 401 = <Response [401 Unauthorized]>.status_code
/Users/arnaurodon/Projects/University/Final Thesis/worldview/services/market-ingestion/tests/e2e/test_api_workflows.py:377: AssertionError
```

### 81. tests.e2e.test_api_workflows::test_triggered_task_progresses_out_of_pending
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "RuntimeError: Event loop is closed"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
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
future = <Task finished name='Task-38' coro=<_wrap_asyncgen_fixture.<locals>._asyncgen_fixture_wrapper.<locals>.finalizer.<loca...estion/.venv/lib/python3.11/site-packages/pytest_asyncio/plugin.py:331> exception=RuntimeError('Event loop is closed')>
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

### 82. tests.e2e.test_api_workflows::test_list_signals_empty_on_clean_db
- suite: nlp-pipeline:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM (SELECT outbox_events.event_id AS event_id, outbox_events.topic AS topic, outbox_events.partition_key AS partition_key, outbox_events.payload_avro AS payload_avro, outbox_events.status AS status, outbox_events.created_at AS created_at, outbox_events.dispatched_at AS dispatched_at, outbox_events.retry_count AS retry_count, outbox_events.failed_at AS failed_at
FROM outbox_events
WHERE outbox_events.topic = $1::VARCHAR ORDER BY outbox_events.created_at DESC) AS anon_1]
[parameters: ('nlp.signal.detected.v1',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/nlp-pipeline_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10de63ae0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 83. tests.e2e.test_api_workflows::test_list_signals_doc_id_filter_no_match
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM (SELECT outbox_events.event_id AS event_id, outbox_events.topic AS topic, outbox_events.partition_key AS partition_key, outbox_events.payload_avro AS payload_avro, outbox_events.status AS status, outbox_events.created_at AS created_at, outbox_events.dispatched_at AS dispatched_at, outbox_events.retry_count AS retry_count, outbox_events.failed_at AS failed_at
FROM outbox_events
WHERE outbox_events.topic = $1::VARCHAR AND outbox_events.partition_key = $2::VARCHAR ORDER BY outbox_events.created_at DESC) AS anon_1]
[parameters: ('nlp.signal.detected.v1', 'f3ce2a9c-a9d4-473e-bd3a-fbc0816d0b74')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10ecb0430>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 84. tests.e2e.test_api_workflows::test_search_entities_empty_on_clean_db
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM (SELECT entity_mentions.resolved_entity_id AS resolved_entity_id, entity_mentions.mention_text AS mention_text, entity_mentions.mention_class AS mention_class, count(entity_mentions.mention_id) AS mention_count
FROM entity_mentions
WHERE entity_mentions.resolved_entity_id IS NOT NULL AND entity_mentions.mention_text ILIKE $1::VARCHAR GROUP BY entity_mentions.resolved_entity_id, entity_mentions.mention_text, entity_mentions.mention_class) AS anon_1]
[parameters: ('%Apple%',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f0db140>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 85. tests.e2e.test_api_workflows::test_search_entities_missing_query_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM (SELECT entity_mentions.resolved_entity_id AS resolved_entity_id, entity_mentions.mention_text AS mention_text, entity_mentions.mention_class AS mention_class, count(entity_mentions.mention_id) AS mention_count
FROM entity_mentions
WHERE entity_mentions.resolved_entity_id IS NOT NULL GROUP BY entity_mentions.resolved_entity_id, entity_mentions.mention_text, entity_mentions.mention_class) AS anon_1]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f1e90e0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 86. tests.e2e.test_api_workflows::test_search_entities_empty_query_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM (SELECT entity_mentions.resolved_entity_id AS resolved_entity_id, entity_mentions.mention_text AS mention_text, entity_mentions.mention_class AS mention_class, count(entity_mentions.mention_id) AS mention_count
FROM entity_mentions
WHERE entity_mentions.resolved_entity_id IS NOT NULL GROUP BY entity_mentions.resolved_entity_id, entity_mentions.mention_text, entity_mentions.mention_class) AS anon_1]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10efe1cb0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 87. tests.e2e.test_api_workflows::test_vector_search_empty_db_returns_empty_hits
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            SELECT s.section_id, s.doc_id,
                   left(regexp_replace(s.doc_id::text, '-', ''), 40) AS snippet,
                   1.0 AS score
            FROM sections s
            WHERE s.doc_id IS NOT NULL
            LIMIT $1::INTEGER
            ]
[parameters: (10,)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e1bac00>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 88. tests.e2e.test_api_workflows::test_vector_search_defaults_applied
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            SELECT s.section_id, s.doc_id,
                   left(regexp_replace(s.doc_id::text, '-', ''), 40) AS snippet,
                   1.0 AS score
            FROM sections s
            WHERE s.doc_id IS NOT NULL
            LIMIT $1::INTEGER
            ]
[parameters: (10,)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e411230>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 89. tests.e2e.test_api_workflows::test_get_entity_not_found_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: Neither 'Function' object nor 'Comparator' object has an attribute '_isnull'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <sqlalchemy.sql.functions.Function at 0x10e3e93a0; Integer>
key = '_isnull'
    def __getattr__(self, key: str) -> Any:
        try:
>           return getattr(self.comparator, key)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           AttributeError: 'Comparator' object has no attribute '_isnull'
.venv/lib/python3.12/site-packages/sqlalchemy/sql/elements.py:1463: AttributeError
The above exception was the direct cause of the following exception:
e2e_client = <httpx.AsyncClient object at 0x10e1ad730>
    async def test_get_entity_not_found_returns_404(e2e_client: AsyncClient) -> None:
        """GET /api/v1/entities/{id} with unknown entity returns 404."""
        unknown_id = uuid.uuid4()
>       resp = await e2e_client.get(f"/api/v1/entities/{unknown_id}")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_api_workflows.py:272:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10e1ad730>
url = '/api/v1/entities/2efe045e-3769-46fe-8290-9024e79f9929'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
```

### 90. tests.e2e.test_api_workflows::test_get_entity_articles_not_found_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT entity_mentions.doc_id, routing_decisions.routing_tier, routing_decisions.decided_at, count(entity_mentions.mention_id) AS mention_count
FROM entity_mentions JOIN routing_decisions ON routing_decisions.doc_id = entity_mentions.doc_id
WHERE entity_mentions.resolved_entity_id = $1::UUID GROUP BY entity_mentions.doc_id, routing_decisions.routing_tier, routing_decisions.decided_at ORDER BY routing_decisions.decided_at DESC
 LIMIT $2::INTEGER]
[parameters: (UUID('78ec2598-b573-4717-a7c5-d07586fe2ef4'), 20)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e419230>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 91. tests.e2e.test_api_workflows::test_reprocess_unknown_article_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT routing_decisions.decision_id, routing_decisions.doc_id, routing_decisions.routing_tier, routing_decisions.final_routing_tier, routing_decisions.composite_score, routing_decisions.feature_scores_json, routing_decisions.decided_at
FROM routing_decisions
WHERE routing_decisions.doc_id = $1::UUID
 LIMIT $2::INTEGER]
[parameters: (UUID('4a98f9cc-9c12-40da-8a94-9d05d495a100'), 1)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x11013b760>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 92. tests.e2e.test_api_workflows::test_dlq_list_empty_on_clean_db
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT count(*) AS count_1
FROM dead_letter_queue
WHERE dead_letter_queue.status = $1::VARCHAR]
[parameters: ('failed',)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e783990>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 93. tests.e2e.test_api_workflows::test_dlq_get_unknown_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('5baf0aee-9f80-4f7a-aec0-c2d0ed724701'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10ed1c270>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 94. tests.e2e.test_api_workflows::test_dlq_resolve_unknown_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('748e4636-3df6-41cd-abf5-d47a80a23b17'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f22e5e0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 95. tests.e2e.test_api_workflows::test_dlq_retry_unknown_entry_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL: SELECT dead_letter_queue.dlq_id, dead_letter_queue.original_event_id, dead_letter_queue.topic, dead_letter_queue.payload_avro, dead_letter_queue.error_detail, dead_letter_queue.status, dead_letter_queue.created_at, dead_letter_queue.resolved_at, dead_letter_queue.resolution_note
FROM dead_letter_queue
WHERE dead_letter_queue.dlq_id = $1::UUID]
[parameters: (UUID('70edd001-c67e-4a3f-aedc-c76155f3c61e'),)]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f17e730>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 96. tests.e2e.test_api_workflows::test_dlq_seeded_entry_is_listable
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_bytes, error_detail, status, created_at)
            VALUES
                ($1, $2, 'nlp.dead-letter.v1', E'\\x00'::bytea,
                 'parse error: unexpected null field', 'failed', now())
        ]
[parameters: ('3d32d4a9-c5fd-444c-87eb-703ec5a3a841', '34c3eab5-d42a-4fbf-8aa9-2a0f00c3b126')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f1e6880>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 97. tests.e2e.test_api_workflows::test_dlq_resolve_seeded_entry
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_bytes, error_detail, status, created_at)
            VALUES
                ($1, $2, 'nlp.dead-letter.v1', E'\\x00'::bytea,
                 'schema mismatch', 'failed', now())
        ]
[parameters: ('cff00982-c0f5-495a-91be-6becb522939f', 'e529191c-5676-4595-b86a-5166481db3f0')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10f226a40>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 98. tests.e2e.test_api_workflows::test_dlq_resolution_note_max_length_enforced
- suite: cross-service:e2e
- kind: failure
- reason: sqlalchemy.exc.InterfaceError: (sqlalchemy.dialects.postgresql.asyncpg.InterfaceError) <class 'asyncpg.exceptions._base.InterfaceError'>: cannot perform operation: another operation is in progress
[SQL:
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_bytes, status, created_at)
            VALUES ($1, $2, 'test', E'\\x00'::bytea, 'failed', now())
        ]
[parameters: ('0335347e-3ab8-4c89-95d9-1feb5671bbab', '5ca45fef-6add-4a6d-8e0f-14025cbc3794')]
(Background on this error at: https://sqlalche.me/e/20/rvf5)
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
self = <AdaptedConnection <asyncpg.connection.Connection object at 0x10e13af30>>
    async def _start_transaction(self):
        if self.isolation_level == "autocommit":
            return
        try:
            self._transaction = self._connection.transaction(
                isolation=self.isolation_level,
                readonly=self.readonly,
                deferrable=self.deferrable,
            )
>           await self._transaction.start()
.venv/lib/python3.12/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:755:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <asyncpg.Transaction state:failed read_committed 0x10e81a8f0>
    @connresource.guarded
    async def start(self):
        """Enter the transaction or savepoint block."""
        self.__check_state_base('start')
        if self._state is TransactionState.STARTED:
            raise apg_errors.InterfaceError(
                'cannot start; the transaction is already started')
        con = self._connection
        if con._top_xact is None:
            if con._protocol.is_in_transaction():
                raise apg_errors.InterfaceError(
```

### 99. tests.integration.test_alert_preferences_api::test_get_alert_preferences_returns_200_with_defaults
- suite: portfolio:integration
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/portfolio_integration.log
```text
integration_client = <httpx.AsyncClient object at 0x11286b210>
    async def test_get_alert_preferences_returns_200_with_defaults(integration_client) -> None:
        """GET /alert-preferences returns 200 with all alert types defaulting to enabled."""
>       tenant = await make_tenant(integration_client, name="APTenant1")
tests/integration/test_alert_preferences_api.py:16:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x11286b210>, name = 'APTenant1'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 100. tests.integration.test_alert_preferences_api::test_put_preference_returns_200
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x1129501d0>
    async def test_put_preference_returns_200(integration_client) -> None:
        """PUT /alert-preferences/{alert_type} updates the preference."""
>       tenant = await make_tenant(integration_client, name="APTenant2")
tests/integration/test_alert_preferences_api.py:34:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129501d0>, name = 'APTenant2'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 101. tests.integration.test_alert_preferences_api::test_put_invalid_alert_type_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x1129cb450>
    async def test_put_invalid_alert_type_returns_422(integration_client) -> None:
        """PUT /alert-preferences/{alert_type} with unknown type returns 422."""
>       tenant = await make_tenant(integration_client, name="APTenant3")
tests/integration/test_alert_preferences_api.py:50:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129cb450>, name = 'APTenant3'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 102. tests.integration.test_alert_preferences_api::test_post_suppression_returns_201
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112a46ed0>
    async def test_post_suppression_returns_201(integration_client) -> None:
        """POST /alert-preferences/suppressions creates entity suppression."""
>       tenant = await make_tenant(integration_client, name="APTenant4")
tests/integration/test_alert_preferences_api.py:63:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a46ed0>, name = 'APTenant4'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 103. tests.integration.test_alert_preferences_api::test_delete_suppression_returns_204
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112ad7050>
    async def test_delete_suppression_returns_204(integration_client) -> None:
        """DELETE /alert-preferences/suppressions/{entity_id} removes suppression."""
>       tenant = await make_tenant(integration_client, name="APTenant5")
tests/integration/test_alert_preferences_api.py:79:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112ad7050>, name = 'APTenant5'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 104. tests.integration.test_alert_preferences_api::test_delete_suppression_not_found_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112b56150>
    async def test_delete_suppression_not_found_returns_404(integration_client) -> None:
        """DELETE /alert-preferences/suppressions/{entity_id} for missing entity → 404."""
>       tenant = await make_tenant(integration_client, name="APTenant6")
tests/integration/test_alert_preferences_api.py:99:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112b56150>, name = 'APTenant6'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 105. tests.integration.test_holding_api::test_holdings_empty_before_transaction
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112bc1650>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112bd7150>
    async def test_holdings_empty_before_transaction(integration_client, db_session) -> None:
        """GET /api/v1/holdings/{portfolio_id} returns empty list before any transaction."""
>       tenant = await make_tenant(integration_client, name="HoldCo")
tests/integration/test_holding_api.py:18:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112bc1650>, name = 'HoldCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 106. tests.integration.test_holding_api::test_holdings_updated_after_buy
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112bd6c90>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112c609d0>
    async def test_holdings_updated_after_buy(integration_client, db_session) -> None:
        """After BUY transaction, GET holdings shows updated quantity and avg_cost."""
>       tenant = await make_tenant(integration_client, name="BuyHoldCo")
tests/integration/test_holding_api.py:32:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112bd6c90>, name = 'BuyHoldCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 107. tests.integration.test_holding_api::test_holdings_cross_tenant_denied
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112bc0b10>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112bbb990>
    async def test_holdings_cross_tenant_denied(integration_client, db_session) -> None:
        """GET holdings with wrong tenant returns 403/404."""
>       tenant1 = await make_tenant(integration_client, name="HTenant1")
tests/integration/test_holding_api.py:67:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112bc0b10>, name = 'HTenant1'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 108. tests.integration.test_portfolio_api::test_create_portfolio_happy_path
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x1129a0b10>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x1129a2210>
    async def test_create_portfolio_happy_path(integration_client, db_session) -> None:
        """POST /api/v1/portfolios creates a portfolio record."""
>       tenant = await make_tenant(integration_client, name="PortCo")
tests/integration/test_portfolio_api.py:16:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129a0b10>, name = 'PortCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 109. tests.integration.test_portfolio_api::test_list_portfolios_scoped_to_owner
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x11292a450>
    async def test_list_portfolios_scoped_to_owner(integration_client) -> None:
        """GET /api/v1/portfolios returns only portfolios for the given owner."""
>       tenant = await make_tenant(integration_client, name="ListCo")
tests/integration/test_portfolio_api.py:37:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x11292a450>, name = 'ListCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 110. tests.integration.test_portfolio_api::test_get_portfolio_happy_path
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112813250>
    async def test_get_portfolio_happy_path(integration_client) -> None:
        """GET /api/v1/portfolios/{id} returns the portfolio."""
>       tenant = await make_tenant(integration_client, name="GetPortCo")
tests/integration/test_portfolio_api.py:60:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112813250>, name = 'GetPortCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 111. tests.integration.test_portfolio_api::test_get_portfolio_cross_tenant_denied
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112952f50>
    async def test_get_portfolio_cross_tenant_denied(integration_client) -> None:
        """GET /api/v1/portfolios/{id} with wrong tenant_id returns 403/404."""
>       tenant1 = await make_tenant(integration_client, name="Tenant1")
tests/integration/test_portfolio_api.py:75:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112952f50>, name = 'Tenant1'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 112. tests.integration.test_portfolio_api::test_rename_portfolio
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112d18dd0>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112d30fd0>
    async def test_rename_portfolio(integration_client, db_session) -> None:
        """PUT /api/v1/portfolios/{id} renames the portfolio."""
>       tenant = await make_tenant(integration_client, name="RenameCo")
tests/integration/test_portfolio_api.py:90:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112d18dd0>, name = 'RenameCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 113. tests.integration.test_portfolio_api::test_rename_portfolio_wrong_owner_denied
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112d7d4d0>
    async def test_rename_portfolio_wrong_owner_denied(integration_client) -> None:
        """PUT /api/v1/portfolios/{id} by wrong owner returns 403."""
>       tenant = await make_tenant(integration_client, name="AuthCo")
tests/integration/test_portfolio_api.py:107:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112d7d4d0>, name = 'AuthCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 114. tests.integration.test_portfolio_api::test_archive_portfolio
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112e1b050>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112e2b1d0>
    async def test_archive_portfolio(integration_client, db_session) -> None:
        """DELETE /api/v1/portfolios/{id} archives the portfolio (204)."""
>       tenant = await make_tenant(integration_client, name="ArchiveCo")
tests/integration/test_portfolio_api.py:122:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112e1b050>, name = 'ArchiveCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 115. tests.integration.test_tenant_api::test_create_tenant_creates_record
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112d09d90>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112d08710>
    async def test_create_tenant_creates_record(integration_client, db_session) -> None:
        """POST /api/v1/tenants creates a tenant record in the DB."""
        resp = await integration_client.post("/api/v1/tenants", json={"name": "ACME Corp"})
>       assert resp.status_code == 201
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/integration/test_tenant_api.py:15: AssertionError
```

### 116. tests.integration.test_tenant_api::test_create_tenant_emits_outbox_event
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112a9b190>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112869650>
    async def test_create_tenant_emits_outbox_event(integration_client, db_session) -> None:
        """POST /api/v1/tenants emits a tenant.created outbox event."""
        resp = await integration_client.post("/api/v1/tenants", json={"name": "OutboxCo"})
>       assert resp.status_code == 201
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/integration/test_tenant_api.py:25: AssertionError
```

### 117. tests.integration.test_tenant_api::test_get_tenant_returns_correct_data
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x1128fc490>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x1128fc310>
    async def test_get_tenant_returns_correct_data(integration_client, db_session) -> None:
        """GET /api/v1/tenants/{id} returns the correct tenant data."""
>       tenant = await make_tenant(integration_client, name="GetMe Corp")
tests/integration/test_tenant_api.py:32:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1128fc490>, name = 'GetMe Corp'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 118. tests.integration.test_tenant_api::test_get_tenant_not_found
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 404
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112a00e90>
    async def test_get_tenant_not_found(integration_client) -> None:
        """GET /api/v1/tenants/{id} returns 404 for unknown tenant."""
        import uuid
        resp = await integration_client.get(f"/api/v1/tenants/{uuid.uuid4()}")
>       assert resp.status_code == 404
E       assert 401 == 404
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/integration/test_tenant_api.py:47: AssertionError
```

### 119. tests.integration.test_transaction_api::test_buy_transaction_creates_records
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112ac9fd0>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112ac9390>
    async def test_buy_transaction_creates_records(integration_client, db_session) -> None:
        """POST /api/v1/transactions (BUY) creates transaction + holding + outbox events."""
>       tenant = await make_tenant(integration_client, name="TxCo")
tests/integration/test_transaction_api.py:18:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112ac9fd0>, name = 'TxCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 120. tests.integration.test_transaction_api::test_idempotency_replay_no_duplicate
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112a587d0>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112a5a990>
    async def test_idempotency_replay_no_duplicate(integration_client, db_session) -> None:
        """Two requests with the same Idempotency-Key produce only one transaction + outbox event."""
>       tenant = await make_tenant(integration_client, name="IdemCo")
tests/integration/test_transaction_api.py:51:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a587d0>, name = 'IdemCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 121. tests.integration.test_transaction_api::test_list_transactions
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112b78110>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112b7b550>
    async def test_list_transactions(integration_client, db_session) -> None:
        """GET /api/v1/transactions returns all transactions for a portfolio."""
>       tenant = await make_tenant(integration_client, name="ListTxCo")
tests/integration/test_transaction_api.py:90:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112b78110>, name = 'ListTxCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 122. tests.integration.test_transaction_api::test_transaction_requires_positive_quantity
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112c0e090>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112c21890>
    async def test_transaction_requires_positive_quantity(integration_client, db_session) -> None:
        """POST /api/v1/transactions with quantity=0 returns 422."""
>       tenant = await make_tenant(integration_client, name="ValCo")
tests/integration/test_transaction_api.py:126:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112c0e090>, name = 'ValCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 123. tests.integration.test_transaction_api::test_transaction_requires_positive_price
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112b5c950>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112b5c4d0>
    async def test_transaction_requires_positive_price(integration_client, db_session) -> None:
        """POST /api/v1/transactions with price=0 returns 422."""
>       tenant = await make_tenant(integration_client, name="PriceCo")
tests/integration/test_transaction_api.py:150:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112b5c950>, name = 'PriceCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 124. tests.integration.test_user_api::test_create_user_happy_path
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112c04850>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112c05a10>
    async def test_create_user_happy_path(integration_client, db_session) -> None:
        """POST /api/v1/users creates a user under an active tenant."""
>       tenant = await make_tenant(integration_client, name="UserCo")
tests/integration/test_user_api.py:14:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112c04850>, name = 'UserCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 125. tests.integration.test_user_api::test_create_user_emits_outbox_event
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112912690>
db_session = <sqlalchemy.orm.session.AsyncSession object at 0x112bcc650>
    async def test_create_user_emits_outbox_event(integration_client, db_session) -> None:
        """POST /api/v1/users emits a user.created outbox event."""
>       tenant = await make_tenant(integration_client, name="EventCo")
tests/integration/test_user_api.py:30:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112912690>, name = 'EventCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 126. tests.integration.test_user_api::test_create_user_duplicate_email_returns_409
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x112ba8590>
    async def test_create_user_duplicate_email_returns_409(integration_client) -> None:
        """POST /api/v1/users returns 409 on duplicate email within same tenant."""
>       tenant = await make_tenant(integration_client, name="DupCo")
tests/integration/test_user_api.py:40:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112ba8590>, name = 'DupCo'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 127. tests.integration.test_user_api::test_get_user_happy_path
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x1129cb550>
    async def test_get_user_happy_path(integration_client) -> None:
        """GET /api/v1/users/{id} returns the user."""
>       tenant = await make_tenant(integration_client)
tests/integration/test_user_api.py:54:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129cb550>, name = 'Test Tenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 128. tests.integration.test_user_api::test_get_user_not_found
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
integration_client = <httpx.AsyncClient object at 0x11283d9d0>
    async def test_get_user_not_found(integration_client) -> None:
        """GET /api/v1/users/{id} returns 404 for unknown user."""
        import uuid
>       tenant = await make_tenant(integration_client)
tests/integration/test_user_api.py:72:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x11283d9d0>, name = 'Test Tenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 129. tests.integration.test_watchlist_api::test_create_watchlist_returns_201
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x1129cf290>
    async def test_create_watchlist_returns_201(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client)
tests/integration/test_watchlist_api.py:94:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129cf290>, name = 'Test Tenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 130. tests.integration.test_watchlist_api::test_create_watchlist_duplicate_name_returns_409
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112dbc450>
    async def test_create_watchlist_duplicate_name_returns_409(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="DupTenant")
tests/integration/test_watchlist_api.py:110:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112dbc450>, name = 'DupTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 131. tests.integration.test_watchlist_api::test_list_watchlists_returns_user_watchlists_only
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112b37550>
    async def test_list_watchlists_returns_user_watchlists_only(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="ListTenant")
tests/integration/test_watchlist_api.py:123:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112b37550>, name = 'ListTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 132. tests.integration.test_watchlist_api::test_get_watchlist_returns_200
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112a9de50>
    async def test_get_watchlist_returns_200(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="GetTenant")
tests/integration/test_watchlist_api.py:141:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a9de50>, name = 'GetTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 133. tests.integration.test_watchlist_api::test_get_watchlist_not_found_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112e34e50>
    async def test_get_watchlist_not_found_returns_404(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="NotFoundTenant")
tests/integration/test_watchlist_api.py:154:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112e34e50>, name = 'NotFoundTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 134. tests.integration.test_watchlist_api::test_get_watchlist_wrong_owner_returns_403
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112d6cfd0>
    async def test_get_watchlist_wrong_owner_returns_403(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="AuthTenant")
tests/integration/test_watchlist_api.py:165:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112d6cfd0>, name = 'AuthTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 135. tests.integration.test_watchlist_api::test_delete_watchlist_returns_204
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112d117d0>
    async def test_delete_watchlist_returns_204(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="DelTenant")
tests/integration/test_watchlist_api.py:178:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112d117d0>, name = 'DelTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 136. tests.integration.test_watchlist_api::test_add_member_returns_201
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112a989d0>
    async def test_add_member_returns_201(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="MemberTenant")
tests/integration/test_watchlist_api.py:190:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a989d0>, name = 'MemberTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 137. tests.integration.test_watchlist_api::test_add_member_duplicate_returns_409
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x1129ec2d0>
    async def test_add_member_duplicate_returns_409(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="DupMemberTenant")
tests/integration/test_watchlist_api.py:207:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1129ec2d0>, name = 'DupMemberTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 138. tests.integration.test_watchlist_api::test_remove_member_returns_204
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112a5a810>
    async def test_remove_member_returns_204(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="RemoveTenant")
tests/integration/test_watchlist_api.py:223:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a5a810>, name = 'RemoveTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 139. tests.integration.test_watchlist_api::test_remove_member_not_found_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
watchlist_client = <httpx.AsyncClient object at 0x112e3b750>
    async def test_remove_member_not_found_returns_404(watchlist_client: AsyncClient) -> None:
>       tenant = await make_tenant(watchlist_client, name="RemoveNFTenant")
tests/integration/test_watchlist_api.py:238:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112e3b750>, name = 'RemoveNFTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 140. tests.integration.test_watchlist_reverse_index::test_add_member_invalidates_cache
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
cache_client = (<httpx.AsyncClient object at 0x11288e890>, <portfolio.infrastructure.cache.watchlist_cache.ValkeyWatchlistCache object at 0x112bcd350>)
    async def test_add_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
        """After add_member, the reverse-index key is absent (was invalidated)."""
        client, cache = cache_client
>       tenant = await make_tenant(client, name="RITenant")
tests/integration/test_watchlist_reverse_index.py:66:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x11288e890>, name = 'RITenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 141. tests.integration.test_watchlist_reverse_index::test_remove_member_invalidates_cache
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
cache_client = (<httpx.AsyncClient object at 0x112a1e190>, <portfolio.infrastructure.cache.watchlist_cache.ValkeyWatchlistCache object at 0x112ca33d0>)
    async def test_remove_member_invalidates_cache(cache_client) -> None:  # type: ignore[no-untyped-def]
        """After remove_member, the reverse-index key is absent (was invalidated)."""
        client, cache = cache_client
>       tenant = await make_tenant(client, name="RIRmTenant")
tests/integration/test_watchlist_reverse_index.py:99:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x112a1e190>, name = 'RIRmTenant'
    async def make_tenant(client: AsyncClient, name: str = "Test Tenant") -> dict[str, Any]:
        """POST /api/v1/tenants and return the response JSON."""
        resp = await client.post("/api/v1/tenants", json={"name": name})
>       assert resp.status_code == 201, f"create_tenant failed: {resp.text}"
E       AssertionError: create_tenant failed: {"detail":"Invalid or missing internal token"}
tests/integration/helpers.py:40: AssertionError
```

### 142. tests.e2e.test_full_flow::test_full_transaction_flow
- suite: portfolio:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/portfolio_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x10977eb10>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x1096de510>
    async def test_full_transaction_flow(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
        """Happy-path: create tenant/user/portfolio, BUY, SELL, verify holdings and transactions."""
        # 1. Create tenant
        resp = await e2e_client.post("/api/v1/tenants", json={"name": f"FlowCo-{uuid.uuid4().hex[:6]}"})
>       assert resp.status_code == 201, resp.text
E       AssertionError: {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_full_flow.py:35: AssertionError
```

### 143. tests.e2e.test_full_flow::test_create_tenant_returns_valid_id
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x109cc50d0>
    async def test_create_tenant_returns_valid_id(e2e_client: AsyncClient) -> None:
        """POST /tenants returns 201 with a UUID id field."""
        resp = await e2e_client.post("/api/v1/tenants", json={"name": f"IdCheck-{uuid.uuid4().hex[:6]}"})
>       assert resp.status_code == 201, resp.text
E       AssertionError: {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_full_flow.py:161: AssertionError
```

### 144. tests.e2e.test_full_flow::test_duplicate_portfolio_name_rejected
- suite: cross-service:e2e
- kind: failure
- reason: KeyError: 'id'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x1099f3290>
    async def test_duplicate_portfolio_name_rejected(e2e_client: AsyncClient) -> None:
        """POST /portfolios with duplicate name for same owner returns 409 or 422."""
        resp = await e2e_client.post("/api/v1/tenants", json={"name": f"DupCo-{uuid.uuid4().hex[:6]}"})
>       tenant_id = resp.json()["id"]
E       KeyError: 'id'
tests/e2e/test_full_flow.py:170: KeyError
```

### 145. tests.e2e.test_full_flow::test_sell_exceeding_holdings_rejected
- suite: cross-service:e2e
- kind: failure
- reason: KeyError: 'id'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x109cc5110>
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x109cd2110>
    async def test_sell_exceeding_holdings_rejected(e2e_client: AsyncClient, e2e_db_session: AsyncSession) -> None:
        """SELL more than held quantity returns 409 or 422 (InsufficientHoldingsError)."""
        resp = await e2e_client.post("/api/v1/tenants", json={"name": f"SellCo-{uuid.uuid4().hex[:6]}"})
>       tenant_id = resp.json()["id"]
E       KeyError: 'id'
tests/e2e/test_full_flow.py:198: KeyError
```

### 146. tests.e2e.test_full_flow::test_archive_portfolio
- suite: cross-service:e2e
- kind: failure
- reason: KeyError: 'id'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_client = <httpx.AsyncClient object at 0x109ce75d0>
    async def test_archive_portfolio(e2e_client: AsyncClient) -> None:
        """DELETE /portfolios/{id} transitions portfolio to ARCHIVED status."""
        resp = await e2e_client.post("/api/v1/tenants", json={"name": f"ArchCo-{uuid.uuid4().hex[:6]}"})
>       tenant_id = resp.json()["id"]
E       KeyError: 'id'
tests/e2e/test_full_flow.py:248: KeyError
```

### 147. tests.e2e.test_instrument_sync::test_instrument_consumer_upserts_instrument
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'InstrumentEventConsumer' object has no attribute '_current_uow'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x109c75890>
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

### 148. tests.e2e.test_instrument_sync::test_instrument_consumer_idempotent
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: 'InstrumentEventConsumer' object has no attribute '_current_uow'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
e2e_db_session = <sqlalchemy.orm.session.AsyncSession object at 0x109c6c210>
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
self = <portfolio.infrastructure.messaging.consumers.instrument_consumer.InstrumentEventConsumer object at 0x109c6fe90>
key = 'IDEM_E184'
value = {'event_id': 'e1845fee-444b-495f-837e-3c634c1d19e9', 'exchange': 'NYSE', 'symbol': 'IDEM_E184'}
```

### 149. tests.e2e.test_content_pipeline::test_s4_readyz
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_readyz(s4_client: AsyncClient) -> None:
        """S4 /readyz returns 200 or 503 (depends on Kafka/MinIO availability)."""
>       resp = await s4_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_content_pipeline.py:126:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 150. tests.e2e.test_content_pipeline::test_s5_readyz
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s5_client = <httpx.AsyncClient object at 0x1085fb260>
    @_skip_s5
    async def test_s5_readyz(s5_client: AsyncClient) -> None:
        """S5 /readyz returns 200 or 503."""
>       resp = await s5_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_content_pipeline.py:144:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085fb260>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 151. tests.e2e.test_content_pipeline::test_s4_admin_create_eodhd_source
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_admin_create_eodhd_source(s4_client: AsyncClient) -> None:
        """S4 admin API: create an EODHD news source and verify it appears in list."""
        unique_name = f"e2e-eodhd-{uuid.uuid4().hex[:8]}"
>       resp = await s4_client.post(
            "/api/v1/sources",
            json={
                "name": unique_name,
                "source_type": "eodhd",
                "config": {
                    "symbols": ["AAPL", "MSFT", "GOOGL"],
                    "lookback_days": 7,
                },
                "enabled": True,
            },
            headers=_s4_admin_headers(),
        )
tests/e2e/test_content_pipeline.py:162:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
```

### 152. tests.e2e.test_content_pipeline::test_s4_admin_create_source_duplicate_name_returns_409
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_admin_create_source_duplicate_name_returns_409(s4_client: AsyncClient) -> None:
        """Creating a source with a duplicate name returns 409 Conflict."""
        unique_name = f"e2e-dup-{uuid.uuid4().hex[:8]}"
        body = {"name": unique_name, "source_type": "finnhub", "config": {}, "enabled": True}
        resp1 = await s4_client.post("/api/v1/sources", json=body, headers=_s4_admin_headers())
>       assert resp1.status_code == 201
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_content_pipeline.py:198: AssertionError
```

### 153. tests.e2e.test_content_pipeline::test_s4_admin_create_source_invalid_type_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_admin_create_source_invalid_type_returns_422(s4_client: AsyncClient) -> None:
        """Creating a source with unknown source_type returns 422."""
>       resp = await s4_client.post(
            "/api/v1/sources",
            json={"name": f"bad-{uuid.uuid4().hex[:6]}", "source_type": "invalid_provider", "config": {}, "enabled": True},
            headers=_s4_admin_headers(),
        )
tests/e2e/test_content_pipeline.py:207:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>, url = '/api/v1/sources'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
```

### 154. tests.e2e.test_content_pipeline::test_s4_internal_submit_raw_content
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_raw_content(s4_client: AsyncClient) -> None:
        """POST /internal/v1/ingest/submit with raw_content returns accepted or duplicate."""
        unique_url = f"https://news.example.com/article/{uuid.uuid4().hex}"
        resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "url": unique_url,
                "source_type": "newsapi",
                "title": "E2E Test Article",
                "raw_content": "Apple reports record quarterly earnings for Q1 2026.",
                "published_at": datetime.now(tz=UTC).isoformat(),
            },
            headers=_internal_headers(),
        )
>       assert resp.status_code == 202
E       assert 401 == 202
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_content_pipeline.py:233: AssertionError
```

### 155. tests.e2e.test_content_pipeline::test_s4_internal_submit_duplicate_url_returns_duplicate
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_duplicate_url_returns_duplicate(s4_client: AsyncClient) -> None:
        """Submitting the same URL twice: second submission returns status=duplicate."""
        unique_url = f"https://news.example.com/dedup-test/{uuid.uuid4().hex}"
        body = {
            "url": unique_url,
            "source_type": "eodhd",
            "title": "Dedup Test",
            "raw_content": "First submission content.",
            "published_at": datetime.now(tz=UTC).isoformat(),
        }
>       resp1 = await s4_client.post("/internal/v1/ingest/submit", json=body, headers=_internal_headers())
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_content_pipeline.py:250:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>
url = '/internal/v1/ingest/submit'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
```

### 156. tests.e2e.test_content_pipeline::test_s4_internal_submit_ssrf_localhost_rejected
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 422
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_ssrf_localhost_rejected(s4_client: AsyncClient) -> None:
        """POST /internal/v1/ingest/submit with a localhost URL is rejected (SSRF prevention)."""
        resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "url": "http://localhost/internal/secrets",
                "source_type": "newsapi",
                "title": "SSRF test",
                "raw_content": "Content",
                "published_at": datetime.now(tz=UTC).isoformat(),
            },
            headers=_internal_headers(),
        )
>       assert resp.status_code == 422
E       assert 401 == 422
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_content_pipeline.py:276: AssertionError
```

### 157. tests.e2e.test_content_pipeline::test_s4_internal_submit_private_ip_rejected
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_private_ip_rejected(s4_client: AsyncClient) -> None:
        """POST /internal/v1/ingest/submit with a private RFC1918 URL is rejected."""
>       resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "url": "http://192.168.1.1/private",
                "source_type": "newsapi",
                "title": "SSRF private IP",
                "raw_content": "Should be rejected",
                "published_at": datetime.now(tz=UTC).isoformat(),
            },
            headers=_internal_headers(),
        )
tests/e2e/test_content_pipeline.py:282:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>
url = '/internal/v1/ingest/submit'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
```

### 158. tests.e2e.test_content_pipeline::test_s4_internal_submit_both_url_and_raw_content_accepted
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_both_url_and_raw_content_accepted(s4_client: AsyncClient) -> None:
        """POST with both url and raw_content should be accepted (url used for dedup)."""
>       resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "url": f"https://news.example.com/both/{uuid.uuid4().hex}",
                "source_type": "finnhub",
                "title": "Both fields test",
                "raw_content": "Content from Finnhub API feed.",
                "published_at": datetime.now(tz=UTC).isoformat(),
            },
            headers=_internal_headers(),
        )
tests/e2e/test_content_pipeline.py:315:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>
url = '/internal/v1/ingest/submit'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
```

### 159. tests.e2e.test_content_pipeline::test_s4_internal_submit_missing_required_fields_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 422
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_internal_submit_missing_required_fields_returns_422(s4_client: AsyncClient) -> None:
        """POST with missing source_type returns 422."""
        resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={"url": "https://news.example.com/test", "title": "No source type"},
            headers=_internal_headers(),
        )
>       assert resp.status_code == 422
E       assert 401 == 422
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_content_pipeline.py:337: AssertionError
```

### 160. tests.e2e.test_content_pipeline::test_s4_admin_pipeline_status
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
    @_skip_s4
    async def test_s4_admin_pipeline_status(s4_client: AsyncClient) -> None:
        """GET /api/v1/status returns pipeline health metrics."""
>       resp = await s4_client.get("/api/v1/status", headers=_s4_admin_headers())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_content_pipeline.py:346:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085f8350>, url = '/api/v1/status'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 161. tests.e2e.test_content_pipeline::test_s5_dlq_list_empty
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s5_client = <httpx.AsyncClient object at 0x1085fb260>
    @_skip_s5
    async def test_s5_dlq_list_empty(s5_client: AsyncClient) -> None:
        """GET /admin/dlq on fresh stack returns empty list."""
>       resp = await s5_client.get("/admin/dlq", headers=_s5_admin_headers())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_content_pipeline.py:365:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085fb260>, url = '/admin/dlq'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 162. tests.e2e.test_content_pipeline::test_content_pipeline_article_stored_within_timeout
- suite: cross-service:e2e
- kind: failure
- reason: assert 401 == 202
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s4_client = <httpx.AsyncClient object at 0x1085f8350>
s5_client = <httpx.AsyncClient object at 0x1085fb260>
    @_skip_s4_s5
    async def test_content_pipeline_article_stored_within_timeout(
        s4_client: AsyncClient,
        s5_client: AsyncClient,
    ) -> None:
        """Submit article via S4 and wait for S5 to store the canonical document.
        This test exercises the full pipeline:
          S4 submit → content.article.raw.v1 → S5 consumer → content.article.stored.v1
        The test polls the S5 stats endpoint every 2 seconds (up to 60 seconds)
        to detect when the document count increases after submission.
        Note: Requires Kafka, MinIO, and both services running.
        """
        # Get baseline document count from S5
        baseline_resp = await s5_client.get("/readyz")
        # If S5 is not fully ready (503), skip rather than fail
        if baseline_resp.status_code == 503:
            pytest.skip("S5 is not fully ready (readyz returned 503)")
        # Submit content to S4
        unique_url = f"https://news.example.com/pipeline-test/{uuid.uuid4().hex}"
        submit_resp = await s4_client.post(
            "/internal/v1/ingest/submit",
            json={
                "url": unique_url,
```

### 163. tests.e2e.test_intelligence_pipeline::test_s6_readyz
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_readyz(s6_client: AsyncClient) -> None:
        """S6 /readyz returns 200 or 503."""
>       resp = await s6_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:142:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 164. tests.e2e.test_intelligence_pipeline::test_s6_list_signals_empty
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_list_signals_empty(s6_client: AsyncClient) -> None:
        """GET /api/v1/signals returns empty list on fresh stack."""
>       resp = await s6_client.get("/api/v1/signals")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:161:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>, url = '/api/v1/signals'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 165. tests.e2e.test_intelligence_pipeline::test_s6_signals_pagination_defaults
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_signals_pagination_defaults(s6_client: AsyncClient) -> None:
        """GET /api/v1/signals uses default pagination (limit=50, offset=0)."""
>       resp = await s6_client.get("/api/v1/signals")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:179:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>, url = '/api/v1/signals'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 166. tests.e2e.test_intelligence_pipeline::test_s6_vector_search_no_embeddings
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_vector_search_no_embeddings(s6_client: AsyncClient) -> None:
        """POST /api/v1/vector-search with no stored embeddings returns empty hits."""
>       resp = await s6_client.post(
            "/api/v1/vector-search",
            json={"query": "Apple quarterly earnings revenue", "limit": 5},
        )
tests/e2e/test_intelligence_pipeline.py:197:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>, url = '/api/v1/vector-search'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
```

### 167. tests.e2e.test_intelligence_pipeline::test_s6_entity_detail_not_found
- suite: cross-service:e2e
- kind: failure
- reason: assert 500 == 404
 +  where 500 = <Response [500 Internal Server Error]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_entity_detail_not_found(s6_client: AsyncClient) -> None:
        """GET /api/v1/entities/{id} with unknown entity returns 404."""
        resp = await s6_client.get(f"/api/v1/entities/{uuid.uuid4()}")
>       assert resp.status_code == 404
E       assert 500 == 404
E        +  where 500 = <Response [500 Internal Server Error]>.status_code
tests/e2e/test_intelligence_pipeline.py:211: AssertionError
```

### 168. tests.e2e.test_intelligence_pipeline::test_s6_entity_articles_not_found
- suite: cross-service:e2e
- kind: failure
- reason: assert 200 == 404
 +  where 200 = <Response [200 OK]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_entity_articles_not_found(s6_client: AsyncClient) -> None:
        """GET /api/v1/entities/{id}/articles for unknown entity returns 404."""
        resp = await s6_client.get(f"/api/v1/entities/{uuid.uuid4()}/articles")
>       assert resp.status_code == 404
E       assert 200 == 404
E        +  where 200 = <Response [200 OK]>.status_code
tests/e2e/test_intelligence_pipeline.py:218: AssertionError
```

### 169. tests.e2e.test_intelligence_pipeline::test_s6_reprocess_unknown_article
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_reprocess_unknown_article(s6_client: AsyncClient) -> None:
        """POST /api/v1/reprocess/{id} for unknown article returns 404."""
>       resp = await s6_client.post(f"/api/v1/reprocess/{uuid.uuid4()}")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:224:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>
url = '/api/v1/reprocess/8d496eaf-1a47-4238-ac33-9a0c961d72d8'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
```

### 170. tests.e2e.test_intelligence_pipeline::test_s6_dlq_list
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s6_client = <httpx.AsyncClient object at 0x10865a6f0>
    @_skip_s6
    async def test_s6_dlq_list(s6_client: AsyncClient) -> None:
        """GET /admin/dlq with valid token returns entries list."""
>       resp = await s6_client.get("/admin/dlq", headers=_s6_admin())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:238:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10865a6f0>, url = '/admin/dlq'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 171. tests.e2e.test_intelligence_pipeline::test_s7_readyz
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_readyz(s7_client: AsyncClient) -> None:
        """S7 /readyz returns 200 or 503."""
>       resp = await s7_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:258:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb16d20>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 172. tests.e2e.test_intelligence_pipeline::test_s7_entity_graph_not_found
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_entity_graph_not_found(s7_client: AsyncClient) -> None:
        """GET /api/v1/entities/{id}/graph for unknown entity returns 404."""
>       resp = await s7_client.get(f"/api/v1/entities/{uuid.uuid4()}/graph")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:275:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb16d20>
url = '/api/v1/entities/a8277078-81af-4f4f-90e3-59ab6644d191/graph'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
```

### 173. tests.e2e.test_intelligence_pipeline::test_s7_relations_list_empty
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_relations_list_empty(s7_client: AsyncClient) -> None:
        """GET /api/v1/relations returns empty list on fresh intelligence_db."""
>       resp = await s7_client.get("/api/v1/relations")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:289:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb16d20>, url = '/api/v1/relations'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 174. tests.e2e.test_intelligence_pipeline::test_s7_relations_list_subject_filter
- suite: cross-service:e2e
- kind: failure
- reason: assert 500 == 200
 +  where 500 = <Response [500 Internal Server Error]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_relations_list_subject_filter(s7_client: AsyncClient) -> None:
        """GET /api/v1/relations?subject_id=<uuid> filters correctly."""
        resp = await s7_client.get(f"/api/v1/relations?subject_id={uuid.uuid4()}")
>       assert resp.status_code == 200
E       assert 500 == 200
E        +  where 500 = <Response [500 Internal Server Error]>.status_code
tests/e2e/test_intelligence_pipeline.py:300: AssertionError
```

### 175. tests.e2e.test_intelligence_pipeline::test_s7_relations_list_confidence_filter
- suite: cross-service:e2e
- kind: failure
- reason: assert 500 == 200
 +  where 500 = <Response [500 Internal Server Error]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_relations_list_confidence_filter(s7_client: AsyncClient) -> None:
        """GET /api/v1/relations?min_confidence=0.9 returns only high-confidence relations."""
        resp = await s7_client.get("/api/v1/relations?min_confidence=0.9")
>       assert resp.status_code == 200
E       assert 500 == 200
E        +  where 500 = <Response [500 Internal Server Error]>.status_code
tests/e2e/test_intelligence_pipeline.py:308: AssertionError
```

### 176. tests.e2e.test_intelligence_pipeline::test_s7_graph_stats_returns_counts
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_graph_stats_returns_counts(s7_client: AsyncClient) -> None:
        """GET /api/v1/graph/stats returns non-negative counts for all fields."""
>       resp = await s7_client.get("/api/v1/graph/stats")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:324:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb16d20>, url = '/api/v1/graph/stats'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 177. tests.e2e.test_intelligence_pipeline::test_s7_dlq_list
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s7_client = <httpx.AsyncClient object at 0x10fb16d20>
    @_skip_s7
    async def test_s7_dlq_list(s7_client: AsyncClient) -> None:
        """GET /admin/dlq with valid token returns entries list."""
>       resp = await s7_client.get("/admin/dlq", headers=_s7_admin())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:343:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb16d20>, url = '/admin/dlq'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 178. tests.e2e.test_intelligence_pipeline::test_s10_readyz
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s10_client = <httpx.AsyncClient object at 0x10fb62a80>
    @_skip_s10
    async def test_s10_readyz(s10_client: AsyncClient) -> None:
        """S10 /readyz returns 200 or 503."""
>       resp = await s10_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:363:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb62a80>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 179. tests.e2e.test_intelligence_pipeline::test_s10_pending_alerts_empty_for_new_user
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s10_client = <httpx.AsyncClient object at 0x10fb62a80>
    @_skip_s10
    async def test_s10_pending_alerts_empty_for_new_user(s10_client: AsyncClient) -> None:
        """GET /api/v1/alerts/pending for a new user returns empty list."""
>       resp = await s10_client.get(f"/api/v1/alerts/pending?user_id={uuid.uuid4()}")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:380:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb62a80>
url = '/api/v1/alerts/pending?user_id=d4ae515f-2274-4cd5-b223-720f6bfd6dcf'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
```

### 180. tests.e2e.test_intelligence_pipeline::test_s10_dlq_auth_guard
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s10_client = <httpx.AsyncClient object at 0x10fb62a80>
    @_skip_s10
    async def test_s10_dlq_auth_guard(s10_client: AsyncClient) -> None:
        """GET /admin/dlq without token → 401."""
>       resp = await s10_client.get("/admin/dlq")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:397:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb62a80>, url = '/admin/dlq'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 181. tests.e2e.test_intelligence_pipeline::test_s10_tenant_isolation_no_cross_user_alerts
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s10_client = <httpx.AsyncClient object at 0x10fb62a80>
    @_skip_s10
    async def test_s10_tenant_isolation_no_cross_user_alerts(s10_client: AsyncClient) -> None:
        """Alerts for user A are NOT accessible by user B (no cross-tenant leakage)."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        # user_b should not see user_a's alerts (and vice versa)
>       resp_a = await s10_client.get(f"/api/v1/alerts/pending?user_id={user_a}")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_intelligence_pipeline.py:417:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10fb62a80>
url = '/api/v1/alerts/pending?user_id=1e01f5b6-a477-4f3f-bcba-b322a0f1c3ea'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
```

### 182. tests.e2e.test_intelligence_pipeline::test_s7_graph_grows_after_s6_enrichment
- suite: cross-service:e2e
- kind: failure
- reason: httpx.ReadTimeout
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
@contextlib.contextmanager
    def map_httpcore_exceptions() -> typing.Iterator[None]:
        try:
>           yield
.venv/lib/python3.12/site-packages/httpx/_transports/default.py:69:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncHTTPTransport object at 0x10fb70800>
request = <Request('GET', 'http://localhost:8007/api/v1/graph/stats')>
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

### 183. tests.e2e.test_market_data_pipeline::test_s2_readyz_healthy
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s2_client = <httpx.AsyncClient object at 0x10868b950>
    @_skip_s2
    async def test_s2_readyz_healthy(s2_client: AsyncClient) -> None:
        """GET /readyz on S2 returns 200 with db and storage checks passing."""
>       resp = await s2_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_market_data_pipeline.py:97:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x10868b950>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 184. tests.e2e.test_market_data_pipeline::test_s3_readyz_healthy
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s3_client = <httpx.AsyncClient object at 0x1086eec00>
    @_skip_s3
    async def test_s3_readyz_healthy(s3_client: AsyncClient) -> None:
        """GET /readyz on S3 returns 200."""
>       resp = await s3_client.get("/readyz")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_market_data_pipeline.py:108:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1086eec00>, url = '/readyz'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
        """
```

### 185. tests.e2e.test_market_data_pipeline::test_trigger_aapl_creates_exactly_one_task
- suite: cross-service:e2e
- kind: failure
- reason: ModuleNotFoundError: No module named 'market_ingestion'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s2_client = <httpx.AsyncClient object at 0x10868b950>
s2_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10f8d7ce0>
    @_skip_s2
    async def test_trigger_aapl_creates_exactly_one_task(
        s2_client: AsyncClient,
        s2_db_session: AsyncSession,
    ) -> None:
        """POST /api/v1/ingest/trigger for AAPL → 202 + exactly 1 pending task row in DB."""
>       from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
E       ModuleNotFoundError: No module named 'market_ingestion'
tests/e2e/test_market_data_pipeline.py:122: ModuleNotFoundError
```

### 186. tests.e2e.test_market_data_pipeline::test_trigger_same_symbol_twice_creates_only_one_task
- suite: cross-service:e2e
- kind: failure
- reason: ModuleNotFoundError: No module named 'market_ingestion'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s2_client = <httpx.AsyncClient object at 0x10868b950>
s2_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10fad72f0>
    @_skip_s2
    async def test_trigger_same_symbol_twice_creates_only_one_task(
        s2_client: AsyncClient,
        s2_db_session: AsyncSession,
    ) -> None:
        """Triggering the same symbol twice: first creates, second skips (idempotency).
        DB should contain exactly 1 active task for this symbol after both calls.
        """
>       from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
E       ModuleNotFoundError: No module named 'market_ingestion'
tests/e2e/test_market_data_pipeline.py:151: ModuleNotFoundError
```

### 187. tests.e2e.test_market_data_pipeline::test_triggered_task_progresses_through_lifecycle
- suite: cross-service:e2e
- kind: failure
- reason: ModuleNotFoundError: No module named 'market_ingestion'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s2_client = <httpx.AsyncClient object at 0x10868b950>
s2_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10fad6e10>
    @_skip_s2
    async def test_triggered_task_progresses_through_lifecycle(
        s2_client: AsyncClient,
        s2_db_session: AsyncSession,
    ) -> None:
        """A triggered task should leave 'pending' within 30 s as the worker claims it.
        We do not require success — running/retry/succeeded/failed are all valid
        terminal-or-intermediate states that confirm the worker pipeline is active.
        """
>       from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
E       ModuleNotFoundError: No module named 'market_ingestion'
tests/e2e/test_market_data_pipeline.py:193: ModuleNotFoundError
```

### 188. tests.e2e.test_market_data_pipeline::test_eodhd_demo_key_task_lifecycle_observed
- suite: cross-service:e2e
- kind: failure
- reason: ModuleNotFoundError: No module named 'market_ingestion'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s2_client = <httpx.AsyncClient object at 0x10868b950>
s2_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10fa4d610>
    @_skip_s2
    async def test_eodhd_demo_key_task_lifecycle_observed(
        s2_client: AsyncClient,
        s2_db_session: AsyncSession,
    ) -> None:
        """Full worker pipeline test using the EODHD demo key with symbol AAPL.
        The demo key may return data or fail with an API error; either outcome is
        acceptable.  What we assert is that:
          1. The API accepted the trigger (202).
          2. The worker claimed the task within 30 s (status != 'pending').
        This confirms the scheduler and worker processes are running end-to-end.
        """
>       from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel
E       ModuleNotFoundError: No module named 'market_ingestion'
tests/e2e/test_market_data_pipeline.py:248: ModuleNotFoundError
```

### 189. tests.e2e.test_security_isolation::test_cross_tenant_portfolio_isolation
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_cross_tenant_portfolio_isolation(s1_client: AsyncClient) -> None:
        """Resources created by Tenant A must not be accessible by Tenant B.
        Tenant B using its own X-Tenant-ID to query Tenant A's portfolio must
        receive 403 or 404 — never the actual portfolio data.
        """
        tag = uuid.uuid4().hex[:6]
>       tenant_a = await _make_tenant(s1_client, f"A_{tag}")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:111:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'A_40f670'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
        resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
>       assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
E       AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_security_isolation.py:52: AssertionError
```

### 190. tests.e2e.test_security_isolation::test_cross_tenant_holdings_isolation
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
s1_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10fad6ba0>
    @_skip_s1
    async def test_cross_tenant_holdings_isolation(s1_client: AsyncClient, s1_db_session: Any) -> None:
        """Holdings and transactions created under Tenant A must not be visible via Tenant B."""
        tag = uuid.uuid4().hex[:6]
>       tenant_a = await _make_tenant(s1_client, f"HA_{tag}")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:143:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'HA_b681f9'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
>       resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:51:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/tenants'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
```

### 191. tests.e2e.test_security_isolation::test_watchlist_requires_tenant_and_owner_headers
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_watchlist_requires_tenant_and_owner_headers(s1_client: AsyncClient) -> None:
        """GET /api/v1/watchlist without X-Tenant-ID and X-Owner-ID must return 400 or 422."""
        # No headers at all.
>       resp_no_headers = await s1_client.get("/api/v1/watchlist")
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:222:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/watchlist'
    async def get(
        self,
        url: URLTypes,
        *,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
        """
        Send a `GET` request.
        **Parameters**: See `httpx.request`.
```

### 192. tests.e2e.test_security_isolation::test_access_another_users_portfolio_within_same_tenant
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_access_another_users_portfolio_within_same_tenant(s1_client: AsyncClient) -> None:
        """Within the same tenant, User A2 accessing User A1's portfolio.
        The actual enforcement depends on the auth model:
        - If the service is owner-scoped, A2 should receive 403/404.
        - If the service is tenant-scoped (all users share access), A2 may receive 200.
        This test documents the observed behaviour without prescribing which is
        correct — the assertion logs the status code for review.
        """
        tag = uuid.uuid4().hex[:6]
>       tenant = await _make_tenant(s1_client, f"SAME_{tag}")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:255:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'SAME_24e1a4'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
        resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
>       assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
E       AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_security_isolation.py:52: AssertionError
```

### 193. tests.e2e.test_security_isolation::test_create_tenant_with_empty_name_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_create_tenant_with_empty_name_returns_422(s1_client: AsyncClient) -> None:
        """POST /api/v1/tenants with an empty name string must be rejected with 422."""
>       resp = await s1_client.post("/api/v1/tenants", json={"name": ""})
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:280:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/tenants'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
        cookies: CookieTypes | None = None,
        auth: AuthTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
        timeout: TimeoutTypes | UseClientDefault = USE_CLIENT_DEFAULT,
        extensions: RequestExtensions | None = None,
    ) -> Response:
```

### 194. tests.e2e.test_security_isolation::test_create_portfolio_with_nonexistent_user_returns_404_or_422
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_create_portfolio_with_nonexistent_user_returns_404_or_422(s1_client: AsyncClient) -> None:
        """POST /api/v1/portfolios with a non-existent owner_user_id must return 404 or 422."""
        tag = uuid.uuid4().hex[:6]
>       tenant = await _make_tenant(s1_client, f"NX_{tag}")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:298:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'NX_6ea7fa'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
>       resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:51:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/tenants'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
```

### 195. tests.e2e.test_security_isolation::test_create_portfolio_for_user_from_different_tenant
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_create_portfolio_for_user_from_different_tenant(s1_client: AsyncClient) -> None:
        """Creating a portfolio for a user that belongs to a different tenant must fail.
        X-Tenant-ID = Tenant B, but owner_user_id belongs to Tenant A → 404 or 422.
        """
        tag = uuid.uuid4().hex[:6]
>       tenant_a = await _make_tenant(s1_client, f"CPA_{tag}")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:322:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'CPA_eaa81c'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
        resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
>       assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
E       AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_security_isolation.py:52: AssertionError
```

### 196. tests.e2e.test_security_isolation::test_holdings_for_nonexistent_portfolio_returns_404
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_holdings_for_nonexistent_portfolio_returns_404(s1_client: AsyncClient) -> None:
        """GET /api/v1/holdings/{id} for a random UUID must return 404."""
        tag = uuid.uuid4().hex[:6]
>       tenant = await _make_tenant(s1_client, f"NXH_{tag}")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:345:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'NXH_bb5c2b'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
>       resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:51:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/tenants'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
```

### 197. tests.e2e.test_security_isolation::test_transaction_with_oversized_quantity_returns_422
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_transaction_with_oversized_quantity_returns_422(s1_client: AsyncClient) -> None:
        """POST /api/v1/transactions with an absurdly large quantity must return 422."""
        tag = uuid.uuid4().hex[:6]
>       tenant = await _make_tenant(s1_client, f"OVQ_{tag}")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:361:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'OVQ_ad96e5'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
        resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
>       assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
E       AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_security_isolation.py:52: AssertionError
```

### 198. tests.e2e.test_security_isolation::test_concurrent_sell_same_holding
- suite: cross-service:e2e
- kind: failure
- reason: ModuleNotFoundError: No module named 'portfolio'
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
s1_db_session = <sqlalchemy.ext.asyncio.session.AsyncSession object at 0x10fad6d50>
    @_skip_s1
    async def test_concurrent_sell_same_holding(s1_client: AsyncClient, s1_db_session: Any) -> None:
        """Two concurrent SELL requests for a shared holding must not produce a negative quantity.
        Setup: Buy 10 shares, then fire two SELL-5 requests concurrently.
        Expected outcomes:
          - Both succeed (total sold = 10, final qty = 0) — optimistic serialization
          - One succeeds, one fails with 422/409 — DB-level constraint
          - Final quantity must be >= 0 (no oversell)
        """
        from uuid import uuid4
>       from portfolio.infrastructure.db.models.instrument import InstrumentModel
E       ModuleNotFoundError: No module named 'portfolio'
tests/e2e/test_security_isolation.py:397: ModuleNotFoundError
```

### 199. tests.e2e.test_security_isolation::test_tenant_name_with_special_chars
- suite: cross-service:e2e
- kind: failure
- reason: RuntimeError: Event loop is closed
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_tenant_name_with_special_chars(s1_client: AsyncClient) -> None:
        """Tenant name containing SQL meta-characters must be stored safely.
        The service should either:
          - Accept the name (201) and store it literally (parameterised queries prevent injection)
          - Reject it with 422 if the name fails validation
        After the request the service must still be healthy (SQL injection did not corrupt the DB).
        """
        injection_name = "'; DROP TABLE tenants; --"
>       resp = await s1_client.post("/api/v1/tenants", json={"name": injection_name})
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:485:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <httpx.AsyncClient object at 0x1085ccfe0>, url = '/api/v1/tenants'
    async def post(
        self,
        url: URLTypes,
        *,
        content: RequestContent | None = None,
        data: RequestData | None = None,
        files: RequestFiles | None = None,
        json: typing.Any | None = None,
        params: QueryParamTypes | None = None,
        headers: HeaderTypes | None = None,
```

### 200. tests.e2e.test_security_isolation::test_alert_preferences_cross_tenant
- suite: cross-service:e2e
- kind: failure
- reason: AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
assert 401 == 201
 +  where 401 = <Response [401 Unauthorized]>.status_code
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
s1_client = <httpx.AsyncClient object at 0x1085ccfe0>
    @_skip_s1
    async def test_alert_preferences_cross_tenant(s1_client: AsyncClient) -> None:
        """Alert preferences are scoped to the (tenant_id, owner_id) pair.
        Tenant A's customised preference must not be visible when queried with
        Tenant B's headers — the response should reflect Tenant B's own defaults,
        not Tenant A's stored value.
        """
        tag = uuid.uuid4().hex[:6]
>       tenant_a = await _make_tenant(s1_client, f"APA_{tag}")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/e2e/test_security_isolation.py:518:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
client = <httpx.AsyncClient object at 0x1085ccfe0>, suffix = 'APA_6d3464'
    async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
        tag = suffix or uuid.uuid4().hex[:6]
        resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
>       assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
E       AssertionError: make_tenant failed (401): {"detail":"Invalid or missing internal token"}
E       assert 401 == 201
E        +  where 401 = <Response [401 Unauthorized]>.status_code
tests/e2e/test_security_isolation.py:52: AssertionError
```

### 201. tests.e2e.test_security_isolation::test_alert_preferences_cross_tenant
- suite: cross-service:e2e
- kind: error
- reason: failed on teardown with "ExceptionGroup: errors while tearing down <Session  exitstatus=<ExitCode.OK: 0> testsfailed=52 testscollected=97> (3 sub-exceptions)"
- log: docs/testing/test-runs/20260331T082221Z/suites/cross-service_e2e.log
```text
+ Exception Group Traceback (most recent call last):
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/_pytest/runner.py", line 344, in from_call
  |     result: TResult | None = func()
  |                              ^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/_pytest/runner.py", line 246, in <lambda>
  |     lambda: runtest_hook(item=item, **kwds), when=when, reraise=reraise
  |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_hooks.py", line 512, in __call__
  |     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_manager.py", line 120, in _hookexec
  |     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 167, in _multicall
  |     raise exception
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 139, in _multicall
  |     teardown.throw(exception)
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/_pytest/logging.py", line 858, in pytest_runtest_teardown
  |     yield
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 139, in _multicall
  |     teardown.throw(exception)
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/_pytest/capture.py", line 905, in pytest_runtest_teardown
  |     return (yield)
  |             ^^^^^
  |   File "/Users/arnaurodon/Projects/University/final_thesis/worldview/.venv/lib/python3.12/site-packages/pluggy/_callers.py", line 121, in _multicall
```
