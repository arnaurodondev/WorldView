"""Tests for migration ``0013_add_dispatched_at_to_outbox``.

PLAN-0087 #9 / qa-beta-data-platform F-003 — Outbox schema unification.

These are pure-Python tests (no Postgres required) that verify:

1. The migration's revision metadata is correctly chained.
2. The ORM exposes the new ``dispatched_at`` column so SQL writers can
   populate it; ``test_ddl_alignment.py`` (existing) verifies that the
   migration DDL also defines the column (R32 / BP-008).
3. The ``mark_published`` / ``mark_published_simple`` repository paths
   write ``dispatched_at`` in lock-step with ``published_at`` so cross-
   service tooling that filters on the canonical column sees this
   service's rows.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from market_ingestion.infrastructure.db.models import OutboxEventModel
from market_ingestion.infrastructure.db.repositories.outbox_repository import (
    SqlaOutboxRepository,
)
from sqlalchemy import inspect as sa_inspect

pytestmark = pytest.mark.unit


_MIGRATION_PATH = (
    Path(__file__).parent.parent.parent.parent / "alembic" / "versions" / "0013_add_dispatched_at_to_outbox.py"
)


def _load_migration_module():
    """Load the migration file as a module without invoking alembic.op.

    Same trick as portfolio's test — we never call ``upgrade()``; we just
    inspect the constants. Stub ``alembic.op`` so the import succeeds.
    """
    spec = importlib.util.spec_from_file_location("_migration_0013_outbox", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("alembic", type(sys)("alembic"))
    sys.modules.setdefault("alembic.op", type(sys)("alembic.op"))
    spec.loader.exec_module(mod)
    return mod


class TestMigrationMetadata:
    """Verify revision identifiers chain correctly off head 0012."""

    def test_revision_is_0013(self) -> None:
        mod = _load_migration_module()
        assert mod.revision == "0013"

    def test_down_revision_is_0012(self) -> None:
        mod = _load_migration_module()
        assert mod.down_revision == "0012"


class TestOutboxModelHasDispatchedAt:
    """The ORM column must exist after migration 0013."""

    def test_dispatched_at_column_in_orm(self) -> None:
        mapper = sa_inspect(OutboxEventModel)
        column_names = {col.key for col in mapper.columns}
        assert "dispatched_at" in column_names

    def test_dispatched_at_column_is_nullable(self) -> None:
        # Nullable for backwards-compat with rows pre-migration; populated
        # going forward by the dispatcher's mark_published paths.
        mapper = sa_inspect(OutboxEventModel)
        col = mapper.columns["dispatched_at"]
        assert col.nullable is True


class TestRepositoryPersistsDispatchedAt:
    """``mark_published`` paths must write both ``published_at`` and ``dispatched_at``."""

    @pytest.mark.asyncio
    async def test_mark_published_sets_dispatched_at(self) -> None:
        # The repository's ``mark_published`` builds a SQLAlchemy ``update``
        # statement and executes it via the unit-of-work session. We don't
        # need a real DB — we capture the values dict that's passed to
        # ``.values(...)``. Use a MagicMock for the session and inspect the
        # compiled UPDATE.
        from sqlalchemy.dialects import postgresql

        captured_values: list[dict] = []

        class _CapturingSession:
            async def execute(self, stmt):
                # SQLAlchemy update statements expose the values via
                # ``stmt.compile().params``. We compile against the
                # postgres dialect since that's what the service uses.
                compiled = stmt.compile(dialect=postgresql.dialect())
                captured_values.append(dict(compiled.params))
                # Return a result-like object with ``.rowcount = 1`` so the
                # caller's ``return rowcount > 0`` returns True.
                result = MagicMock()
                result.rowcount = 1
                return result

        # The repo expects (write_session, read_session); we pass the same
        # capturing mock for both since these tests only exercise the
        # write path (mark_published / mark_published_simple).
        capturing = _CapturingSession()
        repo = SqlaOutboxRepository(capturing, capturing)
        now = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)
        ok = await repo.mark_published(
            outbox_id="01J9X1AAAAAAAAAAAAAAAAAAAA",
            published_at=now,
            worker_id="test-worker",
        )
        assert ok is True
        assert len(captured_values) == 1
        # Both timestamp columns must be set to the same value so cross-
        # service tooling stays consistent.
        params = captured_values[0]
        assert params["published_at"] == now
        assert params["dispatched_at"] == now

    @pytest.mark.asyncio
    async def test_mark_published_simple_sets_dispatched_at(self) -> None:
        # The dispatcher-protocol-compatible helper must also write both
        # columns so the BaseOutboxDispatcher path stays aligned with the
        # explicit-API path.
        from sqlalchemy.dialects import postgresql

        captured_values: list[dict] = []

        class _CapturingSession:
            async def execute(self, stmt):
                compiled = stmt.compile(dialect=postgresql.dialect())
                captured_values.append(dict(compiled.params))
                return MagicMock()

        # The repo expects (write_session, read_session); we pass the same
        # capturing mock for both since these tests only exercise the
        # write path (mark_published / mark_published_simple).
        capturing = _CapturingSession()
        repo = SqlaOutboxRepository(capturing, capturing)
        await repo.mark_published_simple(
            record_id="01J9X1AAAAAAAAAAAAAAAAAAAA",
            worker_id="test-worker",
        )
        assert len(captured_values) == 1
        params = captured_values[0]
        # The repo computes ``now`` internally; we just check that
        # both columns received the same value (lock-step invariant).
        assert "published_at" in params
        assert "dispatched_at" in params
        assert params["published_at"] == params["dispatched_at"]
