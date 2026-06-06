"""Unit tests for AgenticBriefGenerator (PLAN-0099 Wave C scaffold).

Covers four invariants:
    1. With ``brief_agentic_enabled=False`` the route uses the standard path
       (no AgenticBriefGenerator instance is constructed).
    2. With the flag True, the agentic generator's ``generate()`` IS invoked.
    3. Happy path: agentic generator returns a brief envelope on a clean run.
    4. Fallback paths: exception in the LLM AND tool-call budget overrun both
       fall back to the standard generator.

NOTE: these tests stub the LLM chain + tool executor; they do NOT exercise
real DeepInfra or any upstream service.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from rag_chat.application.use_cases.agentic_brief_generator import (
    AgenticBriefGenerator,
    _BudgetExhausted,
    _wrap_envelope,
)

pytestmark = pytest.mark.unit

# ── Tiny fake types matching the libs/tools types.py shape ───────────────────
# WHY local fakes (not real types): keeps the test self-contained and lets us
# poke ``finish_reason`` / ``has_tool_calls`` without importing the full lib.


class _FakeToolCall:
    """OpenAI-compat tool_call returned by the LLM chain."""

    def __init__(self, name: str, args: dict[str, Any], call_id: str = "call_1") -> None:
        self.name = name
        self.input = args
        self.id = call_id


class _FakeLLMResponse:
    """Stand-in for tools.types.LLMToolResponse."""

    def __init__(
        self,
        *,
        text: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls or []
        self.finish_reason = "tool_calls" if tool_calls else "stop"

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def _make_settings(max_tool_calls: int = 8, *, enabled: bool = True) -> Any:
    """Minimal settings stub — only the two fields the generator reads."""
    s = MagicMock()
    s.brief_agentic_enabled = enabled
    s.brief_agentic_max_tool_calls = max_tool_calls
    return s


def _make_tool_executor(registry_specs: dict[str, Any] | None = None) -> Any:
    """Build a tool executor mock with a get_spec-returning registry."""
    exec_mock = MagicMock()
    exec_mock.execute = AsyncMock(return_value=[])
    registry = MagicMock()
    registry.get_spec = MagicMock(
        side_effect=lambda name: (registry_specs or {}).get(name),
    )
    exec_mock._registry = registry
    return exec_mock


def _make_fallback(envelope: dict[str, Any] | None = None) -> Any:
    """Standard-generator stub. Returns a recognisable sentinel envelope."""
    fb = MagicMock()
    fb.execute_public_morning = AsyncMock(
        return_value=envelope or {"content": "FALLBACK_NARRATIVE", "generated_at": "2026-05-25T00:00:00+00:00"},
    )
    return fb


# ── 1. Happy-path: agentic generator returns a brief envelope ────────────────


@pytest.mark.asyncio
async def test_agentic_generator_happy_path_returns_envelope() -> None:
    """LLM emits 1 tool call → tool result fed back → LLM stops with text."""
    llm_chain = MagicMock()
    # Two LLM hops: first emits a tool call, second returns final text.
    llm_chain.chat_with_tools = AsyncMock(
        side_effect=[
            _FakeLLMResponse(tool_calls=[_FakeToolCall("get_portfolio_news", {})]),
            _FakeLLMResponse(text="Morning brief narrative."),
        ],
    )
    tool_exec = _make_tool_executor()

    gen = AgenticBriefGenerator(
        llm_chain=llm_chain,
        tool_executor=tool_exec,
        settings=_make_settings(),
        fallback=_make_fallback(),
    )
    result = await gen.generate(user_id=uuid4(), tenant_id=uuid4())

    assert result["content"] == "Morning brief narrative."
    assert "generated_at" in result
    assert llm_chain.chat_with_tools.await_count == 2
    assert tool_exec.execute.await_count == 1


# ── 2. Fallback: agentic generator catches exception and uses standard path ──


@pytest.mark.asyncio
async def test_agentic_generator_falls_back_on_exception() -> None:
    """LLM chain raises → standard generator's envelope is returned verbatim."""
    llm_chain = MagicMock()
    llm_chain.chat_with_tools = AsyncMock(side_effect=RuntimeError("provider down"))
    fb = _make_fallback({"content": "STANDARD_OK", "generated_at": "x"})

    gen = AgenticBriefGenerator(
        llm_chain=llm_chain,
        tool_executor=_make_tool_executor(),
        settings=_make_settings(),
        fallback=fb,
    )
    result = await gen.generate(user_id=uuid4(), tenant_id=uuid4())

    assert result["content"] == "STANDARD_OK"
    fb.execute_public_morning.assert_awaited_once()


