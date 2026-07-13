"""Unit tests for GetEntityPredictionsUseCase (PLAN-0056 Wave C4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


def _make_row(*, condition_id: str = "0xabc", polarity: str | None = "bullish") -> dict[str, object]:
    return {
        "event_id": uuid4(),
        "condition_id": condition_id,
        "question": "Will X happen?",
        "close_time": None,
        "polarity": polarity,
        "polarity_confidence": 0.8,
        "exposure_type": "directly_affected",
        "confidence": 0.9,
    }


def _make_repo(rows: list | None = None, total: int = 0) -> AsyncMock:
    repo = AsyncMock()
    repo.list_prediction_exposures_for_entity = AsyncMock(return_value=(rows or [], total))
    return repo


class TestGetEntityPredictionsUseCase:
    def test_delegates_and_returns_repo_result(self) -> None:
        from knowledge_graph.application.use_cases.get_entity_predictions import (
            GetEntityPredictionsUseCase,
        )

        row = _make_row()
        repo = _make_repo(rows=[row], total=1)

        items, total = asyncio.run(GetEntityPredictionsUseCase(repo).execute(uuid4()))

        assert total == 1
        assert len(items) == 1
        assert items[0]["condition_id"] == "0xabc"
        repo.list_prediction_exposures_for_entity.assert_called_once()

    def test_forwards_entity_id_limit_offset(self) -> None:
        from knowledge_graph.application.use_cases.get_entity_predictions import (
            GetEntityPredictionsUseCase,
        )

        repo = _make_repo()
        entity_id = uuid4()

        asyncio.run(GetEntityPredictionsUseCase(repo).execute(entity_id, limit=100, offset=20))

        kwargs = repo.list_prediction_exposures_for_entity.call_args.kwargs
        assert kwargs["entity_id"] == entity_id
        assert kwargs["limit"] == 100
        assert kwargs["offset"] == 20

    def test_defaults_forwarded(self) -> None:
        from knowledge_graph.application.use_cases.get_entity_predictions import (
            GetEntityPredictionsUseCase,
        )

        repo = _make_repo()

        asyncio.run(GetEntityPredictionsUseCase(repo).execute(uuid4()))

        kwargs = repo.list_prediction_exposures_for_entity.call_args.kwargs
        assert kwargs["limit"] == 50
        assert kwargs["offset"] == 0

    def test_empty_result(self) -> None:
        from knowledge_graph.application.use_cases.get_entity_predictions import (
            GetEntityPredictionsUseCase,
        )

        repo = _make_repo(rows=[], total=0)

        items, total = asyncio.run(GetEntityPredictionsUseCase(repo).execute(uuid4()))

        assert items == []
        assert total == 0

    def test_multiple_markets_returned_in_order(self) -> None:
        from knowledge_graph.application.use_cases.get_entity_predictions import (
            GetEntityPredictionsUseCase,
        )

        row1 = _make_row(condition_id="0x1", polarity="bullish")
        row2 = _make_row(condition_id="0x2", polarity="bearish")
        repo = _make_repo(rows=[row1, row2], total=2)

        items, total = asyncio.run(GetEntityPredictionsUseCase(repo).execute(uuid4()))

        assert total == 2
        assert items[0]["condition_id"] == "0x1"
        assert items[1]["condition_id"] == "0x2"
