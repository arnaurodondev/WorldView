"""BrokerageTransactionSyncWorker — background process that syncs brokerage transactions.

Runs every `brokerage_sync_cycle_seconds` (default: 4 h).  For each ACTIVE or ERROR
brokerage connection it fetches activities from SnapTrade and replays them through
`RecordTransactionUseCase`.

Entry point:
    python -m portfolio.workers.brokerage_sync_worker

Security notes:
    R-001: Fernet cipher must be threaded through every SqlAlchemyUnitOfWork created
           here so that encrypted snaptrade_user_secret is decrypted before use.
    R-002: Instrument ticker symbols are URL-encoded before being embedded in HTTP
           paths — SnapTrade tickers can contain '.', '/', etc.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.brokerage_client import SnapTradeUser
from portfolio.application.use_cases.record_transaction import RecordTransactionCommand, RecordTransactionUseCase
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import SyncErrorType, TransactionDirection, TransactionType
from portfolio.domain.errors import BrokerageApiError, IdempotencyConflictError
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from portfolio.infrastructure.metrics.prometheus import (
    BROKERAGE_SYNC_CYCLE_DURATION,
    BROKERAGE_SYNC_TRANSACTIONS_TOTAL,
)

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from portfolio.application.ports.brokerage_client import IBrokerageClient, SnapTradeActivity
    from portfolio.config import Settings
    from portfolio.domain.entities.brokerage_connection import BrokerageConnection
    from portfolio.domain.entities.instrument import InstrumentRef

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Transaction type mapping (PRD-0022 §6.5) ──────────────────────────────────
#
# Keys are the raw activity_type strings returned by SnapTrade.
# Values are (TransactionType, TransactionDirection) tuples.

_TYPE_MAP: dict[str, tuple[TransactionType, TransactionDirection]] = {
    # direction = asset direction (INFLOW = holdings increase, OUTFLOW = holdings decrease)
    # This is the same semantic used by RecordTransactionUseCase (qty_delta positive on INFLOW).
    # Note: the PRD §6.5 table uses cash direction (opposite), but the domain model is authoritative.
    "BUY": (TransactionType.BUY, TransactionDirection.INFLOW),
    "SELL": (TransactionType.SELL, TransactionDirection.OUTFLOW),
    "DIV": (TransactionType.DIVIDEND, TransactionDirection.INFLOW),
    "DIVIDEND": (TransactionType.DIVIDEND, TransactionDirection.INFLOW),
}


class BrokerageTransactionSyncWorker:
    """Background worker: iterate active/error connections and sync transactions.

    Dependencies are injected so that unit tests can substitute fakes without
    touching the database or SnapTrade API.
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
        self._http_client: httpx.AsyncClient | None = None

    # ── Public entry points ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop — runs indefinitely, sleeping between cycles."""
        logger.info(  # type: ignore[no-any-return]
            "brokerage_sync_worker_started",
            cycle_seconds=self._settings.brokerage_sync_cycle_seconds,
        )
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            self._http_client = http_client
            while True:
                try:
                    with BROKERAGE_SYNC_CYCLE_DURATION.time():
                        await self.sync_cycle()
                except Exception as exc:
                    logger.error("sync_cycle_error", error=str(exc))  # type: ignore[no-any-return]
                await asyncio.sleep(self._settings.brokerage_sync_cycle_seconds)

    async def sync_cycle(self) -> None:
        """Single sync pass over all active/error connections."""
        # Load connections — close UoW before any SnapTrade calls (BP-057)
        async with SqlAlchemyUnitOfWork(  # type: ignore[call-arg]
            self._session_factory,
            snaptrade_cipher=self._cipher,
        ) as uow:
            connections = await uow.brokerage_connections.list_active_or_error()

        for connection in connections:
            await self._sync_connection(connection)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _sync_connection(self, connection: BrokerageConnection) -> None:
        """Fetch and process activities for a single brokerage connection.

        Opens a fresh UoW per connection to keep transactions short (BP-057).
        Always passes snaptrade_cipher so encrypted secrets are decrypted (R-001).
        """
        # Determine date range
        today = datetime.now(tz=UTC).date()
        if connection.last_sync_cursor:
            start_date = datetime.fromisoformat(connection.last_sync_cursor).date()
        else:
            start_date = today - timedelta(days=self._settings.brokerage_sync_history_days)
        end_date = today

        # Call SnapTrade BEFORE opening the write UoW (BP-057)
        snap_user = SnapTradeUser(
            snaptrade_user_id=connection.snaptrade_user_id,
            snaptrade_user_secret=connection.snaptrade_user_secret,
            # snaptrade_user_secret intentionally not logged
        )
        try:
            # TODO: verify SnapTrade SDK pagination for accounts with >1000 activities (OQ-002)
            activities = await self._brokerage_client.get_activities(
                user=snap_user,
                start=start_date,
                end=end_date,
            )
        except BrokerageApiError:
            logger.warning(  # type: ignore[no-any-return]
                "brokerage_sync_api_error",
                connection_id=str(connection.id),
                # snaptrade_user_secret intentionally omitted
            )
            async with SqlAlchemyUnitOfWork(  # type: ignore[call-arg]
                self._session_factory,
                snaptrade_cipher=self._cipher,
            ) as uow:
                connection.mark_error()
                await uow.brokerage_connections.save(connection)
                await uow.commit()
            return

        async with SqlAlchemyUnitOfWork(  # type: ignore[call-arg]
            self._session_factory,
            snaptrade_cipher=self._cipher,
        ) as uow:
            for activity in activities:
                await self._process_activity(connection, activity, uow)

            # Update cursor and status regardless of individual activity errors
            from common.time import utc_now  # type: ignore[import-untyped]

            connection.last_synced_at = utc_now()
            connection.last_sync_cursor = end_date.isoformat()
            if connection.status.value == "error":
                # Recovery: successful API fetch after previous error
                from portfolio.domain.enums import ConnectionStatus

                connection.status = ConnectionStatus.ACTIVE

            await uow.brokerage_connections.save(connection)
            await uow.commit()

        logger.info(  # type: ignore[no-any-return]
            "brokerage_sync_connection_done",
            connection_id=str(connection.id),
            activity_count=len(activities),
        )

    async def _process_activity(
        self,
        connection: BrokerageConnection,
        activity: SnapTradeActivity,
        uow: SqlAlchemyUnitOfWork,  # type: ignore[type-arg]
    ) -> None:
        """Process a single SnapTrade activity into a transaction record."""
        from common.ids import new_uuid  # type: ignore[import-untyped]

        # 1. Type check
        mapping = _TYPE_MAP.get(activity.activity_type.upper())
        if mapping is None:
            await uow.brokerage_sync_errors.save(
                BrokerageTransactionSyncError(
                    id=new_uuid(),
                    connection_id=connection.id,
                    snaptrade_transaction_id=activity.snaptrade_transaction_id,
                    error_type=SyncErrorType.UNSUPPORTED_TYPE,
                    error_detail=f"Unsupported activity type: {activity.activity_type!r}",
                ),
            )
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="unsupported_type").inc()
            return

        tx_type, direction = mapping

        # 2. Dedup check — skip if already recorded (idempotent)
        existing = await uow.transactions.find_by_external_ref(
            connection.portfolio_id,
            connection.tenant_id,
            activity.snaptrade_transaction_id,
        )
        if existing is not None:
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="duplicate").inc()
            return

        # 3. Instrument resolution
        instrument = await self._resolve_instrument(activity.symbol, uow)
        if instrument is None:
            await uow.brokerage_sync_errors.save(
                BrokerageTransactionSyncError(
                    id=new_uuid(),
                    connection_id=connection.id,
                    snaptrade_transaction_id=activity.snaptrade_transaction_id,
                    error_type=SyncErrorType.UNKNOWN_INSTRUMENT,
                    error_detail=f"Instrument not found for symbol: {activity.symbol!r}",
                ),
            )
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="unknown_instrument").inc()
            return

        # 4. Record transaction via use case
        cmd = RecordTransactionCommand(
            tenant_id=connection.tenant_id,
            portfolio_id=connection.portfolio_id,
            owner_id=connection.user_id,
            instrument_id=instrument.id,
            transaction_type=tx_type,
            direction=direction,
            quantity=Decimal(str(activity.quantity)),
            price=Decimal(str(activity.price)),
            currency=activity.currency,
            executed_at=activity.executed_at,
            external_ref=activity.snaptrade_transaction_id,
        )
        try:
            await RecordTransactionUseCase().execute(cmd, uow)
        except IdempotencyConflictError:
            # Duplicate external_ref — already recorded; silently skip (F-13)
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="duplicate").inc()
            return
        except Exception as exc:
            await uow.brokerage_sync_errors.save(
                BrokerageTransactionSyncError(
                    id=new_uuid(),
                    connection_id=connection.id,
                    snaptrade_transaction_id=activity.snaptrade_transaction_id,
                    error_type=SyncErrorType.VALIDATION_ERROR,
                    error_detail=str(exc),
                ),
            )
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="failed", error_type="validation_error").inc()
            return

        BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="success", error_type="").inc()

    async def _resolve_instrument(
        self,
        symbol: str,
        uow: SqlAlchemyUnitOfWork,  # type: ignore[type-arg]
    ) -> InstrumentRef | None:
        """Resolve instrument by symbol — first DB, then S3 (market-data) fallback."""
        # Primary: local DB lookup (case-insensitive)
        instrument = await uow.instruments.get_by_symbol(symbol)
        if instrument is not None:
            return instrument

        # Fallback: call market-data service (S3)
        if self._http_client is None:
            return None

        # R-002: URL-encode symbol — SnapTrade tickers can contain '.', '/', etc.
        encoded_symbol = urllib.parse.quote(symbol, safe="")
        try:
            response = await self._http_client.get(
                f"{self._settings.market_data_service_url}/api/v1/instruments/{encoded_symbol}",
            )
        except Exception:
            return None

        if response.status_code != 200:
            return None

        data = response.json()
        from common.ids import new_uuid  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]
        from portfolio.domain.entities.instrument import InstrumentRef

        instrument = InstrumentRef(
            id=new_uuid(),
            symbol=data.get("symbol", symbol),
            exchange=data.get("exchange", ""),
            name=data.get("name"),
            currency=data.get("currency"),
            asset_class=data.get("asset_class"),
            entity_id=None,
            source_event_id=new_uuid(),  # placeholder — no Kafka event backing S3 resolution
            synced_at=utc_now(),
        )
        instrument = await uow.instruments.upsert(instrument)
        return instrument


