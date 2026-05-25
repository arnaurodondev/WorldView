"""Symmetric-fallback observability tests for LLMProviderChain (PLAN-0093 QA-7).

Covers:
- F1-a: chat_with_tools failure increments `rag_provider_fallback{from,to}` and
  emits the `provider_failed` structured log entry.
- F1-b: same behaviour for stream_chat.
- F1 regression guard: stream() still emits the fallback metric (refactor must
  not have broken the existing path).
- F2: chat_with_tools failure also increments
  `rag_chat_with_tools_failed_total{provider}` by exactly 1 per provider failure.

All tests pull metric samples via the prometheus_client default registry so the
assertions read the same counter the dashboards consume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from prometheus_client import REGISTRY
from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain
from tools.types import LLMToolResponse  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _structlog_to_stdlib() -> Iterator[None]:
    """Route structlog through stdlib so pytest's `caplog` can capture events.

    WHY autouse: provider_chain emits the `provider_failed` warning via structlog;
    without this redirect, structlog writes to its own renderer and the records
    never reach `caplog`. Same pattern as test_tool_executor.py.

    WHY restore: ``structlog.configure`` mutates a process-global. If we do not
    restore the prior configuration on teardown, every subsequent test in the
    pytest session inherits the stdlib-routed config and any test that relies on
    structlog's default stdout renderer (e.g. ``capsys``-based assertions in
    test_chat_orchestrator_tool_loop.py) will see empty output. Snapshot before,
    reset + reconfigure after.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valkey() -> AsyncMock:
    """Build a valkey mock that mimics the negative-cache contract.

    WHY: provider_chain.stream/chat_with_tools/stream_chat all hit `exists` and
    `setex` against the same Valkey client. Returning False from `exists` keeps
    all providers eligible so we can drive failure paths explicitly.
    """
    valkey = AsyncMock()
    valkey.exists = AsyncMock(return_value=False)
    valkey.setex = AsyncMock()
    return valkey


def _make_failing_provider(name: str) -> MagicMock:
    """A provider whose chat_with_tools, stream and stream_chat all raise.

    The exception is a plain RuntimeError so the chain treats it as a transient
    provider failure (NotImplementedError would be a "skip silently" path).
    """
    provider = MagicMock()
    provider.name = name
    provider.model_id = name
    provider.chat_with_tools = AsyncMock(side_effect=RuntimeError(f"{name} HTTP 500"))

    async def _stream(prompt: str, **kw: object) -> AsyncIterator[str]:
        # WHY raise BEFORE yielding: stream() catches exceptions thrown from the
        # generator body; this models a provider that fails the initial POST.
        raise RuntimeError(f"{name} stream HTTP 500")
        yield  # pragma: no cover — needed to make this an async generator

    async def _stream_chat(messages: list, **kw: object) -> AsyncIterator[str]:
        raise RuntimeError(f"{name} stream_chat HTTP 500")
        yield  # pragma: no cover

    provider.stream = _stream
    provider.stream_chat = _stream_chat
    return provider


def _make_ok_provider(name: str, *, response_text: str = "ok") -> MagicMock:
    """A provider that returns a successful LLMToolResponse / single text chunk."""
    provider = MagicMock()
    provider.name = name
    provider.model_id = name
    provider.chat_with_tools = AsyncMock(
        return_value=LLMToolResponse(
            text=response_text,
            tool_calls=[],
            finish_reason="stop",
            usage=None,
        )
    )

    async def _stream(prompt: str, **kw: object) -> AsyncIterator[str]:
        yield response_text

    async def _stream_chat(messages: list, **kw: object) -> AsyncIterator[str]:
        yield response_text

    provider.stream = _stream
    provider.stream_chat = _stream_chat
    return provider


def _counter_sample(metric_name: str, labels: dict[str, str]) -> float:
    """Read a single labelled counter sample from the default Prometheus registry.

    WHY this helper exists: prometheus_client appends a `_total` suffix on
    Counter sample names, so `rag_chat_with_tools_failed_total` is registered
    under the same name. We tolerate both forms to be defensive.
    """
    for fam in REGISTRY.collect():
        if fam.name not in {metric_name, metric_name.removesuffix("_total")}:
            continue
        for sample in fam.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return float(sample.value)
    return 0.0


