"""Unit tests for the 4 intelligence tool handlers added in PLAN-0080 Wave A.

Handlers under test:
  - _handle_get_entity_narrative   (calls S7IntelligencePort.get_narrative)
  - _handle_get_entity_paths       (calls S7IntelligencePort.get_entity_paths)
  - _handle_get_entity_health      (calls S7IntelligencePort.get_entity_intelligence)
  - _handle_get_entity_intelligence (calls S7IntelligencePort.get_entity_intelligence)

Each handler is tested for:
  (a) happy path — returns a RetrievedItem
  (b) EntityContext enforcement — scoped entity_id is used, ignoring the LLM-supplied arg
  (c) scope mismatch — LLM passes different entity_id → scoped id used + structlog warning
  (d) missing port (s7_intel=None) → returns []
  (e) upstream returns None/empty → returns []
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

_SCOPED_ENTITY_ID = UUID("018f0000-0000-7000-8000-000000000001")
_OTHER_ENTITY_ID = UUID("018f0000-0000-7000-8000-000000000099")
_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-000000000002")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000003")

# ── Helper builders ───────────────────────────────────────────────────────────


def _make_registry():
    """Build a ToolRegistry with all 14 tools (including the 4 new intelligence tools)."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry

    return build_default_registry()


def _make_s3_port() -> AsyncMock:
    """Minimal S3Port mock."""
    mock = AsyncMock()
    mock.get_ohlcv_range.return_value = []
    mock.get_fundamentals_history.return_value = []
    mock.get_fundamentals_highlights.return_value = {}
    mock.get_earnings.return_value = []
    mock.get_quote.return_value = {}
    mock.find_instrument_by_ticker.return_value = None
    return mock


def _make_entity_context(
    entity_id: UUID = _SCOPED_ENTITY_ID,
    ticker: str = "AAPL",
    name: str = "Apple Inc.",
) -> Any:
    """Build an EntityContext for entity-first tests."""
    from rag_chat.application.pipeline.tool_executor import EntityContext

    return EntityContext(entity_id=entity_id, ticker=ticker, name=name)


def _make_tool_use_block(name: str, input_dict: dict | None = None) -> Any:
    """Build a ToolUseBlock for the given tool name."""
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=input_dict or {})


def _make_s7_intel_port(
    narrative: Any = None,
    paths: Any = None,
    intelligence: Any = None,
) -> AsyncMock:
    """Build a mock S7IntelligencePort with configurable responses."""
    from rag_chat.application.ports.upstream_clients import EntityPathsResult

    mock = AsyncMock()
    mock.get_narrative.return_value = narrative
    mock.get_entity_paths.return_value = paths or EntityPathsResult(entity_id=str(_SCOPED_ENTITY_ID))
    mock.get_entity_intelligence.return_value = intelligence
    return mock


def _make_narrative_result(
    entity_id: str | None = None,
    content: str = "Apple is strategically positioned in AI hardware...",
    version: int = 3,
    generated_at: str | None = "2026-05-09T10:00:00Z",
) -> Any:
    """Build a NarrativeResult for get_entity_narrative tests."""
    from rag_chat.application.ports.upstream_clients import NarrativeResult

    return NarrativeResult(
        entity_id=entity_id or str(_SCOPED_ENTITY_ID),
        content=content,
        version=version,
        generated_at=generated_at,
    )


def _make_paths_result(
    entity_id: str | None = None,
    paths: list | None = None,
    total_paths: int | None = None,
) -> Any:
    """Build an EntityPathsResult for get_entity_paths tests."""
    from rag_chat.application.ports.upstream_clients import EntityPathsResult

    _paths = paths or [
        {"hop_1": "Apple Inc.", "hop_2": "Beats Electronics", "relation": "ACQUIRED"},
        {"hop_1": "Apple Inc.", "hop_2": "TSMC", "relation": "SUPPLIES_TO"},
    ]
    return EntityPathsResult(
        entity_id=entity_id or str(_SCOPED_ENTITY_ID),
        paths=_paths,
        total_paths=total_paths if total_paths is not None else len(_paths),
    )


