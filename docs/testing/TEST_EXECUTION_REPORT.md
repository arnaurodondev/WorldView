# Test Execution Report

Generated at: 2026-04-01T09:28:13Z
Run ID: 20260330T220331Z
Run artifacts: docs/testing/test-runs/20260330T220331Z
Run duration (sec): 127482

## Environment
- git branch: feat/content-ingestion-wave-a1
- git sha: f07f9c67d6a660529650af117dbe425633c666df
- python: Python 3.12.7
- docker: Docker version 29.1.3, build f52814d
- docker compose: Docker Compose version v5.0.0-desktop.1
- retain logs: on-failure
- integration mode: sequential

## Summary
- Test suites passed: 12
- Test suites failed: 5
- Test suites skipped: 31
- Total collected tests: 2237
- Total failed tests: 17
- Note: suite counts and test counts are different units

## Aggregated Metrics
- Collected in passed/failed suites: 2237
- Collected in skipped suites: 0
- Failed tests extracted from JUnit: 14

## Metrics By Layer
| Layer | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| architecture | 1/0/0 | 35 | 0 | 2 |
| contract | 3/0/8 | 20 | 0 | 2 |
| e2e | 0/0/12 | 0 | 13 | 0 |
| infra | 0/1/0 | 0 | 0 | 127302 |
| integration | 0/0/11 | 0 | 0 | 0 |
| libs | 1/0/0 | 0 | 0 | 7 |
| unit | 7/4/0 | 2182 | 1 | 18 |

## Metrics By Service
| Service | Suites (P/F/S) | Collected Tests | Failed Tests | Duration (s) |
|---|---:|---:|---:|---:|
| alert | 1/1/2 | 129 | 1 | 1 |
| api-gateway | 0/1/3 | 0 | 0 | 0 |
| architecture | 1/0/0 | 35 | 0 | 2 |
| compose | 0/1/0 | 0 | 0 | 127302 |
| content-ingestion | 1/0/3 | 401 | 0 | 2 |
| content-store | 1/0/3 | 241 | 0 | 1 |
| cross-service | 0/0/1 | 0 | 13 | 0 |
| intelligence-migrations | 0/1/3 | 0 | 0 | 0 |
| knowledge-graph | 1/0/3 | 177 | 0 | 1 |
| libs | 1/0/0 | 0 | 0 | 7 |
| market-data | 1/0/3 | 338 | 0 | 9 |
| market-ingestion | 2/0/2 | 395 | 0 | 3 |
| nlp-pipeline | 1/0/3 | 217 | 0 | 1 |
| portfolio | 2/0/2 | 304 | 0 | 2 |
| rag-chat | 0/1/3 | 0 | 0 | 0 |

## Failure Hotspots
- cross-service:e2e: 13 failed tests
- alert:unit: 1 failed tests

## Infra Status
- Status: failed
- compose ps: docs/testing/test-runs/20260330T220331Z/infra/compose.ps.txt
- compose config: docs/testing/test-runs/20260330T220331Z/infra/compose.config.yaml
- compose all logs: docs/testing/test-runs/20260330T220331Z/infra/compose.all.log
- service logs dir: docs/testing/test-runs/20260330T220331Z/infra/services
- inspect dir: docs/testing/test-runs/20260330T220331Z/infra/inspect

