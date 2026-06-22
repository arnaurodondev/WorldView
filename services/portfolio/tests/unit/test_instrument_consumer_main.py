"""Unit tests for the standalone instrument_consumer_main entry point.

F-005/BP-704: this Kafka consumer main exposed ``start_metrics_server`` (so
/healthz existed) but did NOT wire a stall-aware liveness probe, so a wedged or
crashed poll loop kept a GREEN healthcheck and was never restarted. This test
locks in that the main now binds a liveness probe and runs under the supervisor.

All infrastructure (DB, Kafka) is patched — no real connections are made. The
flat ``main()`` coroutine is exercised by patching ``asyncio.Event`` to return a
pre-set event so the supervisor takes the graceful-stop path immediately.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force METRICS_PORT=0 so the real start_metrics_server (when not patched) picks
# an ephemeral port and never collides with the Docker stack's prometheus on 9100.
os.environ["METRICS_PORT"] = "0"

pytestmark = pytest.mark.unit

# Capture the real asyncio.Event class BEFORE any test patch replaces it.
_REAL_ASYNCIO_EVENT = asyncio.Event


def _preset_event(*_args: object, **_kwargs: object) -> asyncio.Event:
    """Return a real asyncio.Event that is already set."""
    e = _REAL_ASYNCIO_EVENT()
    e.set()
    return e


def _gated_consumer() -> MagicMock:
    """Consumer mock whose run() blocks until stop() is signalled."""
    mock_consumer = MagicMock()
    gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=gate.set)
    return mock_consumer


def _mock_settings(**overrides: object) -> MagicMock:
    s = MagicMock()
    s.service_name = "portfolio"
    s.log_level = "INFO"
    s.log_json = False
    s.kafka_bootstrap_servers = "localhost:9092"
    s.database_url = "postgresql+asyncpg://localhost/db"
    s.consumer_group_instrument = "portfolio-instrument-sync"
    s.topic_instrument_discovered = "market.instrument.discovered.v1"
    s.topic_instrument_created = "market.instrument.created"
    s.topic_instrument_updated = "market.instrument.updated"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _patches(mock_engine: AsyncMock, mock_consumer: MagicMock) -> list[object]:
    return [
        patch("portfolio.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "portfolio.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "portfolio.infrastructure.messaging.consumers.instrument_consumer.InstrumentEventConsumer",
            return_value=mock_consumer,
        ),
    ]


@pytest.mark.asyncio
async def test_instrument_consumer_main_graceful_stop() -> None:
    """Pre-set stop_event → main() stops the consumer and disposes the engine."""
    mock_engine = AsyncMock()
    mock_consumer = _gated_consumer()

    with ExitStack() as stack:
        for p in _patches(mock_engine, mock_consumer):
            stack.enter_context(p)
        stack.enter_context(patch("asyncio.Event", side_effect=_preset_event))
        from portfolio.infrastructure.messaging.consumers.instrument_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_instrument_consumer_main_binds_liveness_probe() -> None:
    """F-005/BP-704: start_metrics_server is called with a non-None liveness probe."""
    mock_engine = AsyncMock()
    mock_consumer = _gated_consumer()

    with ExitStack() as stack:
        for p in _patches(mock_engine, mock_consumer):
            stack.enter_context(p)
        mock_start_metrics = stack.enter_context(
            patch("portfolio.infrastructure.messaging.consumers.instrument_consumer_main.start_metrics_server")
        )
        stack.enter_context(patch("asyncio.Event", side_effect=_preset_event))
        from portfolio.infrastructure.messaging.consumers.instrument_consumer_main import main

        await main()

    mock_start_metrics.assert_called_once()
    assert mock_start_metrics.call_args.kwargs["liveness_probe"] is not None
