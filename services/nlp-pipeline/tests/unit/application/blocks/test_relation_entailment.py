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


# ── Usage-log threading (cost visibility) ─────────────────────────────────────
# The verifier's Qwen3-235B spend was invisible because the block called
# extract() with NO usage_logger. These prove EVERY verifier call — success and
# failure — now appends exactly one llm_usage_log row, and that non-risky/skipped
# relations never touch the logger (no phantom cost).
_DOC_UUID = "0190bd3e-0000-7000-8000-000000000000"  # valid UUIDv7-shaped string


class _FakeUsageLogger:
    """Captures ``log()`` kwargs so tests can assert what was recorded."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_usage_logged_on_successful_check() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.return_value = _make_output(asserted=True, confidence=0.9)
    usage = _FakeUsageLogger()
    await check_relation_entailment(
        [_relation("competes_with")],
        entailment_client=client,
        model_id="Qwen3-235B",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    assert len(usage.calls) == 1
    call = usage.calls[0]
    assert call["capability"] == "extraction"
    assert call["provider"] == "deepinfra"
    assert call["success"] is True
    assert call["model_id"] == "Qwen3-235B"


@pytest.mark.asyncio
async def test_usage_logged_on_failed_check_marks_failure() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.side_effect = RuntimeError("deepinfra 500")
    usage = _FakeUsageLogger()
    out = await check_relation_entailment(
        [_relation("produces")],
        entailment_client=client,
        model_id="Qwen3-235B",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    # Fail-open still keeps the relation, AND the failed call is recorded.
    assert len(out) == 1
    assert len(usage.calls) == 1
    assert usage.calls[0]["success"] is False
    assert usage.calls[0]["error_code"] == "model_error"


@pytest.mark.asyncio
async def test_no_usage_logged_when_no_llm_call() -> None:
    client = AsyncMock()
    usage = _FakeUsageLogger()
    # Non-risky predicate → skipped → no LLM call → no cost row.
    await check_relation_entailment(
        [_relation("listed_on")],
        entailment_client=client,
        model_id="Qwen3-235B",
        doc_id=_DOC_UUID,
        usage_logger=usage,
    )
    assert usage.calls == []
    client.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_usage_logger_failure_never_breaks_verdict() -> None:
    client = AsyncMock()
    client.provider = "deepinfra"
    client.extract.return_value = _make_output(asserted=False, confidence=0.95)

    class _BoomLogger:
        async def log(self, **kwargs: Any) -> None:
            raise RuntimeError("cost-log db down")

    # A drop must still happen even though the cost logger explodes.
    out = await check_relation_entailment(
        [_relation("competes_with")],
        entailment_client=client,
        model_id="Qwen3-235B",
        min_drop_confidence=0.7,
        doc_id=_DOC_UUID,
        usage_logger=_BoomLogger(),
    )
    assert out == []


# ── Content-addressed result cache (cost dedup for the deterministic verifier) ──
# Mirrors the claim-entailment cache tests: the verifier runs at temperature=0.0,
# so the SAME (subject, predicate, object, evidence) tuple always yields the SAME
# verdict — caching it is safe.


class _FakeCache:
    """In-memory stand-in for EntailmentCachePort."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self.set_calls: list[tuple[str, dict[str, Any], int]] = []

    async def get(self, key: str) -> dict[str, Any] | None:
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
    rel = _relation("competes_with")
    out_first = await check_relation_entailment(
        [rel],
        entailment_client=AsyncMock(extract=AsyncMock(return_value=_make_output(asserted=False, confidence=0.95))),
        model_id="test-model",
        doc_id="doc-1",
        min_drop_confidence=0.7,
        cache=cache,
    )
    assert out_first == []
    assert len(cache.set_calls) == 1

    client = AsyncMock()
    out_second = await check_relation_entailment(
        [rel],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-2",
        min_drop_confidence=0.7,
        cache=cache,
    )
    client.extract.assert_not_awaited()
    assert out_second == []


@pytest.mark.asyncio
async def test_cache_miss_calls_llm_and_writes_result() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=True, confidence=0.9)
    cache = _FakeCache()
    rel = _relation("produces")
    out = await check_relation_entailment(
        [rel],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        cache=cache,
    )
    assert out == [rel]
    client.extract.assert_awaited_once()
    assert len(cache.set_calls) == 1
    key, value, ttl = cache.set_calls[0]
    assert value == {"asserted": True, "confidence": 0.9}
    assert ttl > 0
    assert key in cache.store


@pytest.mark.asyncio
async def test_cache_hits_do_not_count_against_max_per_doc() -> None:
    # 3 identical relations sharing one cache entry + 1 distinct relation, capped
    # at max_per_doc=2 (enough for the 2 DISTINCT pairs' misses, but far fewer
    # than the 4 total relations): the 2 cache-hitting duplicates must NOT
    # consume any of that budget, so both distinct pairs still get their own
    # real LLM call.
    client = AsyncMock()
    client.extract.side_effect = [
        _make_output(asserted=True, confidence=0.9),
        _make_output(asserted=False, confidence=0.95),
    ]
    cache = _FakeCache()
    dup = _relation("competes_with", evidence="Acme competes with Beta in cloud services.")
    distinct = _relation("competes_with", evidence="Acme and Beta were both mentioned in the report.")
    rels = [dup, dup, dup, distinct]
    out = await check_relation_entailment(
        rels,
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        max_per_doc=2,
        min_drop_confidence=0.7,
        cache=cache,
    )
    assert len(out) == 3
    assert client.extract.await_count == 2  # one per DISTINCT pair, not per relation


@pytest.mark.asyncio
async def test_cache_get_error_falls_back_to_llm_call() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=True, confidence=0.9)
    rel = _relation("supplier_of")
    out = await check_relation_entailment(
        [rel],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        cache=_BoomCache(),
    )
    assert out == [rel]
    client.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_set_error_never_affects_returned_verdict() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=False, confidence=0.95)
    rel = _relation("regulates")
    out = await check_relation_entailment(
        [rel],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
        min_drop_confidence=0.7,
        cache=_BoomCache(),
    )
    assert out == []


@pytest.mark.asyncio
async def test_no_cache_means_no_caching_behaviour_change() -> None:
    client = AsyncMock()
    client.extract.return_value = _make_output(asserted=True, confidence=0.9)
    rel = _relation("competes_with")
    out = await check_relation_entailment(
        [rel, rel],
        entailment_client=client,
        model_id="test-model",
        doc_id="doc-1",
    )
    assert out == [rel, rel]
    assert client.extract.await_count == 2
