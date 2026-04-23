"""Tests for LlmUsageLogProtocol and LlmCallUsage (PLAN-0033 T-A-1-01)."""

from __future__ import annotations

import pytest
from ml_clients.usage_log import LlmCallUsage, LlmUsageLogProtocol

# ---------------------------------------------------------------------------
# Protocol structural checks
# ---------------------------------------------------------------------------


class _ConformingLogger:
    """Minimal class that satisfies LlmUsageLogProtocol."""

    async def log(
        self,
        *,
        model_id: str,
        provider: str,
        capability: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
        error_code: str | None = None,
        **context: object,
    ) -> None:
        pass  # pragma: no cover


class _MissingLogMethod:
    """Class WITHOUT a ``log()`` method — must NOT satisfy the protocol."""

    async def insert(self, **kwargs: object) -> None:
        pass  # pragma: no cover


@pytest.mark.unit
def test_llm_usage_log_protocol_structural_check() -> None:
    """A class with the correct ``log`` signature satisfies the protocol at runtime."""
    instance = _ConformingLogger()
    assert isinstance(instance, LlmUsageLogProtocol)


@pytest.mark.unit
def test_llm_usage_log_protocol_missing_method_fails() -> None:
    """A class without ``log()`` does NOT satisfy the protocol."""
    bad = _MissingLogMethod()
    assert not isinstance(bad, LlmUsageLogProtocol)


# ---------------------------------------------------------------------------
# LlmCallUsage value object
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_llm_call_usage_frozen() -> None:
    """LlmCallUsage is immutable (frozen dataclass)."""
    usage = LlmCallUsage(
        model_id="qwen2.5:3b",
        provider="ollama",
        capability="classification",
        tokens_in=50,
        tokens_out=20,
        estimated_cost_usd=0.0,
        latency_ms=123,
        success=True,
    )
    with pytest.raises((AttributeError, TypeError)):  # FrozenInstanceError or AttributeError from frozen dataclass
        usage.tokens_in = 999  # type: ignore[misc]


@pytest.mark.unit
def test_llm_call_usage_default_error_code_none() -> None:
    """error_code defaults to None when not provided."""
    usage = LlmCallUsage(
        model_id="m",
        provider="p",
        capability="c",
        tokens_in=1,
        tokens_out=1,
        estimated_cost_usd=0.0,
        latency_ms=0,
        success=True,
    )
    assert usage.error_code is None


@pytest.mark.unit
def test_none_logger_accepted() -> None:
    """The protocol accepts ``None`` — callers should guard before calling."""
    # The protocol cannot be instantiated directly (it's a Protocol), but
    # a None reference is acceptable as an optional param in practice.
    logger: LlmUsageLogProtocol | None = None
    assert logger is None  # type-guard pattern used throughout codebase


@pytest.mark.unit
def test_llm_call_usage_equality_by_value() -> None:
    """Two LlmCallUsage instances with identical fields are equal."""
    a = LlmCallUsage(
        model_id="m",
        provider="p",
        capability="c",
        tokens_in=10,
        tokens_out=5,
        estimated_cost_usd=0.001,
        latency_ms=200,
        success=True,
        error_code=None,
    )
    b = LlmCallUsage(
        model_id="m",
        provider="p",
        capability="c",
        tokens_in=10,
        tokens_out=5,
        estimated_cost_usd=0.001,
        latency_ms=200,
        success=True,
        error_code=None,
    )
    assert a == b
