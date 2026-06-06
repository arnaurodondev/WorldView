"""PLAN-0104 W36 / BP-NEW: regression tests for the second-turn synthesis
fallback path in ``ChatOrchestratorUseCase``.

Pinned failure modes (Round 4 chat-quality benchmark
``run_20260602T012842Z``):

* Q3 ``ru_amzn_revenue_yoy`` — ``stream_chat`` raised post-tool with
  ``full_text == ""``. Old contract: emit ``llm_second_turn_failed``,
  return empty ``answer_text``. New contract (W36): emit a degraded but
  useful fallback answer naming the tool that ran and any snippets from
  the retrieved items so the user never sees an empty bubble.
* Q5 ``ru_googl_pe_vs_history`` — ``stream_chat`` completed normally but
  yielded ZERO chunks (DeepInfra returned an empty SSE stream after a
  long tool batch). Old contract: ``final_answer`` event with empty
  text, no error. New contract: the orchestrator detects the empty
  ``full_text`` post-stream and substitutes the same degraded answer.

Both tests reuse the existing fallback-suite helpers
(``_make_pipeline`` / ``_make_chat_request`` etc.) for consistency with
the FIX-LIVE-V / PLAN-0103 W15 sibling tests so behaviour drift in any
of the shared fixtures surfaces in one place.
"""

from __future__ import annotations

import asyncio
import json

# Reuse the fixture helpers from the fallback test module so we don't
# duplicate the (intricate) pipeline / executor mock setup. They are
# module-level functions, not fixtures, so a plain import is the
# simplest and least-surprising option.
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Both modules live in the same directory but the rag-chat test tree has no
# package ``__init__.py`` (pytest discovers via rootdir), so neither absolute
# (``tests.unit.use_cases``) nor relative (``.test_chat_orchestrator_fallback``)
# imports resolve. Insert the directory and import by bare module name.
sys.path.insert(0, str(Path(__file__).parent))
from test_chat_orchestrator_fallback import (
    _collect_events,
    _make_chat_request,
    _make_factory_with_execute_side_effect,
    _make_llm_tool_response,
    _make_pipeline,
    _make_retrieved_item,
    _make_tool_use_block,
)

pytestmark = pytest.mark.unit


class TestSecondTurnFallback:
    """Contract: when the second-turn LLM call fails to produce text the
    user always sees a non-empty ``final_answer`` event and no
    ``llm_second_turn_failed`` error code on the SSE stream."""

    def test_second_turn_exception_produces_degraded_answer_naming_tool(self) -> None:
        """Q3 ``ru_amzn_revenue_yoy`` regression: stream_chat raises with no
        prior tokens → fallback answer streamed, no hard error."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_fundamentals_history", {"ticker": "AMZN", "periods": 8})
        iter0 = _make_llm_tool_response(tool_calls=[tool_block])
        iter1 = _make_llm_tool_response(text="")  # forces final stream_chat
        pipeline = _make_pipeline(first_llm_response=iter0)
        pipeline.llm_chain.chat_with_tools = AsyncMock(side_effect=[iter0, iter1])
        # The shared helper does not stub emit_final_answer (the default
        # fallback suite doesn't exercise that event). Wire it up locally
        # so we can assert the final_answer carries non-empty text.
        pipeline.emitter.emit_final_answer = MagicMock(
            side_effect=lambda text: {"event": "final_answer", "data": json.dumps({"text": text})}
        )

        async def _raises(messages: list, **kwargs: Any):
            if False:  # pragma: no cover — empty-async-gen-with-raise idiom
                yield ""
            raise RuntimeError("All LLM providers failed stream_chat (last error: timeout)")

        pipeline.llm_chain.stream_chat = _raises

        # Realistic-looking AMZN fundamentals snippet so the helper has
        # text to include in the fallback message.
        recovered = _make_retrieved_item("AMZN FY2025 Q3 revenue 158.9B (+13.2% YoY).")
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[recovered]],
            execute_side_effects=[],
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        # No ``llm_second_turn_failed`` reaches the SSE stream — the fallback
        # path absorbs the upstream error.
        error_codes = [json.loads(e["data"]).get("code") for e in events if e.get("event") == "error"]
        assert "llm_second_turn_failed" not in error_codes, error_codes

        # Final answer is non-empty — the symptom the chat-quality benchmark
        # caught was ``answer_text == ""``; we now guarantee non-empty.
        final = [e for e in events if e.get("event") == "final_answer"]
        assert final, "expected a final_answer event"
        text = json.loads(final[-1]["data"]).get("text", "")
        assert text.strip(), f"final_answer must be non-empty; got {text!r}"

        # Fallback names the tool the user invoked so they can retry / pivot.
        joined_tokens = "".join(json.loads(e["data"]).get("text", "") for e in events if e.get("event") == "token")
        assert "get_fundamentals_history" in joined_tokens, joined_tokens

    def test_second_turn_zero_chunk_stream_produces_degraded_answer(self) -> None:
        """Q5 ``ru_googl_pe_vs_history`` regression: stream_chat completes
        cleanly but yields no chunks → orchestrator must substitute the
        fallback answer instead of emitting empty ``final_answer`` text."""
        from rag_chat.application.use_cases.chat_orchestrator import ChatOrchestratorUseCase

        tool_block = _make_tool_use_block("get_fundamentals_history", {"ticker": "GOOGL", "periods": 12})
        iter0 = _make_llm_tool_response(tool_calls=[tool_block])
        iter1 = _make_llm_tool_response(text="")
        pipeline = _make_pipeline(first_llm_response=iter0)
        pipeline.llm_chain.chat_with_tools = AsyncMock(side_effect=[iter0, iter1])
        # The shared helper does not stub emit_final_answer (the default
        # fallback suite doesn't exercise that event). Wire it up locally
        # so we can assert the final_answer carries non-empty text.
        pipeline.emitter.emit_final_answer = MagicMock(
            side_effect=lambda text: {"event": "final_answer", "data": json.dumps({"text": text})}
        )

        # stream_chat completes WITHOUT raising and yields ZERO chunks — the
        # silent-failure mode that produced empty answer_text on GOOGL.
        async def _empty_stream(messages: list, **kwargs: Any):
            # Mark as async generator without yielding any chunks.
            if False:  # pragma: no cover
                yield ""
            return

        pipeline.llm_chain.stream_chat = _empty_stream

        recovered = _make_retrieved_item("GOOGL trailing P/E 26.4 vs 5y median 24.1.")
        factory = _make_factory_with_execute_side_effect(
            execute_all_return=[[recovered]],
            execute_side_effects=[],
        )

        orch = ChatOrchestratorUseCase(pipeline=pipeline, tool_executor_factory=factory)
        request = _make_chat_request()
        uow = MagicMock()

        events = asyncio.run(_collect_events(orch, request, uow))

        # No hard error code on the SSE stream.
        error_codes = [json.loads(e["data"]).get("code") for e in events if e.get("event") == "error"]
        assert "llm_second_turn_failed" not in error_codes, error_codes

        # Non-empty final_answer (this is the literal bug — empty text).
        final = [e for e in events if e.get("event") == "final_answer"]
        assert final, "expected a final_answer event"
        text = json.loads(final[-1]["data"]).get("text", "")
        assert text.strip(), f"final_answer must be non-empty; got {text!r}"

        # Fallback streams tokens AND names the tool.
        token_texts = [json.loads(e["data"]).get("text", "") for e in events if e.get("event") == "token"]
        joined = "".join(token_texts)
        assert joined.strip(), "fallback must stream tokens, not just emit final_answer"
        assert "get_fundamentals_history" in joined, joined
