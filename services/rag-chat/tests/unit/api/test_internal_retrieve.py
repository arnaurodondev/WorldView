"""Unit tests for POST /v1/internal/retrieve (PLAN-0063 W5-1-00).

Mocks the RetrieveOnlyUseCase and exercises the route layer only. End-to-end
integration with a live orchestrator + dev stack is covered by the eval script
itself running against the deployed service (T-W5-1-02).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000020")
_USER_ID = UUID("00000000-0000-0000-0000-000000000021")

_INTERNAL_JWT = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)
_AUTH_HEADERS = {"X-Internal-JWT": _INTERNAL_JWT}


def _make_retrieve_result(n: int = 3, intent: str = "intent_free"):
    """Build a fake RetrieveOnlyResult with n synthetic candidates."""
    from rag_chat.application.use_cases.retrieve_only import RetrieveOnlyResult
    from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
    from rag_chat.domain.enums import ItemType

    items: list[RetrievedItem] = []
    for i in range(n):
        items.append(
            RetrievedItem.create(
                item_id=str(uuid4()),
                item_type=ItemType.chunk,
                text=f"Synthetic chunk {i} text content used for retrieval scoring.",
                score=1.0 - i * 0.1,
                trust_weight=0.9,
                citation_meta=CitationMeta(
                    title=f"Doc {i}",
                    url=None,
                    source_name="sec_filing",
                    published_at=None,
                    entity_name=None,
                ),
                doc_id=uuid4(),
                published_at=None,
            )
        )
    return RetrieveOnlyResult(intent=intent, candidates=items, rephrased_query="rephrased")


@pytest.fixture
def settings() -> RagChatSettings:
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=True,
    )


@pytest.fixture
def app_with_uc(settings: RagChatSettings):  # type: ignore[return]
    """App with retrieve_only_uc mocked, JWT verification skipped."""
    from rag_chat.api.dependencies import get_auth_context

    app = create_app(settings)
    mock_uc = AsyncMock()
    mock_uc.execute = AsyncMock(return_value=_make_retrieve_result())
    app.state.retrieve_only_uc = mock_uc

    async def _override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_auth_context] = _override_auth
    return app, mock_uc


async def test_internal_retrieve_returns_200_with_candidates(app_with_uc) -> None:
    """Valid query → 200 with ≥1 candidate."""
    app, _uc = app_with_uc
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "Apple iPhone Q4 guidance", "top_k": 20},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    # Intent classification was retired — the harness is now intent-free.
    assert body["intent"] == "intent_free"
    assert body["n_candidates"] == 3
    assert len(body["candidates"]) == 3
    # Rank starts at 1, scores monotonically descending (orchestrator sorted).
    assert body["candidates"][0]["rank"] == 1
    assert body["candidates"][0]["score"] >= body["candidates"][1]["score"]


async def test_internal_retrieve_requires_internal_jwt(settings: RagChatSettings) -> None:
    """No JWT header → 401 (InternalJWTMiddleware rejects)."""
    app = create_app(settings)
    app.state.retrieve_only_uc = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "Apple", "top_k": 10},
            # No X-Internal-JWT header
        )
    assert resp.status_code == 401


async def test_internal_retrieve_respects_top_k(app_with_uc) -> None:
    """top_k argument is forwarded to the use case."""
    app, uc = app_with_uc
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "MSFT earnings", "top_k": 5},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    # Use case received top_k=5 (the route forwards it).
    assert uc.execute.await_args.kwargs["top_k"] == 5


async def test_internal_retrieve_rejects_empty_query(app_with_uc) -> None:
    """Empty query_text → 422 (Pydantic min_length=1)."""
    app, _uc = app_with_uc
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "", "top_k": 10},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 422


async def test_internal_retrieve_accepts_precomputed_embedding(app_with_uc) -> None:
    """Embedding-input path forwards to UC and bypasses the embedder.

    Verifies the L5 contract: when query_embedding is set, UC.execute receives
    it and the embedder is NOT consulted (the embedder mock would have raised
    if called — the use case's own implementation enforces this; here we just
    assert the param flows through).
    """
    app, uc = app_with_uc
    embedding = [0.1] * 1024  # bge-large-en-v1.5 dimension
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "Apple", "query_embedding": embedding, "top_k": 10},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert uc.execute.await_args.kwargs["query_embedding"] == embedding


async def test_internal_retrieve_does_not_call_chat_orchestrator(app_with_uc) -> None:
    """Endpoint uses retrieve_only_uc, not chat_orchestrator (no LLM call)."""
    app, uc = app_with_uc
    chat_mock = AsyncMock()
    chat_mock.execute_sync = AsyncMock()
    app.state.chat_orchestrator = chat_mock
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/internal/retrieve",
            json={"query_text": "Apple", "top_k": 10},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    # The retrieve-only path must not invoke the chat orchestrator (which would
    # call the LLM).
    chat_mock.execute_sync.assert_not_called()
    uc.execute.assert_awaited_once()
