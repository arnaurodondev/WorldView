"""Tests for the listing-status registry + graceful non-US/private resolution.

Area-3 Phase 0+2 (roadmap 2026-07-09): a named company that is non-US-listed
(Samsung/Xiaomi/Tencent) or privately held (Huawei/ByteDance) must be handled
gracefully by the KG intelligence tools — the chat states the listing status and
NEVER fabricates a US ticker (the ``iter3_apple_competitors_spanish`` failure).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.services.listing_status import (
    ListingStatus,
    lookup_listing_status,
)

pytestmark = pytest.mark.unit

_RESOLVED_ID = UUID("018f0000-0000-7000-8000-00000000beef")


# ── Registry ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["Samsung", "samsung electronics", "SAMSUNG ELECTRONICS CO., LTD.", "005930"],
)
def test_samsung_aliases_resolve_to_krx(name: str) -> None:
    status = lookup_listing_status(name)
    assert status is not None
    assert status.is_public is True
    assert status.exchange == "KRX"
    assert status.local_ticker == "005930"
    assert status.us_adr_ticker is None


@pytest.mark.parametrize("name", ["Xiaomi", "Xiaomi Corp", "1810"])
def test_xiaomi_resolves_to_hkex(name: str) -> None:
    status = lookup_listing_status(name)
    assert status is not None and status.exchange == "HKEX" and status.local_ticker == "1810"


def test_huawei_is_private() -> None:
    status = lookup_listing_status("Huawei")
    assert status is not None
    assert status.is_public is False
    assert status.exchange is None and status.local_ticker is None


def test_bytedance_is_private() -> None:
    status = lookup_listing_status("bytedance ltd.")
    assert status is not None and status.is_public is False


def test_tsmc_has_us_adr() -> None:
    status = lookup_listing_status("TSMC")
    assert status is not None
    assert status.us_adr_ticker == "TSM"
    # ADR ticker also resolves directly.
    assert lookup_listing_status("TSM") is status


def test_unknown_company_returns_none() -> None:
    assert lookup_listing_status("Apple") is None
    assert lookup_listing_status("") is None
    assert lookup_listing_status("   ") is None


# ── describe() wording — the anti-fabrication payload ────────────────────────────


def test_private_describe_states_not_traded_and_forbids_ticker() -> None:
    text = ListingStatus("Huawei Technologies Co., Ltd.", is_public=False).describe()
    assert "privately held" in text.lower()
    assert "not publicly traded" in text.lower()
    assert "no ticker" in text.lower()


def test_non_us_describe_names_exchange_and_forbids_fabrication() -> None:
    text = ListingStatus("Xiaomi Corporation", is_public=True, exchange="HKEX", local_ticker="1810").describe()
    assert "HKEX" in text
    assert "1810" in text
    assert "does not currently ingest" in text.lower()
    assert "fabricate" in text.lower()


def test_adr_describe_points_to_us_adr() -> None:
    text = ListingStatus(
        "Taiwan Semiconductor Manufacturing Company Limited",
        is_public=True,
        exchange="TWSE",
        local_ticker="2330",
        us_adr_ticker="TSM",
    ).describe()
    assert "TSM" in text
    assert "adr" in text.lower()


# ── IntelligenceHandler graceful branch ──────────────────────────────────────────


def _make_handler(s7: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

    return IntelligenceHandler(s7=s7, entity_context=None, timeout=5.0)


def _make_block(name: str, **kwargs: Any) -> Any:
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=kwargs)


def _empty_graph() -> MagicMock:
    g = MagicMock()
    g.nodes = []
    g.edges = []
    g.entity_id = str(_RESOLVED_ID)
    return g


@pytest.mark.asyncio
async def test_get_entity_graph_private_empty_returns_listing_note() -> None:
    """A private company with NO KG graph data returns the listing note, not []."""
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = [
        {"entity_id": str(_RESOLVED_ID), "alias_text": "Huawei", "similarity": 0.95}
    ]
    s7.get_egocentric_graph.return_value = _empty_graph()
    handler = _make_handler(s7)

    items = await handler._handle_get_entity_graph(_make_block("get_entity_graph"), entity_name="Huawei")

    assert len(items) == 1
    text = items[0].text.lower()
    assert "privately held" in text and "no ticker" in text


@pytest.mark.asyncio
async def test_get_entity_graph_non_us_unresolved_returns_listing_note() -> None:
    """Even if the name does not resolve to an entity_id, surface the listing note."""
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = []  # no alias match
    handler = _make_handler(s7)

    items = await handler._handle_get_entity_graph(_make_block("get_entity_graph"), entity_name="Xiaomi")

    assert len(items) == 1
    assert "HKEX" in items[0].text


@pytest.mark.asyncio
async def test_get_entity_graph_non_us_with_graph_prepends_listing_note() -> None:
    """When the KG DOES have data, the listing note is prepended to the graph item."""
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = [
        {"entity_id": str(_RESOLVED_ID), "alias_text": "Samsung", "similarity": 0.95}
    ]
    g = MagicMock()
    g.nodes = ["Samsung Electronics"]
    g.edges = ["Samsung --[competes_with]--> Apple"]
    g.entity_id = str(_RESOLVED_ID)
    s7.get_egocentric_graph.return_value = g
    handler = _make_handler(s7)

    items = await handler._handle_get_entity_graph(_make_block("get_entity_graph"), entity_name="Samsung")

    assert len(items) == 2
    assert "KRX" in items[0].text  # listing note first
    assert "Knowledge graph" in (items[1].citation_meta.title or "")


@pytest.mark.asyncio
async def test_get_entity_graph_us_entity_unaffected() -> None:
    """An unknown/US entity gets NO listing note — normal behaviour preserved."""
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = [
        {"entity_id": str(_RESOLVED_ID), "alias_text": "Apple", "similarity": 0.95}
    ]
    s7.get_egocentric_graph.return_value = _empty_graph()  # no data
    handler = _make_handler(s7)

    items = await handler._handle_get_entity_graph(_make_block("get_entity_graph"), entity_name="Apple")

    assert items == []  # empty graph + not in registry → [] (no fabricated note)


@pytest.mark.asyncio
async def test_search_entity_relations_private_empty_returns_listing_note() -> None:
    s7 = AsyncMock()
    s7.resolve_entity_by_name.return_value = [
        {"entity_id": str(_RESOLVED_ID), "alias_text": "ByteDance", "similarity": 0.95}
    ]
    s7.search_relations.return_value = []
    handler = _make_handler(s7)

    items = await handler._handle_search_entity_relations(
        _make_block("search_entity_relations"), entity_name="ByteDance"
    )

    assert len(items) == 1
    assert "privately held" in items[0].text.lower()
