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
import contextlib
import hashlib
import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import jwt as pyjwt
from sqlalchemy import text

from observability import get_logger, start_metrics_server  # type: ignore[import-untyped]
from portfolio.application.ports.brokerage_client import SnapTradeUser
from portfolio.application.use_cases.record_transaction import RecordTransactionCommand, RecordTransactionUseCase
from portfolio.application.use_cases.upsert_holdings_from_snapshot import (
    ResolvedSnapshotPosition,
    UpsertHoldingsFromSnapshotCommand,
    UpsertHoldingsFromSnapshotUseCase,
)
from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError
from portfolio.domain.enums import SyncErrorType, TransactionDirection, TransactionType
from portfolio.domain.errors import (
    BrokerageApiError,
    BrokerageSyncSymbolNotFoundError,
    IdempotencyConflictError,
    InstrumentResolutionTransientError,
)
from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from portfolio.infrastructure.metrics.prometheus import (
    BROKERAGE_SYNC_CYCLE_DURATION,
    BROKERAGE_SYNC_TRANSACTIONS_TOTAL,
)

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from portfolio.application.ports.brokerage_client import IBrokerageClient, SnapTradeActivity, SnapTradePosition
    from portfolio.application.ports.instrument_lookup_client import IInstrumentLookupClient
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
    # NOTE: FEE / INTEREST intentionally absent — they are cash-only activities
    # (no instrument_id) and are intercepted by _CASH_ACTIVITY_TYPES before this
    # map is consulted. They will be added here once the transactions table
    # supports nullable instrument_id (BP-501).
}

# ── Cash-only activity types (BP-501) ────────────────────────────────────────
#
# FEE and INTEREST come from SnapTrade without a tradable symbol. The current
# transactions schema has instrument_id NOT NULL, so they cannot be recorded
# yet. Intercept them before the instrument-lookup step so they don't produce
# UNSUPPORTED_TYPE sync errors in the brokerage panel — they are expected, not
# failures. A future schema change (nullable instrument_id + cash tx support)
# will remove this set and add the types to _TYPE_MAP.
_CASH_ACTIVITY_TYPES: frozenset[str] = frozenset({"FEE", "INTEREST"})


# ── BUG-003 / TASK-W1-03 ─────────────────────────────────────────────────────
#
# Per-connection advisory lock helpers. Two worker replicas can otherwise iterate
# the same active ``BrokerageConnection`` concurrently and double-record
# activities before the snapshot upsert at the end of ``_sync_connection``
# stabilises — visible to the user as inflated holdings for 5-60s, or
# permanently if the snapshot fetch fails after the partial replay.
#
# We use ``pg_try_advisory_xact_lock`` (non-blocking, auto-released on
# COMMIT/ROLLBACK) keyed off a deterministic 63-bit int derived from the
# connection UUID. ``hashlib.blake2b`` is used instead of Python's built-in
# ``hash()`` because the latter is randomised per process (PYTHONHASHSEED),
# which would defeat cross-replica coordination.
#
# Scoping: the lock must be held INSIDE the same Postgres transaction that
# performs the writes. The simplest minimal-refactor approach (which preserves
# BP-057's "no SnapTrade calls while a write UoW is open" rule for the
# inner work-UoWs) is to open ONE outermost "lock UoW" at the start of
# ``_sync_connection`` whose only job is to hold the advisory lock for the
# duration of the per-connection sync. The lock UoW is never committed —
# ``__aexit__`` rolls it back which releases the xact-scoped lock cleanly.


