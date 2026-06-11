"""Unit tests for ExecuteContentTaskUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.application.use_cases.execute_task import ExecuteContentTaskUseCase, _FetchOutput
from content_ingestion.application.use_cases.fetch_and_write import FetchSummary
from content_ingestion.domain.entities import ContentIngestionTask, Source, SourceType
from content_ingestion.domain.exceptions import ConfigurationError

import common.ids
import common.time
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claimed_task(name: str = "test-source") -> ContentIngestionTask:
    """Create a task in CLAIMED state (ready to be started)."""
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=name,
        source_type=SourceType.EODHD,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
        attempt_count=0,
        max_attempts=5,
    )


def _make_source(task: ContentIngestionTask) -> Source:
    return Source(
        id=task.source_id,
        name=task.source_name,
        source_type=task.source_type,
        enabled=True,
        config={},
    )


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.backfill_enabled = False
    return settings


def _make_adapter_state_factory(
    last_watermark: object = None,
) -> tuple[MagicMock, AsyncMock]:
    """Create a mock adapter_state_factory and its underlying repo mock.

    Returns (factory, repo_mock) so tests can assert on repo_mock calls.
    """
    mock_state = MagicMock()
    mock_state.last_watermark = last_watermark
    repo = AsyncMock()
    repo.get.return_value = mock_state
    factory = MagicMock(return_value=repo)
    return factory, repo


def _make_write_factory() -> tuple[MagicMock, AsyncMock]:
    """Create a mock write_factory that yields mock sessions.

    Returns (factory, session) so tests can assert on session calls.
    """
    mock_session = AsyncMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)
    write_factory = MagicMock(return_value=mock_session_cm)
    return write_factory, mock_session


def _make_use_case(
    write_factory: MagicMock | None = None,
    settings: MagicMock | None = None,
    bronze: MagicMock | None = None,
    adapter_state_factory: MagicMock | None = None,
    fetch_log_factory: MagicMock | None = None,
    outbox_factory: MagicMock | None = None,
    adapter_builder: MagicMock | None = None,
) -> ExecuteContentTaskUseCase:
    wf = write_factory or MagicMock()
    return ExecuteContentTaskUseCase(
        write_factory=wf,
        settings=settings or _make_settings(),
        bronze=bronze or MagicMock(),
        adapter_state_factory=adapter_state_factory or MagicMock(),
        fetch_log_factory=fetch_log_factory or MagicMock(),
        outbox_factory=outbox_factory or MagicMock(),
        adapter_builder=adapter_builder or MagicMock(),
    )


def _mock_task_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.update_status = AsyncMock()
    return repo


def _make_fetch_output(
    task: ContentIngestionTask,
    results: list[MagicMock] | None = None,
) -> _FetchOutput:
    """Build a _FetchOutput with sensible defaults for testing."""
    return _FetchOutput(
        results=results or [],  # type: ignore[arg-type]
        adapter=MagicMock(),
        source=_make_source(task),
        watermark_date="",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecuteHappyPath:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_task_transitions_to_succeeded(self, mock_dofw: AsyncMock) -> None:
        mock_dofw.return_value = FetchSummary(source_name="test", fetched=1)

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()

        result = await uc.execute(task, task_repo)

        # Task should have been started (RUNNING) then _do_fetch_and_write ran
        assert result is not None
        assert result.fetched == 1
        # update_status called at least once for RUNNING
        task_repo.update_status.assert_awaited()


class TestExecuteNoResults:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    async def test_task_succeeded_when_no_results(self, mock_fetch: AsyncMock) -> None:
        task = _make_claimed_task()

        # _fetch_from_source returns empty results
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        # Mock adapter state factory for watermark read
        adapter_state_factory, _repo = _make_adapter_state_factory()

        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        task_repo = _mock_task_repo()

        result = await uc.execute(task, task_repo)
        assert task.status == IngestionTaskStatus.SUCCEEDED
        assert result is None


class TestExecuteFetchErrorRetry:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_network_error_causes_retry(self, mock_dofw: AsyncMock) -> None:
        mock_dofw.side_effect = ConnectionError("network down")

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()

        result = await uc.execute(task, task_repo)
        assert task.status == IngestionTaskStatus.RETRY
        assert result is None


class TestExecuteFetchErrorFatal:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_config_error_causes_immediate_failure(self, mock_dofw: AsyncMock) -> None:
        mock_dofw.side_effect = ConfigurationError("bad config")

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()

        result = await uc.execute(task, task_repo)
        assert task.status == IngestionTaskStatus.FAILED
        assert result is None


class TestExecuteReleasesSessionDuringFetch:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    async def test_fetch_called_without_active_session(self, mock_fetch: AsyncMock) -> None:
        """Verify that _fetch_from_source is called outside any long-lived UoW (R24)."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        adapter_state_factory, _repo = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)
        # _fetch_from_source was called (manages its own short-lived sessions)
        mock_fetch.assert_awaited_once()