# ── Process entry point ───────────────────────────────────────────────────────


async def main() -> None:
    """Wire dependencies and start the sync worker."""
    from observability import configure_logging  # type: ignore[import-untyped]
    from portfolio.config import Settings
    from portfolio.infrastructure.brokerage.snaptrade_client import SnapTradeClient
    from portfolio.infrastructure.db.session import _build_factories

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="portfolio-brokerage-sync-worker",
        level=settings.log_level,
        json=settings.log_json,
    )

    # R-001: Build Fernet cipher so encrypted snaptrade_user_secret is decrypted.
    # Without this, when SNAPTRADE_SECRET_ENCRYPTION_KEY is set the worker passes
    # raw ciphertext to SnapTrade — causing all sync operations to fail silently.
    from cryptography.fernet import Fernet  # type: ignore[import-untyped]

    cipher: Fernet | None = None
    if settings.snaptrade_secret_encryption_key:
        cipher = Fernet(settings.snaptrade_secret_encryption_key.encode())

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    brokerage_client = SnapTradeClient(
        client_id=settings.snaptrade_client_id.get_secret_value(),
        consumer_key=settings.snaptrade_consumer_key.get_secret_value(),
    )
    worker = BrokerageTransactionSyncWorker(
        session_factory=write_factory,
        brokerage_client=brokerage_client,
        settings=settings,
        cipher=cipher,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
