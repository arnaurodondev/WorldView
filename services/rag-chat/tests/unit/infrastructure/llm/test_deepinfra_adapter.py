"""Security regression tests for DeepInfra + OpenRouter adapters (PLAN-0093 QA-7).

F3: the `tool_call_bad_json` warning previously logged the first 100 chars of
the raw arguments string. That string can carry user-entered text from
LLM-generated tool arguments (e.g. `search_documents.query`), so it must not
appear in any structured log field. We now log only `raw_length` and `name`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import httpx
import pytest
import structlog
from rag_chat.infrastructure.llm.deepinfra_adapter import DeepInfraCompletionAdapter
from rag_chat.infrastructure.llm.openrouter_adapter import OpenRouterCompletionAdapter

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _structlog_to_stdlib() -> Iterator[None]:
    """Route structlog through stdlib so pytest's `caplog` can capture events.

    Same redirect pattern as test_tool_executor.py. Critical because the
    `tool_call_bad_json` warning is emitted via structlog; without this,
    caplog never sees the record and the redaction assertion is vacuous.

    WHY restore: ``structlog.configure`` mutates a process-global. Without a
    restore step, every subsequent test in the pytest session inherits the
    stdlib-routed config — including tests that rely on structlog's default
    stdout renderer (``capsys`` assertions in test_chat_orchestrator_tool_loop.py).
    """
    prior_config = structlog.get_config()
    structlog.configure(
        processors=[structlog.processors.KeyValueRenderer(key_order=["event"])],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    try:
        yield
    finally:
        structlog.reset_defaults()
        structlog.configure(**prior_config)


# Sentinel string we feed in as malformed arguments. The 20-char length is what
# the test asserts via raw_length; the substring "sensitive" is what the test
# asserts is NOT present anywhere in the captured log record.
_SENSITIVE_ARGS = "sensitive user query"  # 20 chars exactly


def _assert_redacted(caplog_records: list[logging.LogRecord]) -> None:
    """Assert that no captured record exposes the sensitive payload string.

    Under the test's structlog configuration (KeyValueRenderer + stdlib logging),
    every structured field is rendered into the LogRecord's message as
    ``key=value`` pairs. We therefore search:

    1. ``record.getMessage()`` — primary surface area;
    2. every string value in ``record.__dict__`` — defensive against renderers
       that stash fields as record attributes.

    We also assert that at least one record carries the ``tool_call_bad_json``
    event marker AND ``raw_length=20`` — confirming the diagnostic was emitted
    without the underlying payload.
    """
    saw_event = False
    saw_raw_length_20 = False
    for record in caplog_records:
        message = record.getMessage()
        # 1. Message must not leak the payload.
        assert "sensitive" not in message.lower(), f"message leaked: {message}"
        # 2. Walk every string attribute as well (some renderers stash fields here).
        for attr_name, attr_value in record.__dict__.items():
            if isinstance(attr_value, str):
                assert (
                    "sensitive" not in attr_value.lower()
                ), f"structured field '{attr_name}' leaked sensitive payload: {attr_value!r}"
        if "tool_call_bad_json" in message:
            saw_event = True
        # KeyValueRenderer writes `raw_length=20` into the message text.
        if "raw_length=20" in message:
            saw_raw_length_20 = True

    assert saw_event, "tool_call_bad_json event was not emitted"
    assert saw_raw_length_20, "expected `raw_length=20` on the warning record"


def test_deepinfra_tool_call_bad_json_redacts_raw_arguments(caplog) -> None:
    """Malformed JSON args -> log carries raw_length + name only, never the payload."""
    adapter = DeepInfraCompletionAdapter(api_key="x", http_client=AsyncMock())
    raw_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "search_documents",
                # Invalid JSON (no quotes) so _parse_tool_calls hits the warning branch.
                "arguments": _SENSITIVE_ARGS,
            },
        }
    ]
    with caplog.at_level(logging.WARNING):
        result = adapter._parse_tool_calls(raw_calls)
    # Function still returns a ToolUseBlock with empty input (graceful degradation).
    assert len(result) == 1
    assert result[0].input == {}
    _assert_redacted(caplog.records)


def test_openrouter_tool_call_bad_json_redacts_raw_arguments(caplog) -> None:
    """Same redaction contract as DeepInfra — OpenRouter must not leak either."""
    adapter = OpenRouterCompletionAdapter(api_key="x", http_client=AsyncMock())
    raw_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "search_documents",
                "arguments": _SENSITIVE_ARGS,
            },
        }
    ]
    with caplog.at_level(logging.WARNING):
        result = adapter._parse_tool_calls(raw_calls)
    assert len(result) == 1
    assert result[0].input == {}
    _assert_redacted(caplog.records)


# ── PLAN-0104 W43 / BP-NEW ────────────────────────────────────────────────────
# Same-provider model fallback when the primary completion model returns an
# empty SSE stream on second-turn synthesis.  Root cause: Round 6 Q5
# ``ru_googl_pe_vs_history`` — DeepInfra responded 200 OK + immediate
# ``data: [DONE]`` (no content frames) after a ~56s multi-tool call against
# the Qwen3-235B primary.  W40 cross-provider failover could not help because
# the live stack only has DeepInfra wired.  The adapter now transparently
# retries with a lighter chat model on the SAME provider before raising.


def _sse_done_only() -> bytes:
    """SSE body that reproduces the zero-chunk failure mode (just [DONE])."""
    return b"data: [DONE]\n\n"


def _sse_with_content(text: str) -> bytes:
    """SSE body that yields a single content delta then [DONE]."""
    import json as _json

    frame = {"choices": [{"delta": {"content": text}}]}
    return f"data: {_json.dumps(frame)}\n\ndata: [DONE]\n\n".encode()


@pytest.mark.asyncio
async def test_stream_chat_falls_back_to_secondary_model_on_zero_chunk() -> None:
    """Primary model emits no content frames → adapter retries on the fallback model.

    This is the W43 regression: the primary (Qwen3-235B in prod) returned a
    200 OK + [DONE]-only SSE; without this fix the orchestrator's W36 path
    would have synthesised a degraded answer.  With the fix we recover a real
    LLM answer by retrying the SAME provider with the lighter fallback model.
    """
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        # Record which model each request used so we can assert the fallback
        # was actually attempted with the alternate model id.
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        if body["model"] == "primary/zero-chunk-model":
            # Primary: 200 OK + [DONE] only, no content frames — reproduces
            # the live failure mode observed against Qwen3-235B.
            return httpx.Response(200, content=_sse_done_only())
        # Secondary: returns a real answer.
        return httpx.Response(200, content=_sse_with_content("recovered answer"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/zero-chunk-model",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    chunks: list[str] = []
    async for chunk in adapter.stream_chat([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    # Adapter must have retried — two HTTP requests, second with fallback model.
    assert [c["model"] for c in calls] == [
        "primary/zero-chunk-model",
        "fallback/light-chat-model",
    ]
    # The user-visible stream must carry the secondary model's content.
    assert "".join(chunks) == "recovered answer"
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_chat_no_fallback_when_disabled() -> None:
    """``stream_chat_fallback_model=None`` preserves legacy zero-chunk behaviour.

    We rely on this so the chain-level W40 + orchestrator-level W36 paths
    remain testable in isolation and so operators can opt out via env var.
    """
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        return httpx.Response(200, content=_sse_done_only())

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/zero-chunk-model",
        http_client=client,
        stream_chat_fallback_model=None,
    )

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
    # Exactly one HTTP request, zero recovered chunks → W40/W36 still owns recovery.
    assert chunks == []
    assert len(calls) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_chat_no_fallback_when_primary_succeeds() -> None:
    """Happy path: primary model yields content → no retry, latency unchanged."""
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        return httpx.Response(200, content=_sse_with_content("primary answer"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/ok-model",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "primary answer"
    # Exactly one upstream call — fallback must NOT trigger on the happy path.
    assert [c["model"] for c in calls] == ["primary/ok-model"]
    await client.aclose()


# ── PLAN-0104 W46 / BP-NEW ────────────────────────────────────────────────────
# Same-provider model fallback when the primary model raises a retriable error
# (HTTP 429 / 5xx / timeout) BEFORE yielding any chunk.  Root cause: Round 7 v2
# Q1 ``ru_aapl_pe_simple`` (second-turn 429 chain-exhaustion → W36 fallback)
# and Q2 ``ru_meta_eps_trend`` (first-turn 429 chain-exhaustion → empty answer).
# Curl reproduction: rotating the DeepInfra key (2026-06-02) tightened the
# per-model rate limit on Qwen3-235B specifically; Llama-3.1-8B on the same
# key was unaffected.  The adapter now retries on the configured fallback
# model for retriable errors in BOTH ``chat_with_tools`` (first turn) and
# ``stream_chat`` (second turn), not only on the zero-chunk path covered by W43.


@pytest.mark.asyncio
async def test_stream_chat_falls_back_on_429_from_primary() -> None:
    """Primary 429 before any chunk -> adapter retries on the fallback model.

    This covers W46 for the second-turn path: when the chain has only DeepInfra
    wired, a 429 on Qwen3-235B should not propagate as ``RuntimeError`` to the
    orchestrator's W36 fallback — the lighter Llama model on the SAME key
    almost always answers immediately.
    """
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        if body["model"] == "primary/rate-limited-model":
            return httpx.Response(429, content=b'{"error":"rate_limited"}')
        return httpx.Response(200, content=_sse_with_content("recovered answer"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/rate-limited-model",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    chunks = [c async for c in adapter.stream_chat([{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "recovered answer"
    assert [c["model"] for c in calls] == [
        "primary/rate-limited-model",
        "fallback/light-chat-model",
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_chat_propagates_non_retriable_error_without_fallback() -> None:
    """4xx auth/validation errors propagate immediately — fallback wouldn't help.

    A 401 on the primary means the API key is wrong; the fallback model would
    just 401 too.  We must NOT double the upstream cost on misconfiguration.
    """
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        return httpx.Response(401, content=b'{"error":"unauthorized"}')

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/auth-broken",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}]):
            pass
    # Only ONE upstream call — fallback must NOT trigger on 401.
    assert [c["model"] for c in calls] == ["primary/auth-broken"]
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_with_tools_falls_back_on_429_from_primary() -> None:
    """First-turn 429 on the primary -> adapter retries on the fallback model.

    This is the W46 fix for Q2 ``ru_meta_eps_trend``: previously the chain
    exhausted its retry budget on the rate-limited primary and the orchestrator
    emitted ``llm_first_turn_failed`` with an empty answer.  After W46 the
    in-adapter fallback recovers the call on the same key.
    """
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        if body["model"] == "primary/rate-limited-model":
            return httpx.Response(429, content=b'{"error":"rate_limited"}')
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "recovered", "tool_calls": []},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/rate-limited-model",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    resp = await adapter.chat_with_tools(messages=[{"role": "user", "content": "hi"}])
    assert resp.text == "recovered"
    assert [c["model"] for c in calls] == [
        "primary/rate-limited-model",
        "fallback/light-chat-model",
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_with_tools_propagates_non_retriable_error() -> None:
    """4xx auth on first-turn must propagate — fallback wouldn't help."""
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        return httpx.Response(401, content=b'{"error":"unauthorized"}')

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/auth-broken",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    with pytest.raises(httpx.HTTPStatusError):
        await adapter.chat_with_tools(messages=[{"role": "user", "content": "hi"}])
    assert [c["model"] for c in calls] == ["primary/auth-broken"]
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_with_tools_no_fallback_when_primary_succeeds() -> None:
    """Happy path: one upstream call, fallback model is never touched."""
    calls: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        calls.append({"model": body["model"]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "primary answer", "tool_calls": []},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(
        api_key="x",
        model="primary/ok-model",
        http_client=client,
        stream_chat_fallback_model="fallback/light-chat-model",
    )

    resp = await adapter.chat_with_tools(messages=[{"role": "user", "content": "hi"}])
    assert resp.text == "primary answer"
    assert [c["model"] for c in calls] == ["primary/ok-model"]
    await client.aclose()


# ── PLAN-0107 follow-up: synthesis-turn quality (tools=[], seed pass-through) ──
# The synthesis-turn stream_chat call must be able to (a) forbid function calling
# (so the model can't emit `<tool_call>` XML as visible text) and (b) forward an
# eval-mode seed for reproducibility. These regressions guard the wire payload.


@pytest.mark.asyncio
async def test_stream_chat_includes_tools_when_passed() -> None:
    """Caller passes ``tools=[]`` → payload must carry ``tools: []`` on the wire.

    Regression for the synthesis-turn quality fix: without ``tools=[]`` the
    DeepSeek V4 Flash model (reasoning_effort=medium) sees prior tool turns and
    decides to plan MORE tool calls, emitting `<tool_call>` JSON XML as visible
    text in the answer.
    """
    captured: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(200, content=_sse_with_content("ok"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(api_key="x", model="m", http_client=client)
    async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], tools=[]):
        pass
    assert len(captured) == 1
    assert captured[0].get("tools") == []
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_chat_includes_seed_when_passed() -> None:
    """Caller passes ``seed=42`` → payload must carry ``seed: 42`` on the wire."""
    captured: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(200, content=_sse_with_content("ok"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(api_key="x", model="m", http_client=client)
    async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}], seed=42):
        pass
    assert len(captured) == 1
    assert captured[0].get("seed") == 42
    await client.aclose()


@pytest.mark.asyncio
async def test_stream_chat_omits_tools_and_seed_when_not_passed() -> None:
    """Backward-compat: legacy callers (no tools/seed kwargs) must not get them in the payload.

    Sending ``tools: null`` or ``seed: null`` to DeepInfra could trigger schema
    validation failures; provider defaults only apply when the keys are absent.
    """
    captured: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.append(_json.loads(request.content))
        return httpx.Response(200, content=_sse_with_content("ok"))

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = DeepInfraCompletionAdapter(api_key="x", model="m", http_client=client)
    async for _ in adapter.stream_chat([{"role": "user", "content": "hi"}]):
        pass
    assert len(captured) == 1
    assert "tools" not in captured[0]
    assert "seed" not in captured[0]
    await client.aclose()
