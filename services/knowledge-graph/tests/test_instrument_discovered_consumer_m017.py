"""PLAN-0089 F2 step 4 — M-017 enforcement tests for InstrumentDiscoveredConsumer.

M-017 invariant: every ``canonical_entities`` row whose ``entity_type =
'financial_instrument'`` MUST have ``entity_id == market_data.instruments.id``.
This consumer is the entry-point that materialises the canonical row from the
upstream ``market.instrument.discovered.v1`` Kafka event.  Its SQL therefore
MUST use ``event.instrument_id`` as ``canonical_entities.entity_id`` (rather
than minting a fresh UUID) — that's what these tests assert.

The pre-existing
``tests/unit/infrastructure/consumer/test_instrument_discovered_consumer.py``
already exercises the broader behaviour (aliases, embedding rows,
malformed-event handling, dedup).  This file isolates the *single contract*
that PLAN-0089 introduces, so any future regression of that contract surfaces
with a clear failure name (M-017) regardless of changes elsewhere in the
consumer.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _build_consumer() -> tuple[Any, list[tuple[str, dict]]]:
    """Construct an InstrumentDiscoveredConsumer with mocked DB plumbing.

    Returns:
        consumer + a captured ``sql_calls`` list of (stmt_str, params) tuples
        recorded for every ``session.execute`` invocation during
        ``process_message``.

    """
    # Import lazily so the module-level pytest collection doesn't require the
    # full service to be importable on disk (mirrors the pattern used by
    # the existing unit tests in this package).
    from knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer import (
        InstrumentDiscoveredConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    sql_calls: list[tuple[str, dict]] = []

    async def _execute(stmt: Any, params: dict | None = None) -> Any:
        # ``stmt`` is a sqlalchemy TextClause; str(stmt) gives the rendered SQL.
        sql_calls.append((str(stmt), params or {}))
        return MagicMock()

    # AsyncSession mock — only execute/commit/begin_nested are exercised here.
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()

    # SAVEPOINT (begin_nested) returns an async context manager.  The two
    # alias INSERTs in process_message run inside their own SAVEPOINT so that
    # one UniqueViolation does not abort the outer transaction.
    nested_cm = AsyncMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested_cm)

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    sf = MagicMock(return_value=session_cm)

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-instrument-discovered-m017-test",
        topics=["market.instrument.discovered.v1"],
    )

    return InstrumentDiscoveredConsumer(config=config, session_factory=sf), sql_calls


def _run(consumer: Any, msg: dict[str, Any]) -> None:
    """Invoke ``process_message`` with the embedding repo stubbed out.

    The real ``EntityEmbeddingStateRepository`` would issue additional SQL to
    materialise three rows; we don't need to assert that here, so a no-op
    AsyncMock keeps the captured-SQL list focused on the canonical UPSERT
    plus the two alias INSERTs.
    """
    emb_repo = AsyncMock()
    emb_repo.ensure_rows_exist = AsyncMock()
    with patch(
        "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository",
        return_value=emb_repo,
    ):
        asyncio.run(consumer.process_message(None, msg, {}))


class TestM017InstrumentIdEqualsEntityId:
    """M-017: instrument_id from the event becomes canonical_entities.entity_id."""

    def test_canonical_entity_id_equals_event_instrument_id(self) -> None:
        """The first SQL INSERT must bind entity_id := event.instrument_id verbatim."""
        consumer, sql_calls = _build_consumer()
        instrument_id = uuid4()

        msg = {
            "event_id": str(uuid4()),
            "event_type": "market.instrument.discovered",
            "schema_version": 1,
            "occurred_at": "2026-05-20T12:00:00Z",
            "instrument_id": str(instrument_id),
            "symbol": "AAPL",
            "exchange": "NASDAQ",
        }
        _run(consumer, msg)

        # SQL call ordering: [0] canonical UPSERT, [1] EXACT alias, [2] TICKER alias.
        canonical_sql, canonical_params = sql_calls[0]
        assert "INSERT INTO canonical_entities" in canonical_sql

        # M-017 core assertion: the entity_id parameter must be the SAME UUID
        # that arrived on the event as instrument_id.  Any drift here means
        # the M-017 invariant is broken and the entire post-F2 unification
        # collapses (S1 can no longer use instruments.id as a foreign key
        # into canonical_entities).
        assert canonical_params["entity_id"] == str(instrument_id), (
            f"M-017 VIOLATION: expected entity_id={instrument_id} (from event.instrument_id); "
            f"got entity_id={canonical_params['entity_id']}"
        )

    def test_canonical_entity_type_is_financial_instrument(self) -> None:
        """M-017 only applies to financial_instrument rows; this consumer hard-codes that."""
        consumer, sql_calls = _build_consumer()

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(uuid4()),
            "symbol": "MSFT",
            "exchange": "NASDAQ",
        }
        _run(consumer, msg)

        canonical_sql, _ = sql_calls[0]
        # The literal 'financial_instrument' is in the SQL VALUES list — not
        # a parameter — so we assert on the SQL text.  This guards against a
        # future refactor that turns it into a variable and accidentally
        # passes a wrong entity_type for non-tradable kinds.
        assert (
            "'financial_instrument'" in canonical_sql
        ), "M-017 VIOLATION: canonical row must declare entity_type='financial_instrument'"

    def test_redelivery_is_idempotent_via_on_conflict_do_update(self) -> None:
        """Replay safety: second delivery executes the same SQL; DB-side ON CONFLICT dedups.

        PLAN-0089 F2 step 4 promoted the conflict clause from DO NOTHING to
        DO UPDATE so that fresh metadata propagates on replay.  The consumer
        must not raise on replay, and the same entity_id must be bound on
        every delivery.  (Actual ON CONFLICT semantics are exercised by the
        intelligence-migrations integration suite; here we only verify the
        Python-side behaviour.)
        """
        consumer, sql_calls = _build_consumer()
        instrument_id = uuid4()

        msg = {
            "event_id": str(uuid4()),
            "instrument_id": str(instrument_id),
            "symbol": "GOOGL",
            "exchange": "NASDAQ",
        }
        # Two back-to-back deliveries simulate Kafka at-least-once re-delivery.
        _run(consumer, msg)
        _run(consumer, msg)

        # 2 deliveries * (1 canonical + 2 alias inserts) = 6 SQL calls.
        assert len(sql_calls) == 6

        # entity_id must match on both deliveries — neither delivery may
        # mint a fresh UUID.
        first_canonical_params = sql_calls[0][1]
        second_canonical_params = sql_calls[3][1]
        assert first_canonical_params["entity_id"] == str(instrument_id)
        assert second_canonical_params["entity_id"] == str(instrument_id)

        # Both canonical SQL statements must use the M-017 ON CONFLICT DO UPDATE
        # form (so the test fails loudly if a later refactor reverts to
        # DO NOTHING and silently breaks downstream metadata-refresh).
        for canonical_sql in (sql_calls[0][0], sql_calls[3][0]):
            assert "ON CONFLICT (entity_id) DO UPDATE" in canonical_sql
