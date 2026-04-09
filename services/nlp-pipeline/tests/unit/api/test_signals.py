"""Unit tests for GET /api/v1/signals (PLAN-0020 Wave A-5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from nlp_pipeline.api.dependencies import get_signals_query_repo
from nlp_pipeline.api.routes.signals import router

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)
_DOC_ID = uuid4()
_ENTITY_ID = uuid4()
_EVENT_ID = uuid4()


def _make_app(repo_mock: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_signals_query_repo] = lambda: repo_mock
    return app


def _signal_row(impact_score: float = 0.0) -> dict:
    payload = {
        "event_id": str(_EVENT_ID),
        "doc_id": str(_DOC_ID),
        "claimer_entity_id": str(_ENTITY_ID),
        "claim_type": "BULLISH",
        "extraction_confidence": 0.85,
        "claim_id": "claim-abc",
        "occurred_at": _NOW.isoformat(),
    }
    return {
        "event_id": _EVENT_ID,
        "partition_key": str(_DOC_ID),
        "payload_avro": json.dumps(payload),
        "created_at": _NOW,
        "impact_score": impact_score,
    }


def _make_repo(rows: list | None = None, total: int | None = None) -> AsyncMock:
    rows = rows or []
    repo = AsyncMock()
    repo.list_signal_events = AsyncMock(return_value=(rows, total if total is not None else len(rows)))
    return repo


class TestListSignalsEndpoint:
    @pytest.mark.asyncio
    async def test_response_includes_market_impact_score(self) -> None:
        """market_impact_score is present in each signal item."""
        repo = _make_repo(rows=[_signal_row(impact_score=0.42)])
        app = _make_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/signals")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert "market_impact_score" in item
        assert item["market_impact_score"] == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_min_impact_score_param_forwarded_to_repo(self) -> None:
        """?min_impact_score query param is forwarded to the use case / repo."""
        repo = _make_repo()
        app = _make_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/signals", params={"min_impact_score": "0.5"})

        assert response.status_code == 200
        call_kwargs = repo.list_signal_events.call_args.kwargs
        assert call_kwargs["min_impact_score"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_order_by_market_impact_score_forwarded_to_repo(self) -> None:
        """?order_by=market_impact_score is forwarded to the repo."""
        repo = _make_repo()
        app = _make_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/signals", params={"order_by": "market_impact_score"})

        assert response.status_code == 200
        call_kwargs = repo.list_signal_events.call_args.kwargs
        assert call_kwargs["order_by"] == "market_impact_score"

    @pytest.mark.asyncio
    async def test_invalid_order_by_returns_422(self) -> None:
        """Unknown order_by value fails pattern validation and returns 422."""
        repo = _make_repo()
        app = _make_app(repo)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/signals", params={"order_by": "foo"})

        assert response.status_code == 422
