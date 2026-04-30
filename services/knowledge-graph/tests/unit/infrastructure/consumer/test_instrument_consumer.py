"""Unit tests for InstrumentEntityConsumer (PRD §6.7 Block 13D-4).

Covers:
- New instrument: creates entity + triggers definition embedding
- Replay with embedding present: skips (no refresh call)
- Replay with embedding ABSENT: re-triggers refresh_for_entity (BP-124 fix)
- Missing description: no refresh triggered
- No definition_worker: embedding step silently skipped
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

_INSTRUMENT_ID = uuid4()
_ENTITY_ID = uuid4()
_DESCRIPTION = "Apple Inc. is a consumer electronics company."


def _make_consumer(
    *,
    entity_exists: bool = False,
    embedding_model_id: str | None = None,
    with_def_worker: bool = True,
) -> tuple[Any, Any, Any]:
    """Build an InstrumentEntityConsumer with mocked infrastructure.

    Args:
        entity_exists:      If True, entity_repo.get() returns an existing entity dict.
        embedding_model_id: model_id in the embedding state row (None = no embedding).
        with_def_worker:    Whether to wire in a DefinitionRefreshWorker mock.

    Returns:
        (consumer, def_worker_mock, alias_repo_mock)
    """
    from knowledge_graph.infrastructure.messaging.consumers.instrument_consumer import (
        InstrumentEntityConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-instrument-test",
        topics=["market.instrument.created"],
    )

    # ── Session factory mock ──────────────────────────────────────────────────
    session = AsyncMock()
    session.commit = AsyncMock()

    entity_repo_mock = AsyncMock()
    alias_repo_mock = AsyncMock()
    alias_repo_mock.insert = AsyncMock()
    alias_repo_mock.find_exact = AsyncMock(return_value=None)
    emb_repo_mock = AsyncMock()

    if entity_exists:
        existing_dict: dict[str, Any] = {
            "entity_id": _ENTITY_ID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "isin": None,
            "metadata": {},
        }
        entity_repo_mock.get = AsyncMock(return_value=existing_dict)
        # When entity exists, always return a row but model_id may be None (None = no embedding yet)
        emb_row_actual = {
            "entity_id": _ENTITY_ID,
            "view_type": "definition",
            "model_id": embedding_model_id,
            "source_hash": "oldhash",
        }
        emb_repo_mock.get = AsyncMock(return_value=emb_row_actual)
    else:
        entity_repo_mock.get = AsyncMock(return_value=None)
        entity_repo_mock.create = AsyncMock(return_value=_ENTITY_ID)
        emb_repo_mock.ensure_rows_exist = AsyncMock()
        emb_repo_mock.get = AsyncMock(return_value=None)

    # Patch repo constructors to return our mocks

    def _entity_repo_factory(_session: Any) -> Any:
        return entity_repo_mock

    def _alias_repo_factory(_session: Any) -> Any:
        return alias_repo_mock

    def _emb_repo_factory(_session: Any) -> Any:
        return emb_repo_mock

    # ── Session as async context manager ─────────────────────────────────────
    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock()
    sf.return_value = session_cm

    # ── LLM client ───────────────────────────────────────────────────────────
    llm_client = AsyncMock()
    llm_client.extract = AsyncMock(return_value=None)

    # ── DefinitionRefreshWorker ───────────────────────────────────────────────
    def_worker = AsyncMock() if with_def_worker else None
    if def_worker:
        def_worker.refresh_for_entity = AsyncMock()

    consumer = InstrumentEntityConsumer(
        config=config,
        session_factory=sf,
        llm_client=llm_client,
        definition_worker=def_worker,
    )

    return consumer, def_worker, entity_repo_mock, emb_repo_mock


class TestInstrumentEntityConsumerNew:
    def test_new_entity_creates_and_triggers_embedding(self) -> None:
        """New instrument → entity created + refresh_for_entity called with description."""
        consumer, def_worker, entity_repo, emb_repo = _make_consumer(entity_exists=False)

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "isin": "US0378331005",
            "description": _DESCRIPTION,
        }

        import unittest.mock as mock

        with (
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=mock.AsyncMock(insert=mock.AsyncMock(), find_exact=mock.AsyncMock(return_value=None)),
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
                return_value=emb_repo,
            ),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_awaited_once()
        call_args = def_worker.refresh_for_entity.call_args
        assert call_args.args[1] == _DESCRIPTION  # source_text

    def test_no_description_skips_embedding(self) -> None:
        """No description → definition_worker not called even for new entity."""
        consumer, def_worker, entity_repo, emb_repo = _make_consumer(entity_exists=False)

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "description": "",  # empty
        }

        import unittest.mock as mock

        with (
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=mock.AsyncMock(insert=mock.AsyncMock(), find_exact=mock.AsyncMock(return_value=None)),
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
                return_value=emb_repo,
            ),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()


class TestInstrumentEntityConsumerReplay:
    def test_replay_with_embedding_present_skips_refresh(self) -> None:
        """Entity exists + embedding present (model_id set) → refresh_for_entity NOT called."""
        consumer, def_worker, entity_repo, emb_repo = _make_consumer(
            entity_exists=True,
            embedding_model_id="nomic-embed-text",  # embedding exists
        )

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "description": _DESCRIPTION,
        }

        import unittest.mock as mock

        with (
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
                return_value=emb_repo,
            ),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_not_awaited()

    def test_replay_without_embedding_triggers_refresh(self) -> None:
        """Entity exists but embedding absent (model_id=None) → refresh_for_entity called (BP-124 fix)."""
        consumer, def_worker, entity_repo, emb_repo = _make_consumer(
            entity_exists=True,
            embedding_model_id=None,  # no embedding — crash between steps
        )

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "description": _DESCRIPTION,
        }

        import unittest.mock as mock

        with (
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
                return_value=emb_repo,
            ),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        def_worker.refresh_for_entity.assert_awaited_once()
        call_args = def_worker.refresh_for_entity.call_args
        assert call_args.args[1] == _DESCRIPTION


class TestInstrumentEntityConsumerUpsertAfterDiscover:
    """PLAN-0057 Wave D-2: UPSERT-after-discover semantics.

    When a placeholder canonical exists (created by InstrumentDiscoveredConsumer
    with metadata.needs_fundamentals_enrichment = true), processing
    market.instrument.created MUST:
      1. UPDATE canonical_entities to clear the flag and stamp the real Name/ISIN.
      2. Run the rich alias-enrichment block (entity_repo.create() must NOT be
         called — the canonical already exists).
      3. Trigger description embedding via DefinitionRefreshWorker.
    """

    def test_upsert_after_discover_updates_and_runs_alias_block(self) -> None:
        """Placeholder canonical → UPDATE + alias enrichment + embedding refresh."""
        consumer, def_worker, entity_repo, emb_repo = _make_consumer(entity_exists=True)

        # Override the existing dict to mark it as a discovered placeholder
        entity_repo.get = AsyncMock(
            return_value={
                "entity_id": _INSTRUMENT_ID,
                "canonical_name": "AAPL",  # placeholder = symbol
                "entity_type": "financial_instrument",
                "ticker": "AAPL",
                "exchange": "NASDAQ",
                "isin": None,
                "metadata": {
                    "source": "discovered",
                    "needs_fundamentals_enrichment": True,
                    "discovered_at": "2026-04-30T11:00:00Z",
                },
            }
        )
        # entity_repo.create must NEVER be called on the upsert-after-discover path
        entity_repo.create = AsyncMock(side_effect=AssertionError("create() called on UPSERT path"))

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(_INSTRUMENT_ID),
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "isin": "US0378331005",
            "description": _DESCRIPTION,
        }

        import unittest.mock as mock

        with (
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository",
                return_value=entity_repo,
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_alias.EntityAliasRepository",
                return_value=mock.AsyncMock(insert=mock.AsyncMock(), find_exact=mock.AsyncMock(return_value=None)),
            ),
            mock.patch(
                "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
                return_value=emb_repo,
            ),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        # 1. entity_repo.create was NOT called (handled by side_effect AssertionError)
        # 2. ensure_rows_exist was called (Step 4 still runs)
        emb_repo.ensure_rows_exist.assert_awaited_once()
        # 3. description embedding refresh was triggered (Step 5)
        def_worker.refresh_for_entity.assert_awaited_once()
        call_args = def_worker.refresh_for_entity.call_args
        assert call_args.args[1] == _DESCRIPTION
