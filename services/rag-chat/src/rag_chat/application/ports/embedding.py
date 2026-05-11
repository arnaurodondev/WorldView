"""EmbeddingPort — single-text embedding interface for the application layer.

Implemented by the S6 HTTP adapter (Wave E-3).
Used by HydeExpander to embed the hypothesis paragraph.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingPort(Protocol):
    """Embed a single text string into a dense float vector."""

    async def embed(self, text: str) -> list[float]: ...
