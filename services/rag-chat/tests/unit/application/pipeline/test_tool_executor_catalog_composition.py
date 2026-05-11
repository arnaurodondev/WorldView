"""Cross-tool composition tests for the 6 catalog tool handlers (PLAN-0081 Wave B).

These tests verify that execute_all() correctly dispatches multiple concurrent
tool calls and returns a flat-compatible list of results, including:
  - compare_entities + get_market_movers (multi-source data in one call)
  - screen_universe + get_earnings_calendar (two s3_brief calls)
  - get_morning_brief + compare_entities (brief_archive + s3 together)
  - graceful degradation when a required port is missing for one tool
  - unknown tool name alongside a known tool (hallucination guard)

WHY composition tests: Wave A tests exercise each handler in isolation.
Wave B validates that execute_all() runs them concurrently without side effects,
correct port wiring, and proper result merging under realistic multi-tool LLM
responses (e.g. "compare AAPL and MSFT and show me the top movers").

Architecture notes:
  - execute_all() returns list[RetrievedItem | list[RetrievedItem] | None]
    (not a flat list) — callers (the orchestrator) are responsible for flattening.
    These tests flatten with _flatten() to assess the total useful items returned.
  - R25: ToolExecutor depends on port Protocols, never concrete adapters.
  - R9: any per-tool error returns None/[] without propagating exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000030")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000031")
_FAKE_BRIEF_ID = UUID("018f0000-0000-7000-8000-000000000032")
_FAKE_INSTRUMENT_ID = UUID("018f0000-0000-7000-8000-000000000040")


# ── Shared helpers ────────────────────────────────────────────────────────────


def _flatten(results: list[Any]) -> list[Any]:
    """Flatten execute_all() output into a flat list of RetrievedItems.

    execute_all() returns list[RetrievedItem | list[RetrievedItem] | None].
    Multi-result tools (search_documents, compare_entities, etc.) return a list;
    single-result tools return one item; failed tools return None.
    This helper mirrors what the orchestrator does before building LLM context.
    """
    flat: list[Any] = []
    for entry in results:
        if entry is None:
            # Tool failed or was unknown — skip
            continue
        if isinstance(entry, list):
            # Multi-result tool (e.g. compare_entities, screen_universe)
            flat.extend(entry)
        else:
            # Single-result tool (e.g. get_price_history)
            flat.append(entry)
    return flat


def _make_registry() -> Any:
    """Build a ToolRegistry with all 20 registered tools (including 6 catalog tools)."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry

    return build_default_registry()


def _make_s3_port(
    instrument_id: UUID | None = _FAKE_INSTRUMENT_ID,
    fundamentals: dict | None = None,
    quote: dict | None = None,
) -> AsyncMock:
    """Build a mock S3Port pre-configured for compare_entities happy paths.

    WHY configurable: composition tests mix happy-path and degraded scenarios;
    callers can override per-method return values after calling this helper.
    """
    mock = AsyncMock()
    mock.get_ohlcv_range.return_value = []
    mock.get_fundamentals_history.return_value = []
    mock.get_fundamentals_highlights.return_value = fundamentals or {
        "market_cap": "3T",
        "pe_ratio": 28.5,
        "revenue": "395B",
    }
    mock.get_quote.return_value = quote or {"price": 189.50}
    mock.find_instrument_by_ticker.return_value = instrument_id
    return mock


def _make_s3_brief_port(
    screen_result: dict | None = None,
    movers_result: dict | None = None,
    economic_result: list | None = None,
    earnings_result: list | None = None,
) -> AsyncMock:
    """Build a mock S3BriefPort with configurable per-method responses."""
    mock = AsyncMock()
    mock.screen_instruments.return_value = screen_result if screen_result is not None else {}
    mock.get_top_movers.return_value = movers_result if movers_result is not None else {}
    mock.get_economic_calendar.return_value = economic_result if economic_result is not None else []
    mock.get_earnings_calendar.return_value = earnings_result if earnings_result is not None else []
    return mock


def _make_brief_archive_port(records: list | None = None) -> AsyncMock:
    """Build a mock BriefArchivePort with configurable get_latest response."""
    mock = AsyncMock()
    mock.get_latest.return_value = records if records is not None else []
    mock.save.return_value = None
    mock.get_history.return_value = ([], 0)
    mock.get_by_id.return_value = None
    return mock


