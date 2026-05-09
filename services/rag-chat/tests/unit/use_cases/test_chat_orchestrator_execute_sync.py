"""Unit tests for ``ChatOrchestratorUseCase.execute_sync`` error mapping.

PLAN-0087 Wave F D-R1-005: ``execute_sync`` previously consumed only ``token``,
``citations``, ``contradictions``, and ``metadata`` events from the streaming
generator — it ignored ``error`` events.  When the LLM first turn failed (e.g.
DeepInfra returned a malformed response and ``provider_chat_with_tools_failed``
fired), the user got a 200 OK with an empty ``answer`` field instead of a 5xx.

The fix routes ``error`` events to typed exceptions so the route handler in
``api/routes/chat.py`` translates them to HTTP 4xx/5xx — never silently 200.

Mapping under test:
  ``RATE_LIMIT_EXCEEDED``     → ``RateLimitExceededError``     (429)
  ``INPUT_REJECTED``          → ``PromptInjectionError``       (400)
  ``llm_first_turn_failed``   → ``ProviderUnavailableError``   (503)
  ``llm_second_turn_failed``  → ``ProviderUnavailableError``   (503)
  ``all_tools_failed``        → ``ProviderUnavailableError``   (503)
  ``PROVIDER_UNAVAILABLE``    → ``ProviderUnavailableError``   (503)
  any other code              → ``ProviderUnavailableError``   (503, default)
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _build_orchestrator_with_streaming(events: list[dict[str, str]]) -> Any:
    """Build a ChatOrchestratorUseCase whose ``execute_streaming`` yields ``events``.

    We bypass the real streaming pipeline entirely — the test only exercises
    ``execute_sync``'s consumption + error-mapping logic.

    The pipeline mock is just enough for ``execute_sync``'s "safety net"
    ``self._pipeline.process_output(answer, [])[0]`` call (only reached when
    no error event was emitted).
    """
    from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

    pipeline = MagicMock()
    # Identity process_output: returns (input_text, [])
    pipeline.process_output = MagicMock(side_effect=lambda txt, _items: (txt, []))

    orch = ChatOrchestratorUseCase(pipeline=pipeline)

    async def _fake_stream(_request: Any, _uow: Any) -> AsyncGenerator[dict[str, str], None]:
        for ev in events:
            yield ev

    # Replace execute_streaming with our fake.  This is a focused unit test on
    # execute_sync's event-consumption + exception-mapping logic — the streaming
    # pipeline itself has its own dedicated test suite (test_chat_orchestrator_tool_loop.py).
    orch.execute_streaming = _fake_stream  # type: ignore[assignment]
    return orch


def _err(code: str, message: str = "boom") -> dict[str, str]:
    return {"event": "error", "data": json.dumps({"code": code, "message": message})}


def _token(text: str) -> dict[str, str]:
    return {"event": "token", "data": json.dumps({"text": text})}


def _metadata(**fields: Any) -> dict[str, str]:
    return {"event": "metadata", "data": json.dumps(fields)}


# ── Happy path: no error events → returns dict ─────────────────────────────────


@pytest.mark.asyncio
async def test_execute_sync_returns_dict_when_no_error() -> None:
    """No ``error`` event → existing dict-return behaviour preserved."""
    events = [
        _token("Hello "),
        _token("world."),
        {"event": "citations", "data": json.dumps([])},
        {"event": "contradictions", "data": json.dumps([])},
        _metadata(thread_id="abc", message_id="def", intent="GENERAL", provider="deepinfra", latency_ms=200),
    ]
    orch = _build_orchestrator_with_streaming(events)
    result = await orch.execute_sync(MagicMock(), MagicMock())

    assert result["answer"] == "Hello world."
    assert result["citations"] == []
    assert result["contradictions"] == []
    assert result["thread_id"] == "abc"
    assert result["latency_ms"] == 200


# ── D-R1-005: error events → typed exceptions ─────────────────────────────────


@pytest.mark.asyncio
async def test_llm_first_turn_failed_raises_provider_unavailable() -> None:
    """The exact failure mode from the audit (R1, prompt #5) — model emits
    ``provider_chat_with_tools_failed`` and the orchestrator returns
    ``llm_first_turn_failed``.  Must surface as 503, not silent 200."""
    from rag_chat.domain.errors import ProviderUnavailableError

    events = [_err("llm_first_turn_failed", "Unable to process request")]
    orch = _build_orchestrator_with_streaming(events)

    with pytest.raises(ProviderUnavailableError, match="Unable to process request"):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_llm_second_turn_failed_raises_provider_unavailable() -> None:
    from rag_chat.domain.errors import ProviderUnavailableError

    events = [
        _token("partial..."),
        _err("llm_second_turn_failed", "Unable to generate answer"),
    ]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(ProviderUnavailableError):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_all_tools_failed_raises_provider_unavailable() -> None:
    """All-tools-failed guard fires when every tool returns None.  Currently the
    orchestrator emits ``error`` with code ``all_tools_failed``; the user must
    see 503, not a 200 with an empty answer."""
    from rag_chat.domain.errors import ProviderUnavailableError

    events = [_err("all_tools_failed", "Unable to retrieve relevant data")]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(ProviderUnavailableError):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_rate_limit_error_event_raises_rate_limit_error() -> None:
    """Rate limits are 429 — keep them out of the 5xx bucket."""
    from rag_chat.domain.errors import RateLimitExceededError

    events = [_err("RATE_LIMIT_EXCEEDED", "Too many requests")]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(RateLimitExceededError):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_input_rejected_error_event_raises_prompt_injection_error() -> None:
    """Input validation failures map to 400, not 503."""
    from rag_chat.domain.errors import PromptInjectionError

    events = [_err("INPUT_REJECTED", "Potential prompt injection detected")]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(PromptInjectionError):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_unknown_error_code_defaults_to_provider_unavailable() -> None:
    """Defensive: unknown codes default to 503 rather than silent 200."""
    from rag_chat.domain.errors import ProviderUnavailableError

    events = [_err("SOMETHING_WEIRD", "huh?")]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(ProviderUnavailableError):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_first_error_wins_when_multiple_emitted() -> None:
    """If the streaming generator emits multiple errors, only the FIRST is mapped.

    Defensive: ``execute_streaming`` returns immediately after an error in
    practice but we don't rely on that — capturing the first error is the
    safest contract.
    """
    from rag_chat.domain.errors import RateLimitExceededError

    events = [
        _err("RATE_LIMIT_EXCEEDED", "Too many"),
        _err("llm_first_turn_failed", "later"),
    ]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(RateLimitExceededError, match="Too many"):
        await orch.execute_sync(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_token_events_before_error_do_not_short_circuit_raise() -> None:
    """Even if some tokens were emitted before the error, execute_sync must raise.

    Otherwise the user would see a 200 OK with a partial / truncated answer when
    the second LLM turn aborted mid-stream — same silent-failure shape as
    D-R1-005's original report.
    """
    from rag_chat.domain.errors import ProviderUnavailableError

    events = [
        _token("Apple is "),
        _token("a "),
        _err("llm_second_turn_failed", "stream aborted"),
    ]
    orch = _build_orchestrator_with_streaming(events)
    with pytest.raises(ProviderUnavailableError):
        await orch.execute_sync(MagicMock(), MagicMock())
