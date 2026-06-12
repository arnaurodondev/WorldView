"""BP-661 regression — NarrativeHandler resolves non-UUID entity identifiers.

The "what is AAPL?" bug, tool side: the LLM passed ``entity_id="AAPL"`` to
``get_entity_intelligence``; ``UUID("AAPL")`` raised, the handler returned
[] and the user saw "I cannot find a matching entity" even though Apple Inc.
exists with a full intelligence bundle.

Contract under test:
  1. Ticker-shaped strings ("AAPL", "BRK.B") resolve via S6 ticker resolution.
  2. Free-text names ("Apple Inc.") resolve via the sibling
     IntelligenceHandler's S7 alias pipeline (``name_resolver.resolve_name``).
  3. Ticker miss falls through to name resolution.
  4. No resolvers wired → legacy UUID-only behaviour (returns None).
  5. EntityContext scope still always wins (M-1 unchanged).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.pipeline.handlers.narrative import NarrativeHandler

pytestmark = pytest.mark.unit

_APPLE_ID = UUID("01900000-0000-7000-8000-000000001001")
_SCOPED_ID = UUID("01900000-0000-7000-8000-000000009999")


def _make_intel_result() -> Any:
    """Minimal duck-typed intelligence bundle result."""
    result = MagicMock()
    result.narrative = "Apple Inc. designs consumer electronics."
    result.health_score = 0.73
    result.key_metrics = {"pe": 30.1}
    result.source_distribution = {}
    result.paths = []
    result.relations_summary = None
    return result


def _make_handler(
    *,
    s6: Any = None,
    name_resolver: Any = None,
    s7_intel: Any = None,
    entity_context: Any = None,
) -> NarrativeHandler:
    return NarrativeHandler(
        s7_intel=s7_intel,
        entity_context=entity_context,
        timeout=2.0,
        s6=s6,
        name_resolver=name_resolver,
    )


class TestTickerResolution:
    @pytest.mark.asyncio
    async def test_ticker_shaped_id_resolves_via_s6(self) -> None:
        """'AAPL' is not a UUID → resolved through S6.resolve_entity_by_ticker."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")

        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_class_share_ticker_shape_accepted(self) -> None:
        """Exchange-suffixed tickers like BRK.B pass the shape gate."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6)

        resolved = await handler._resolve_intel_entity_id("get_entity_health", "BRK.B")

        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_awaited_once_with("BRK.B")

    @pytest.mark.asyncio
    async def test_lowercase_name_skips_ticker_path(self) -> None:
        """'Apple Inc.' is not ticker-shaped → S6 ticker resolver never called."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        name_resolver = MagicMock()
        name_resolver.resolve_name = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, name_resolver=name_resolver)

        resolved = await handler._resolve_intel_entity_id("get_entity_narrative", "Apple Inc.")

        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_not_awaited()
        name_resolver.resolve_name.assert_awaited_once_with("get_entity_narrative", "Apple Inc.")

    @pytest.mark.asyncio
    async def test_ticker_miss_falls_through_to_name_resolution(self) -> None:
        """S6 ticker miss (None) → S7 alias name resolution is attempted next."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=None)
        name_resolver = MagicMock()
        name_resolver.resolve_name = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, name_resolver=name_resolver)

        resolved = await handler._resolve_intel_entity_id("get_entity_paths", "AAPL")

        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_awaited_once()
        name_resolver.resolve_name.assert_awaited_once_with("get_entity_paths", "AAPL")

    @pytest.mark.asyncio
    async def test_s6_exception_degrades_to_name_resolution(self) -> None:
        """An S6 transport error must not crash the tool — fall through gracefully."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(side_effect=ConnectionError("s6 down"))
        name_resolver = MagicMock()
        name_resolver.resolve_name = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, name_resolver=name_resolver)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")

        assert resolved == _APPLE_ID


class TestLegacyBehaviourPreserved:
    @pytest.mark.asyncio
    async def test_uuid_string_short_circuits_resolvers(self) -> None:
        """A valid UUID never touches S6/S7 — fast path unchanged."""
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock()
        name_resolver = MagicMock()
        name_resolver.resolve_name = AsyncMock()
        handler = _make_handler(s6=s6, name_resolver=name_resolver)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", str(_APPLE_ID))

        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_not_awaited()
        name_resolver.resolve_name.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_resolvers_wired_returns_none_for_non_uuid(self) -> None:
        """Default-constructed handler (tests/minimal harnesses) keeps legacy semantics."""
        handler = _make_handler()
        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_entity_context_always_wins_over_ticker(self) -> None:
        """M-1 scope enforcement: scoped entity overrides any LLM identifier."""
        ctx = MagicMock()
        ctx.entity_id = _SCOPED_ID
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, entity_context=ctx)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")

        assert resolved == _SCOPED_ID
        s6.resolve_entity_by_ticker.assert_not_awaited()