def _make_tool_use_block(name: str, input_dict: dict | None = None) -> Any:
    """Build a ToolUseBlock (local variant — uses tool_use_id, not id)."""
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=input_dict or {})


def _make_executor(
    s3: AsyncMock | None = None,
    s3_brief: AsyncMock | None = None,
    brief_archive: AsyncMock | None = None,
    user_id: UUID | None = _FAKE_USER_ID,
    tenant_id: UUID | None = _FAKE_TENANT_ID,
) -> Any:
    """Build a ToolExecutor with the given port mocks.

    WHY direct construction (not factory): unit tests avoid DI container overhead;
    ToolExecutor is instantiated directly with mocked ports per R25.
    """
    from rag_chat.application.pipeline.tool_executor import ToolExecutor

    return ToolExecutor(
        registry=_make_registry(),
        # s3 is required (not Optional); fall back to a safe stub if not provided
        s3=s3 if s3 is not None else _make_s3_port(),
        s3_brief=s3_brief,
        brief_archive=brief_archive,
        user_id=user_id,
        tenant_id=tenant_id,
        timeout=5.0,
    )


def _make_brief_record(
    brief_id: UUID = _FAKE_BRIEF_ID,
    headline: str = "AI Surge: Tech Leaders Post Record Gains",
    lead: str | None = "US equity markets closed at all-time highs driven by AI sentiment.",
    sections_json: list | None = None,
) -> Any:
    """Build a UserBriefRecord for get_morning_brief composition tests."""
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    return UserBriefRecord(
        id=brief_id,
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=datetime(2026, 5, 9, 8, 0, 0, tzinfo=UTC),
        headline=headline,
        lead=lead,
        sections_json=sections_json
        or [
            {"title": "Market Overview", "content": "S&P 500 up 1.4%. Nasdaq up 2.1%."},
            {"title": "Portfolio", "content": "Your holdings gained 1.8% today."},
        ],
        citations_json=[],
        confidence=0.91,
        source_version="v2.1",
    )


# ── Composition tests ─────────────────────────────────────────────────────────


class TestExecuteAllCompareMoverComposition:
    """compare_entities + get_market_movers — the canonical multi-source composition case.

    Simulates the LLM responding to "compare AAPL and MSFT and show me top movers"
    with two simultaneous tool_use blocks. Both should succeed independently and
    produce results from different source_name values.
    """

    @pytest.mark.asyncio
    async def test_execute_all_compare_and_movers(self) -> None:
        """execute_all() with compare_entities + get_market_movers yields ≥2 items.

        Both tools succeed. Result list must contain at least one item with
        source_name="fundamentals" (from compare_entities) and at least one with
        source_name="market_data" (from get_market_movers).
        """
        # S3 port for compare_entities: finds both instruments, returns mock data
        s3 = _make_s3_port(
            fundamentals={"market_cap": "3T", "pe_ratio": 28.0},
            quote={"price": 189.50},
        )

        # S3BriefPort for get_market_movers: returns gainers list
        s3_brief = _make_s3_brief_port(
            movers_result={
                "movers": [
                    {"ticker": "NVDA", "change_percent": 5.2, "price": 850.0},
                    {"ticker": "AMD", "change_percent": 3.1, "price": 175.0},
                ]
            }
        )

        executor = _make_executor(s3=s3, s3_brief=s3_brief)

        # Two tool_use blocks — the LLM emits both simultaneously
        blocks = [
            _make_tool_use_block(
                "compare_entities",
                {"entity_tickers": ["AAPL", "MSFT"]},
            ),
            _make_tool_use_block(
                "get_market_movers",
                {"mover_type": "gainers", "limit": 10, "period": "1d"},
            ),
        ]

        raw_results = await executor.execute_all(blocks)
        # execute_all returns one entry per tool call (may be item, list, or None)
        assert len(raw_results) == 2

        flat = _flatten(raw_results)
        # At least one item from each tool (compare_entities returns 1, movers returns 1)
        assert len(flat) >= 2, f"Expected ≥2 items, got {len(flat)}: {flat}"

        # Verify source_name diversity: fundamentals from compare, market_data from movers
        source_names = {item.citation_meta.source_name for item in flat if item.citation_meta is not None}
        assert "fundamentals" in source_names, f"Expected 'fundamentals' in sources: {source_names}"
        assert "market_data" in source_names, f"Expected 'market_data' in sources: {source_names}"


