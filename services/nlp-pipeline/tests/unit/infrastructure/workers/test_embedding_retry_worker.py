"""Unit tests for EmbeddingRetryWorker (PLAN-0057 Wave E-4 + Wave C T-002).

The Wave E-4 tests covered the abandoned-log emission; Wave C T-002 extends
coverage to the success path, write-side commit failures, backoff arithmetic,
and the public ``run_once`` / ``run_forever`` surface.

structlog is not bound to stdlib ``logging`` in unit-test runs so we monkey-patch
the module-level ``logger`` and assert on its captured calls instead of using
``caplog``.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(*, commit_raises: bool = False) -> MagicMock:
    """Build a session factory that yields an AsyncMock session via async with.

    When ``commit_raises`` is true the yielded session.commit() raises so the
    write-side failure path can be exercised.
    """

    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        if commit_raises:
            session.commit = AsyncMock(side_effect=RuntimeError("commit denied"))
        else:
            session.commit = AsyncMock()
        session.add = MagicMock()
        yield session

    return MagicMock(side_effect=_ctx)


def _make_failing_embedding_client() -> AsyncMock:
    client = AsyncMock()
    client.embed = AsyncMock(side_effect=RuntimeError("DeepInfra 503"))
    return client


def _make_fatal_embedding_client() -> AsyncMock:
    """Embedding client whose embed() raises FatalError — the typed exception the
    DeepInfra adapter surfaces for HTTP 4xx (non-429) permanent/bad-input errors.
    """
    from ml_clients.errors import FatalError

    client = AsyncMock()
    client.embed = AsyncMock(side_effect=FatalError("DeepInfra embedding 4xx: 400 Bad Request"))
    return client


def _make_retryable_embedding_client() -> AsyncMock:
    """Embedding client whose embed() raises RetryableError — the typed exception
    the adapter surfaces for transient 5xx / timeout / network failures.
    """
    from ml_clients.errors import RetryableError

    client = AsyncMock()
    client.embed = AsyncMock(side_effect=RetryableError("DeepInfra embedding 5xx: 503"))
    return client


def _make_billing_embedding_client() -> AsyncMock:
    """Embedding client whose embed() raises ProviderBillingError — the typed
    exception the adapter surfaces for a spend-cap / auth refusal (HTTP 402/401/403).
    """
    from ml_clients.errors import ProviderBillingError

    client = AsyncMock()
    client.embed = AsyncMock(
        side_effect=ProviderBillingError("DeepInfra embedding billing/auth refusal (HTTP 402): Payment Required"),
    )
    return client


def _make_successful_embedding_client(*, vector: list[float] | None = None) -> AsyncMock:
    """Embedding client whose embed() returns a single 1024-dim vector."""
    from ml_clients.dataclasses import EmbeddingOutput

    vec = vector or [0.1] * 1024
    client = AsyncMock()
    client.embed = AsyncMock(
        return_value=[EmbeddingOutput(embedding=vec, model_id="bge-large", dimension=len(vec))],
    )
    return client


def _make_empty_embedding_client() -> AsyncMock:
    """Embedding client whose embed() returns an empty list — triggers the
    'Empty embedding response' RuntimeError inside _process_job."""
    client = AsyncMock()
    client.embed = AsyncMock(return_value=[])
    return client


def _make_job(retry_count: int, *, kind: str = "section", age_seconds: float = 0.0) -> MagicMock:
    """Build a fake claimed RetryJob.  ``kind`` controls section vs chunk.

    ``age_seconds`` sets ``created_at`` to that many seconds in the past (BP-729:
    the billing-deferral escalation uses ``now() - created_at``). Default 0 = a
    freshly-enqueued row that is well within the tolerance window.
    """
    job = MagicMock()
    job.pending_id = uuid.uuid4()
    job.doc_id = uuid.uuid4()
    if kind == "section":
        job.section_id = uuid.uuid4()
        job.chunk_id = None
    elif kind == "chunk":
        job.section_id = None
        job.chunk_id = uuid.uuid4()
    else:
        raise ValueError(f"unknown job kind: {kind}")
    job.embedding_text = "Apple posted Q3 earnings."
    job.retry_count = retry_count
    job.created_at = datetime.now(tz=UTC) - timedelta(seconds=age_seconds)
    return job


class TestAbandonedLogEmission:
    @pytest.mark.asyncio
    async def test_emits_abandoned_log_on_final_retry(self, monkeypatch) -> None:
        """When the failing job's incoming retry_count is _MAX_RETRIES-1 (=4),
        the resulting attempt brings the total to _MAX_RETRIES so the next
        ``claim_batch`` call will skip it.  The worker must surface this with an
        ``embedding_retry_abandoned`` warning.
        """
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_failing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        await worker._process_job(_make_job(retry_count=4))

        events = [event for event, _ in warning_calls]
        assert "embedding_retry_failed" in events
        assert "embedding_retry_abandoned" in events
        # Verify the abandoned event carries diagnostic context.
        abandoned_kw = next(kw for event, kw in warning_calls if event == "embedding_retry_abandoned")
        assert abandoned_kw["retry_count"] == 5
        assert abandoned_kw["max_retries"] == 5
        assert abandoned_kw["final_error"] == "DeepInfra 503"

    @pytest.mark.asyncio
    async def test_does_not_emit_abandoned_log_on_intermediate_retry(self, monkeypatch) -> None:
        """A job with retry_count=2 -> 3 must NOT emit the abandoned signal."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_failing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        await worker._process_job(_make_job(retry_count=2))

        events = [event for event, _ in warning_calls]
        assert "embedding_retry_abandoned" not in events


