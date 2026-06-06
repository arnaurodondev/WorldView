"""Unit tests for the 6 catalog tool handlers added in PLAN-0081 Wave A.

Handlers under test:
  - _handle_get_morning_brief       (calls BriefArchivePort.get_latest)
  - _handle_compare_entities        (calls S3Port.find_instrument_by_ticker + get_fundamentals_highlights + get_quote)
  - _handle_screen_universe         (calls S3BriefPort.screen_instruments)
  - _handle_get_market_movers       (calls S3BriefPort.get_top_movers)
  - _handle_get_economic_calendar   (calls S3BriefPort.get_economic_calendar)
  - _handle_get_earnings_calendar   (calls S3BriefPort.get_earnings_calendar)

Each handler is tested for:
  (a) happy path — returns a RetrievedItem with correct fields
  (b) missing port → returns []
  (c) upstream returns empty/{}  → returns []

For get_morning_brief specifically:
  (d) missing auth context (user_id=None) → returns []
  (e) happy path with sections → RetrievedItem text contains headline + sections

For compare_entities specifically:
  (f) too few tickers (< 2) → returns []
  (g) too many tickers (> 4) → returns []
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000010")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000011")
_FAKE_BRIEF_ID = UUID("018f0000-0000-7000-8000-000000000012")
_FAKE_INSTRUMENT_ID = UUID("018f0000-0000-7000-8000-000000000020")


# ── Helper builders ───────────────────────────────────────────────────────────


def _make_registry() -> Any:
    """Build a ToolRegistry with all 20 tools (including the 6 new catalog tools)."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry

    return build_default_registry()


def _make_s3_port() -> AsyncMock:
    """Minimal S3Port mock covering methods needed by compare_entities."""
    mock = AsyncMock()
    mock.get_ohlcv_range.return_value = []
    mock.get_fundamentals_history.return_value = []
    mock.get_fundamentals_highlights.return_value = {}
    # PLAN-0103 W14 (FQA-04 carry): compare_entities now routes the batch
    # endpoint through the same path as get_fundamentals_history_batch and
    # selects the latest fully-populated common period. Default to {} so
    # the per-ticker latest fallback engages cleanly in tests that do not
    # care about the batch path.
    mock.get_fundamentals_history_batch.return_value = {}
    mock.get_earnings.return_value = []
    mock.get_quote.return_value = {}
    mock.find_instrument_by_ticker.return_value = None
    return mock


def _make_s3_brief_port(
    screen_result: dict | None = None,
    movers_result: dict | None = None,
    economic_result: list | None = None,
    earnings_result: list | None = None,
) -> AsyncMock:
    """Build a mock S3BriefPort with configurable responses."""
    mock = AsyncMock()
    mock.screen_instruments.return_value = screen_result or {}
    mock.get_top_movers.return_value = movers_result or {}
    mock.get_economic_calendar.return_value = economic_result or []
    mock.get_earnings_calendar.return_value = earnings_result or []
    return mock


def _make_brief_archive_port(
    records: list | None = None,
) -> AsyncMock:
    """Build a mock BriefArchivePort with configurable get_latest response."""
    mock = AsyncMock()
    mock.get_latest.return_value = records or []
    mock.save.return_value = None
    mock.get_history.return_value = ([], 0)
    mock.get_by_id.return_value = None
    return mock


def _make_tool_use_block(name: str, input_dict: dict | None = None) -> Any:
    """Build a ToolUseBlock for the given tool name."""
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=input_dict or {})


def _make_executor(
    s3: AsyncMock | None = None,
    s3_brief: AsyncMock | None = None,
    brief_archive: AsyncMock | None = None,
    user_id: UUID | None = _FAKE_USER_ID,
    tenant_id: UUID | None = _FAKE_TENANT_ID,
) -> Any:
    """Build a ToolExecutor with the given ports and auth context (kept for backwards compat)."""
    from rag_chat.application.pipeline.tool_executor import ToolExecutor

    return ToolExecutor(
        registry=_make_registry(),
        s3=s3 or _make_s3_port(),
        s3_brief=s3_brief,
        brief_archive=brief_archive,
        user_id=user_id,
        tenant_id=tenant_id,
        timeout=5.0,
    )


