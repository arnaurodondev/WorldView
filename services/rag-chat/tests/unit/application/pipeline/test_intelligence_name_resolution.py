"""Tests for PLAN-0093 Wave E-3 T-E-3-01 — name resolution on the 4 KG tools.

Before this fix, the 4 graph-backed tools (search_claims, search_events,
search_entity_relations, get_contradictions) silently returned [] when
no scoped entity_context was set because _require_context_entity bailed
out early. Now they route through _resolve_entity_by_name and call S7's
alias lookup so they work for any entity the user mentions by name.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_RESOLVED_ID = UUID("018f0000-0000-7000-8000-00000000beef")
_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000002")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000003")


def _make_block(name: str, **kwargs: Any) -> Any:
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=kwargs)


def _make_s7(
    *,
    resolve_return: list | None = None,
    relations: list | None = None,
    claims: list | None = None,
    events: list | None = None,
    contradictions: list | None = None,
) -> AsyncMock:
    """Build a mocked S7Port with all relevant methods stubbed."""
    s7 = AsyncMock()
    # The resolve_entity_by_name call returns a list of candidate dicts.
    s7.resolve_entity_by_name.return_value = (
        resolve_return
        if resolve_return is not None
        else [{"entity_id": str(_RESOLVED_ID), "alias_text": "Apple", "similarity": 0.95}]
    )
    s7.search_relations.return_value = relations or []
    s7.search_claims.return_value = claims or []
    s7.search_events.return_value = events or []
    s7.get_contradictions.return_value = contradictions or []
    return s7


def _make_handler(s7: AsyncMock, *, entity_context: Any = None) -> Any:
    """Build an IntelligenceHandler with no scoped entity_context by default.

    The point of the E-3 fix is that the tools must work even with
    entity_context=None — they should fall through to name resolution.
    """
    from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

    return IntelligenceHandler(s7=s7, entity_context=entity_context, timeout=5.0)


def _make_relation() -> Any:
    """Stub for an S7 relation row — only fields the handler formats are needed."""
    from unittest.mock import MagicMock

    r = MagicMock()
    r.subject = "Apple"
    r.relation_type = "INVESTS_IN"
    r.object = "Anthropic"
    r.confidence = 0.92
    r.summary = "Apple invested in Anthropic in 2023."
    return r


def _make_claim() -> Any:
    """Stub matching the handler's expected field set (claim_text, polarity,
    extraction_confidence, etc.). We use a plain object so attribute typing
    is strict — MagicMock format-strings break on numeric format specs."""

    class _Claim:
        claim_id = "claim-1"
        claim_text = "Apple will expand into India."
        claim_type = "strategic_move"
        polarity = "positive"
        extraction_confidence = 0.8
        source = "analyst_report"
        extracted_at = None

    return _Claim()


def _make_event() -> Any:
    class _Event:
        event_id = "evt-1"
        event_type = "earnings"
        event_subtype = None
        event_text = "Apple reports Q3 FY24 earnings: EPS $1.40 on revenue $85B"
        event_date = None
        extraction_confidence = 0.85
        doc_id = None

    return _Event()


def _make_contradiction() -> Any:
    """Stub matching ContradictionResult — sides is a list[dict]."""
    from typing import ClassVar

    class _Contra:
        claim_type = "valuation"
        strength = 0.72
        detected_at = "2026-05-01T00:00:00Z"
        sides: ClassVar[list[dict]] = [
            {"speaker": "Analyst A", "claim_text": "AAPL P/E should be 25"},
            {"speaker": "Analyst B", "claim_text": "AAPL P/E should be 18"},
        ]

    return _Contra()


class TestNameResolutionOnFourKGTools:
    @pytest.mark.asyncio
    async def test_search_claims_resolves_by_name(self) -> None:
        """search_claims with no scope → resolves via S7 alias lookup → returns items."""
        s7 = _make_s7(claims=[_make_claim()])
        handler = _make_handler(s7, entity_context=None)
        block = _make_block("search_claims", entity_name="Apple")
        result = await handler._handle_search_claims(block, entity_name="Apple")
        # The handler resolved Apple → _RESOLVED_ID and called search_claims.
        s7.resolve_entity_by_name.assert_awaited_once()
        s7.search_claims.assert_awaited_once()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_search_events_resolves_by_name(self) -> None:
        s7 = _make_s7(events=[_make_event()])
        handler = _make_handler(s7, entity_context=None)
        block = _make_block("search_events", entity_name="Apple")
        result = await handler._handle_search_events(block, entity_name="Apple")
        s7.resolve_entity_by_name.assert_awaited_once()
        s7.search_events.assert_awaited_once()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_search_entity_relations_resolves_by_name(self) -> None:
        s7 = _make_s7(relations=[_make_relation()])
        handler = _make_handler(s7, entity_context=None)
        block = _make_block("search_entity_relations", entity_name="Apple")
        result = await handler._handle_search_entity_relations(block, entity_name="Apple")
        s7.resolve_entity_by_name.assert_awaited_once()
        s7.search_relations.assert_awaited_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_contradictions_resolves_by_name(self) -> None:
        s7 = _make_s7(contradictions=[_make_contradiction()])
        handler = _make_handler(s7, entity_context=None)
        block = _make_block("get_contradictions", entity_name="Apple")
        result = await handler._handle_get_contradictions(block, entity_name="Apple")
        s7.resolve_entity_by_name.assert_awaited_once()
        s7.get_contradictions.assert_awaited_once()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_unknown_entity_name_returns_empty_with_log(self, capsys: Any) -> None:
        """entity_name='ZZZZZZ' → S7 returns 0 candidates → handler returns [] + logs.

        Regression guard for the E-3 fix: the silent-empty path must now
        emit a structured ``tool_entity_unresolved`` warning so an operator
        can grep for the failure mode in production.

        structlog writes to stdout/stderr (not stdlib logging), so we use
        capsys instead of caplog.
        """
        s7 = _make_s7(resolve_return=[])  # no alias match
        handler = _make_handler(s7, entity_context=None)
        block = _make_block("search_claims", entity_name="ZZZZZZ")
        result = await handler._handle_search_claims(block, entity_name="ZZZZZZ")
        assert result == []
        # search_claims itself was NEVER called — we bailed at resolution.
        s7.search_claims.assert_not_awaited()
        # structlog renders to stdout — verify the structured warning fired.
        captured = capsys.readouterr()
        assert "tool_entity_unresolved" in (captured.out + captured.err)


class TestTickerFirstResolution:
    """BP-661 — ticker-shaped entity_name strings resolve via S6 before S7 alias search.

    The S7 alias index is dominated by ticker-derived noise aliases
    ("AAPL Stock", "AAPL.US") that trip the ambiguity gates; S6's ticker
    resolver matches the exact ticker column and is phantom-twin aware.
    """

    @pytest.mark.asyncio
    async def test_ticker_shaped_name_resolves_via_s6_before_alias_search(self) -> None:
        from unittest.mock import MagicMock

        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        s7 = _make_s7()
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_RESOLVED_ID)
        handler = IntelligenceHandler(s7=s7, s6=s6, entity_context=None, timeout=5.0)

        resolved = await handler._resolve_entity_by_name("get_entity_graph", "AAPL")

        assert resolved == _RESOLVED_ID
        s6.resolve_entity_by_ticker.assert_awaited_once_with("AAPL")
        # S7 alias search must NOT run when the ticker path hits.
        s7.resolve_entity_by_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ticker_miss_falls_back_to_alias_search(self) -> None:
        from unittest.mock import MagicMock

        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        s7 = _make_s7()  # default: resolves "Apple" → _RESOLVED_ID at 0.95
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=None)
        handler = IntelligenceHandler(s7=s7, s6=s6, entity_context=None, timeout=5.0)

        resolved = await handler._resolve_entity_by_name("search_claims", "AAPL")

        assert resolved == _RESOLVED_ID
        s6.resolve_entity_by_ticker.assert_awaited_once()
        s7.resolve_entity_by_name.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_name_public_wrapper_guards_missing_s7(self) -> None:
        """resolve_name (used by NarrativeHandler) returns None when S7 not wired."""
        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        handler = IntelligenceHandler(s7=None, entity_context=None, timeout=5.0)
        assert await handler.resolve_name("get_entity_intelligence", "Apple") is None

    @pytest.mark.asyncio
    async def test_resolve_name_public_wrapper_delegates(self) -> None:
        s7 = _make_s7()
        handler = _make_handler(s7, entity_context=None)
        resolved = await handler.resolve_name("get_entity_intelligence", "Apple")
        assert resolved == _RESOLVED_ID