class TestInferredVsPinnedEntityContext:
    """BP-661 P/E→Pandora (2026-06-12): inferred scope must not override a valid LLM id.

    The regular /chat path builds an INFERRED EntityContext from
    ``entities[0]`` of the S6 resolve (``pinned=False``). That ranking is
    fragile — it ranked Pandora #1 for "AAPL's P/E" and Alexandria Real
    Estate #1 for "Apple's competitors". When the LLM supplies a concrete,
    valid ``entity_id`` (e.g. "AAPL"), the handler must keep the LLM's id, not
    silently swap in the inferred scope. The pinned ``/chat/entity-context``
    surface (``pinned=True``) keeps the hard override.
    """

    @pytest.mark.asyncio
    async def test_inferred_scope_does_not_override_valid_llm_ticker(self) -> None:
        from rag_chat.application.pipeline.tool_executor import EntityContext

        # Inferred scope = the wrong company S6 ranked first (Pandora).
        ctx = EntityContext(entity_id=_SCOPED_ID, ticker="P", name="Pandora", pinned=False)
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, entity_context=ctx)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")

        # The LLM's correct AAPL wins over the inferred Pandora scope.
        assert resolved == _APPLE_ID
        s6.resolve_entity_by_ticker.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_pinned_scope_overrides_valid_llm_ticker(self) -> None:
        from rag_chat.application.pipeline.tool_executor import EntityContext

        # Pinned entity-context surface — scope wins regardless of LLM id.
        ctx = EntityContext(entity_id=_SCOPED_ID, ticker="MSFT", name="Microsoft", pinned=True)
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        handler = _make_handler(s6=s6, entity_context=ctx)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "AAPL")

        assert resolved == _SCOPED_ID
        s6.resolve_entity_by_ticker.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inferred_scope_used_when_llm_id_missing(self) -> None:
        from rag_chat.application.pipeline.tool_executor import EntityContext

        ctx = EntityContext(entity_id=_SCOPED_ID, ticker="AAPL", name="Apple", pinned=False)
        handler = _make_handler(entity_context=ctx)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", None)

        # No LLM id → fall back to the inferred scope.
        assert resolved == _SCOPED_ID

    @pytest.mark.asyncio
    async def test_inferred_scope_used_when_llm_id_unresolvable(self) -> None:
        from rag_chat.application.pipeline.tool_executor import EntityContext

        ctx = EntityContext(entity_id=_SCOPED_ID, ticker="AAPL", name="Apple", pinned=False)
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=None)
        name_resolver = MagicMock()
        name_resolver.resolve_name = AsyncMock(return_value=None)
        handler = _make_handler(s6=s6, name_resolver=name_resolver, entity_context=ctx)

        resolved = await handler._resolve_intel_entity_id("get_entity_intelligence", "ZZZQQQ")

        # LLM id non-empty but unresolvable → degrade to the inferred scope.
        assert resolved == _SCOPED_ID


class TestEndToEndToolPath:
    @pytest.mark.asyncio
    async def test_get_entity_intelligence_with_ticker_returns_bundle(self) -> None:
        """The full live repro: get_entity_intelligence(entity_id='AAPL') returns data.

        Before BP-661 this returned [] (UUID parse failure) which produced
        the user-facing 'I cannot find a matching entity' answer.
        """
        s6 = MagicMock()
        s6.resolve_entity_by_ticker = AsyncMock(return_value=_APPLE_ID)
        s7_intel = MagicMock()
        s7_intel.get_entity_intelligence = AsyncMock(return_value=_make_intel_result())
        handler = _make_handler(s6=s6, s7_intel=s7_intel)

        items = await handler.execute("get_entity_intelligence", {"entity_id": "AAPL"})

        assert len(items) == 1
        assert "Apple Inc. designs consumer electronics." in items[0].text
        # Citation surfaces the human identifier, not a raw UUID string.
        assert items[0].citation_meta.entity_name == "AAPL"
        s7_intel.get_entity_intelligence.assert_awaited_once_with(_APPLE_ID)
