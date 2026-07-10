"""ToolExecutor — thin dispatcher that routes LLM tool_use blocks to domain handlers.

Plans: PLAN-0066 Wave H, PLAN-0067 Wave W11-2, PLAN-0082 Wave A, PLAN-0089 Wave C-1.

PLAN-0089 C-1: per-domain handlers live in handlers/; this file is a dispatcher only.
  handlers/market.py       — price/fundamentals/screener/movers/calendars (S3/S3Brief)
  handlers/intelligence.py — KG graph/traversal/claims/events (S7)
  handlers/narrative.py    — entity narrative/paths/health/intelligence bundle (S7Intel)
  handlers/portfolio.py    — portfolio holdings + watchlist (S1)
  handlers/news.py         — document search + morning brief (S6/BriefArchive)
  handlers/alerts.py       — alert read + creation (S10)

Architecture: R25 (port Protocols only), R30 (factory singleton + per-request executor),
BP-025 (all upstream calls in asyncio.wait_for), structlog only (never stdlib logging).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from .handlers.alerts import AlertsHandler
from .handlers.intelligence import IntelligenceHandler
from .handlers.market import MarketHandler
from .handlers.market_sizing import MarketSizingHandler
from .handlers.narrative import NarrativeHandler
from .handlers.news import NewsHandler
from .handlers.portfolio import PortfolioHandler
from .tool_registry_builder import (  # re-exported for callers
    ToolRegistryDriftError,
    build_default_registry,
    validate_registry_parity,
)
from .transport_error import TransportErrorMarker, UpstreamTransportError

if TYPE_CHECKING:
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped,import-not-found]

    from rag_chat.application.ports.brief_archive import BriefArchivePort
    from rag_chat.application.ports.upstream_clients import (
        ContentStorePort,
        S1Port,
        S3BriefPort,
        S3Port,
        S6Port,
        S7IntelligencePort,
        S7Port,
        S10Port,
    )
    from rag_chat.domain.entities.chat import RetrievedItem

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Exported for tests that validate truncation behaviour.
_TOOL_RESULT_MAX_CHARS = 4000
_MAX_CONCURRENT_TOOLS = 5


@dataclass
class ToolUseBlock:
    """Parsed LLM tool_use block (LOCAL variant; canonical in libs/tools/types.py uses ``id``)."""

    name: str
    input: dict[str, Any]
    tool_use_id: str = ""


@dataclass
class EntityContext:
    """Entity scope injected at request time (PLAN-0067 §0 M-1).

    ``pinned`` (BP-661 P/E→Pandora follow-up, 2026-06-12) distinguishes two
    very different sources of this scope:

      * ``pinned=True``  — the user is on a PINNED entity surface (the
        ``/chat/entity-context`` endpoints) where every tool MUST be scoped to
        this entity regardless of what the LLM passes. The hard override in
        ``NarrativeHandler._resolve_intel_entity_id`` is correct here.
      * ``pinned=False`` — the scope was merely INFERRED from the first
        S6-resolved question entity (the regular ``/chat`` path). S6's
        ``entities[0]`` ranking is fragile for relationship/comparison
        questions ("Apple's competitors" once ranked Alexandria Real Estate
        #1; "AAPL's P/E" once ranked Pandora #1). When the LLM supplies a
        concrete, VALID ``entity_id`` we must trust it over this inferred
        guess instead of blindly discarding it.

    Defaults to ``True`` so any existing caller that constructs an
    ``EntityContext`` without the flag keeps the historical hard-override
    behaviour; the orchestrator's inferred path opts out explicitly.
    """

    entity_id: UUID
    ticker: str
    name: str
    pinned: bool = True


@dataclass
class ToolCallProvenance:
    """Provenance record for citation audit (PLAN-0067 §0 I-6)."""

    tool_name: str
    tool_input: dict[str, Any]
    call_id: str


class ToolExecutorFactory:
    """Singleton; holds shared collaborators (HTTP clients, registry) and creates per-request ToolExecutors."""

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
        content_store: ContentStorePort | None = None,
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
        self._content_store = content_store
        self._timeout = timeout

    def for_request(
        self,
        *,
        user_id: UUID | None,
        tenant_id: UUID | None,
        internal_jwt: str | None,
        entity_context: EntityContext | None = None,
    ) -> ToolExecutor:
        """Return a per-request ToolExecutor with auth context bound."""
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
            content_store=self._content_store,
            user_id=user_id,
            tenant_id=tenant_id,
            internal_jwt=internal_jwt,
            entity_context=entity_context,
            timeout=self._timeout,
        )


class ToolExecutor:
    """Routes LLM tool_use blocks to per-domain ToolHandler instances (R25, PLAN-0089 C-1).

    After each ``execute_all`` call, ``last_per_tool_latencies_s`` holds the
    wall-clock time for each individual tool invocation in the same order as the
    input tool_calls.  This lets the orchestrator use accurate per-tool latency
    for the ``tool_slow`` warning instead of dividing the total batch time by the
    number of tools (which under-reports any single slow tool in a concurrent batch).
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
        content_store: ContentStorePort | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        internal_jwt: str | None = None,
        entity_context: EntityContext | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._registry = registry
        self._timeout = timeout
        self._alerts_handler = AlertsHandler(s10=s10, user_id=user_id, tenant_id=tenant_id, timeout=timeout)
        # PLAN-0093 E-4 T-E-4-01: pass S6 so search_entity_relations can
        # call S6.embed_text() for real query embeddings.
        # feat/chat-kg-source-links: content_store backfills claim/event citation
        # URLs from the source article each was extracted from.
        _intelligence_handler = IntelligenceHandler(
            s7=s7,
            s6=s6,
            content_store=content_store,
            entity_context=entity_context,
            timeout=timeout,
        )
        self._handlers = [
            MarketHandler(s3=s3, s3_brief=s3_brief, timeout=timeout),
            _intelligence_handler,
            # BP-661: NarrativeHandler receives S6 (ticker resolution) and the
            # IntelligenceHandler (S7 alias name resolution) so a non-UUID
            # ``entity_id`` from the LLM ("AAPL", "Apple Inc.") resolves
            # tool-side instead of yielding an empty intelligence result.
            NarrativeHandler(
                s7_intel=s7_intel,
                entity_context=entity_context,
                timeout=timeout,
                s6=s6,
                name_resolver=_intelligence_handler,
            ),
            PortfolioHandler(s1=s1, user_id=user_id, tenant_id=tenant_id, internal_jwt=internal_jwt, timeout=timeout),
            NewsHandler(
                s6=s6,
                brief_archive=brief_archive,
                entity_context=entity_context,
                user_id=user_id,
                tenant_id=tenant_id,
                timeout=timeout,
            ),
            self._alerts_handler,
            # Area-2 P3: curated TAM / market-size reference lookup. No upstream
            # port — reads a packaged YAML reference table (analyst estimates)
            # so projections can GROUND a scenario parameter instead of assuming.
            MarketSizingHandler(),
        ]
        # Populated by execute_all; holds per-tool wall-clock seconds in the same
        # order as the capped input list.  Empty list before the first call.
        self.last_per_tool_latencies_s: list[float] = []

    @property
    def _create_alert_count(self) -> int:  # exposed for test introspection
        return self._alerts_handler._create_alert_count

    @_create_alert_count.setter
    def _create_alert_count(self, value: int) -> None:  # exposed for test priming
        self._alerts_handler._create_alert_count = value

    # ── Test-compatibility shims (PLAN-0089 C-1) ──────────────────────────────
    # Catalog and extended tests call these methods directly on ToolExecutor.
    # After the C-1 handler split the implementations live on the domain handler
    # objects; these thin wrappers keep existing tests green without rewriting them.

    def _get_market_handler(self) -> MarketHandler:
        for h in self._handlers:
            if isinstance(h, MarketHandler):
                return h
        raise RuntimeError("MarketHandler not found in _handlers")  # pragma: no cover

    def _get_news_handler(self) -> NewsHandler:
        for h in self._handlers:
            if isinstance(h, NewsHandler):
                return h
        raise RuntimeError("NewsHandler not found in _handlers")  # pragma: no cover

    # market shims — no block arg; match MarketHandler._handle_* signatures
    async def _handle_compare_entities(self, entity_tickers: list[str] | None = None) -> Any:
        return await self._get_market_handler()._handle_compare_entities(entity_tickers=entity_tickers)

    async def _handle_screen_universe(self, **kwargs: Any) -> Any:
        return await self._get_market_handler()._handle_screen_universe(**kwargs)

    async def _handle_get_market_movers(self, **kwargs: Any) -> Any:
        return await self._get_market_handler()._handle_get_market_movers(**kwargs)

    async def _handle_get_economic_calendar(self, **kwargs: Any) -> Any:
        return await self._get_market_handler()._handle_get_economic_calendar(**kwargs)

    async def _handle_get_earnings_calendar(self, **kwargs: Any) -> Any:
        return await self._get_market_handler()._handle_get_earnings_calendar(**kwargs)

    # news shim — passes block through; NewsHandler._handle_get_morning_brief(tool_call)
    async def _handle_get_morning_brief(self, tool_call: ToolUseBlock) -> Any:
        return await self._get_news_handler()._handle_get_morning_brief(tool_call)

    async def execute(
        self, tool_call: ToolUseBlock
    ) -> RetrievedItem | list[RetrievedItem] | TransportErrorMarker | None:
        """Dispatch a single tool call to the owning domain handler.

        FIX-LIVE-E (2026-05-24): exceptions are CLASSIFIED before being swallowed.
        Previously a single ``except Exception: return None`` masked TypeErrors
        from arg-shape mismatches as "tool returned None", which made the
        Phase 5c Q2 fallback failure invisible.  Now ``TypeError`` and
        ``AttributeError`` log under ``tool_argument_error`` while every other
        exception logs under ``tool_execution_error`` — both include
        ``exception_type`` and ``exception_repr`` for debugging.  We still
        return None so the orchestrator's fallback chain can take over, but the
        structured log now lets us debug arg-shape mismatches without re-running.

        PLAN-0103 W2 (BP-623): ``UpstreamTransportError`` (a BaseException, not
        Exception — so per-handler ``except Exception: return []`` guards do
        NOT swallow it) is caught here and converted into a
        ``TransportErrorMarker`` so the orchestrator can render
        ``status="transport_error"`` instead of conflating an outage with an
        empty result.
        """
        if self._registry.get_spec(tool_call.name) is None:
            log.warning("unknown_tool_name", name=tool_call.name)
            return None
        t0 = time.monotonic()
        try:
            for handler in self._handlers:
                if handler.can_handle(tool_call.name):
                    result = await handler.execute(tool_call.name, tool_call.input)
                    ms = round((time.monotonic() - t0) * 1000)
                    n = len(result) if isinstance(result, list) else (1 if result is not None else 0)
                    log.info("tool_executed", tool=tool_call.name, latency_ms=ms, items_returned=n)
                    return result  # type: ignore[no-any-return]
            log.warning("unknown_tool_name", name=tool_call.name)
            return None
        except UpstreamTransportError as exc:
            # BP-623: upstream is unreachable / timing out / 5xx-erroring.
            # Surface as a typed marker so the orchestrator can emit
            # status="transport_error" and feed the LLM a structured tool
            # message instead of an empty list (which would be rendered as
            # "no data was found").
            ms = round((time.monotonic() - t0) * 1000)
            log.warning(
                "tool_transport_error",
                tool=tool_call.name,
                reason=exc.reason,
                status_code=exc.status_code,
                elapsed_ms=ms,
                path=exc.path,
            )
            return TransportErrorMarker(
                tool_name=tool_call.name,
                reason=exc.reason,
                elapsed_ms=ms,
                status_code=exc.status_code,
                path=exc.path,
            )
        except (TypeError, AttributeError) as exc:
            # Arg-shape mismatch (e.g. fallback passed keys the handler doesn't accept).
            # Distinct event tag so dashboards/log queries can isolate this class.
            log.warning(
                "tool_argument_error",
                tool=tool_call.name,
                exception_type=type(exc).__name__,
                exception_repr=repr(exc),
                input_keys=sorted(tool_call.input.keys()),
            )
            return None
        except Exception as exc:
            log.warning(
                "tool_execution_error",
                tool=tool_call.name,
                exception_type=type(exc).__name__,
                exception_repr=repr(exc),
            )
            return None

    async def execute_all(
        self, tool_calls: list[ToolUseBlock]
    ) -> list[RetrievedItem | list[RetrievedItem] | TransportErrorMarker | None]:
        """Execute up to _MAX_CONCURRENT_TOOLS calls concurrently via asyncio.gather.

        Per-tool wall-clock latencies are stored in ``last_per_tool_latencies_s``
        (Q1 fix: previously the orchestrator divided total batch time by the number
        of tools, which under-reports any single slow tool running concurrently).
        """
        # PLAN-0093 E-5 T-E-5-04: warn when the LLM emits more tool calls than
        # the concurrency cap allows. Previously the surplus was silently
        # dropped; now operators get a structured event so they can spot
        # over-aggressive tool-batching by the LLM (F-RAG-011).
        if len(tool_calls) > _MAX_CONCURRENT_TOOLS:
            log.warning(
                "tool_calls_truncated",
                requested=len(tool_calls),
                kept=_MAX_CONCURRENT_TOOLS,
                dropped_tool_names=[c.name for c in tool_calls[_MAX_CONCURRENT_TOOLS:]],
            )
        capped = tool_calls[:_MAX_CONCURRENT_TOOLS]

        async def _timed_execute(
            tc: ToolUseBlock,
        ) -> tuple[RetrievedItem | list[RetrievedItem] | TransportErrorMarker | None, float]:
            _t0 = time.monotonic()
            result = await self.execute(tc)
            return result, time.monotonic() - _t0

        pairs: list[tuple[RetrievedItem | list[RetrievedItem] | TransportErrorMarker | None, float]] = list(
            await asyncio.gather(*[_timed_execute(tc) for tc in capped])
        )
        results, latencies = zip(*pairs, strict=False) if pairs else ([], [])
        self.last_per_tool_latencies_s = list(latencies)
        return list(results)


__all__ = [
    "AlertsHandler",
    "EntityContext",
    "IntelligenceHandler",
    "MarketHandler",
    "MarketSizingHandler",
    "NarrativeHandler",
    "NewsHandler",
    "PortfolioHandler",
    "ToolCallProvenance",
    "ToolExecutor",
    "ToolExecutorFactory",
    "ToolRegistryDriftError",
    "ToolUseBlock",
    "TransportErrorMarker",
    "build_default_registry",
    "validate_registry_parity",
]
