"""ToolExecutor — dispatches LLM tool_use blocks to S3/S6/S7/S1/S10 Port handlers.

Plans: PLAN-0066 Wave H, PLAN-0067 Wave W11-2, PLAN-0082 Wave A.

Architecture notes:
- R25: ToolExecutor depends on port Protocols (S3Port, S6Port, S7Port, S1Port), never concrete adapters
- R30: ToolExecutorFactory holds shared collaborators; ToolExecutor is per-request (has auth)
- Structlog only (STANDARDS.md §5) — never stdlib logging
- BP-025: all upstream calls wrapped in asyncio.wait_for(timeout=N)
- Tool results truncated to _TOOL_RESULT_MAX_CHARS=4000 to prevent context overflow

Structured logging conventions:
- tool_executed: success path, carries tool name + latency_ms + items_returned
- tool_failed: any exception from a handler (error swallowed, [] returned)
- unknown_tool_name: LLM emitted a tool name not in the registry (hallucination guard)
- tool_no_data: handler received empty response from upstream (not found / no data)
- tool_handler_missing_port: handler called but required port is None (graceful degradation)
- cypher_pattern_rejected: traverse_graph received a disallowed cypher pattern (injection guard)

PLAN-0067 §0 additions:
- EntityContext: entity scope injected at request time (M-1)
- ToolCallProvenance: provenance for citation audit (I-6)
- ToolExecutorFactory: singleton wired in DI container; ToolExecutor is per-request

IMPORTANT — two ToolUseBlock variants:
- The LOCAL ToolUseBlock (defined here) uses ``tool_use_id`` (string, default "").
  Existing S3 handlers (get_price_history, get_fundamentals_history) use this.
- The CANONICAL ToolUseBlock from libs/tools/src/tools/types.py uses ``id``.
  New handlers in this file accept the LOCAL variant so the existing execute()
  dispatcher works uniformly. The canonical variant is used by the LLM adapter layer.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, date
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

# Import from libs/tools (must be on PYTHONPATH — added in Dockerfile, BP-181)
from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

if TYPE_CHECKING:
    # Port interfaces — annotation-only to satisfy TC001 and maintain R25 compliance.
    from rag_chat.application.ports.brief_archive import BriefArchivePort
    from rag_chat.application.ports.upstream_clients import (
        S1Port,
        S3BriefPort,
        S3Port,
        S6Port,
        S7IntelligencePort,
        S7Port,
        S10Port,
    )

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
# WHY: OHLCV data for 252 trading days at ~50 chars/row ≈ 12,600 chars — well
# beyond most context windows. Cap at 4000 to stay within budget.
_TOOL_RESULT_MAX_CHARS = 4000

# Maximum simultaneous tool calls dispatched from a single LLM turn.
# Prevents runaway tool use if the LLM emits many calls at once.
_MAX_CONCURRENT_TOOLS = 5

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


# ── Domain helpers ─────────────────────────────────────────────────────────────


@dataclass
class ToolUseBlock:
    """Parsed representation of a single tool_use block from the LLM response.

    The LLM emits JSON blocks shaped like:
        {"type": "tool_use", "name": "get_price_history",
         "input": {"ticker": "AAPL", "from_date": "...", ...}}

    tool_use_id is optional — not all providers set it for the MVP.

    NOTE: this is the LOCAL variant (used throughout ToolExecutor dispatch).
    The canonical variant in libs/tools/src/tools/types.py uses ``id`` instead
    of ``tool_use_id``. Both exist because the adapter layer pre-dates PLAN-0067.
    """

    name: str
    input: dict[str, Any]
    tool_use_id: str = ""


@dataclass
class EntityContext:
    """Entity scope injected at request time (PLAN-0067 §0 M-1).

    Tool handlers that take entity-scoped queries auto-inject
    entity_ids=[entity_context.entity_id] so the LLM need not pass UUIDs.
    Cross-entity tools check entity_context is None and fall back to
    name-based resolution.
    """

    entity_id: UUID
    ticker: str
    name: str


@dataclass
class ToolCallProvenance:
    """Provenance for citation audit (PLAN-0067 §0 I-6).

    Attached to each RetrievedItem produced via tool-use so downstream
    citation rendering can link items back to the tool call that produced them.
    Stored separately from RetrievedItem to avoid polluting the domain entity.
    """

    tool_name: str
    tool_input: dict[str, Any]
    call_id: str


# ── Factory ────────────────────────────────────────────────────────────────────


class ToolExecutorFactory:
    """Singleton — wired once into the DI container at app startup.

    Holds all shared collaborators (registry, port references, default timeout).
    Call for_request() to get a per-request ToolExecutor with auth context bound.

    WHY singleton + per-request split: shared collaborators (HTTP clients, registry)
    are expensive to construct on every request. Auth context (user_id, tenant_id,
    internal_jwt) is per-request and must not bleed between requests.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        s3: S3Port,
        s6: S6Port | None = None,
        s7: S7Port | None = None,
        s7_intel: S7IntelligencePort | None = None,
        s1: S1Port | None = None,
        s3_brief: S3BriefPort | None = None,
        brief_archive: BriefArchivePort | None = None,
        s10: S10Port | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._registry = registry
        self._s3 = s3
        self._s6 = s6
        self._s7 = s7
        self._s7_intel = s7_intel
        self._s1 = s1
        self._s3_brief = s3_brief
        self._brief_archive = brief_archive
        self._s10 = s10
        self._timeout = timeout

    def for_request(
        self,
        *,
        user_id: UUID | None,
        tenant_id: UUID | None,
        internal_jwt: str | None,
        entity_context: EntityContext | None = None,
    ) -> ToolExecutor:
        """Return a per-request ToolExecutor with auth context bound.

        Args:
            user_id: Resolved from X-Internal-JWT by InternalJWTMiddleware.
            tenant_id: Resolved from X-Internal-JWT by InternalJWTMiddleware.
            internal_jwt: Raw JWT string for forwarding to S1 portfolio endpoint.
            entity_context: Optional entity scope for entity-first queries (M-1).
        """
        return ToolExecutor(
            registry=self._registry,
            s3=self._s3,
            s6=self._s6,
            s7=self._s7,
            s7_intel=self._s7_intel,
            s1=self._s1,
            s3_brief=self._s3_brief,
            brief_archive=self._brief_archive,
            s10=self._s10,
            user_id=user_id,
            tenant_id=tenant_id,
            internal_jwt=internal_jwt,
            entity_context=entity_context,
            timeout=self._timeout,
        )


# ── Executor ───────────────────────────────────────────────────────────────────


