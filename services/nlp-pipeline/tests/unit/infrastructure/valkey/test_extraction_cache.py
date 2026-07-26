"""Unit tests for DeepExtractionCache (2026-07-26 cost audit).

Covers:
  - Cache key construction: identical (model_id, prompt) -> identical key;
    any difference in model_id OR prompt content -> a different key. Since
    ``prompt`` is the FULLY RENDERED extraction prompt, this also proves the
    correctness property the task requires: a prompt-template content change
    (which changes the rendered prompt even if ``version`` is unchanged)
    produces a different key and therefore cannot serve a stale cached result.
  - get()/set() round-trip against a fake Valkey client.
  - Fail-open behaviour: a Valkey error on get() returns None (miss) rather
    than raising; a Valkey error on set() is swallowed.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.infrastructure.valkey.extraction_cache import (
    DeepExtractionCache,
    build_cache_key,
)

pytestmark = pytest.mark.unit


class _FakeValkeyClient:
    """Minimal in-memory stand-in for messaging.valkey.client.ValkeyClient."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.store[key] = value
        self.set_calls.append((key, value, ttl))


class _RaisingValkeyClient:
    """Simulates a Valkey outage — every call raises."""

    async def get(self, key: str) -> str | None:
        raise ConnectionError("valkey unreachable")

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        raise ConnectionError("valkey unreachable")


@pytest.mark.unit
class TestBuildCacheKey:
    def test_identical_inputs_produce_identical_key(self) -> None:
        k1 = build_cache_key(model_id="deepseek-ai/DeepSeek-V4-Flash", prompt="rendered prompt text")
        k2 = build_cache_key(model_id="deepseek-ai/DeepSeek-V4-Flash", prompt="rendered prompt text")
        assert k1 == k2

    def test_different_model_id_produces_different_key(self) -> None:
        k1 = build_cache_key(model_id="deepseek-ai/DeepSeek-V4-Flash", prompt="same text")
        k2 = build_cache_key(model_id="Qwen/Qwen3-235B-A22B-Instruct-2507", prompt="same text")
        assert k1 != k2

    def test_different_window_text_produces_different_key(self) -> None:
        """A different article body must miss even under the same model."""
        k1 = build_cache_key(model_id="m", prompt="Apple reported record revenue.")
        k2 = build_cache_key(model_id="m", prompt="Apple reported a revenue miss.")
        assert k1 != k2

    def test_prompt_template_content_change_invalidates_key(self) -> None:
        """CRITICAL CORRECTNESS PROPERTY (task requirement): a prompt-template
        content edit — even one that does NOT bump the semver ``version``
        string — must invalidate the cache key. Because the key hashes the
        FULLY RENDERED prompt (which contains the template body verbatim),
        any byte-level template edit changes the key, simulating what
        happens when ``DEEP_EXTRACTION.template`` is edited in libs/prompts
        without touching ``DEEP_EXTRACTION.version``.
        """
        template_v1 = "You are an extraction engine. Extract relations from: {text}"
        template_v1_edited = "You are an extraction engine. Carefully extract relations from: {text}"
        rendered_before = template_v1.format(text="Acme acquired Foo Corp.")
        rendered_after = template_v1_edited.format(text="Acme acquired Foo Corp.")

        key_before = build_cache_key(model_id="m", prompt=rendered_before)
        key_after = build_cache_key(model_id="m", prompt=rendered_after)

        assert key_before != key_after

    def test_key_is_namespaced_under_ador0004_taxonomy(self) -> None:
        key = build_cache_key(model_id="m", prompt="p")
        assert key.startswith("nlp:v1:extraction_cache:")