## Suite Results
- architecture: passed (layer=architecture, type=pytest, collected=35, duration=2s)
- libs: passed (layer=libs, type=script, collected=0, duration=7s) - summarized by scripts/test-libs.sh
- alert:unit: failed (layer=unit, type=pytest, collected=126, duration=1s, failure_type=assertion) - pytest exited with code 1
- api-gateway:unit: failed (layer=unit, type=pytest, collected=0, duration=0s, failure_type=script_failure) - pytest exited with code 4
- content-ingestion:unit: passed (layer=unit, type=pytest, collected=401, duration=2s)
- content-store:unit: passed (layer=unit, type=pytest, collected=241, duration=1s)
- intelligence-migrations:unit: failed (layer=unit, type=pytest, collected=0, duration=0s, failure_type=script_failure) - pytest exited with code 4
- knowledge-graph:unit: passed (layer=unit, type=pytest, collected=177, duration=1s)
- market-data:unit: passed (layer=unit, type=pytest, collected=338, duration=9s)
- market-ingestion:unit: passed (layer=unit, type=pytest, collected=392, duration=2s)
- nlp-pipeline:unit: passed (layer=unit, type=pytest, collected=217, duration=1s)
- portfolio:unit: passed (layer=unit, type=pytest, collected=290, duration=1s)
- rag-chat:unit: failed (layer=unit, type=pytest, collected=0, duration=0s, failure_type=script_failure) - pytest exited with code 4
- alert:contract: passed (layer=contract, type=pytest, collected=3, duration=0s)
- api-gateway:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-ingestion:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-store:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- intelligence-migrations:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract dir
- knowledge-graph:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-data:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-ingestion:contract: passed (layer=contract, type=pytest, collected=3, duration=1s)
- nlp-pipeline:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- portfolio:contract: passed (layer=contract, type=pytest, collected=14, duration=1s)
- rag-chat:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- compose:up: failed (layer=infra, type=compose_startup, collected=0, duration=127302s, failure_type=infra_startup) - docker compose up failed (exit 1)
- alert:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- alert:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- api-gateway:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- api-gateway:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-ingestion:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- content-ingestion:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- content-store:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- content-store:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- intelligence-migrations:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- intelligence-migrations:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- knowledge-graph:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- knowledge-graph:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- market-data:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- market-data:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- market-ingestion:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- market-ingestion:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- nlp-pipeline:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- nlp-pipeline:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- portfolio:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=setup) - integration skipped due to infra startup/readiness failure
- portfolio:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure
- rag-chat:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- rag-chat:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- cross-service:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=setup) - e2e skipped due to infra startup/readiness failure

## Failed Tests (Reason + Traceback Excerpt)
### 1. tests.unit.api.test_alerts_api.TestGetPendingAlerts::test_returns_empty_list_when_no_alerts
- suite: alert:unit
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
- log: docs/testing/test-runs/20260330T220331Z/suites/alert_unit.log
```text
self = <tests.unit.api.test_alerts_api.TestGetPendingAlerts object at 0x10b232330>
    @pytest.mark.unit
    async def test_returns_empty_list_when_no_alerts(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = str(uuid4())
        with (
>           patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
tests/unit/api/test_alerts_api.py:92:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b49fd40>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
            spec_set = None
        if autospec is False:
```