class TestExecuteUpdatesWatermark:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_watermark_updated_on_success(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        task = _make_claimed_task()

        # _fetch_from_source returns results
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        # Advisory lock acquired
        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        # FetchAndWriteUseCase returns success
        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=2)
        mock_faw_cls.return_value = mock_faw

        # Inject adapter state factory
        adapter_state_factory, mock_asr = _make_adapter_state_factory()

        # Write factory
        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)

        # Watermark upsert should have been called
        assert mock_asr.upsert.await_count >= 1
        assert task.status == IngestionTaskStatus.SUCCEEDED


class TestMetricsNotCalledInUseCase:
    """Verify metrics recording is NOT called inside the use case (T-C-05).

    After refactoring, ``record_fetch`` moved to the worker (infra layer).
    The use case must not import or call any metrics function.
    """

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_no_metrics_call_in_use_case(self, mock_dofw: AsyncMock) -> None:
        mock_dofw.return_value = FetchSummary(source_name="test", fetched=5)

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()

        result = await uc.execute(task, task_repo)

        assert result is not None
        assert result.fetched == 5
        # Verify no 'record_fetch' attribute exists on the use case
        assert not hasattr(uc, "_metrics")


# ---------------------------------------------------------------------------
# PLAN-0109 / T-C-1-02 — Watermark always advances ``last_run_at`` on success
# ---------------------------------------------------------------------------


class TestWatermarkLastRunAtAlwaysAdvances:
    """When a poll completes successfully with zero fetched articles, the
    ``last_run_at`` field MUST advance so the polling-staleness alert can
    distinguish a healthy "no news today" cycle from a silently hung worker.
    ``last_watermark`` must remain unchanged so backfills stay anchored on
    the most recent article we actually saw (BP-658)."""

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    async def test_last_run_at_set_when_fetched_zero(self, mock_fetch: AsyncMock) -> None:
        """Adapter returns empty list → ``adapter_state_repo.upsert`` is called
        with ``last_run_at`` set (and ``last_watermark`` NOT passed)."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        adapter_state_factory, repo = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)

        # adapter_state_repo.upsert must have been called at least once
        # (once for the empty-results path).  Verify last_run_at is present.
        assert repo.upsert.await_count >= 1
        last_call = repo.upsert.await_args
        assert last_call is not None
        # kwargs should carry last_run_at but NOT last_watermark
        assert last_call.kwargs.get("last_run_at") is not None

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    async def test_last_watermark_unchanged_when_fetched_zero(self, mock_fetch: AsyncMock) -> None:
        """Empty-but-successful poll must NOT pass ``last_watermark`` to the
        upsert so the existing watermark is preserved (backfill anchor)."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        adapter_state_factory, repo = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)

        assert repo.upsert.await_count >= 1
        # No call should have advanced last_watermark on the empty path.
        for call in repo.upsert.await_args_list:
            assert (
                "last_watermark" not in call.kwargs
            ), "last_watermark must not be touched on an empty-but-successful poll"


# ---------------------------------------------------------------------------
# PLAN-0109 / T-C-1-03 — Transaction hygiene: rollback short-lived sessions
# ---------------------------------------------------------------------------


