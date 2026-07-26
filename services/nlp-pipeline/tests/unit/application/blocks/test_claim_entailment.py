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
@pytest.mark.parametrize(
    "body",
    [
        {"entailed": False},
        {"entailed": False, "confidence": None},
        {"entailed": False, "confidence": "high"},
    ],
)
async def test_not_entailed_with_malformed_confidence_fails_open(body: dict[str, Any]) -> None:
    # Fail-open guard: a NOT_ENTAILED verdict whose confidence is missing/null/non-numeric
    # is UNKNOWN confidence and MUST keep the claim (never drop on ambiguity). Regression
    # for the confidence-default: an absent/garbage confidence must not read as max-confident
    # and silently shrink the KG.
    from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

    client = AsyncMock()
    client.extract.return_value = ExtractionOutput(
        result=dict(body), raw_response=json.dumps(body), model_id="test-model"
    )
    claims = [_claim("DEBT_CHANGE")]
    out = await _run(claims, client, min_drop_confidence=0.7)
    assert out == claims  # kept — malformed confidence never drops


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


# ── Usage-log threading (cost visibility) ─────────────────────────────────────
# The verifier spend was invisible because the block called extract() with NO
# usage_logger. These prove every verifier call (success + failure) appends one
# llm_usage_log row, skipped claims never touch the logger, and a logger failure
# never affects the verdict.
_DOC_UUID = "0190bd3e-0000-7000-8000-000000000000"


