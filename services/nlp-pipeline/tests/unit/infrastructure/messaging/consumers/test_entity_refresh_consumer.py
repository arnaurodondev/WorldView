"""Unit tests for EntityRefreshConsumer (REQ-003 / TASK-W0-06).

Tests verify:
  - refresh_type="description" → UPDATE flips ONLY the definition view row.
  - refresh_type="narrative"   → UPDATE flips ONLY the narrative view row.
  - refresh_type="all"         → UPDATE flips BOTH view rows.
  - Forward-compat: payload without refresh_type defaults to "all".
  - Invalid entity_id is ignored without raising.
  - Unknown refresh_type is ignored without raising (forward-compat).
  - Consumer is_duplicate is always False (UPDATE is idempotent).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer import (
    EntityRefreshConsumer,
)

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_consumer(mock_session: AsyncMock) -> EntityRefreshConsumer:
    """Build an EntityRefreshConsumer with a mocked intel session factory."""

    @asynccontextmanager  # type: ignore[misc]
    async def _factory():
        yield mock_session

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="nlp-entity-refresh-group",
        topics=["entity.refresh.v1"],
    )
    return EntityRefreshConsumer(
        config=config,
        intelligence_session_factory=_factory,  # type: ignore[arg-type]
    )


def _make_session() -> AsyncMock:
    """AsyncMock session whose execute() returns a result with rowcount=1."""
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def _make_event(
    entity_id: uuid.UUID | None = None,
    refresh_type: str | None = "all",
) -> dict:
    event: dict = {
        "event_id": str(uuid.uuid4()),
        "schema_version": 1,
        "occurred_at": "2026-05-08T10:00:00+00:00",
        "tenant_id": "",
        "entity_id": str(entity_id or uuid.uuid4()),
        "triggered_by_user_id": "u1",
    }
    if refresh_type is not None:
        event["refresh_type"] = refresh_type
    return event


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_type_description_flips_definition_only() -> None:
    """refresh_type='description' updates view_type=['definition'] only."""
    entity_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    await consumer.process_message(
        key=None,
        value=_make_event(entity_id=entity_id, refresh_type="description"),
        headers={},
    )

    session.execute.assert_awaited_once()
    args, kwargs = session.execute.call_args
    # Second positional arg is the parameter dict.
    params = args[1]
    assert params["entity_id"] == str(entity_id)
    assert params["view_types"] == ["definition"]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_type_narrative_flips_narrative_only() -> None:
    """refresh_type='narrative' updates view_type=['narrative'] only."""
    entity_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    await consumer.process_message(
        key=None,
        value=_make_event(entity_id=entity_id, refresh_type="narrative"),
        headers={},
    )

    args, _ = session.execute.call_args
    assert args[1]["view_types"] == ["narrative"]


@pytest.mark.asyncio
async def test_refresh_type_all_flips_both_views() -> None:
    """refresh_type='all' updates both definition + narrative rows."""
    entity_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    await consumer.process_message(
        key=None,
        value=_make_event(entity_id=entity_id, refresh_type="all"),
        headers={},
    )

    args, _ = session.execute.call_args
    assert args[1]["view_types"] == ["definition", "narrative"]


@pytest.mark.asyncio
async def test_missing_refresh_type_defaults_to_all() -> None:
    """Forward-compat: payload without refresh_type → defaults to 'all'."""
    entity_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    await consumer.process_message(
        key=None,
        value=_make_event(entity_id=entity_id, refresh_type=None),
        headers={},
    )

    args, _ = session.execute.call_args
    assert args[1]["view_types"] == ["definition", "narrative"]


@pytest.mark.asyncio
async def test_missing_entity_id_logs_and_returns() -> None:
    """Empty entity_id → no DB writes, no exception."""
    session = _make_session()
    consumer = _make_consumer(session)

    event = {
        "event_id": str(uuid.uuid4()),
        "entity_id": "",
        "refresh_type": "all",
    }
    await consumer.process_message(key=None, value=event, headers={})

    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_entity_id_logs_and_returns() -> None:
    """Malformed entity_id UUID → no DB writes, no exception."""
    session = _make_session()
    consumer = _make_consumer(session)

    event = {
        "event_id": str(uuid.uuid4()),
        "entity_id": "not-a-uuid",
        "refresh_type": "all",
    }
    await consumer.process_message(key=None, value=event, headers={})

    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_refresh_type_is_skipped() -> None:
    """Forward-compat: unknown refresh_type → log + skip, no exception."""
    entity_id = uuid.uuid4()
    session = _make_session()
    consumer = _make_consumer(session)

    await consumer.process_message(
        key=None,
        value=_make_event(entity_id=entity_id, refresh_type="future_value"),
        headers={},
    )

    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_is_duplicate_always_false() -> None:
    """UPDATE next_refresh_at=now() is idempotent → no dedup needed."""
    session = _make_session()
    consumer = _make_consumer(session)
    assert (await consumer.is_duplicate("any-event-id")) is False