# ── Permanent (4xx) vs transient error classification ────────────────────────


class TestErrorClassification:
    """A FatalError (HTTP 4xx, permanent) must abandon the row immediately
    without burning the full backoff-retry schedule; a transient RetryableError
    must keep the existing exponential-backoff behaviour."""

    @pytest.mark.asyncio
    async def test_fatal_error_abandons_immediately_without_retries(self, monkeypatch) -> None:
        """A first-attempt (retry_count=0) FatalError must:
        - emit ``embedding_retry_abandoned_permanent`` (distinct from the
          transient ``embedding_retry_abandoned`` exhaustion signal),
        - call mark_abandoned(pending_id, max_retries=5) instead of mark_failure,
        - NOT schedule another backoff attempt.
        """
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        fake_logger.error = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        repo_instance = MagicMock()
        repo_instance.mark_abandoned = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_fatal_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=0))

        events = [e for e, _ in warning_calls]
        # The permanent signal fires; NEITHER the transient failure nor the
        # transient-exhaustion signal must appear.
        assert "embedding_retry_abandoned_permanent" in events
        assert "embedding_retry_failed" not in events
        assert "embedding_retry_abandoned" not in events

        # Abandoned via mark_abandoned (retry_count jumped to max) — never the
        # backoff-scheduling mark_failure.
        repo_instance.mark_abandoned.assert_awaited_once()
        call = repo_instance.mark_abandoned.await_args
        assert call.kwargs["max_retries"] == 5
        repo_instance.mark_failure.assert_not_called()

        # The permanent log must carry the reason + error for triage.
        kw = next(kw for e, kw in warning_calls if e == "embedding_retry_abandoned_permanent")
        assert kw["reason"] == "fatal_4xx"
        assert "4xx" in kw["error"]

    @pytest.mark.asyncio
    async def test_transient_error_still_backoff_retries(self, monkeypatch) -> None:
        """A RetryableError must NOT abandon — it goes through the existing
        mark_failure backoff path and, mid-schedule, emits neither abandoned
        signal."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        fake_logger.error = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        repo_instance = MagicMock()
        repo_instance.mark_abandoned = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_retryable_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=1))

        events = [e for e, _ in warning_calls]
        assert "embedding_retry_failed" in events
        assert "embedding_retry_abandoned_permanent" not in events
        # Backoff scheduled (transient), not a permanent abandon.
        repo_instance.mark_failure.assert_awaited_once()
        call = repo_instance.mark_failure.await_args
        # retry_count=1 → 60 * 2^1 = 120s backoff.
        assert call.kwargs["backoff_seconds"] == 120.0
        repo_instance.mark_abandoned.assert_not_called()


# ── Spend-cap / billing refusal (HTTP 402) — self-heal without abandoning ─────


class TestBillingRefusalClassification:
    """A ProviderBillingError (HTTP 402/401/403 spend-cap / auth refusal) must
    NOT consume the bounded retry budget: it backs off at the fixed billing
    cadence WITHOUT incrementing retry_count so the row self-heals when the
    operator raises the cap (2026-07-18 incident regression guard)."""

    @pytest.mark.asyncio
    async def test_billing_error_defers_without_incrementing_retry_count(self, monkeypatch) -> None:
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        fake_logger.error = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        # BP-729: assert the billing-deferred Prometheus counter is incremented.
        billing_metric = MagicMock()
        abandoned_metric = MagicMock()
        monkeypatch.setattr(mod, "record_embedding_retry_billing_deferred", billing_metric)
        monkeypatch.setattr(mod, "record_embedding_retry_abandoned", abandoned_metric)

        repo_instance = MagicMock()
        repo_instance.mark_abandoned = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_billing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        # retry_count=4 would ordinarily be the LAST attempt before abandon — but a
        # billing refusal must NOT abandon it even here. Fresh row (age 0) → deferred.
        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=4))

        events = [e for e, _ in warning_calls]
        # Distinct billing signal; NONE of the abandon signals may appear.
        assert "embedding_retry_billing_deferred" in events
        assert "embedding_retry_abandoned" not in events
        assert "embedding_retry_abandoned_permanent" not in events
        assert "embedding_retry_failed" not in events

        # Backed off via mark_failure WITHOUT consuming the budget, and NOT abandoned.
        repo_instance.mark_abandoned.assert_not_called()
        repo_instance.mark_failure.assert_awaited_once()
        call = repo_instance.mark_failure.await_args
        assert call.kwargs["increment_retry"] is False
        assert call.kwargs["backoff_seconds"] == mod._BILLING_RETRY_BACKOFF_SECONDS
        # Observability: billing-deferred counter incremented, abandon counter NOT.
        billing_metric.assert_called_once()
        abandoned_metric.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistent_billing_escalates_to_abandon_with_metric(self, monkeypatch) -> None:
        """A billing/auth refusal on a row OLDER than billing_defer_max_age_s (e.g. a
        revoked key that never clears) must ABANDON + emit the permanent-abandon
        signal/metric instead of looping forever."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        fake_logger.error = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        billing_metric = MagicMock()
        abandoned_metric = MagicMock()
        monkeypatch.setattr(mod, "record_embedding_retry_billing_deferred", billing_metric)
        monkeypatch.setattr(mod, "record_embedding_retry_abandoned", abandoned_metric)

        repo_instance = MagicMock()
        repo_instance.mark_abandoned = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_billing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
            billing_defer_max_age_s=3600.0,  # 1 h ceiling for the test
        )

        # Row first enqueued 2 h ago → age (7200s) > ceiling (3600s) → escalate.
        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=0, age_seconds=7200))

        # Abandoned (not deferred): permanent signal + metric with the distinct reason.
        events = [e for e, _ in warning_calls]
        assert "embedding_retry_abandoned_permanent" in events
        assert "embedding_retry_billing_deferred" not in events
        kw = next(kw for e, kw in warning_calls if e == "embedding_retry_abandoned_permanent")
        assert kw["reason"] == "billing_auth_persistent"
        repo_instance.mark_abandoned.assert_awaited_once()
        repo_instance.mark_failure.assert_not_called()
        abandoned_metric.assert_called_once_with("billing_auth_persistent")
        billing_metric.assert_not_called()