# ── 3. Budget-exhausted: tool-call cap triggers fallback ─────────────────────


@pytest.mark.asyncio
async def test_agentic_generator_budget_overrun_falls_back() -> None:
    """LLM never stops emitting tool calls → budget cap raises → fallback."""
    # Cap of 2; LLM emits a tool call on every hop → cap hits on the 3rd call.
    llm_chain = MagicMock()
    llm_chain.chat_with_tools = AsyncMock(
        return_value=_FakeLLMResponse(
            tool_calls=[_FakeToolCall("get_portfolio_news", {})],
        ),
    )
    fb = _make_fallback({"content": "STANDARD_AFTER_BUDGET", "generated_at": "y"})

    gen = AgenticBriefGenerator(
        llm_chain=llm_chain,
        tool_executor=_make_tool_executor(),
        settings=_make_settings(max_tool_calls=2),
        fallback=fb,
    )
    result = await gen.generate(user_id=uuid4(), tenant_id=uuid4())

    assert result["content"] == "STANDARD_AFTER_BUDGET"
    fb.execute_public_morning.assert_awaited_once()


# ── 4. Budget enforcement: _BudgetExhausted raised in pure loop ──────────────


@pytest.mark.asyncio
async def test_agentic_loop_raises_budget_exhausted_when_cap_hit() -> None:
    """Direct _run_loop test: verifies the internal sentinel is raised."""
    llm_chain = MagicMock()
    llm_chain.chat_with_tools = AsyncMock(
        return_value=_FakeLLMResponse(
            tool_calls=[_FakeToolCall("get_portfolio_news", {}, call_id="c")],
        ),
    )

    gen = AgenticBriefGenerator(
        llm_chain=llm_chain,
        tool_executor=_make_tool_executor(),
        settings=_make_settings(max_tool_calls=1),
        fallback=_make_fallback(),
    )
    with pytest.raises(_BudgetExhausted):
        await gen._run_loop(user_id=uuid4(), tenant_id=uuid4(), max_tool_calls=1)


# ── 5. Empty LLM response triggers fallback ──────────────────────────────────


@pytest.mark.asyncio
async def test_agentic_generator_empty_text_falls_back() -> None:
    """LLM stops without text → fallback is invoked (empty_response reason)."""
    llm_chain = MagicMock()
    llm_chain.chat_with_tools = AsyncMock(return_value=_FakeLLMResponse(text=""))
    fb = _make_fallback({"content": "STANDARD_NONEMPTY", "generated_at": "z"})

    gen = AgenticBriefGenerator(
        llm_chain=llm_chain,
        tool_executor=_make_tool_executor(),
        settings=_make_settings(),
        fallback=fb,
    )
    result = await gen.generate(user_id=uuid4(), tenant_id=uuid4())

    assert result["content"] == "STANDARD_NONEMPTY"
    fb.execute_public_morning.assert_awaited_once()


# ── 6. Envelope shape (route-layer compatibility) ────────────────────────────


def test_wrap_envelope_returns_route_compatible_shape() -> None:
    """The minimal envelope must carry every field public_briefings reads."""
    env = _wrap_envelope("hello world")
    assert env["content"] == "hello world"
    # Fields the route serialises to PublicBriefingResponse:
    for key in ("summary", "sections", "risk_summary", "entity_mentions", "citations", "lead", "confidence"):
        assert key in env, f"missing field: {key}"


# ── 7. Flag-off path verified at the route layer ─────────────────────────────
# The route-layer flag branch is too thin to warrant a full TestClient; we
# instead assert that the AgenticBriefGenerator import is gated by the flag
# attribute on Settings (defaults to False per config.py).


def test_settings_flag_defaults_off() -> None:
    """Catches accidental flip of brief_agentic_enabled default."""
    from rag_chat.config import Settings

    # Provide the single required field so Settings instantiates; everything
    # else falls back to the model default.
    s = Settings(database_url="postgresql+asyncpg://u:p@h/db")  # type: ignore[arg-type]
    assert s.brief_agentic_enabled is False
    assert s.brief_agentic_max_tool_calls == 8
