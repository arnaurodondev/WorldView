"""Unit tests for GET /api/v1/entities/{entity_id} endpoint (PRD-0073 §9.6 Wave C-3).

Tests:
- test_entity_detail_200_with_enrichment: enriched entity returns 200 with all fields
- test_entity_detail_200_null_fields: unenriched entity returns 200 with null enrichment fields
- test_entity_detail_404: unknown entity_id returns 404
- test_entity_detail_metadata_fields: metadata dict is mapped to EntityMetadata
- test_entity_detail_invalid_uuid: invalid UUID returns 422
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

# asyncio_mode = "auto" is set in services/knowledge-graph/pyproject.toml (F-Q16),
# so pytest.mark.asyncio is redundant here — only keep the unit marker.
pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 5, 1, 2, 0, 0, tzinfo=UTC)
_ENTITY_ID = UUID("01900000-0000-7000-8000-000000000002")


def _make_canonical_entity(
    entity_type: str = "financial_instrument",
    description: str | None = "Apple Inc. is a technology company.",
    data_completeness: float | None = 0.7,
    metadata: dict | None = None,
) -> Any:
    from knowledge_graph.domain.models import CanonicalEntity

    return CanonicalEntity(
        entity_id=_ENTITY_ID,
        canonical_name="Apple Inc.",
        entity_type=entity_type,
        ticker="AAPL",
        isin="US0378331005",
        exchange="NASDAQ",
        description=description,
        data_completeness=data_completeness,
        enriched_at=_NOW if description else None,
        metadata=metadata or {"sector": "Technology", "country": "USA"},
        enrichment_attempts=0,
    )


class TestEntityDetailEndpoint:
    async def test_entity_detail_200_with_enrichment(self, api_app: Any, api_client: Any) -> None:
        """Enriched entity returns 200 with all fields populated."""
        from knowledge_graph.api.dependencies import get_entity_detail_uc
        from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase

        mock_uc = AsyncMock(spec=GetEntityDetailUseCase)
        mock_uc.execute = AsyncMock(return_value=_make_canonical_entity())

        api_app.dependency_overrides[get_entity_detail_uc] = lambda: mock_uc

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_id"] == str(_ENTITY_ID)
        assert body["canonical_name"] == "Apple Inc."
        assert body["entity_type"] == "financial_instrument"
        assert body["ticker"] == "AAPL"
        assert body["description"] == "Apple Inc. is a technology company."
        assert body["data_completeness"] == 0.7
        assert body["metadata"]["sector"] == "Technology"

        api_app.dependency_overrides.pop(get_entity_detail_uc, None)

    async def test_entity_detail_200_null_fields(self, api_app: Any, api_client: Any) -> None:
        """Unenriched entity returns 200 with null description/completeness."""
        from knowledge_graph.api.dependencies import get_entity_detail_uc
        from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase

        mock_uc = AsyncMock(spec=GetEntityDetailUseCase)
        mock_uc.execute = AsyncMock(
            return_value=_make_canonical_entity(description=None, data_completeness=None, metadata={})
        )

        api_app.dependency_overrides[get_entity_detail_uc] = lambda: mock_uc

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["description"] is None
        assert body["data_completeness"] is None
        assert body["enriched_at"] is None

        api_app.dependency_overrides.pop(get_entity_detail_uc, None)

    async def test_entity_detail_404(self, api_app: Any, api_client: Any) -> None:
        """Unknown entity_id returns 404."""
        from knowledge_graph.api.dependencies import get_entity_detail_uc
        from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase

        mock_uc = AsyncMock(spec=GetEntityDetailUseCase)
        mock_uc.execute = AsyncMock(return_value=None)

        api_app.dependency_overrides[get_entity_detail_uc] = lambda: mock_uc

        resp = await api_client.get(f"/api/v1/entities/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Entity not found"

        api_app.dependency_overrides.pop(get_entity_detail_uc, None)

    async def test_entity_detail_metadata_fields(self, api_app: Any, api_client: Any) -> None:
        """Rich metadata dict is correctly mapped to EntityMetadata fields."""
        from knowledge_graph.api.dependencies import get_entity_detail_uc
        from knowledge_graph.application.use_cases.get_entity_detail import GetEntityDetailUseCase

        mock_uc = AsyncMock(spec=GetEntityDetailUseCase)
        mock_uc.execute = AsyncMock(
            return_value=_make_canonical_entity(
                metadata={
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "country": "US",
                    "employee_count": 164000,
                    "founded_year": 1976,
                    "headquarters_city": "Cupertino",
                    "headquarters_country": "USA",
                }
            )
        )

        api_app.dependency_overrides[get_entity_detail_uc] = lambda: mock_uc

        resp = await api_client.get(f"/api/v1/entities/{_ENTITY_ID}")

        assert resp.status_code == 200
        body = resp.json()
        meta = body["metadata"]
        assert meta["sector"] == "Technology"
        assert meta["industry"] == "Consumer Electronics"
        assert meta["employee_count"] == 164000
        assert meta["founded_year"] == 1976
        assert meta["headquarters_city"] == "Cupertino"

        # F-Q15: enriched_at must serialise as an ISO-8601 string and
        # data_completeness must be a float.  The previous metadata-fields test only
        # checked the metadata dict, missing top-level field type contracts.
        assert isinstance(body["enriched_at"], str)
        # ISO-8601 UTC must include 'T' between date+time and end with a tz marker.
        assert "T" in body["enriched_at"]
        assert (
            body["enriched_at"].endswith("Z")
            or "+" in body["enriched_at"]
            or body["enriched_at"].endswith(
                "+00:00",
            )
        )
        assert isinstance(body["data_completeness"], float)

        api_app.dependency_overrides.pop(get_entity_detail_uc, None)

    async def test_entity_detail_invalid_uuid(self, api_client: Any) -> None:
        """Non-UUID entity_id path param returns 422 Unprocessable Entity."""
        resp = await api_client.get("/api/v1/entities/not-a-uuid")
        assert resp.status_code == 422
