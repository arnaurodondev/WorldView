"""Intelligence tool handlers — knowledge graph, entity relations, claims, and events.

Covers tools backed by S7Port:
  - get_entity_graph          (egocentric graph)
  - traverse_graph            (multi-hop Cypher traversal)
  - search_entity_relations   (ANN relation search)
  - search_claims             (analyst claims)
  - search_events             (corporate events)
  - get_contradictions        (cross-source contradictions)

Narrative/intelligence bundle tools (S7IntelligencePort) live in narrative.py.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.pipeline.tool_executor import EntityContext, ToolUseBlock
    from rag_chat.application.ports.upstream_clients import S7Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000

# Allowlist of Cypher relationship type tokens accepted from LLM input.
# WHY: traverse_graph accepts a cypher_pattern string; we must guard against
# prompt injection — an adversarial user could inject arbitrary Cypher. We
# extract relationship type tokens (e.g. INVESTS_IN from [:INVESTS_IN]) and
# only allow known domain types. Unknown tokens are silently dropped.
_ALLOWED_CYPHER_REL_TYPES: frozenset[str] = frozenset(
    {
        "INVESTS_IN",
        "BOARD_MEMBER_OF",
        "SUBSIDIARY_OF",
        "COMPETES_WITH",
        "PARTNERSHIP",
        "ACQUIRED",
        "FOUNDER_OF",
        "SUPPLIES_TO",
        "REGULATES",
        "LISTED_ON",
    }
)


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-format date string to a UTC datetime; returns None on failure."""
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s).replace(tzinfo=UTC)
    except ValueError:
        return None


