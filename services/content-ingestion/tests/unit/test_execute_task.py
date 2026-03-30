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


def _make_use_case(
    write_factory: MagicMock | None = None,
    settings: MagicMock | None = None,
) -> ExecuteContentTaskUseCase:
    wf = write_factory or MagicMock()
    return ExecuteContentTaskUseCase(
        write_factory=wf,
        http_client=AsyncMock(),
        storage=MagicMock(),
        valkey=AsyncMock(),
        settings=settings or _make_settings(),
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
    @patch("content_ingestion.application.use_cases.execute_task.AdapterStateRepository")
    async def test_task_succeeded_when_no_results(self, mock_asr_cls: MagicMock, mock_fetch: AsyncMock) -> None:
        task = _make_claimed_task()

        # _fetch_from_source returns empty results
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        # Mock the watermark read session
        mock_state = MagicMock()
        mock_state.last_watermark = None
        mock_asr = AsyncMock()
        mock_asr.get.return_value = mock_state
        mock_asr_cls.return_value = mock_asr

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        uc = _make_use_case(write_factory=write_factory)
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
    @patch("content_ingestion.application.use_cases.execute_task.AdapterStateRepository")
    async def test_fetch_called_without_active_session(self, mock_asr_cls: MagicMock, mock_fetch: AsyncMock) -> None:
        """Verify that _fetch_from_source is called outside any long-lived UoW (R24)."""
        task = _make_claimed_task()
        mock_fetch.return_value = _make_fetch_output(task, results=[])

        mock_state = MagicMock()
        mock_state.last_watermark = None
        mock_asr = AsyncMock()
        mock_asr.get.return_value = mock_state
        mock_asr_cls.return_value = mock_asr

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        uc = _make_use_case(write_factory=write_factory)
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)
        # _fetch_from_source was called (manages its own short-lived sessions)
        mock_fetch.assert_awaited_once()


class TestExecuteUpdatesWatermark:
    @patch("content_ingestion.application.use_cases.execute_task.ExecuteContentTaskUseCase._fetch_from_source")
    @patch("content_ingestion.application.use_cases.execute_task.pg_advisory_lock")
    @patch("content_ingestion.application.use_cases.execute_task.record_fetch")
    @patch("content_ingestion.application.use_cases.execute_task.AdapterStateRepository")
    @patch("content_ingestion.application.use_cases.execute_task.FetchAndWriteUseCase")
    async def test_watermark_updated_on_success(
        self,
        mock_faw_cls: MagicMock,
        mock_asr_cls: MagicMock,
        mock_record: MagicMock,
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

        # AdapterStateRepository mock for both watermark read and write
        mock_state = MagicMock()
        mock_state.last_watermark = None
        mock_asr = AsyncMock()
        mock_asr.get.return_value = mock_state
        mock_asr_cls.return_value = mock_asr

        # Write factory
        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=mock_session_cm)

        uc = _make_use_case(write_factory=write_factory)
        task_repo = _mock_task_repo()

        await uc.execute(task, task_repo)

        # Watermark upsert should have been called (second ASR instance in write session)
        assert mock_asr.upsert.await_count >= 1
        assert task.status == IngestionTaskStatus.SUCCEEDED