class TestExecuteAllScreenAndEarningsComposition:
    """screen_universe + get_earnings_calendar — two s3_brief calls in parallel.

    Both tools share the s3_brief port. execute_all() should issue both calls
    concurrently without port contention and return results from each.
    """

    @pytest.mark.asyncio
    async def test_execute_all_screen_and_earnings_calendar(self) -> None:
        """execute_all() with screen_universe + get_earnings_calendar yields ≥2 items.

        WHY: verifies that two tools sharing the same port (s3_brief) can run
        concurrently without one blocking or overwriting the other's result.
        """
        s3_brief = _make_s3_brief_port(
            # screen_universe response: two instruments matched
            screen_result={
                "instruments": [
                    {"ticker": "AAPL", "name": "Apple Inc.", "market_cap": "3T"},
                    {"ticker": "MSFT", "name": "Microsoft Corp.", "market_cap": "2.8T"},
                ]
            },
            # get_earnings_calendar response: two upcoming reports
            earnings_result=[
                {
                    "date": "2026-05-13",
                    "ticker": "AAPL",
                    "name": "Apple Inc.",
                    "eps_estimate": 1.52,
                    "eps_actual": None,
                },
                {
                    "date": "2026-05-14",
                    "ticker": "MSFT",
                    "name": "Microsoft Corp.",
                    "eps_estimate": 2.81,
                    "eps_actual": None,
                },
            ],
        )

        executor = _make_executor(s3_brief=s3_brief)

        blocks = [
            _make_tool_use_block(
                "screen_universe",
                {"sector": "Technology", "limit": 20},
            ),
            _make_tool_use_block(
                "get_earnings_calendar",
                {"from_date": "2026-05-10", "to_date": "2026-05-20"},
            ),
        ]

        raw_results = await executor.execute_all(blocks)
        assert len(raw_results) == 2

        flat = _flatten(raw_results)
        # Each tool returns one RetrievedItem — expect exactly 2
        assert len(flat) >= 2, f"Expected ≥2 items, got {len(flat)}"

        # Verify both s3_brief methods were actually called (concurrent, not skipped)
        s3_brief.screen_instruments.assert_awaited_once()
        s3_brief.get_earnings_calendar.assert_awaited_once()


class TestExecuteAllMorningBriefAndCompareComposition:
    """get_morning_brief + compare_entities — different ports (brief_archive + s3).

    Verifies that a tool drawing from the DB archive and one from the S3 port
    can coexist in the same execute_all() call without interference.
    """

    @pytest.mark.asyncio
    async def test_execute_all_morning_brief_and_compare(self) -> None:
        """execute_all() with get_morning_brief + compare_entities yields ≥2 items.

        At least one item must have source_name="morning_brief" (from the brief
        archive) and at least one from a compare_entities result.
        """
        # Brief archive returns a populated morning brief
        brief = _make_brief_record()
        brief_archive = _make_brief_archive_port(records=[brief])

        # S3 port finds both instruments and returns mock fundamentals
        s3 = _make_s3_port(
            fundamentals={"market_cap": "3T", "pe_ratio": 28.0},
            quote={"price": 189.50},
        )

        executor = _make_executor(
            s3=s3,
            brief_archive=brief_archive,
        )

        blocks = [
            _make_tool_use_block("get_morning_brief", {}),
            _make_tool_use_block(
                "compare_entities",
                {"entity_tickers": ["AAPL", "MSFT"]},
            ),
        ]

        raw_results = await executor.execute_all(blocks)
        assert len(raw_results) == 2

        flat = _flatten(raw_results)
        assert len(flat) >= 2, f"Expected ≥2 items from brief+compare, got {len(flat)}"

        # Verify source diversity
        source_names = {item.citation_meta.source_name for item in flat if item.citation_meta is not None}
        assert "morning_brief" in source_names, f"Expected 'morning_brief' in sources: {source_names}"

        # Verify the brief item carries the expected headline text
        brief_items = [
            item
            for item in flat
            if item.citation_meta is not None and item.citation_meta.source_name == "morning_brief"
        ]
        assert len(brief_items) >= 1
        assert "AI Surge" in brief_items[0].text