class ToolExecutor:
    """Executes tool_use blocks emitted by the LLM against upstream port adapters.

    Design constraints:
    - R25: depends only on port Protocol interfaces (never concrete infra adapters)
    - All errors are swallowed and logged; callers receive None/[] on failure
    - execute_all() uses asyncio.gather for concurrent execution
    - New ports (s6, s7, s1) default to None so existing tests need no changes (R19)
    """

    def __init__(
        self,
        registry: ToolRegistry,
        s3: S3Port,
        s6: S6Port | None = None,
        s7: S7Port | None = None,
        s7_intel: S7IntelligencePort | None = None,
        s1: S1Port | None = None,
        s3_brief: S3BriefPort | None = None,
        brief_archive: BriefArchivePort | None = None,
        s10: S10Port | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        internal_jwt: str | None = None,
        entity_context: EntityContext | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._registry = registry
        self._s3 = s3
        self._s6 = s6
        self._s7 = s7
        self._s7_intel = s7_intel
        self._s1 = s1
        self._s3_brief = s3_brief
        self._brief_archive = brief_archive
        self._s10 = s10
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._internal_jwt = internal_jwt
        self._entity_context = entity_context
        self._timeout = timeout
        # PLAN-0082 Wave B: per-session rate limit for create_alert (≤5/session).
        # WHY session limit: the LLM could in principle loop and emit many create_alert
        # calls in a single conversation turn. Limiting to 5 prevents runaway alert
        # creation and keeps the UX intention clear — this is a deliberate action,
        # not a background task.
        self._create_alert_count: int = 0

    async def execute(self, tool_call: ToolUseBlock) -> RetrievedItem | list[RetrievedItem] | None:
        """Execute a single tool call and return a RetrievedItem, list, or None.

        Multi-result tools (search_documents, get_entity_graph, etc.) return a list.
        Single-result tools (get_price_history, get_fundamentals_history) return one item.
        Returns None on any error (unknown name, empty data, network failure) so
        the orchestrator can apply the all-tools-failed guard safely.
        """
        spec = self._registry.get_spec(tool_call.name)
        if spec is None:
            # LLM hallucinated a tool name or called a deregistered tool
            log.warning("unknown_tool_name", name=tool_call.name)
            return None

        t0 = time.monotonic()
        try:
            result: RetrievedItem | list[RetrievedItem] | None
            if tool_call.name == "get_price_history":
                result = await self._handle_get_price_history(**tool_call.input)
            elif tool_call.name == "get_fundamentals_history":
                result = await self._handle_get_fundamentals_history(**tool_call.input)
            elif tool_call.name == "search_documents":
                result = await self._handle_search_documents(tool_call, **tool_call.input)
            elif tool_call.name == "get_entity_graph":
                result = await self._handle_get_entity_graph(tool_call, **tool_call.input)
            elif tool_call.name == "traverse_graph":
                result = await self._handle_traverse_graph(tool_call, **tool_call.input)
            elif tool_call.name == "search_entity_relations":
                result = await self._handle_search_entity_relations(tool_call, **tool_call.input)
            elif tool_call.name == "search_claims":
                result = await self._handle_search_claims(tool_call, **tool_call.input)
            elif tool_call.name == "search_events":
                result = await self._handle_search_events(tool_call, **tool_call.input)
            elif tool_call.name == "get_contradictions":
                result = await self._handle_get_contradictions(tool_call, **tool_call.input)
            elif tool_call.name == "get_portfolio_context":
                result = await self._handle_get_portfolio_context(tool_call)
            elif tool_call.name == "get_entity_narrative":
                result = await self._handle_get_entity_narrative(tool_call, **tool_call.input)
            elif tool_call.name == "get_entity_paths":
                result = await self._handle_get_entity_paths(tool_call, **tool_call.input)
            elif tool_call.name == "get_entity_health":
                result = await self._handle_get_entity_health(tool_call, **tool_call.input)
            elif tool_call.name == "get_entity_intelligence":
                result = await self._handle_get_entity_intelligence(tool_call, **tool_call.input)
            elif tool_call.name == "get_morning_brief":
                result = await self._handle_get_morning_brief(tool_call)
            elif tool_call.name == "compare_entities":
                result = await self._handle_compare_entities(tool_call, **tool_call.input)
            elif tool_call.name == "screen_universe":
                result = await self._handle_screen_universe(tool_call, **tool_call.input)
            elif tool_call.name == "get_market_movers":
                result = await self._handle_get_market_movers(tool_call, **tool_call.input)
            elif tool_call.name == "get_economic_calendar":
                result = await self._handle_get_economic_calendar(tool_call, **tool_call.input)
            elif tool_call.name == "get_earnings_calendar":
                result = await self._handle_get_earnings_calendar(tool_call, **tool_call.input)
            elif tool_call.name == "get_alerts":
                result = await self._handle_get_alerts(tool_call)
            elif tool_call.name == "create_alert":
                result = await self._handle_create_alert(tool_call, **tool_call.input)
            else:
                # Registry had the spec but we have no handler — shouldn't happen
                # if build_default_registry() is used; guard logs the gap.
                log.warning("unknown_tool_name", name=tool_call.name)
                return None

            latency_ms = round((time.monotonic() - t0) * 1000)
            items_returned = len(result) if isinstance(result, list) else (1 if result is not None else 0)
            log.info(
                "tool_executed",
                tool=tool_call.name,
                latency_ms=latency_ms,
                items_returned=items_returned,
            )
            return result
        except Exception as exc:
            log.warning("tool_failed", tool=tool_call.name, error=str(exc))
            return None

    async def execute_all(self, tool_calls: list[ToolUseBlock]) -> list[RetrievedItem | list[RetrievedItem] | None]:
        """Execute all tool calls concurrently, capped at _MAX_CONCURRENT_TOOLS.

        WHY asyncio.gather: tool calls are independent — parallel execution
        minimises total latency (both S3 calls run in ~150ms instead of ~300ms).
        """
        capped = tool_calls[:_MAX_CONCURRENT_TOOLS]
        return list(await asyncio.gather(*[self.execute(tc) for tc in capped]))

    # ── Cypher injection guard ────────────────────────────────────────────────

    def _sanitize_cypher_pattern(self, pattern: str | None) -> str | None:
        """Validate and sanitize a cypher relationship pattern from LLM input.

        Extracts :REL_TYPE tokens from a pattern like '[:INVESTS_IN|:BOARD_MEMBER_OF]'
        and keeps only tokens that appear in _ALLOWED_CYPHER_REL_TYPES.
        Returns None if no allowlisted tokens are found (logs a warning).

        WHY: traverse_graph passes the pattern to S7.cypher_traverse(). An
        adversarial user could inject arbitrary Cypher via this field to exfiltrate
        data or cause unintended graph mutations. Allowlisting rel types is the
        minimal guard; the S7 implementation adds further validation.
        """
        if pattern is None:
            return None
        tokens = re.findall(r":([A-Z_]+)", pattern)
        allowed = [t for t in tokens if t in _ALLOWED_CYPHER_REL_TYPES]
        if not allowed:
            log.warning(
                "cypher_pattern_rejected",
                pattern=pattern[:100],
                reason="no_allowlisted_rel_types",
            )
            return None
        return "[:" + "|:".join(allowed) + "]"

    # ── S3 handlers (price + fundamentals) ───────────────────────────────────

    async def _handle_get_price_history(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        interval: str = "week",
    ) -> RetrievedItem | None:
        """Fetch OHLCV bars and format as a markdown table RetrievedItem."""
        # Parse and validate date strings before hitting S3
        try:
            _from = date.fromisoformat(from_date)
            _to = date.fromisoformat(to_date)
        except ValueError:
            log.warning(
                "tool_invalid_dates",
                tool="get_price_history",
                from_date=from_date,
                to_date=to_date,
            )
            return None

        # BP-025: wrap S3 call with timeout to prevent long tail latency
        bars = await asyncio.wait_for(
            self._s3.get_ohlcv_range(
                ticker=ticker,
                from_date=_from,
                to_date=_to,
                interval=interval,
            ),
            timeout=self._timeout,
        )
        if not bars:
            log.warning("tool_no_data", tool="get_price_history", ticker=ticker)
            return None

        table = self._format_price_table(ticker, from_date, to_date, interval, bars)
        # CRITICAL: field is `text` NOT `content` (N-7); use .create() factory
        # (never direct construction — fusion_score invariant enforced in __post_init__)
        return RetrievedItem.create(
            item_id=f"tool:price_history:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
        )

    async def _handle_get_fundamentals_history(
        self,
        ticker: str,
        periods: int = 8,
    ) -> RetrievedItem | None:
        """Fetch quarterly fundamentals and format as a markdown table RetrievedItem."""
        data = await asyncio.wait_for(
            self._s3.get_fundamentals_history(ticker=ticker, periods=periods),
            timeout=self._timeout,
        )
        if not data:
            log.warning("tool_no_data", tool="get_fundamentals_history", ticker=ticker)
            return None

        table = self._format_fundamentals_table(ticker, data)
        return RetrievedItem.create(
            item_id=f"tool:fundamentals:{ticker}",
            item_type=ItemType.financial,
            text=table[:_TOOL_RESULT_MAX_CHARS],
            score=0.88,
            trust_weight=0.90,
        )

    # ── S6 handlers (document search) ────────────────────────────────────────

    async def _handle_search_documents(
        self,
        tool_call: ToolUseBlock,
        query: str,
        entity_tickers: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        source_types: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Search document corpus via S6 hybrid BM25+ANN retrieval.

        entity_tickers is accepted from the LLM but not yet forwarded to S6 —
        entity resolution by ticker is PLAN-0078. A TODO comment marks the gap.

        Returns up to 20 RetrievedItem objects, each truncated to _TOOL_RESULT_MAX_CHARS.
        Returns [] if S6 port is absent or any error occurs (graceful degradation).
        """
        if self._s6 is None:
            log.warning("tool_handler_missing_port", tool="search_documents", port="s6")
            return []

        # BUG-2 FIX: ToolUseBlock from libs/tools/types.py uses `.id`; the LOCAL
        # ToolUseBlock (defined in this file) uses `.tool_use_id`.  Use getattr
        # with fallback to handle both variants without breaking existing tests.
        _call_id = getattr(tool_call, "id", None) or getattr(tool_call, "tool_use_id", "") or ""

        # Build provenance record for citation audit (PLAN-0067 §0 I-6)
        _provenance = ToolCallProvenance(
            tool_name="search_documents",
            tool_input=tool_call.input,
            call_id=_call_id,
        )

        # Parse optional date strings into datetime objects (S6 expects datetime | None)
        from datetime import datetime

        from rag_chat.application.ports.upstream_clients import ChunkSearchRequest

        def _parse_dt(s: str | None) -> datetime | None:
            if s is None:
                return None
            try:
                return datetime.fromisoformat(s).replace(tzinfo=UTC)
            except ValueError:
                log.warning("tool_invalid_date", tool="search_documents", value=s)
                return None

        request = ChunkSearchRequest(
            query_text=query,
            top_k=20,
            search_type="hybrid",
            date_from=_parse_dt(date_from),
            date_to=_parse_dt(date_to),
            source_types=source_types or [],
            # TODO(PLAN-0078): pass entity_ids=resolved_entity_ids once ChunkSearchRequest
            # entity ticker→id resolution is wired. Currently entity_tickers is accepted
            # from the LLM but silently ignored here.
        )

        try:
            results = await asyncio.wait_for(
                self._s6.search_chunks(request),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="search_documents", error=str(e))
            return []

        items: list[RetrievedItem] = []
        for result in results[:20]:
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:chunk:{result.chunk_id}",
                    item_type=ItemType.chunk,
                    text=result.text[:_TOOL_RESULT_MAX_CHARS],
                    score=result.score,
                    trust_weight=0.80,
                    source_type=result.source_type,
                    published_at=result.published_at,
                    citation_meta=CitationMeta(
                        title=result.title,
                        url=result.url,
                        source_name=result.source_name,
                        published_at=result.published_at,
                        entity_name=None,
                    ),
                )
            )

        # BUG-5 FIX: do NOT emit tool_executed here — the outer execute() dispatcher
        # already emits tool_executed after the handler returns.  Double-logging this
        # event produced two identical log lines per search_documents call.
        return items

    # ── S7 graph handlers ─────────────────────────────────────────────────────

    async def _handle_get_entity_graph(
        self,
        tool_call: ToolUseBlock,
        entity_name: str,
        depth: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Retrieve egocentric knowledge graph for an entity via S7.

        If entity_context is set (entity-first request), uses entity_context.entity_id
        directly without name resolution. Otherwise requires entity_context — returns []
        with a warning if neither is available (name-based entity resolution is PLAN-0078).

        relation_types filtering is accepted from the LLM but not yet forwarded to
        get_egocentric_graph — the S7 v1 API filters by confidence only.
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="get_entity_graph", port="s7")
            return []

        # Resolve entity_id: use injected context if available
        entity_id: UUID | None = None
        if self._entity_context is not None:
            entity_id = self._entity_context.entity_id
        else:
            # Name-based resolution not yet wired (PLAN-0078); log and degrade.
            log.warning(
                "tool_entity_unresolved",
                tool="get_entity_graph",
                entity_name=entity_name,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
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

        # Format graph as compact text for LLM context injection
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
            "tool_executed",
            tool="get_entity_graph",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=1,
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
        """Execute multi-hop Cypher traversal via S7.

        cypher_pattern is sanitized through the allowlist before forwarding to S7
        to guard against prompt injection (see _sanitize_cypher_pattern).
        """
        if self._s7 is None:
            log.warning("tool_handler_missing_port", tool="traverse_graph", port="s7")
            return []

        # BUG-4 FIX: clamp LLM-supplied depth to [1, 4] before interpolating into
        # the traversal params.  An unclamped depth=100 causes expensive graph
        # scans and could be used to DoS the knowledge-graph service.
        raw_depth = int(depth)
        clamped_depth = min(max(raw_depth, 1), 4)
        if clamped_depth != raw_depth:
            log.warning(
                "traverse_depth_clamped",
                requested=raw_depth,
                clamped=clamped_depth,
            )

        # SECURITY: sanitize cypher pattern before forwarding
        safe_pattern = self._sanitize_cypher_pattern(cypher_pattern)

        # BUG-3 FIX: S7Client.cypher_traverse() reads params.get("id", "") to get
        # the anchor entity UUID for the /api/v1/graph/cypher/neighborhood endpoint.
        # The old code passed {"start": ..., "target": ...} which was silently ignored,
        # causing the traversal to always return [] (entity_id="").
        #
        # Resolution:
        # - When entity_context is available, use entity_context.entity_id as "id".
        # - When entity_context is absent, we cannot resolve start_entity to a UUID
        #   without an S6/S7 lookup — degrade gracefully to [] (PLAN-0078 will add
        #   name-based resolution).
        #
        # The cypher string is still passed but S7 currently ignores it (the S7
        # neighborhood endpoint uses max_hops/min_confidence instead).  It is kept
        # for forward-compatibility when S7 adds full Cypher execution.
        if self._entity_context is not None:
            entity_id_str = str(self._entity_context.entity_id)
        else:
            log.warning(
                "tool_entity_unresolved",
                tool="traverse_graph",
                start_entity=start_entity,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
            return []

        if target_entity:
            cypher = (
                f"MATCH p=(a {{name: $start}})-[r{safe_pattern or ''}*1..{clamped_depth}]-"
                f"(b {{name: $target}}) RETURN p LIMIT 10"
            )
        else:
            cypher = f"MATCH p=(a {{name: $start}})-[r{safe_pattern or ''}*1..{clamped_depth}]-() RETURN p LIMIT 20"

        # Pass entity_id under "id" key as expected by S7Client.cypher_traverse()
        params: dict[str, Any] = {"id": entity_id_str}

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
            "tool_executed",
            tool="traverse_graph",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=1,
        )
        return [item]

    # ── S7 signal handlers ────────────────────────────────────────────────────

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

        entity_id: UUID | None = None
        if self._entity_context is not None:
            entity_id = self._entity_context.entity_id
        else:
            log.warning(
                "tool_entity_unresolved",
                tool="search_entity_relations",
                entity_name=entity_name,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
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

        entity_id: UUID | None = None
        if self._entity_context is not None:
            entity_id = self._entity_context.entity_id
        else:
            log.warning(
                "tool_entity_unresolved",
                tool="search_claims",
                entity_name=entity_name,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
            return []

        from datetime import datetime

        def _parse_dt(s: str | None) -> datetime | None:
            if s is None:
                return None
            try:
                return datetime.fromisoformat(s).replace(tzinfo=UTC)
            except ValueError:
                return None

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

        entity_id: UUID | None = None
        if self._entity_context is not None:
            entity_id = self._entity_context.entity_id
        else:
            log.warning(
                "tool_entity_unresolved",
                tool="search_events",
                entity_name=entity_name,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
            return []

        from datetime import datetime

        def _parse_dt(s: str | None) -> datetime | None:
            if s is None:
                return None
            try:
                return datetime.fromisoformat(s).replace(tzinfo=UTC)
            except ValueError:
                return None

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

        entity_id: UUID | None = None
        if self._entity_context is not None:
            entity_id = self._entity_context.entity_id
        else:
            log.warning(
                "tool_entity_unresolved",
                tool="get_contradictions",
                entity_name=entity_name,
                reason="no_entity_context_and_name_resolution_not_wired",
            )
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

    # ── S1 portfolio handler ──────────────────────────────────────────────────

    async def _handle_get_portfolio_context(
        self,
        tool_call: ToolUseBlock,
    ) -> list[RetrievedItem]:
        """Retrieve portfolio holdings + watchlist for the authenticated user via S1.

        PRIVACY: log MUST NOT include tickers, values, or holding identifiers.
        Only holding_count and watchlist_count are logged (safe aggregate metrics).

        Returns [] for anonymous sessions (user_id is None) or on any error.
        """
        if self._user_id is None:
            # Anonymous session — portfolio tool cannot be used without auth
            log.warning("tool_no_auth", tool="get_portfolio_context", reason="user_id_none")
            return []

        if self._s1 is None:
            log.warning("tool_handler_missing_port", tool="get_portfolio_context", port="s1")
            return []

        if self._tenant_id is None:
            log.warning("tool_no_auth", tool="get_portfolio_context", reason="tenant_id_none")
            return []

        t0 = time.monotonic()
        try:
            context = await asyncio.wait_for(
                self._s1.get_portfolio_context(
                    user_id=self._user_id,
                    tenant_id=self._tenant_id,
                    x_internal_token=self._internal_jwt or "",
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_portfolio_context", error=str(e))
            return []

        if context is None:
            log.warning("tool_no_data", tool="get_portfolio_context")
            return []

        # Format holdings and watchlist as compact text for LLM context injection.
        # PRIVACY: we format only generic field names; the full context.holdings dicts
        # may contain sensitive values but they are passed to the LLM, not logged.
        lines = [f"Portfolio context for user (tenant={self._tenant_id}):"]
        if context.holdings:
            lines.append(f"Holdings ({len(context.holdings)} positions):")
            for h in context.holdings:
                lines.append(f"  {h}")
        if context.watchlist:
            lines.append(f"Watchlist ({len(context.watchlist)} items):")
            for w in context.watchlist:
                lines.append(f"  {w}")
        text = "\n".join(lines)

        # PRIVACY: log only counts — never tickers, quantities, or dollar values
        log.info(
            "tool_executed",
            tool="get_portfolio_context",
            latency_ms=round((time.monotonic() - t0) * 1000),
            holding_count=len(context.holdings),
            watchlist_count=len(context.watchlist),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:portfolio:{self._user_id}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=1.0,  # user's own data — always maximally relevant
                trust_weight=0.95,
                citation_meta=CitationMeta(
                    title="Portfolio context",
                    url=None,
                    source_name="portfolio",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    # ── S7 Intelligence handlers (PLAN-0080 Wave A) ───────────────────────────

    def _resolve_intel_entity_id(self, tool_name: str, llm_entity_id: str | None) -> UUID | None:
        """Resolve entity_id for intelligence tools, enforcing EntityContext scope (M-1).

        WHY: When the executor is bound to an entity scope (entity_context is set),
        all intelligence tools MUST use that entity_id regardless of what the LLM
        passes. This prevents the LLM from inadvertently leaking cross-entity data
        and ensures tool results are always scoped to the active entity page.
        If the LLM passes a different entity_id, we silently override it and log
        a warning (M-1 compliance, not a hard error — the LLM may just be confused).
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

    # ── Catalog tool handlers (PLAN-0081 Wave A) ─────────────────────────────

    async def _handle_get_morning_brief(
        self,
        tool_call: ToolUseBlock,
    ) -> list[RetrievedItem]:
        """Return the user's latest morning brief from the DB archive (PLAN-0081 Wave A).

        R27: no UnitOfWork — uses BriefArchivePort.get_latest() via read adapter.
        R9: returns [] on any error or missing data.
        PRIVACY: headline and lead are passed to LLM context; sections_json may contain
        sensitive portfolio context — no special filtering needed here (already curated).
        """
        if self._brief_archive is None:
            log.warning("tool_handler_missing_port", tool="get_morning_brief", port="brief_archive")
            return []
        if self._user_id is None or self._tenant_id is None:
            log.warning("tool_no_auth_context", tool="get_morning_brief")
            return []

        # M-1: start timer before the async call so latency_ms reflects actual wait time.
        t0 = time.monotonic()
        try:
            records = await asyncio.wait_for(
                self._brief_archive.get_latest(
                    user_id=self._user_id,
                    tenant_id=self._tenant_id,
                    brief_type="morning",
                    limit=1,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_morning_brief", error=str(e))
            return []

        if not records:
            log.info("tool_no_data", tool="get_morning_brief", user_id=str(self._user_id))
            return []

        brief = records[0]
        lines = [f"**Morning Brief** — {brief.headline}"]
        if brief.lead:
            lines.append(brief.lead)
        for section in brief.sections_json:
            title = section.get("title", "")
            content = section.get("content", "")
            if title:
                lines.append(f"\n### {title}")
            if content:
                lines.append(content)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_morning_brief",
            latency_ms=round((time.monotonic() - t0) * 1000),
            sections=len(brief.sections_json),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:brief:{brief.id}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.95,
                trust_weight=0.92,  # platform-curated brief — high authority
                citation_meta=CitationMeta(
                    title=brief.headline,
                    url=None,
                    source_name="morning_brief",
                    published_at=brief.generated_at,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_compare_entities(
        self,
        tool_call: ToolUseBlock,
        entity_tickers: list[str] | None = None,
    ) -> list[RetrievedItem]:
        """Side-by-side fundamentals + price comparison for 2-4 entities (PLAN-0081 Wave A).

        Fetches fundamentals highlights and latest quote in parallel for each ticker.
        R9: returns [] on missing port, invalid input, or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3 is None:
            log.warning("tool_handler_missing_port", tool="compare_entities", port="s3")
            return []

        tickers = entity_tickers or []
        if len(tickers) < 2 or len(tickers) > 4:
            log.warning(
                "tool_invalid_param",
                tool="compare_entities",
                reason="entity_tickers must be 2-4 items",
                count=len(tickers),
            )
            return []

        t0 = time.monotonic()

        async def _fetch_one(ticker: str) -> dict:
            """Fetch fundamentals + quote for a single ticker in parallel."""
            instrument_id = await self._s3.find_instrument_by_ticker(ticker)
            if instrument_id is None:
                return {"ticker": ticker, "error": "not_found"}
            # Fetch fundamentals highlights and quote concurrently — independent reads
            gather_results: list[dict | BaseException] = list(
                await asyncio.gather(
                    self._s3.get_fundamentals_highlights(instrument_id),
                    self._s3.get_quote(instrument_id),
                    return_exceptions=True,
                )
            )
            funda_raw, quote_raw = gather_results[0], gather_results[1]
            return {
                "ticker": ticker,
                "fundamentals": funda_raw if not isinstance(funda_raw, BaseException) else {},
                "quote": quote_raw if not isinstance(quote_raw, BaseException) else {},
            }

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch_one(t) for t in tickers], return_exceptions=True),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="compare_entities", error=str(e))
            return []

        lines = [f"## Entity Comparison: {', '.join(tickers)}\n"]
        for item in results:
            # M-3: BaseException is the correct check — asyncio.gather(return_exceptions=True)
            # can return KeyboardInterrupt, SystemExit, etc. which are BaseException but not Exception.
            if isinstance(item, BaseException) or item.get("error"):  # type: ignore[union-attr]
                ticker_label = item.get("ticker", "?") if not isinstance(item, BaseException) else "?"  # type: ignore[union-attr]
                lines.append(f"### {ticker_label} — data unavailable\n")
                continue
            ticker = item["ticker"]  # type: ignore[index]
            funda = item.get("fundamentals") or {}  # type: ignore[union-attr]
            quote = item.get("quote") or {}  # type: ignore[union-attr]
            lines.append(f"### {ticker}")
            if quote:
                price = quote.get("price") or quote.get("close") or quote.get("last_price")
                if price:
                    lines.append(f"  Price: {price}")
            if funda:
                for key in ("market_cap", "pe_ratio", "revenue", "gross_profit", "eps"):
                    val = funda.get(key)
                    if val is not None:
                        lines.append(f"  {key.replace('_', ' ').title()}: {val}")
            lines.append("")

        text = "\n".join(lines)
        log.info(
            "tool_executed",
            tool="compare_entities",
            latency_ms=round((time.monotonic() - t0) * 1000),
            ticker_count=len(tickers),
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:compare:{'-'.join(tickers)}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title=f"Comparison: {', '.join(tickers)}",
                    url=None,
                    source_name="fundamentals",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_screen_universe(
        self,
        tool_call: ToolUseBlock,
        market_cap_min: float | None = None,
        market_cap_max: float | None = None,
        pe_ratio_max: float | None = None,
        sector: str | None = None,
        region: str | None = None,
        limit: int = 20,
    ) -> list[RetrievedItem]:
        """Quantitative screener via S9 POST /v1/fundamentals/screen (PLAN-0081 Wave A).

        Builds a filter dict from LLM-supplied params and forwards to S3BriefPort.
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="screen_universe", port="s3_brief")
            return []

        filters: dict = {}
        if market_cap_min is not None:
            filters["market_cap_min"] = market_cap_min
        if market_cap_max is not None:
            filters["market_cap_max"] = market_cap_max
        if pe_ratio_max is not None:
            filters["pe_ratio_max"] = pe_ratio_max
        if sector:
            filters["sector"] = sector
        if region:
            filters["region"] = region
        # WHY clamp limit: prevent the LLM from requesting huge result sets that
        # would overflow the context window budget.
        filters["limit"] = max(1, min(int(limit), 100))

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.screen_instruments(filters),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="screen_universe", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="screen_universe")
            return []

        instruments = raw.get("instruments") or raw.get("results") or raw.get("data") or []
        if not instruments:
            text = "No instruments matched the screening criteria."
        else:
            lines = [f"## Screener Results ({len(instruments)} instruments)\n"]
            for inst in instruments[:50]:
                ticker = inst.get("ticker") or inst.get("symbol") or "?"
                name = inst.get("name") or ""
                mc = inst.get("market_cap")
                pe = inst.get("pe_ratio")
                row = f"  {ticker}"
                if name:
                    row += f" — {name}"
                if mc:
                    row += f" | MCap: {mc}"
                if pe:
                    row += f" | P/E: {pe}"
                lines.append(row)
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="screen_universe",
            latency_ms=round((time.monotonic() - t0) * 1000),
            result_count=len(instruments) if isinstance(instruments, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id="tool:screener:results",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.82,
                trust_weight=0.80,
                citation_meta=CitationMeta(
                    title="Screener results",
                    url=None,
                    source_name="screener",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_market_movers(
        self,
        tool_call: ToolUseBlock,
        mover_type: str = "gainers",
        limit: int = 10,
        period: str = "1D",
    ) -> list[RetrievedItem]:
        """Top gainers/losers via S9 GET /v1/market/top-movers (PLAN-0081 Wave A).

        C-2: period default changed to "1D" (uppercase) to match S9 contract.
        C-3: "most_active" removed — S9 only accepts "gainers" and "losers".
        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_market_movers", port="s3_brief")
            return []

        # C-3: "most_active" is NOT a valid S9 mover_type — only "gainers" and "losers" are accepted.
        # WHY removed: sending "most_active" to S9 causes a 422 validation error downstream.
        valid_types = {"gainers", "losers"}
        safe_mover_type = mover_type if mover_type in valid_types else "gainers"
        limit_clamped = max(1, min(int(limit), 50))

        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._s3_brief.get_top_movers(
                    mover_type=safe_mover_type,
                    limit=limit_clamped,
                    period=period,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_market_movers", error=str(e))
            return []

        if not raw:
            log.info("tool_no_data", tool="get_market_movers")
            return []

        movers = raw.get("movers") or raw.get("data") or raw.get("results") or []
        if not movers:
            text = f"No {safe_mover_type} data available for period {period}."
        else:
            lines = [f"## Market Movers — {safe_mover_type.replace('_', ' ').title()} ({period})\n"]
            for m in movers[:limit_clamped]:
                ticker = m.get("ticker") or m.get("symbol") or "?"
                change_pct = m.get("change_percent") or m.get("change_pct") or m.get("changePercent")
                price = m.get("price") or m.get("close")
                row = f"  {ticker}"
                if change_pct is not None:
                    row += f" {change_pct:+.2f}%" if isinstance(change_pct, float) else f" {change_pct}"
                if price:
                    row += f" @ {price}"
                lines.append(row)
            text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_market_movers",
            latency_ms=round((time.monotonic() - t0) * 1000),
            mover_type=safe_mover_type,
            count=len(movers) if isinstance(movers, list) else 0,
        )
        return [
            RetrievedItem.create(
                item_id=f"tool:movers:{safe_mover_type}:{period}",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.85,
                trust_weight=0.82,
                citation_meta=CitationMeta(
                    title=f"Market movers: {safe_mover_type} ({period})",
                    url=None,
                    source_name="market_data",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_economic_calendar(
        self,
        tool_call: ToolUseBlock,
        from_date: str | None = None,
        to_date: str | None = None,
        region: str | None = None,
    ) -> list[RetrievedItem]:
        """Upcoming macro events (CPI, FOMC, GDP) via S9 GET /v1/fundamentals/economic-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_economic_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            events = await asyncio.wait_for(
                self._s3_brief.get_economic_calendar(
                    from_date=from_date,
                    to_date=to_date,
                    region=region,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_economic_calendar", error=str(e))
            return []

        if not events:
            log.info("tool_no_data", tool="get_economic_calendar")
            return []

        lines = ["## Economic Calendar\n"]
        for evt in events[:30]:
            date_str = evt.get("date") or evt.get("event_date") or ""
            name = evt.get("name") or evt.get("event") or evt.get("title") or "?"
            actual = evt.get("actual")
            forecast = evt.get("forecast") or evt.get("estimate")
            prev = evt.get("previous") or evt.get("prior")
            row = f"  {date_str}  {name}"
            if actual is not None:
                row += f" | Actual: {actual}"
            if forecast is not None:
                row += f" | Forecast: {forecast}"
            if prev is not None:
                row += f" | Prior: {prev}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_economic_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            event_count=len(events),
        )
        return [
            RetrievedItem.create(
                item_id="tool:economic_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Economic calendar",
                    url=None,
                    source_name="economic_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    async def _handle_get_earnings_calendar(
        self,
        tool_call: ToolUseBlock,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[RetrievedItem]:
        """Earnings release dates via S9 GET /v1/fundamentals/earnings-calendar (PLAN-0081 Wave A).

        R9: returns [] on missing port or upstream errors.
        R27: read-only — no UnitOfWork.
        """
        if self._s3_brief is None:
            log.warning("tool_handler_missing_port", tool="get_earnings_calendar", port="s3_brief")
            return []

        t0 = time.monotonic()
        try:
            earnings = await asyncio.wait_for(
                self._s3_brief.get_earnings_calendar(
                    from_date=from_date,
                    to_date=to_date,
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_earnings_calendar", error=str(e))
            return []

        if not earnings:
            log.info("tool_no_data", tool="get_earnings_calendar")
            return []

        lines = ["## Earnings Calendar\n"]
        for entry in earnings[:30]:
            date_str = entry.get("date") or entry.get("report_date") or ""
            ticker = entry.get("ticker") or entry.get("symbol") or "?"
            name = entry.get("name") or entry.get("company") or ""
            eps_est = entry.get("eps_estimate") or entry.get("eps_forecast")
            eps_act = entry.get("eps_actual")
            row = f"  {date_str}  {ticker}"
            if name:
                row += f" ({name})"
            if eps_est is not None:
                row += f" | EPS Est: {eps_est}"
            if eps_act is not None:
                row += f" | EPS Actual: {eps_act}"
            lines.append(row)
        text = "\n".join(lines)

        log.info(
            "tool_executed",
            tool="get_earnings_calendar",
            latency_ms=round((time.monotonic() - t0) * 1000),
            entry_count=len(earnings),
        )
        return [
            RetrievedItem.create(
                item_id="tool:earnings_calendar",
                item_type=ItemType.financial,
                text=text[:_TOOL_RESULT_MAX_CHARS],
                score=0.88,
                trust_weight=0.85,
                citation_meta=CitationMeta(
                    title="Earnings calendar",
                    url=None,
                    source_name="earnings_calendar",
                    published_at=None,
                    entity_name=None,
                ),
            )
        ]

    # ── S10 action handlers (PLAN-0082 Wave A) ────────────────────────────────

    async def _handle_get_alerts(self, tool_call: ToolUseBlock) -> list[RetrievedItem]:
        """Retrieve active (pending) alerts for the authenticated user via S10 (PLAN-0082 Wave A).

        R25: depends only on S10Port Protocol — never imports S10Client directly.
        R27: read-only — no UnitOfWork; calls S10 via HTTP only.
        R9:  returns [] on missing port, missing auth, or any upstream error.
        PRIVACY: alert content is passed to LLM context; no special filtering needed
        (alerts are the user's own data, already scoped by user_id + tenant_id).
        """
        if self._s10 is None:
            log.warning("tool_handler_missing_port", tool="get_alerts", port="s10")
            return []

        # Auth guard: user_id and tenant_id are required to scope the alert query.
        # Both are resolved from X-Internal-JWT by InternalJWTMiddleware — if either
        # is None the request is anonymous (or the JWT is malformed) so we degrade.
        if self._user_id is None or self._tenant_id is None:
            log.warning(
                "tool_no_auth_context",
                tool="get_alerts",
                user_id_missing=self._user_id is None,
                tenant_id_missing=self._tenant_id is None,
            )
            return []

        t0 = time.monotonic()
        try:
            alerts = await asyncio.wait_for(
                self._s10.get_alerts(
                    user_id=str(self._user_id),
                    tenant_id=str(self._tenant_id),
                ),
                timeout=self._timeout,
            )
        except Exception as e:
            log.warning("tool_failed", tool="get_alerts", error=str(e))
            return []

        if not alerts:
            log.info("tool_no_data", tool="get_alerts", user_id=str(self._user_id))
            return []

        import json

        items: list[RetrievedItem] = []
        for alert in alerts:
            # Serialise each alert dict as JSON for LLM context injection.
            # WHY json.dumps: keeps the alert structure intact so the LLM can
            # reason about individual fields (status, trigger_price, etc.).
            alert_text = json.dumps(alert)[:_TOOL_RESULT_MAX_CHARS]
            # Use alert_id if present for stable item_id; fall back to loop index.
            alert_id = alert.get("id") or alert.get("alert_id") or str(len(items))
            items.append(
                RetrievedItem.create(
                    item_id=f"tool:alert:{alert_id}",
                    item_type=ItemType.financial,
                    text=alert_text,
                    score=1.0,  # user's own alerts — maximally relevant
                    trust_weight=0.95,
                    source_type="alert",
                    citation_meta=CitationMeta(
                        title="Alert",
                        url=None,
                        source_name="alert_service",
                        published_at=None,
                        entity_name=None,
                    ),
                )
            )

        log.info(
            "tool_executed",
            tool="get_alerts",
            latency_ms=round((time.monotonic() - t0) * 1000),
            items_returned=len(items),
        )
        return items

    # ── S10 write action handlers (PLAN-0082 Wave B) ──────────────────────────

    async def _handle_create_alert(
        self,
        tool_call: ToolUseBlock,
        entity_id: str = "",
        condition: str = "",
        threshold: dict | None = None,
        severity: str = "low",
        **_: Any,
    ) -> RetrievedItem | None:
        """Create a user-initiated alert rule via S10 (PLAN-0082 Wave B).

        CONFIRMATION FLOW: this handler does NOT execute the alert creation
        directly.  Instead it returns a special ``action_pending`` RetrievedItem
        that signals to the ChatPipeline that user confirmation is required
        before the action is executed.

        The confirmation flow:
          1. LLM emits a ``create_alert`` tool call.
          2. This handler is called; it validates inputs and returns an
             ``action_pending`` RetrievedItem with a generated ``proposal_id``.
          3. The orchestrator detects the ``action_pending`` item type and emits
             a ``pending_action`` SSE event with the proposal_id.
          4. The frontend shows a confirmation modal.
          5. The user confirms → frontend calls POST /v1/chat/proposals/{id}/confirm.
          6. The proposal endpoint calls S10 directly and emits ``action_executed``.

        RATE LIMIT: ≤5 create_alert calls per session. Exceeding the limit
        returns None (no confirmation offered) so the LLM receives an empty
        result and should not retry.

        WHY NOT EXECUTE DIRECTLY: write actions must never be auto-executed
        without user consent — doing so would be a UX footgun and a security
        issue if an adversarial query triggers alert creation.

        R25: depends only on S10Port Protocol — no concrete infra imports.
        R9:  returns None on missing port, missing auth, rate limit, or bad input.
        """
        if self._s10 is None:
            log.warning("tool_handler_missing_port", tool="create_alert", port="s10")
            return None

        # Auth guard: user_id and tenant_id are required (resolved from JWT).
        if self._user_id is None or self._tenant_id is None:
            log.warning(
                "tool_no_auth_context",
                tool="create_alert",
                user_id_missing=self._user_id is None,
                tenant_id_missing=self._tenant_id is None,
            )
            return None

        # Per-session rate limit: ≤5 create_alert calls.
        _max_create_alert = 5
        if self._create_alert_count >= _max_create_alert:
            log.warning(
                "create_alert_rate_limit_exceeded",
                count=self._create_alert_count,
                limit=_max_create_alert,
            )
            return None

        # Input validation: both entity_id and condition are required.
        if not entity_id or not condition:
            log.warning(
                "tool_no_data",
                tool="create_alert",
                reason="missing_entity_id_or_condition",
            )
            return None

        # Increment session counter.
        self._create_alert_count += 1

        # Generate a proposal_id that the frontend will send back on confirm.
        # WHY UUIDv7: consistent with all other IDs in this codebase (R10).
        from common.ids import new_uuid7  # type: ignore[import-untyped]

        proposal_id = str(new_uuid7())

        threshold_dict: dict[str, Any] = threshold or {}

        # Serialise proposal params as JSON text for LLM context injection.
        # The LLM receives this text and can reference the pending action.
        import json as _json

        params_text = _json.dumps(
            {
                "proposal_id": proposal_id,
                "entity_id": entity_id,
                "condition": condition,
                "threshold": threshold_dict,
                "severity": severity,
            }
        )

        log.info(
            "create_alert_proposal_created",
            proposal_id=proposal_id,
            entity_id=entity_id,
            condition=condition,
            user_id=str(self._user_id),
            tenant_id=str(self._tenant_id),
        )

        # Return a special action_pending RetrievedItem.  The orchestrator
        # detects item_type == action_pending and emits the pending_action SSE.
        return RetrievedItem.create(
            item_id=f"tool:create_alert:{proposal_id}",
            item_type=ItemType.action_pending,
            text=params_text[:_TOOL_RESULT_MAX_CHARS],
            score=1.0,  # user-initiated action — maximally relevant
            trust_weight=1.0,
            source_type="action_pending",
            citation_meta=CitationMeta(
                title="Pending alert creation",
                url=None,
                source_name="alert_service",
                published_at=None,
                entity_name=None,
            ),
        )

    # ── Formatters ────────────────────────────────────────────────────────────

    def _format_price_table(
        self,
        ticker: str,
        from_date: str,
        to_date: str,
        interval: str,
        bars: list[dict[str, Any]],
    ) -> str:
        """Format OHLCV bars as a markdown table with a header line."""
        header = f"{ticker} price history ({interval}, {from_date} → {to_date})\n"
        header += "| Date       | Close  | Volume |\n|------------|--------|--------|\n"
        rows = []
        for b in bars:
            close = b.get("close", 0) or 0
            volume = b.get("volume", 0) or 0
            rows.append(f"| {b.get('date', '?')} | ${float(close):.2f} | {int(volume):,} |")
        return header + "\n".join(rows)

    def _format_fundamentals_table(
        self,
        ticker: str,
        periods: list[dict[str, Any]],
    ) -> str:
        """Format quarterly fundamentals as a markdown table."""
        header = f"{ticker} quarterly fundamentals\n"
        header += "| Period | Revenue | Net Income | EPS | P/E |\n"
        header += "|--------|---------|------------|-----|-----|\n"
        rows = []
        for p in periods:
            rev_val = p.get("revenue") or p.get("totalRevenue")
            rev = f"${float(rev_val) / 1e9:.1f}B" if rev_val else "—"
            ni_val = p.get("net_income") or p.get("netIncome")
            ni = f"${float(ni_val) / 1e9:.1f}B" if ni_val else "—"
            eps_val = p.get("eps") or p.get("epsActual")
            eps = f"${float(eps_val):.2f}" if eps_val else "—"
            pe_val = p.get("pe_ratio") or p.get("pe")
            pe = f"{float(pe_val):.1f}x" if pe_val else "—"
            period_label = p.get("period") or p.get("date") or "?"
            rows.append(f"| {period_label} | {rev} | {ni} | {eps} | {pe} |")
        return header + "\n".join(rows)

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


def build_default_registry() -> ToolRegistry:
    """Factory: create a ToolRegistry with all 22 tools registered.

    Breakdown: 10 v1 + 4 PLAN-0080 v2 + 6 PLAN-0081 v3 + 2 PLAN-0082 v4.

    Called by api/dependencies.py to wire the ToolExecutor at startup.
    The handlers registered here are placeholder stubs — the actual execution
    is dispatched inside ToolExecutor.execute() via name-based dispatch, not
    through the handler stored in the registry. The registry handler field is
    kept for future extension (e.g. PLAN-0067 full tool catalog).
    """
    from tools.tool_spec import ParameterSpec, ToolSpec  # type: ignore[import-untyped]

    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="get_price_history",
            description=(
                "Fetches OHLCV (open/high/low/close/volume) bar history for a stock ticker "
                "over a specified date range. Use when the user asks about price movement, "
                "trend, range, or performance over a time period."
            ),
            parameters=[
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol (e.g. 'AAPL')",
                    required=True,
                ),
                ParameterSpec(
                    name="from_date",
                    type="date",
                    description="Start of date range (YYYY-MM-DD)",
                    required=True,
                ),
                ParameterSpec(
                    name="to_date",
                    type="date",
                    description="End of date range (YYYY-MM-DD)",
                    required=True,
                ),
                ParameterSpec(
                    name="interval",
                    type="string",
                    description="Bar granularity: day/week/month. Default 'week'.",
                    required=False,
                    enum=["day", "week", "month"],
                ),
            ],
            source_type="ohlcv",
            example_queries=[
                "How has AAPL performed over the last 3 months?",
                "What was NVDA's price range in Q1 2026?",
            ],
        ),
        handler=lambda **_: None,  # dispatch happens inside ToolExecutor.execute()
    )

    registry.register(
        ToolSpec(
            name="get_fundamentals_history",
            description=(
                "Fetches quarterly fundamental metrics (revenue, gross profit, net income, "
                "EPS, P/E ratio, market cap) for a ticker over N periods. Use when the user "
                "asks about revenue trends, EPS growth, or multi-quarter financial performance."
            ),
            parameters=[
                ParameterSpec(
                    name="ticker",
                    type="string",
                    description="Stock ticker symbol (e.g. 'MSFT')",
                    required=True,
                ),
                ParameterSpec(
                    name="periods",
                    type="integer",
                    description="Number of quarters to return (1-20). Default 8.",
                    required=False,
                ),
            ],
            source_type="fundamentals",
            example_queries=[
                "Show me MSFT's revenue trend over 8 quarters",
                "What has AAPL's EPS been over the last 2 years?",
            ],
        ),
        handler=lambda **_: None,
    )

    # PLAN-0067 Wave W11-2: register remaining 8 tools.
    # Handlers are placeholder stubs — dispatch is inside ToolExecutor.execute().
    _new_tool_names = [
        "search_documents",
        "get_entity_graph",
        "traverse_graph",
        "search_entity_relations",
        "search_claims",
        "search_events",
        "get_contradictions",
        "get_portfolio_context",
    ]
    for tool_name in _new_tool_names:
        registry.register(
            ToolSpec(
                name=tool_name,
                description=f"Tool: {tool_name} (see capability_manifest.yaml for full description)",
                parameters=[],
                source_type="mixed",
            ),
            handler=lambda **_: None,
        )

    # PLAN-0080 Wave A: register 4 intelligence tools (get_entity_narrative, get_entity_paths,
    # get_entity_health, get_entity_intelligence). These are distinct from the S7 KG tools —
    # they call S9-proxied intelligence endpoints (R14 compliance).
    _intel_tool_names = [
        "get_entity_narrative",
        "get_entity_paths",
        "get_entity_health",
        "get_entity_intelligence",
    ]
    for tool_name in _intel_tool_names:
        registry.register(
            ToolSpec(
                name=tool_name,
                description=f"Tool: {tool_name} (see capability_manifest.yaml for full description)",
                parameters=[],
                source_type="narrative",
            ),
            handler=lambda **_: None,
        )

    # PLAN-0081 Wave A: register 6 catalog tools (brief, compare, screener, movers, calendars).
    # These call S9-proxied endpoints or the DB archive (R14 compliance).
    _catalog_tool_names = [
        "get_morning_brief",
        "compare_entities",
        "screen_universe",
        "get_market_movers",
        "get_economic_calendar",
        "get_earnings_calendar",
    ]
    for tool_name in _catalog_tool_names:
        registry.register(
            ToolSpec(
                name=tool_name,
                description=f"Tool: {tool_name} (see capability_manifest.yaml for full description)",
                parameters=[],
                source_type="mixed",
            ),
            handler=lambda **_: None,
        )

    # PLAN-0082 Wave A + Wave B: register 2 action tools (get_alerts, create_alert).
    # Calls S9-proxied S10 alert endpoints (R14 compliance).
    # create_alert requires user confirmation before execution (requires_confirmation=true).
    _action_tool_names = [
        "get_alerts",
        "create_alert",
    ]
    for tool_name in _action_tool_names:
        registry.register(
            ToolSpec(
                name=tool_name,
                description=f"Tool: {tool_name} (see capability_manifest.yaml for full description)",
                parameters=[],
                source_type="alert",
            ),
            handler=lambda **_: None,
        )

    return registry