### 2. tests.unit.api.test_alerts_api.TestGetPendingAlerts::test_returns_pending_alerts_for_user
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestGetPendingAlerts object at 0x10b2327b0>
    @pytest.mark.unit
    async def test_returns_pending_alerts_for_user(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert = _make_alert()
        pending = _make_pending(user_id, alert.alert_id)
        with (
>           patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
tests/unit/api/test_alerts_api.py:114:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b50a300>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
```

### 3. tests.unit.api.test_alerts_api.TestGetPendingAlerts::test_pagination_params_respected
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestGetPendingAlerts object at 0x10b232900>
    @pytest.mark.unit
    async def test_pagination_params_respected(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        captured_args: list[dict] = []
        async def _capture_list(uid: UUID, limit: int = 50, offset: int = 0) -> list:
            captured_args.append({"user_id": uid, "limit": limit, "offset": offset})
            return []
        with (
>           patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH),
        ):
tests/unit/api/test_alerts_api.py:142:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b49d160>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
```

### 4. tests.unit.api.test_alerts_api.TestGetPendingAlerts::test_missing_alert_record_skipped
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestGetPendingAlerts object at 0x10b232b10>
    @pytest.mark.unit
    async def test_missing_alert_record_skipped(self) -> None:
        """Pending row whose alert was deleted (orphan) is silently skipped."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        pending = _make_pending(user_id, uuid4())
        with (
>           patch(_PENDING_REPO_PATH) as MockPendingRepo,
            patch(_ALERT_REPO_PATH) as MockAlertRepo,
        ):
tests/unit/api/test_alerts_api.py:162:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b4f7c80>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
```

### 5. tests.unit.api.test_alerts_api.TestAcknowledgeAlert::test_ack_returns_200_on_success
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestAcknowledgeAlert object at 0x10b232f30>
    @pytest.mark.unit
    async def test_ack_returns_200_on_success(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
>       with patch(_PENDING_REPO_PATH) as MockPendingRepo:
tests/unit/api/test_alerts_api.py:186:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b530860>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
            spec_set = None
        if autospec is False:
            autospec = None
        if spec is not None and autospec is not None:
```

### 6. tests.unit.api.test_alerts_api.TestAcknowledgeAlert::test_ack_returns_404_on_wrong_user
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestAcknowledgeAlert object at 0x10b233110>
    @pytest.mark.unit
    async def test_ack_returns_404_on_wrong_user(self) -> None:
        """ack returns 404 — not 403 — when alert belongs to a different user."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
>       with patch(_PENDING_REPO_PATH) as MockPendingRepo:
tests/unit/api/test_alerts_api.py:203:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b50bf50>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
            spec_set = None
        if autospec is False:
            autospec = None
```

### 7. tests.unit.api.test_alerts_api.TestAcknowledgeAlert::test_ack_returns_404_on_already_acknowledged
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestAcknowledgeAlert object at 0x10b233320>
    @pytest.mark.unit
    async def test_ack_returns_404_on_already_acknowledged(self) -> None:
        """ack returns 404 when the alert was already acknowledged."""
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
>       with patch(_PENDING_REPO_PATH) as MockPendingRepo:
tests/unit/api/test_alerts_api.py:219:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b52c530>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
            spec_set = None
        if autospec is False:
            autospec = None
```

### 8. tests.unit.api.test_alerts_api.TestAcknowledgeAlert::test_ack_calls_acknowledge_with_correct_ids
- suite: cross-service:e2e
- kind: failure
- reason: AttributeError: <module 'alert.application.use_cases.pending_alerts' from '/Users/arnaurodon/Projects/University/final_thesis/worldview/services/alert/src/alert/application/use_cases/pending_alerts.py'> does not have the attribute 'PendingAlertRepository'
```text
self = <tests.unit.api.test_alerts_api.TestAcknowledgeAlert object at 0x10b233530>
    @pytest.mark.unit
    async def test_ack_calls_acknowledge_with_correct_ids(self) -> None:
        app, _session = _make_app()
        transport = ASGITransport(app=app)
        user_id = uuid4()
        alert_id = uuid4()
        captured: list[tuple[UUID, UUID]] = []
        async def _capture_ack(uid: UUID, aid: UUID) -> bool:
            captured.append((uid, aid))
            return True
>       with patch(_PENDING_REPO_PATH) as MockPendingRepo:
tests/unit/api/test_alerts_api.py:240:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
self = <unittest.mock._patch object at 0x10b479e50>
    def __enter__(self):
        """Perform the patch."""
        new, spec, spec_set = self.new, self.spec, self.spec_set
        autospec, kwargs = self.autospec, self.kwargs
        new_callable = self.new_callable
        self.target = self.getter()
        # normalise False to None
        if spec is False:
            spec = None
        if spec_set is False:
```

### 9. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_suppresses_backfill_event
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2eefc0>
    @pytest.mark.unit
    async def test_suppresses_backfill_event(self) -> None:
>       use_case, _, _ = _make_use_case()
tests/unit/application/test_alert_fanout.py:229:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
        if save_alert_raises:
            mock_alert_repo.save = AsyncMock(side_effect=save_alert_raises)
```

### 10. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_returns_no_watchers_result
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2ef140>
    @pytest.mark.unit
    async def test_returns_no_watchers_result(self) -> None:
>       use_case, _mock_ws, _ = _make_use_case(watchers=[])
tests/unit/application/test_alert_fanout.py:245:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
        if save_alert_raises:
            mock_alert_repo.save = AsyncMock(side_effect=save_alert_raises)
```

### 11. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_dedup_suppresses_within_window
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2ef350>
    @pytest.mark.unit
    async def test_dedup_suppresses_within_window(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
>       use_case, _mock_ws, _ = _make_use_case(watchers=watchers)
tests/unit/application/test_alert_fanout.py:263:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
        if save_alert_raises:
```

### 12. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_fanout_creates_alert_and_pending
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2ef560>
    @pytest.mark.unit
    async def test_fanout_creates_alert_and_pending(self) -> None:
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
>       use_case, _mock_ws2, _ = _make_use_case(watchers=watchers)
tests/unit/application/test_alert_fanout.py:281:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
        if save_alert_raises:
```

### 13. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_websocket_push_happens_after_commit
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2ef770>
    @pytest.mark.unit
    async def test_websocket_push_happens_after_commit(self) -> None:
        """WebSocket push must happen outside the DB transaction."""
        watchers = [WatcherInfo(user_id=_USER_ID, watchlist_id=_WATCHLIST_ID)]
>       use_case, mock_ws, _ = _make_use_case(watchers=watchers)
tests/unit/application/test_alert_fanout.py:308:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
```

### 14. tests.unit.application.test_alert_fanout.TestAlertFanoutExecute::test_suppresses_no_entity_id
- suite: cross-service:e2e
- kind: failure
- reason: TypeError: AlertFanoutUseCase.__init__() missing 1 required positional argument: 'repo_factory'
```text
self = <tests.unit.application.test_alert_fanout.TestAlertFanoutExecute object at 0x10b2ef980>
    @pytest.mark.unit
    async def test_suppresses_no_entity_id(self) -> None:
        event = {**_SIGNAL_EVENT, "subject_entity_id": None, "claimer_entity_id": None}
>       use_case, _, _ = _make_use_case()
tests/unit/application/test_alert_fanout.py:337:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def _make_use_case(
        *,
        watchers: list[WatcherInfo] | None = None,
        dedup_exists: bool = False,
        save_alert_raises: Exception | None = None,
    ) -> tuple[AlertFanoutUseCase, AsyncMock, AsyncMock]:
        """Build a use case with mocked collaborators.
        Returns (use_case, mock_ws, mock_cache).
        """
        mock_ws = AsyncMock()
        mock_ws.send_to_user = AsyncMock(return_value=True)
        mock_cache = AsyncMock()
        mock_cache.get_watchers = AsyncMock(return_value=watchers if watchers is not None else [])
        # Build a fake session that returns mocked repositories
        mock_dedup_repo = AsyncMock()
        mock_dedup_repo.exists = AsyncMock(return_value=dedup_exists)
        mock_alert_repo = AsyncMock()
        if save_alert_raises:
```

### 15. <suite-level failure>
- suite: api-gateway:unit
- kind: script_failure
- reason: pytest exited with code 4
- log: docs/testing/test-runs/20260330T220331Z/suites/api-gateway_unit.log

### 16. <suite-level failure>
- suite: intelligence-migrations:unit
- kind: script_failure
- reason: pytest exited with code 4
- log: docs/testing/test-runs/20260330T220331Z/suites/intelligence-migrations_unit.log

### 17. <suite-level failure>
- suite: rag-chat:unit
- kind: script_failure
- reason: pytest exited with code 4
- log: docs/testing/test-runs/20260330T220331Z/suites/rag-chat_unit.log
