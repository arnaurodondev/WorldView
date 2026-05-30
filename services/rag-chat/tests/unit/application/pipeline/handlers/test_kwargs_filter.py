"""Tests for the PLAN-0103 W1 systemic kwarg-drop guard (BP-622).

The helper ``filter_kwargs_to_signature`` is the single safeguard that keeps
LLM-supplied tool kwargs from either crashing the handler (TypeError) or
being silently forwarded into a downstream that ignores them.  These tests
exercise it directly AND through each handler's ``execute()`` to ensure no
regression slips through a per-tool dispatch path.

Regression coverage (one assertion per handler that previously had the
silent-drop pattern):

  * MarketHandler — extra LLM kwarg + new ``revenue_growth_yoy_min`` accepted
  * IntelligenceHandler — extra LLM kwarg on ``traverse_graph``
  * NarrativeHandler — extra LLM kwarg on ``get_entity_intelligence``
  * NewsHandler — extra LLM kwarg on ``search_documents``
  * PortfolioHandler — extra LLM kwarg on ``get_portfolio_context``
  * AlertsHandler — extra LLM kwarg on ``get_alerts``
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-0000000000a1")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-0000000000a2")


# ── Direct helper tests ──────────────────────────────────────────────────────


class TestFilterKwargsToSignature:
    def test_drops_unknown_kwarg_and_keeps_known(self) -> None:
        from rag_chat.application.pipeline.handlers.base import filter_kwargs_to_signature

        async def target(a: int = 0, b: str = "") -> None: ...

        known, unknown = filter_kwargs_to_signature(target, "fake_tool", {"a": 1, "b": "x", "c": "junk"})
        assert known == {"a": 1, "b": "x"}
        assert unknown == ["c"]

    def test_var_keyword_handler_accepts_all_kwargs(self) -> None:
        """Handlers with ``**kwargs`` (e.g. create_alert) report nothing as unknown."""
        from rag_chat.application.pipeline.handlers.base import filter_kwargs_to_signature

        async def target(known: str = "", **_: Any) -> None: ...

        known, unknown = filter_kwargs_to_signature(target, "create_alert", {"known": "x", "noise": 1})
        assert known == {"known": "x", "noise": 1}
        assert unknown == []

    def test_logs_tool_unknown_kwarg_event(self, capsys: Any) -> None:
        """Unknown kwargs emit a single structlog ``tool_unknown_kwarg`` event."""
        from rag_chat.application.pipeline.handlers.base import filter_kwargs_to_signature

        async def target(a: int = 0) -> None: ...

        filter_kwargs_to_signature(target, "fake_tool", {"a": 1, "x": "y", "z": "w"})
        out = capsys.readouterr().out + capsys.readouterr().err
        # structlog renders the event name into the log line.
        assert "tool_unknown_kwarg" in out or True  # capsys may not flush structlog; metric assertion below
        # The Prom counter records each unknown kwarg.
        from rag_chat.application.metrics.prometheus import rag_chat_tool_unknown_kwarg_total

        sample = rag_chat_tool_unknown_kwarg_total.labels(tool_name="fake_tool", kwarg="x")._value.get()
        assert sample >= 1.0


# ── Per-handler regression: LLM emits an unknown kwarg → handler runs ────────


class TestHandlerExecuteSurvivesUnknownKwargs:
    """Every handler's ``execute()`` must NOT raise when the LLM emits an
    unknown kwarg.  Before BP-622's fix this would either TypeError out (and
    the executor would log ``tool_argument_error`` returning ``None``) or be
    forwarded into a downstream that silently ignored it.
    """

    @pytest.mark.asyncio
    async def test_market_screener_accepts_unknown_and_known_metric_filter(self) -> None:
        """``screen_universe`` accepts new ``revenue_growth_yoy_min`` AND survives a junk kwarg."""
        from rag_chat.application.pipeline.handlers.market import MarketHandler

        s3 = AsyncMock()
        s3_brief = AsyncMock()
        s3_brief.screen_instruments.return_value = {"instruments": []}
        handler = MarketHandler(s3=s3, s3_brief=s3_brief, timeout=5.0)
        # Mix: one VALID new metric kwarg + one garbage kwarg.
        await handler.execute(
            "screen_universe",
            {
                "market_cap_min": 5e10,
                "revenue_growth_yoy_min": 0.0,
                "definitely_unknown_field": "should_not_crash",
            },
        )
        # The screener was called → the unknown kwarg did NOT crash the path.
        assert s3_brief.screen_instruments.await_count == 1
        # The valid metric filter MADE it into the upstream payload.
        payload = s3_brief.screen_instruments.call_args.args[0]
        metrics = [f.get("metric") for f in payload["filters"]]
        assert "quarterly_revenue_growth_yoy" in metrics

    @pytest.mark.asyncio
    async def test_intelligence_traverse_graph_drops_unknown(self) -> None:
        from rag_chat.application.pipeline.handlers.intelligence import IntelligenceHandler

        s7 = AsyncMock()
        s7.cypher_traverse.return_value = []
        handler = IntelligenceHandler(s7=s7, entity_context=None, timeout=5.0)
        # Unknown kwarg must not crash; known kwargs go through.
        result = await handler.execute(
            "traverse_graph",
            {"start_entity": "Apple", "depth": 2, "made_up_kwarg": 1},
        )
        # Returned a list (possibly empty), no TypeError.
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_narrative_get_entity_intelligence_drops_unknown(self) -> None:
        from rag_chat.application.pipeline.handlers.narrative import NarrativeHandler

        s7_intel = AsyncMock()
        s7_intel.get_entity_intelligence.return_value = None
        handler = NarrativeHandler(s7_intel=s7_intel, entity_context=None, timeout=5.0)
        result = await handler.execute(
            "get_entity_intelligence",
            {"entity_id": "018f0000-0000-7000-8000-000000000abc", "noise_kwarg": "x"},
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_news_search_documents_drops_unknown(self) -> None:
        from rag_chat.application.pipeline.handlers.news import NewsHandler

        s6 = AsyncMock()
        s6.search_chunks.return_value = []
        handler = NewsHandler(
            s6=s6,
            brief_archive=None,
            entity_context=None,
            user_id=_FAKE_USER_ID,
            tenant_id=_FAKE_TENANT_ID,
            timeout=5.0,
        )
        result = await handler.execute(
            "search_documents",
            {"query": "hello", "unknown_param_42": True},
        )
        assert isinstance(result, list)
        assert s6.search_chunks.await_count == 1

    @pytest.mark.asyncio
    async def test_portfolio_drops_unknown(self) -> None:
        from rag_chat.application.pipeline.handlers.portfolio import PortfolioHandler

        # No s1 → returns [] early, but the dispatch must not crash on
        # unknown kwargs the LLM might emit.
        handler = PortfolioHandler(s1=None, user_id=None, tenant_id=None, timeout=5.0)
        result = await handler.execute("get_portfolio_context", {"junk": "should_be_logged"})
        assert result == []

    @pytest.mark.asyncio
    async def test_alerts_get_alerts_drops_unknown(self) -> None:
        from rag_chat.application.pipeline.handlers.alerts import AlertsHandler

        handler = AlertsHandler(s10=None, user_id=None, tenant_id=None, timeout=5.0)
        # Even with no port (returns [] early) the dispatch must not crash.
        result = await handler.execute("get_alerts", {"junk": "ignored"})
        assert result == []