def _make_intelligence_result(
    entity_id: str | None = None,
    narrative: str | None = "Apple is a global technology leader...",
    health_score: float | None = 0.87,
    key_metrics: dict | None = None,
    source_distribution: dict | None = None,
    paths: list | None = None,
    relations_summary: str | None = "Strong supply chain relations",
) -> Any:
    """Build an EntityIntelligenceResult for intelligence/health tests."""
    from rag_chat.application.ports.upstream_clients import EntityIntelligenceResult

    return EntityIntelligenceResult(
        entity_id=entity_id or str(_SCOPED_ENTITY_ID),
        narrative=narrative,
        health_score=health_score,
        key_metrics=key_metrics or {"articles_30d": 42, "relations_count": 18},
        source_distribution=source_distribution or {"news": 0.7, "sec_filing": 0.3},
        paths=paths or [{"hop_1": "AAPL", "hop_2": "TSMC"}],
        relations_summary=relations_summary,
    )


def _make_executor(
    s7_intel: Any = None,
    entity_context: Any = None,
    user_id: UUID | None = _FAKE_USER_ID,
    tenant_id: UUID | None = _FAKE_TENANT_ID,
) -> Any:
    """Build a NarrativeHandler with the given s7_intel port and entity context.

    PLAN-0089 C-1: narrative/intelligence tools moved to NarrativeHandler; tests
    now target the handler directly instead of routing through ToolExecutor.
    """
    from rag_chat.application.pipeline.handlers.narrative import NarrativeHandler

    return NarrativeHandler(
        s7_intel=s7_intel,
        entity_context=entity_context,
        timeout=5.0,
    )


# ── get_entity_narrative tests ────────────────────────────────────────────────