@pytest.mark.unit
class TestDeepExtractionCacheGetSet:
    @pytest.mark.asyncio
    async def test_miss_returns_none(self) -> None:
        cache = DeepExtractionCache(client=_FakeValkeyClient())  # type: ignore[arg-type]
        result = await cache.get(model_id="m", prompt="p")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get_round_trips(self) -> None:
        fake_client = _FakeValkeyClient()
        cache = DeepExtractionCache(client=fake_client, ttl_seconds=1234)  # type: ignore[arg-type]
        payload: dict[str, Any] = {
            "events": [],
            "claims": [{"entity_ref": "Apple", "claim_type": "REVENUE_GROWTH", "polarity": "positive"}],
            "relations": [],
        }
        await cache.set(model_id="deepseek-ai/DeepSeek-V4-Flash", prompt="Apple grew revenue.", result=payload)
        got = await cache.get(model_id="deepseek-ai/DeepSeek-V4-Flash", prompt="Apple grew revenue.")
        assert got == payload
        # TTL was forwarded to the underlying client.
        assert fake_client.set_calls[0][2] == 1234

    @pytest.mark.asyncio
    async def test_different_prompt_is_a_miss(self) -> None:
        fake_client = _FakeValkeyClient()
        cache = DeepExtractionCache(client=fake_client)  # type: ignore[arg-type]
        empty_result: dict[str, Any] = {"events": [], "claims": [], "relations": []}
        await cache.set(model_id="m", prompt="Apple grew revenue.", result=empty_result)
        got = await cache.get(model_id="m", prompt="Tesla grew revenue.")
        assert got is None

    @pytest.mark.asyncio
    async def test_get_fails_open_on_valkey_error(self) -> None:
        cache = DeepExtractionCache(client=_RaisingValkeyClient())  # type: ignore[arg-type]
        result = await cache.get(model_id="m", prompt="p")
        assert result is None  # never raises

    @pytest.mark.asyncio
    async def test_set_fails_open_on_valkey_error(self) -> None:
        cache = DeepExtractionCache(client=_RaisingValkeyClient())  # type: ignore[arg-type]
        # Must not raise.
        await cache.set(model_id="m", prompt="p", result={"events": [], "claims": [], "relations": []})

    @pytest.mark.asyncio
    async def test_get_returns_none_on_corrupt_json(self) -> None:
        fake_client = _FakeValkeyClient()
        key = build_cache_key(model_id="m", prompt="p")
        fake_client.store[key] = "not valid json {{"
        cache = DeepExtractionCache(client=fake_client)  # type: ignore[arg-type]
        result = await cache.get(model_id="m", prompt="p")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_cached_value_is_not_a_dict(self) -> None:
        fake_client = _FakeValkeyClient()
        key = build_cache_key(model_id="m", prompt="p")
        fake_client.store[key] = json.dumps([1, 2, 3])  # a list, not a dict
        cache = DeepExtractionCache(client=fake_client)  # type: ignore[arg-type]
        result = await cache.get(model_id="m", prompt="p")
        assert result is None

    @pytest.mark.asyncio
    async def test_uses_default_ttl_when_not_specified(self) -> None:
        from nlp_pipeline.infrastructure.valkey.extraction_cache import DEFAULT_TTL_SECONDS

        fake_client = _FakeValkeyClient()
        cache = DeepExtractionCache(client=fake_client)  # type: ignore[arg-type]
        await cache.set(model_id="m", prompt="p", result={"events": [], "claims": [], "relations": []})
        assert fake_client.set_calls[0][2] == DEFAULT_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_client_receives_json_serialised_payload(self) -> None:
        """set() must persist a JSON string (not a python repr) — the
        watchlist/completion caches in this repo follow the same convention."""
        fake_client = AsyncMock()
        cache = DeepExtractionCache(client=fake_client)
        payload = {"events": [], "claims": [], "relations": [{"subject_ref": "A", "predicate": "p", "object_ref": "B"}]}
        await cache.set(model_id="m", prompt="p", result=payload)
        fake_client.set.assert_awaited_once()
        called_args, called_kwargs = fake_client.set.call_args
        stored_value = called_args[1] if len(called_args) > 1 else called_kwargs["value"]
        assert json.loads(stored_value) == payload
