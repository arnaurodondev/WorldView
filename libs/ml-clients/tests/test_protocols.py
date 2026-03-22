"""Protocol compliance tests for ml-clients."""

from __future__ import annotations

import dataclasses

import pytest
from ml_clients.dataclasses import (
    EmbeddingInput,
    EmbeddingOutput,
    ExtractionInput,
    ExtractionOutput,
    NERInput,
    NEROutput,
)
from ml_clients.protocols import EmbeddingClient, ExtractionClient, NERClient

# ── Mock implementations ──────────────────────────────────────────────────────


class MockEmbeddingClient:
    async def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:
        return []


class MockNERClient:
    async def extract_entities(self, inp: NERInput) -> NEROutput:
        return NEROutput(mentions=[])


class MockExtractionClient:
    async def extract(self, inp: ExtractionInput) -> ExtractionOutput:
        return ExtractionOutput(result={}, raw_response="", model_id="test")


# ── Protocol compliance ───────────────────────────────────────────────────────


def test_embedding_protocol_isinstance() -> None:
    assert isinstance(MockEmbeddingClient(), EmbeddingClient)


def test_ner_protocol_isinstance() -> None:
    assert isinstance(MockNERClient(), NERClient)


def test_extraction_protocol_isinstance() -> None:
    assert isinstance(MockExtractionClient(), ExtractionClient)


def test_bad_client_missing_method_fails() -> None:
    """A class missing the protocol method should not satisfy isinstance."""

    class NoEmbedMethod:
        pass

    assert not isinstance(NoEmbedMethod(), EmbeddingClient)


def test_bad_client_sync_method_passes_runtime_check() -> None:
    """runtime_checkable only checks method presence, not async signature.

    This documents a known limitation: a sync 'embed' satisfies isinstance at
    runtime even though the Protocol requires async. Type errors are caught by
    mypy, not runtime isinstance.
    """

    class SyncEmbedClient:
        def embed(self, inputs: list[EmbeddingInput]) -> list[EmbeddingOutput]:  # type: ignore[empty-body]
            ...

    # Runtime passes — structural check only verifies method name exists
    assert isinstance(SyncEmbedClient(), EmbeddingClient)


# ── Frozen dataclass immutability ─────────────────────────────────────────────


def test_embedding_input_is_frozen() -> None:
    inp = EmbeddingInput(text="hello", model_id="bge")
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.text = "world"  # type: ignore[misc]


def test_embedding_output_is_frozen() -> None:
    out = EmbeddingOutput(embedding=[0.1] * 1024, model_id="bge", dimension=1024)
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.dimension = 512  # type: ignore[misc]


def test_ner_input_is_frozen() -> None:
    inp = NERInput(text="Apple Inc.", entity_classes=["ORG"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.text = "Google"  # type: ignore[misc]


def test_extraction_input_is_frozen() -> None:
    inp = ExtractionInput(
        prompt="Extract entities",
        context="Apple reported earnings",
        output_schema={"type": "object"},
        model_id="qwen",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.prompt = "Different prompt"  # type: ignore[misc]


def test_embedding_input_optional_prefix() -> None:
    inp = EmbeddingInput(text="hello", model_id="bge", instruction_prefix="Represent:")
    assert inp.instruction_prefix == "Represent:"


def test_ner_input_default_threshold() -> None:
    inp = NERInput(text="Apple", entity_classes=["ORG"])
    assert inp.threshold == 0.5
