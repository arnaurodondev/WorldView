"""ToolExecutor — dispatches LLM tool_use blocks to S3Port handlers (PLAN-0066 Wave H T-W10-H-02).

Architecture notes:
- R25: ToolExecutor depends on S3Port (Protocol), never S3Client (infrastructure)
- R30: ToolExecutor holds NO per-request state (no user_id/tenant_id in __init__)
- Structlog only (STANDARDS.md §5) — never stdlib logging
- BP-025: all S3 calls wrapped in asyncio.wait_for(timeout=5.0)
- Tool results truncated to _TOOL_RESULT_MAX_CHARS=4000 to prevent context overflow

Structured logging conventions:
- tool_executed: success path, carries tool name + latency_ms + items_returned
- tool_failed: any exception from a handler (error swallowed, None returned)
- unknown_tool_name: LLM emitted a tool name not in the registry (hallucination guard)
- tool_no_data: handler received empty response from S3 (ticker not found / no data)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

# Import from libs/tools (must be on PYTHONPATH — added in Dockerfile, BP-181)
from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

from rag_chat.application.ports.upstream_clients import S3Port  # noqa: TCH001
from rag_chat.domain.entities.chat import RetrievedItem
from rag_chat.domain.enums import ItemType

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Maximum characters for tool result text injected into LLM context.
# WHY: OHLCV data for 252 trading days at ~50 chars/row ≈ 12,600 chars — well
# beyond most context windows. Cap at 4000 to stay within budget.
_TOOL_RESULT_MAX_CHARS = 4000

# Maximum simultaneous tool calls dispatched from a single LLM turn.
# Prevents runaway tool use if the LLM emits many calls at once.
_MAX_CONCURRENT_TOOLS = 5


@dataclass
class ToolUseBlock:
    """Parsed representation of a single tool_use block from the LLM response.

    The LLM emits JSON blocks shaped like:
        {"type": "tool_use", "name": "get_price_history",
         "input": {"ticker": "AAPL", "from_date": "...", ...}}

    tool_use_id is optional — not all providers set it for the MVP.
    """

    name: str
    input: dict[str, Any]
    tool_use_id: str = ""


class ToolExecutor:
    """Executes tool_use blocks emitted by the LLM against S3Port.

    Design constraints:
    - No per-request state: __init__ takes only registry + port (R30)
    - All errors are swallowed and logged; callers receive None on failure
    - execute_all() uses asyncio.gather for concurrent execution
    """

    def __init__(self, registry: ToolRegistry, s3: S3Port) -> None:
        self._registry = registry
        self._s3 = s3

    async def execute(self, tool_call: ToolUseBlock) -> RetrievedItem | None:
        """Execute a single tool call and return a RetrievedItem or None.

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
            result: RetrievedItem | None
            if tool_call.name == "get_price_history":
                result = await self._handle_get_price_history(**tool_call.input)
            elif tool_call.name == "get_fundamentals_history":
                result = await self._handle_get_fundamentals_history(**tool_call.input)
            else:
                # Registry had the spec but we have no handler — shouldn't happen
                # if build_default_registry() is used; guard logs the gap.
                log.warning("unknown_tool_name", name=tool_call.name)
                return None

            latency_ms = round((time.monotonic() - t0) * 1000)
            log.info(
                "tool_executed",
                tool=tool_call.name,
                latency_ms=latency_ms,
                items_returned=1 if result is not None else 0,
            )
            return result
        except Exception as exc:
            log.warning("tool_failed", tool=tool_call.name, error=str(exc))
            return None

    async def execute_all(self, tool_calls: list[ToolUseBlock]) -> list[RetrievedItem | None]:
        """Execute all tool calls concurrently, capped at _MAX_CONCURRENT_TOOLS.

        WHY asyncio.gather: tool calls are independent — parallel execution
        minimises total latency (both S3 calls run in ~150ms instead of ~300ms).
        """
        capped = tool_calls[:_MAX_CONCURRENT_TOOLS]
        return list(await asyncio.gather(*[self.execute(tc) for tc in capped]))

    # ── Private handlers ──────────────────────────────────────────────────────

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
            timeout=5.0,
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
            timeout=5.0,
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


def build_default_registry() -> ToolRegistry:
    """Factory: create a ToolRegistry with both temporal tools registered.

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

    return registry
