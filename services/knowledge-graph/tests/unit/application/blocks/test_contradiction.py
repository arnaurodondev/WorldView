"""Unit tests for Block 12b: contradiction detection hot path."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 28, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_contradiction_repo(
    opposing: list | None = None,
    link_id: object = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.find_opposing_claims = AsyncMock(return_value=opposing or [])
    repo.insert_link = AsyncMock(return_value=link_id or uuid4())
    return repo


def _make_outbox_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.append = AsyncMock(return_value=uuid4())
    return repo


def _opposing_claim(confidence: float = 0.70) -> dict:
    return {
        "claim_id": uuid4(),
        "extraction_confidence": confidence,
        "polarity": "negative",
        "claim_type": "analyst_rating",
        "subject_entity_id": uuid4(),
    }


# ---------------------------------------------------------------------------
# Polarity rules
# ---------------------------------------------------------------------------


class TestPolarityRules:
    def test_neutral_polarity_returns_empty_immediately(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        contra_repo = _make_contradiction_repo()
        result = asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="neutral",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert result == []
        contra_repo.find_opposing_claims.assert_not_called()

    def test_positive_polarity_queries_opposing(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        contra_repo = _make_contradiction_repo(opposing=[_opposing_claim()])
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        contra_repo.find_opposing_claims.assert_called_once()

    def test_no_opposing_claims_returns_empty(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        result = asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=_make_contradiction_repo(opposing=[]),
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert result == []


# ---------------------------------------------------------------------------
# 90-day window
# ---------------------------------------------------------------------------


class TestWindowParam:
    def test_find_opposing_uses_90_day_window(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        contra_repo = _make_contradiction_repo(opposing=[])
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                window_days=90,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        call_kwargs = contra_repo.find_opposing_claims.call_args.kwargs
        assert call_kwargs["window_days"] == 90


# ---------------------------------------------------------------------------
# Contradiction link + outbox emission
# ---------------------------------------------------------------------------


class TestContradictionLinkAndOutbox:
    def test_contradiction_link_written(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        contra_repo = _make_contradiction_repo(opposing=[_opposing_claim()])
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        contra_repo.insert_link.assert_called_once()

    def test_contradiction_event_emitted_via_outbox(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=_make_contradiction_repo(opposing=[_opposing_claim()]),
                outbox_repo=outbox,
            )
        )
        outbox.append.assert_called_once()
        topic = outbox.append.call_args.kwargs["topic"]
        assert topic == "intelligence.contradiction.v1"

    def test_contradiction_strength_is_min_of_both_confidences(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        opposing = _opposing_claim(confidence=0.60)
        contra_repo = _make_contradiction_repo(opposing=[opposing])
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        kwargs = contra_repo.insert_link.call_args.kwargs
        assert kwargs["strength"] == pytest.approx(0.60)  # min(0.80, 0.60)

    def test_is_backfill_propagated_in_payload(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        outbox = _make_outbox_repo()
        asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=True,
                contradiction_repo=_make_contradiction_repo(opposing=[_opposing_claim()]),
                outbox_repo=outbox,
            )
        )
        raw = outbox.append.call_args.kwargs["payload_avro"]
        payload = json.loads(raw)
        assert payload["is_backfill"] is True

    def test_multiple_opposing_claims_produce_multiple_links(self) -> None:
        from knowledge_graph.application.blocks.contradiction import (
            detect_and_record_contradictions,
        )

        contra_repo = _make_contradiction_repo(opposing=[_opposing_claim(0.5), _opposing_claim(0.6)])
        results = asyncio.get_event_loop().run_until_complete(
            detect_and_record_contradictions(
                raw_evidence_id=uuid4(),
                claim_id=uuid4(),
                subject_entity_id=uuid4(),
                claim_type="analyst_rating",
                polarity="positive",
                new_claim_confidence=0.80,
                is_backfill=False,
                contradiction_repo=contra_repo,
                outbox_repo=_make_outbox_repo(),
            )
        )
        assert len(results) == 2
        assert contra_repo.insert_link.call_count == 2
