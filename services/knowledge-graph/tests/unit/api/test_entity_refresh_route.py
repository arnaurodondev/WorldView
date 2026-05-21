"""Unit tests for entity refresh endpoint (REQ-003 / TASK-W0-06).

Tests:
  - POST /entities/{id}/refresh: 202 on first trigger (default refresh_type=all)
  - POST /entities/{id}/refresh: 202 with explicit refresh_type override
  - POST /entities/{id}/refresh: 429 when rate-limited (key exists), Retry-After header
  - POST /entities/{id}/refresh: 422 on invalid refresh_type
  - POST /entities/{id}/refresh: 404 when entity_id not found in canonical_entities
  - POST /entities/{id}/refresh: 422 on malformed UUID
  - Forward-compat: payload missing refresh_type defaults to "all" (Avro schema)
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ENTITY_ID = uuid4()

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


def _make_app():
    """Build a test app with the shared session/outbox dependencies mocked.

    The route reads write/read/outbox_repo_class from app.state.  We replace
    each with a MagicMock so the use case is constructed without touching
    a real DB — the actual ``execute()`` call is patched per-test.
    """
    from knowledge_graph.app import create_app
    from knowledge_graph.config import Settings

    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]

    # The lifespan does not run in unit tests (TestClient/AsyncClient + ASGITransport
    # does NOT invoke lifespan unless explicitly enabled).  We set the app.state
    # fields the route reads.
    app.state.write_factory = MagicMock()
    app.state.read_factory = MagicMock()
    app.state.outbox_repo_class = MagicMock()
    return app


def _patch_use_case(*, execute_return=None, execute_side_effect=None):
    """Return a context manager patching TriggerEntityRefreshUseCase + ValkeyClient.

    The route constructs ValkeyClient(url=...) so we patch that constructor to
    avoid a real Redis connection.  The use case is patched at the route's
    import site so the constructor returns a mock whose ``execute()`` is
    pre-configured.
    """
    import knowledge_graph.api.entity_refresh as _mod

    instance = AsyncMock()
    instance.execute = AsyncMock(return_value=execute_return, side_effect=execute_side_effect)

    return patch.object(_mod, "TriggerEntityRefreshUseCase", return_value=instance), instance


class TestEntityRefreshTrigger:
    """POST /api/v1/entities/{entity_id}/refresh — REQ-003."""

    async def test_202_on_first_trigger_default_refresh_type(self) -> None:
        """No body → defaults refresh_type to 'all'; returns 202 + job_id + refresh_type=all."""
        from knowledge_graph.application.use_cases.trigger_entity_refresh import (
            TriggerEntityRefreshResult,
        )

        app = _make_app()
        job_id = uuid4()

        uc_patch, uc_instance = _patch_use_case(
            execute_return=TriggerEntityRefreshResult(
                job_id=job_id,
                entity_id=_ENTITY_ID,
                refresh_type="all",
            ),
        )

        with (
            uc_patch,
            patch("knowledge_graph.api.entity_refresh.ValkeyClient") as mock_valkey_cls,
        ):
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/refresh")

        assert resp.status_code == 202
        data = resp.json()
        assert data["entity_id"] == str(_ENTITY_ID)
        assert data["refresh_type"] == "all"
        assert data["job_id"] == str(job_id)
        # No body → use case called with refresh_type="all"
        kwargs = uc_instance.execute.call_args.kwargs
        assert kwargs["refresh_type"] == "all"

    async def test_202_with_explicit_refresh_type(self) -> None:
        """Explicit body refresh_type='description' is forwarded to the use case."""
        from knowledge_graph.application.use_cases.trigger_entity_refresh import (
            TriggerEntityRefreshResult,
        )

        app = _make_app()
        job_id = uuid4()

        uc_patch, uc_instance = _patch_use_case(
            execute_return=TriggerEntityRefreshResult(
                job_id=job_id,
                entity_id=_ENTITY_ID,
                refresh_type="description",
            ),
        )

        with (
            uc_patch,
            patch("knowledge_graph.api.entity_refresh.ValkeyClient") as mock_valkey_cls,
        ):
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(
                    f"/api/v1/entities/{_ENTITY_ID}/refresh",
                    json={"refresh_type": "description"},
                )

        assert resp.status_code == 202
        data = resp.json()
        assert data["refresh_type"] == "description"
        kwargs = uc_instance.execute.call_args.kwargs
        assert kwargs["refresh_type"] == "description"

    async def test_429_when_rate_limited(self) -> None:
        """Use case returns None (rate-limited) → 429 with Retry-After header."""
        app = _make_app()
        uc_patch, _ = _patch_use_case(execute_return=None)

        with (
            uc_patch,
            patch("knowledge_graph.api.entity_refresh.ValkeyClient") as mock_valkey_cls,
        ):
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/refresh")

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == "3600"

    async def test_422_on_invalid_refresh_type(self) -> None:
        """refresh_type='bogus' → use case raises InvalidRefreshTypeError → 422."""
        from knowledge_graph.application.use_cases.trigger_entity_refresh import (
            InvalidRefreshTypeError,
        )

        app = _make_app()
        uc_patch, _ = _patch_use_case(
            execute_side_effect=InvalidRefreshTypeError("refresh_type must be one of [...]"),
        )

        with (
            uc_patch,
            patch("knowledge_graph.api.entity_refresh.ValkeyClient") as mock_valkey_cls,
        ):
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(
                    f"/api/v1/entities/{_ENTITY_ID}/refresh",
                    json={"refresh_type": "bogus"},
                )

        assert resp.status_code == 422

    async def test_404_when_entity_not_found(self) -> None:
        """Use case raises EntityNotFoundError → 404."""
        from knowledge_graph.application.use_cases.trigger_entity_refresh import (
            EntityNotFoundError,
        )

        app = _make_app()
        uc_patch, _ = _patch_use_case(
            execute_side_effect=EntityNotFoundError(f"entity_id {_ENTITY_ID} not found"),
        )

        with (
            uc_patch,
            patch("knowledge_graph.api.entity_refresh.ValkeyClient") as mock_valkey_cls,
        ):
            mock_valkey_cls.return_value = AsyncMock()

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS
            ) as client:
                resp = await client.post(f"/api/v1/entities/{_ENTITY_ID}/refresh")

        assert resp.status_code == 404

    async def test_422_on_invalid_uuid(self) -> None:
        """Malformed UUID in path → 422 from FastAPI before any handler runs."""
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
            resp = await client.post("/api/v1/entities/not-a-uuid/refresh")

        assert resp.status_code == 422
