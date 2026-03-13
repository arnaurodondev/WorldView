"""Integration tests for outbox dispatch pipeline (T-MI-26).

Requires live PostgreSQL + Kafka. Skip otherwise.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

_NEEDS_INFRA = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)",
)

_NEEDS_KAFKA = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS"),
    reason="Requires live Kafka (set MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS)",
)


@_NEEDS_INFRA
@_NEEDS_KAFKA
@pytest.mark.asyncio
async def test_dispatcher_starts_and_stops_cleanly():
    """DispatcherProcess starts and stops without error."""
    from market_ingestion.config import Settings
    from market_ingestion.messaging.dispatcher_main import DispatcherProcess

    settings = Settings()
    process = DispatcherProcess(settings=settings)
    process.stop()  # Stop immediately — just tests lifecycle
    await process.run()


# ---------------------------------------------------------------------------
# Unit-level outbox dispatch tests (no real infra)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatcher_process_build_uses_settings():
    """DispatcherProcess builds kafka config from settings."""
    from market_ingestion.messaging.dispatcher_main import DispatcherProcess

    settings = MagicMock()
    settings.database_url = "postgresql+asyncpg://x:x@localhost/test"
    settings.database_url_read = ""
    settings.kafka_bootstrap_servers = "kafka:9092"
    settings.schema_registry_url = "http://schema-registry:8081"

    with (
        patch(
            "market_ingestion.messaging.dispatcher_main._build_factories",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch("market_ingestion.messaging.dispatcher_main.build_market_ingestion_dispatcher") as mock_build,
    ):
        mock_dispatcher = MagicMock()
        mock_dispatcher.run = AsyncMock()
        mock_build.return_value = mock_dispatcher

        DispatcherProcess(settings=settings)

        # Verify settings (with kafka_bootstrap_servers) was passed correctly;
        # no raw Kafka config dict is passed as DispatcherConfig.
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["settings"] is settings
        assert "config" not in call_kwargs or call_kwargs["config"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_outbox_dispatcher_claim_and_publish_flow():
    """MarketIngestionOutboxDispatcher._dispatch_batch flow with mock outbox."""
    from market_ingestion.infrastructure.messaging.dispatcher import (
        MarketIngestionOutboxDispatcher,
    )

    settings = MagicMock()
    settings.schema_registry_url = "http://localhost:8081"
    settings.kafka_bootstrap_servers = "localhost:9092"

    write_factory = MagicMock()
    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)
    mock_uow.commit = AsyncMock()

    # Empty outbox — nothing to dispatch
    mock_uow.outbox = MagicMock()
    mock_uow.outbox.claim_batch = AsyncMock(return_value=[])

    dispatcher = MarketIngestionOutboxDispatcher(
        settings=settings,
        write_factory=write_factory,
    )

    # Patch UoW construction to return the mock
    with patch(
        "market_ingestion.infrastructure.messaging.dispatcher.SqlaUnitOfWork",
        return_value=mock_uow,
    ):
        await dispatcher._dispatch_batch()

    # No records → claim_batch called once, no publish
    mock_uow.outbox.claim_batch.assert_called_once()
