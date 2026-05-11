"""TriggerBrokerageSync use case — run a single brokerage sync cycle (F-013).

Extracted from the inline ``_run_single_sync`` background task in
``brokerage_connections.py`` to respect R25 (API routes use only use cases)
and LAYER-APP-ISOLATION (no infrastructure imports in application layer).

The use case delegates to ``BrokerageTransactionSyncWorker._sync_connection``
which already contains the full sync logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from portfolio.application.ports.brokerage_client import IBrokerageClient
    from portfolio.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class TriggerBrokerageSync:
    """Execute a single on-demand brokerage sync for one connection.

    Designed for fire-and-forget background tasks initiated by the
    ``POST /brokerage-connections/{id}/sync`` endpoint.  Errors are
    logged but never propagated (the HTTP 202 was already sent).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        brokerage_client: IBrokerageClient,
        settings: Settings,
        cipher: Fernet | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._brokerage_client = brokerage_client
        self._settings = settings
        self._cipher = cipher

    async def execute(self, connection: Any) -> None:
        """Run the sync cycle for *connection*, suppressing all exceptions."""
        import httpx

        from portfolio.workers.brokerage_sync_worker import BrokerageTransactionSyncWorker

        try:
            worker = BrokerageTransactionSyncWorker(
                session_factory=self._session_factory,
                brokerage_client=self._brokerage_client,
                settings=self._settings,
                cipher=self._cipher,
            )

            # Scoped HTTP client so S3 instrument resolution works.
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                worker._http_client = http_client
                await worker._sync_connection(connection)

        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "brokerage_force_sync_background_error",
                connection_id=str(connection.id),
                error=str(exc),
            )
