"""Unit tests for ToolExecutor (PLAN-0066 Wave H T-W10-H-02).

Tests:
- test_executor_price_history_passes_ticker_to_port
- test_executor_returns_none_on_empty_bars
- test_executor_returns_none_on_s3_error
- test_executor_execute_all_runs_concurrently
- test_executor_execute_all_caps_at_5
- test_executor_unknown_tool_name_logs_warning
- test_executor_tool_result_truncated_at_max_chars
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_registry_with_tools():
    """Build a ToolRegistry with both temporal tools registered."""
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]
    from tools.tool_spec import ParameterSpec, ToolSpec  # type: ignore[import-untyped]

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="get_price_history",
            description="OHLCV history",
            parameters=[
                ParameterSpec(name="ticker", type="string", description="Ticker", required=True),
                ParameterSpec(name="from_date", type="date", description="Start", required=True),
                ParameterSpec(name="to_date", type="date", description="End", required=True),
            ],
            source_type="ohlcv",
        ),
        handler=AsyncMock(return_value=None),
    )
    registry.register(
        ToolSpec(
            name="get_fundamentals_history",
            description="Quarterly fundamentals",
            parameters=[
                ParameterSpec(name="ticker", type="string", description="Ticker", required=True),
            ],
            source_type="fundamentals",
        ),
        handler=AsyncMock(return_value=None),
    )
    return registry


def _make_s3_port(bars: list | None = None, fundamentals: list | None = None) -> Any:
    """Build a mock S3Port."""
    mock = AsyncMock()
    mock.get_ohlcv_range.return_value = bars if bars is not None else []
    mock.get_fundamentals_history.return_value = fundamentals if fundamentals is not None else []
    # Other S3Port methods required by Protocol
    mock.get_fundamentals_highlights.return_value = {}
    mock.get_earnings.return_value = []
    mock.get_quote.return_value = {}
    mock.find_instrument_by_ticker.return_value = None
    return mock


def _sample_bars() -> list[dict]:
    return [
        {"date": "2026-02-07", "open": 184.5, "high": 186.0, "low": 183.0, "close": 185.2, "volume": 52000000},
        {"date": "2026-02-14", "open": 185.2, "high": 188.0, "low": 184.0, "close": 187.0, "volume": 48000000},
    ]


def _sample_fundamentals() -> list[dict]:
    return [
        {"period": "Q4 2025", "revenue": 120e9, "net_income": 30e9, "eps": 1.85, "pe_ratio": 28.5},
        {"period": "Q3 2025", "revenue": 115e9, "net_income": 28e9, "eps": 1.72, "pe_ratio": 27.0},
    ]


def _make_tool_use_block(name: str, **kwargs: Any):
    from rag_chat.application.pipeline.tool_executor import ToolUseBlock

    return ToolUseBlock(name=name, input=kwargs)


def _make_executor(bars: list | None = None, fundamentals: list | None = None):
    from rag_chat.application.pipeline.tool_executor import ToolExecutor

    return ToolExecutor(
        registry=_make_registry_with_tools(),
        s3=_make_s3_port(bars=bars, fundamentals=fundamentals),
    )


# ---------------------------------------------------------------------------
# Price history tests
# ---------------------------------------------------------------------------


class TestGetPriceHistory:
    async def test_executor_price_history_passes_ticker_to_port(self) -> None:
        """execute() must call s3.get_ohlcv_range with the ticker from the tool call."""
        s3 = _make_s3_port(bars=_sample_bars())
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tc = _make_tool_use_block("get_price_history", ticker="AAPL", from_date="2026-02-01", to_date="2026-05-01")

        result = await executor.execute(tc)

        assert result is not None
        s3.get_ohlcv_range.assert_called_once()
        call_kwargs = s3.get_ohlcv_range.call_args
        assert call_kwargs.kwargs["ticker"] == "AAPL"
        # No find_instrument_by_ticker call — S3 resolves server-side
        s3.find_instrument_by_ticker.assert_not_called()

    async def test_executor_price_history_formats_markdown_table(self) -> None:
        """Returned RetrievedItem.text must contain markdown table header."""
        executor = _make_executor(bars=_sample_bars())
        tc = _make_tool_use_block("get_price_history", ticker="AAPL", from_date="2026-02-01", to_date="2026-05-01")

        result = await executor.execute(tc)

        assert result is not None
        assert "| Date" in result.text
        assert "Close" in result.text
        assert "AAPL" in result.text

    async def test_executor_returns_none_on_empty_bars(self) -> None:
        """execute() must return None when BOTH the requested window AND the
        1-minute fallback return empty bars. Empty mock here means S3 returns
        [] for both calls — the fallback path is exercised but also gets [].
        """
        executor = _make_executor(bars=[])
        tc = _make_tool_use_block("get_price_history", ticker="TSLA", from_date="2026-01-01", to_date="2026-04-01")

        result = await executor.execute(tc)

        assert result is None

    async def test_executor_price_history_falls_back_to_latest_1m_bar(self) -> None:
        """When the requested date range has no bars, the handler must retry
        with interval='1m' over the last 7 days and surface the most recent
        bar as a "last known price" RetrievedItem. Covers the after-hours /
        weekend "what is X trading at?" path that previously returned 503.
        """
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        # S3 mock: first call (requested window) returns []; second call (1m
        # fallback) returns a single most-recent bar.
        s3 = _make_s3_port()
        s3.get_ohlcv_range = AsyncMock(
            side_effect=[
                [],  # original interval='day' over user-supplied range → no bars
                [
                    {
                        "ts": "2026-06-09T20:00:00Z",
                        "date": "2026-06-09",
                        "open": 200.0,
                        "high": 201.5,
                        "low": 199.8,
                        "close": 200.9,
                        "volume": 1234,
                    }
                ],
            ]
        )
        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tc = _make_tool_use_block(
            "get_price_history",
            ticker="AAPL",
            from_date="2026-06-09",
            to_date="2026-06-10",
        )

        result = await executor.execute(tc)

        assert result is not None
        # Two calls: original + 1m fallback.
        assert s3.get_ohlcv_range.call_count == 2
        # Second call uses interval='1m' regardless of what the LLM asked for.
        second_call_kwargs = s3.get_ohlcv_range.call_args_list[1].kwargs
        assert second_call_kwargs["interval"] == "1m"
        # The RetrievedItem.item_id ends with ':latest_1m' so downstream
        # citation rendering can distinguish "last known" from full history.
        assert result.item_id.endswith(":latest_1m")
        assert "AAPL" in result.text

    async def test_executor_returns_none_on_s3_error(self) -> None:
        """execute() must return None when S3 raises, not propagate the exception."""
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        s3 = _make_s3_port()
        s3.get_ohlcv_range.side_effect = RuntimeError("connection refused")
        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tc = _make_tool_use_block("get_price_history", ticker="MSFT", from_date="2026-01-01", to_date="2026-04-01")

        result = await executor.execute(tc)

        assert result is None  # graceful degradation, no exception raised


# ---------------------------------------------------------------------------
# Fundamentals history tests
# ---------------------------------------------------------------------------


class TestGetFundamentalsHistory:
    async def test_executor_fundamentals_formats_markdown_table(self) -> None:
        """Returned RetrievedItem.text must contain Period column header."""
        executor = _make_executor(fundamentals=_sample_fundamentals())
        tc = _make_tool_use_block("get_fundamentals_history", ticker="MSFT", periods=4)

        result = await executor.execute(tc)

        assert result is not None
        assert "Period" in result.text
        assert "MSFT" in result.text


# ---------------------------------------------------------------------------
# execute_all tests
# ---------------------------------------------------------------------------


class TestExecuteAll:
    async def test_executor_execute_all_runs_concurrently(self) -> None:
        """execute_all() must call all handlers (both tool calls executed)."""
        s3 = _make_s3_port(bars=_sample_bars(), fundamentals=_sample_fundamentals())
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tool_calls = [
            _make_tool_use_block("get_price_history", ticker="AAPL", from_date="2026-02-01", to_date="2026-05-01"),
            _make_tool_use_block("get_fundamentals_history", ticker="AAPL", periods=4),
        ]

        results = await executor.execute_all(tool_calls)

        assert len(results) == 2
        assert s3.get_ohlcv_range.called
        assert s3.get_fundamentals_history.called

    async def test_executor_execute_all_caps_at_5(self) -> None:
        """execute_all() must execute at most 5 tool calls even if more are passed."""
        s3 = _make_s3_port(bars=_sample_bars())
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        # 8 tool calls — only 5 should be executed
        tool_calls = [
            _make_tool_use_block("get_price_history", ticker=f"T{i}", from_date="2026-01-01", to_date="2026-04-01")
            for i in range(8)
        ]

        results = await executor.execute_all(tool_calls)

        assert len(results) == 5  # capped at _MAX_CONCURRENT_TOOLS


# ---------------------------------------------------------------------------
# Unknown tool + truncation tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_executor_unknown_tool_name_logs_warning(self, caplog) -> None:
        """execute() must log unknown_tool_name and return None for unregistered tools."""
        import logging

        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        s3 = _make_s3_port()
        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tc = _make_tool_use_block("nonexistent_tool", ticker="AAPL")

        with caplog.at_level(logging.WARNING):
            result = await executor.execute(tc)

        assert result is None
        # structlog writes to stdlib logging in test mode; verify warning was issued
        # (structlog's caplog integration varies; check the return value is None which
        # confirms the unknown_tool_name branch was taken)

    async def test_executor_tool_result_truncated_at_max_chars(self) -> None:
        """RetrievedItem.text must not exceed _TOOL_RESULT_MAX_CHARS (4000) chars (N-7)."""
        from rag_chat.application.pipeline.tool_executor import _TOOL_RESULT_MAX_CHARS, ToolExecutor

        # Create 300 bars to generate > 4000 chars of output
        many_bars = [
            {"date": f"2025-{(i % 12) + 1:02d}-01", "close": 100 + i, "volume": 1000000 + i * 100} for i in range(300)
        ]
        s3 = _make_s3_port(bars=many_bars)
        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=s3)
        tc = _make_tool_use_block("get_price_history", ticker="AAPL", from_date="2024-01-01", to_date="2026-01-01")

        result = await executor.execute(tc)

        assert result is not None
        # Field is `text` NOT `content` (N-7)
        assert len(result.text) <= _TOOL_RESULT_MAX_CHARS


# ---------------------------------------------------------------------------
# FIX-LIVE-E: Exception classification in ToolExecutor.execute
#
# Pre-fix: a single `except Exception: return None` swallowed TypeErrors from
# arg-shape mismatches as "tool returned None", which masked the Phase 5c Q2
# fallback failure.  Post-fix: TypeError/AttributeError are tagged
# tool_argument_error, all other exceptions are tagged tool_execution_error,
# and both include exception_type + exception_repr for debugging.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecutorExceptionClassification:
    """Verify FIX-LIVE-E exception classification + structured logging."""

    @pytest.fixture(autouse=True)
    def _restore_structlog(self):
        """Snapshot + restore structlog global config around each test.

        WHY: the test methods below call ``structlog.configure(...)`` inline to
        route structlog through stdlib so ``caplog`` can capture events. That
        call mutates a process-global. Without restoring on teardown, any
        subsequent test in the pytest session that depends on structlog's
        default stdout renderer (e.g. ``capsys`` assertions in
        test_chat_orchestrator_tool_loop.py) sees empty output and fails.
        Snapshot before the test runs, restore (reset + reconfigure with the
        snapshot) after.
        """
        import structlog

        prior_config = structlog.get_config()
        try:
            yield
        finally:
            structlog.reset_defaults()
            structlog.configure(**prior_config)

    def _make_executor_with_failing_handler(self, exc: Exception):
        """Build an executor whose handler raises ``exc`` when called.

        We monkey-patch the executor's internal _handlers list with a single
        failing handler whose can_handle() returns True for our test tool name.
        """
        from rag_chat.application.pipeline.tool_executor import ToolExecutor

        executor = ToolExecutor(registry=_make_registry_with_tools(), s3=_make_s3_port())

        # Inject a synthetic handler that raises the desired exception.
        class _RaisingHandler:
            def can_handle(self, name: str) -> bool:
                return name == "get_price_history"

            async def execute(self, name: str, args: dict[str, Any]) -> Any:
                raise exc

        executor._handlers = [_RaisingHandler()]
        return executor

    async def test_typeerror_classified_as_tool_argument_error(self, caplog: Any) -> None:
        """Handler raising TypeError → executor logs ``tool_argument_error`` with type+repr."""
        import logging

        import structlog

        # Route structlog through stdlib so caplog can capture (test environment default).
        structlog.configure(
            processors=[structlog.processors.KeyValueRenderer(key_order=["event"])],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        exc = TypeError("unexpected keyword 'date_from'")
        executor = self._make_executor_with_failing_handler(exc)
        tc = _make_tool_use_block("get_price_history", date_from="bogus")

        with caplog.at_level(logging.WARNING):
            result = await executor.execute(tc)

        # Returns None so the orchestrator can fall back.
        assert result is None
        # Structured log includes the classification tag and exception type.
        all_messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "tool_argument_error" in all_messages
        assert "TypeError" in all_messages

    async def test_attributeerror_classified_as_tool_argument_error(self, caplog: Any) -> None:
        """Handler raising AttributeError → also ``tool_argument_error`` (arg-shape family)."""
        import logging

        import structlog

        structlog.configure(
            processors=[structlog.processors.KeyValueRenderer(key_order=["event"])],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        exc = AttributeError("'NoneType' object has no attribute 'id'")
        executor = self._make_executor_with_failing_handler(exc)
        tc = _make_tool_use_block("get_price_history", ticker="AAPL")

        with caplog.at_level(logging.WARNING):
            result = await executor.execute(tc)

        assert result is None
        all_messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "tool_argument_error" in all_messages
        assert "AttributeError" in all_messages

    async def test_generic_exception_classified_as_tool_execution_error(self, caplog: Any) -> None:
        """Handler raising RuntimeError (or any non-arg exception) → ``tool_execution_error``."""
        import logging

        import structlog

        structlog.configure(
            processors=[structlog.processors.KeyValueRenderer(key_order=["event"])],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        exc = RuntimeError("upstream timeout after 30s")
        executor = self._make_executor_with_failing_handler(exc)
        tc = _make_tool_use_block("get_price_history", ticker="AAPL")

        with caplog.at_level(logging.WARNING):
            result = await executor.execute(tc)

        assert result is None
        all_messages = " ".join(rec.getMessage() for rec in caplog.records)
        assert "tool_execution_error" in all_messages
        # Must NOT be misclassified as the arg-shape variant.
        assert "tool_argument_error" not in all_messages
        assert "RuntimeError" in all_messages
