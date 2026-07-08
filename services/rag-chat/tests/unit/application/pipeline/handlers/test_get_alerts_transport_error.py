"""Tests for the ``get_alerts`` handler's transport-error degradation.

Regression for tc_get_alerts_list_active (chat_quality_benchmark run
run_20260708T084449Z): S10 returned HTTP 500 (``upstream_5xx``), which
``BaseUpstreamClient`` raises as ``UpstreamTransportError`` — a ``BaseException``
that BYPASSES the handler's ``except Exception: return []`` guard and propagates
to ``ToolExecutor`` as ``status=transport_error``. The model then produced an
infra-apology ("the get_alerts data source is currently unavailable …"), which
the judge quality-FAILs as a NON-ANSWER to an answerable first-person question
("What alerts do I currently have set up?").

BP-623's transport-error surfacing is correct for EXTERNAL market-DATA tools
(never fake "no news" on an outage). But ``get_alerts`` reads the user's OWN
alert configuration and its documented R9 contract already promises "[] on ...
any upstream error". The fix catches ``UpstreamTransportError`` in
``_handle_get_alerts`` and degrades to ``[]`` so synthesis returns the graceful
empty-state instead of an outage refusal.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from rag_chat.application.pipeline.transport_error import UpstreamTransportError

pytestmark = pytest.mark.unit

_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-0000000000d1")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-0000000000d2")


def _make_handler(s10: AsyncMock):
    from rag_chat.application.pipeline.handlers.alerts import AlertsHandler

    return AlertsHandler(
        s10=s10,
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        timeout=5.0,
    )


class TestGetAlertsTransportError:
    @pytest.mark.asyncio
    async def test_upstream_5xx_degrades_to_empty_not_outage(self) -> None:
        """A 5xx transport error degrades to [] (R9) instead of escaping as a
        transport-error non-answer. This lets synthesis give the empty-state
        answer for the user's own alert list rather than an infra apology."""
        s10 = AsyncMock()
        s10.get_alerts = AsyncMock(
            side_effect=UpstreamTransportError(
                "upstream_5xx",
                path="/v1/alerts/pending",
                elapsed_ms=505,
                status_code=500,
            )
        )
        handler = _make_handler(s10)

        # Must NOT raise — the BaseException is caught and degraded to [].
        items = await handler._handle_get_alerts()

        assert items == []

    @pytest.mark.asyncio
    async def test_happy_path_still_returns_alerts(self) -> None:
        """R19 guard: the transport-error catch is additive — a successful
        get_alerts still returns the alert items unchanged."""
        s10 = AsyncMock()
        s10.get_alerts = AsyncMock(
            return_value=[{"id": "a1", "condition": "price_below", "threshold": {"price": 100}}]
        )
        handler = _make_handler(s10)

        items = await handler._handle_get_alerts()

        assert len(items) == 1
        assert "price_below" in items[0].text

    @pytest.mark.asyncio
    async def test_empty_alert_list_returns_empty(self) -> None:
        """A user with no alerts yields [] (the graceful empty-state path)."""
        s10 = AsyncMock()
        s10.get_alerts = AsyncMock(return_value=[])
        handler = _make_handler(s10)

        items = await handler._handle_get_alerts()

        assert items == []
