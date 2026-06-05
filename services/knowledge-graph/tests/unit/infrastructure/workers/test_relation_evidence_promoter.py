"""Unit tests for RelationEvidencePromoterWorker (Worker 13B — SA-2 + E-3).

Covers:
  * happy-path promotion: N rows fetched + inserted → promoted count correct
  * empty batch: nothing to promote → promoted=0, no error
  * idempotency: ON CONFLICT DO NOTHING means double-run is safe
  * DB error: session.execute raises → worker re-raises (APScheduler records)
  * diagnostic counts (blocked_provisional, no_match, gated_quality) present in log
  * E-3 quality gate: high-confidence rows promoted regardless of density
  * E-3 quality gate: low-confidence + high-density rows ARE promoted
  * E-3 quality gate: low-confidence + low-density rows are NOT promoted
  * gated_quality log field is present and accurate
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# Path helpers for patching SQLAlchemy text() inside the worker module.
_WORKER_MODULE = "knowledge_graph.infrastructure.workers.relation_evidence_promoter"


def _make_fetch_row(idx: int, extraction_confidence: float = 0.85) -> tuple:
    """Return a fake fetchall row tuple matching the SELECT column order.

    ``extraction_confidence`` defaults to 0.85 (above the 0.70 gate threshold)
    so existing tests remain unaffected.  Pass a lower value to test the gate.
    """
    from datetime import datetime

    return (
        f"raw-id-{idx}",  # raw_id
        f"00000000-0000-0000-0000-{idx:012d}",  # relation_id
        f"10000000-0000-0000-0000-{idx:012d}",  # doc_id
        f"20000000-0000-0000-0000-{idx:012d}",  # chunk_id
        f"Evidence text {idx}.",  # evidence_text
        extraction_confidence,  # extraction_confidence
        1.0,  # source_weight
        datetime(2025, 1, 1, tzinfo=UTC),  # evidence_date
        None,  # claim_id (nullable)
    )


def _make_session_factory(
    fetch_rows: list,
    prov_count: int = 5,
    no_match_count: int = 3,
    gated_quality_count: int = 0,
) -> tuple[MagicMock, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build a session_factory mock that returns ``fetch_rows`` on the first
    execute() call, then scalar counts for the three diagnostic queries.

    Returns (sf, session1, session2, session3, session4) so callers can inspect
    sessions BEFORE the iterator is consumed by run().

    Sessions:
      1. Fetch + insert session (returns fetch_rows on SELECT, dummy on INSERTs)
      2. COUNT provisional session
      3. COUNT no_match session
      4. COUNT gated_quality session (E-3 diagnostic)
    """
    # --- Session 1: fetch + insert ---
    fetch_result = MagicMock()
    fetch_result.fetchall = MagicMock(return_value=fetch_rows)

    session1 = AsyncMock()
    session1.__aenter__ = AsyncMock(return_value=session1)
    session1.__aexit__ = AsyncMock(return_value=False)
    session1.commit = AsyncMock()
    # First execute() returns the fetch result; subsequent execute() calls
    # (inserts) return a dummy result.
    insert_result = MagicMock()
    session1.execute = AsyncMock(side_effect=[fetch_result] + [insert_result] * len(fetch_rows))

    # --- Session 2: provisional count ---
    prov_result = MagicMock()
    prov_result.scalar = MagicMock(return_value=prov_count)

    session2 = AsyncMock()
    session2.__aenter__ = AsyncMock(return_value=session2)
    session2.__aexit__ = AsyncMock(return_value=False)
    session2.execute = AsyncMock(return_value=prov_result)

    # --- Session 3: no_match count ---
    nm_result = MagicMock()
    nm_result.scalar = MagicMock(return_value=no_match_count)

    session3 = AsyncMock()
    session3.__aenter__ = AsyncMock(return_value=session3)
    session3.__aexit__ = AsyncMock(return_value=False)
    session3.execute = AsyncMock(return_value=nm_result)

    # --- Session 4: gated_quality count (E-3 diagnostic) ---
    gq_result = MagicMock()
    gq_result.scalar = MagicMock(return_value=gated_quality_count)

    session4 = AsyncMock()
    session4.__aenter__ = AsyncMock(return_value=session4)
    session4.__aexit__ = AsyncMock(return_value=False)
    session4.execute = AsyncMock(return_value=gq_result)

    sf = MagicMock()
    # Each sf() call returns the next session in sequence.
    sf.side_effect = [session1, session2, session3, session4]
    return sf, session1, session2, session3, session4


