"""Unit tests for the standalone document_ready_consumer_main entry point.

F-005/BP-704: this consumer main previously had NO ``start_metrics_server`` call
at all, so the Docker healthcheck (``GET http://localhost:9100/healthz``) hit a
port that refused the connection → the container was permanently UNHEALTHY. It is
also a Kafka consumer, so it must wire a stall-aware liveness probe and run under
the supervisor so a wedged/crashed poll loop flips ``/healthz`` to 503.

All infrastructure (DB, Kafka, Valkey) is patched — no real connections are made.
The flat ``main()`` coroutine is exercised by patching ``asyncio.Event`` to return
a pre-set event so the supervisor takes the graceful-stop path immediately.
"""

from __future__ import annotations

import asyncio
import os
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
    """Build a consumer mock whose run() blocks until stop() is signalled.

    A healthy consumer's run() only returns after stop(); with the supervisor a
    run() that returns instantly would be flagged as an unexpected wedge exit.
    """
    mock_consumer = MagicMock()
    gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=gate.set)
    return mock_consumer


def _mock_settings(**overrides: object) -> MagicMock:
    s = MagicMock()
    s.service_name = "content-ingestion"
    s.log_level = "INFO"
    s.log_json = False
    s.kafka_bootstrap_servers = "localhost:9092"
    s.valkey_url = "redis://localhost:6379/0"
    s.db_url = "postgresql+asyncpg://localhost/db"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _patches(mock_engine: AsyncMock, mock_valkey: AsyncMock, mock_consumer: MagicMock) -> list[object]:
    return [
        patch("content_ingestion.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_ingestion.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "content_ingestion.infrastructure.messaging.consumers." "document_ready_consumer.DocumentReadyConsumer",
            return_value=mock_consumer,
        ),
    ]


@pytest.mark.asyncio
async def test_document_ready_consumer_main_graceful_stop() -> None:
    """Pre-set stop_event → main() stops the consumer and runs full cleanup."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

    with patch("asyncio.Event", side_effect=_preset_event):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in _patches(mock_engine, mock_valkey, mock_consumer):
                stack.enter_context(p)
            from content_ingestion.infrastructure.messaging.consumers.document_ready_consumer_main import (
                main,
            )

            await main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_document_ready_consumer_main_binds_liveness_probe() -> None:
    """F-005/BP-704: start_metrics_server is called with a non-None liveness probe.

    This is the primary fix — the main had no metrics server at all, so /healthz
    refused the connection and the container was permanently UNHEALTHY.
    """
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _patches(mock_engine, mock_valkey, mock_consumer):
            stack.enter_context(p)
        mock_start_metrics = stack.enter_context(
            patch(
                "content_ingestion.infrastructure.messaging.consumers."
                "document_ready_consumer_main.start_metrics_server"
            )
        )
        stack.enter_context(patch("asyncio.Event", side_effect=_preset_event))
        from content_ingestion.infrastructure.messaging.consumers.document_ready_consumer_main import (
            main,
        )

        await main()

    mock_start_metrics.assert_called_once()
    assert mock_start_metrics.call_args.kwargs["liveness_probe"] is not None
