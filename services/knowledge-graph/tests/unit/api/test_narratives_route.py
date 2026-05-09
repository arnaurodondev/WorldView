"""Unit tests for narrative endpoints (PRD-0074 Wave D, T-D-03).

Tests:
  - GET /entities/{id}/narratives: pagination cursor round-trip
  - GET /entities/{id}/narratives: empty history returns empty list
  - POST /entities/{id}/narratives/generate: 202 on first trigger
  - POST /entities/{id}/narratives/generate: 429 when rate-limited (key exists)
  - POST /entities/{id}/narratives/generate: Retry-After header present on 429
  - GET /entities/{id}/intelligence: 200 happy path
  - GET /entities/{id}/intelligence: 404 when entity not found
  - GET /entities/{id}/intelligence: 422 on invalid UUID
  - GET /internal/v1/entities/{id}/intelligence: accessible (200)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ENTITY_ID = uuid4()
_VERSION_ID = uuid4()
_NOW = datetime(2026, 5, 8, 10, 0, 0, tzinfo=UTC)

_SYSTEM_JWT = _jwt.encode(
    {
        "iss": "worldview-gateway",
        "sub": "unit-test-system",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    },
    "unit-test-secret",
    algorithm="HS256",
)
_HEADERS = {"X-Internal-JWT": _SYSTEM_JWT}


def _make_intelligence_public():
    from knowledge_graph.api.schemas_intelligence import ConfidenceBreakdownPublic, EntityIntelligencePublic

    return EntityIntelligencePublic(
        entity_id=_ENTITY_ID,
        canonical_name="Apple Inc.",
        entity_type="company",
        health_score=0.75,
        current_narrative=None,
        confidence_breakdown=ConfidenceBreakdownPublic(relation_count=5),
        key_metrics={"sector": "Technology"},
        data_completeness=0.7,
    )


def _make_narratives_app():
    """Build test app with narrative-specific dependencies overridden."""
    from knowledge_graph.api.dependencies import get_readonly_session
    from knowledge_graph.app import create_app
    from knowledge_graph.config import Settings

    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]

    async def _mock_readonly_session():
        yield AsyncMock()

    app.dependency_overrides[get_readonly_session] = _mock_readonly_session
    return app


def _make_intelligence_app(return_value=None, raise_404: bool = False):
    """Build test app with GetEntityIntelligenceUseCase overridden."""
    from knowledge_graph.api.dependencies import get_entity_intelligence_uc, get_readonly_session
    from knowledge_graph.app import create_app
    from knowledge_graph.config import Settings

    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]

    async def _mock_readonly_session():
        yield AsyncMock()

    app.dependency_overrides[get_readonly_session] = _mock_readonly_session

    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=return_value)
    app.dependency_overrides[get_entity_intelligence_uc] = lambda: mock_uc

    return app


class TestNarrativesListEndpoint:
    async def test_empty_history_returns_empty_list(self) -> None:
        """Entity with no narratives returns empty versions list.

        The use case now returns (versions, next_cursor) — a plain tuple of
        domain objects.  The API layer maps domain types to the wire format
        (R12 — API layer must not import from application/).
        """
        app = _make_narratives_app()

        import knowledge_graph.application.use_cases.list_narrative_versions as _luc_mod

        # UC returns (versions_list, next_cursor) — empty list + None cursor.
        with patch.object(_luc_mod, "ListNarrativeVersionsUseCase") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.execute = AsyncMock(return_value=([], None))
            mock_cls.return_value = mock_instance

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/narratives")

        assert resp.status_code == 200
        data = resp.json()
        assert data["versions"] == []
        assert data["next_cursor"] is None

    async def test_pagination_cursor_in_response(self) -> None:
        """When there are more pages, next_cursor is populated.

        The use case returns (versions, next_cursor) where versions is a list
        of EntityNarrativeVersion domain objects.  The API layer serialises them.
        """
        app = _make_narratives_app()

        import knowledge_graph.application.use_cases.list_narrative_versions as _luc_mod
        from knowledge_graph.domain.narrative import EntityNarrativeVersion, NarrativeGenerationReason

        domain_version = EntityNarrativeVersion(
            version_id=_VERSION_ID,
            entity_id=_ENTITY_ID,
            narrative_text="Apple Inc. is a technology company with wide product portfolio.",
            model_id="meta-llama/Meta-Llama-3.1-8B-Instruct",
            generation_reason=NarrativeGenerationReason.INITIAL,
            generated_at=_NOW,
            is_current=True,
        )

        with patch.object(_luc_mod, "ListNarrativeVersionsUseCase") as mock_cls:
            mock_instance = AsyncMock()
            # UC returns (versions_list, next_cursor)
            mock_instance.execute = AsyncMock(return_value=([domain_version], "dGVzdC1jdXJzb3I="))
            mock_cls.return_value = mock_instance

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/narratives")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 1
        assert data["next_cursor"] == "dGVzdC1jdXJzb3I="


class TestNarrativeGenerateTriggerEndpoint:
    async def test_202_on_first_trigger(self) -> None:
        """POST trigger returns 202 when rate limit not hit."""
        app = _make_narratives_app()

        import knowledge_graph.api.narratives as _narratives_mod

        mock_valkey = AsyncMock()
        mock_valkey.set_nx = AsyncMock(return_value=True)  # allowed — key was newly set

        with (
            patch.object(_narratives_mod, "GenerateNarrativeUseCase"),
            patch("knowledge_graph.api.narratives.ValkeyClient") as mock_valkey_cls,
            patch.object(_narratives_mod, "TriggerNarrativeGenerationUseCase") as mock_trigger_cls,
        ):
            # Make TriggerNarrativeGenerationUseCase.execute return True (allowed)
            mock_trigger_instance = AsyncMock()
            mock_trigger_instance.execute = AsyncMock(return_value=True)
            mock_trigger_cls.return_value = mock_trigger_instance
            mock_valkey_cls.return_value = mock_valkey

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/narratives/generate")

        assert resp.status_code == 202
        data = resp.json()
        assert "queued" in data["message"].lower()
        assert data["entity_id"] == str(_ENTITY_ID)

    async def test_429_when_rate_limited(self) -> None:
        """POST trigger returns 429 when rate limit is hit."""
        app = _make_narratives_app()

        mock_valkey = AsyncMock()
        mock_valkey.set_nx = AsyncMock(return_value=False)  # key already exists — rate-limited

        with (
            patch("knowledge_graph.api.narratives.ValkeyClient") as mock_valkey_cls,
            patch("knowledge_graph.api.narratives.GenerateNarrativeUseCase"),
            patch("knowledge_graph.api.narratives.TriggerNarrativeGenerationUseCase") as mock_trigger_cls,
        ):
            mock_trigger_instance = AsyncMock()
            mock_trigger_instance.execute = AsyncMock(return_value=False)  # rate-limited
            mock_trigger_cls.return_value = mock_trigger_instance
            mock_valkey_cls.return_value = mock_valkey

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/narratives/generate")

        assert resp.status_code == 429

    async def test_429_includes_retry_after_header(self) -> None:
        """429 response must include Retry-After header."""
        app = _make_narratives_app()

        with (
            patch("knowledge_graph.api.narratives.ValkeyClient") as mock_valkey_cls,
            patch("knowledge_graph.api.narratives.GenerateNarrativeUseCase"),
            patch("knowledge_graph.api.narratives.TriggerNarrativeGenerationUseCase") as mock_trigger_cls,
        ):
            mock_trigger_instance = AsyncMock()
            mock_trigger_instance.execute = AsyncMock(return_value=False)
            mock_trigger_cls.return_value = mock_trigger_instance
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/narratives/generate")

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    async def test_422_on_invalid_uuid(self) -> None:
        """POST with invalid UUID returns 422."""
        app = _make_narratives_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.post("/api/v1/entities/not-a-uuid/narratives/generate")
        assert resp.status_code == 422


class TestEntityIntelligenceEndpoint:
    async def test_200_happy_path(self) -> None:
        """GET /entities/{id}/intelligence returns 200 with full payload."""
        intelligence = _make_intelligence_public()
        app = _make_intelligence_app(return_value=intelligence)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/intelligence")

        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == str(_ENTITY_ID)
        assert data["canonical_name"] == "Apple Inc."
        assert data["entity_type"] == "company"
        assert data["health_score"] == pytest.approx(0.75, abs=1e-4)

    async def test_404_when_entity_not_found(self) -> None:
        """GET /entities/{id}/intelligence returns 404 when entity absent."""
        app = _make_intelligence_app(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/api/v1/entities/{_ENTITY_ID}/intelligence")

        assert resp.status_code == 404

    async def test_422_on_invalid_uuid(self) -> None:
        """GET with invalid UUID returns 422."""
        app = _make_intelligence_app(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get("/api/v1/entities/not-a-uuid/intelligence")

        assert resp.status_code == 422

    async def test_internal_route_accessible(self) -> None:
        """GET /internal/v1/entities/{id}/intelligence returns 200."""
        intelligence = _make_intelligence_public()
        app = _make_intelligence_app(return_value=intelligence)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.get(f"/internal/v1/entities/{_ENTITY_ID}/intelligence")

        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == str(_ENTITY_ID)
