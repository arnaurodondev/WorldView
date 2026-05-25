"""Unit tests for the /api/v1/threads endpoints (T-D-4-02).

All tests use dependency_overrides to avoid requiring a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
_THREAD_ID = UUID("01950000-0000-7000-8000-000000000001")  # fake UUIDv7-like

# InternalJWTMiddleware requires X-Internal-JWT; with no public key loaded (unit tests,
# no lifespan) it decodes without signature verification and passes through.
_INTERNAL_JWT = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)

# F-CRIT-001: Only X-Internal-JWT is used; backends read tenant_id/user_id from
# the JWT payload via InternalJWTMiddleware. Legacy headers removed.
_AUTH_HEADERS = {
    "X-Internal-JWT": _INTERNAL_JWT,
}


def _make_mock_uow() -> MagicMock:
    uow = MagicMock()
    uow.threads = MagicMock()
    uow.threads.create = AsyncMock(return_value=None)
    uow.threads.get = AsyncMock(return_value=None)
    uow.threads.list_active = AsyncMock(return_value=([], 0))
    uow.threads.soft_delete = AsyncMock(return_value=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC))
    # PLAN-0051 T-E-5-06: PATCH /threads/{id} -> update_title
    uow.threads.update_title = AsyncMock(return_value=_make_thread())
    uow.commit = AsyncMock(return_value=None)
    return uow


def _make_thread(thread_id: UUID = _THREAD_ID) -> object:
    from rag_chat.domain.entities.conversation import ConversationThread

    now = datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC)
    return ConversationThread(
        thread_id=thread_id,
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        created_at=now,
        updated_at=now,
        title="Test thread",
        entity_ids=(),
        messages=(),
        archived_at=None,
    )


@pytest.fixture
def mock_uow() -> MagicMock:
    return _make_mock_uow()


@pytest.fixture
def app_with_mocks(app: object, mock_uow: MagicMock) -> object:
    """App with UoW and auth dependencies overridden for unit tests."""
    from rag_chat.api.dependencies import get_auth_context, get_read_uow, get_uow

    async def override_uow():  # type: ignore[return]
        yield mock_uow

    async def override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_read_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_auth_context] = override_auth  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_no_auth_override(app: object, mock_uow: MagicMock) -> object:
    """App with only UoW overridden; auth dependency is NOT overridden."""
    from rag_chat.api.dependencies import get_read_uow, get_uow

    async def override_uow():  # type: ignore[return]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_read_uow] = override_uow  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ── POST /api/v1/threads ──────────────────────────────────────────────────────


class TestCreateThreadEndpoint:
    async def test_create_thread_endpoint(self, app_with_mocks: object) -> None:
        """POST /api/v1/threads with valid body → 201 with thread_id and created_at."""
        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/threads",
                json={"title": "My analysis", "entity_ids": []},
                headers=_AUTH_HEADERS,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert "created_at" in data
        assert data["title"] == "My analysis"


# ── GET /api/v1/threads ───────────────────────────────────────────────────────


class TestListThreadsEndpoint:
    async def test_list_threads_endpoint(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads → 200 with threads list and total."""
        thread = _make_thread()
        mock_uow.threads.list_active = AsyncMock(return_value=([thread], 1))

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads?limit=10&offset=0", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["threads"]) == 1
        assert data["threads"][0]["thread_id"] == str(_THREAD_ID)

    async def test_list_threads_empty(self, app_with_mocks: object) -> None:
        """GET /api/v1/threads with no threads → 200, total=0, threads=[]."""
        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["threads"] == []


# ── GET /api/v1/threads/{thread_id} ──────────────────────────────────────────


class TestGetThreadEndpoint:
    async def test_get_thread_endpoint_not_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads/{id} for unknown thread → 404."""
        mock_uow.threads.get = AsyncMock(return_value=None)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 404

    async def test_get_thread_endpoint_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads/{id} for existing thread → 200 with messages list."""
        thread = _make_thread()
        mock_uow.threads.get = AsyncMock(return_value=thread)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert data["messages"] == []


# ── DELETE /api/v1/threads/{thread_id} ───────────────────────────────────────


