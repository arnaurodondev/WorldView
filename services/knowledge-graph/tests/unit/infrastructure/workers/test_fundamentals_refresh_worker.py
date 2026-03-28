"""Unit tests for FundamentalsRefreshWorker (T-D-3-07) — Worker 13D-3."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000042")
_EMB_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state.EntityEmbeddingStateRepository"
)


def _make_session_factory(due_rows: list) -> tuple:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    emb_repo = AsyncMock()
    emb_repo.get_due_for_refresh = AsyncMock(return_value=due_rows)
    emb_repo.upsert = AsyncMock()

    return sf, emb_repo


class TestFundamentalsRefreshWorkerS3Failure:
    def test_s3_down_does_not_update_refresh_at(self) -> None:
        """HTTP failure -> upsert() never called (next_refresh_at not updated)."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "AAPL",
                "canonical_name": "Apple Inc.",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        http_client = AsyncMock()
        http_client.get = AsyncMock(side_effect=RuntimeError("connection refused"))
        http_client.aclose = AsyncMock()

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=None)

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.get_event_loop().run_until_complete(worker.run())

        emb_repo.upsert.assert_not_awaited()

    def test_http_non_200_does_not_update_refresh_at(self) -> None:
        """HTTP 503 -> upsert() never called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "MSFT",
                "canonical_name": "Microsoft",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        mock_response = MagicMock()
        mock_response.status_code = 503

        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=mock_response)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.get_event_loop().run_until_complete(worker.run())

        emb_repo.upsert.assert_not_awaited()

    def test_non_ticker_entity_skipped(self) -> None:
        """Entity without ticker field -> skipped, no HTTP call, upsert not called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": None,
                "canonical_name": "Some Person",
                "entity_type": "person",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        http_client = AsyncMock()
        http_client.get = AsyncMock()

        llm = AsyncMock()

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.get_event_loop().run_until_complete(worker.run())

        http_client.get.assert_not_awaited()
        emb_repo.upsert.assert_not_awaited()

    def test_successful_fetch_calls_upsert(self) -> None:
        """Successful HTTP 200 -> embed called, upsert called."""
        from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker
        from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

        due_rows = [
            {
                "entity_id": _ENTITY_ID,
                "ticker": "AAPL",
                "canonical_name": "Apple Inc.",
                "entity_type": "financial_instrument",
            },
        ]
        sf, emb_repo = _make_session_factory(due_rows)

        fundamentals_data = {
            "revenue_usd_millions": 390000.0,
            "gross_margin_pct": 44.5,
            "net_margin_pct": 25.3,
            "pe_ratio": 28.0,
            "price": 189.0,
            "week_52_high": 200.0,
            "week_52_low": 130.0,
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=fundamentals_data)

        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=mock_response)
        http_client.aclose = AsyncMock()

        llm = AsyncMock()
        llm.embed = AsyncMock(
            return_value=[EmbeddingOutput(embedding=[0.1] * 10, model_id="nomic-embed-text", dimension=10)]
        )

        with patch(_EMB_REPO, return_value=emb_repo):
            worker = FundamentalsRefreshWorker(sf, llm, "http://market-data:8003", http_client=http_client)
            asyncio.get_event_loop().run_until_complete(worker.run())

        llm.embed.assert_awaited_once()
        emb_repo.upsert.assert_awaited_once()
