"""Unit tests for SummaryWorker (T-D-3-06) — Worker 13C."""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_REL_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation.RelationRepository"
_EV_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence.RelationEvidenceRepository"
_SUM_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary.RelationSummaryRepository"


def _make_session(
    stale_relations: list,
    evidence_rows: list,
    existing_summary: dict | None,
    *,
    raw_fallback_rows: list | None = None,
) -> tuple:
    """Return (sf, _session, rel_repo, ev_repo, sum_repo).

    ``raw_fallback_rows`` is what ``get_raw_for_relation_id`` returns (default []).
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    mock_rel_repo = AsyncMock()
    mock_rel_repo.fetch_stale_summary = AsyncMock(return_value=stale_relations)
    mock_rel_repo.mark_summary_updated = AsyncMock()

    mock_ev_repo = AsyncMock()
    mock_ev_repo.get_all_for_relation = AsyncMock(return_value=evidence_rows)
    mock_ev_repo.get_raw_for_relation_id = AsyncMock(return_value=raw_fallback_rows or [])

    mock_summary_repo = AsyncMock()
    mock_summary_repo.get_current = AsyncMock(return_value=existing_summary)
    mock_summary_repo.insert_new = AsyncMock()

    return sf, session, mock_rel_repo, mock_ev_repo, mock_summary_repo


class TestSummaryWorkerHashSkip:
    def test_same_hash_skips_llm_call(self) -> None:
        """Same evidence hash -> LLM extract() never called, mark_summary_updated still called."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        evidence_texts = ["Company A acquired Company B.", "Deal closed in Q3 2025."]
        combined = "\n".join(sorted(evidence_texts))
        evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

        evidence_rows = [{"evidence_text": t, "canonicalized_evidence_text": None} for t in evidence_texts]
        existing_summary = {"evidence_hash": evidence_hash, "summary_text": "old summary"}
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000001"}]

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, existing_summary)

        llm = AsyncMock()
        llm.extract = AsyncMock()

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        llm.extract.assert_not_awaited()
        mock_rel.mark_summary_updated.assert_awaited_once()
        mock_sum.insert_new.assert_not_awaited()

    def test_different_hash_calls_llm(self) -> None:
        """Different evidence hash -> LLM is called, insert_new called."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        evidence_texts = ["New evidence about merger."]
        evidence_rows = [{"evidence_text": t, "canonicalized_evidence_text": None} for t in evidence_texts]
        old_summary = {"evidence_hash": "deadbeef" * 8, "summary_text": "old"}
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000002"}]

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, old_summary)

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(
                result={"summary": "New LLM summary."},
                raw_response="ok",
                model_id="m",
            )
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        llm.extract.assert_awaited_once()
        mock_sum.insert_new.assert_awaited_once()
        mock_rel.mark_summary_updated.assert_awaited_once()

    def test_no_stale_relations_no_llm(self) -> None:
        """Empty stale list -> nothing called."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session([], [], None)

        llm = AsyncMock()
        llm.extract = AsyncMock()

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        llm.extract.assert_not_awaited()
        mock_sum.insert_new.assert_not_awaited()

    def test_no_evidence_rows_skips_relation(self) -> None:
        """Relation with no evidence rows is skipped (LLM not called)."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000003"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, [], None)

        llm = AsyncMock()
        llm.extract = AsyncMock()

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        llm.extract.assert_not_awaited()
        mock_sum.insert_new.assert_not_awaited()


class TestSummaryWorkerRawFallback:
    """BP-343: SummaryWorker falls back to relation_evidence_raw when immutable table is empty."""

    def test_falls_back_to_raw_when_immutable_empty(self) -> None:
        """get_all_for_relation returns [] → get_raw_for_relation_id called and used."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        raw_rows = [
            {"evidence_text": "Apple reported record revenue.", "canonicalized_evidence_text": None},
            {"evidence_text": "Tim Cook cited iPhone sales growth.", "canonicalized_evidence_text": None},
        ]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000010"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(
            stale_relations,
            [],  # immutable table empty
            None,
            raw_fallback_rows=raw_rows,
        )

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(
                result={"summary": "Apple had strong performance."},
                raw_response="ok",
                model_id="m",
            )
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        mock_ev.get_raw_for_relation_id.assert_awaited_once()
        llm.extract.assert_awaited_once()
        mock_sum.insert_new.assert_awaited_once()

    def test_skips_when_both_tables_empty(self) -> None:
        """Both immutable and raw return [] → LLM never called."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000011"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(
            stale_relations,
            [],
            None,
            raw_fallback_rows=[],
        )

        llm = AsyncMock()
        llm.extract = AsyncMock()

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        mock_ev.get_raw_for_relation_id.assert_awaited_once()
        llm.extract.assert_not_awaited()
        mock_sum.insert_new.assert_not_awaited()

    def test_uses_immutable_when_present_does_not_query_raw(self) -> None:
        """When immutable table has rows, raw fallback is never queried."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        immutable_rows = [{"evidence_text": "Apple grew revenue.", "canonicalized_evidence_text": None}]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000012"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(
            stale_relations,
            immutable_rows,
            None,
            raw_fallback_rows=[{"evidence_text": "should not be used", "canonicalized_evidence_text": None}],
        )

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "ok"}, raw_response="ok", model_id="m")
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            asyncio.run(worker.run())

        mock_ev.get_raw_for_relation_id.assert_not_awaited()
        llm.extract.assert_awaited_once()