class TestGetEntityNarrative:
    """Tests for _handle_get_entity_narrative."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: upstream returns a narrative → single RetrievedItem returned."""
        narrative = _make_narrative_result()
        mock_port = _make_s7_intel_port(narrative=narrative)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_narrative")
        result = await executor._handle_get_entity_narrative(block)

        assert len(result) == 1
        item = result[0]
        assert "Apple is strategically positioned" in item.text
        assert item.score == pytest.approx(0.92)
        assert item.trust_weight == pytest.approx(0.88)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "narrative"
        mock_port.get_narrative.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_entity_context_auto_injects_scoped_id(self) -> None:
        """(b) When entity_context is set, entity_id is auto-injected from scope (M-1)."""
        narrative = _make_narrative_result()
        mock_port = _make_s7_intel_port(narrative=narrative)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_narrative")
        # LLM passes no entity_id — should be auto-injected from context
        result = await executor._handle_get_entity_narrative(block)

        assert len(result) == 1
        mock_port.get_narrative.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_scope_mismatch_uses_scoped_id(self) -> None:
        """(c) LLM passes different entity_id than scope → scoped id overrides (M-1)."""
        narrative = _make_narrative_result()
        mock_port = _make_s7_intel_port(narrative=narrative)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_narrative")
        # LLM passes a DIFFERENT entity_id — must be overridden
        result = await executor._handle_get_entity_narrative(
            block,
            entity_id=str(_OTHER_ENTITY_ID),
        )

        assert len(result) == 1
        # Must be called with the scoped entity_id, not the LLM-supplied one
        mock_port.get_narrative.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(d) When s7_intel is None, returns empty list without error."""
        executor = _make_executor(s7_intel=None)
        block = _make_tool_use_block("get_entity_narrative")
        # Need an entity_id since no entity_context and no port
        result = await executor._handle_get_entity_narrative(
            block,
            entity_id=str(_SCOPED_ENTITY_ID),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_none_returns_empty(self) -> None:
        """(e) Upstream returns None → returns empty list."""
        mock_port = _make_s7_intel_port(narrative=None)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_narrative")
        result = await executor._handle_get_entity_narrative(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_content_returns_empty(self) -> None:
        """(e) Upstream returns narrative with empty content → returns empty list."""
        from rag_chat.application.ports.upstream_clients import NarrativeResult

        empty_narrative = NarrativeResult(entity_id=str(_SCOPED_ENTITY_ID), content="")
        mock_port = _make_s7_intel_port(narrative=empty_narrative)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_narrative")
        result = await executor._handle_get_entity_narrative(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_entity_context_uses_llm_provided_id(self) -> None:
        """When no entity context, use LLM-provided entity_id directly."""
        narrative = _make_narrative_result()
        mock_port = _make_s7_intel_port(narrative=narrative)
        executor = _make_executor(s7_intel=mock_port, entity_context=None)
        block = _make_tool_use_block("get_entity_narrative")
        result = await executor._handle_get_entity_narrative(
            block,
            entity_id=str(_SCOPED_ENTITY_ID),
        )
        assert len(result) == 1
        mock_port.get_narrative.assert_awaited_once_with(_SCOPED_ENTITY_ID)


# ── get_entity_paths tests ────────────────────────────────────────────────────


class TestGetEntityPaths:
    """Tests for _handle_get_entity_paths."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: upstream returns paths → single RetrievedItem returned."""
        paths = _make_paths_result()
        mock_port = _make_s7_intel_port(paths=paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_paths")
        result = await executor._handle_get_entity_paths(block, top_n=5)

        assert len(result) == 1
        item = result[0]
        assert "Apple Inc." in item.text
        assert item.score == pytest.approx(0.85)
        assert item.trust_weight == pytest.approx(0.82)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "knowledge_graph"
        mock_port.get_entity_paths.assert_awaited_once_with(_SCOPED_ENTITY_ID, top_n=5)

    @pytest.mark.asyncio
    async def test_entity_context_auto_injects_scoped_id(self) -> None:
        """(b) EntityContext scope is used for the paths query (M-1)."""
        paths = _make_paths_result()
        mock_port = _make_s7_intel_port(paths=paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_paths")
        result = await executor._handle_get_entity_paths(block)

        assert len(result) == 1
        mock_port.get_entity_paths.assert_awaited_once_with(_SCOPED_ENTITY_ID, top_n=5)

    @pytest.mark.asyncio
    async def test_scope_mismatch_uses_scoped_id(self) -> None:
        """(c) LLM entity_id different from scope → scoped id overrides (M-1)."""
        paths = _make_paths_result()
        mock_port = _make_s7_intel_port(paths=paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_paths")
        result = await executor._handle_get_entity_paths(
            block,
            entity_id=str(_OTHER_ENTITY_ID),
            top_n=3,
        )

        assert len(result) == 1
        mock_port.get_entity_paths.assert_awaited_once_with(_SCOPED_ENTITY_ID, top_n=3)

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(d) s7_intel=None → returns []."""
        executor = _make_executor(s7_intel=None)
        block = _make_tool_use_block("get_entity_paths")
        result = await executor._handle_get_entity_paths(
            block,
            entity_id=str(_SCOPED_ENTITY_ID),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_empty_paths_returns_empty(self) -> None:
        """(e) Upstream returns EntityPathsResult with empty paths → returns []."""
        from rag_chat.application.ports.upstream_clients import EntityPathsResult

        empty_paths = EntityPathsResult(entity_id=str(_SCOPED_ENTITY_ID), paths=[], total_paths=0)
        mock_port = _make_s7_intel_port(paths=empty_paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_paths")
        result = await executor._handle_get_entity_paths(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_top_n_clamped_to_valid_range(self) -> None:
        """top_n is clamped between 1 and 20 regardless of LLM input."""
        paths = _make_paths_result()
        mock_port = _make_s7_intel_port(paths=paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_paths")
        # top_n=999 should be clamped to 20
        await executor._handle_get_entity_paths(block, top_n=999)
        mock_port.get_entity_paths.assert_awaited_once_with(_SCOPED_ENTITY_ID, top_n=20)

    @pytest.mark.asyncio
    async def test_top_n_clamped_to_minimum(self) -> None:
        """top_n=0 or negative should be clamped to 1."""
        paths = _make_paths_result()
        mock_port = _make_s7_intel_port(paths=paths)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_paths")
        await executor._handle_get_entity_paths(block, top_n=0)
        mock_port.get_entity_paths.assert_awaited_once_with(_SCOPED_ENTITY_ID, top_n=1)


# ── get_entity_health tests ───────────────────────────────────────────────────


class TestGetEntityHealth:
    """Tests for _handle_get_entity_health."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: upstream returns intelligence bundle → health RetrievedItem."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(block)

        assert len(result) == 1
        item = result[0]
        assert "Health data for" in item.text
        assert "0.87" in item.text  # health_score formatted
        assert item.score == pytest.approx(0.88)
        assert item.trust_weight == pytest.approx(0.85)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "narrative"
        # Health uses get_entity_intelligence (same bundle, health fields extracted)
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_entity_context_auto_injects_scoped_id(self) -> None:
        """(b) EntityContext scope is used for the health query."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(block)

        assert len(result) == 1
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_scope_mismatch_uses_scoped_id(self) -> None:
        """(c) LLM entity_id different from scope → scoped id overrides (M-1)."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(
            block,
            entity_id=str(_OTHER_ENTITY_ID),
        )

        assert len(result) == 1
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(d) s7_intel=None → returns []."""
        executor = _make_executor(s7_intel=None)
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(
            block,
            entity_id=str(_SCOPED_ENTITY_ID),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_none_returns_empty(self) -> None:
        """(e) Upstream returns None → returns []."""
        mock_port = _make_s7_intel_port(intelligence=None)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_null_health_score_still_returns_item(self) -> None:
        """health_score=None in bundle → item still returned without health line."""
        from rag_chat.application.ports.upstream_clients import EntityIntelligenceResult

        intelligence = EntityIntelligenceResult(
            entity_id=str(_SCOPED_ENTITY_ID),
            health_score=None,
            key_metrics={"articles_30d": 5},
        )
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_health")
        result = await executor._handle_get_entity_health(block)

        # Should still return an item (with just the key_metrics line)
        assert len(result) == 1
        assert "Health score" not in result[0].text  # no score line when null
        assert "Key metrics" in result[0].text


# ── get_entity_intelligence tests ─────────────────────────────────────────────


class TestGetEntityIntelligence:
    """Tests for _handle_get_entity_intelligence."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_retrieved_item(self) -> None:
        """(a) Happy path: upstream returns full bundle → single RetrievedItem."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(block)

        assert len(result) == 1
        item = result[0]
        assert "Intelligence bundle for" in item.text
        assert "## Narrative" in item.text
        assert "Apple is a global technology leader" in item.text
        assert "## Health Score" in item.text
        assert "0.87" in item.text
        assert item.score == pytest.approx(0.90)
        assert item.trust_weight == pytest.approx(0.88)
        assert item.citation_meta is not None
        assert item.citation_meta.source_name == "narrative"
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_entity_context_auto_injects_scoped_id(self) -> None:
        """(b) EntityContext scope is used for the intelligence query."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(block)

        assert len(result) == 1
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_scope_mismatch_uses_scoped_id(self) -> None:
        """(c) LLM entity_id different from scope → scoped id overrides (M-1)."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID),
        )
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(
            block,
            entity_id=str(_OTHER_ENTITY_ID),
        )

        assert len(result) == 1
        mock_port.get_entity_intelligence.assert_awaited_once_with(_SCOPED_ENTITY_ID)

    @pytest.mark.asyncio
    async def test_missing_port_returns_empty(self) -> None:
        """(d) s7_intel=None → returns []."""
        executor = _make_executor(s7_intel=None)
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(
            block,
            entity_id=str(_SCOPED_ENTITY_ID),
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_upstream_returns_none_returns_empty(self) -> None:
        """(e) Upstream returns None → returns []."""
        mock_port = _make_s7_intel_port(intelligence=None)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(block)
        assert result == []

    @pytest.mark.asyncio
    async def test_sparse_bundle_renders_only_available_sections(self) -> None:
        """Bundle with only narrative (no health, no paths) → only Narrative section rendered."""
        from rag_chat.application.ports.upstream_clients import EntityIntelligenceResult

        sparse = EntityIntelligenceResult(
            entity_id=str(_SCOPED_ENTITY_ID),
            narrative="Apple is navigating macro headwinds.",
            health_score=None,
            key_metrics={},
            source_distribution={},
            paths=[],
            relations_summary=None,
        )
        mock_port = _make_s7_intel_port(intelligence=sparse)
        executor = _make_executor(
            s7_intel=mock_port,
            entity_context=_make_entity_context(),
        )
        block = _make_tool_use_block("get_entity_intelligence")
        result = await executor._handle_get_entity_intelligence(block)

        assert len(result) == 1
        text = result[0].text
        assert "## Narrative" in text
        assert "## Health Score" not in text
        assert "## Key Metrics" not in text
        assert "## Top Paths" not in text

    @pytest.mark.asyncio
    async def test_no_entity_context_no_entity_id_returns_empty(self) -> None:
        """No entity_context + no entity_id from LLM → returns [] (no scoping possible)."""
        intelligence = _make_intelligence_result()
        mock_port = _make_s7_intel_port(intelligence=intelligence)
        executor = _make_executor(s7_intel=mock_port, entity_context=None)
        block = _make_tool_use_block("get_entity_intelligence")
        # No entity_id passed — no context available
        result = await executor._handle_get_entity_intelligence(block)
        assert result == []
        mock_port.get_entity_intelligence.assert_not_awaited()


# ── _resolve_intel_entity_id tests ───────────────────────────────────────────


class TestResolveIntelEntityId:
    """Tests for the shared entity_id resolution helper."""

    def test_no_context_no_id_returns_none(self) -> None:
        """No entity context + no LLM entity_id → returns None."""
        executor = _make_executor(entity_context=None)
        result = executor._resolve_intel_entity_id("test_tool", None)
        assert result is None

    def test_no_context_with_valid_id_parses_it(self) -> None:
        """No entity context + valid UUID string → parsed UUID returned."""
        executor = _make_executor(entity_context=None)
        result = executor._resolve_intel_entity_id("test_tool", str(_SCOPED_ENTITY_ID))
        assert result == _SCOPED_ENTITY_ID

    def test_no_context_with_invalid_id_returns_none(self) -> None:
        """No entity context + invalid UUID string → returns None."""
        executor = _make_executor(entity_context=None)
        result = executor._resolve_intel_entity_id("test_tool", "not-a-uuid")
        assert result is None

    def test_with_context_returns_scoped_id(self) -> None:
        """Entity context present → always returns scoped entity_id."""
        executor = _make_executor(entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID))
        result = executor._resolve_intel_entity_id("test_tool", None)
        assert result == _SCOPED_ENTITY_ID

    def test_with_context_overrides_different_llm_id(self) -> None:
        """Entity context overrides a different LLM-supplied entity_id."""
        executor = _make_executor(entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID))
        result = executor._resolve_intel_entity_id("test_tool", str(_OTHER_ENTITY_ID))
        # Must return the SCOPED id, not the LLM-supplied other id
        assert result == _SCOPED_ENTITY_ID

    def test_with_context_matching_id_returns_scoped_id(self) -> None:
        """Entity context with same entity_id as LLM → returns scoped id (no warning needed)."""
        executor = _make_executor(entity_context=_make_entity_context(entity_id=_SCOPED_ENTITY_ID))
        result = executor._resolve_intel_entity_id("test_tool", str(_SCOPED_ENTITY_ID))
        assert result == _SCOPED_ENTITY_ID