class TestDeleteThreadEndpoint:
    async def test_delete_thread_endpoint(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """DELETE /api/v1/threads/{id} for owned thread → 200 with archived_at."""

        archived_at = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
        mock_uow.threads.soft_delete = AsyncMock(return_value=archived_at)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert "archived_at" in data

    async def test_delete_thread_not_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """DELETE /api/v1/threads/{id} for unknown thread → 404."""
        from rag_chat.domain.errors import ThreadNotFoundError

        mock_uow.threads.soft_delete = AsyncMock(side_effect=ThreadNotFoundError("not found"))

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 404


# ── PATCH /api/v1/threads/{thread_id} (PLAN-0051 T-E-5-06) ───────────────────


class TestUpdateThreadEndpoint:
    async def test_update_thread_endpoint_renames_title(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """PATCH /api/v1/threads/{id} with valid body -> 200 with new title."""
        from rag_chat.domain.entities.conversation import ConversationThread

        # Construct a thread reflecting the renamed state for the mock to return.
        renamed = ConversationThread(
            thread_id=_THREAD_ID,
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            created_at=datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC),
            title="Renamed analysis",
            entity_ids=(),
            messages=(),
            archived_at=None,
        )
        mock_uow.threads.update_title = AsyncMock(return_value=renamed)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/threads/{_THREAD_ID}",
                json={"title": "Renamed analysis"},
                headers=_AUTH_HEADERS,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert data["title"] == "Renamed analysis"
        # Repository was invoked with the new title (ownership filters applied
        # internally — verified by the kwargs).
        kwargs = mock_uow.threads.update_title.call_args.kwargs
        assert kwargs["title"] == "Renamed analysis"
        assert kwargs["thread_id"] == _THREAD_ID

    async def test_update_thread_not_found_returns_404(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """PATCH on a missing/foreign thread surfaces ThreadNotFoundError as 404."""
        from rag_chat.domain.errors import ThreadNotFoundError

        mock_uow.threads.update_title = AsyncMock(
            side_effect=ThreadNotFoundError("not found"),
        )

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/threads/{_THREAD_ID}",
                json={"title": "New"},
                headers=_AUTH_HEADERS,
            )

        assert resp.status_code == 404


# ── Q-9: MessageResponse extended fields ─────────────────────────────────────


class TestMessageResponseExtendedFields:
    """Verify that Q-9 extended fields are correctly populated (or None for legacy rows)."""

    def _make_message_with_extended_fields(self) -> object:
        """Build a Message domain object with all Q-9 fields populated."""
        from uuid import uuid4

        from rag_chat.domain.entities.chat import ResolvedEntity
        from rag_chat.domain.entities.conversation import ContradictionRef, Message
        from rag_chat.domain.enums import MessageRole

        now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)
        return Message(
            message_id=uuid4(),
            thread_id=_THREAD_ID,
            role=MessageRole.assistant,
            content="NVDA is trading near ATH.",
            created_at=now,
            # Q-9 fields
            provider="deepinfra",
            model="meta-llama/Meta-Llama-3.1-8B-Instruct",
            latency_ms=1400,
            resolved_entities=(
                ResolvedEntity(
                    entity_id=UUID("00000000-0000-0000-0000-000000000010"),
                    canonical_name="NVIDIA",
                    entity_type="company",
                    confidence=0.98,
                    matched_text="NVDA",
                    ticker="NVDA",
                ),
            ),
            contradiction_refs=(
                ContradictionRef(
                    claim_type="price_direction",
                    strength=0.75,
                    sides=({"text": "bullish"}, {"text": "bearish"}),
                ),
            ),
        )

    def _make_legacy_message(self) -> object:
        """Build a Message domain object with all Q-9 fields absent (legacy row)."""
        from uuid import uuid4

        from rag_chat.domain.entities.conversation import Message
        from rag_chat.domain.enums import MessageRole

        return Message(
            message_id=uuid4(),
            thread_id=_THREAD_ID,
            role=MessageRole.user,
            content="What is the price of NVDA?",
            created_at=datetime(2026, 5, 25, 11, 0, 0, tzinfo=UTC),
            # All Q-9 fields left at defaults (None / empty tuple)
        )

    async def test_get_thread_returns_extended_fields_when_populated(
        self,
        app_with_mocks: object,
        mock_uow: MagicMock,
    ) -> None:
        """GET /api/v1/threads/{id} — message with Q-9 fields returns them in response."""
        from rag_chat.domain.entities.conversation import ConversationThread

        msg = self._make_message_with_extended_fields()
        thread = ConversationThread(
            thread_id=_THREAD_ID,
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            created_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            title="Q-9 test thread",
            entity_ids=(),
            messages=(msg,),
            archived_at=None,
        )
        mock_uow.threads.get = AsyncMock(return_value=thread)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 1
        m = data["messages"][0]

        # Q-9 fields must be populated
        assert m["provider"] == "deepinfra"
        assert m["model"] == "meta-llama/Meta-Llama-3.1-8B-Instruct"
        assert m["latency_ms"] == 1400

        # resolved_entities: one entry with all sub-fields
        assert isinstance(m["resolved_entities"], list)
        assert len(m["resolved_entities"]) == 1
        re = m["resolved_entities"][0]
        assert re["canonical_name"] == "NVIDIA"
        assert re["entity_type"] == "company"
        assert re["ticker"] == "NVDA"

        # contradictions: field name differs from DB column name (contradiction_refs → contradictions)
        assert isinstance(m["contradictions"], list)
        assert len(m["contradictions"]) == 1
        con = m["contradictions"][0]
        assert con["claim_type"] == "price_direction"
        assert con["strength"] == 0.75

        # retrieval_plan not yet surfaced on domain entity — always None
        assert m["retrieval_plan"] is None

    async def test_get_thread_returns_none_for_legacy_message_fields(
        self,
        app_with_mocks: object,
        mock_uow: MagicMock,
    ) -> None:
        """GET /api/v1/threads/{id} — legacy message (NULL Q-9 columns) returns None for new fields."""
        from rag_chat.domain.entities.conversation import ConversationThread

        msg = self._make_legacy_message()
        thread = ConversationThread(
            thread_id=_THREAD_ID,
            tenant_id=_TENANT_ID,
            user_id=_USER_ID,
            created_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            updated_at=datetime(2026, 5, 25, 10, 0, 0, tzinfo=UTC),
            title="Legacy thread",
            entity_ids=(),
            messages=(msg,),
            archived_at=None,
        )
        mock_uow.threads.get = AsyncMock(return_value=thread)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        m = data["messages"][0]

        # All Q-9 fields must be None (not absent) for legacy rows
        assert m["provider"] is None
        assert m["model"] is None
        assert m["latency_ms"] is None
        assert m["resolved_entities"] is None
        assert m["retrieval_plan"] is None
        assert m["contradictions"] is None

    def test_message_response_schema_direct_construction_all_none(self) -> None:
        """MessageResponse can be constructed with only legacy fields (Q-9 fields default to None)."""
        from uuid import uuid4

        from rag_chat.api.schemas import MessageResponse

        now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)
        resp = MessageResponse(
            message_id=uuid4(),
            role="user",
            content="hello",
            intent=None,
            citations=[],
            created_at=now,
        )
        # All Q-9 fields should be None by default
        assert resp.provider is None
        assert resp.model is None
        assert resp.latency_ms is None
        assert resp.resolved_entities is None
        assert resp.retrieval_plan is None
        assert resp.contradictions is None

    def test_message_response_schema_direct_construction_populated(self) -> None:
        """MessageResponse can be constructed with all Q-9 fields populated."""
        from uuid import uuid4

        from rag_chat.api.schemas import MessageResponse

        now = datetime(2026, 5, 25, 12, 0, 0, tzinfo=UTC)
        resp = MessageResponse(
            message_id=uuid4(),
            role="assistant",
            content="NVDA is up.",
            intent="price_query",
            citations=[],
            created_at=now,
            provider="deepinfra",
            model="qwen3-235b",
            latency_ms=980,
            resolved_entities=[{"entity_id": "abc", "canonical_name": "NVIDIA"}],
            retrieval_plan={"strategy": "hybrid", "k": 10},
            contradictions=[{"claim_type": "direction", "strength": 0.6, "sides": []}],
        )
        assert resp.provider == "deepinfra"
        assert resp.model == "qwen3-235b"
        assert resp.latency_ms == 980
        assert resp.resolved_entities == [{"entity_id": "abc", "canonical_name": "NVIDIA"}]
        assert resp.retrieval_plan == {"strategy": "hybrid", "k": 10}
        assert resp.contradictions == [{"claim_type": "direction", "strength": 0.6, "sides": []}]


# ── Auth header enforcement ───────────────────────────────────────────────────


class TestThreadsAuthHeaders:
    async def test_threads_require_auth_context(self, app_no_auth_override: object) -> None:
        """POST /api/v1/threads without JWT auth context -> 401."""
        transport = ASGITransport(app=app_no_auth_override)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/threads",
                json={"title": "test"},
                # No auth headers
            )

        assert resp.status_code == 401

    async def test_list_requires_auth_headers(self, app_no_auth_override: object) -> None:
        """GET /api/v1/threads without auth headers → 401."""
        transport = ASGITransport(app=app_no_auth_override)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads")

        assert resp.status_code == 401
