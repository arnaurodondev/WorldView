"""Unit tests for KnowledgeGraphScheduler crash instrumentation (T-A-2-01).

Verifies that worker exceptions are:
  - counted in ``s7_worker_crash_total`` with the correct worker label
  - logged at ERROR level as ``kg_worker_crashed``
  - re-raised so APScheduler can apply coalesce/retry logic
  - NOT counted when a no-op stub runs without error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from knowledge_graph.infrastructure.scheduler.scheduler import KnowledgeGraphScheduler
from structlog.testing import capture_logs

pytestmark = pytest.mark.unit

_COUNTER_PATH = "knowledge_graph.infrastructure.scheduler.scheduler.s7_worker_crash_total"


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.worker_confidence_interval_s = 60
    s.worker_contradiction_interval_s = 60
    s.worker_summary_interval_s = 60
    s.worker_definition_refresh_interval_s = 60
    s.worker_narrative_refresh_interval_s = 60
    s.worker_fundamentals_refresh_interval_s = 60
    s.worker_embedding_refresh_interval_s = 60
    s.worker_partition_interval_s = 3600
    s.worker_age_sync_interval_s = 60
    s.worker_provisional_enrichment_interval_s = 600  # PLAN-0061 T-A-1
    return s


def _make_scheduler(workers: dict | None = None) -> KnowledgeGraphScheduler:
    return KnowledgeGraphScheduler(_make_settings(), workers=workers or {})


class TestWorkerCrashInstrumentation:
    @pytest.mark.asyncio
    async def test_worker_crash_increments_counter(self) -> None:
        """When a worker raises, s7_worker_crash_total is incremented with the worker label."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with patch(_COUNTER_PATH) as mock_counter:
            wrapped = scheduler._wrap_worker("my_worker", error_fn)
            with pytest.raises(RuntimeError):
                await wrapped()

        mock_counter.labels.assert_called_once_with(worker="my_worker")
        mock_counter.labels.return_value.inc.assert_called_once()

    @pytest.mark.asyncio
    async def test_worker_crash_logs_error(self) -> None:
        """When a worker raises, kg_worker_crashed is logged at ERROR with exc_info."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("boom"))

        with capture_logs() as cap:
            with patch(_COUNTER_PATH):
                wrapped = scheduler._wrap_worker("my_worker", error_fn)
                with pytest.raises(RuntimeError):
                    await wrapped()

        assert any(
            e.get("event") == "kg_worker_crashed" and e.get("log_level") == "error" for e in cap
        ), f"Expected 'kg_worker_crashed' error log not found in: {cap}"

    @pytest.mark.asyncio
    async def test_worker_crash_reraises(self) -> None:
        """Exception is re-raised after counter increment and logging (APScheduler needs it)."""
        scheduler = _make_scheduler()
        error_fn = AsyncMock(side_effect=RuntimeError("should be reraised"))

        with patch(_COUNTER_PATH):
            wrapped = scheduler._wrap_worker("my_worker", error_fn)
            with pytest.raises(RuntimeError, match="should be reraised"):
                await wrapped()

    @pytest.mark.asyncio
    async def test_stub_does_not_increment_counter(self) -> None:
        """A no-op stub run does not trigger the crash counter."""
        scheduler = _make_scheduler()  # no workers → stubs only

        with patch(_COUNTER_PATH) as mock_counter:
            stub = scheduler._resolve_job("confidence_recompute")
            await stub()

        mock_counter.labels.assert_not_called()


class TestProvisionalEnrichmentInterval:
    @pytest.mark.asyncio
    async def test_provisional_enrichment_uses_dedicated_interval(self) -> None:
        """Scheduler wires 'worker_13e_provisional' to worker_provisional_enrichment_interval_s.

        T-A-1: The old wiring used worker_embedding_refresh_interval_s (10800s = 3h).
        The correct interval is worker_provisional_enrichment_interval_s (600s = 10min).
        We verify by checking add_job() was called with seconds=600 for that job ID.
        """
        s = _make_settings()
        s.worker_embedding_refresh_interval_s = 9999  # wrong key — must NOT be used
        s.worker_provisional_enrichment_interval_s = 600  # correct key

        scheduler = _make_scheduler(workers={})
        scheduler._settings = s

        captured: list[dict] = []

        def _capture_add_job(fn, trigger, *args, id, max_instances, coalesce, **kwargs):  # noqa: A002
            captured.append({"trigger": trigger, "id": id, **kwargs})

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        prov = next((c for c in captured if c["id"] == "worker_13e_provisional"), None)
        assert prov is not None, "worker_13e_provisional job must be registered"
        assert prov.get("seconds") == 600, (
            f"Expected 600s interval for worker_13e_provisional, got {prov.get('seconds')}. "
            "The job must use worker_provisional_enrichment_interval_s, not "
            "worker_embedding_refresh_interval_s."
        )


class TestEmbeddingRefreshRegistration:
    """Regression guard for BP-092: Worker instantiated but never registered in _register_jobs().

    Worker 13F (EmbeddingRefreshWorker) was instantiated in build_workers() but never
    added to the jobs list in _register_jobs(), causing ALL relation_summaries.summary_embedding
    to remain NULL and the HNSW ANN search to return zero results.
    """

    def test_embedding_refresh_job_is_registered(self) -> None:
        """_register_jobs() must include worker_13f_embedding with the correct interval."""
        s = _make_settings()
        s.worker_embedding_refresh_interval_s = 10800

        scheduler = _make_scheduler(workers={})
        scheduler._settings = s

        captured: list[dict] = []

        def _capture_add_job(fn, trigger, *args, id, max_instances, coalesce, **kwargs):  # noqa: A002
            captured.append({"trigger": trigger, "id": id, **kwargs})

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        job = next((c for c in captured if c["id"] == "worker_13f_embedding"), None)
        assert job is not None, (
            "worker_13f_embedding must be registered in _register_jobs(). "
            "Without it, relation_summaries.summary_embedding stays NULL and "
            "HNSW ANN search on relations returns empty results (BP-092)."
        )
        assert job.get("seconds") == 10800, (
            f"Expected 10800s interval for worker_13f_embedding, got {job.get('seconds')}. "
            "Must use worker_embedding_refresh_interval_s."
        )

    def test_all_eleven_jobs_registered(self) -> None:
        """_register_jobs() must register exactly 11 jobs — no worker left unscheduled.

        11 = 10 interval jobs + 1 cron job (worker_13j_enrichment_sweep, PRD-0073).
        """
        expected_ids = {
            "worker_13a_confidence",
            "worker_13b_contradiction",
            "worker_13c_summary",
            "worker_13d1_definition",
            "worker_13d2_narrative",
            "worker_13d3_fundamentals",
            "worker_13e_provisional",
            "worker_13f_embedding",
            "worker_13f_partition",
            "worker_13f_age_sync",
            "worker_13j_enrichment_sweep",  # PRD-0073 daily cron at 02:00 UTC
        }

        scheduler = _make_scheduler(workers={})

        captured_ids: set[str] = set()

        def _capture_add_job(fn, trigger, *args, id, max_instances, coalesce, **kwargs):  # noqa: A002
            captured_ids.add(id)

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        missing = expected_ids - captured_ids
        assert not missing, (
            f"The following jobs were NOT registered: {missing}. "
            "All 11 workers must be scheduled (BP-092, PRD-0073)."
        )

    def test_embedding_refresh_uses_dedicated_interval_not_provisional(self) -> None:
        """worker_13f_embedding must use worker_embedding_refresh_interval_s, not provisional."""
        s = _make_settings()
        s.worker_embedding_refresh_interval_s = 10800
        s.worker_provisional_enrichment_interval_s = 300  # different value

        scheduler = _make_scheduler(workers={})
        scheduler._settings = s

        captured: list[dict] = []

        def _capture_add_job(fn, trigger, *args, id, max_instances, coalesce, **kwargs):  # noqa: A002
            captured.append({"trigger": trigger, "id": id, **kwargs})

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        emb = next((c for c in captured if c["id"] == "worker_13f_embedding"), None)
        assert emb is not None
        assert emb.get("seconds") == 10800, (
            f"worker_13f_embedding uses wrong interval {emb.get('seconds')}; "
            "must be worker_embedding_refresh_interval_s=10800, not "
            "worker_provisional_enrichment_interval_s=300."
        )

    def test_worker_13j_registered_as_cron_at_0200(self) -> None:
        """worker_13j_enrichment_sweep must be registered as a cron job at 02:00 UTC (PRD-0073)."""
        scheduler = _make_scheduler(workers={})

        captured: list[dict] = []

        def _capture_add_job(fn, trigger, *args, id, max_instances, coalesce, **kwargs):  # noqa: A002
            captured.append({"trigger": trigger, "id": id, **kwargs})

        with patch.object(scheduler._scheduler, "add_job", side_effect=_capture_add_job):
            scheduler._register_jobs()

        job = next((c for c in captured if c["id"] == "worker_13j_enrichment_sweep"), None)
        assert job is not None, "worker_13j_enrichment_sweep must be registered in _register_jobs()"
        assert (
            job["trigger"] == "cron"
        ), f"worker_13j must use 'cron' trigger (got '{job['trigger']}') — daily sweep at 02:00 UTC."
        assert job.get("hour") == 2, f"cron hour must be 2 (got {job.get('hour')})"
        assert job.get("minute") == 0, f"cron minute must be 0 (got {job.get('minute')})"


# ---------------------------------------------------------------------------
# DEF-034 (Wave B-5) — read/write factory split through build_workers()
# ---------------------------------------------------------------------------


class TestBuildWorkersReadWriteFactorySplit:
    """build_workers() must thread the read replica factory into split workers
    while keeping R23-EXEMPT workers (Confidence/Contradiction/MonthlyPartition)
    on the write factory only."""

    def _make_full_settings(self) -> MagicMock:
        """Settings stub broad enough that ``build_workers`` does not raise on
        attribute access from any worker constructor — read-only attributes
        only; no DB or LLM connections are made because the factories are
        themselves mocks and ``llm_client`` is None for the simplest path."""
        s = _make_settings()
        # Embedding/extraction are not exercised when llm_client is None, but
        # the structured-enrichment helper still reads description settings.
        s.description_provider = "null"
        s.description_deepinfra_concurrency = 1
        s.description_gemini_concurrency = 1
        s.deepinfra_api_key = MagicMock(get_secret_value=lambda: "")
        s.deepinfra_extraction_base_url = "https://api.deepinfra.com/v1/openai"
        s.gemini_api_key = MagicMock(get_secret_value=lambda: "")
        s.embedding_provider = "ollama"
        s.embedding_api_key = MagicMock(get_secret_value=lambda: "")
        s.embedding_api_model_id = "x"
        s.embedding_api_base_url = "x"
        s.embedding_model_id = "x"
        s.worker_embedding_batch_limit = 0
        s.market_data_internal_url = "http://localhost:9999"
        s.kafka_bootstrap_servers = "localhost:9092"
        s.kafka_topic_entity_dirtied = "entity.dirtied.v1"
        s.internal_jwt_private_key = MagicMock(get_secret_value=lambda: "")
        return s

    def test_build_workers_accepts_read_factory_kwarg(self) -> None:
        """``build_workers`` accepts a read_session_factory and stores it on
        every worker that participates in the R23 split."""
        from knowledge_graph.infrastructure.scheduler.scheduler import build_workers

        settings = self._make_full_settings()
        write_sf = MagicMock(name="write_factory")
        read_sf = MagicMock(name="read_factory")

        workers = build_workers(settings, write_sf, read_sf)

        # confidence_recompute is R23-EXEMPT — must NOT receive a read factory
        # (it should still be using the write factory exclusively).
        assert "confidence_recompute" in workers
        assert "contradiction_batch" in workers
        assert "partition_management" in workers

        # The structured-enrichment adapter is built unconditionally; assert
        # that its read factory equals the read factory passed in.
        sew = workers["structured_enrichment"]
        assert sew is not None
        # The adapter is the use case's enrichment_adapter; it stores the read
        # factory on ``_read_session_factory``.
        adapter = sew._adapter
        assert adapter._read_session_factory is read_sf, "EntityEnrichmentAdapter must use the read factory"
        assert adapter._sf is write_sf, "EntityEnrichmentAdapter writes must use the write factory"

    def test_build_workers_falls_back_when_read_factory_none(self) -> None:
        """When ``read_session_factory`` is None, every worker falls back to
        the write factory so existing call sites do not break."""
        from knowledge_graph.infrastructure.scheduler.scheduler import build_workers

        settings = self._make_full_settings()
        write_sf = MagicMock(name="write_factory")

        # No read factory — must fall back without raising AttributeError.
        workers = build_workers(settings, write_sf, None)

        sew = workers["structured_enrichment"]
        adapter = sew._adapter
        # Falls back to write factory when no read replica is configured.
        assert adapter._read_session_factory is write_sf
        assert adapter._sf is write_sf


# ── DEF-002: internal-JWT claims (aud + jti) ──────────────────────────────────


def test_build_market_data_signer_token_includes_aud_and_jti() -> None:
    """DEF-002: the signer's token MUST carry aud + a unique jti."""
    from unittest.mock import MagicMock

    import jwt as pyjwt
    from knowledge_graph.infrastructure.scheduler.scheduler import build_market_data_signer

    settings = MagicMock()
    settings.internal_jwt_private_key.get_secret_value.return_value = ""  # HS256 dev path
    sign = build_market_data_signer(settings)
    decoded = pyjwt.decode(sign(), options={"verify_signature": False})
    assert decoded["aud"] == "worldview-internal"
    assert decoded["iss"] == "worldview-gateway"
    assert decoded["sub"] == "system:kg-structured-enrichment"
    assert decoded["jti"]