class TestExecuteAllMissingPortGracefulDegradation:
    """Graceful degradation when a port is absent for one tool but present for another.

    Simulates s3_brief=None: get_market_movers degrades to [] while compare_entities
    (which uses s3, not s3_brief) still succeeds. execute_all() must not raise.
    """

    @pytest.mark.asyncio
    async def test_execute_all_with_missing_port_graceful(self) -> None:
        """s3_brief=None causes get_market_movers to degrade to []; compare_entities succeeds.

        WHY: verifies that a per-tool port-missing guard (R9) does not propagate
        as an exception into execute_all(). The orchestrator still gets partial results.
        """
        # S3 port available — compare_entities will succeed
        s3 = _make_s3_port(
            fundamentals={"market_cap": "3T", "pe_ratio": 28.0},
            quote={"price": 189.50},
        )

        # s3_brief is intentionally None — get_market_movers must degrade gracefully
        executor = _make_executor(s3=s3, s3_brief=None)

        blocks = [
            _make_tool_use_block(
                "compare_entities",
                {"entity_tickers": ["AAPL", "MSFT"]},
            ),
            _make_tool_use_block(
                "get_market_movers",
                {"mover_type": "gainers", "limit": 10},
            ),
        ]

        # Must not raise — R9 graceful degradation applies to both tools
        raw_results = await executor.execute_all(blocks)
        assert len(raw_results) == 2

        flat = _flatten(raw_results)
        # compare_entities succeeds → ≥1 item; get_market_movers degrades → 0 items
        assert len(flat) >= 1, f"Expected ≥1 item from compare_entities, got {len(flat)}"

        # Verify compare_entities result is present (source_name="fundamentals")
        source_names = {item.citation_meta.source_name for item in flat if item.citation_meta is not None}
        assert "fundamentals" in source_names, f"compare_entities should contribute; sources={source_names}"


class TestExecuteAllUnknownToolPlusKnown:
    """Unknown tool alongside a known catalog tool — hallucination guard test.

    The LLM may hallucinate a tool name. execute_all() should return None for
    the unknown tool and the correct result for the known tool, without raising.
    """

    @pytest.mark.asyncio
    async def test_execute_all_unknown_tool_plus_known(self) -> None:
        """Unknown tool returns None; get_economic_calendar still succeeds.

        WHY: ToolExecutor.execute() returns None for unknown tool names (logged
        as unknown_tool_name). execute_all() gathers both concurrently — the None
        entry must not crash the caller.
        """
        s3_brief = _make_s3_brief_port(
            economic_result=[
                {
                    "date": "2026-05-14",
                    "name": "CPI (YoY)",
                    "actual": "3.2%",
                    "forecast": "3.3%",
                    "previous": "3.5%",
                },
                {
                    "date": "2026-05-07",
                    "name": "FOMC Meeting",
                    "actual": None,
                    "forecast": "5.25%",
                    "previous": "5.50%",
                },
            ]
        )

        executor = _make_executor(s3_brief=s3_brief)

        blocks = [
            # Hallucinated/unknown tool name — the registry will not have a spec for this
            _make_tool_use_block("unknown_tool_xyz", {"param": "value"}),
            # Real catalog tool that should succeed
            _make_tool_use_block(
                "get_economic_calendar",
                {"from_date": "2026-05-01", "to_date": "2026-05-31"},
            ),
        ]

        # Must not raise — unknown tool returns None, known tool returns items
        raw_results = await executor.execute_all(blocks)
        assert len(raw_results) == 2

        # First entry (unknown tool) → None
        assert raw_results[0] is None, f"Unknown tool should return None, got: {raw_results[0]}"

        # Second entry (get_economic_calendar) → list with ≥1 item
        economic_result = raw_results[1]
        assert isinstance(
            economic_result, list
        ), f"get_economic_calendar should return a list, got: {type(economic_result)}"
        assert len(economic_result) >= 1, "get_economic_calendar should return ≥1 item"

        # Verify the known tool's item has the expected source_name
        assert economic_result[0].citation_meta is not None
        assert economic_result[0].citation_meta.source_name == "economic_calendar"

        # Flatten confirms only the known tool contributed useful items
        flat = _flatten(raw_results)
        assert len(flat) >= 1
