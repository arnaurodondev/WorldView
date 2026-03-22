"""ML client protocols — structural typing only, no ABC."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ml_clients.dataclasses import (
        EmbeddingInput,
        EmbeddingOutput,
        ExtractionInput,
        ExtractionOutput,
        NERInput,
        NEROutput,
    )


@runtime_checkable
class EmbeddingClient(Protocol):
    """Embed a batch of texts into dense vectors."""

    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]: ...


@runtime_checkable
class NERClient(Protocol):
    """Extract named entity mentions from text."""

    async def extract_entities(self, inp: NERInput) -> NEROutput: ...


@runtime_checkable
class ExtractionClient(Protocol):
    """Run structured LLM extraction against a schema."""

    async def extract(self, inp: ExtractionInput) -> ExtractionOutput: ...
