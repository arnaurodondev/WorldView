"""Shared test fixtures for observability library."""

from __future__ import annotations

import pytest
import structlog


@pytest.fixture(autouse=True)
def reset_otel_provider() -> None:
    """Reset the OTel global TracerProvider before each test.

    OTel only allows setting the TracerProvider once per process.  This fixture
    resets the internal ``_TRACER_PROVIDER_SET_ONCE`` flag and ``_TRACER_PROVIDER``
    so each test starts with a clean slate.
    """
    import opentelemetry.trace as trace_api

    # Reset global provider state
    trace_api._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    trace_api._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def reset_structlog() -> None:
    """Clear structlog context variables between tests."""
    structlog.contextvars.clear_contextvars()
