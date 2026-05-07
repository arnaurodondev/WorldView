"""Unit tests for IntentClassifierPort Protocol (PLAN-0084 D-3, T-D-3-03).

Demonstrates that:
1. A ``StubIntentClassifier`` that implements the Protocol signature is accepted
   as a valid ``IntentClassifierPort`` at runtime (``isinstance`` check via
   ``runtime_checkable``).
2. Both concrete classifiers (``OllamaIntentClassifier``,
   ``DeepInfraIntentClassifier``) satisfy the Protocol structurally — mypy
   verifies this at type-check time; the test confirms it at runtime.
3. An object that does NOT implement ``classify`` is rejected by
   ``isinstance``.

Why test the Protocol rather than just relying on mypy:
- ``runtime_checkable`` isinstance checks are the safety net for dependency-
  injection containers (FastAPI Depends, test fixtures) that assemble classifiers
  dynamically. If the Protocol shape drifts, these checks fire at startup before
  a request is ever processed.
- The stub also serves as a canonical "minimum viable" example for test authors
  writing new integration tests that need a classifier fixture.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from rag_chat.application.pipeline.intent_classifier import (
    DeepInfraIntentClassifier,
    OllamaIntentClassifier,
)
from rag_chat.application.ports.intent_classifier import IntentClassifierPort
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.domain.enums import QueryIntent

pytestmark = pytest.mark.unit


# ── Stub implementation ───────────────────────────────────────────────────────


class StubIntentClassifier:
    """Minimal Protocol-conforming stub for use in tests.

    Always returns FACTUAL_LOOKUP with no sub_questions and the original
    message as the rephrased query.  No I/O, no external deps.
    """

    async def classify(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        resolved_entities: list[ResolvedEntity],
    ) -> tuple[QueryIntent, list[str], str]:
        # Return the simplest valid classification — callers can monkeypatch
        # this method for richer test scenarios.
        return QueryIntent.FACTUAL_LOOKUP, [], message


# ── isinstance / runtime_checkable tests ─────────────────────────────────────


class TestIntentClassifierPortProtocol:
    """Verify Protocol conformance at runtime via runtime_checkable."""

    def test_stub_satisfies_protocol(self) -> None:
        """StubIntentClassifier must be accepted as IntentClassifierPort."""
        stub = StubIntentClassifier()
        # runtime_checkable only checks that the object has the right methods;
        # it does NOT verify return-type annotations at runtime (that is mypy's job).
        assert isinstance(stub, IntentClassifierPort)

    def test_ollama_classifier_satisfies_protocol(self) -> None:
        """OllamaIntentClassifier must be accepted as IntentClassifierPort.

        The constructor requires an Ollama base URL but we never call classify
        here — we only check structural conformance.
        """
        classifier = OllamaIntentClassifier(ollama_base_url="http://localhost:11434")
        assert isinstance(classifier, IntentClassifierPort)

    def test_deepinfra_classifier_satisfies_protocol(self) -> None:
        """DeepInfraIntentClassifier must be accepted as IntentClassifierPort."""
        classifier = DeepInfraIntentClassifier(api_key="dummy-key")
        assert isinstance(classifier, IntentClassifierPort)

    def test_object_without_classify_rejected(self) -> None:
        """An object without a ``classify`` method must not be accepted."""

        class _NoClassify:
            pass

        assert not isinstance(_NoClassify(), IntentClassifierPort)

    async def test_stub_classify_returns_correct_shape(self) -> None:
        """StubIntentClassifier.classify returns the expected triple."""
        stub = StubIntentClassifier()
        # Create a minimal ResolvedEntity fixture inline — no DB required.
        entity = ResolvedEntity(
            entity_id=UUID("00000000-0000-0000-0000-000000000001"),
            canonical_name="Apple Inc.",
            entity_type="COMPANY",
            confidence=0.9,
            matched_text="Apple",
        )
        intent, sub_questions, rephrased = await stub.classify(
            "What is Apple's revenue?",
            [],
            [entity],
        )
        assert intent == QueryIntent.FACTUAL_LOOKUP
        assert sub_questions == []
        assert rephrased == "What is Apple's revenue?"