class _FakeUsageLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_usage_logged_on_successful_check() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.return_value = _make_output(entailed=True, confidence=0.9)
    usage = _FakeUsageLogger()
    await check_claim_entailment(
        [_claim("DEBT_CHANGE")],
        entailment_client=client,
        model_id="DeepSeek-V4-Flash",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    assert len(usage.calls) == 1
    call = usage.calls[0]
    assert call["capability"] == "extraction"
    assert call["provider"] == "deepinfra"
    assert call["success"] is True
    assert call["model_id"] == "DeepSeek-V4-Flash"


@pytest.mark.asyncio
async def test_usage_logged_on_failed_check_marks_failure() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.side_effect = RuntimeError("deepinfra 500")
    usage = _FakeUsageLogger()
    out = await check_claim_entailment(
        [_claim("REVENUE_GROWTH")],
        entailment_client=client,
        model_id="DeepSeek-V4-Flash",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    assert len(out) == 1  # fail-open keeps the claim
    assert len(usage.calls) == 1
    assert usage.calls[0]["success"] is False
    assert usage.calls[0]["error_code"] == "model_error"


@pytest.mark.asyncio
async def test_no_usage_logged_when_no_llm_call() -> None:
    client = AsyncMock()
    usage = _FakeUsageLogger()
    await check_claim_entailment(
        [_claim("PRODUCT_LAUNCH")],  # non-gated → skipped
        entailment_client=client,
        model_id="DeepSeek-V4-Flash",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    assert usage.calls == []
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_usage_logger_failure_never_breaks_verdict() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.return_value = _make_output(entailed=False, confidence=0.95)

    class _BoomLogger:
        async def log(self, **kwargs: Any) -> None:
            raise RuntimeError("cost-log db down")

    out = await check_claim_entailment(
        [_claim("DEBT_CHANGE")],
        entailment_client=client,
        model_id="DeepSeek-V4-Flash",
        min_drop_confidence=0.7,
        doc_id=_DOC_UUID,
        usage_logger=_BoomLogger(),
    )
    assert out == []


def test_default_high_fab_claim_types_match_audit() -> None:
    assert DEFAULT_HIGH_FAB_CLAIM_TYPES == frozenset(
        {"DEBT_CHANGE", "REVENUE_GROWTH", "GUIDANCE_RAISE", "GUIDANCE_CUT", "HEADCOUNT_CHANGE", "EPS_BEAT"}
    )


# ── Content-addressed result cache (cost dedup for the deterministic verifier) ──
# The verifier runs at temperature=0.0 (see ml_clients.adapters.deepseek_extraction),
# so the SAME (entity, claim_type, polarity, evidence) tuple always yields the SAME
# verdict — caching it is safe. These prove: a HIT skips the LLM call entirely and
# reuses the cached verdict; a MISS calls the LLM as before and writes the result
# back; a cache error is fail-open (treated as a miss, never breaks the verdict).


class _FakeCache:
    """In-memory stand-in for EntailmentCachePort."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, dict[str, Any], int]] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        self.get_calls.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        self.set_calls.append((key, value, ttl))
        self.store[key] = value


class _BoomCache:
    """A cache whose get()/set() always raise — exercises the fail-open path."""

    async def get(self, key: str) -> dict[str, Any] | None:
        raise RuntimeError("valkey down")

    async def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        raise RuntimeError("valkey down")


@pytest.mark.asyncio
async def test_cache_hit_skips_llm_call_and_uses_cached_verdict() -> None:
    cache = _FakeCache()
    claim = _claim("DEBT_CHANGE")
    # Pre-seed the cache with a confident NOT_ENTAILED verdict for this exact pair.
    out_first = await check_claim_entailment(
        [claim],
        entailment_client=AsyncMock(extract=AsyncMock(return_value=_make_output(entailed=False, confidence=0.95))),
        model_id="test-model",
        doc_id="doc-1",
        min_drop_confidence=0.7,
        cache=cache,
    )
    assert out_first == []  # dropped on the (cache-writing) miss path
    assert len(cache.set_calls) == 1

    # Second call with the SAME pair against a client that must NOT be awaited.
    client = AsyncMock()
    out_second = await check_claim_entailment(
        [claim],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-2",
        min_drop_confidence=0.7,
        cache=cache,
    )
    client.extract.assert_not_awaited()
    assert out_second == []  # cached verdict reproduces the same drop


@pytest.mark.asyncio
async def test_cache_miss_calls_llm_and_writes_result() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=True, confidence=0.9)
    cache = _FakeCache()
    claim = _claim("REVENUE_GROWTH")
    out = await check_claim_entailment(
        [claim],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        cache=cache,
    )
    assert out == [claim]
    client.extract.assert_awaited_once()
    assert len(cache.set_calls) == 1
    key, value, ttl = cache.set_calls[0]
    assert value == {"entailed": True, "confidence": 0.9}
    assert ttl > 0
    assert key in cache.store


@pytest.mark.asyncio
async def test_cache_hits_do_not_count_against_max_per_doc() -> None:
    # 3 identical claims sharing one cache entry + 1 distinct claim, capped at
    # max_per_doc=2 (enough for the 2 DISTINCT pairs' misses, but far fewer than
    # the 4 total claims): the 2 cache-hitting duplicates must NOT consume any of
    # that budget, so both distinct pairs still get their own real LLM call.
    client = AsyncMock()
    client.extract.side_effect = [
        _make_output(entailed=True, confidence=0.9),  # first duplicate: miss
        _make_output(entailed=False, confidence=0.95),  # distinct claim: miss
    ]
    cache = _FakeCache()
    dup = _claim("DEBT_CHANGE", evidence="Acme refinanced $2B of debt.")
    distinct = _claim("DEBT_CHANGE", evidence="Acme borrowed a fresh $500M term loan.")
    claims = [dup, dup, dup, distinct]
    out = await check_claim_entailment(
        claims,
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        max_per_doc=2,
        min_drop_confidence=0.7,
        cache=cache,
    )
    # 3 duplicates kept (entailed=True cached), distinct dropped (entailed=False).
    assert len(out) == 3
    assert client.extract.await_count == 2  # one per DISTINCT pair, not per claim


@pytest.mark.asyncio
async def test_cache_get_error_falls_back_to_llm_call() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=True, confidence=0.9)
    claim = _claim("EPS_BEAT")
    out = await check_claim_entailment(
        [claim],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        cache=_BoomCache(),
    )
    assert out == [claim]
    client.extract.assert_awaited_once()  # fail-open: cache error treated as a miss


@pytest.mark.asyncio
async def test_cache_set_error_never_affects_returned_verdict() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=False, confidence=0.95)
    claim = _claim("HEADCOUNT_CHANGE")
    out = await check_claim_entailment(
        [claim],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        min_drop_confidence=0.7,
        cache=_BoomCache(),
    )
    assert out == []  # the drop still happens despite the cache write failing


@pytest.mark.asyncio
async def test_no_cache_means_no_caching_behaviour_change() -> None:
    # cache=None (the default) must reproduce EXACTLY the pre-cache behaviour:
    # every gated claim pays for its own LLM call, no caching machinery invoked.
    client = AsyncMock()
    client.extract.return_value = _make_output(entailed=True, confidence=0.9)
    claim = _claim("DEBT_CHANGE")
    out = await check_claim_entailment(
        [claim, claim],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
    )
    assert out == [claim, claim]
    assert client.extract.await_count == 2
