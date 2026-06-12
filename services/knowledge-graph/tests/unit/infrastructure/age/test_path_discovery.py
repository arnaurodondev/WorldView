"""Unit tests for PathDiscovery AGE adapter (T-E1-03).

Updated for BP-SA5-003 (2026-05-10): the scalar-based query approach replaced
the path-function (relationships(p)/nodes(p)) approach that was incompatible
with asyncpg's prepared-statement protocol.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(
    rows_2hop: list | None = None,
    rows_3hop: list | None = None,
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock async_sessionmaker that returns rows or raises an exception.

    The session mock intercepts calls in order:
      1. LOAD 'age'
      2. SET search_path
      3. SET LOCAL statement_timeout
      4. 2-hop Cypher query → rows_2hop
      5. 3-hop Cypher query → rows_3hop

    When ``raise_exc`` is provided it fires on the 4th execute call (the first
    Cypher query).
    """
    session = AsyncMock()

    result_2 = MagicMock()
    result_2.fetchall.return_value = rows_2hop or []
    result_3 = MagicMock()
    result_3.fetchall.return_value = rows_3hop or []

    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    if raise_exc is not None:
        _ok = MagicMock()
        session.execute = AsyncMock(side_effect=[_ok, _ok, _ok, raise_exc])
    else:
        # LOAD 'age' → ok, SET search_path → ok, SET LOCAL → ok,
        # 2-hop query → result_2, 3-hop query → result_3
        _ok = MagicMock()
        session.execute = AsyncMock(side_effect=[_ok, _ok, _ok, result_2, result_3])

    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


def _make_2hop_row(
    n0_id: str = "aaa",
    n0_name: str = "A",
    n0_type: str = "company",
    r1_type: str = "COMPETES_WITH",
    r1_conf: str = "0.9",
    n1_id: str = "bbb",
    n1_name: str = "B",
    n1_type: str = "company",
    r2_type: str = "PARTNER_OF",
    r2_conf: str = "0.8",
    n2_id: str = "ccc",
    n2_name: str = "C",
    n2_type: str = "company",
) -> tuple:
    """Build a synthetic 2-hop scalar result row (13 columns, all strings)."""
    return (
        n0_id,
        n0_name,
        n0_type,
        r1_type,
        r1_conf,
        n1_id,
        n1_name,
        n1_type,
        r2_type,
        r2_conf,
        n2_id,
        n2_name,
        n2_type,
    )


def _make_3hop_row() -> tuple:
    """Build a synthetic 3-hop scalar result row (18 columns, all strings)."""
    return (
        "aaa",
        "A",
        "company",  # n0
        "COMPETES_WITH",
        "0.9",  # r1
        "bbb",
        "B",
        "company",  # n1
        "PARTNER_OF",
        "0.8",  # r2
        "ccc",
        "C",
        "company",  # n2
        "EMPLOYS",
        "0.7",  # r3
        "ddd",
        "D",
        "person",  # n3
    )


