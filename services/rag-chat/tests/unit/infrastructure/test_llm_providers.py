"""Unit tests for LLM provider adapters and LLMProviderChain (T-F-3-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.domain.errors import ProviderUnavailableError
from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain


def _make_provider(name: str, chunks: list[str] | None = None, *, fail: bool = False) -> MagicMock:
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.name = name

    async def _stream(prompt: str, *, max_tokens: int, temperature: float):  # type: ignore[no-untyped-def]
        if fail:
            raise RuntimeError(f"{name} is down")
        for chunk in chunks or ["hello ", "world"]:
            yield chunk

    provider.stream = _stream
    return provider


def _make_valkey(neg_cached: set[str] | None = None) -> AsyncMock:
    """Create a mock Valkey client."""
    neg = neg_cached or set()
    valkey = AsyncMock()
    valkey.exists = AsyncMock(side_effect=lambda key: key.split(":")[-1] in neg)
    valkey.setex = AsyncMock()
    return valkey


@pytest.mark.unit
async def test_provider_chain_skips_negative_cached() -> None:
    """Provider in neg cache -> skipped, next provider used."""
    primary = _make_provider("deepinfra", ["token1"])
    secondary = _make_provider("openrouter", ["token2"])
    valkey = _make_valkey(neg_cached={"deepinfra"})

    chain = LLMProviderChain(providers=[primary, secondary], valkey=valkey)
    tokens = []
    async for chunk in chain.stream("prompt"):
        tokens.append(chunk)

    assert tokens == ["token2"]
    assert chain.last_provider_name == "openrouter"


@pytest.mark.unit
async def test_provider_chain_falls_back_on_error() -> None:
    """Primary fails -> secondary used."""
    primary = _make_provider("deepinfra", fail=True)
    secondary = _make_provider("openrouter", ["fallback_token"])
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[primary, secondary], valkey=valkey)
    tokens = []
    async for chunk in chain.stream("prompt"):
        tokens.append(chunk)

    assert tokens == ["fallback_token"]
    assert chain.last_provider_name == "openrouter"


@pytest.mark.unit
async def test_provider_chain_all_failed_raises() -> None:
    """All providers fail -> ProviderUnavailableError raised."""
    p1 = _make_provider("deepinfra", fail=True)
    p2 = _make_provider("openrouter", fail=True)
    p3 = _make_provider("ollama", fail=True)
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[p1, p2, p3], valkey=valkey)

    with pytest.raises(ProviderUnavailableError):
        async for _ in chain.stream("prompt"):
            pass


@pytest.mark.unit
async def test_provider_chain_sets_negative_cache() -> None:
    """Failure -> 60 s neg cache set."""
    primary = _make_provider("deepinfra", fail=True)
    secondary = _make_provider("openrouter", ["ok"])
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[primary, secondary], valkey=valkey)
    async for _ in chain.stream("prompt"):
        pass

    valkey.setex.assert_called_once()
    args = valkey.setex.call_args[0]
    assert "deepinfra" in args[0]
    assert args[1] == 60


@pytest.mark.unit
async def test_provider_chain_first_provider_success() -> None:
    """Happy path: first provider returns tokens without fallback."""
    primary = _make_provider("deepinfra", ["tok1", "tok2", "tok3"])
    valkey = _make_valkey()

    chain = LLMProviderChain(providers=[primary], valkey=valkey)
    tokens = []
    async for chunk in chain.stream("prompt"):
        tokens.append(chunk)

    assert tokens == ["tok1", "tok2", "tok3"]
    valkey.setex.assert_not_called()