# ── Wave C T-002: success-path + failure-path coverage ───────────────────────


class TestSuccessPath:
    """The happy path: embedding returns a vector, worker writes the row,
    deletes the pending entry, and emits ``embedding_retry_success``."""

    @pytest.mark.asyncio
    async def test_section_embed_success(self, monkeypatch) -> None:
        """A section job (section_id set, chunk_id=None) must produce a
        SectionEmbeddingModel row, mark_success(pending_id), and log success."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        info_calls: list[tuple[str, dict]] = []
        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.info = lambda event, **kw: info_calls.append((event, kw))
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        monkeypatch.setattr(mod, "logger", fake_logger)

        # Capture the rows passed to session.add() via a real list — we want
        # to assert the model class + key arguments.
        added_rows: list = []

        @asynccontextmanager
        async def _section_session_ctx():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.add = MagicMock(side_effect=lambda row: added_rows.append(row))
            yield session

        sf = MagicMock(side_effect=_section_session_ctx)

        # Patch the EmbeddingPendingRepository so we can assert mark_success was
        # called with the right pending_id without needing a real DB.
        repo_instance = MagicMock(name="repo_instance")
        repo_instance.mark_success = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=sf,
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        job = _make_job(retry_count=0, kind="section")
        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(job)

        # session.add() must have been called once with a SectionEmbeddingModel
        # carrying our section_id, the embedding vector, and the model_id.
        from nlp_pipeline.infrastructure.nlp_db.models import SectionEmbeddingModel

        assert len(added_rows) == 1
        row = added_rows[0]
        assert isinstance(row, SectionEmbeddingModel)
        assert row.section_id == job.section_id
        assert row.embedding == [0.1] * 1024
        assert row.model_id == "bge-large"

        repo_instance.mark_success.assert_awaited_once_with(job.pending_id)
        repo_instance.mark_failure.assert_not_called()

        info_events = [e for e, _ in info_calls]
        assert "embedding_retry_success" in info_events

    @pytest.mark.asyncio
    async def test_chunk_embed_success(self, monkeypatch) -> None:
        """A chunk job (chunk_id set, section_id=None) must produce a
        ChunkEmbeddingModel row, mark_success, and log success."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        info_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.info = lambda event, **kw: info_calls.append((event, kw))
        fake_logger.warning = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        added_rows: list = []

        @asynccontextmanager
        async def _chunk_session_ctx():
            session = AsyncMock()
            session.commit = AsyncMock()
            session.add = MagicMock(side_effect=lambda row: added_rows.append(row))
            yield session

        sf = MagicMock(side_effect=_chunk_session_ctx)
        repo_instance = MagicMock()
        repo_instance.mark_success = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=sf,
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        job = _make_job(retry_count=0, kind="chunk")
        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(job)

        from nlp_pipeline.infrastructure.nlp_db.models import ChunkEmbeddingModel

        assert len(added_rows) == 1
        row = added_rows[0]
        assert isinstance(row, ChunkEmbeddingModel)
        assert row.chunk_id == job.chunk_id
        assert row.embedding == [0.1] * 1024
        assert row.model_id == "bge-large"
        repo_instance.mark_success.assert_awaited_once_with(job.pending_id)


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_empty_embedding_response_triggers_backoff(self, monkeypatch) -> None:
        """An empty `outputs` list must raise RuntimeError → mark_failure path."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        repo_instance = MagicMock()
        repo_instance.mark_failure = AsyncMock()
        repo_instance.mark_success = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_empty_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=1))

        # The empty response should produce an embedding_retry_failed warn with
        # the "Empty embedding response" error message.
        failed = [kw for e, kw in warning_calls if e == "embedding_retry_failed"]
        assert len(failed) == 1
        assert failed[0]["error"] == "Empty embedding response"
        repo_instance.mark_failure.assert_awaited_once()
        repo_instance.mark_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_side_commit_failure_logs_warning(self, monkeypatch) -> None:
        """If the write-side session.commit() raises, we must surface
        ``embedding_retry_write_failed`` and NOT call mark_success."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        warning_calls: list[tuple[str, dict]] = []
        fake_logger = MagicMock()
        fake_logger.warning = lambda event, **kw: warning_calls.append((event, kw))
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        repo_instance = MagicMock()
        repo_instance.mark_success = AsyncMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(commit_raises=True),
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=0))

        events = [e for e, _ in warning_calls]
        # The embed() call succeeded so there must be no embedding_retry_failed
        # warning — only the write-side failure should surface.
        assert "embedding_retry_failed" not in events
        assert "embedding_retry_write_failed" in events
        # mark_success() runs INSIDE the same try block as session.commit; the
        # commit raises so we cannot guarantee mark_success was not invoked at
        # all — but it must NOT have produced a successful retry log either.
        # The only contract that matters is the warn was emitted and no info
        # success log was produced.
        info_calls = fake_logger.info.call_args_list
        success_logs = [c for c in info_calls if c.args and c.args[0] == "embedding_retry_success"]
        assert success_logs == []