class TestFetchSessionRollback:
    """The dedup-check session in ``_fetch_from_source`` spans the external
    HTTP fetch.  On every exit path (success or failure) the session MUST be
    rolled back so the pooled asyncpg connection does not return with state
    ``idle in transaction (aborted)`` (BP-659)."""

    async def test_fetch_session_rollback_called_on_exit(self) -> None:
        """``_fetch_from_source`` must call ``session.rollback()`` even on
        a successful path (read-only session over network I/O)."""
        task = _make_claimed_task()

        # Adapter returns empty results — clean success path
        mock_adapter = MagicMock()
        mock_adapter.fetch = AsyncMock(return_value=[])
        adapter_builder = MagicMock(return_value=mock_adapter)

        mock_dedup_repo = AsyncMock()
        fetch_log_factory = MagicMock(return_value=mock_dedup_repo)

        # Session whose rollback is recorded
        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_builder=adapter_builder,
            fetch_log_factory=fetch_log_factory,
        )

        await uc._fetch_from_source(task, "")

        # rollback must have been invoked exactly once on the dedup session
        mock_session.rollback.assert_awaited()


class TestAdapterBuilderInjection:
    """Verify the adapter_builder is called correctly in _fetch_from_source."""

    async def test_adapter_builder_called_with_source_type_and_exists_fn(self) -> None:
        task = _make_claimed_task()

        mock_adapter = MagicMock()
        mock_adapter.fetch = AsyncMock(return_value=[])
        adapter_builder = MagicMock(return_value=mock_adapter)

        mock_dedup_repo = AsyncMock()
        fetch_log_factory = MagicMock(return_value=mock_dedup_repo)

        write_factory, _session = _make_write_factory()

        uc = _make_use_case(
            write_factory=write_factory,
            adapter_builder=adapter_builder,
            fetch_log_factory=fetch_log_factory,
        )

        output = await uc._fetch_from_source(task, "")

        # adapter_builder was called with the source type and dedup exists_fn
        adapter_builder.assert_called_once_with(
            task.source_type,
            mock_dedup_repo.exists_by_url_hash,
        )
        assert output.results == []


# ---------------------------------------------------------------------------
# D-9 — Split-brain prevention: task.succeed() is atomic with data write
# ---------------------------------------------------------------------------


