"""Unit tests for ChainedDescriptionAdapter (BP-RC8).

Tests verify:
- Returns first non-None result (primary succeeds)
- Falls through to next adapter when primary returns None
- Falls through to next adapter on exception
- Falls through to next adapter on asyncio.TimeoutError
- Returns None when all adapters are exhausted
- aclose() calls aclose() on all adapters that expose it
- Works with an empty adapter list (returns None immediately)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from ml_clients.adapters.chained_description import ChainedDescriptionAdapter

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTITY_ID = "00000000-0000-0000-0000-000000000001"
_NAME = "Jerome Powell"
_TYPE = "person"
_HINTS: dict[str, str] = {"role": "Fed Chair"}


def _mock_adapter(return_value: str | None) -> MagicMock:
    """Return an AsyncMock adapter whose generate_description returns *return_value*."""
    adapter = MagicMock()
    adapter.generate_description = AsyncMock(return_value=return_value)
    return adapter


def _raising_adapter(exc: Exception) -> MagicMock:
    """Return an adapter whose generate_description raises *exc*."""
    adapter = MagicMock()
    adapter.generate_description = AsyncMock(side_effect=exc)
    return adapter


def _hanging_adapter(delay_s: float = 999.0) -> MagicMock:
    """Return an adapter that hangs for *delay_s* seconds (simulates timeout)."""

    async def _hang(*args: object, **kwargs: object) -> str | None:
        await asyncio.sleep(delay_s)
        return "should never be reached"

    adapter = MagicMock()
    adapter.generate_description = _hang
    return adapter


async def _call(adapter: ChainedDescriptionAdapter) -> str | None:
    return await adapter.generate_description(
        entity_id=_ENTITY_ID,
        canonical_name=_NAME,
        entity_type=_TYPE,
        context_hints=_HINTS,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChainedDescriptionAdapterRouting:
    """Verify the chain-of-responsibility routing logic."""

    async def test_primary_success_returns_immediately(self) -> None:
        """When the primary adapter succeeds, its result is returned and fallback is never called."""
        primary = _mock_adapter("Primary description")
        fallback = _mock_adapter("Fallback description")
        chain = ChainedDescriptionAdapter([primary, fallback])

        result = await _call(chain)

        assert result == "Primary description"
        primary.generate_description.assert_awaited_once()
        fallback.generate_description.assert_not_awaited()

    async def test_primary_none_falls_through_to_fallback(self) -> None:
        """When primary returns None, fallback is tried next."""
        primary = _mock_adapter(None)
        fallback = _mock_adapter("Fallback description")
        chain = ChainedDescriptionAdapter([primary, fallback])

        result = await _call(chain)

        assert result == "Fallback description"
        primary.generate_description.assert_awaited_once()
        fallback.generate_description.assert_awaited_once()

    async def test_primary_exception_falls_through_to_fallback(self) -> None:
        """When primary raises, the chain catches it and tries the next adapter."""
        primary = _raising_adapter(RuntimeError("API error"))
        fallback = _mock_adapter("Fallback description")
        chain = ChainedDescriptionAdapter([primary, fallback])

        result = await _call(chain)

        assert result == "Fallback description"
        fallback.generate_description.assert_awaited_once()

    async def test_all_adapters_return_none_returns_none(self) -> None:
        """When every adapter returns None, the chain returns None (caller uses stub)."""
        chain = ChainedDescriptionAdapter([_mock_adapter(None), _mock_adapter(None)])

        result = await _call(chain)

        assert result is None

    async def test_all_adapters_raise_returns_none(self) -> None:
        """When every adapter raises, the chain returns None."""
        chain = ChainedDescriptionAdapter(
            [
                _raising_adapter(RuntimeError("error A")),
                _raising_adapter(ValueError("error B")),
            ]
        )

        result = await _call(chain)

        assert result is None

    async def test_empty_adapter_list_returns_none(self) -> None:
        """An empty chain returns None immediately."""
        result = await ChainedDescriptionAdapter([]).generate_description(
            entity_id=_ENTITY_ID,
            canonical_name=_NAME,
            entity_type=_TYPE,
            context_hints=_HINTS,
        )
        assert result is None

    async def test_single_adapter_success(self) -> None:
        chain = ChainedDescriptionAdapter([_mock_adapter("Only description")])
        assert await _call(chain) == "Only description"

    async def test_fallback_used_when_middle_adapter_fails(self) -> None:
        """Three-adapter chain: first fails, second fails, third succeeds."""
        chain = ChainedDescriptionAdapter(
            [
                _raising_adapter(RuntimeError("first error")),
                _mock_adapter(None),
                _mock_adapter("Third description"),
            ]
        )
        assert await _call(chain) == "Third description"


class TestChainedDescriptionAdapterTimeout:
    """Verify the per-adapter asyncio.wait_for timeout guard."""

    async def test_timeout_skips_to_next_adapter(self) -> None:
        """A hanging primary is abandoned after timeout; fallback is used."""
        # Use a very short timeout so the test does not actually wait 65 s.
        hanging = _hanging_adapter(delay_s=10.0)
        fallback = _mock_adapter("Fallback after timeout")
        chain = ChainedDescriptionAdapter([hanging, fallback], per_adapter_timeout_s=0.05)

        result = await _call(chain)

        assert result == "Fallback after timeout"
        fallback.generate_description.assert_awaited_once()

    async def test_timeout_on_all_returns_none(self) -> None:
        """When all adapters time out, the chain returns None."""
        chain = ChainedDescriptionAdapter(
            [_hanging_adapter(10.0), _hanging_adapter(10.0)],
            per_adapter_timeout_s=0.05,
        )

        result = await _call(chain)

        assert result is None


class TestChainedDescriptionAdapterAclose:
    """Verify aclose() cleanup behaviour (F-X15)."""

    async def test_aclose_calls_aclose_on_all_adapters(self) -> None:
        """aclose() must propagate to every adapter that exposes it."""
        a = _mock_adapter("A")
        a.aclose = AsyncMock()
        b = _mock_adapter("B")
        b.aclose = AsyncMock()
        chain = ChainedDescriptionAdapter([a, b])

        await chain.aclose()

        a.aclose.assert_awaited_once()
        b.aclose.assert_awaited_once()

    async def test_aclose_skips_adapters_without_aclose(self) -> None:
        """aclose() must not raise when an adapter does not have an aclose() method."""
        no_close = _mock_adapter("no-close")
        # Ensure there is NO aclose attribute (spec'ed MagicMock might add one)
        if hasattr(no_close, "aclose"):
            del no_close.aclose
        chain = ChainedDescriptionAdapter([no_close])

        # Should not raise
        await chain.aclose()

    async def test_aclose_continues_after_error(self) -> None:
        """aclose() must close all adapters even if one raises during cleanup."""
        a = _mock_adapter("A")
        a.aclose = AsyncMock(side_effect=RuntimeError("cleanup error"))
        b = _mock_adapter("B")
        b.aclose = AsyncMock()
        chain = ChainedDescriptionAdapter([a, b])

        # Should not raise despite adapter A failing to close
        await chain.aclose()

        b.aclose.assert_awaited_once()
