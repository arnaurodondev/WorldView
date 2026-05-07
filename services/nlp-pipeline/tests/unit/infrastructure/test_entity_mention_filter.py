"""Unit tests for _build_entity_mention_filter (PLAN-0078 Wave C).

Validates the SQL fragment builder that applies entity_ids / entity_types
filter against chunks.entity_mentions JSONB via EXISTS subquery.
"""

from __future__ import annotations

import uuid

import pytest
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk_search import (
    _build_entity_mention_filter,
)


class TestBuildEntityMentionFilter:
    @pytest.mark.unit
    def test_entity_ids_only_produces_id_clause(self) -> None:
        """Only entity_ids → single id-equality clause."""
        eid = uuid.uuid4()
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=[eid], entity_types=None)

        assert "entity_id" in sql
        assert "entity_type" not in sql
        assert "EXISTS" in sql
        assert params["entity_id_strs"] == [str(eid)]

    @pytest.mark.unit
    def test_entity_types_only_produces_type_clause(self) -> None:
        """Only entity_types → single type-equality clause."""
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=None, entity_types=["organization"])

        assert "entity_type" in sql
        assert "entity_id" not in sql
        assert params["entity_type_strs"] == ["organization"]

    @pytest.mark.unit
    def test_both_fields_produce_and_clause(self) -> None:
        """Both entity_ids and entity_types → AND predicate (same-mention semantics)."""
        eid = uuid.uuid4()
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=[eid], entity_types=["person"])

        assert " AND " in sql
        assert "entity_id" in sql
        assert "entity_type" in sql

    @pytest.mark.unit
    def test_multiple_entity_ids_use_any(self) -> None:
        """Multiple entity_ids are emitted as a single ANY(CAST(...)) clause."""
        eid_a, eid_b = uuid.uuid4(), uuid.uuid4()
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=[eid_a, eid_b], entity_types=None)

        assert "ANY" in sql
        assert set(params["entity_id_strs"]) == {str(eid_a), str(eid_b)}

    @pytest.mark.unit
    def test_no_f_string_injection_in_sql(self) -> None:
        """The returned SQL must not contain raw UUID values — only param placeholders."""
        eid = uuid.uuid4()
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=[eid], entity_types=["organization"])

        # Actual UUID values must NOT appear in the SQL string
        assert str(eid) not in sql
        # Param placeholders must be present
        assert ":entity_id_strs" in sql
        assert ":entity_type_strs" in sql

    @pytest.mark.unit
    def test_cast_bp180_guard_present(self) -> None:
        """BP-180: params must use CAST(... AS TEXT[]) to avoid asyncpg ambiguity."""
        eid = uuid.uuid4()
        params: dict = {}

        sql = _build_entity_mention_filter(params, entity_ids=[eid], entity_types=["company"])

        assert "CAST(:entity_id_strs AS TEXT[])" in sql
        assert "CAST(:entity_type_strs AS TEXT[])" in sql

    @pytest.mark.unit
    def test_raises_on_both_empty(self) -> None:
        """Calling with both args falsy raises ValueError (MAJOR-01 guard)."""
        import pytest

        params: dict = {}

        with pytest.raises(ValueError, match="at least one non-empty filter"):
            _build_entity_mention_filter(params, entity_ids=None, entity_types=None)

        with pytest.raises(ValueError):
            _build_entity_mention_filter(params, entity_ids=[], entity_types=[])
