"""Tests for PLAN-0093 Wave E-4 T-E-4-02 — entity_tickers → UUID resolution.

Before this fix, the LLM-supplied ``entity_tickers=["AAPL","MSFT"]`` field
was silently ignored, so comparison queries returned generic results.
Now the handler resolves each ticker via S6.resolve_entity_by_ticker and
forwards the UUIDs to the S6 hybrid search.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_AAPL_ID = UUID("018f0000-0000-7000-8000-000000aaaa01")
_MSFT_ID = UUID("018f0000-0000-7000-8000-000000ffff02")
_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000002")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000003")


def _make_block(name: str, **kwargs: Any) -> Any:
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=kwargs)


def _make_s6(ticker_map: dict[str, UUID | None] | None = None) -> AsyncMock:
    """Build a mocked S6Port with resolve_entity_by_ticker stubbed.

    ``ticker_map`` lets each test choose what each ticker resolves to.
    Unknown tickers default to None.
    """
    s6 = AsyncMock()

    async def _resolve(ticker: str) -> UUID | None:
        if ticker_map is None:
            return None
        return ticker_map.get(ticker.upper())

    s6.resolve_entity_by_ticker.side_effect = _resolve
    s6.search_chunks.return_value = []
    return s6


def _make_handler(s6: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.news import NewsHandler

    return NewsHandler(
        s6=s6,
        brief_archive=None,
        entity_context=None,
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        timeout=5.0,
    )


class TestEntityTickersResolution:
    @pytest.mark.asyncio
    async def test_entity_tickers_resolved_to_uuids(self) -> None:
        """Input [AAPL, MSFT] → S6 hybrid search receives both UUIDs."""
        s6 = _make_s6({"AAPL": _AAPL_ID, "MSFT": _MSFT_ID})
        handler = _make_handler(s6)
        block = _make_block(
            "search_documents",
            query="compare Apple and Microsoft",
            entity_tickers=["AAPL", "MSFT"],
        )
        await handler._handle_search_documents(
            block,
            query="compare Apple and Microsoft",
            entity_tickers=["AAPL", "MSFT"],
        )
        # Both tickers were resolved.
        assert s6.resolve_entity_by_ticker.await_count == 2
        # The S6 hybrid search received exactly those UUIDs.
        req = s6.search_chunks.call_args.args[0]
        assert set(req.entity_ids) == {_AAPL_ID, _MSFT_ID}

    @pytest.mark.asyncio
    async def test_unknown_ticker_logged_and_skipped(self, capsys: Any) -> None:
        """Input [ZZZZZ] → logged warning + entity_ids=None (preserves any-entity)."""
        s6 = _make_s6({})  # no tickers resolvable
        handler = _make_handler(s6)
        block = _make_block(
            "search_documents",
            query="news",
            entity_tickers=["ZZZZZ"],
        )
        await handler._handle_search_documents(
            block,
            query="news",
            entity_tickers=["ZZZZZ"],
        )
        req = s6.search_chunks.call_args.args[0]
        # No UUIDs were resolvable → entity_ids stays None (any-entity).
        assert req.entity_ids is None
        out = capsys.readouterr()
        assert "entity_ticker_unresolved" in (out.out + out.err)