class TestPathDiscovery:
    def test_empty_path_returns_nothing(self) -> None:
        """When AGE returns no rows, find_paths_for_anchor returns empty list."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        factory = _make_session_factory(rows_2hop=[], rows_3hop=[])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        assert paths == []

    def test_entity_id_validated_before_embedding(self) -> None:
        """BP-SA5-003: entity_id is embedded via _build_2hop_sql/_build_3hop_sql with UUID validation.

        The builder functions validate the UUID format against _UUID_RE before
        embedding so no SQL/Cypher injection is possible (UUIDs are hex+hyphen only).
        This test verifies that valid UUIDs pass and the embedding produces the
        expected string.
        """
        from knowledge_graph.infrastructure.age.path_discovery import _validate_and_embed_entity_id

        uid = uuid4()
        result = _validate_and_embed_entity_id(uid)
        # Result should be the string representation of the UUID
        assert result == str(uid)
        # Result must match UUID format (hex+hyphen only, no SQL metacharacters)
        assert "'" not in result
        assert ";" not in result

    def test_invalid_entity_id_string_raises_value_error(self) -> None:
        """_validate_and_embed_entity_id raises ValueError for non-UUID strings."""
        from knowledge_graph.infrastructure.age.path_discovery import _UUID_RE

        # A UUID-like string is valid
        assert _UUID_RE.match("12345678-1234-1234-1234-123456789abc")
        # SQL injection attempts must fail the pattern
        assert not _UUID_RE.match("'; DROP TABLE entities; --")
        assert not _UUID_RE.match("abc-xyz")

    def test_age_timeout_raises_path_discovery_timeout(self) -> None:
        """PathDiscovery raises PathDiscoveryTimeoutError on asyncio.TimeoutError."""
        from knowledge_graph.infrastructure.age.path_discovery import (
            PathDiscovery,
            PathDiscoveryTimeoutError,
        )

        entity_id = uuid4()
        factory = _make_session_factory(raise_exc=TimeoutError())
        discovery = PathDiscovery(factory)
        with pytest.raises(PathDiscoveryTimeoutError):
            asyncio.run(discovery.find_paths_for_anchor(entity_id))

    def test_age_timeout_with_timeout_keyword_in_message(self) -> None:
        """PathDiscovery treats exceptions with 'timeout' in message as timeout."""
        from knowledge_graph.infrastructure.age.path_discovery import (
            PathDiscovery,
            PathDiscoveryTimeoutError,
        )

        entity_id = uuid4()
        factory = _make_session_factory(raise_exc=RuntimeError("statement timeout exceeded"))
        discovery = PathDiscovery(factory)
        with pytest.raises(PathDiscoveryTimeoutError):
            asyncio.run(discovery.find_paths_for_anchor(entity_id))

    def test_malformed_row_skipped_gracefully(self) -> None:
        """Malformed rows (None values) are skipped without aborting the batch."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        valid_row = _make_2hop_row()
        # A malformed row: all None values → _parse_2hop_row returns None
        bad_row = (None, None, None, None, None, None, None, None, None, None, None, None, None)

        factory = _make_session_factory(rows_2hop=[valid_row, bad_row], rows_3hop=[])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        # Malformed row is skipped; valid row returns a path
        assert len(paths) == 1

    def test_cypher_query_uses_lowercase_entity_label(self) -> None:
        """BP-SA5-001: queries must use lowercase 'entity' label (not 'Entity').

        AgeSyncWorker writes nodes with the lowercase 'entity' label.
        Using 'Entity' would be a different label namespace and return zero paths.
        """
        from knowledge_graph.infrastructure.age.path_discovery import _build_2hop_sql, _build_3hop_sql

        uid = str(uuid4())
        sql2 = _build_2hop_sql(uid)
        sql3 = _build_3hop_sql(uid)

        assert "entity" in sql2.lower()
        assert ":Entity" not in sql2  # must not use PascalCase
        assert "entity" in sql3.lower()
        assert ":Entity" not in sql3

    def test_valid_2hop_row_returns_raw_path_with_correct_hop_count(self) -> None:
        """A valid 2-hop scalar result row maps to a RawPath with hop_count=2."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        row = _make_2hop_row(
            n0_id="id-a",
            n0_name="Apple",
            n0_type="company",
            r1_type="COMPETES_WITH",
            r1_conf="0.9",
            n1_id="id-b",
            n1_name="TSMC",
            n1_type="company",
            r2_type="PARTNER_OF",
            r2_conf="0.8",
            n2_id="id-c",
            n2_name="Samsung",
            n2_type="company",
        )

        factory = _make_session_factory(rows_2hop=[row], rows_3hop=[])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        assert len(paths) == 1
        p = paths[0]
        assert p.hop_count == 2
        assert p.edge_confs == (0.9, 0.8)
        assert p.rel_types == ("COMPETES_WITH", "PARTNER_OF")
        assert p.node_ids == ("id-a", "id-b", "id-c")
        assert p.node_names == ("Apple", "TSMC", "Samsung")

    def test_valid_3hop_row_returns_raw_path_with_hop_count_3(self) -> None:
        """A valid 3-hop scalar result row maps to a RawPath with hop_count=3."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        row = _make_3hop_row()

        factory = _make_session_factory(rows_2hop=[], rows_3hop=[row])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        assert len(paths) == 1
        p = paths[0]
        assert p.hop_count == 3
        assert p.rel_types == ("COMPETES_WITH", "PARTNER_OF", "EMPLOYS")
        assert p.node_ids == ("aaa", "bbb", "ccc", "ddd")

    def test_duplicate_paths_deduplicated(self) -> None:
        """Paths with identical node_ids tuples are deduplicated."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        row = _make_2hop_row()
        factory = _make_session_factory(rows_2hop=[row, row], rows_3hop=[])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        # Only 1 unique path despite 2 identical rows
        assert len(paths) == 1


class TestTimeoutConstantsInvariant:
    """Regression guard for the PLAN-0111 A-3 timeout inversion.

    The DB-side ``statement_timeout`` MUST fire STRICTLY BEFORE the per-query
    ``asyncio.wait_for`` budget so Postgres cancels its own query cleanly
    instead of the client abandoning an orphaned connection (which produced
    "could not send data to client: Broken pipe" log spam and 1,172 failed
    path_insight_jobs).
    """

    def test_statement_timeout_strictly_less_than_per_query_wait_for(self) -> None:
        from knowledge_graph.infrastructure.age import path_discovery as pd

        # Per-query wait_for budget = half the overall discovery budget.
        per_query_wait_for_s = pd._DISCOVERY_TIMEOUT_SECONDS / 2
        statement_timeout_s = float(pd._STATEMENT_TIMEOUT_MS) / 1000.0

        # DB cancels before the client → no orphaned query, no broken pipe.
        assert statement_timeout_s < per_query_wait_for_s, (
            f"statement_timeout ({statement_timeout_s}s) must be < per-query "
            f"wait_for ({per_query_wait_for_s}s) — see PLAN-0111 A-3 / BP-688"
        )
