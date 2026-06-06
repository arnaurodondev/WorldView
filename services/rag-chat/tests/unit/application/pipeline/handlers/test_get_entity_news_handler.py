"""Tests for the PLAN-0103 W2 ``get_entity_news`` tool handler.

Closes the Q1 catalogue gap from the 2026-05-29 real-user audit
(``docs/audits/2026-05-29-plan-0103-real-user-failures.md``): the LLM
previously had to route entity-anchored news questions through broad
``search_documents``, which returned weak hits.  ``get_entity_news`` is a
direct entity_id (or ticker → entity_id) lookup against the same
``/api/v1/entities/{eid}/briefing-articles`` endpoint the morning brief uses.

Test scenarios:
  1. entity_id path — UUID provided directly, no ticker resolution.
  2. ticker path — UUID resolved via S6.resolve_entity_by_ticker.
  3. default days_back — articles older than the window are filtered out.
  4. max_results cap — the per-call cap is honoured even if upstream returns more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_AAPL_ID = UUID("018f0000-0000-7000-8000-000000aaaa01")
_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-0000000000c1")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-0000000000c2")


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


def _article(idx: int, *, days_ago: int = 1) -> dict[str, Any]:
    published = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return {
        "article_id": f"018f0000-0000-7000-8000-00000000000{idx:1d}",
        "title": f"Apple news headline {idx}",
        "url": f"https://example.com/news/{idx}",
        "published_at": published.isoformat(),
        "source_name": "ExampleWire",
        "source_type": "news",
        "display_relevance_score": 0.75,
    }


class TestGetEntityNewsHandler:
    @pytest.mark.asyncio
    async def test_entity_id_path_skips_ticker_resolution(self) -> None:
        """When entity_id is provided as UUID, no S6 ticker resolution happens."""
        s6 = AsyncMock()
        s6._get = AsyncMock(return_value={"articles": [_article(1)]})
        handler = _make_handler(s6)

        items = await handler._handle_get_entity_news(entity_id=str(_AAPL_ID))

        assert len(items) == 1
        # The path passed to _get must include the resolved entity_id.
        path = s6._get.call_args.args[0]
        assert str(_AAPL_ID) in path
        # No ticker resolution should have happened.
        s6.resolve_entity_by_ticker.assert_not_called()

    @pytest.mark.asyncio
    async def test_ticker_resolution_path(self) -> None:
        """When only ticker is given, S6.resolve_entity_by_ticker is invoked."""
        s6 = AsyncMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_AAPL_ID)
        s6._get = AsyncMock(return_value={"articles": [_article(1)]})
        handler = _make_handler(s6)

        items = await handler._handle_get_entity_news(ticker="AAPL")

        assert len(items) == 1
        s6.resolve_entity_by_ticker.assert_awaited_once_with("AAPL")
        # Path uses the resolved UUID, NOT the ticker.
        path = s6._get.call_args.args[0]
        assert str(_AAPL_ID) in path

    @pytest.mark.asyncio
    async def test_default_days_back_filters_stale_articles(self) -> None:
        """Default days_back=14: a 30-day-old article must be dropped."""
        s6 = AsyncMock()
        s6._get = AsyncMock(
            return_value={
                "articles": [
                    _article(1, days_ago=1),  # fresh — kept
                    _article(2, days_ago=30),  # stale — dropped (default 14d)
                    _article(3, days_ago=5),  # fresh — kept
                ]
            }
        )
        handler = _make_handler(s6)

        items = await handler._handle_get_entity_news(entity_id=str(_AAPL_ID))

        # Only the 2 fresh articles survive the 14-day default.
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_max_results_cap_is_honoured(self) -> None:
        """max_results=2 → only 2 items returned even if upstream gives more."""
        s6 = AsyncMock()
        s6._get = AsyncMock(return_value={"articles": [_article(i, days_ago=1) for i in range(10)]})
        handler = _make_handler(s6)

        items = await handler._handle_get_entity_news(entity_id=str(_AAPL_ID), max_results=2)

        assert len(items) == 2
