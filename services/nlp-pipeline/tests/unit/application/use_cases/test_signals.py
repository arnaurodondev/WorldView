"""Unit tests for S6 signals query use cases.

Tests: ListSignalsUseCase, SearchEntitiesUseCase, GetEntityDetailUseCase,
       GetEntityArticlesUseCase, VectorSearchUseCase, ReprocessArticleUseCase.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
_DOC_ID = uuid4()
_ENTITY_ID = uuid4()
_SECTION_ID = uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal_row(
    event_id: object = None,
    doc_id: object = None,
    entity_id: object = None,
    claim_type: str = "BULLISH",
    confidence: float = 0.85,
    occurred_at: str | None = None,
) -> dict:
    payload = {
        "event_id": str(event_id or uuid4()),
        "doc_id": str(doc_id or _DOC_ID),
        "claimer_entity_id": str(entity_id or _ENTITY_ID),
        "claim_type": claim_type,
        "extraction_confidence": confidence,
        "claim_id": "claim-abc",
    }
    if occurred_at:
        payload["occurred_at"] = occurred_at
    return {
        "event_id": event_id or uuid4(),
        "partition_key": str(doc_id or _DOC_ID),
        "payload_avro": json.dumps(payload),
        "created_at": _NOW,
    }


def _make_signals_repo(
    signal_rows: list | None = None,
    entity_rows: list | None = None,
    entity_detail_row: dict | None = None,
    article_rows: list | None = None,
    vector_rows: list | None = None,
    has_routing: bool = True,
) -> AsyncMock:
    repo = AsyncMock()
    repo.list_signal_events = AsyncMock(return_value=(signal_rows or [], len(signal_rows or [])))
    repo.search_entity_mentions = AsyncMock(return_value=(entity_rows or [], len(entity_rows or [])))
    repo.get_entity_detail = AsyncMock(return_value=entity_detail_row)
    repo.get_entity_articles = AsyncMock(return_value=(article_rows or [], len(article_rows or [])))
    repo.vector_search_sections = AsyncMock(return_value=vector_rows or [])
    repo.find_routing_decision = AsyncMock(return_value=has_routing)
    repo.insert_outbox_event = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# ListSignalsUseCase
# ---------------------------------------------------------------------------


class TestListSignalsUseCase:
    async def test_returns_signal_data_from_payload(self) -> None:
        """Valid JSON payloads are parsed into SignalData objects."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        row = _signal_row(confidence=0.9)
        repo = _make_signals_repo(signal_rows=[row])

        items, total = await ListSignalsUseCase().execute(repo=repo, limit=10, offset=0, doc_id=None)

        assert total == 1
        assert len(items) == 1
        assert items[0].confidence == 0.9
        assert items[0].signal_type == "BULLISH"

    async def test_malformed_payload_is_skipped_not_raised(self) -> None:
        """Rows with non-JSON payload_avro are silently skipped."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        bad_row = {
            "event_id": uuid4(),
            "partition_key": str(_DOC_ID),
            "payload_avro": "NOT JSON {{",
            "created_at": _NOW,
        }
        repo = _make_signals_repo(signal_rows=[bad_row])

        items, total = await ListSignalsUseCase().execute(repo=repo, limit=10, offset=0, doc_id=None)

        # Bad row skipped; total from DB still 1 but items list is empty
        assert items == []

    async def test_occurred_at_parsed_from_payload(self) -> None:
        """occurred_at in payload takes precedence over row created_at."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        occurred = "2026-03-15T10:00:00+00:00"
        row = _signal_row(occurred_at=occurred)
        repo = _make_signals_repo(signal_rows=[row])

        items, _ = await ListSignalsUseCase().execute(repo=repo, limit=10, offset=0, doc_id=None)

        assert items[0].detected_at.isoformat() == datetime.fromisoformat(occurred).isoformat()

    async def test_missing_occurred_at_falls_back_to_created_at(self) -> None:
        """When occurred_at absent from payload, row created_at is used."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        row = _signal_row()  # no occurred_at
        repo = _make_signals_repo(signal_rows=[row])

        items, _ = await ListSignalsUseCase().execute(repo=repo, limit=10, offset=0, doc_id=None)

        assert items[0].detected_at == _NOW

    async def test_subject_entity_id_fallback(self) -> None:
        """subject_entity_id is used when claimer_entity_id is absent."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        subj_id = uuid4()
        payload = {
            "event_id": str(uuid4()),
            "doc_id": str(_DOC_ID),
            "subject_entity_id": str(subj_id),
            "claim_type": "BEARISH",
            "extraction_confidence": 0.7,
            "claim_id": "claim-xyz",
        }
        row = {
            "event_id": uuid4(),
            "partition_key": str(_DOC_ID),
            "payload_avro": json.dumps(payload),
            "created_at": _NOW,
        }
        repo = _make_signals_repo(signal_rows=[row])

        items, _ = await ListSignalsUseCase().execute(repo=repo, limit=10, offset=0, doc_id=None)

        assert items[0].entity_id == subj_id

    async def test_delegates_doc_id_filter_to_repo(self) -> None:
        """doc_id filter is forwarded to the repo."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        repo = _make_signals_repo()
        await ListSignalsUseCase().execute(repo=repo, limit=5, offset=10, doc_id=_DOC_ID)

        repo.list_signal_events.assert_called_once_with(limit=5, offset=10, doc_id=_DOC_ID)

    async def test_empty_result(self) -> None:
        """Empty repo returns empty list with total=0."""
        from nlp_pipeline.application.use_cases.signals import ListSignalsUseCase

        repo = _make_signals_repo(signal_rows=[])

        items, total = await ListSignalsUseCase().execute(repo=repo, limit=20, offset=0, doc_id=None)

        assert items == []
        assert total == 0


# ---------------------------------------------------------------------------
# SearchEntitiesUseCase
# ---------------------------------------------------------------------------


class TestSearchEntitiesUseCase:
    async def test_returns_entity_search_data(self) -> None:
        """Delegates to repo.search_entity_mentions and maps rows."""
        from nlp_pipeline.application.use_cases.signals import SearchEntitiesUseCase

        rows = [
            {
                "resolved_entity_id": str(_ENTITY_ID),
                "mention_text": "Apple Inc.",
                "mention_class": "financial_instrument",
                "mention_count": 42,
            }
        ]
        repo = _make_signals_repo(entity_rows=rows)

        items, total = await SearchEntitiesUseCase().execute(repo=repo, q="Apple", limit=10, offset=0)

        assert len(items) == 1
        assert items[0].canonical_name == "Apple Inc."
        assert items[0].entity_type == "financial_instrument"
        assert items[0].mention_count == 42
        assert total == 1

    async def test_empty_query_returns_all(self) -> None:
        """repo.search_entity_mentions called with q even when empty string."""
        from nlp_pipeline.application.use_cases.signals import SearchEntitiesUseCase

        repo = _make_signals_repo()
        await SearchEntitiesUseCase().execute(repo=repo, q="", limit=20, offset=5)

        repo.search_entity_mentions.assert_called_once_with(q="", limit=20, offset=5)


# ---------------------------------------------------------------------------
# GetEntityDetailUseCase
# ---------------------------------------------------------------------------


class TestGetEntityDetailUseCase:
    async def test_returns_none_when_not_found(self) -> None:
        """Returns None when repo returns None for the entity."""
        from nlp_pipeline.application.use_cases.signals import GetEntityDetailUseCase

        repo = _make_signals_repo(entity_detail_row=None)
        result = await GetEntityDetailUseCase().execute(repo=repo, entity_id=_ENTITY_ID)

        assert result is None

    async def test_calculates_provisional_count(self) -> None:
        """provisional_count = total - resolved_count."""
        from nlp_pipeline.application.use_cases.signals import GetEntityDetailUseCase

        row = {
            "mention_text": "Apple Inc.",
            "mention_class": "financial_instrument",
            "total": "10",
            "resolved": "7",
        }
        repo = _make_signals_repo(entity_detail_row=row)

        result = await GetEntityDetailUseCase().execute(repo=repo, entity_id=_ENTITY_ID)

        assert result is not None
        assert result.mention_count == 10
        assert result.resolved_count == 7
        assert result.provisional_count == 3

    async def test_handles_missing_resolved_field(self) -> None:
        """resolved field defaults to 0 when absent from row."""
        from nlp_pipeline.application.use_cases.signals import GetEntityDetailUseCase

        row = {
            "mention_text": "Jerome Powell",
            "mention_class": "person",
            "total": "5",
            # 'resolved' not in row
        }
        repo = _make_signals_repo(entity_detail_row=row)

        result = await GetEntityDetailUseCase().execute(repo=repo, entity_id=_ENTITY_ID)

        assert result is not None
        assert result.resolved_count == 0
        assert result.provisional_count == 5

    async def test_entity_id_preserved(self) -> None:
        """The entity_id passed in is reflected in the result."""
        from nlp_pipeline.application.use_cases.signals import GetEntityDetailUseCase

        row = {"mention_text": "NVIDIA", "mention_class": "financial_instrument", "total": "3", "resolved": "3"}
        repo = _make_signals_repo(entity_detail_row=row)

        result = await GetEntityDetailUseCase().execute(repo=repo, entity_id=_ENTITY_ID)

        assert result is not None
        assert result.entity_id == _ENTITY_ID


# ---------------------------------------------------------------------------
# GetEntityArticlesUseCase
# ---------------------------------------------------------------------------


class TestGetEntityArticlesUseCase:
    async def test_returns_entity_article_data(self) -> None:
        """Maps repo rows to EntityArticleData objects."""
        from nlp_pipeline.application.use_cases.signals import GetEntityArticlesUseCase

        rows = [
            {"doc_id": str(_DOC_ID), "routing_tier": "deep", "mention_count": "5"},
        ]
        repo = _make_signals_repo(article_rows=rows)

        items, total = await GetEntityArticlesUseCase().execute(repo=repo, entity_id=_ENTITY_ID, limit=10)

        assert len(items) == 1
        assert items[0].doc_id == _DOC_ID
        assert items[0].routing_tier == "deep"
        assert items[0].mention_count == 5
        assert total == 1

    async def test_delegates_limit_to_repo(self) -> None:
        """limit is forwarded to repo.get_entity_articles."""
        from nlp_pipeline.application.use_cases.signals import GetEntityArticlesUseCase

        repo = _make_signals_repo()
        await GetEntityArticlesUseCase().execute(repo=repo, entity_id=_ENTITY_ID, limit=25)

        repo.get_entity_articles.assert_called_once_with(entity_id=_ENTITY_ID, limit=25)


# ---------------------------------------------------------------------------
# VectorSearchUseCase
# ---------------------------------------------------------------------------


class TestVectorSearchUseCase:
    async def test_returns_vector_search_hits(self) -> None:
        """Maps repo rows to VectorSearchHitData objects."""
        from nlp_pipeline.application.use_cases.signals import VectorSearchUseCase

        rows = [
            {
                "doc_id": _DOC_ID,
                "section_id": _SECTION_ID,
                "score": 0.92,
                "snippet": "Apple reported strong quarterly earnings.",
            }
        ]
        repo = _make_signals_repo(vector_rows=rows)

        results = await VectorSearchUseCase().execute(repo=repo, query="earnings", limit=5)

        assert len(results) == 1
        assert results[0].score == 0.92
        assert "Apple" in results[0].snippet

    async def test_empty_results(self) -> None:
        """Returns empty list when no sections match."""
        from nlp_pipeline.application.use_cases.signals import VectorSearchUseCase

        repo = _make_signals_repo(vector_rows=[])
        results = await VectorSearchUseCase().execute(repo=repo, query="nonexistent", limit=5)

        assert results == []

    async def test_delegates_query_and_limit(self) -> None:
        """query and limit are forwarded to repo.vector_search_sections."""
        from nlp_pipeline.application.use_cases.signals import VectorSearchUseCase

        repo = _make_signals_repo()
        await VectorSearchUseCase().execute(repo=repo, query="inflation", limit=15)

        repo.vector_search_sections.assert_called_once_with(query="inflation", limit=15)


# ---------------------------------------------------------------------------
# ReprocessArticleUseCase
# ---------------------------------------------------------------------------


class TestReprocessArticleUseCase:
    async def test_returns_false_when_article_not_found(self) -> None:
        """Returns False when no routing decision exists for the article."""
        from nlp_pipeline.application.use_cases.signals import ReprocessArticleUseCase

        repo = _make_signals_repo(has_routing=False)
        result = await ReprocessArticleUseCase().execute(repo=repo, article_id=_DOC_ID)

        assert result is False
        repo.insert_outbox_event.assert_not_called()

    async def test_returns_true_and_inserts_outbox_when_found(self) -> None:
        """Returns True and inserts an outbox event when routing decision exists."""
        from nlp_pipeline.application.use_cases.signals import ReprocessArticleUseCase

        repo = _make_signals_repo(has_routing=True)
        result = await ReprocessArticleUseCase().execute(repo=repo, article_id=_DOC_ID)

        assert result is True
        repo.insert_outbox_event.assert_called_once()

    async def test_outbox_event_contains_doc_id(self) -> None:
        """The reprocess event payload includes the article doc_id."""
        from nlp_pipeline.application.use_cases.signals import ReprocessArticleUseCase

        repo = _make_signals_repo(has_routing=True)
        await ReprocessArticleUseCase().execute(repo=repo, article_id=_DOC_ID)

        call_kwargs = repo.insert_outbox_event.call_args.kwargs
        payload = json.loads(call_kwargs["payload_avro"])
        assert payload["doc_id"] == str(_DOC_ID)
        assert payload["event_type"] == "nlp.reprocess.requested"

    async def test_outbox_topic_is_correct(self) -> None:
        """Outbox event is sent to 'nlp.reprocess.v1' topic."""
        from nlp_pipeline.application.use_cases.signals import ReprocessArticleUseCase

        repo = _make_signals_repo(has_routing=True)
        await ReprocessArticleUseCase().execute(repo=repo, article_id=_DOC_ID)

        call_kwargs = repo.insert_outbox_event.call_args.kwargs
        assert call_kwargs["topic"] == "nlp.reprocess.v1"
        assert call_kwargs["partition_key"] == str(_DOC_ID)
