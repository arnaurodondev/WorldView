"""LLM provider ports — streaming and structured chat interfaces for the application layer.

LlmStreamProvider  — original streaming interface (HyDE expander, completion orchestrator).
LlmChatProvider    — structured chat with optional function calling (W11-1 tool-use loop).

Both protocols are implemented by the LLMProviderChain in infrastructure/llm/provider_chain.py.
Keeping them separate prevents changes to the tool-use path from breaking HyDE and other
callers that only depend on the plain streaming interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    # Imported only for type annotations — tools lib is on PYTHONPATH via editable install.
    # Using string annotation "LLMToolResponse" below avoids a runtime import of libs/tools
    # from inside the application port layer, which would couple application → infrastructure.
    from tools.types import LLMToolResponse  # type: ignore[import-untyped]


@runtime_checkable
class LlmStreamProvider(Protocol):
    """Yield token-level text chunks from an LLM given a plain-text prompt."""

    def stream(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class LlmChatProvider(Protocol):
    """Structured chat interface with optional function calling.

    Used by ChatOrchestratorUseCase tool-use loop (PLAN-0067 W11-x).
    Kept separate from LlmStreamProvider so that:
    - HyDE expander and plain-text orchestrator are unaffected
    - OllamaCompletionAdapter (which can't do function calling) only needs
      to raise NotImplementedError on chat_with_tools, not fail isinstance checks
    """

    async def chat_with_tools(
        self,
        messages: list[dict],  # OpenAI-format: [{"role": ..., "content": ...}]
        tools: list[dict] | None = None,  # OpenAI tool definitions; None = no tools
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        """Non-streaming structured call.

        Returns LLMToolResponse with either .text (finish_reason=="stop") or
        .tool_calls (finish_reason=="tool_calls") populated.
        """
        ...

    def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        seed: int | None = None,
    ) -> AsyncIterator[str]:
        """Streaming chat for the final LLM turn after tools have been executed.

        WHY separate from stream(): stream() takes a raw prompt string; stream_chat()
        takes an OpenAI-format messages list, allowing the caller to inject tool
        results into the conversation before asking the model to produce the final answer.
        """
        ...
