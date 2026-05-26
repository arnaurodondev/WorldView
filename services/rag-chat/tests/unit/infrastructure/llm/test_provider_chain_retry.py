"""FIX-LIVE-EE — provider-chain exponential backoff on iter-0 transient errors.

Tests cover the new `retry=` flag added to ``LLMProviderChain.chat_with_tools``:

- Retriable exceptions (TimeoutError, httpx.ConnectError, httpx.ReadError,
  HTTPStatusError with 429/503) are retried up to ``retry_attempts`` times
  with exponential backoff.
- Non-retriable exceptions (ValueError, KeyError, 4xx) bypass retry entirely
  and fall straight through to the next provider in the chain.
- retry=False (the default — used for iteration > 0 in the orchestrator) is
  the pre-FIX-LIVE-EE fail-fast behaviour: no in-place retry, propagate to
  the outer chain loop immediately.
- The Prometheus counter ``llm_provider_retry_attempt_total{provider, attempt,
  outcome}`` is incremented appropriately.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from prometheus_client import REGISTRY
from rag_chat.infrastructure.llm.provider_chain import (
    LLMProviderChain,
    _is_retriable_exception,
)
from tools.types import LLMToolResponse  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey() -> AsyncMock:
    """Stub Valkey client — never-cached, swallow setex/setnx."""
    valkey = AsyncMock()
    valkey.exists = AsyncMock(return_value=False)
    valkey.setex = AsyncMock()
    return valkey


def _ok_response(text: str = "ok") -> LLMToolResponse:
    return LLMToolResponse(text=text, tool_calls=[], finish_reason="stop")


def _make_provider(name: str, *, side_effects: list[object] | None = None) -> MagicMock:
    """Provider that returns the next side_effect on each call.

    side_effects = [Exception, Exception, response]  -> fails twice then succeeds.
    side_effects = [response]                        -> succeeds immediately.
    """
    provider = MagicMock()
    provider.name = name
    provider.model_id = name
    provider.chat_with_tools = AsyncMock(side_effect=side_effects)

    async def _stream_chat(messages: list, **kw: object) -> AsyncIterator[str]:
        yield "chunk"

    provider.stream_chat = _stream_chat
    return provider


def _counter_value(metric: str, labels: dict[str, str]) -> float:
    """Read a single labelled counter sample from the default Prometheus registry."""
    for fam in REGISTRY.collect():
        if fam.name not in {metric, metric.removesuffix("_total")}:
            continue
        for sample in fam.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return float(sample.value)
    return 0.0


# Patch asyncio.sleep so the 1s/2s backoff doesn't slow the test suite. The
# autouse fixture below applies it to every test in this module.
@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr("rag_chat.infrastructure.llm.provider_chain.asyncio.sleep", _instant)


# ---------------------------------------------------------------------------
# Exception classification
# ---------------------------------------------------------------------------


def test_is_retriable_timeout() -> None:
    # asyncio.TimeoutError is aliased to builtin TimeoutError on Py 3.11+ —
    # one assertion is sufficient; ruff (UP041) collapses the duplicate form.
    assert _is_retriable_exception(TimeoutError())


def test_is_retriable_httpx_transport_errors() -> None:
    assert _is_retriable_exception(httpx.ConnectError("connection refused"))
    assert _is_retriable_exception(httpx.ReadError("socket reset"))
    assert _is_retriable_exception(httpx.RemoteProtocolError("server disconnected"))


def test_is_retriable_http_status_429_503() -> None:
    req = httpx.Request("POST", "http://example/api")
    for code in (429, 502, 503, 504):
        resp = httpx.Response(code, request=req)
        exc = httpx.HTTPStatusError("err", request=req, response=resp)
        assert _is_retriable_exception(exc), f"status {code} must be retriable"


def test_not_retriable_4xx_status() -> None:
    req = httpx.Request("POST", "http://example/api")
    for code in (400, 401, 403, 404, 500):
        resp = httpx.Response(code, request=req)
        exc = httpx.HTTPStatusError("err", request=req, response=resp)
        assert not _is_retriable_exception(exc), f"status {code} must NOT be retriable"


def test_not_retriable_value_error_etc() -> None:
    assert not _is_retriable_exception(ValueError("bad arg"))
    assert not _is_retriable_exception(KeyError("missing"))
    assert not _is_retriable_exception(RuntimeError("plain"))
    assert not _is_retriable_exception(NotImplementedError())


# ---------------------------------------------------------------------------
# Retry behaviour — chat_with_tools(retry=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_two_timeouts_then_success() -> None:
    """DeepInfra raises TimeoutError twice -> 3rd call succeeds. 2 retries used."""
    deepinfra = _make_provider(
        "deepinfra",
        side_effects=[TimeoutError("budget exceeded"), TimeoutError("budget exceeded"), _ok_response("recovered")],
    )
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra],
        valkey=valkey,
        retry_attempts=2,
        retry_backoff_base=1.0,
    )

    before_success = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "1", "outcome": "success"},
    )
    before_success_2 = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "2", "outcome": "success"},
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=True)

    assert resp.text == "recovered"
    # Provider was called 3 times total (1 initial + 2 retries).
    assert deepinfra.chat_with_tools.await_count == 3

    after_success = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "1", "outcome": "success"},
    )
    after_success_2 = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "2", "outcome": "success"},
    )
    # Each retry scheduled increments the {attempt=N, outcome=success} counter.
    assert after_success - before_success == pytest.approx(1.0)
    assert after_success_2 - before_success_2 == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_non_retriable_skips_retry_and_falls_back() -> None:
    """ValueError on DeepInfra -> 0 retries -> immediate fallback to OpenRouter."""
    deepinfra = _make_provider(
        "deepinfra",
        side_effects=[ValueError("malformed prompt")],
    )
    openrouter = _make_provider("openrouter", side_effects=[_ok_response("fallback")])
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra, openrouter],
        valkey=valkey,
        retry_attempts=2,
        retry_backoff_base=1.0,
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=True)

    assert resp.text == "fallback"
    # DeepInfra called exactly once — no retries.
    assert deepinfra.chat_with_tools.await_count == 1
    openrouter.chat_with_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_disabled_when_iter_gt_zero() -> None:
    """retry=False (orchestrator iter > 0) -> 0 retries even for TimeoutError."""
    deepinfra = _make_provider(
        "deepinfra",
        side_effects=[TimeoutError("ignored")],
    )
    openrouter = _make_provider("openrouter", side_effects=[_ok_response("fallback")])
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra, openrouter],
        valkey=valkey,
        retry_attempts=2,
        retry_backoff_base=1.0,
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=False)

    assert resp.text == "fallback"
    # No retry on iter > 0 — DeepInfra called exactly once, then fallback.
    assert deepinfra.chat_with_tools.await_count == 1


@pytest.mark.asyncio
async def test_retry_exhausted_then_fallback_to_next_provider() -> None:
    """All 3 attempts on DeepInfra fail -> fallback to OpenRouter which succeeds."""
    deepinfra = _make_provider(
        "deepinfra",
        side_effects=[
            TimeoutError("t1"),
            TimeoutError("t2"),
            TimeoutError("t3"),
        ],
    )
    openrouter = _make_provider("openrouter", side_effects=[_ok_response("from openrouter")])
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra, openrouter],
        valkey=valkey,
        retry_attempts=2,
        retry_backoff_base=1.0,
    )

    before_failure = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "2", "outcome": "failure"},
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=True)

    assert resp.text == "from openrouter"
    # DeepInfra exhausted (1 initial + 2 retries = 3 attempts), OpenRouter succeeded once.
    assert deepinfra.chat_with_tools.await_count == 3
    openrouter.chat_with_tools.assert_awaited_once()

    after_failure = _counter_value(
        "llm_provider_retry_attempt_total",
        {"provider": "deepinfra", "attempt": "2", "outcome": "failure"},
    )
    # The exhaustion event increments the {attempt=N=retry_attempts, outcome=failure} counter.
    assert after_failure - before_failure == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_all_providers_fail_chain_raises_runtime_error() -> None:
    """Both retriable providers exhaust, Ollama skipped -> RuntimeError."""
    deepinfra = _make_provider(
        "deepinfra",
        side_effects=[TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")],
    )
    openrouter = _make_provider(
        "openrouter",
        side_effects=[TimeoutError("t1"), TimeoutError("t2"), TimeoutError("t3")],
    )
    ollama = _make_provider("ollama", side_effects=[NotImplementedError()])
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra, openrouter, ollama],
        valkey=valkey,
        retry_attempts=2,
        retry_backoff_base=1.0,
    )

    with pytest.raises(RuntimeError, match="chat_with_tools"):
        await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=True)

    # Each retriable provider exhausted = 3 attempts each.
    assert deepinfra.chat_with_tools.await_count == 3
    assert openrouter.chat_with_tools.await_count == 3
    # Ollama's NotImplementedError is non-retriable -> single call.
    assert ollama.chat_with_tools.await_count == 1


@pytest.mark.asyncio
async def test_retry_attempts_zero_disables_retry() -> None:
    """retry_attempts=0 reproduces the legacy (pre-FIX-LIVE-EE) fail-fast path."""
    deepinfra = _make_provider("deepinfra", side_effects=[TimeoutError("once")])
    openrouter = _make_provider("openrouter", side_effects=[_ok_response("fb")])
    valkey = _make_valkey()
    chain = LLMProviderChain(
        providers=[deepinfra, openrouter],
        valkey=valkey,
        retry_attempts=0,
        retry_backoff_base=1.0,
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}], retry=True)

    assert resp.text == "fb"
    # retry_attempts=0 -> no retries even when retry=True.
    assert deepinfra.chat_with_tools.await_count == 1
