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


class TestSummaryWorkerEvidenceTextFallback:
    """T-72-2-02: canonicalized_evidence_text used when evidence_text IS NULL."""

    def test_uses_canonicalized_text_when_evidence_text_null(self) -> None:
        """Row with evidence_text=None and canonicalized_evidence_text → text used for summary."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        # Old str(None) bug: str(e.get("evidence_text", "")) → "None" (truthy non-empty str)
        # Fixed code: e.get("evidence_text") → None (falsy) → fallback to canonicalized_evidence_text
        evidence_rows = [
            {
                "evidence_text": None,
                "canonicalized_evidence_text": "Apple reported strong iPhone sales in Q3.",
            }
        ]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000020"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, None)

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(
                result={"summary": "Apple showed strong Q3 performance."},
                raw_response='{"summary": "Apple showed strong Q3 performance."}',
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

        # LLM should be called — the canonicalized text is valid evidence
        llm.extract.assert_awaited_once()
        mock_sum.insert_new.assert_awaited_once()

    def test_skips_when_both_evidence_columns_null(self) -> None:
        """Row with both evidence_text=None and canonicalized_evidence_text=None → skipped."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        evidence_rows = [{"evidence_text": None, "canonicalized_evidence_text": None}]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000021"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, None)

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

    def test_llm_raw_response_logged_before_parse(self) -> None:
        """LLM raw_response is logged (length+preview) before summary parse step."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        evidence_rows = [{"evidence_text": "Apple beat Q3 revenue targets.", "canonicalized_evidence_text": None}]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000022"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, None)

        raw_json = '{"summary": "Apple grew revenue in Q3."}'
        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(
                result={"summary": "Apple grew revenue in Q3."},
                raw_response=raw_json,
                model_id="kg-summary-v1",
            )
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm)
            # run() should not raise — diagnostic log is fire-and-forget
            asyncio.run(worker.run())

        llm.extract.assert_awaited_once()
        # summary must have been inserted with inlined model_id (no _SUMMARY_MODEL_ID constant)
        call_kwargs = mock_sum.insert_new.await_args.kwargs
        assert call_kwargs["model_id"] == "kg-summary-v1"


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


class TestSummaryWorkerSessionDiscipline:
    """DS-001: DB session must not be held open during LLM I/O."""

    def test_session_factory_called_multiple_times_per_relation(self) -> None:
        """Each DB phase opens its own session (≥3 calls for a hash-changed relation)."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        evidence_rows = [{"evidence_text": "Apple acquired Beats.", "canonicalized_evidence_text": None}]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000030"}]
        # No existing summary → hash will differ → LLM will be called → write phase fires.
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, None)

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

        # Phase 1 (fetch stale list) + Phase 2 (fetch evidence+summary) +
        # Phase 4 (write summary) = 3 calls minimum for one hash-changed relation.
        assert sf.call_count >= 3, f"Expected ≥3 session factory calls (DS-001 session discipline), got {sf.call_count}"
        llm.extract.assert_awaited_once()
        mock_sum.insert_new.assert_awaited_once()

    def test_hash_unchanged_skips_llm_and_uses_separate_write_session(self) -> None:
        """Hash-unchanged path: LLM skipped; write session still opened for mark_updated."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        evidence_texts = ["Stable evidence row."]
        combined = "\n".join(sorted(evidence_texts))
        evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

        evidence_rows = [{"evidence_text": evidence_texts[0], "canonicalized_evidence_text": None}]
        existing = {"evidence_hash": evidence_hash, "summary_text": "cached"}
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000031"}]

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, existing)

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
        # Phase 1 + Phase 2 + Phase 3a (hash-match write) = 3 calls.
        assert sf.call_count >= 3, f"Expected ≥3 session factory calls for hash-match path, got {sf.call_count}"
        mock_rel.mark_summary_updated.assert_awaited_once()


class TestSummaryWorkerAuditMetric:
    """DATA-008: canonicalized_text_null_count must not count raw-path rows."""

    def test_raw_path_rows_excluded_from_canonicalized_null_count(self) -> None:
        """Rows from relation_evidence_raw (no canonicalized_evidence_text key) are excluded."""

        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        # Raw rows — no 'canonicalized_evidence_text' key at all.
        raw_rows = [
            {"evidence_text": "Apple beat Q3 estimates."},
            {"evidence_text": "Revenue up 8% YoY."},
        ]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000040"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(
            stale_relations,
            [],  # immutable table empty → triggers raw fallback
            None,
            raw_fallback_rows=raw_rows,
        )

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "ok"}, raw_response="ok", model_id="m")
        )

        # Capture structured log calls by patching the module-level logger.
        logged_events: list[tuple] = []

        import knowledge_graph.infrastructure.workers.summary as _summary_mod

        original_logger_info = _summary_mod.logger.info  # type: ignore[attr-defined]

        def _capture_info(event: str, **kwargs: object) -> None:  # type: ignore[return]
            logged_events.append((event, kwargs))
            return original_logger_info(event, **kwargs)  # type: ignore[no-any-return]

        _summary_mod.logger.info = _capture_info  # type: ignore[method-assign]

        try:
            with (
                patch(_REL_REPO, return_value=mock_rel),
                patch(_EV_REPO, return_value=mock_ev),
                patch(_SUM_REPO, return_value=mock_sum),
            ):
                worker = SummaryWorker(sf, llm)
                asyncio.run(worker.run())
        finally:
            _summary_mod.logger.info = original_logger_info  # type: ignore[method-assign]

        # Find the audit log entry.
        audit_entries = [kw for ev, kw in logged_events if ev == "summary_worker_relation_evidence_audit"]
        assert audit_entries, "summary_worker_relation_evidence_audit not logged"
        audit = audit_entries[0]
        # Raw-path rows have no 'canonicalized_evidence_text' key, so the count must be 0.
        assert (
            audit["canonicalized_text_null_count"] == 0
        ), f"Expected 0 for raw-path rows (DATA-008), got {audit['canonicalized_text_null_count']}"

    def test_immutable_path_counts_null_canonicalized_text(self) -> None:
        """Immutable rows with canonicalized_evidence_text=None ARE counted as null."""
        import knowledge_graph.infrastructure.workers.summary as _summary_mod
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        # Immutable rows with the key present but value None.
        immutable_rows = [
            {"evidence_text": "Apple beat Q3.", "canonicalized_evidence_text": None},
            {"evidence_text": "iPhone sales up.", "canonicalized_evidence_text": "iPhone sales up."},
        ]
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000041"}]
        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, immutable_rows, None)

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "ok"}, raw_response="ok", model_id="m")
        )

        logged_events: list[tuple] = []
        original_logger_info = _summary_mod.logger.info  # type: ignore[attr-defined]

        def _capture_info(event: str, **kwargs: object) -> None:  # type: ignore[return]
            logged_events.append((event, kwargs))
            return original_logger_info(event, **kwargs)  # type: ignore[no-any-return]

        _summary_mod.logger.info = _capture_info  # type: ignore[method-assign]

        try:
            with (
                patch(_REL_REPO, return_value=mock_rel),
                patch(_EV_REPO, return_value=mock_ev),
                patch(_SUM_REPO, return_value=mock_sum),
            ):
                worker = SummaryWorker(sf, llm)
                asyncio.run(worker.run())
        finally:
            _summary_mod.logger.info = original_logger_info  # type: ignore[method-assign]

        audit_entries = [kw for ev, kw in logged_events if ev == "summary_worker_relation_evidence_audit"]
        assert audit_entries, "summary_worker_relation_evidence_audit not logged"
        audit = audit_entries[0]
        # One row has the key with None → count should be 1.
        assert (
            audit["canonicalized_text_null_count"] == 1
        ), f"Expected 1 for immutable row with null canonicalized text, got {audit['canonicalized_text_null_count']}"


class TestSummaryWorkerForceRegen:
    """ARCH-008: summary_worker_force_regen_batch_size skips hash check."""

    def test_force_regen_zero_respects_hash_skip(self) -> None:
        """Default force_regen_batch_size=0 → hash match still skips LLM."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker

        evidence_texts = ["Evidence row one."]
        combined = "\n".join(sorted(evidence_texts))
        evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

        evidence_rows = [{"evidence_text": evidence_texts[0], "canonicalized_evidence_text": None}]
        existing = {"evidence_hash": evidence_hash, "summary_text": "cached"}
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000050"}]

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, existing)
        llm = AsyncMock()
        llm.extract = AsyncMock()

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm, force_regen_batch_size=0)
            asyncio.run(worker.run())

        llm.extract.assert_not_awaited()
        mock_sum.insert_new.assert_not_awaited()

    def test_force_regen_nonzero_bypasses_hash_check(self) -> None:
        """force_regen_batch_size > 0 → LLM called even when hash matches."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        evidence_texts = ["Evidence row one."]
        combined = "\n".join(sorted(evidence_texts))
        evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

        # Existing summary has the SAME hash → normally would skip LLM.
        evidence_rows = [{"evidence_text": evidence_texts[0], "canonicalized_evidence_text": None}]
        existing = {"evidence_hash": evidence_hash, "summary_text": "old summary"}
        stale_relations = [{"relation_id": "00000000-0000-0000-0000-000000000051"}]

        sf, _session, mock_rel, mock_ev, mock_sum = _make_session(stale_relations, evidence_rows, existing)
        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "refreshed"}, raw_response="ok", model_id="m")
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm, force_regen_batch_size=5)
            asyncio.run(worker.run())

        # LLM must be called despite hash match.
        llm.extract.assert_awaited_once()
        mock_sum.insert_new.assert_awaited_once()

    def test_force_regen_cap_limits_forced_calls(self) -> None:
        """force_regen_batch_size=1 → only first relation is force-regenerated; second respects hash."""
        from knowledge_graph.infrastructure.workers.summary import SummaryWorker
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-untyped]

        evidence_text_a = "Evidence for relation A."
        evidence_text_b = "Evidence for relation B."
        hash_a = hashlib.sha256(evidence_text_a.encode()).hexdigest()
        hash_b = hashlib.sha256(evidence_text_b.encode()).hexdigest()

        # Both have matching hashes — only the first should bypass.
        stale_relations = [
            {"relation_id": "00000000-0000-0000-0000-000000000052"},
            {"relation_id": "00000000-0000-0000-0000-000000000053"},
        ]

        # Build separate evidence + existing for each relation using call_count routing.
        # Since both use the same mock we simulate with alternating side_effect.
        evidence_a = [{"evidence_text": evidence_text_a, "canonicalized_evidence_text": None}]
        evidence_b = [{"evidence_text": evidence_text_b, "canonicalized_evidence_text": None}]
        existing_a = {"evidence_hash": hash_a, "summary_text": "cached A"}
        existing_b = {"evidence_hash": hash_b, "summary_text": "cached B"}

        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.commit = AsyncMock()
        sf = MagicMock()
        sf.return_value = session

        mock_rel = AsyncMock()
        mock_rel.fetch_stale_summary = AsyncMock(return_value=stale_relations)
        mock_rel.mark_summary_updated = AsyncMock()

        mock_ev = AsyncMock()
        mock_ev.get_all_for_relation = AsyncMock(side_effect=[evidence_a, evidence_b])
        mock_ev.get_raw_for_relation_id = AsyncMock(return_value=[])

        mock_sum = AsyncMock()
        mock_sum.get_current = AsyncMock(side_effect=[existing_a, existing_b])
        mock_sum.insert_new = AsyncMock()

        llm = AsyncMock()
        llm.extract = AsyncMock(
            return_value=ExtractionOutput(result={"summary": "forced"}, raw_response="ok", model_id="m")
        )

        with (
            patch(_REL_REPO, return_value=mock_rel),
            patch(_EV_REPO, return_value=mock_ev),
            patch(_SUM_REPO, return_value=mock_sum),
        ):
            worker = SummaryWorker(sf, llm, force_regen_batch_size=1)
            asyncio.run(worker.run())

        # LLM called once (only first relation bypassed), second was skipped by hash.
        assert (
            llm.extract.await_count == 1
        ), f"Expected 1 LLM call (force_regen_batch_size=1), got {llm.extract.await_count}"
        assert (
            mock_sum.insert_new.await_count == 1
        ), f"Expected 1 insert_new call, got {mock_sum.insert_new.await_count}"
