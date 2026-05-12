"""Narrative and intelligence bundle tool handlers — PLAN-0080 Wave A tools via S7Intel.

Covers tools backed by S7IntelligencePort:
  - get_entity_narrative      (LLM-generated narrative summary)
  - get_entity_paths          (pre-computed multi-hop paths)
  - get_entity_health         (health score + key_metrics)
  - get_entity_intelligence   (full intelligence bundle)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.pipeline.tool_executor import EntityContext, ToolUseBlock
    from rag_chat.application.ports.upstream_clients import S7IntelligencePort

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_TOOL_RESULT_MAX_CHARS = 4000


class NarrativeHandler(ToolHandler):
    """Handles entity narrative and intelligence bundle tools (PLAN-0080 Wave A).

    All tools call S7IntelligencePort (S9-proxied intelligence endpoints, R14 compliance).
    """

    _HANDLED_TOOLS = frozenset(
        {"get_entity_narrative", "get_entity_paths", "get_entity_health", "get_entity_intelligence"}
    )

    def __init__(
        self,
        s7_intel: S7IntelligencePort | None = None,
        entity_context: EntityContext | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s7_intel = s7_intel
        self._entity_context = entity_context
        self._timeout = timeout

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        _stub = ToolUseBlock(name=tool_name, input=args)
        if tool_name == "get_entity_narrative":
            return await self._handle_get_entity_narrative(_stub, **args)
        if tool_name == "get_entity_paths":
            return await self._handle_get_entity_paths(_stub, **args)
        if tool_name == "get_entity_health":
            return await self._handle_get_entity_health(_stub, **args)
        if tool_name == "get_entity_intelligence":
            return await self._handle_get_entity_intelligence(_stub, **args)
        raise ValueError(f"NarrativeHandler cannot handle tool: {tool_name}")

    # ── Entity ID resolver (M-1: EntityContext scope enforcement) ──────────────

    def _resolve_intel_entity_id(self, tool_name: str, llm_entity_id: str | None) -> UUID | None:
        """Resolve entity_id, enforcing EntityContext scope (M-1).

        When the executor is bound to an entity scope, all intelligence tools MUST
        use that entity_id regardless of what the LLM passes. Prevents cross-entity
        data leakage in entity-first queries.
        """
        if self._entity_context is not None:
            if llm_entity_id is not None and llm_entity_id != str(self._entity_context.entity_id):
                log.warning(
                    "entity_context_override",
                    tool=tool_name,
                    llm_entity_id=llm_entity_id,
                    scoped_entity_id=str(self._entity_context.entity_id),
                )
            return self._entity_context.entity_id
        if llm_entity_id is not None:
            try:
                return UUID(llm_entity_id)
            except ValueError:
                log.warning("tool_invalid_entity_id", tool=tool_name, entity_id=llm_entity_id)
                return None
        log.warning("tool_no_entity_id", tool=tool_name)
        return None

    # ── Handlers ───────────────────────────────────────────────────────────────

    async def _handle_get_entity_narrative(
        self,
        tool_call: ToolUseBlock,
        entity_id: str | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve the LLM-generated narrative for an entity via S9 proxy."""
        if self._s7_intel is None:
            log.warning("tool_handler_missing_port", tool="get_entity_narrative", port="s7_intel")
            return []

        resolved_id = self._resolve_intel_entity_id("get_entity_narrative", entity_id)
        if resolved_id is None:
            return []

        try:
            result = await asyncio.wait_for(
                self._s7_intel.get_narrative(resolved_id),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_narrative", error=str(e))
            return []

        if result is None or not result.content:
            log.warning("tool_no_data", tool="get_entity_narrative", entity_id=str(resolved_id))
            return []

        entity_name = self._entity_context.name if self._entity_context else str(resolved_id)
        item = RetrievedItem.create(
            item_id=f"tool:narrative:{resolved_id}",
            item_type=ItemType.financial,
            text=result.content[:_TOOL_RESULT_MAX_CHARS],
            score=0.92,
            trust_weight=0.88,  # platform-curated narrative — high authority
            citation_meta=CitationMeta(
                title=f"Narrative: {entity_name}",
                url=None,
                source_name="narrative",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        return [item]

    async def _handle_get_entity_paths(
        self,
        tool_call: ToolUseBlock,
        entity_id: str | None = None,
        top_n: int = 5,
    ) -> list[RetrievedItem]:
        """Retrieve top-N multi-hop paths for an entity via S9 proxy."""
        if self._s7_intel is None:
            log.warning("tool_handler_missing_port", tool="get_entity_paths", port="s7_intel")
            return []

        resolved_id = self._resolve_intel_entity_id("get_entity_paths", entity_id)
        if resolved_id is None:
            return []

        top_n_clamped = max(1, min(int(top_n), 20))

        try:
            result = await asyncio.wait_for(
                self._s7_intel.get_entity_paths(resolved_id, top_n=top_n_clamped),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_paths", error=str(e))
            return []

        if not result.paths:
            log.warning("tool_no_data", tool="get_entity_paths", entity_id=str(resolved_id))
            return []

        entity_name = self._entity_context.name if self._entity_context else str(resolved_id)
        lines = [f"Top {len(result.paths)} relationship paths for {entity_name}:"]
        for i, path in enumerate(result.paths, 1):
            path_str = str(path)[:200]
            lines.append(f"  {i}. {path_str}")
        text = "\n".join(lines)

        item = RetrievedItem.create(
            item_id=f"tool:paths:{resolved_id}",
            item_type=ItemType.relation,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.85,
            trust_weight=0.82,
            citation_meta=CitationMeta(
                title=f"Paths: {entity_name}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        return [item]

    async def _handle_get_entity_health(
        self,
        tool_call: ToolUseBlock,
        entity_id: str | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve entity health score + key_metrics subset from intelligence bundle."""
        if self._s7_intel is None:
            log.warning("tool_handler_missing_port", tool="get_entity_health", port="s7_intel")
            return []

        resolved_id = self._resolve_intel_entity_id("get_entity_health", entity_id)
        if resolved_id is None:
            return []

        try:
            result = await asyncio.wait_for(
                self._s7_intel.get_entity_intelligence(resolved_id),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_health", error=str(e))
            return []

        if result is None:
            log.warning("tool_no_data", tool="get_entity_health", entity_id=str(resolved_id))
            return []

        entity_name = self._entity_context.name if self._entity_context else str(resolved_id)
        lines = [f"Health data for {entity_name}:"]
        if result.health_score is not None:
            lines.append(f"  Health score: {result.health_score:.2f}")
        if result.key_metrics:
            lines.append(f"  Key metrics: {result.key_metrics}")
        if result.source_distribution:
            lines.append(f"  Source distribution: {result.source_distribution}")
        text = "\n".join(lines)

        item = RetrievedItem.create(
            item_id=f"tool:health:{resolved_id}",
            item_type=ItemType.financial,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.85,
            citation_meta=CitationMeta(
                title=f"Health: {entity_name}",
                url=None,
                source_name="narrative",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        return [item]

    async def _handle_get_entity_intelligence(
        self,
        tool_call: ToolUseBlock,
        entity_id: str | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve the full intelligence bundle for an entity via S9 proxy."""
        if self._s7_intel is None:
            log.warning("tool_handler_missing_port", tool="get_entity_intelligence", port="s7_intel")
            return []

        resolved_id = self._resolve_intel_entity_id("get_entity_intelligence", entity_id)
        if resolved_id is None:
            return []

        try:
            result = await asyncio.wait_for(
                self._s7_intel.get_entity_intelligence(resolved_id),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_intelligence", error=str(e))
            return []

        if result is None:
            log.warning("tool_no_data", tool="get_entity_intelligence", entity_id=str(resolved_id))
            return []

        entity_name = self._entity_context.name if self._entity_context else str(resolved_id)
        sections = [f"Intelligence bundle for {entity_name}:"]
        if result.narrative:
            sections.append(f"\n## Narrative\n{result.narrative}")
        if result.health_score is not None:
            sections.append(f"\n## Health Score\n{result.health_score:.2f}")
        if result.key_metrics:
            sections.append(f"\n## Key Metrics\n{result.key_metrics}")
        if result.paths:
            paths_preview = "\n".join(f"  - {str(p)[:150]}" for p in result.paths[:5])
            sections.append(f"\n## Top Paths\n{paths_preview}")
        if result.relations_summary:
            sections.append(f"\n## Relations Summary\n{result.relations_summary}")
        text = "\n".join(sections)

        item = RetrievedItem.create(
            item_id=f"tool:intelligence:{resolved_id}",
            item_type=ItemType.financial,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.90,
            trust_weight=0.88,
            citation_meta=CitationMeta(
                title=f"Intelligence: {entity_name}",
                url=None,
                source_name="narrative",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        return [item]