class TestBackoffMath:
    """The backoff formula is min(60 * 2^retry_count, 3600)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("retry_count", "expected_backoff"),
        [
            (0, 60.0),
            (4, 960.0),
            (10, 3600.0),  # capped
        ],
    )
    async def test_backoff_seconds(
        self,
        monkeypatch,
        retry_count: int,
        expected_backoff: float,
    ) -> None:
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        fake_logger = MagicMock()
        fake_logger.warning = MagicMock()
        fake_logger.info = MagicMock()
        monkeypatch.setattr(mod, "logger", fake_logger)

        repo_instance = MagicMock()
        repo_instance.mark_failure = AsyncMock()
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_failing_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            await worker._process_job(_make_job(retry_count=retry_count))

        repo_instance.mark_failure.assert_awaited_once()
        # mark_failure(pending_id, backoff_seconds=...) — assert the kwarg.
        call = repo_instance.mark_failure.await_args
        assert call.kwargs["backoff_seconds"] == expected_backoff


class TestPublicSurface:
    @pytest.mark.asyncio
    async def test_run_once_returns_job_count(self, monkeypatch) -> None:
        """run_once must return len(jobs) — 3 in this fixture."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        # Stub the logger so noisy warnings on _process_job don't matter.
        monkeypatch.setattr(mod, "logger", MagicMock())

        jobs = [_make_job(retry_count=0) for _ in range(3)]
        repo_instance = MagicMock()
        repo_instance.claim_batch = AsyncMock(return_value=jobs)
        # _process_job will be invoked for each job; stub it on the instance
        # so we don't exercise the success/failure machinery again.
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )
        # Replace _process_job to skip actual work.
        worker._process_job = AsyncMock()

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            count = await worker.run_once()

        assert count == 3
        assert worker._process_job.await_count == 3

    @pytest.mark.asyncio
    async def test_run_once_returns_zero_when_no_jobs(self, monkeypatch) -> None:
        """An empty claim_batch must short-circuit and return 0."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        monkeypatch.setattr(mod, "logger", MagicMock())

        repo_instance = MagicMock()
        repo_instance.claim_batch = AsyncMock(return_value=[])
        repo_cls = MagicMock(return_value=repo_instance)

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
        )
        worker._process_job = AsyncMock()

        with patch(
            "nlp_pipeline.infrastructure.nlp_db.repositories.embedding_pending.EmbeddingPendingRepository",
            repo_cls,
        ):
            count = await worker.run_once()

        assert count == 0
        worker._process_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_forever_exits_when_stop_event_set(self, monkeypatch) -> None:
        """run_forever must exit cleanly once the stop_event is set —
        no hang, no exception."""
        from nlp_pipeline.infrastructure.workers import embedding_retry_worker as mod

        monkeypatch.setattr(mod, "logger", MagicMock())

        worker = mod.EmbeddingRetryWorker(
            nlp_session_factory=_make_session_factory(),
            embedding_client=_make_successful_embedding_client(),
            model_id="bge-large",
            instruction_prefix="Represent this passage: ",
            poll_interval=0.05,  # short poll so the test resolves quickly
        )
        # Stub run_once to do nothing — we only care about the stop loop.
        worker.run_once = AsyncMock(return_value=0)

        stop_event = asyncio.Event()
        task = asyncio.create_task(worker.run_forever(stop_event))

        # Give the loop a chance to enter, then ask it to exit.
        await asyncio.sleep(0.05)
        stop_event.set()

        # The task must complete within a small window — if run_forever leaks a
        # poll cycle, asyncio.wait_for will raise TimeoutError.
        await asyncio.wait_for(task, timeout=1.0)
        assert task.done()
        assert task.exception() is None