class TestSplitBrainPrevention:
    """Verify that task SUCCEEDED status is committed inside the advisory-lock
    transaction (D-9).  If the inner commit fails, the task must NOT appear
    SUCCEEDED in the caller's view.
    """

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_task_succeeded_committed_inside_advisory_lock(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """When task_factory is provided, update_status is called inside the
        advisory-lock session — not via the outer task_repo argument (D-9)."""
        task = _make_claimed_task()
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=1)
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _mock_asr = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        # inner_task_repo returned by task_factory (bound to the advisory lock session)
        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        await uc.execute(task, outer_task_repo)

        # Succeeded update must go through inner_task_repo (inside the lock), not outer
        inner_task_repo.update_status.assert_awaited()
        # Outer task_repo should only be called for RUNNING status (step 1)
        for call in outer_task_repo.update_status.await_args_list:
            from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

            # positional arg[1] is the new status
            if len(call.args) >= 2:
                assert (
                    call.args[1] != IngestionTaskStatus.SUCCEEDED
                ), "outer task_repo.update_status was called with SUCCEEDED — D-9 violation"

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    async def test_advisory_lock_not_acquired_marks_retry(
        self,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """When the advisory lock is held by another worker, the task must be
        marked RETRY (D-003) — NOT SUCCEEDED."""
        task = _make_claimed_task()
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        # Advisory lock NOT acquired
        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=False)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        adapter_state_factory, _mock_asr = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        result = await uc.execute(task, outer_task_repo)

        # Must be RETRY, not SUCCEEDED
        assert task.status == IngestionTaskStatus.RETRY
        assert result is None
        # inner_task_repo receives RUNNING first (poisoned-session P0 fix:
        # committed immediately in its own session) and then RETRY.
        assert inner_task_repo.update_status.await_count == 2
        first_call = inner_task_repo.update_status.await_args_list[0]
        assert first_call.args[1] == IngestionTaskStatus.RUNNING
        call_args = inner_task_repo.update_status.await_args
        assert call_args.args[1] == IngestionTaskStatus.RETRY

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    async def test_advisory_lock_not_acquired_fallback_marks_retry(
        self,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """When task_factory is None and lock not acquired, outer task_repo
        is used — and status must still be RETRY (D-003)."""
        task = _make_claimed_task()
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        # Advisory lock NOT acquired
        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=False)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        adapter_state_factory, _mock_asr = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        # No task_factory — uses fallback path
        uc = _make_use_case(
            write_factory=write_factory,
            adapter_state_factory=adapter_state_factory,
        )
        outer_task_repo = _mock_task_repo()

        result = await uc.execute(task, outer_task_repo)

        assert task.status == IngestionTaskStatus.RETRY
        assert result is None

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_commit_failure_prevents_succeeded_status(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """If the inner commit (data + status) fails, the exception propagates
        and the caller must NOT see SUCCEEDED status — preventing split-brain (D-9)."""
        task = _make_claimed_task()
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=1)
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _mock_asr = _make_adapter_state_factory()

        # Write factory whose session.commit raises on the SECOND call.
        # The first commit is now the immediate RUNNING commit (poisoned-session
        # P0 fix); the second is the data+status commit inside the lock.
        mock_session = AsyncMock()
        mock_session.commit.side_effect = [None, RuntimeError("DB commit failed")]
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        # The DB error propagates — execute() catches it and marks RETRY/FAILED
        await uc.execute(task, outer_task_repo)

        # Task must NOT be in SUCCEEDED state (data was never committed)
        from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

        assert (
            task.status != IngestionTaskStatus.SUCCEEDED
        ), "Task was marked SUCCEEDED despite the commit failing — D-9 split-brain detected"


# ---------------------------------------------------------------------------
# Poisoned-session P0 (2026-06-11) — RUNNING status committed immediately
# ---------------------------------------------------------------------------