def _connection_lock_key(connection_id: UUID) -> int:
    """Derive a deterministic 63-bit positive int from a connection UUID.

    PostgreSQL bigint is signed 64-bit; we mask to 63 bits to guarantee a
    positive value (some PG clients log negative advisory keys oddly). The
    use of blake2b — not ``hash()`` — is required: built-in ``hash()`` is
    randomised across processes when ``PYTHONHASHSEED`` is not set, which
    would cause two replicas to derive DIFFERENT lock keys for the same
    connection and the advisory lock would not coordinate them.
    """
    digest = hashlib.blake2b(str(connection_id).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & 0x7FFF_FFFF_FFFF_FFFF


async def _try_acquire_connection_lock(uow: SqlAlchemyUnitOfWork, connection_id: UUID) -> bool:  # type: ignore[type-arg]
    """Attempt non-blocking advisory lock for ``connection_id`` on ``uow``'s txn.

    Returns ``True`` if acquired, ``False`` if another worker already holds it.
    The lock is automatically released when ``uow``'s transaction ends
    (commit OR rollback) — callers do not need to release it explicitly.

    Lives as a module-level helper (not a UoW method) because the lock is a
    worker-specific concern; adding it to the UoW would leak infrastructure
    detail into every other call site that doesn't need it.
    """
    lock_key = _connection_lock_key(connection_id)
    # Access the underlying session via the private attribute. The UoW does not
    # expose a public ``session`` accessor and we'd rather not widen the
    # public interface for this single use case.
    session = uow._session  # intentional: see comment above
    assert session is not None, "UoW must be entered before acquiring a lock"
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": lock_key},
    )
    return bool(result.scalar())


