"""Unit tests for NarrativeHandler.get_path_between (PLAN-0112 W4, T-4-04).

Covers the on-demand two-entity pairwise pathfinding tool handler:
  - connected → single RetrievedItem summarising the path
  - disconnected → "no connection found" item
  - missing s7_intel port → []
  - same resolved entity (source == target) → []
  - unresolvable endpoint → []
  - UUID-id passthrough + S9-proxied call shape
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.pipeline.handlers.narrative import NarrativeHandler
from rag_chat.application.ports.upstream_clients import PathBetweenResult

pytestmark = pytest.mark.unit

_SRC = UUID("01900000-0000-7000-8000-0000000000a1")
_TGT = UUID("01900000-0000-7000-8000-0000000000a2")


def _handler(s7_intel: Any = None) -> NarrativeHandler:
    return NarrativeHandler(s7_intel=s7_intel, entity_context=None, timeout=2.0)


class TestGetPathBetween:
    async def test_connected_returns_item(self) -> None:
        s7 = MagicMock()
        s7.get_path_between = AsyncMock(
            return_value=PathBetweenResult(
                source_entity_id=str(_SRC),
                target_entity_id=str(_TGT),
                connected=True,
                shortest_hops=2,
                paths=[{"hop_count": 2, "weirdness": 0.42}],
            )
        )
        h = _handler(s7)
        items = await h.execute(
            "get_path_between",
            {"source_entity": str(_SRC), "target_entity": str(_TGT)},
        )
        assert len(items) == 1
        assert "connected" in items[0].text.lower()
        # The S9-proxied call received the two resolved UUIDs.
        s7.get_path_between.assert_awaited_once()
        call = s7.get_path_between.await_args
        assert call.args[0] == _SRC
        assert call.args[1] == _TGT

    async def test_disconnected_returns_no_connection_item(self) -> None:
        s7 = MagicMock()
        s7.get_path_between = AsyncMock(
            return_value=PathBetweenResult(
                source_entity_id=str(_SRC),
                target_entity_id=str(_TGT),
                connected=False,
                shortest_hops=None,
                paths=[],
            )
        )
        h = _handler(s7)
        items = await h.execute(
            "get_path_between",
            {"source_entity": str(_SRC), "target_entity": str(_TGT)},
        )
        assert len(items) == 1
        assert "no connection" in items[0].text.lower()

    async def test_missing_port_returns_empty(self) -> None:
        h = _handler(s7_intel=None)
        items = await h.execute(
            "get_path_between",
            {"source_entity": str(_SRC), "target_entity": str(_TGT)},
        )
        assert items == []

    async def test_same_entity_returns_empty(self) -> None:
        s7 = MagicMock()
        s7.get_path_between = AsyncMock()
        h = _handler(s7)
        items = await h.execute(
            "get_path_between",
            {"source_entity": str(_SRC), "target_entity": str(_SRC)},
        )
        assert items == []
        s7.get_path_between.assert_not_awaited()

    async def test_unresolvable_endpoint_returns_empty(self) -> None:
        # No s6 / name_resolver wired → non-UUID identifier is unresolvable → [].
        s7 = MagicMock()
        s7.get_path_between = AsyncMock()
        h = _handler(s7)
        items = await h.execute(
            "get_path_between",
            {"source_entity": "Some Unknown Co", "target_entity": str(_TGT)},
        )
        assert items == []
        s7.get_path_between.assert_not_awaited()

    async def test_max_hops_clamped(self) -> None:
        s7 = MagicMock()
        s7.get_path_between = AsyncMock(
            return_value=PathBetweenResult(source_entity_id=str(_SRC), target_entity_id=str(_TGT), connected=False)
        )
        h = _handler(s7)
        await h.execute(
            "get_path_between",
            {"source_entity": str(_SRC), "target_entity": str(_TGT), "max_hops": 9},
        )
        assert s7.get_path_between.await_args.kwargs["max_hops"] == 3