class TestRelationEvidencePromoterHappyPath:
    """Normal promotion of N rows."""

    def test_promotes_three_rows(self) -> None:
        """3 promotable rows → promoted=3, insert executed 3 times, commit called once."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        rows = [_make_fetch_row(i) for i in range(3)]
        sf, session1, _s2, _s3, _s4 = _make_session_factory(rows)

        worker = RelationEvidencePromoterWorker(sf)
        asyncio.run(worker.run())

        # Session 1 should have been called with 1 fetch + 3 inserts = 4 executes total.
        # First execute was the SELECT, next 3 were INSERTs.
        assert session1.execute.await_count == 4
        session1.commit.assert_awaited_once()

    def test_promoted_count_logged(self) -> None:
        """relation_evidence_promoter_complete is logged with promoted=N."""
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        rows = [_make_fetch_row(i) for i in range(2)]
        sf, *_ = _make_session_factory(rows, prov_count=10, no_match_count=1, gated_quality_count=0)

        logged: list[tuple] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append((event, kw))
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            worker = RelationEvidencePromoterWorker(sf)
            asyncio.run(worker.run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        complete_events = [kw for ev, kw in logged if ev == "relation_evidence_promoter_complete"]
        assert complete_events, "relation_evidence_promoter_complete not logged"
        ev = complete_events[0]
        assert ev["promoted"] == 2
        assert ev["blocked_provisional"] == 10
        assert ev["no_match"] == 1
        # E-3: gated_quality must be present in log record.
        assert "gated_quality" in ev, "gated_quality field missing from log record"
        assert ev["gated_quality"] == 0


class TestRelationEvidencePromoterEmptyBatch:
    """No rows to promote — must be a no-op."""

    def test_empty_batch_no_inserts(self) -> None:
        """Empty fetch result → promoted=0, no insert calls, commit still called."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        sf, session1, _s2, _s3, _s4 = _make_session_factory([])
        worker = RelationEvidencePromoterWorker(sf)
        asyncio.run(worker.run())  # must not raise

        # Session 1: only the SELECT was executed (no inserts).
        assert session1.execute.await_count == 1  # SELECT only
        session1.commit.assert_awaited_once()

    def test_empty_batch_logs_zero_promoted(self) -> None:
        """promoted=0 is logged after an empty batch."""
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        logged: list[tuple] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append((event, kw))
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            sf, *_ = _make_session_factory([])
            worker = RelationEvidencePromoterWorker(sf)
            asyncio.run(worker.run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        events = [kw for ev, kw in logged if ev == "relation_evidence_promoter_complete"]
        assert events
        assert events[0]["promoted"] == 0


class TestRelationEvidencePromoterDbError:
    """Session raises on execute → worker propagates the exception."""

    def test_db_error_propagates(self) -> None:
        """RuntimeError from session.execute → run() raises (APScheduler records)."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        sf = MagicMock()
        sf.return_value = session

        worker = RelationEvidencePromoterWorker(sf)
        with pytest.raises(RuntimeError, match="DB connection lost"):
            asyncio.run(worker.run())


class TestRelationEvidencePromoterIdempotency:
    """Two consecutive runs must be safe (ON CONFLICT DO NOTHING guard)."""

    def test_second_run_promotes_zero_when_already_done(self) -> None:
        """Second run with an empty fetch result → no-op (idempotent)."""
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        counts: list[int] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            if event == "relation_evidence_promoter_complete":
                counts.append(kw["promoted"])  # type: ignore[arg-type]
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            # Run 1: 1 row promoted.
            sf1, *_ = _make_session_factory([_make_fetch_row(0)])
            asyncio.run(RelationEvidencePromoterWorker(sf1).run())

            # Run 2: empty batch (as would happen if the row was already promoted).
            sf2, *_ = _make_session_factory([])
            asyncio.run(RelationEvidencePromoterWorker(sf2).run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        assert len(counts) == 2
        assert counts[0] == 1  # first run promoted one row
        assert counts[1] == 0  # second run found nothing new


class TestRelationEvidencePromoterSchedulerRegistration:
    """Worker 13B is registered in the scheduler and resolve_job returns non-stub."""

    def test_evidence_promotion_job_registered(self) -> None:
        """Scheduler registers 'worker_13b_evidence_promoter' job ID."""
        from unittest.mock import MagicMock

        from knowledge_graph.infrastructure.scheduler.scheduler import KnowledgeGraphScheduler

        settings = MagicMock()
        settings.worker_confidence_interval_s = 900
        settings.worker_contradiction_interval_s = 1800
        settings.worker_evidence_promote_interval_s = 300  # Worker 13B
        settings.worker_summary_interval_s = 3600
        settings.worker_definition_refresh_interval_s = 3600
        settings.worker_narrative_refresh_interval_s = 3600
        settings.worker_fundamentals_refresh_interval_s = 7200
        settings.worker_embedding_refresh_interval_s = 10800
        settings.worker_partition_interval_s = 86400
        settings.worker_provisional_enrichment_interval_s = 300
        settings.worker_age_sync_interval_s = 900

        # Build a minimal fake promoter worker.
        promoter = MagicMock()
        promoter.run = AsyncMock()

        scheduler = KnowledgeGraphScheduler(
            settings,
            workers={"evidence_promotion": promoter},
        )
        scheduler._register_jobs()

        job_ids = {job.id for job in scheduler._scheduler.get_jobs()}
        assert (
            "worker_13b_evidence_promoter" in job_ids
        ), f"worker_13b_evidence_promoter not found in registered jobs: {job_ids}"


# ── E-3 Quality Gate Tests ────────────────────────────────────────────────────


class TestRelationEvidencePromoterQualityGate:
    """E-3 quality gate: confidence threshold and density threshold behavior.

    The gate is implemented inside _FETCH_SQL (SQL-level filtering), so unit
    tests simulate gate behavior by controlling what the mock session returns:
    - rows returned by mock session1  →  rows that PASSED the SQL gate
    - gated_quality_count > 0         →  rows that were BLOCKED by the SQL gate
    """

    def test_high_confidence_rows_are_promoted(self) -> None:
        """Rows with extraction_confidence >= 0.70 are promoted regardless of density.

        The SQL gate passes them through, so the mock session returns them and
        we verify promoted == expected count.
        """
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            _CONF_THRESHOLD,
            RelationEvidencePromoterWorker,
        )

        # Rows at exactly the confidence threshold — should pass the SQL gate.
        high_conf_rows = [_make_fetch_row(i, extraction_confidence=_CONF_THRESHOLD) for i in range(3)]
        sf, *_ = _make_session_factory(high_conf_rows, gated_quality_count=0)

        worker = RelationEvidencePromoterWorker(sf)
        asyncio.run(worker.run())

        # All 3 high-confidence rows were returned by the gate → 3 inserts fired.
        _sf, session1, *_ = sf, *[None] * 4  # noqa: F841 — unpack to inspect  # type: ignore[misc]
        # Retrieve via the side_effect list tracking what sf() was called with.
        # Because _make_session_factory returns session1 as the 2nd tuple element:
        _, _session1_actual, *_ = _make_session_factory.__code__.co_varnames  # won't work
        # Simpler: just verify the worker itself saw promoted=3 by checking
        # that 4 execute calls happened on session1 (1 SELECT + 3 INSERTs).
        # We need session1 from the original factory call above.
        sf2, session1_check, *_ = _make_session_factory(high_conf_rows, gated_quality_count=0)
        worker2 = RelationEvidencePromoterWorker(sf2)
        asyncio.run(worker2.run())
        assert session1_check.execute.await_count == 4  # 1 SELECT + 3 INSERTs

    def test_high_confidence_rows_logged_as_promoted(self) -> None:
        """High-confidence rows are logged with promoted == count."""
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            _CONF_THRESHOLD,
            RelationEvidencePromoterWorker,
        )

        # Use confidence above threshold — these should be promoted.
        high_conf_rows = [_make_fetch_row(i, extraction_confidence=_CONF_THRESHOLD + 0.01) for i in range(2)]
        sf, *_ = _make_session_factory(high_conf_rows, gated_quality_count=0)

        logged: list[dict] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append({"event": event, **kw})  # type: ignore[arg-type]
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        complete = [e for e in logged if e["event"] == "relation_evidence_promoter_complete"]
        assert complete, "completion log not emitted"
        assert complete[0]["promoted"] == 2
        assert complete[0]["gated_quality"] == 0

    def test_low_confidence_high_density_rows_are_promoted(self) -> None:
        """Low-confidence rows with density >= density_threshold ARE promoted.

        The SQL gate passes them through (density condition satisfied), so the
        mock session1 returns them; promoted count is nonzero.
        """
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            _CONF_THRESHOLD,
            RelationEvidencePromoterWorker,
        )

        # Low confidence — below threshold.
        low_conf_rows = [_make_fetch_row(i, extraction_confidence=_CONF_THRESHOLD - 0.30) for i in range(2)]
        # gated_quality=0: no rows were held back, meaning density passed for these.
        sf, *_ = _make_session_factory(low_conf_rows, gated_quality_count=0)

        logged: list[dict] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append({"event": event, **kw})  # type: ignore[arg-type]
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        complete = [e for e in logged if e["event"] == "relation_evidence_promoter_complete"]
        assert complete, "completion log not emitted"
        # Low-confidence rows passed the density check → promoted.
        assert complete[0]["promoted"] == 2
        # No rows blocked by gate in this scenario.
        assert complete[0]["gated_quality"] == 0

    def test_low_confidence_low_density_rows_not_promoted(self) -> None:
        """Low-confidence, low-density rows are NOT promoted (gated).

        The SQL gate filters them out → session1 returns an empty fetchall,
        while the gated_quality diagnostic query returns a nonzero count.
        """
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        # The SQL gate blocked all 3 candidate rows → empty fetch result.
        # gated_quality_count=3 simulates the diagnostic count of gated rows.
        sf, *_ = _make_session_factory([], gated_quality_count=3)

        logged: list[dict] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append({"event": event, **kw})  # type: ignore[arg-type]
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        complete = [e for e in logged if e["event"] == "relation_evidence_promoter_complete"]
        assert complete, "completion log not emitted"
        # No rows passed the gate → promoted=0.
        assert complete[0]["promoted"] == 0
        # Diagnostic count shows 3 rows were held back by the quality gate.
        assert complete[0]["gated_quality"] == 3

    def test_gated_quality_field_always_present_in_log(self) -> None:
        """gated_quality key is always present in the completion log record."""
        import knowledge_graph.infrastructure.workers.relation_evidence_promoter as _mod
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        sf, *_ = _make_session_factory([_make_fetch_row(0)], gated_quality_count=0)

        logged: list[dict] = []
        orig_info = _mod.logger.info  # type: ignore[attr-defined]

        def _capture(event: str, **kw: object) -> None:  # type: ignore[return]
            logged.append({"event": event, **kw})  # type: ignore[arg-type]
            return orig_info(event, **kw)  # type: ignore[no-any-return]

        _mod.logger.info = _capture  # type: ignore[method-assign]
        try:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())
        finally:
            _mod.logger.info = orig_info  # type: ignore[method-assign]

        complete = [e for e in logged if e["event"] == "relation_evidence_promoter_complete"]
        assert complete, "completion log not emitted"
        assert (
            "gated_quality" in complete[0]
        ), "gated_quality field is missing from relation_evidence_promoter_complete log record"

    def test_prometheus_counter_incremented_when_gated(self) -> None:
        """Prometheus counter kg_evidence_quality_gated_total is incremented when gated_quality > 0."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        # 4 rows blocked by the gate.
        sf, *_ = _make_session_factory([], gated_quality_count=4)

        with patch(
            "knowledge_graph.infrastructure.workers.relation_evidence_promoter.kg_evidence_quality_gated_total"
        ) as mock_counter:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())

        # Counter should be incremented by 4 (the gated_quality count).
        mock_counter.inc.assert_called_once_with(4)

    def test_prometheus_counter_not_incremented_when_not_gated(self) -> None:
        """Prometheus counter is NOT incremented when gated_quality == 0."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        # All rows passed the gate.
        sf, *_ = _make_session_factory([_make_fetch_row(0)], gated_quality_count=0)

        with patch(
            "knowledge_graph.infrastructure.workers.relation_evidence_promoter.kg_evidence_quality_gated_total"
        ) as mock_counter:
            asyncio.run(RelationEvidencePromoterWorker(sf).run())

        mock_counter.inc.assert_not_called()

    def test_fetch_sql_passes_threshold_params(self) -> None:
        """run() passes conf_threshold and density_threshold to the fetch execute call."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            _BATCH_SIZE,
            _CONF_THRESHOLD,
            _DENSITY_THRESHOLD,
            RelationEvidencePromoterWorker,
        )

        sf, session1, *_ = _make_session_factory([])

        asyncio.run(RelationEvidencePromoterWorker(sf).run())

        # Inspect the first execute() call (the SELECT/fetch call).
        first_call_kwargs = session1.execute.call_args_list[0]
        # The second positional argument is the params dict.
        params = first_call_kwargs[0][1]  # positional args → (text_obj, params_dict)
        assert params["conf_threshold"] == _CONF_THRESHOLD
        assert params["density_threshold"] == _DENSITY_THRESHOLD
        assert params["batch_size"] == _BATCH_SIZE
