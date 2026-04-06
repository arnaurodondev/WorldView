"""LlmStreamProvider port — streaming LLM interface for the application layer.

Implemented by the DeepInfra/OpenRouter/Ollama provider chain (Wave F-1).
Referenced by HydeExpander and the completion orchestrator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
