"""Unit tests for the claim entailment pass (2026-07-16 fabrication cure).

Invariants under test (mirrors the relation-entailment gate — the validated 0%-FP
template — because the false-positive risk is identical: killing a good claim):
  - Non-gated claim_types are NEVER sent to the LLM (no call, kept).
  - Claims without evidence are kept without an LLM call.
  - A confident NOT_ENTAILED verdict on a gated claim drops it.
  - A low-confidence NOT_ENTAILED verdict is IGNORED (kept) — false-positive guard.
  - ENTAILED keeps the claim.
  - FAIL-OPEN: LLM exception or unparseable output keeps the claim (no yield loss on
    an API blip — the operator's hard requirement).
  - The per-document cap bounds the number of LLM calls.
  - Order is preserved and only gated claims are checked in a mixed batch.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.application.blocks.claim_entailment import (
    DEFAULT_HIGH_FAB_CLAIM_TYPES,
    check_claim_entailment,
)

pytestmark = pytest.mark.unit


def _make_output(entailed: bool, confidence: float, *, raw_only: bool = False) -> Any:
    """Build a stub ExtractionOutput-like object.

    raw_only=True simulates a client that only fills raw_response (JSON string), to
    exercise the raw-response parse fallback.
    """
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    body = {"entailed": entailed, "confidence": confidence, "reason": "test"}
    return ExtractionOutput(
        result={} if raw_only else dict(body),
        raw_response=json.dumps(body),
        model_id="test-model",
    )


def _claim(
    claim_type: str, *, evidence: str = "Acme refinanced $2B of debt.", polarity: str = "negative"
) -> dict[str, Any]:
    return {
        "entity_ref": "Acme",
        "claim_type": claim_type,
        "polarity": polarity,
        "confidence": 0.9,
        "evidence_text": evidence,
    }


async def _run(claims: list[dict[str, Any]], client: AsyncMock, **kwargs: Any) -> list[dict[str, Any]]:
    return await check_claim_entailment(
        claims,
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_non_gated_claim_type_skips_llm_and_keeps() -> None:
    client = AsyncMock()
    claims = [_claim("PRODUCT_LAUNCH")]  # not in high-fab set
    out = await _run(claims, client)
    assert out == claims
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_without_evidence_kept_without_call() -> None:
    client = AsyncMock()
    claims = [_claim("DEBT_CHANGE", evidence="")]
    out = await _run(claims, client)
    assert out == claims
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_confident_not_entailed_drops_claim() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=False, confidence=0.95)
    claims = [_claim("DEBT_CHANGE")]  # refinancing mislabelled as a debt change
    out = await _run(claims, client, min_drop_confidence=0.7)
    assert out == []  # dropped
    client.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_confidence_not_entailed_is_kept() -> None:
    # The critical false-positive guard: an unsure "drop" must NOT kill the claim.
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=False, confidence=0.4)
    claims = [_claim("REVENUE_GROWTH")]
    out = await _run(claims, client, min_drop_confidence=0.7)
    assert out == claims


@pytest.mark.asyncio
async def test_entailed_keeps_claim() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=True, confidence=0.99)
    claims = [_claim("GUIDANCE_RAISE")]
    out = await _run(claims, client)
    assert out == claims


@pytest.mark.asyncio
async def test_llm_exception_fails_open_keeps_claim() -> None:
    client = AsyncMock()
    client.extract.side_effect = RuntimeError("deepinfra 500")
    claims = [_claim("EPS_BEAT")]
    out = await _run(claims, client)
    assert out == claims  # fail-open


@pytest.mark.asyncio
async def test_unparseable_output_fails_open() -> None:
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    client = AsyncMock()
    client.extract.return_value = ExtractionOutput(result={}, raw_response="not json at all", model_id="test-model")
    claims = [_claim("HEADCOUNT_CHANGE")]
    out = await _run(claims, client)
    assert out == claims


@pytest.mark.asyncio
async def test_raw_response_fallback_parse_drops() -> None:
    # Client fills only raw_response (no structured result) — fallback parse must work.
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=False, confidence=0.9, raw_only=True)
    claims = [_claim("DEBT_CHANGE")]
    out = await _run(claims, client, min_drop_confidence=0.7)
    assert out == []


@pytest.mark.asyncio
async def test_max_per_doc_caps_calls() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=True, confidence=0.9)
    claims = [_claim("DEBT_CHANGE") for _ in range(5)]
    out = await _run(claims, client, max_per_doc=2)
    # Only 2 checked; all kept (entailed), but exactly 2 LLM calls made.
    assert len(out) == 5
    assert client.extract.await_count == 2


@pytest.mark.asyncio
async def test_mixed_batch_only_gated_checked_and_order_preserved() -> None:
    client = AsyncMock()
    # DEBT_CHANGE -> drop; REVENUE_GROWTH -> keep (entailed)
    client.extract.side_effect = [
        _make_output(entailed=False, confidence=0.95),
        _make_output(entailed=True, confidence=0.95),
    ]
    claims = [
        _claim("PRODUCT_LAUNCH"),  # skipped, kept
        _claim("DEBT_CHANGE"),  # dropped
        _claim("ANALYST_RATING"),  # skipped, kept
        _claim("REVENUE_GROWTH"),  # kept
    ]
    out = await _run(claims, client)
    types = [c["claim_type"] for c in out]
    assert types == ["PRODUCT_LAUNCH", "ANALYST_RATING", "REVENUE_GROWTH"]
    assert client.extract.await_count == 2


@pytest.mark.asyncio
async def test_missing_entity_ref_skips_llm() -> None:
    client = AsyncMock()
    claim = _claim("DEBT_CHANGE")
    claim["entity_ref"] = ""
    out = await _run([claim], client)
    assert out == [claim]
    client.extract.assert_not_awaited()


def test_default_high_fab_claim_types_match_audit() -> None:
    assert DEFAULT_HIGH_FAB_CLAIM_TYPES == frozenset(
        {"DEBT_CHANGE", "REVENUE_GROWTH", "GUIDANCE_RAISE", "GUIDANCE_CUT", "HEADCOUNT_CHANGE", "EPS_BEAT"}
    )
