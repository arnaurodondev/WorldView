"""Unit tests for GetClusterArticlesUseCase (P2-F)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from content_store.application.use_cases.get_cluster_articles import (
    ClusterArticleDTO,
    GetClusterArticlesUseCase,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_NOW = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)


def _make_dto(cluster_id=None) -> ClusterArticleDTO:
    return ClusterArticleDTO(
        id=uuid4(),
        title="Test Article",
        url="https://example.com/article",
        published_at=_NOW,
        source_name=None,
        cluster_id=cluster_id or uuid4(),
        cluster_size=2,
    )


async def test_execute_returns_dtos_from_repo() -> None:
    """Use case returns whatever the repository returns."""
    cluster_id = uuid4()
    dto1 = _make_dto(cluster_id=cluster_id)
    dto2 = _make_dto(cluster_id=cluster_id)

    repo = AsyncMock()
    repo.get_cluster_article_dtos.return_value = [dto1, dto2]

    uc = GetClusterArticlesUseCase(repo)
    result = await uc.execute(cluster_id)

    assert result == [dto1, dto2]
    repo.get_cluster_article_dtos.assert_awaited_once_with(cluster_id)


async def test_execute_returns_empty_list_for_unknown_cluster() -> None:
    """Unknown cluster_id → repo returns [] → use case returns []."""
    cluster_id = uuid4()
    repo = AsyncMock()
    repo.get_cluster_article_dtos.return_value = []

    uc = GetClusterArticlesUseCase(repo)
    result = await uc.execute(cluster_id)

    assert result == []
