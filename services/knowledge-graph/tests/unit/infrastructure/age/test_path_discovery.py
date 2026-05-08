"""Unit tests for PathDiscovery AGE adapter (T-E1-03)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_session_factory(rows: list | None = None, raise_exc: Exception | None = None) -> MagicMock:
    """Build a mock async_sessionmaker that returns rows or raises an exception.

    When ``raise_exc`` is provided, the mock raises on the 3rd execute call.
    The first two calls succeed (LOAD 'age' + SET search_path), so that
    ``_setup_age_session`` completes and the exception fires on the Cypher query,
    which is the correct level for timeout testing.
    """
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows or []
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    if raise_exc is not None:
        # Allow first 3 calls (LOAD 'age', SET search_path, SET LOCAL statement_timeout)
        # to succeed; raise on the 4th call (the actual Cypher query).
        _ok = MagicMock()
        session.execute = AsyncMock(side_effect=[_ok, _ok, _ok, raise_exc])
    else:
        session.execute = AsyncMock(return_value=result)

    factory = MagicMock()
    factory.return_value = session
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


class TestPathDiscovery:
    def test_empty_path_returns_nothing(self) -> None:
        """When AGE returns no rows, find_paths_for_anchor returns empty list."""
        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        factory = _make_session_factory(rows=[])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        assert paths == []

    def test_entity_id_not_string_interpolated(self) -> None:
        """entity_id is passed via params dict, never f-strung into the Cypher query.

        Verifies that the SQL template string does not contain any UUID value
        literally — the entity_id must appear only in the :params binding.
        """
        from knowledge_graph.infrastructure.age.path_discovery import _CYPHER_FIND_PATHS

        # The static SQL template should not contain any UUID-like pattern.
        # We verify by checking that the SQL only references '$id' (the Cypher param),
        # not any literal UUID value.
        assert "$id" in _CYPHER_FIND_PATHS
        # The template must not contain f-string-style interpolation placeholders.
        assert "{entity_id}" not in _CYPHER_FIND_PATHS

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
        """Malformed rows are skipped without aborting the whole batch."""
        import json

        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        # A valid row
        valid_edges = json.dumps([0.8, 0.7])
        valid_node_types = json.dumps(["company", "company", "company"])
        valid_rel_types = json.dumps(["SUPPLIES_TO", "OWNS"])
        valid_node_ids = json.dumps([str(uuid4()), str(uuid4()), str(uuid4())])
        valid_node_names = json.dumps(["A", "B", "C"])
        valid_row = (valid_edges, valid_node_types, valid_rel_types, valid_node_ids, valid_node_names)

        # A malformed row (None values)
        bad_row = (None, None, None, None, None)

        factory = _make_session_factory(rows=[valid_row, bad_row])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        # Malformed row is skipped, valid row returns a path
        assert len(paths) == 1

    def test_valid_row_returns_raw_path_with_correct_hop_count(self) -> None:
        """A valid 2-hop path row maps to a RawPath with hop_count=2."""
        import json

        from knowledge_graph.infrastructure.age.path_discovery import PathDiscovery

        edges = json.dumps([0.8, 0.7])
        node_types = json.dumps(["company", "company", "company"])
        rel_types = json.dumps(["SUPPLIES_TO", "OWNS"])
        node_ids = json.dumps([str(uuid4()), str(uuid4()), str(uuid4())])
        node_names = json.dumps(["Apple", "TSMC", "Samsung"])
        row = (edges, node_types, rel_types, node_ids, node_names)

        factory = _make_session_factory(rows=[row])
        discovery = PathDiscovery(factory)
        paths = asyncio.run(discovery.find_paths_for_anchor(uuid4()))
        assert len(paths) == 1
        assert paths[0].hop_count == 2
        assert paths[0].edge_confs == (0.8, 0.7)
        assert paths[0].rel_types == ("SUPPLIES_TO", "OWNS")