class IntelligenceHandler(ToolHandler):
    """Handles knowledge graph tools (get_entity_graph, traverse_graph, relations, claims, events, contradictions).

    All tools call S7Port (knowledge-graph service). Narrative/intelligence tools
    are handled by NarrativeHandler (handlers/narrative.py).
    """

    _HANDLED_TOOLS = frozenset(
        {
            "get_entity_graph",
            "traverse_graph",
            "search_entity_relations",
            "search_claims",
            "search_events",
            "get_contradictions",
        }
    )

    def __init__(
        self,
        s7: S7Port | None = None,
        entity_context: EntityContext | None = None,
        timeout: float = 5.0,
        # s7_intel is accepted but not used by IntelligenceHandler — narrative/
        # intelligence bundle tools live in NarrativeHandler (handlers/narrative.py).
        # Accepted here so ToolExecutorFactory can pass a uniform kwarg set to
        # all handlers without per-handler conditionals.
        s7_intel: object | None = None,
    ) -> None:
        self._s7 = s7
        self._entity_context = entity_context
        self._timeout = timeout
        # s7_intel intentionally unused; accepted to keep factory call uniform.

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        # Import ToolUseBlock only for the graph tools that pass it through.
        # WHY: the handler dispatcher no longer passes ToolUseBlock to execute();
        # a dummy stub is created here so the handler signatures remain unchanged.
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        _stub = ToolUseBlock(name=tool_name, input=args)

        if tool_name == "get_entity_graph":
            return await self._handle_get_entity_graph(_stub, **args)
        if tool_name == "traverse_graph":
            return await self._handle_traverse_graph(_stub, **args)
        if tool_name == "search_entity_relations":
            return await self._handle_search_entity_relations(_stub, **args)
        if tool_name == "search_claims":
            return await self._handle_search_claims(_stub, **args)
        if tool_name == "search_events":
            return await self._handle_search_events(_stub, **args)
        if tool_name == "get_contradictions":
            return await self._handle_get_contradictions(_stub, **args)
        raise ValueError(f"IntelligenceHandler cannot handle tool: {tool_name}")

    def _sanitize_cypher_pattern(self, pattern: str | None) -> str | None:
        """Allowlist-filter a Cypher rel-type pattern to guard against prompt injection.

        Extracts :REL_TYPE tokens and keeps only those in _ALLOWED_CYPHER_REL_TYPES.
        Returns None when no allowlisted tokens remain (traverse_graph skips pattern).
        """
        if pattern is None:
            return None
        tokens = re.findall(r":([A-Z_]+)", pattern)
        allowed = [t for t in tokens if t in _ALLOWED_CYPHER_REL_TYPES]
        if not allowed:
            log.warning("cypher_pattern_rejected", pattern=pattern[:100], reason="no_allowlisted_rel_types")
            return None
        return "[:" + "|:".join(allowed) + "]"

    def _require_context_entity(self, tool_name: str, entity_name: str) -> UUID | None:
        """Return entity_context.entity_id or log a warning and return None."""
        if self._entity_context is not None:
            return self._entity_context.entity_id
        log.warning(
            "tool_entity_unresolved",
            tool=tool_name,
            entity_name=entity_name,
            reason="no_entity_context_and_name_resolution_not_wired",
        )
        return None

    async def _resolve_entity_by_name(self, tool_name: str, entity_name: str) -> UUID | None:
        """Resolve entity_name to UUID via entity_context fuzzy-match or S7 alias search.

        Returns None and logs a warning when resolution fails.
        """
        assert self._s7 is not None  # callers must check self._s7 is not None first
        ctx_name_lower = self._entity_context.name.lower() if self._entity_context else ""
        name_lower = entity_name.lower()
        use_context = self._entity_context is not None and (
            name_lower in ctx_name_lower or ctx_name_lower in name_lower or name_lower == ctx_name_lower
        )
        if use_context and self._entity_context is not None:
            return self._entity_context.entity_id
        candidates = await self._s7.resolve_entity_by_name(entity_name, limit=3)
        if not candidates:
            log.warning("tool_entity_unresolved", tool=tool_name, entity_name=entity_name, reason="no_alias_match")
            return None
        try:
            entity_id = UUID(str(candidates[0]["entity_id"]))
        except (ValueError, KeyError):
            log.warning(
                "tool_entity_unresolved",
                tool=tool_name,
                entity_name=entity_name,
                reason="invalid_entity_id_in_candidate",
            )
            return None
        log.info(
            "tool_entity_resolved_by_name",
            tool=tool_name,
            entity_name=entity_name,
            resolved_entity_id=str(entity_id),
            alias_text=candidates[0].get("alias_text"),
            similarity=candidates[0].get("similarity"),
        )
        return entity_id

    async def _handle_get_entity_graph(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve egocentric knowledge graph via S7 (PLAN-0078 alias resolution)."""
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="get_entity_graph", port="s7")
            return []

        entity_id = await self._resolve_entity_by_name("get_entity_graph", entity_name)
        if entity_id is None:
            return []

        t0 = time.monotonic()
        try:
            graph = await asyncio.wait_for(
                self._s7.get_egocentric_graph(
                    entity_id=entity_id,
                    min_confidence=0.3,
                    limit=50 * depth,  # depth 1 → 50 edges, depth 2 → 100
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_entity_graph", error=str(e))
            return []

        if not graph.nodes and not graph.edges:
            log.warning("tool_no_data", tool="get_entity_graph", entity_name=entity_name)
            return []

        text = self._format_graph(entity_name, graph)

        item = RetrievedItem.create(
            item_id=f"tool:graph:{graph.entity_id}",
            item_type=ItemType.relation,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.85,
            trust_weight=0.80,
            citation_meta=CitationMeta(
                title=f"Knowledge graph: {entity_name}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        log.info(
            "tool_executed", tool="get_entity_graph", latency_ms=round((time.monotonic() - t0) * 1000), items_returned=1
        )
        return [item]

    async def _handle_traverse_graph(
        self,
        tool_call: ToolUseBlock,
        start_entity: str,
        target_entity: str | None = None,
        depth: int = 3,
        cypher_pattern: str | None = None,
    ) -> list[RetrievedItem]:
        """Execute multi-hop Cypher traversal via S7 (BP-459-A fix, injection guard)."""
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="traverse_graph", port="s7")
            return []

        # BUG-4 FIX: clamp depth to [1,4] — unclamped depth=100 is a DoS vector.
        raw_depth = int(depth)
        clamped_depth = min(max(raw_depth, 1), 4)
        if clamped_depth != raw_depth:
            log.warning("traverse_depth_clamped", requested=raw_depth, clamped=clamped_depth)

        # SECURITY: sanitize cypher pattern before forwarding
        safe_pattern = self._sanitize_cypher_pattern(cypher_pattern)

        # BP-459-A FIX: resolve source + target independently via alias search so
        # two-entity queries (e.g. "Apple → Anthropic") each get their own UUID.
        # entity_context is used only when start_entity name fuzzy-matches it.
        source_entity_id = await self._resolve_entity_by_name("traverse_graph", start_entity)
        if source_entity_id is None:
            return []

        # target_entity is always resolved via alias search (context holds ONE entity).
        target_entity_id: UUID | None = None
        if target_entity:
            target_entity_id = await self._resolve_entity_by_name("traverse_graph", target_entity)
            if target_entity_id is None:
                return []

        # BP-459-B FIX: source_id/target_id keys route to /graph/cypher/path or /neighborhood.
        params: dict[str, Any] = {
            "source_id": str(source_entity_id),
            "max_hops": clamped_depth,
        }
        if target_entity_id is not None:
            params["target_id"] = str(target_entity_id)

        if target_entity:
            cypher = (
                f"MATCH p=(a:entity {{entity_id: $source}})-[r{safe_pattern or ''}*1..{clamped_depth}]-"
                f"(b:entity {{entity_id: $target}}) RETURN p LIMIT 10"
            )
        else:
            cypher = (
                f"MATCH p=(a:entity {{entity_id: $source}})-[r{safe_pattern or ''}*1..{clamped_depth}]-() "
                f"RETURN p LIMIT 20"
            )

        t0 = time.monotonic()
        try:
            paths = await asyncio.wait_for(
                self._s7.cypher_traverse(cypher=cypher, params=params, max_results=20),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="traverse_graph", error=str(e))
            return []

        if not paths:
            log.warning("tool_no_data", tool="traverse_graph", start_entity=start_entity)
            return []

        text = f"Graph traversal: {start_entity}"
        if target_entity:
            text += f" → {target_entity}"
        text += f" (depth {clamped_depth})\n"
        text += "\n".join(str(p) for p in paths[:20])

        item = RetrievedItem.create(
            item_id=f"tool:traverse:{start_entity}",
            item_type=ItemType.cypher_path,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.80,
            trust_weight=0.75,
            citation_meta=CitationMeta(
                title=f"Graph traversal: {start_entity}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=start_entity,
            ),
        )
        log.info(
            "tool_executed", tool="traverse_graph", latency_ms=round((time.monotonic() - t0) * 1000), items_returned=1
        )
        return [item]

    async def _handle_search_entity_relations(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        relation_type: str | None = None,
        min_confidence: float = 0.6,
        limit: int = 15,
    ) -> list[RetrievedItem]:
        """Search relation triplets for an entity via S7 ANN relation search.

        S7.search_relations takes an embedding + entity_ids — not a text query.
        We use entity_context.entity_id when available; otherwise degrade to [].
        relation_type filtering is accepted from the LLM but not forwarded to
        search_relations because S7 v1 filters by embedding ANN, not type literal.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_entity_relations", port="s7")
            return []
        # PLAN-0093 E-3 T-E-3-01: route through _resolve_entity_by_name so the
        # tool works even without a scoped entity_context — previously this
        # silently returned [] for any out-of-scope entity (F-RAG-003).
        entity_id = await self._resolve_entity_by_name("search_entity_relations", entity_name)
        if entity_id is None:
            return []
        # Use a zero embedding as placeholder — S7 will fall back to entity_id filter
        placeholder_embedding: list[float] = [0.0] * 1024

        t0 = time.monotonic()
        try:
            relations = await asyncio.wait_for(
                self._s7.search_relations(
                    embedding=placeholder_embedding,
                    entity_ids=[entity_id],
                    top_k=limit,
                    min_confidence=min_confidence,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_entity_relations", error=str(e))
            return []

        if not relations:
            log.warning("tool_no_data", tool="search_entity_relations", entity_name=entity_name)
            return []

        lines = [f"Relations for {entity_name}:"]
        for r in relations:
            lines.append(
                f"  {r.subject} --[{r.relation_type}]--> {r.object} (confidence={r.confidence:.2f}): {r.summary}"
            )

        text = "\n".join(lines)
        item = RetrievedItem.create(
            item_id=f"tool:relations:{entity_id}",
            item_type=ItemType.relation,
            text=text[:_TOOL_RESULT_MAX_CHARS],
            score=0.82,
            trust_weight=0.80,
            citation_meta=CitationMeta(
                title=f"Relations: {entity_name}",
                url=None,
                source_name="knowledge_graph",
                published_at=None,
                entity_name=entity_name,
            ),
        )
        log.info(
            "tool_executed",
            tool="search_entity_relations",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=1,
        )
        return [item]

    async def _handle_search_claims(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        claim_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RetrievedItem]:
        """Search analyst claims for an entity via S7.search_claims.

        Returns one RetrievedItem per claim, up to 20. Returns [] on any error.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_claims", port="s7")
            return []
        # PLAN-0093 E-3 T-E-3-01: route through _resolve_entity_by_name so
        # claims work without a scoped entity_context (F-RAG-003).
        entity_id = await self._resolve_entity_by_name("search_claims", entity_name)
        if entity_id is None:
            return []
        claim_types = [claim_type] if claim_type else None

        t0 = time.monotonic()
        try:
            claims = await asyncio.wait_for(
                self._s7.search_claims(
                    entity_ids=[entity_id],
                    claim_types=claim_types,
                    date_from=_parse_dt(date_from),
                    date_to=_parse_dt(date_to),
                    top_k=20,
                    min_confidence=0.45,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_claims", error=str(e))
            return []

        if not claims:
            log.warning("tool_no_data", tool="search_claims", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for claim in claims:
            text = (
                f"[{claim.claim_type}] ({claim.polarity}) "
                f"{claim.claim_text} "
                f"(confidence={claim.extraction_confidence:.2f})"
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:claim:{claim.claim_id}",
                    item_type=ItemType.claim,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=claim.extraction_confidence,
                    trust_weight=0.75,
                    extraction_confidence=claim.extraction_confidence,
                    citation_meta=CitationMeta(
                        title=f"Claim: {claim.claim_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="search_claims",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    async def _handle_search_events(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RetrievedItem]:
        """Search structured corporate events for an entity via S7.search_events.

        date_from and date_to are forwarded to S7 to enable timeline filtering.
        Returns [] on any error (graceful degradation).
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="search_events", port="s7")
            return []
        # PLAN-0093 E-3 T-E-3-01: route through _resolve_entity_by_name so
        # events work without a scoped entity_context (F-RAG-003).
        entity_id = await self._resolve_entity_by_name("search_events", entity_name)
        if entity_id is None:
            return []
        event_types = [event_type] if event_type else None

        t0 = time.monotonic()
        try:
            events = await asyncio.wait_for(
                self._s7.search_events(
                    entity_ids=[entity_id],
                    event_types=event_types,
                    date_from=_parse_dt(date_from),
                    date_to=_parse_dt(date_to),
                    top_k=20,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_events", error=str(e))
            return []

        if not events:
            log.warning("tool_no_data", tool="search_events", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for event in events:
            text = (
                f"[{event.event_type}]"
                + (f" ({event.event_subtype})" if event.event_subtype else "")
                + (f" on {event.event_date}" if event.event_date else "")
                + f": {event.event_text}"
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:event:{event.event_id}",
                    item_type=ItemType.event,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=event.extraction_confidence,
                    trust_weight=0.78,
                    citation_meta=CitationMeta(
                        title=f"Event: {event.event_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="search_events",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    async def _handle_get_contradictions(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        confidence_threshold: float = 0.5,
    ) -> list[RetrievedItem]:
        """Retrieve analyst claim contradictions for an entity via S7.get_contradictions.

        Returns one RetrievedItem per contradiction pair. Returns [] on any error.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="get_contradictions", port="s7")
            return []
        # PLAN-0093 E-3 T-E-3-01: route through _resolve_entity_by_name so
        # contradictions work without a scoped entity_context (F-RAG-003).
        entity_id = await self._resolve_entity_by_name("get_contradictions", entity_name)
        if entity_id is None:
            return []

        t0 = time.monotonic()
        try:
            contradictions = await asyncio.wait_for(
                self._s7.get_contradictions(entity_id=entity_id, top_k=10),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_contradictions", error=str(e))
            return []

        # Filter by confidence_threshold (S7 doesn't accept threshold param in v1)
        contradictions = [c for c in contradictions if c.strength >= confidence_threshold]

        if not contradictions:
            log.warning("tool_no_data", tool="get_contradictions", entity_name=entity_name)
            return []

        items: list[RetrievedItem] = []
        for contradiction in contradictions:
            sides_text = ""
            for i, side in enumerate(contradiction.sides, 1):
                sides_text += f"\n  Side {i}: {side}"
            text = (
                f"[CONTRADICTION: {contradiction.claim_type}] "
                f"strength={contradiction.strength:.2f} "
                f"detected={contradiction.detected_at}" + sides_text
            )
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:contradiction:{contradiction.claim_type}:{entity_id}",
                    item_type=ItemType.claim,
                    text=text[:_TOOL_RESULT_MAX_CHARS],
                    score=contradiction.strength,
                    trust_weight=0.70,
                    citation_meta=CitationMeta(
                        title=f"Contradiction: {contradiction.claim_type}",
                        url=None,
                        source_name="knowledge_graph",
                        published_at=None,
                        entity_name=entity_name,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_contradictions",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    def _format_graph(self, entity_name: str, graph: Any) -> str:
        """Format an EgocentricGraph as compact text for LLM context injection."""
        lines = [f"Knowledge graph: {entity_name} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)"]
        if graph.nodes:
            lines.append("Nodes:")
            for node in graph.nodes[:20]:
                lines.append(f"  {node}")
        if graph.edges:
            lines.append("Edges:")
            for edge in graph.edges[:30]:
                lines.append(f"  {edge}")
        return "\n".join(lines)