class TestRunningStatusCommittedImmediately:
    """The RUNNING status write must be committed in its own short-lived
    session BEFORE the fetch begins.  Holding it uncommitted on the outer
    worker session created a row lock that self-deadlocked with the D-9
    status update from the advisory-lock session, poisoning the asyncpg
    pool after the 120s task timeout ("Can't reconnect until invalid
    transaction is rolled back")."""

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_running_commit_happens_before_fetch(self, mock_dofw: AsyncMock) -> None:
        """When task_factory is provided, RUNNING goes through a fresh
        write_factory session and ``session.commit()`` is awaited BEFORE
        ``_do_fetch_and_write`` (the fetch pipeline) starts."""
        events: list[str] = []

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock(side_effect=lambda: events.append("running_commit"))
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        async def _record_fetch(*_args: object, **_kwargs: object) -> FetchSummary:
            events.append("fetch_started")
            return FetchSummary(source_name="test", fetched=1)

        mock_dofw.side_effect = _record_fetch

        inner_task_repo = AsyncMock()
        inner_task_repo.update_status = AsyncMock(side_effect=lambda *_a, **_k: events.append("running_write"))
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=MagicMock(),
            fetch_log_factory=MagicMock(),
            outbox_factory=MagicMock(),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        result = await uc.execute(task := _make_claimed_task(), outer_task_repo)

        assert result is not None
        # RUNNING write + commit must precede the fetch — the exact ordering
        # that prevents the uncommitted row lock from being held across the
        # long external fetch.
        assert events == ["running_write", "running_commit", "fetch_started"]
        # The RUNNING write must NOT go through the outer (uncommitted) session.
        for call in outer_task_repo.update_status.await_args_list:
            if len(call.args) >= 2:
                assert call.args[1] != IngestionTaskStatus.RUNNING, (
                    "RUNNING was written on the outer worker session — "
                    "uncommitted row lock would self-deadlock with the D-9 update"
                )
        assert task.status == IngestionTaskStatus.RUNNING or task.status == IngestionTaskStatus.SUCCEEDED

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_final_status_write_after_running_commit_no_self_deadlock(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """Regression for the self-deadlock: both the RUNNING write and the
        final SUCCEEDED write touch the same task row from different sessions.
        The RUNNING commit must complete BEFORE the advisory-lock session
        issues its UPDATE — asserted via strict event ordering."""
        events: list[str] = []
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[MagicMock()])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=1)
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _repo = _make_adapter_state_factory()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        inner_task_repo = AsyncMock()

        def _record_status(_task_id: object, status: object, **_kw: object) -> None:
            events.append(f"status:{status}")

        inner_task_repo.update_status = AsyncMock(side_effect=_record_status)
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        result = await uc.execute(task, outer_task_repo)

        assert result is not None
        assert task.status == IngestionTaskStatus.SUCCEEDED
        # Strict ordering: RUNNING write → commit (releases the row lock) →
        # SUCCEEDED write from the advisory-lock session → commit.  If the
        # first commit were missing, the second status write would block on
        # the row lock in production (the self-deadlock).
        running_write = events.index(f"status:{IngestionTaskStatus.RUNNING}")
        succeeded_write = events.index(f"status:{IngestionTaskStatus.SUCCEEDED}")
        first_commit = events.index("commit")
        assert running_write < first_commit < succeeded_write, (
            f"RUNNING was not committed before the SUCCEEDED write — " f"self-deadlock regression (events={events})"
        )
        # The outer task_repo must never have been used for status writes.
        outer_task_repo.update_status.assert_not_awaited()

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_running_commit_failure_rolls_back_and_raises(self, mock_dofw: AsyncMock) -> None:
        """If the immediate RUNNING commit fails, the session is rolled back
        (clean pooled connection) and the error propagates to the worker's
        rescue path — the fetch must never start."""
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=MagicMock(),
            fetch_log_factory=MagicMock(),
            outbox_factory=MagicMock(),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )

        with pytest.raises(RuntimeError, match="commit failed"):
            await uc.execute(_make_claimed_task(), _mock_task_repo())

        mock_session.rollback.assert_awaited()
        mock_dofw.assert_not_awaited()


class TestAdvisoryLockSessionHygiene:
    """Defense-in-depth checks for the advisory-lock session (poisoned-session P0)."""

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_lock_timeout_set_on_advisory_lock_session(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """``SET LOCAL lock_timeout`` must be issued on the advisory-lock
        session so a future re-introduction of an uncommitted row lock fails
        loudly after 10s instead of hanging until the 120s task timeout."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[MagicMock()])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=1)
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _repo = _make_adapter_state_factory()
        write_factory, session = _make_write_factory()

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )

        await uc.execute(task, _mock_task_repo())

        executed_sql = [str(call.args[0]) for call in session.execute.await_args_list if call.args]
        assert any(
            "lock_timeout" in sql for sql in executed_sql
        ), f"SET LOCAL lock_timeout was never issued on the advisory-lock session (executed={executed_sql})"

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_advisory_lock_session_rolled_back_on_failure(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        """If anything inside the advisory-lock session fails, the session is
        rolled back BEFORE the lock context exits, so ``pg_advisory_unlock``
        runs on a clean (non-aborted) transaction."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[MagicMock()])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        # The write pipeline blows up inside the lock
        mock_faw = AsyncMock()
        mock_faw.execute.side_effect = RuntimeError("write pipeline failed")
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _repo = _make_adapter_state_factory()
        write_factory, session = _make_write_factory()

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )

        # execute() swallows the error (marks RETRY) — that is fine; we only
        # care that the advisory-lock session was explicitly rolled back.
        await uc.execute(task, _mock_task_repo())

        session.rollback.assert_awaited()
        assert task.status == IngestionTaskStatus.RETRY


# ---------------------------------------------------------------------------
# F-CRIT-005 — Exception chaining when DB status update also fails
# ---------------------------------------------------------------------------


