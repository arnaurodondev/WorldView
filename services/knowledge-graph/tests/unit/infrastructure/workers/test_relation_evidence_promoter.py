"""Unit tests for RelationEvidencePromoterWorker (Worker 13B — SA-2).

Covers:
  * happy-path promotion: N rows fetched + inserted → promoted count correct
  * empty batch: nothing to promote → promoted=0, no error
  * idempotency: ON CONFLICT DO NOTHING means double-run is safe
  * DB error: session.execute raises → worker re-raises (APScheduler records)
  * diagnostic counts (blocked_provisional, no_match) are present in log record
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

# Path helpers for patching SQLAlchemy text() inside the worker module.
_WORKER_MODULE = "knowledge_graph.infrastructure.workers.relation_evidence_promoter"


def _make_fetch_row(idx: int) -> tuple:
    """Return a fake fetchall row tuple matching the SELECT column order."""
    from datetime import datetime

    return (
        f"raw-id-{idx}",  # raw_id
        f"00000000-0000-0000-0000-{idx:012d}",  # relation_id
        f"10000000-0000-0000-0000-{idx:012d}",  # doc_id
        f"20000000-0000-0000-0000-{idx:012d}",  # chunk_id
        f"Evidence text {idx}.",  # evidence_text
        0.85,  # extraction_confidence
        1.0,  # source_weight
        datetime(2025, 1, 1, tzinfo=UTC),  # evidence_date
        None,  # claim_id (nullable)
    )


def _make_session_factory(
    fetch_rows: list, prov_count: int = 5, no_match_count: int = 3
) -> tuple[MagicMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build a session_factory mock that returns ``fetch_rows`` on the first
    execute() call, then scalar counts for the two diagnostic queries.

    Returns (sf, session1, session2, session3) so callers can inspect sessions
    BEFORE the iterator is consumed by run().
    """
    # We need three separate sessions:
    #   1. Fetch + insert session (returns fetch_rows on execute)
    #   2. COUNT provisional session
    #   3. COUNT no_match session

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

    sf = MagicMock()
    # Each sf() call returns the next session in sequence.
    sf.side_effect = [session1, session2, session3]
    return sf, session1, session2, session3


class TestRelationEvidencePromoterHappyPath:
    """Normal promotion of N rows."""

    def test_promotes_three_rows(self) -> None:
        """3 promotable rows → promoted=3, insert executed 3 times, commit called once."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        rows = [_make_fetch_row(i) for i in range(3)]
        sf, session1, _s2, _s3 = _make_session_factory(rows)

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
        sf, *_ = _make_session_factory(rows, prov_count=10, no_match_count=1)

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


class TestRelationEvidencePromoterEmptyBatch:
    """No rows to promote — must be a no-op."""

    def test_empty_batch_no_inserts(self) -> None:
        """Empty fetch result → promoted=0, no insert calls, commit still called."""
        from knowledge_graph.infrastructure.workers.relation_evidence_promoter import (
            RelationEvidencePromoterWorker,
        )

        sf, session1, _s2, _s3 = _make_session_factory([])
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
