"""RC-1 regression: S6 entity-resolution connection retry + graceful degradation.

The bug (confirmed live 2026-07-04/05, the #1 chat reliability failure): the
pre-loop S6 ``POST /api/v1/entities/resolve`` call reuses a pooled keep-alive
socket that has gone STALE while rag-chat held it idle across a long turn (~80s
of tool calls + synthesis). nlp-pipeline drops the idle connection, so the NEXT
turn's resolve dials a dead socket → ``httpx.ConnectError`` /
``RemoteProtocolError`` → ``UpstreamTransportError`` → the ENTIRE chat turn used
to die ("Exception in ASGI application"), leaving the user with an empty stream.

Two layers of defence, both pinned here:

  1. **Connection resilience** (``S6Client.resolve_entities``) — a single
     ``upstream_unreachable`` transport failure triggers exactly one retry.
     httpx evicts the dead connection on failure, so the retry dials a FRESH
     connection and the turn proceeds normally.

  2. **Graceful degradation** (``ChatPipeline.resolve_entities``) — if the
     resolve is STILL unreachable after the retry, the turn does NOT hard-fail:
     it degrades to an empty entity list (a warning + metric are emitted) so the
     agent loop + synthesis still run and the user gets an answer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from rag_chat.application.pipeline.chat_pipeline import ChatPipeline
from rag_chat.application.pipeline.transport_error import UpstreamTransportError
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.infrastructure.clients.s6_client import S6Client

pytestmark = pytest.mark.unit

_APPLE_ID = "01900000-0000-7000-8000-000000001001"

# A well-formed /entities/resolve success body (one high-confidence entity).
_RESOLVE_OK_BODY: dict[str, Any] = {
    "entities": [
        {
            "entity_id": _APPLE_ID,
            "canonical_name": "Apple Inc.",
            "entity_type": "financial_instrument",
            "confidence": 0.97,
            "matched_text": "Apple",
            "ticker": "AAPL",
        }
    ]
}


def _s6_with_transport(handler: httpx.MockTransport) -> S6Client:
    """Build an S6Client whose real ``_post`` runs against a MockTransport.

    We can't pass a transport through the constructor (the real httpx client is
    created internally), so we swap ``._client`` afterwards — the same pattern
    the existing BaseUpstreamClient transport tests use. This exercises the
    genuine ``_post`` → ``_raise_transport_error_from_httpx`` → retry chain
    rather than mocking it out.
    """
    client = S6Client(base_url="http://nlp-pipeline.test:8006", timeout=5.0)
    client._client = httpx.AsyncClient(base_url="http://nlp-pipeline.test:8006", transport=handler)
    return client


# ── Scenario (a): stale socket on first attempt, success on retry ─────────────


@pytest.mark.asyncio
async def test_resolve_retries_on_stale_socket_then_succeeds() -> None:
    """ConnectError once → fresh-connection retry → resolved entities returned.

    This is the exact stale-socket path: the first send fails at the transport
    layer (dead pooled keep-alive socket), the second send succeeds. The turn
    must proceed WITH the resolved entity — no exception, no degradation.
    """
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate the dead-socket reuse: httpx raises this class when the
            # server has silently dropped a pooled keep-alive connection.
            raise httpx.ConnectError("Server disconnected without sending a response")
        return httpx.Response(200, json=_RESOLVE_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))

    resolved = await client.resolve_entities("How is Apple doing?")

    assert calls["n"] == 2, "expected exactly one retry after the stale-socket failure"
    assert len(resolved) == 1
    # entity_id arrives as the raw JSON string here (s6_client stores it as-is);
    # compare on string form so the assertion is representation-agnostic.
    assert str(resolved[0].entity_id) == _APPLE_ID
    assert resolved[0].ticker == "AAPL"


@pytest.mark.asyncio
async def test_resolve_gives_up_after_retry_and_raises_for_caller_to_degrade() -> None:
    """Both attempts ConnectError → ``UpstreamTransportError`` propagates.

    The S6Client layer does NOT swallow — it retries once then re-raises so the
    orchestrator's graceful-degradation layer (tested below) decides how to
    survive. Pin the attempt count so the retry stays bounded (no infinite loop
    / latency blow-up on a genuinely-down upstream).
    """
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")

    client = _s6_with_transport(httpx.MockTransport(_handler))

    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.resolve_entities("How is Apple doing?")

    assert exc_info.value.reason == "upstream_unreachable"
    assert calls["n"] == 2, "bounded retry: first try + exactly one retry, then give up"


@pytest.mark.asyncio
async def test_resolve_does_not_retry_upstream_5xx() -> None:
    """A 5xx (upstream up-but-unhealthy) is NOT retried — fail fast, no extra call.

    Retrying an unhealthy upstream just burns the tight chat latency budget; the
    error propagates to the degradation layer immediately.
    """
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"detail": "unavailable"})

    client = _s6_with_transport(httpx.MockTransport(_handler))

    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.resolve_entities("How is Apple doing?")

    assert exc_info.value.reason == "upstream_5xx"
    assert calls["n"] == 1, "5xx must NOT be retried"


# ── Scenario (c): first-try success is unchanged (no extra calls) ─────────────


@pytest.mark.asyncio
async def test_resolve_success_first_try_makes_exactly_one_call() -> None:
    """Happy path: one 200 response, one HTTP call, entities returned unchanged."""
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_RESOLVE_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))

    resolved = await client.resolve_entities("How is Apple doing?")

    assert calls["n"] == 1, "no retry on success — behaviour unchanged"
    assert len(resolved) == 1
    assert resolved[0].canonical_name == "Apple Inc."


# ── Scenario (b): the pipeline degrades instead of killing the turn ───────────


def _make_pipeline(**overrides: Any) -> ChatPipeline:
    """Build a ChatPipeline with all collaborators mocked (mirrors test_chat_pipeline)."""
    defaults: dict[str, Any] = {
        "validator": MagicMock(),
        "rate_limiter": MagicMock(),
        "cache": MagicMock(),
        "get_thread": MagicMock(),
        "s6_client": MagicMock(),
        "classifier": MagicMock(),
        "plan_builder": MagicMock(),
        "hyde": MagicMock(),
        "embedder": MagicMock(),
        "retrieval": MagicMock(),
        "reranker": MagicMock(),
        "llm_chain": MagicMock(),
        "persistence": MagicMock(),
    }
    defaults.update(overrides)
    return ChatPipeline(**defaults)


@pytest.mark.asyncio
async def test_pipeline_degrades_when_resolution_unreachable() -> None:
    """RC-1: resolve fails after retries → turn survives with empty entities.

    ``UpstreamTransportError`` is a ``BaseException`` (bypasses ``except
    Exception``), so this pins that the pipeline catches it EXPLICITLY and
    returns ``[]`` rather than letting it bubble up and kill the ASGI turn.
    """
    s6 = MagicMock()
    s6.resolve_entities = AsyncMock(
        side_effect=UpstreamTransportError(
            "upstream_unreachable",
            path="/api/v1/entities/resolve",
            elapsed_ms=12,
        )
    )
    pipeline = _make_pipeline(s6_client=s6)

    from rag_chat.application.metrics import prometheus as _m

    before = _m.rag_entity_resolution_degraded_total.labels(reason="upstream_unreachable")._value.get()

    # Must NOT raise — the whole point of the fix.
    result = await pipeline.resolve_entities("How is Apple doing?")

    assert result == [], "degraded turn proceeds with empty resolved entities"
    after = _m.rag_entity_resolution_degraded_total.labels(reason="upstream_unreachable")._value.get()
    assert after == before + 1, "degradation must emit a metric"


@pytest.mark.asyncio
async def test_pipeline_resolution_success_is_unchanged() -> None:
    """When resolution succeeds, the pipeline returns the resolved entities as before."""
    entity = ResolvedEntity(
        entity_id=UUID(_APPLE_ID),
        canonical_name="Apple Inc.",
        entity_type="financial_instrument",
        confidence=0.97,
        matched_text="Apple",
        ticker="AAPL",
    )
    s6 = MagicMock()
    s6.resolve_entities = AsyncMock(return_value=[entity])
    pipeline = _make_pipeline(s6_client=s6)

    result = await pipeline.resolve_entities("How is Apple doing?")

    # The resolver gate may re-order/filter, but the Apple entity survives a
    # high-confidence single-candidate resolve.
    assert any(r.entity_id == UUID(_APPLE_ID) for r in result)
