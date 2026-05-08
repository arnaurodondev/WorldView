"""Unit tests for NarrativeRepository (T-C-02).

Uses in-memory AsyncMock sessions — no live DB required.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000001")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000002")
_GENERATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_NARRATIVE = "A" * 100  # valid 100-char narrative


def _make_narrative_version(
    entity_id: UUID = _ENTITY_ID,
    version_id: UUID = _VERSION_ID,
    is_current: bool = True,
) -> EntityNarrativeVersion:
    from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

    return EntityNarrativeVersion(
        version_id=version_id,
        entity_id=entity_id,
        narrative_text=_NARRATIVE,
        model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
        generation_reason=NarrativeGenerationReason.INITIAL,
        input_snapshot={"_hash": "abc123"},
        generated_at=_GENERATED_AT,
        is_current=is_current,
    )


def _make_db_row(
    version_id: UUID = _VERSION_ID,
    entity_id: UUID = _ENTITY_ID,
    narrative_text: str = _NARRATIVE,
    model_id: str = "meta-llama/Meta-Llama-3.1-8B-Instruct",
    generation_reason: str = "INITIAL",
    input_snapshot: dict | None = None,
    generated_at: datetime = _GENERATED_AT,
    is_current: bool = True,
    word_count: int | None = None,
    quality_score: float | None = None,
) -> tuple:
    """Return a tuple matching the _row_to_version column order."""
    return (
        str(version_id),  # 0: version_id
        str(entity_id),  # 1: entity_id
        narrative_text,  # 2: narrative_text
        model_id,  # 3: model_id
        generation_reason,  # 4: generation_reason
        input_snapshot,  # 5: input_snapshot
        None,  # 6: tenant_id
        generated_at,  # 7: generated_at
        is_current,  # 8: is_current
        word_count,  # 9: word_count
        quality_score,  # 10: quality_score
    )


def _make_session(row: tuple | None) -> AsyncMock:
    """Return a mock AsyncSession that returns *row* from execute().fetchone()."""
    session = AsyncMock()
    result = MagicMock()
    result.fetchone.return_value = row
    result.fetchall.return_value = [row] if row else []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


class TestNarrativeRepositoryIdempotencyLookup:
    def test_find_by_input_snapshot_returns_version_when_found(self) -> None:
        """find_by_input_snapshot returns EntityNarrativeVersion when a row matches."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        row = _make_db_row(input_snapshot={"_hash": "abc123"})
        session = _make_session(row)

        repo = NarrativeRepository(session)
        version = asyncio.run(repo.find_by_input_snapshot(entity_id=_ENTITY_ID, snapshot_hash="abc123"))

        assert version is not None
        assert version.entity_id == _ENTITY_ID
        assert version.version_id == _VERSION_ID

    def test_find_by_input_snapshot_returns_none_when_not_found(self) -> None:
        """find_by_input_snapshot returns None when no matching row exists."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        session = _make_session(None)  # No row found
        repo = NarrativeRepository(session)
        result = asyncio.run(repo.find_by_input_snapshot(entity_id=_ENTITY_ID, snapshot_hash="nonexistent"))

        assert result is None


class TestNarrativeRepositoryFindCurrent:
    def test_find_current_returns_version(self) -> None:
        """find_current returns the is_current=True version."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        row = _make_db_row(is_current=True)
        session = _make_session(row)

        repo = NarrativeRepository(session)
        version = asyncio.run(repo.find_current(entity_id=_ENTITY_ID))

        assert version is not None
        assert version.is_current is True

    def test_find_current_returns_none_when_no_current(self) -> None:
        """find_current returns None when no current version exists."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        session = _make_session(None)
        repo = NarrativeRepository(session)
        result = asyncio.run(repo.find_current(entity_id=_ENTITY_ID))

        assert result is None


class TestNarrativeRepositoryVersionHistory:
    def test_empty_history_returns_empty_list(self) -> None:
        """list_versions returns empty list + None cursor when no rows exist."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        session = AsyncMock()
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        session.execute = AsyncMock(return_value=empty_result)

        repo = NarrativeRepository(session)
        versions, next_cursor = asyncio.run(repo.list_versions(entity_id=_ENTITY_ID, limit=10))

        assert versions == []
        assert next_cursor is None

    def test_list_versions_returns_versions_and_cursor(self) -> None:
        """list_versions returns versions and a next_cursor when more pages exist."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        # Return limit+1 rows to simulate "has_more"
        rows = [_make_db_row(is_current=(i == 0)) for i in range(3)]  # limit=2, 3 rows → has_more
        session = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = rows
        session.execute = AsyncMock(return_value=result)

        repo = NarrativeRepository(session)
        versions, next_cursor = asyncio.run(repo.list_versions(entity_id=_ENTITY_ID, limit=2))

        assert len(versions) == 2  # capped at limit
        assert next_cursor is not None
        # Cursor should be base64-decodable
        decoded = base64.b64decode(next_cursor.encode()).decode()
        assert "|" in decoded


class TestNarrativeRepositoryInsertAndPromote:
    def test_insert_and_promote_executes_four_statements(self) -> None:
        """insert_and_promote must execute exactly 4 SQL statements in sequence."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        version = _make_narrative_version()
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()

        # NarrativeRepository uses the session passed to insert_and_promote
        repo = NarrativeRepository(session)
        asyncio.run(repo.insert_and_promote(version, session, health_score=0.75))

        # 4 executes: INSERT + UPDATE demote + UPDATE promote + UPDATE canonical
        assert session.execute.await_count == 4

    def test_insert_and_promote_serializes_input_snapshot(self) -> None:
        """insert_and_promote passes JSON-serialized input_snapshot to SQL."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        version = _make_narrative_version()
        session = AsyncMock()
        session.execute = AsyncMock()

        repo = NarrativeRepository(session)
        asyncio.run(repo.insert_and_promote(version, session))

        # First call is the INSERT — check that input_snapshot is JSON-serialized
        insert_call = session.execute.call_args_list[0]
        params = insert_call.args[1]  # second positional arg is the params dict
        snapshot_val = params.get("input_snapshot")
        if snapshot_val is not None:
            # Must be a JSON string or None
            json.loads(snapshot_val)  # should not raise


class TestNarrativeRepositoryConcurrentInsert:
    def test_concurrent_insert_unique_violation_propagates(self) -> None:
        """A UniqueViolationError from a concurrent insert is propagated to the caller."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
            NarrativeRepository,
        )

        version = _make_narrative_version()
        session = AsyncMock()
        # Simulate DB unique constraint violation on INSERT
        session.execute = AsyncMock(side_effect=Exception("UniqueViolation: entity_id already current"))

        repo = NarrativeRepository(session)
        with pytest.raises(Exception, match="UniqueViolation"):
            asyncio.run(repo.insert_and_promote(version, session))