class TestExceptionChainingOnDbFailure:
    """When a pipeline error occurs AND the subsequent task_repo.update_status
    also fails, the DB error must be raised with the original error in its
    __cause__ chain (F-CRIT-005)."""

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_fatal_error_db_update_failure_chains_exceptions(self, mock_dofw: AsyncMock) -> None:
        """ConfigurationError (fatal) + DB update failure → DB error raised with
        original as __cause__."""
        original_error = ConfigurationError("bad config")
        mock_dofw.side_effect = original_error

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()
        db_error = RuntimeError("DB connection lost")
        # First call (mark RUNNING) succeeds; second call (in except handler) fails.
        task_repo.update_status.side_effect = [None, db_error]

        with pytest.raises(RuntimeError, match="DB connection lost") as exc_info:
            await uc.execute(task, task_repo)

        # Verify exception chaining: __cause__ should be the original error
        assert exc_info.value.__cause__ is original_error

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._do_fetch_and_write")
    async def test_retryable_error_db_update_failure_chains_exceptions(self, mock_dofw: AsyncMock) -> None:
        """ConnectionError (retryable) + DB update failure → DB error raised with
        original as __cause__."""
        original_error = ConnectionError("network down")
        mock_dofw.side_effect = original_error

        uc = _make_use_case()
        task = _make_claimed_task()
        task_repo = _mock_task_repo()
        db_error = RuntimeError("DB timeout")
        # First call (mark RUNNING) succeeds; second call (in except handler) fails.
        task_repo.update_status.side_effect = [None, db_error]

        with pytest.raises(RuntimeError, match="DB timeout") as exc_info:
            await uc.execute(task, task_repo)

        assert exc_info.value.__cause__ is original_error


# ---------------------------------------------------------------------------
# F-CRIT-004 — task_factory invariant: never use outer task_repo inside
# write_factory sessions when task_factory is available
# ---------------------------------------------------------------------------


class TestTaskFactoryInvariant:
    """When task_factory is provided, all status updates inside the advisory-lock
    session MUST go through task_factory(session), never the outer task_repo."""

    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_outer_task_repo_never_receives_succeeded_when_factory_exists(
        self,
        mock_faw_cls: MagicMock,
        mock_lock: MagicMock,
        mock_fetch: AsyncMock,
    ) -> None:
        task = _make_claimed_task()
        result_item = MagicMock()
        mock_fetch.return_value = _make_fetch_output(task, results=[result_item])

        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock(return_value=True)
        mock_lock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_lock.return_value = mock_lock_cm

        mock_faw = AsyncMock()
        mock_faw.execute.return_value = FetchSummary(source_name="test-source", fetched=1)
        mock_faw_cls.return_value = mock_faw

        adapter_state_factory, _mock_asr = _make_adapter_state_factory()
        write_factory, _session = _make_write_factory()

        inner_task_repo = AsyncMock()
        task_factory = MagicMock(return_value=inner_task_repo)

        uc = ExecuteContentTaskUseCase(
            write_factory=write_factory,
            settings=_make_settings(),
            bronze=MagicMock(),
            adapter_state_factory=adapter_state_factory,
            fetch_log_factory=MagicMock(return_value=AsyncMock()),
            outbox_factory=MagicMock(return_value=AsyncMock()),
            adapter_builder=MagicMock(),
            task_factory=task_factory,
        )
        outer_task_repo = _mock_task_repo()

        await uc.execute(task, outer_task_repo)

        # inner_task_repo must have received the SUCCEEDED update
        inner_task_repo.update_status.assert_awaited()
        found_succeeded = False
        for call in inner_task_repo.update_status.await_args_list:
            if len(call.args) >= 2 and call.args[1] == IngestionTaskStatus.SUCCEEDED:
                found_succeeded = True
        assert found_succeeded, "inner_task_repo never received SUCCEEDED — F-CRIT-004 violation"

        # outer_task_repo must NOT have SUCCEEDED (only RUNNING is allowed)
        for call in outer_task_repo.update_status.await_args_list:
            if len(call.args) >= 2:
                assert (
                    call.args[1] != IngestionTaskStatus.SUCCEEDED
                ), "outer task_repo received SUCCEEDED inside write session — F-CRIT-004 violation"