def _system_jwt_headers(settings: Settings) -> dict[str, str]:
    """Generate X-Internal-JWT for service-to-service calls to market-data.

    WHY: Market-data uses InternalJWTMiddleware which requires X-Internal-JWT on
    every request. The brokerage-sync worker calls market-data directly (not via
    S9), so it cannot obtain an RS256-signed JWT from the gateway. In dev,
    market-data is configured with skip_verification=True which accepts any
    decodable JWT. The HS256 token here is only for dev — production would
    require a proper service account token from S9.
    """
    now = int(time.time())
    token = pyjwt.encode(
        {
            "iss": "worldview-gateway",
            "sub": "system:brokerage-sync",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            "exp": now + 86400,
        },
        settings.brokerage_sync_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {"X-Internal-JWT": token}


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
        instrument_lookup: IInstrumentLookupClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._brokerage_client = brokerage_client
        self._settings = settings
        self._cipher = cipher
        self._http_client: httpx.AsyncClient | None = None
        # PRD-0089 F2 §4.4 — single canonical symbol→instrument_id resolver.
        # ``None`` means "construct one lazily from the worker's httpx client".
        # Tests inject a fake directly; production wires HttpInstrumentLookupClient
        # in main() once the shared httpx client is available.
        self._instrument_lookup: IInstrumentLookupClient | None = instrument_lookup

    # ── Public entry points ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Main loop — runs indefinitely, sleeping between cycles."""
        logger.info(  # type: ignore[no-any-return]
            "brokerage_sync_worker_started",
            cycle_seconds=self._settings.brokerage_sync_cycle_seconds,
        )
        async with httpx.AsyncClient(timeout=10.0, headers=_system_jwt_headers(self._settings)) as http_client:
            self._http_client = http_client
            # If no lookup client was injected, build the production HTTP adapter
            # against the shared httpx client. Tests inject a fake at __init__ time
            # so this branch is a no-op there. Constructed here (not in __init__)
            # so the adapter shares the same connection pool / auth headers as the
            # rest of the worker.
            if self._instrument_lookup is None:
                from portfolio.infrastructure.market_data.instrument_lookup_client import (
                    HttpInstrumentLookupClient,
                )

                self._instrument_lookup = HttpInstrumentLookupClient(
                    http=http_client,
                    market_data_url=self._settings.market_data_service_url,
                )
            while True:
                # PLAN-0052 platform-QA round 4 (2026-05-01): bounded
                # exponential backoff retry. Previously ONE transient
                # exception (typically a Docker DNS race or SnapTrade API
                # blip — error `[Errno -2] Name or service not known`)
                # logged `sync_cycle_error` and skipped the entire cycle,
                # so the next sync was 4h away. Live state showed 3 such
                # skips in 12h — TastyTrade holdings going stale because
                # one DNS hiccup ate the whole window. Three retries with
                # 30s/60s/120s delays bring the worker back in <4 minutes
                # of wall-clock without changing the steady-state cadence.
                # If all 3 retries fail, log the final error and sleep
                # the full cycle (preserves the pre-fix behavior — no
                # tighter retry storm than 4h).
                cycle_succeeded = False
                for delay_s in (0, 30, 60, 120):
                    if delay_s:
                        logger.warning(  # type: ignore[no-any-return]
                            "sync_cycle_retry",
                            delay_s=delay_s,
                        )
                        await asyncio.sleep(delay_s)
                    try:
                        with BROKERAGE_SYNC_CYCLE_DURATION.time():
                            await self.sync_cycle()
                        cycle_succeeded = True
                        break
                    except Exception as exc:
                        logger.warning(  # type: ignore[no-any-return]
                            "sync_cycle_attempt_failed",
                            attempt_delay_s=delay_s,
                            error=str(exc),
                        )
                if not cycle_succeeded:
                    logger.error(  # type: ignore[no-any-return]
                        "sync_cycle_error_exhausted",
                        retries=3,
                    )
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

        BUG-003 / TASK-W1-03: per-connection advisory lock — if another worker
        replica is already syncing the same ``connection.id`` we return
        immediately and let the next cycle pick it up. This is non-blocking
        (``pg_try_advisory_xact_lock``) so two replicas never queue or
        double-count holdings during the snapshot-upsert reconciliation window.
        """
        # ── Per-connection advisory lock ─────────────────────────────────────
        # The outer UoW exists only to hold the xact-scoped lock for the
        # duration of this method. We deliberately do NOT call ``commit()`` on
        # it: ``__aexit__`` will rollback (no writes were issued on this UoW
        # anyway) which releases the lock cleanly.
        async with SqlAlchemyUnitOfWork(  # type: ignore[call-arg]
            self._session_factory,
            snaptrade_cipher=self._cipher,
        ) as lock_uow:
            acquired = await _try_acquire_connection_lock(lock_uow, connection.id)
            if not acquired:
                logger.info(  # type: ignore[no-any-return]
                    "brokerage_sync_skipped_lock_held",
                    connection_id=str(connection.id),
                )
                return
            await self._do_sync_connection(connection)

    async def _do_sync_connection(self, connection: BrokerageConnection) -> None:
        """Inner per-connection sync — runs under the caller's advisory lock.

        Extracted from ``_sync_connection`` so the lock-scoping context manager
        stays compact and the existing sync semantics (multiple inner UoWs,
        BP-057 ordering) remain unchanged inside this method.
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

        # ── BP-264 (PLAN-0046 T-46-1-03) ─────────────────────────────────────
        # AFTER the activity sync, fetch the broker's authoritative position
        # snapshot and overwrite the holdings table for this portfolio. This is
        # what stops the cumulative-replay drift that produced 8-10x inflated
        # quantities. Snapshot fetch is best-effort: on failure we log and
        # continue so transient SnapTrade errors don't hold up other connections.
        try:
            await self._sync_holdings_from_snapshot(connection, snap_user)
        except BrokerageApiError as exc:
            logger.warning(  # type: ignore[no-any-return]
                "brokerage_sync_snapshot_failed",
                connection_id=str(connection.id),
                error=type(exc).__name__,
            )

        logger.info(  # type: ignore[no-any-return]
            "brokerage_sync_connection_done",
            connection_id=str(connection.id),
            activity_count=len(activities),
        )

    async def _sync_holdings_from_snapshot(
        self,
        connection: BrokerageConnection,
        snap_user: SnapTradeUser,
    ) -> None:
        """Fetch broker-truth positions and overwrite local holdings.

        PLAN-0046 / BP-264: positions across all linked accounts for this user
        are aggregated by symbol, resolved to ``instrument_id`` via the same
        path activities use (DB-first, S3 fallback), and handed to
        ``UpsertHoldingsFromSnapshotUseCase`` which performs the diff and
        emits HoldingChanged events for every change.
        """
        # 1. Get account ids
        account_ids = await self._brokerage_client.list_account_ids(snap_user)

        # 2. Fetch positions per account, concatenate
        all_positions: list[SnapTradePosition] = []
        for account_id in account_ids:
            try:
                positions = await self._brokerage_client.get_account_positions(snap_user, account_id)
                all_positions.extend(positions)
            except BrokerageApiError as exc:
                # One bad account shouldn't kill the whole sync.
                logger.warning(  # type: ignore[no-any-return]
                    "brokerage_sync_account_positions_failed",
                    account_id=account_id,
                    error=type(exc).__name__,
                )

        # 3. Resolve symbols → instrument_ids inside a fresh UoW (write-capable
        #    so we can upsert instrument refs that come from the S3 fallback).
        async with SqlAlchemyUnitOfWork(  # type: ignore[call-arg]
            self._session_factory,
            snaptrade_cipher=self._cipher,
        ) as uow:
            resolved: list[ResolvedSnapshotPosition] = []
            for pos in all_positions:
                try:
                    instrument = await self._resolve_instrument(pos.symbol, uow)
                except InstrumentResolutionTransientError:
                    # Skip transient resolution failures — next sync will retry.
                    continue
                except BrokerageSyncSymbolNotFoundError:
                    # Unknown symbol — skip; we don't error-record positions
                    # the same way we do activities (positions are an overview).
                    continue
                resolved.append(
                    ResolvedSnapshotPosition(
                        instrument_id=instrument.id,
                        quantity=pos.quantity,
                        average_cost=pos.average_purchase_price,
                        currency=pos.currency or "USD",
                    ),
                )

            # BP-500: Guard — if the broker returned positions but ALL failed
            # instrument resolution, calling the use case with resolved=[] would
            # delete every existing holding (the use case treats "absent from
            # snapshot = closed position"). This happens when S2 doesn't know a
            # symbol yet (seeding gap). Skip the upsert so existing holdings
            # survive; the next sync will retry after instruments are seeded.
            if all_positions and not resolved:
                logger.warning(  # type: ignore[no-any-return]
                    "brokerage_sync_snapshot_all_unresolved",
                    connection_id=str(connection.id),
                    portfolio_id=str(connection.portfolio_id),
                    total_positions=len(all_positions),
                )
                return

            # PLAN-0109 Sub-Plan G — gate holding.changed emission behind
            # ``PORTFOLIO_EMIT_HOLDING_CHANGED`` (default false). No consumer
            # exists today; flip the env var when alert's position-closure
            # rule lands.
            await UpsertHoldingsFromSnapshotUseCase(
                emit_holding_changed_events=self._settings.emit_holding_changed_events,
            ).execute(
                UpsertHoldingsFromSnapshotCommand(
                    tenant_id=connection.tenant_id,
                    portfolio_id=connection.portfolio_id,
                    positions=resolved,
                ),
                uow,
            )

    async def _process_activity(
        self,
        connection: BrokerageConnection,
        activity: SnapTradeActivity,
        uow: SqlAlchemyUnitOfWork,  # type: ignore[type-arg]
    ) -> None:
        """Process a single SnapTrade activity into a transaction record."""
        from common.ids import new_uuid  # type: ignore[import-untyped]

        # 0. Cash-only activity types — silently skip, no sync error.
        # BP-501: FEE/INTEREST have no instrument_id; transactions.instrument_id
        # is NOT NULL so they can't be recorded until the schema supports cash
        # transactions. Skipping without an error record keeps the brokerage
        # panel clean — these are expected, not failures.
        if activity.activity_type.upper() in _CASH_ACTIVITY_TYPES:
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="cash_activity").inc()
            return

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
        #
        # PRD-0089 F2 §4.4 — single canonical S2 lookup. Two distinct failure
        # modes still need to be told apart (F-007):
        #   a) Genuine 404 → S2 does not know this symbol → UNKNOWN_INSTRUMENT
        #   b) Network exception or 5xx → transient outage → API_ERROR
        #
        # _resolve_instrument() raises BrokerageSyncSymbolNotFoundError for (a)
        # and InstrumentResolutionTransientError for (b). This prevents a brief
        # S2 outage from flooding brokerage_sync_errors with UNKNOWN_INSTRUMENT
        # records that look identical to real missing instruments.
        try:
            instrument = await self._resolve_instrument(activity.symbol, uow)
        except InstrumentResolutionTransientError as exc:
            await uow.brokerage_sync_errors.save(
                BrokerageTransactionSyncError(
                    id=new_uuid(),
                    connection_id=connection.id,
                    snaptrade_transaction_id=activity.snaptrade_transaction_id,
                    error_type=SyncErrorType.API_ERROR,
                    error_detail=str(exc),
                ),
            )
            BROKERAGE_SYNC_TRANSACTIONS_TOTAL.labels(status="skipped", error_type="api_error").inc()
            return
        except BrokerageSyncSymbolNotFoundError:
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
        # PLAN-0046 / BP-263: pass through SnapTrade ``amount`` and ``fee``.
        # ``amount`` is required for DIVIDEND rows (SnapTrade encodes the cash
        # payment in this field — units≈0, price≈0). ``fee`` is the broker
        # commission for BUY/SELL. Both default to None / Decimal(0) when
        # SnapTrade omits them.
        cmd = RecordTransactionCommand(
            tenant_id=connection.tenant_id,
            portfolio_id=connection.portfolio_id,
            owner_id=connection.user_id,
            instrument_id=instrument.id,
            transaction_type=tx_type,
            direction=direction,
            quantity=Decimal(str(activity.quantity)),
            price=Decimal(str(activity.price)),
            fees=activity.fee if activity.fee is not None else Decimal(0),
            amount=activity.amount,
            currency=activity.currency,
            executed_at=activity.executed_at,
            external_ref=activity.snaptrade_transaction_id,
            # P2-E: propagate description and settlement_date from SnapTrade activity.
            # Both default to None on SnapTradeActivity when the broker omits them.
            description=activity.description,
            settlement_date=activity.settlement_date,
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
    ) -> InstrumentRef:
        """Resolve a SnapTrade symbol to a canonical ``InstrumentRef`` via S2.

        PRD-0089 F2 §4.4 — single canonical path. The legacy DB-first +
        S3-fallback dual-path was deleted along with the ``InstrumentRef.entity_id``
        bridge-field branch: post-F2 the canonical UUID lives in S2's
        ``instruments`` table (M-017 invariant: ``canonical_entities.entity_id ==
        instruments.id`` for tradable kinds).

        Behaviour contract:

        * S2 returns 200 → return the populated ``InstrumentRef``.
        * S2 returns 404 → raise ``BrokerageSyncSymbolNotFoundError``. The caller
          maps this to a ``SyncErrorType.UNKNOWN_INSTRUMENT`` row and continues.
        * Anything else (timeout, 5xx, malformed payload) → propagate
          ``InstrumentResolutionTransientError`` from the lookup client. The
          caller maps this to ``SyncErrorType.API_ERROR`` so genuine 404s and
          transient outages remain distinguishable in the sync-error table.

        The ``uow`` parameter is unused (kept on the signature so existing call
        sites continue to compile while wave F2 is in flight) — instrument
        persistence is owned by the InstrumentDiscoveredConsumer, not by the
        sync worker. The worker is a pure read-through resolver.
        """
        if self._instrument_lookup is None:
            # Defensive: this should never happen in production (run() wires the
            # client before sync_cycle is called) and tests inject a fake
            # explicitly. We surface the misconfiguration as a transient error so
            # the cycle skips rather than hard-crashes the worker process.
            raise InstrumentResolutionTransientError(
                f"Instrument-lookup client not configured for symbol: {symbol!r}",
            )

        instrument = await self._instrument_lookup.lookup_by_ticker(symbol)
        if instrument is None:
            # S2 confirmed the symbol does not exist on this platform → genuine
            # unknown. Raise the dedicated exception so the caller can route the
            # outcome to UNKNOWN_INSTRUMENT without inspecting None semantics.
            raise BrokerageSyncSymbolNotFoundError(symbol=symbol)
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

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics so the
    # BROKERAGE_SYNC_* counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="portfolio-brokerage-sync",
        port=int(os.environ.get("METRICS_PORT", "9100")),
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
    try:
        await worker.run()
    finally:
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
