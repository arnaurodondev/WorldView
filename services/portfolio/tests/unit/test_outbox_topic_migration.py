"""Tests for migration ``0017_add_topic_to_outbox_events``.

PLAN-0087 #9 / qa-beta-data-platform F-003 — Outbox schema unification.

These are pure-Python tests (no Postgres required) that verify:

1. The migration's revision metadata is correctly chained.
2. The backfill list inside the migration is in lock-step with the
   application-side ``EVENT_TOPIC_MAP`` (drift here would silently leave
   future event types un-backfilled).
3. The ORM model exposes the new ``topic`` column so the SQLAlchemy
   inspector reports it (i.e. the ORM is aware of the column).
4. ``SqlAlchemyOutboxRepository.save`` populates ``topic`` from the
   canonical map for every known event type.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.infrastructure.db.models.outbox import OutboxEventModel
from portfolio.infrastructure.db.repositories.outbox import SqlAlchemyOutboxRepository
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit


_MIGRATION_PATH = Path(__file__).parent.parent.parent / "alembic" / "versions" / "0017_add_topic_to_outbox_events.py"


def _load_migration_module():
    """Load the migration file as a module without executing alembic.

    The migration file is identified by path, not package, so we use a
    spec-based loader. This avoids importing ``alembic.op`` at module level
    of the test (it would error without an active migration context — we
    only inspect the constants, never invoke ``upgrade()``).
    """
    spec = importlib.util.spec_from_file_location("_migration_0017", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Stub ``alembic.op`` with a dummy so the module can be imported. We
    # don't call upgrade()/downgrade() in this test, so a stub is fine.
    sys.modules.setdefault("alembic", type(sys)("alembic"))
    sys.modules.setdefault("alembic.op", type(sys)("alembic.op"))
    spec.loader.exec_module(mod)
    return mod


class TestMigrationMetadata:
    """Verify revision identifiers chain correctly off head 0016."""

    def test_revision_is_0017(self) -> None:
        mod = _load_migration_module()
        assert mod.revision == "0017"

    def test_down_revision_is_0016(self) -> None:
        mod = _load_migration_module()
        assert mod.down_revision == "0016"


class TestMigrationBackfillCoverage:
    """The migration's backfill list must mirror EVENT_TOPIC_MAP exactly.

    If the application defines a new event_type in EVENT_TOPIC_MAP but the
    migration's backfill is not updated, **rows inserted by the new code
    after the migration runs are fine** (the repository populates ``topic``
    on save), but **historical rows that pre-date the migration would still
    be back-filled correctly only for event types listed here**.

    We therefore enforce that the static migration list is a superset of
    every event_type currently routed by the application — guaranteeing
    that any historical row from any event type can be back-filled.
    """

    def test_backfill_covers_all_event_topic_map_entries(self) -> None:
        mod = _load_migration_module()
        backfill_map = dict(mod._EVENT_TOPIC_BACKFILL)
        for event_type, topic in EVENT_TOPIC_MAP.items():
            assert event_type in backfill_map, (
                f"event_type {event_type!r} is in EVENT_TOPIC_MAP but is "
                f"missing from migration 0017's _EVENT_TOPIC_BACKFILL — "
                f"add it so historical rows of this type can be backfilled."
            )
            assert backfill_map[event_type] == topic, (
                f"event_type {event_type!r} maps to {topic!r} in "
                f"EVENT_TOPIC_MAP but to {backfill_map[event_type]!r} in "
                f"the migration — these must agree."
            )


class TestOutboxModelHasTopic:
    """The ORM column must exist after migration 0017."""

    def test_topic_column_in_orm(self) -> None:
        mapper = sa_inspect(OutboxEventModel)
        column_names = {col.key for col in mapper.columns}
        assert "topic" in column_names

    def test_topic_column_is_nullable(self) -> None:
        # Backwards-compat with rows that pre-date the migration: the
        # column is nullable; tightening to NOT NULL is a follow-up.
        mapper = sa_inspect(OutboxEventModel)
        topic_col = mapper.columns["topic"]
        assert topic_col.nullable is True


class TestRepositoryPersistsTopic:
    """``save()`` must look ``topic`` up from EVENT_TOPIC_MAP and persist it."""

    @pytest.mark.asyncio
    async def test_save_sets_topic_from_event_topic_map(self) -> None:
        # An ``AsyncMock`` for the SQLAlchemy session — ``save`` only calls
        # ``session.add(row)``, so we capture the row and inspect it.
        mock_session = AsyncMock()
        captured: list[OutboxEventModel] = []
        mock_session.add = lambda row: captured.append(row)

        repo = SqlAlchemyOutboxRepository(mock_session)
        record = OutboxRecord(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            event_type="portfolio.created",
            topic="portfolio.events.v1",  # carried in the domain record
            payload={"foo": "bar"},
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await repo.save(record)

        assert len(captured) == 1
        assert captured[0].topic == "portfolio.events.v1"

    @pytest.mark.asyncio
    async def test_save_topic_for_watchlist_event_routes_to_v1(self) -> None:
        # ``watchlist.item_added`` should map to the watchlist topic, not
        # the generic portfolio events topic.
        mock_session = AsyncMock()
        captured: list[OutboxEventModel] = []
        mock_session.add = lambda row: captured.append(row)

        repo = SqlAlchemyOutboxRepository(mock_session)
        record = OutboxRecord(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            event_type="watchlist.item_added",
            topic="portfolio.watchlist.updated.v1",
            payload={},
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await repo.save(record)

        assert captured[0].topic == "portfolio.watchlist.updated.v1"

    @pytest.mark.asyncio
    async def test_save_unknown_event_type_leaves_topic_null(self) -> None:
        # An event_type not in the map should produce a NULL topic — the
        # dispatcher will reject these at publish time, but the row is
        # still persisted so the bug is observable.
        mock_session = AsyncMock()
        captured: list[OutboxEventModel] = []
        mock_session.add = lambda row: captured.append(row)

        repo = SqlAlchemyOutboxRepository(mock_session)
        record = OutboxRecord(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            event_type="not.a.real.event",
            topic="anything",  # ignored by save() — derived from event_type
            payload={},
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await repo.save(record)

        assert captured[0].topic is None
