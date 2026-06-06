"""Portfolio tool handler — holdings and watchlist context for the authenticated user.

Covers tools backed by S1Port:
  - get_portfolio_context  (S1Port — user portfolio holdings + watchlist)
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from .base import ToolHandler

if TYPE_CHECKING:
    from rag_chat.application.ports.upstream_clients import S1Port

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
_TOOL_RESULT_MAX_CHARS = 4000


class PortfolioHandler(ToolHandler):
    """Handles portfolio context tools.

    All tools in this handler call S1Port (portfolio service).
    Auth context (user_id, tenant_id, internal_jwt) is injected at request time.
    """

    _HANDLED_TOOLS = frozenset({"get_portfolio_context"})

    def __init__(
        self,
        s1: S1Port | None = None,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        internal_jwt: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._s1 = s1
        self._user_id = user_id
        self._tenant_id = tenant_id
        self._internal_jwt = internal_jwt
        self._timeout = timeout

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in self._HANDLED_TOOLS

    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        from .base import filter_kwargs_to_signature

        if tool_name == "get_portfolio_context":
            # No accepted kwargs — log/count any that the LLM emits anyway.
            filter_kwargs_to_signature(self._handle_get_portfolio_context, tool_name, args)
            return await self._handle_get_portfolio_context()
        raise ValueError(f"PortfolioHandler cannot handle tool: {tool_name}")

    # ── S1 portfolio handler ───────────────────────────────────────────────────

    async def _handle_get_portfolio_context(self) -> list[RetrievedItem]:
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
