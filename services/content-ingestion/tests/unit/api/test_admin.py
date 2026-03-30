"""Unit tests for admin API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

ADMIN_TOKEN = "test-admin-token"  # noqa: S105


def _make_source(
    *,
    source_id: UUID | None = None,
    name: str = "test-source",
    source_type: str = "eodhd",
    enabled: bool = True,
    config: dict | None = None,
) -> MagicMock:
    """Build a mock source model with typical attributes."""
    import common.ids
    import common.time

    src = MagicMock()
    src.id = source_id or common.ids.new_uuid7()
    src.name = name
    src.source_type = source_type
    src.enabled = enabled
    src.config = config or {}
    src.created_at = common.time.utc_now()
    return src


def _make_adapter_state(source_id: UUID, *, error_count: int = 0) -> MagicMock:
    """Build a mock adapter state row."""
    import common.time

    state = MagicMock()
    state.source_id = source_id
    state.last_run_at = common.time.utc_now()
    state.error_count = error_count
    return state


@pytest.fixture
def mock_uow():
    """Create a mock Unit of Work with all repo stubs."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    # Repository mocks
    uow.sources = AsyncMock()
    uow.tasks = AsyncMock()
    uow.adapter_state = AsyncMock()
    uow.fetch_logs = AsyncMock()
    uow.outbox = AsyncMock()
    uow.dlq = AsyncMock()

    return uow


@pytest.fixture
def mock_app(mock_uow):
    """Create a FastAPI app with mocked state for testing."""
    from content_ingestion.app import create_app

    app = create_app()

    # Mock lifespan dependencies on app.state
    app.state.settings = MagicMock(admin_token=ADMIN_TOKEN)
    mock_factory = AsyncMock()
    app.state.session_factory = mock_factory
    app.state.write_factory = mock_factory
    app.state.read_factory = mock_factory
    app.state.valkey = AsyncMock()
    app.state.storage = AsyncMock()
    app.state.uow_factory = lambda: mock_uow

    return app


@pytest.fixture
async def client(mock_app):
    transport = ASGITransport(app=mock_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Auth tests ──────────────────────────────────────────────────────────────


class TestAdminAuth:
    async def test_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources")
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 401

    async def test_valid_token_passes_auth(self, client: AsyncClient, mock_uow) -> None:
        mock_uow.sources.get_all = AsyncMock(return_value=[])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[])

        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200


class TestDLQAuth:
    async def test_dlq_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get("/admin/dlq")
        assert resp.status_code == 401


class TestInternalAuth:
    async def test_internal_health_no_auth_required(self, client: AsyncClient) -> None:
        resp = await client.get("/internal/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    async def test_internal_submit_missing_token_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/internal/v1/ingest/submit",
            json={"source_type": "manual", "raw_content": "test"},
        )
        assert resp.status_code == 401


# ── ListSources tests ──────────────────────────────────────────────────────


class TestListSources:
    async def test_list_sources_empty(self, client: AsyncClient, mock_uow) -> None:
        mock_uow.sources.get_all = AsyncMock(return_value=[])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[])

        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []

    async def test_list_sources_with_data(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source(name="eodhd-news")
        state = _make_adapter_state(src.id)
        mock_uow.sources.get_all = AsyncMock(return_value=[src])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[state])

        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["name"] == "eodhd-news"
        assert data["sources"][0]["enabled"] is True
        assert data["sources"][0]["last_fetch_at"] is not None

    async def test_list_sources_without_adapter_state(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source(name="new-source")
        mock_uow.sources.get_all = AsyncMock(return_value=[src])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[])

        resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["last_fetch_at"] is None


# ── CreateSource tests ──────────────────────────────────────────────────────


class TestCreateSource:
    async def test_create_source_success(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source(name="sec-edgar", source_type="sec_edgar")
        mock_uow.sources.create = AsyncMock(return_value=src)

        resp = await client.post(
            "/api/v1/sources",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "sec-edgar", "source_type": "sec_edgar"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "sec-edgar"
        assert data["source_type"] == "sec_edgar"
        assert data["enabled"] is True
        mock_uow.sources.create.assert_awaited_once()
        mock_uow.commit.assert_awaited_once()


# ── UpdateSource tests ──────────────────────────────────────────────────────


class TestUpdateSource:
    async def test_update_source_success(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source(name="updated")
        mock_uow.sources.get_by_id = AsyncMock(return_value=src)
        mock_uow.sources.update = AsyncMock(return_value=src)

        resp = await client.put(
            f"/api/v1/sources/{src.id}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "updated"
        mock_uow.commit.assert_awaited_once()

    async def test_update_source_not_found(self, client: AsyncClient, mock_uow) -> None:
        mock_uow.sources.get_by_id = AsyncMock(return_value=None)

        resp = await client.put(
            "/api/v1/sources/00000000-0000-0000-0000-000000000001",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"name": "nope"},
        )
        assert resp.status_code == 404

    async def test_update_source_no_changes(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source()
        mock_uow.sources.get_by_id = AsyncMock(return_value=src)

        resp = await client.put(
            f"/api/v1/sources/{src.id}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={},
        )
        assert resp.status_code == 200
        mock_uow.sources.update.assert_not_awaited()


# ── TriggerSource tests ─────────────────────────────────────────────────────


class TestTriggerSource:
    async def test_trigger_source_success(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source()
        mock_uow.sources.get_by_id = AsyncMock(return_value=src)
        mock_uow.tasks.add = AsyncMock()

        resp = await client.post(
            f"/api/v1/sources/{src.id}/trigger",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["source_id"] == str(src.id)
        assert data["task_id"] is not None
        mock_uow.tasks.add.assert_awaited_once()
        mock_uow.commit.assert_awaited_once()

    async def test_trigger_source_not_found(self, client: AsyncClient, mock_uow) -> None:
        mock_uow.sources.get_by_id = AsyncMock(return_value=None)

        resp = await client.post(
            "/api/v1/sources/00000000-0000-0000-0000-000000000001/trigger",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert resp.status_code == 404


# ── PipelineStatus tests ────────────────────────────────────────────────────


class TestPipelineStatus:
    async def test_pipeline_status_empty(self, client: AsyncClient, mock_uow) -> None:
        mock_uow.sources.get_all = AsyncMock(return_value=[])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[])
        mock_uow.outbox.count_pending = AsyncMock(return_value=0)
        mock_uow.dlq.count_failed = AsyncMock(return_value=0)

        resp = await client.get("/api/v1/status", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []
        assert data["outbox_pending"] == 0
        assert data["dlq_count"] == 0

    async def test_pipeline_status_with_data(self, client: AsyncClient, mock_uow) -> None:
        src = _make_source(name="eodhd-news")
        state = _make_adapter_state(src.id, error_count=2)

        mock_uow.sources.get_all = AsyncMock(return_value=[src])
        mock_uow.adapter_state.get_all = AsyncMock(return_value=[state])
        mock_uow.fetch_logs.count_by_source_since = AsyncMock(return_value=42)
        mock_uow.outbox.count_pending = AsyncMock(return_value=5)
        mock_uow.dlq.count_failed = AsyncMock(return_value=1)

        resp = await client.get("/api/v1/status", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sources"]) == 1
        assert data["sources"][0]["name"] == "eodhd-news"
        assert data["sources"][0]["articles_fetched_24h"] == 42
        assert data["sources"][0]["errors_24h"] == 2
        assert data["outbox_pending"] == 5
        assert data["dlq_count"] == 1