def _make_market_handler(
    s3: AsyncMock | None = None,
    s3_brief: AsyncMock | None = None,
) -> Any:
    """Build a MarketHandler directly (PLAN-0089 C-1: handler split)."""
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3 or _make_s3_port(), s3_brief=s3_brief, timeout=5.0)


def _make_news_handler(
    brief_archive: AsyncMock | None = None,
    user_id: UUID | None = _FAKE_USER_ID,
    tenant_id: UUID | None = _FAKE_TENANT_ID,
) -> Any:
    """Build a NewsHandler directly (PLAN-0089 C-1: handler split)."""
    from rag_chat.application.pipeline.handlers.news import NewsHandler

    return NewsHandler(
        brief_archive=brief_archive,
        user_id=user_id,
        tenant_id=tenant_id,
        timeout=5.0,
    )


def _make_brief_record(
    brief_id: UUID = _FAKE_BRIEF_ID,
    headline: str = "Markets in Focus: AI Surge Continues",
    lead: str | None = "US equity markets closed higher on strong AI earnings.",
    sections_json: list | None = None,
) -> Any:
    """Build a UserBriefRecord for get_morning_brief tests."""
    from datetime import datetime

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
            {"title": "Portfolio Update", "content": "Your holdings are up 1.2% today."},
            {"title": "Macro Events", "content": "CPI data released at 08:30 EST."},
        ],
        citations_json=[],
        confidence=0.88,
        source_version="v2.1",
    )


# ── get_morning_brief tests ───────────────────────────────────────────────────


