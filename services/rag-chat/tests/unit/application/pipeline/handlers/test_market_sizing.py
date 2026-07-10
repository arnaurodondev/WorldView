"""get_market_sizing — curated TAM / market-size reference tool (Area-2 P3).

Covers:
  * The packaged reference table loads + is well-formed (rows, required fields,
    unique ids, file-level disclaimer present).
  * Deterministic keyword search returns the right rows for representative
    projection queries ("AI accelerator TAM", "data-center CPU market").
  * ``get_market_sizing`` returns citable RetrievedItem rows (source_name marks
    them as reference data; each row text is framed as a DATED ESTIMATE, never a
    live figure).
  * Category filter + limit clamp + empty-query default slice + no-match [].
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.handlers.market_sizing import MarketSizingHandler
from rag_chat.application.pipeline.handlers.market_sizing_data import (
    load_market_sizing_reference,
)
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


# ── Dataset well-formedness ───────────────────────────────────────────────────


class TestReferenceDataset:
    def test_loads_and_is_well_formed(self) -> None:
        ref = load_market_sizing_reference()
        assert ref.rows, "reference table must not be empty"
        assert 15 <= len(ref.rows) <= 30, f"curated table should be small (15-30 rows), got {len(ref.rows)}"
        assert ref.disclaimer and "not real-time" in ref.disclaimer.lower()

    def test_every_row_has_required_fields(self) -> None:
        ref = load_market_sizing_reference()
        for row in ref.rows:
            assert row.id and row.segment and row.category
            assert row.market_size_usd
            assert isinstance(row.size_year, int) and row.size_year > 2000
            assert row.cagr
            assert row.source
            assert row.as_of_date

    def test_row_ids_are_unique(self) -> None:
        ref = load_market_sizing_reference()
        ids = [r.id for r in ref.rows]
        assert len(ids) == len(set(ids))

    def test_categories_are_constrained(self) -> None:
        ref = load_market_sizing_reference()
        assert {r.category for r in ref.rows} <= {"semiconductor", "smartphone", "cloud"}

    def test_covers_the_projection_sectors(self) -> None:
        """The sectors the projection questions touch must be present."""
        ref = load_market_sizing_reference()
        blob = " ".join(r.segment.lower() + " " + " ".join(r.aliases) for r in ref.rows)
        for needle in ("ai accelerator", "server cpu", "hbm", "foundry", "smartphone", "cloud"):
            assert needle in blob, f"expected coverage for {needle!r}"


# ── Deterministic search ──────────────────────────────────────────────────────


class TestSearch:
    def test_ai_accelerator_tam_matches_gpu_segment(self) -> None:
        ref = load_market_sizing_reference()
        rows = ref.search(query="AI accelerator TAM", limit=3)
        assert rows, "expected a match for 'AI accelerator TAM'"
        assert rows[0].id == "ms-ai-accelerator-2024"

    def test_data_center_cpu_market_matches_cpu_segment(self) -> None:
        ref = load_market_sizing_reference()
        rows = ref.search(query="data-center CPU market", limit=3)
        assert rows
        assert rows[0].id == "ms-datacenter-cpu-2024"

    def test_category_filter_scopes_results(self) -> None:
        ref = load_market_sizing_reference()
        rows = ref.search(query="market", category="cloud", limit=20)
        assert rows
        assert all(r.category == "cloud" for r in rows)

    def test_empty_query_returns_deterministic_slice(self) -> None:
        ref = load_market_sizing_reference()
        rows = ref.search(query=None, limit=4)
        assert len(rows) == 4
        # Deterministic: same call yields the same order.
        assert [r.id for r in rows] == [r.id for r in ref.search(query="", limit=4)]

    def test_limit_is_clamped(self) -> None:
        ref = load_market_sizing_reference()
        assert len(ref.search(query=None, limit=999)) <= 20
        assert len(ref.search(query="AI accelerator", limit=0)) >= 0  # no crash on 0

    def test_no_match_returns_empty(self) -> None:
        ref = load_market_sizing_reference()
        assert ref.search(query="zzzznonsensequery", limit=5) == []


# ── Handler → citable RetrievedItem rows ──────────────────────────────────────


class TestHandler:
    @pytest.mark.asyncio
    async def test_returns_citable_rows(self) -> None:
        handler = MarketSizingHandler()
        items = await handler.execute("get_market_sizing", {"query": "AI accelerator TAM", "limit": 3})
        assert items, "expected market-sizing rows"
        first = items[0]
        assert first.item_type == ItemType.financial
        assert first.item_id.startswith("tool:market_sizing:")
        # Citable: source_name marks it as reference data (not a live feed).
        assert first.citation_meta.source_name == "market_sizing_reference"
        assert "estimate" in first.citation_meta.title.lower()

    @pytest.mark.asyncio
    async def test_row_text_frames_as_dated_estimate(self) -> None:
        handler = MarketSizingHandler()
        items = await handler.execute("get_market_sizing", {"query": "data-center CPU market"})
        assert items
        text = items[0].text.lower()
        assert "analyst-estimate" in text
        assert "as of" in text
        assert "not real-time" in text  # disclaimer carried into the row text

    @pytest.mark.asyncio
    async def test_grounding_fields_populated(self) -> None:
        handler = MarketSizingHandler()
        items = await handler.execute("get_market_sizing", {"query": "HBM"})
        assert items
        keys = {k for k, _ in items[0].grounding_fields}
        assert {"market_size_usd", "size_year", "cagr"} <= keys

    @pytest.mark.asyncio
    async def test_unknown_kwarg_is_dropped_not_crashed(self) -> None:
        handler = MarketSizingHandler()
        # BP-622: an unknown LLM kwarg must be filtered, not raise TypeError.
        items = await handler.execute("get_market_sizing", {"query": "cloud infrastructure", "bogus_param": 123})
        assert items

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list(self) -> None:
        handler = MarketSizingHandler()
        items = await handler.execute("get_market_sizing", {"query": "zzzznonsense"})
        assert items == []

    def test_can_handle(self) -> None:
        handler = MarketSizingHandler()
        assert handler.can_handle("get_market_sizing")
        assert not handler.can_handle("get_price_history")
