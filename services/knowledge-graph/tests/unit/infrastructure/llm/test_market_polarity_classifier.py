"""Unit tests for MarketPolarityClassifier (PLAN-0056 Wave C3).

The LLM adapter is mocked (no live DeepInfra calls). Covers:
- bullish / bearish / neutral example inputs → correct label + clamped confidence.
- LLM failure (HTTP error / bad JSON / invalid polarity) → ("neutral", 0.0).
- Cost is logged NON-ZERO (from the provider's usage.estimated_cost) on success —
  the S6/S8 $0-cost regression guard.
- The (condition_id, entity_id) cache classifies each pair at most once.
- Empty api_key → inert (neutral, no HTTP call, no cost row).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_ENTITY = UUID("01920000-0000-7000-8000-000000000001")
_CONDITION = "0xabc123"


def _make_classifier(usage_logger: Any = None, *, api_key: str = "test-key") -> Any:
    from knowledge_graph.infrastructure.llm.market_polarity_classifier import MarketPolarityClassifier

    return MarketPolarityClassifier(
        api_key=api_key,
        model_id="Qwen/Qwen2.5-0.5B-Instruct",
        timeout_seconds=5,
        usage_logger=usage_logger,
    )


class _FakeResponse:
    def __init__(self, body: dict[str, Any], *, raise_exc: Exception | None = None) -> None:
        self._body = body
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self) -> dict[str, Any]:
        return self._body


def _patch_http(monkeypatch: Any, response: _FakeResponse, *, post_exc: Exception | None = None) -> list[dict]:
    """Patch httpx.AsyncClient so classify() hits our fake response. Returns POST call log."""
    calls: list[dict] = []

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            calls.append({"url": url, **kwargs})
            if post_exc is not None:
                raise post_exc
            return response

    import knowledge_graph.infrastructure.llm.market_polarity_classifier as mod

    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeClient)
    return calls


def _body(polarity: str, confidence: float, *, cost: float | None = 0.00012) -> dict[str, Any]:
    content = f'{{"polarity": "{polarity}", "confidence": {confidence}, "reason": "x"}}'
    body: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
    if cost is not None:
        body["usage"] = {"estimated_cost": cost}
    return body


class TestPolarityLabels:
    @pytest.mark.parametrize("label", ["bullish", "bearish", "neutral"])
    def test_returns_correct_label(self, monkeypatch: Any, label: str) -> None:
        _patch_http(monkeypatch, _FakeResponse(_body(label, 0.8)))
        clf = _make_classifier()
        polarity, conf = asyncio.run(
            clf.classify("Will X miss earnings?", "Company X", None, condition_id=_CONDITION, entity_id=_ENTITY),
        )
        assert polarity == label
        assert conf == pytest.approx(0.8)

    def test_confidence_clamped_to_unit_interval(self, monkeypatch: Any) -> None:
        _patch_http(monkeypatch, _FakeResponse(_body("bullish", 4.2)))
        clf = _make_classifier()
        _, conf = asyncio.run(clf.classify("q", "X"))
        assert conf == 1.0


class TestFailureModes:
    def test_http_error_returns_neutral(self, monkeypatch: Any) -> None:
        _patch_http(monkeypatch, _FakeResponse({}), post_exc=RuntimeError("boom"))
        clf = _make_classifier()
        assert asyncio.run(clf.classify("q", "X")) == ("neutral", 0.0)

    def test_bad_json_returns_neutral(self, monkeypatch: Any) -> None:
        bad = {"choices": [{"message": {"content": "not json at all"}}], "usage": {"estimated_cost": 0.0001}}
        _patch_http(monkeypatch, _FakeResponse(bad))
        clf = _make_classifier()
        assert asyncio.run(clf.classify("q", "X")) == ("neutral", 0.0)

    def test_invalid_polarity_value_returns_neutral(self, monkeypatch: Any) -> None:
        _patch_http(monkeypatch, _FakeResponse(_body("sideways", 0.9)))
        clf = _make_classifier()
        assert asyncio.run(clf.classify("q", "X")) == ("neutral", 0.0)

    def test_empty_api_key_is_inert(self, monkeypatch: Any) -> None:
        calls = _patch_http(monkeypatch, _FakeResponse(_body("bullish", 0.9)))
        clf = _make_classifier(api_key="")
        assert asyncio.run(clf.classify("q", "X")) == ("neutral", 0.0)
        assert calls == []  # no HTTP call made


class TestCostLogging:
    def test_cost_logged_non_zero_from_provider(self, monkeypatch: Any) -> None:
        _patch_http(monkeypatch, _FakeResponse(_body("bearish", 0.7, cost=0.00034)))
        usage_logger = AsyncMock()
        clf = _make_classifier(usage_logger=usage_logger)
        asyncio.run(clf.classify("q", "X"))
        usage_logger.log.assert_awaited_once()
        kwargs = usage_logger.log.call_args.kwargs
        assert kwargs["estimated_cost_usd"] > 0.0
        assert kwargs["cost_source"] == "provider"
        assert kwargs["capability"] == "classification"
        assert kwargs["success"] is True

    def test_failure_still_logs_usage(self, monkeypatch: Any) -> None:
        _patch_http(monkeypatch, _FakeResponse({}), post_exc=RuntimeError("boom"))
        usage_logger = AsyncMock()
        clf = _make_classifier(usage_logger=usage_logger)
        asyncio.run(clf.classify("q", "X"))
        usage_logger.log.assert_awaited_once()
        assert usage_logger.log.call_args.kwargs["success"] is False


class TestCaching:
    def test_same_pair_classified_once(self, monkeypatch: Any) -> None:
        calls = _patch_http(monkeypatch, _FakeResponse(_body("bullish", 0.9)))
        clf = _make_classifier()
        first = asyncio.run(clf.classify("q", "X", condition_id=_CONDITION, entity_id=_ENTITY))
        second = asyncio.run(clf.classify("q", "X", condition_id=_CONDITION, entity_id=_ENTITY))
        assert first == second == ("bullish", pytest.approx(0.9))
        assert len(calls) == 1  # second call served from cache

    def test_distinct_entities_each_classified(self, monkeypatch: Any) -> None:
        calls = _patch_http(monkeypatch, _FakeResponse(_body("neutral", 0.5)))
        clf = _make_classifier()
        other = UUID("01920000-0000-7000-8000-000000000002")
        asyncio.run(clf.classify("q", "X", condition_id=_CONDITION, entity_id=_ENTITY))
        asyncio.run(clf.classify("q", "Y", condition_id=_CONDITION, entity_id=other))
        assert len(calls) == 2

    def test_no_cache_without_keys(self, monkeypatch: Any) -> None:
        calls = _patch_http(monkeypatch, _FakeResponse(_body("bullish", 0.9)))
        clf = _make_classifier()
        asyncio.run(clf.classify("q", "X"))  # no condition_id/entity_id → not cached
        asyncio.run(clf.classify("q", "X"))
        assert len(calls) == 2