class TestGetMorningBrief:
    """Tests for _handle_get_morning_brief (now on NewsHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When brief_archive is None, returns empty list without error."""
        handler = _make_news_handler(brief_archive=None)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_auth_context_returns_empty(self) -> None:
        """(d) When user_id is None, returns empty list (anonymous session guard)."""
        archive = _make_brief_archive_port()
        handler = _make_news_handler(brief_archive=archive, user_id=None)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)
        assert result == []
        # Should NOT have called get_latest (auth guard fires first)
        archive.get_latest.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_tenant_id_returns_empty(self) -> None:
        """(d) When tenant_id is None, returns empty list."""
        archive = _make_brief_archive_port()
        handler = _make_news_handler(brief_archive=archive, tenant_id=None)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_records_returns_empty(self) -> None:
        """(c) Upstream returns [] (no brief) → returns empty list."""
        archive = _make_brief_archive_port(records=[])
        handler = _make_news_handler(brief_archive=archive)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: upstream returns a brief → single RetrievedItem returned."""
        brief = _make_brief_record()
        archive = _make_brief_archive_port(records=[brief])
        handler = _make_news_handler(brief_archive=archive)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)

        assert len(result) == 1
        item = result[0]
        # Verify headline is in the text
        assert "Markets in Focus: AI Surge Continues" in item.text
        assert item.score == pytest.approx(0.95)
        assert item.trust_weight == pytest.approx(0.92)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "morning_brief"
        # Verify get_latest was called with correct params
        archive.get_latest.assert_awaited_once_with(
            user_id=_FAKE_USER_ID,
            tenant_id=_FAKE_TENANT_ID,
            brief_type="morning",
            limit=1,
        )

    @pytest.mark.asyncio
    async def test_happy_path_text_contains_sections(self) -> None:
        """(e) Happy path with sections: RetrievedItem text contains headline + sections."""
        brief = _make_brief_record(
            sections_json=[
                {"title": "Portfolio Update", "content": "Your holdings are up 1.2% today."},
                {"title": "Macro Events", "content": "CPI data released at 08:30 EST."},
            ]
        )
        archive = _make_brief_archive_port(records=[brief])
        handler = _make_news_handler(brief_archive=archive)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)

        assert len(result) == 1
        text = result[0].text
        assert "Portfolio Update" in text
        assert "Macro Events" in text
        assert "CPI data released" in text

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty(self) -> None:
        """(c) Upstream raises exception → returns empty list (R9 degradation)."""
        archive = _make_brief_archive_port()
        archive.get_latest.side_effect = RuntimeError("DB connection failed")
        handler = _make_news_handler(brief_archive=archive)
        block = _make_tool_use_block("get_morning_brief")
        result = await handler._handle_get_morning_brief(block)
        assert result == []


# ── compare_entities tests ────────────────────────────────────────────────────


class TestCompareEntities:
    """Tests for _handle_compare_entities (now on MarketHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When s3 is not providing find_instrument_by_ticker — actually tests s3 None path.

        Since s3 is required in MarketHandler, we test the missing port by having
        find_instrument_by_ticker return None for all tickers.
        """
        # We test the actual 'missing port' case by using an s3 mock that always
        # returns None for instrument lookup, resulting in "not found" for all tickers.
        s3 = _make_s3_port()
        s3.find_instrument_by_ticker.return_value = None
        handler = _make_market_handler(s3=s3)
        result = await handler._handle_compare_entities(entity_tickers=["AAPL", "MSFT"])
        # Not found tickers produce a result with "data unavailable" text
        assert len(result) == 1
        assert "unavailable" in result[0].text.lower() or "comparison" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_too_few_tickers_returns_empty(self) -> None:
        """(f) Too few tickers (< 2) → returns empty list."""
        handler = _make_market_handler()
        result = await handler._handle_compare_entities(entity_tickers=["AAPL"])
        assert result == []

    @pytest.mark.asyncio
    async def test_too_many_tickers_returns_empty(self) -> None:
        """(g) Too many tickers (> 4) → returns empty list."""
        handler = _make_market_handler()
        result = await handler._handle_compare_entities(entity_tickers=["AAPL", "MSFT", "NVDA", "AMD", "INTC"])
        assert result == []

    @pytest.mark.asyncio
    async def test_none_tickers_returns_empty(self) -> None:
        """(f) None tickers (treated as empty list) → returns empty list."""
        handler = _make_market_handler()
        result = await handler._handle_compare_entities(entity_tickers=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: 2 tickers found → single RetrievedItem with comparison text."""
        s3 = _make_s3_port()
        s3.find_instrument_by_ticker.return_value = _FAKE_INSTRUMENT_ID
        s3.get_fundamentals_highlights.return_value = {
            "market_cap": "3T",
            "pe_ratio": 28.5,
            "revenue": "395B",
        }
        s3.get_quote.return_value = {"price": 189.50}
        handler = _make_market_handler(s3=s3)
        result = await handler._handle_compare_entities(entity_tickers=["AAPL", "MSFT"])

        assert len(result) == 1
        item = result[0]
        assert "AAPL" in item.text
        assert "MSFT" in item.text
        assert item.score == pytest.approx(0.88)
        assert item.trust_weight == pytest.approx(0.85)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "fundamentals"

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_degraded_result(self) -> None:
        """(c) Upstream raises TimeoutError on ticker lookup → returns a result with 'unavailable' text.

        WHY: _fetch_one raises are caught by the outer asyncio.gather(return_exceptions=True).
        The exception items are rendered as 'data unavailable' sections in the comparison text,
        which is the R9 graceful degradation behavior (not a hard empty return).
        The result is a single RetrievedItem with the comparison header present.
        """
        s3 = _make_s3_port()
        s3.find_instrument_by_ticker.side_effect = TimeoutError("timeout")
        handler = _make_market_handler(s3=s3)
        result = await handler._handle_compare_entities(entity_tickers=["AAPL", "MSFT"])
        # Outer gather catches the per-ticker exceptions; comparison text is produced
        # with "unavailable" sections for each ticker (R9 graceful degradation).
        assert len(result) == 1
        assert "unavailable" in result[0].text.lower() or "comparison" in result[0].text.lower()


# ── screen_universe tests ─────────────────────────────────────────────────────


class TestScreenUniverse:
    """Tests for _handle_screen_universe (now on MarketHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When s3_brief is None, returns empty list."""
        handler = _make_market_handler(s3_brief=None)
        result = await handler._handle_screen_universe(sector="Technology")
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_dict_returns_empty(self) -> None:
        """(c) Upstream returns {} → returns empty list (R9 degradation)."""
        s3_brief = _make_s3_brief_port(screen_result={})
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_screen_universe()
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: screener returns instruments → single RetrievedItem returned."""
        s3_brief = _make_s3_brief_port(
            screen_result={
                "instruments": [
                    {"ticker": "AAPL", "name": "Apple Inc.", "market_cap": "3T", "pe_ratio": 28.5},
                    {"ticker": "MSFT", "name": "Microsoft Corp.", "market_cap": "2.8T", "pe_ratio": 30.2},
                ]
            }
        )
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_screen_universe(sector="Technology", limit=20)

        assert len(result) == 1
        item = result[0]
        assert "AAPL" in item.text
        assert "MSFT" in item.text
        assert "Screener Results" in item.text
        assert item.score == pytest.approx(0.82)
        assert item.trust_weight == pytest.approx(0.80)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "screener"
        # Verify filters were forwarded as a ScreenRequest-shaped payload
        # (FIX-LIVE-T): sector/industry live INSIDE each filter entry, not at
        # the top level. With no numeric thresholds we inject a no-op
        # market_capitalization >= 0 so the sector predicate binds.
        s3_brief.screen_instruments.assert_awaited_once()
        call_args = s3_brief.screen_instruments.call_args[0][0]
        assert call_args["limit"] == 20
        assert call_args["filters"] == [{"metric": "market_capitalization", "min_value": 0, "sector": "Technology"}]

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty(self) -> None:
        """(c) Upstream raises exception → returns empty list (R9 degradation)."""
        s3_brief = _make_s3_brief_port()
        s3_brief.screen_instruments.side_effect = RuntimeError("S9 unavailable")
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_screen_universe()
        assert result == []

    @pytest.mark.asyncio
    async def test_limit_is_clamped_to_100(self) -> None:
        """limit > 100 is clamped to 100 before forwarding to S9."""
        s3_brief = _make_s3_brief_port(screen_result={"instruments": [{"ticker": "AAPL"}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_screen_universe(limit=9999)
        call_args = s3_brief.screen_instruments.call_args[0][0]
        assert call_args["limit"] == 100

    @pytest.mark.asyncio
    async def test_industry_filter_propagates(self) -> None:
        """FIX-LIVE-M + FIX-LIVE-T: industry kwarg surfaces inside the ScreenRequest filter entry.

        GICS-tagged tickers (NVDA, AMD, AVGO) live under sector='Technology',
        industry='Semiconductors'. The LLM must be able to target the narrower
        bucket; the handler must therefore pass the kwarg through *inside* the
        filter entry (ScreenFilterRequest), not at body-level — the latter
        silently drops on the ScreenRequest schema.
        """
        s3_brief = _make_s3_brief_port(screen_result={"instruments": [{"ticker": "NVDA"}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_screen_universe(
            sector="Technology",
            industry="Semiconductors",
            market_cap_min=50_000_000_000,
            limit=10,
        )
        call_args = s3_brief.screen_instruments.call_args[0][0]
        assert call_args["limit"] == 10
        assert call_args["filters"] == [
            {
                "metric": "market_capitalization",
                "min_value": 50_000_000_000,
                "sector": "Technology",
                "industry": "Semiconductors",
            }
        ]

    @pytest.mark.asyncio
    async def test_industry_not_set_when_none(self) -> None:
        """When industry kwarg is omitted, the key is absent from every filter entry.

        Mirrors the existing sector/region pattern — None values are dropped so
        S9 doesn't receive a literal ``industry=null`` in the request body.
        """
        s3_brief = _make_s3_brief_port(screen_result={"instruments": [{"ticker": "AAPL"}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_screen_universe(sector="Technology")
        call_args = s3_brief.screen_instruments.call_args[0][0]
        for entry in call_args["filters"]:
            assert "industry" not in entry

    @pytest.mark.asyncio
    async def test_payload_matches_screen_request_schema(self) -> None:
        """FIX-LIVE-T regression: payload must be ScreenRequest-shaped.

        The market-data ``POST /v1/fundamentals/screen`` endpoint validates the
        body against ``ScreenRequest(filters: list[ScreenFilterRequest], limit, ...)``.
        Top-level ``sector``/``industry``/``market_cap_min`` are unknown fields
        that pydantic silently drops, which caused Q6 to receive 50 unrelated
        tickers (Healthcare, Industrials, …) instead of the AI-semi bucket.

        This test pins the wire format so a regression to flat-dict-style
        forwarding fails fast.
        """
        s3_brief = _make_s3_brief_port(screen_result={"instruments": [{"ticker": "NVDA"}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_screen_universe(
            sector="Technology",
            industry="Semiconductors",
            market_cap_min=50_000_000_000,
            pe_ratio_max=30.0,
            limit=25,
        )
        payload = s3_brief.screen_instruments.call_args[0][0]
        # Only the documented body-level keys.
        assert set(payload.keys()) == {"filters", "limit"}
        assert payload["limit"] == 25
        # Per-filter keys must come from ScreenFilterRequest only.
        allowed_keys = {"metric", "min_value", "max_value", "sector", "industry", "period_type"}
        for entry in payload["filters"]:
            assert set(entry.keys()).issubset(allowed_keys), entry
            assert "metric" in entry  # required field
            assert entry.get("sector") == "Technology"
            assert entry.get("industry") == "Semiconductors"
        # market_cap and pe_ratio filters present.
        metrics = {e["metric"] for e in payload["filters"]}
        assert "market_capitalization" in metrics
        assert "pe_ratio" in metrics

    @pytest.mark.asyncio
    async def test_numeric_market_cap_is_formatted(self) -> None:
        """FIX-LIVE-DD regression: raw numeric market caps must be rendered.

        Q6 ("Find AI semiconductors above $50B") failed because the
        screener emitted ``MCap: 5230000000000`` and the 8B-parameter
        chat model hallucinated plausible trillion-magnitude strings
        ($5.23T for NVDA) which the numeric-grounding validator then
        flagged as unsupported. The handler must now render BOTH a
        human-friendly ``$X.XXT`` label AND the raw integer (preserved
        so the validator's tolerance check still binds against either
        form). This test pins the wire format.
        """
        s3_brief = _make_s3_brief_port(
            screen_result={
                "instruments": [
                    {"ticker": "NVDA", "name": "NVIDIA Corp.", "market_cap": 3_600_000_000_000},
                    {"ticker": "AMD", "name": "AMD", "market_cap": 240_000_000_000},
                    {"ticker": "MU", "name": "Micron", "market_cap": 130_000_000_000},
                ]
            }
        )
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_screen_universe(
            sector="Technology",
            industry="Semiconductors",
            market_cap_min=50_000_000_000,
        )
        assert len(result) == 1
        text = result[0].text
        # Formatted labels (LLM-friendly) must appear verbatim.
        assert "MCap: $3.60T" in text, text
        assert "MCap: $240.00B" in text, text
        assert "MCap: $130.00B" in text, text
        # Raw integers must be preserved so the numeric-grounding
        # validator can still tolerance-match `$3.60T` ↔ 3_600_000_000_000.
        assert "3600000000000" in text
        assert "240000000000" in text

    @pytest.mark.asyncio
    async def test_legacy_string_market_cap_passthrough(self) -> None:
        """Backward compatibility: pre-formatted string caps stay verbatim.

        Some upstream/mock paths supply ``market_cap: "3T"`` (a legacy
        display label). The formatter MUST NOT mangle these — only
        numeric inputs are reformatted.
        """
        s3_brief = _make_s3_brief_port(
            screen_result={
                "instruments": [
                    {"ticker": "AAPL", "name": "Apple Inc.", "market_cap": "3T"},
                ]
            }
        )
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_screen_universe()
        text = result[0].text
        # Legacy string is passed through unchanged.
        assert "MCap: 3T" in text
        # Must NOT have been wrapped in raw/formatted parentheses.
        assert "(raw: 3T)" not in text

    @pytest.mark.asyncio
    async def test_no_filters_no_scope_emits_empty_filter_list(self) -> None:
        """When no kwargs are given, send ``filters: []`` (no-filter path).

        This preserves the legacy "show first N instruments" behaviour for
        callers that pass no constraints — the ScreenRequest schema accepts
        ``min_length=0`` for filters precisely so this works.
        """
        s3_brief = _make_s3_brief_port(screen_result={"instruments": [{"ticker": "AAPL"}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_screen_universe()
        payload = s3_brief.screen_instruments.call_args[0][0]
        assert payload == {"filters": [], "limit": 20}


# ── get_market_movers tests ───────────────────────────────────────────────────


class TestGetMarketMovers:
    """Tests for _handle_get_market_movers (now on MarketHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When s3_brief is None, returns empty list."""
        handler = _make_market_handler(s3_brief=None)
        result = await handler._handle_get_market_movers()
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_dict_returns_empty(self) -> None:
        """(c) Upstream returns {} → returns empty list."""
        s3_brief = _make_s3_brief_port(movers_result={})
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_market_movers()
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_gainers_returns_retrieved_item(self) -> None:
        """(a) Happy path: gainers data returned → single RetrievedItem with movers text."""
        s3_brief = _make_s3_brief_port(
            movers_result={
                "movers": [
                    {"ticker": "NVDA", "change_percent": 5.2, "price": 850.0},
                    {"ticker": "AMD", "change_percent": 3.1, "price": 175.0},
                ]
            }
        )
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_market_movers(mover_type="gainers", limit=10, period="1d")

        assert len(result) == 1
        item = result[0]
        assert "NVDA" in item.text
        assert "Gainers" in item.text
        assert item.score == pytest.approx(0.85)
        assert item.trust_weight == pytest.approx(0.82)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "market_data"
        # Verify port was called with correct params
        s3_brief.get_top_movers.assert_awaited_once_with(
            mover_type="gainers",
            limit=10,
            period="1d",
        )

    @pytest.mark.asyncio
    async def test_invalid_mover_type_defaults_to_gainers(self) -> None:
        """Invalid mover_type is sanitized to 'gainers' before forwarding to port."""
        s3_brief = _make_s3_brief_port(movers_result={"movers": [{"ticker": "AAPL", "change_percent": 1.5}]})
        handler = _make_market_handler(s3_brief=s3_brief)
        await handler._handle_get_market_movers(mover_type="INVALID_TYPE")
        s3_brief.get_top_movers.assert_awaited_once()
        call_kwargs = s3_brief.get_top_movers.call_args[1]
        assert call_kwargs["mover_type"] == "gainers"

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty(self) -> None:
        """(c) Upstream raises exception → returns empty list (R9 degradation)."""
        s3_brief = _make_s3_brief_port()
        s3_brief.get_top_movers.side_effect = TimeoutError("timeout")
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_market_movers()
        assert result == []


# ── get_economic_calendar tests ───────────────────────────────────────────────


class TestGetEconomicCalendar:
    """Tests for _handle_get_economic_calendar (now on MarketHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When s3_brief is None, returns empty list."""
        handler = _make_market_handler(s3_brief=None)
        result = await handler._handle_get_economic_calendar()
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_list_returns_empty(self) -> None:
        """(c) Upstream returns [] → returns empty list."""
        s3_brief = _make_s3_brief_port(economic_result=[])
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_economic_calendar()
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: events returned → single RetrievedItem with calendar text."""
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
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_economic_calendar(from_date="2026-05-01", to_date="2026-05-31", region="US")

        assert len(result) == 1
        item = result[0]
        assert "CPI" in item.text
        assert "FOMC" in item.text
        assert "Economic Calendar" in item.text
        assert item.score == pytest.approx(0.88)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "economic_calendar"
        # Verify port was called with correct params
        s3_brief.get_economic_calendar.assert_awaited_once_with(
            from_date="2026-05-01",
            to_date="2026-05-31",
            region="US",
        )

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty(self) -> None:
        """(c) Upstream raises exception → returns empty list (R9 degradation)."""
        s3_brief = _make_s3_brief_port()
        s3_brief.get_economic_calendar.side_effect = RuntimeError("S9 unavailable")
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_economic_calendar()
        assert result == []


# ── get_earnings_calendar tests ───────────────────────────────────────────────


class TestGetEarningsCalendar:
    """Tests for _handle_get_earnings_calendar (now on MarketHandler)."""

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(b) When s3_brief is None, returns empty list."""
        handler = _make_market_handler(s3_brief=None)
        result = await handler._handle_get_earnings_calendar()
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_list_returns_empty(self) -> None:
        """(c) Upstream returns [] → returns empty list."""
        s3_brief = _make_s3_brief_port(earnings_result=[])
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_earnings_calendar()
        assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: earnings entries returned → single RetrievedItem with calendar text."""
        s3_brief = _make_s3_brief_port(
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
            ]
        )
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_earnings_calendar(from_date="2026-05-01", to_date="2026-05-31")

        assert len(result) == 1
        item = result[0]
        assert "AAPL" in item.text
        assert "MSFT" in item.text
        assert "Earnings Calendar" in item.text
        assert "EPS Est" in item.text
        assert item.score == pytest.approx(0.88)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "earnings_calendar"
        # Verify port was called with correct params
        s3_brief.get_earnings_calendar.assert_awaited_once_with(
            from_date="2026-05-01",
            to_date="2026-05-31",
        )

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty(self) -> None:
        """(c) Upstream raises exception → returns empty list (R9 degradation)."""
        s3_brief = _make_s3_brief_port()
        s3_brief.get_earnings_calendar.side_effect = RuntimeError("network error")
        handler = _make_market_handler(s3_brief=s3_brief)
        result = await handler._handle_get_earnings_calendar()
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0095 W2 T-W2-02: get_fundamentals_history_batch handler tests.
# Mocks the S3Port batch method; verifies routing of ok/error per ticker,
# the empty-input guard, and the upstream-error R9 fallback.
# ─────────────────────────────────────────────────────────────────────────────


class TestHandleGetFundamentalsHistoryBatch:
    """Tests for _handle_get_fundamentals_history_batch on MarketHandler."""

    @pytest.mark.asyncio
    async def test_get_fundamentals_history_batch_tool_calls_batch_endpoint(self) -> None:
        """Happy path: mocks S3 batch port, asserts POST shape + per-ticker RetrievedItems."""
        s3 = _make_s3_port()
        # Mixed result: 2 ok, 1 error — proves partial-failure rendering.
        s3.get_fundamentals_history_batch = AsyncMock(
            return_value={
                "AAPL": {
                    "status": "ok",
                    "periods": [{"period": "Q4 2024", "revenue": 100.0, "eps": 2.0}],
                },
                "NVDA": {
                    "status": "ok",
                    "periods": [{"period": "Q4 2024", "revenue": 50.0, "eps": 1.0}],
                },
                "BADTICKER": {"status": "error", "reason": "Instrument not found"},
            }
        )
        handler = _make_market_handler(s3=s3)

        result = await handler._handle_get_fundamentals_history_batch(
            tickers=["aapl", "nvda", "badticker"],  # lowercase to exercise normalisation
            periods=4,
        )

        # Three RetrievedItem rows, one per ticker (case-normalised to upper).
        assert isinstance(result, list)
        assert len(result) == 3
        ids = {item.item_id for item in result}
        assert ids == {
            "tool:fundamentals_batch:AAPL",
            "tool:fundamentals_batch:NVDA",
            "tool:fundamentals_batch:BADTICKER",
        }
        # Verify the port was called with normalised upper-case tickers + the same periods.
        s3.get_fundamentals_history_batch.assert_awaited_once_with(
            tickers=["AAPL", "NVDA", "BADTICKER"],
            periods=4,
        )
        # Error ticker renders a clear unavailability message instead of crashing.
        bad = next(item for item in result if "BADTICKER" in item.item_id)
        assert "unavailable" in bad.text.lower()
        assert "Instrument not found" in bad.text

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_empty_list(self) -> None:
        """Empty input → R9 degradation, no port call attempted."""
        s3 = _make_s3_port()
        s3.get_fundamentals_history_batch = AsyncMock()
        handler = _make_market_handler(s3=s3)
        assert await handler._handle_get_fundamentals_history_batch(tickers=[]) == []
        s3.get_fundamentals_history_batch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upstream_raises_returns_empty_list(self) -> None:
        """Upstream raises → returns [] (R9), does not propagate."""
        s3 = _make_s3_port()
        s3.get_fundamentals_history_batch = AsyncMock(side_effect=RuntimeError("boom"))
        handler = _make_market_handler(s3=s3)
        assert await handler._handle_get_fundamentals_history_batch(tickers=["AAPL"]) == []
