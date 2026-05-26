"""News and content tool handlers — document search and morning brief.

Covers tools backed by S6Port and BriefArchivePort:
  - search_documents   (S6Port — hybrid BM25+ANN document search)
  - get_morning_brief  (BriefArchivePort — DB-archived morning brief)
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.pipeline.tool_executor import EntityContext, ToolUseBlock
    from rag_chat.application.ports.brief_archive import BriefArchivePort
    from rag_chat.application.ports.upstream_clients import S6Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000


class NewsHandler(ToolHandler):
    """Handles document search and morning brief tools.

    search_documents calls S6Port (content-store / NLP pipeline).
    get_morning_brief calls BriefArchivePort (local DB read — R27 compliance).
    """

    _HANDLED_TOOLS = frozenset({"search_documents", "get_morning_brief"})

    def __init__(
        self,
        s6: S6Port | None = None,
        brief_archive: BriefArchivePort | None = None,
        entity_context: EntityContext | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s6 = s6
        self._brief_archive = brief_archive
        self._entity_context = entity_context
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._timeout = timeout

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        from rag_chat.application.pipeline.tool_executor import ToolUseBlock

        _stub = ToolUseBlock(name=tool_name, input=args)

        if tool_name == "search_documents":
            # Normalize to_date → date_to: LLM occasionally uses the wrong param name.
            if "to_date" in args and "date_to" not in args:
                args = {**args, "date_to": args.pop("to_date")}
            return await self._handle_search_documents(_stub, **args)
        if tool_name == "get_morning_brief":
            return await self._handle_get_morning_brief(_stub)
        raise ValueError(f"NewsHandler cannot handle tool: {tool_name}")

    # ── S6 handler (document search) ───────────────────────────────────────────

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
        from rag_chat.application.pipeline.tool_executor import ToolCallProvenance

        _provenance = ToolCallProvenance(  # — created for audit log, consumed downstream
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

        # PLAN-0093 E-4 T-E-4-02: resolve entity_tickers → UUIDs.
        # The LLM passes entity_tickers=["AAPL","MSFT"] for multi-entity
        # comparison queries; before this fix the field was silently ignored
        # and S6 returned generic results filtered only by entity_context.
        # Each ticker is now resolved via S6.resolve_entity_by_ticker and
        # added to entity_ids alongside any scoped entity_context.
        _entity_ids: list[UUID] = []
        if self._entity_context is not None:
            _entity_ids.append(self._entity_context.entity_id)
        if entity_tickers:
            for ticker in entity_tickers:
                if not isinstance(ticker, str) or not ticker.strip():
                    continue
                resolved = await self._s6.resolve_entity_by_ticker(ticker)
                if resolved is not None and resolved not in _entity_ids:
                    _entity_ids.append(resolved)
                elif resolved is None:
                    log.warning("entity_ticker_unresolved", tool="search_documents", ticker=ticker)

        request = ChunkSearchRequest(
            query_text=query,
            top_k=20,
            search_type="hybrid",
            date_from=_parse_dt(date_from),
            date_to=_parse_dt(date_to),
            source_types=source_types or [],
            entity_ids=_entity_ids or None,  # None preserves "any entity" semantics
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

    # ── BriefArchive handler (morning brief) ───────────────────────────────────

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