# ---------------------------------------------------------------------------
# F1-a — chat_with_tools fallback metric + log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_with_tools_records_fallback_metric_on_failure(caplog) -> None:
    """Primary chat_with_tools raises -> rag_provider_fallback{from,to} increments.

    Also asserts the structured `provider_failed` log entry is emitted so the
    fallback dashboards and the log-based runbooks stay in sync.
    """
    deepinfra = _make_failing_provider("deepinfra")
    openrouter = _make_ok_provider("openrouter", response_text="fallback")
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)

    before = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )

    with caplog.at_level("WARNING"):
        resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}])

    after = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )
    assert after - before == pytest.approx(1.0)
    # The chain must have fallen through to the secondary.
    assert resp.text == "fallback"
    # structlog routes through stdlib logging; the event name lands as the message.
    assert any("provider_failed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# F1-b — stream_chat fallback metric + log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_records_fallback_metric_on_failure(caplog) -> None:
    """Primary stream_chat raises -> rag_provider_fallback{from,to} increments."""
    deepinfra = _make_failing_provider("deepinfra")
    openrouter = _make_ok_provider("openrouter", response_text="ok")
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)

    before = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )

    with caplog.at_level("WARNING"):
        chunks = [c async for c in chain.stream_chat([{"role": "user", "content": "hi"}])]

    after = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )
    assert after - before == pytest.approx(1.0)
    assert chunks == ["ok"]
    assert any("provider_failed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# F2 — chat_with_tools failure increments rag_chat_with_tools_failed_total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_with_tools_failure_increments_failed_counter() -> None:
    """rag_chat_with_tools_failed_total{provider="deepinfra"} += 1 per failure."""
    deepinfra = _make_failing_provider("deepinfra")
    openrouter = _make_ok_provider("openrouter")
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)

    before = _counter_sample(
        "rag_chat_with_tools_failed_total",
        {"provider": "deepinfra"},
    )

    await chain.chat_with_tools([{"role": "user", "content": "hi"}])

    after = _counter_sample(
        "rag_chat_with_tools_failed_total",
        {"provider": "deepinfra"},
    )
    assert after - before == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# F1 regression guard — stream() still emits the fallback metric
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_fallback_metric_preserved_after_helper_refactor() -> None:
    """Refactor must not have regressed the existing stream() fallback metric."""
    deepinfra = _make_failing_provider("deepinfra")
    openrouter = _make_ok_provider("openrouter", response_text="stream-ok")
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[deepinfra, openrouter], valkey=valkey)

    before = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )

    chunks = [c async for c in chain.stream("hello")]

    after = _counter_sample(
        "rag_provider_fallback_total",
        {"from_provider": "deepinfra", "to_provider": "openrouter"},
    )
    assert after - before == pytest.approx(1.0)
    assert chunks == ["stream-ok"]


# ---------------------------------------------------------------------------
# F3 — NotImplementedError is a skip signal, not a failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_not_implemented_error_does_not_increment_failed_counter() -> None:
    """NotImplementedError raised by a provider (e.g. Ollama skipping function calling)
    must NOT increment rag_chat_with_tools_failed_total — it is a silent-skip signal,
    not an error.  Only genuine RuntimeError / HTTP failures should count as failures.

    WHY: OllamaCompletionAdapter raises NotImplementedError for chat_with_tools
    because it does not support function calling.  The chain catches this and
    continues silently so the next provider (DeepInfra / OpenRouter) is tried.
    If we were to count NotImplementedError as a failure, every request would
    increment the counter by 1 even when everything works correctly.
    """
    # Provider 1 raises NotImplementedError (Ollama-style skip).
    ollama_skip = MagicMock()
    ollama_skip.name = "ollama_noop"
    ollama_skip.model_id = "ollama_noop"
    ollama_skip.chat_with_tools = AsyncMock(side_effect=NotImplementedError("function calling not supported"))

    # Provider 2 succeeds.
    deepinfra = _make_ok_provider("deepinfra_ok")
    valkey = _make_valkey()
    chain = LLMProviderChain(providers=[ollama_skip, deepinfra], valkey=valkey)

    before = _counter_sample(
        "rag_chat_with_tools_failed_total",
        {"provider": "ollama_noop"},
    )

    resp = await chain.chat_with_tools([{"role": "user", "content": "hi"}])

    after = _counter_sample(
        "rag_chat_with_tools_failed_total",
        {"provider": "ollama_noop"},
    )

    # Counter must not have moved — NotImplementedError is a skip, not a failure.
    assert after == before, (
        f"rag_chat_with_tools_failed_total must NOT increment for NotImplementedError "
        f"(skip signal), but went from {before} to {after}"
    )
    # The chain must have fallen through to the second provider.
    assert resp.text == "ok"
