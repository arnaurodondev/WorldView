"""Unit tests for the co-mention entailment check (ENHANCEMENT #6).

Invariants under test:
  - Non-risky predicates are NEVER sent to the LLM (no call, kept).
  - Relations without evidence are kept without an LLM call.
  - A confident NOT_ASSERTED verdict on a risky relation drops it.
  - A low-confidence NOT_ASSERTED verdict is IGNORED (kept) — false-positive guard.
  - ASSERTED keeps the relation.
  - FAIL-OPEN: LLM exception or unparseable output keeps the relation.
  - The per-document cap bounds the number of LLM calls.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.application.blocks.relation_entailment import (
    DEFAULT_HIGH_RISK_PREDICATES,
    check_relation_entailment,
)

pytestmark = pytest.mark.unit


def _make_output(asserted: bool, confidence: float, *, raw_only: bool = False) -> Any:
    """Build a stub ExtractionOutput-like object.

    raw_only=True simulates a client that only fills raw_response (JSON string), to
    exercise the raw-response parse fallback.
    """
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    body = {"asserted": asserted, "confidence": confidence, "reason": "test"}
    return ExtractionOutput(
        result={} if raw_only else dict(body),
        raw_response=json.dumps(body),
        model_id="test-model",
    )


def _relation(predicate: str, *, evidence: str = "Acme competes with Beta.") -> dict[str, Any]:
    return {
        "subject_ref": "Acme",
        "predicate": predicate,
        "object_ref": "Beta",
        "confidence": 0.9,
        "evidence_text": evidence,
    }


async def _run(relations: list[dict[str, Any]], client: AsyncMock, **kwargs: Any) -> list[dict[str, Any]]:
    return await check_relation_entailment(
        relations,
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_non_risky_predicate_skips_llm_and_keeps() -> None:
    client = AsyncMock()
    rels = [_relation("listed_on")]  # not in high-risk set
    out = await _run(rels, client)
    assert out == rels
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_relation_without_evidence_kept_without_call() -> None:
    client = AsyncMock()
    rels = [_relation("competes_with", evidence="")]
    out = await _run(rels, client)
    assert out == rels
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_confident_not_asserted_drops_relation() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=False, confidence=0.95)
    rels = [_relation("competes_with")]
    out = await _run(rels, client, min_drop_confidence=0.7)
    assert out == []  # dropped
    client.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_confidence_not_asserted_is_kept() -> None:
    # The critical false-positive guard: an unsure "drop" must NOT kill the relation.
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=False, confidence=0.4)
    rels = [_relation("regulates")]
    out = await _run(rels, client, min_drop_confidence=0.7)
    assert out == rels


@pytest.mark.asyncio
async def test_asserted_keeps_relation() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=True, confidence=0.99)
    rels = [_relation("supplier_of")]
    out = await _run(rels, client)
    assert out == rels


@pytest.mark.asyncio
async def test_llm_exception_fails_open_keeps_relation() -> None:
    client = AsyncMock()
    client.extract.side_effect = RuntimeError("deepinfra 500")
    rels = [_relation("produces")]
    out = await _run(rels, client)
    assert out == rels  # fail-open


@pytest.mark.asyncio
async def test_unparseable_output_fails_open() -> None:
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    client = AsyncMock()
    client.extract.return_value = ExtractionOutput(result={}, raw_response="not json at all", model_id="test-model")
    rels = [_relation("partner_of")]
    out = await _run(rels, client)
    assert out == rels


@pytest.mark.asyncio
async def test_raw_response_fallback_parse_drops() -> None:
    # Client fills only raw_response (no structured result) — fallback parse must work.
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=False, confidence=0.9, raw_only=True)
    rels = [_relation("competes_with")]
    out = await _run(rels, client, min_drop_confidence=0.7)
    assert out == []


@pytest.mark.asyncio
async def test_max_per_doc_caps_calls() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=True, confidence=0.9)
    rels = [_relation("competes_with") for _ in range(5)]
    out = await _run(rels, client, max_per_doc=2)
    # Only 2 checked; all kept (asserted), but exactly 2 LLM calls made.
    assert len(out) == 5
    assert client.extract.await_count == 2


@pytest.mark.asyncio
async def test_mixed_batch_only_risky_checked_and_order_preserved() -> None:
    client = AsyncMock()
    # competes_with -> drop; produces -> keep (asserted)
    client.extract.side_effect = [
        _make_output(asserted=False, confidence=0.95),
        _make_output(asserted=True, confidence=0.95),
    ]
    rels = [
        _relation("listed_on"),  # skipped, kept
        _relation("competes_with"),  # dropped
        _relation("headquartered_in"),  # skipped, kept
        _relation("produces"),  # kept
    ]
    out = await _run(rels, client)
    predicates = [r["predicate"] for r in out]
    assert predicates == ["listed_on", "headquartered_in", "produces"]
    assert client.extract.await_count == 2


def test_default_high_risk_predicates_match_audit() -> None:
    assert DEFAULT_HIGH_RISK_PREDICATES == frozenset(
        {"competes_with", "regulates", "produces", "partner_of", "supplier_of"}
    )
