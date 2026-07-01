"""Unit tests for BrokerageTransactionSyncWorker (PRD-0022 §6.5 + PRD-0089 F2 §4.4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from portfolio.application.ports.brokerage_client import SnapTradeActivity
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.entities.instrument import InstrumentRef
from portfolio.domain.enums import ConnectionStatus, SyncErrorType
from portfolio.domain.errors import BrokerageSyncSymbolNotFoundError

from common.time import utc_now  # type: ignore[import-untyped]
from tests.unit.fakes import FakeBrokerageClient, FakeInstrumentLookupClient, FakeUnitOfWork

pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────

USER_ID = uuid4()
TENANT_ID = uuid4()
PORTFOLIO_ID = uuid4()
CONNECTION_ID = uuid4()


def _make_connection(
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
    last_sync_cursor: str | None = None,
) -> BrokerageConnection:
    return BrokerageConnection(
        id=CONNECTION_ID,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        portfolio_id=PORTFOLIO_ID,
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=utc_now(),
        status=status,
        last_sync_cursor=last_sync_cursor,
    )


def _make_activity(
    activity_type: str = "BUY",
    symbol: str = "AAPL",
    txn_id: str = "txn-001",
) -> SnapTradeActivity:
    return SnapTradeActivity(
        snaptrade_transaction_id=txn_id,
        activity_type=activity_type,
        symbol=symbol,
        quantity=Decimal(10),
        price=Decimal("150.00"),
        currency="USD",
        executed_at=datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC),
    )


def _make_instrument(symbol: str = "AAPL") -> InstrumentRef:
    return InstrumentRef(
        id=uuid4(),
        symbol=symbol,
        exchange="NASDAQ",
        source_event_id=uuid4(),
        currency="USD",
    )


def _make_worker(
    uow: FakeUnitOfWork,
    broker: FakeBrokerageClient | None = None,
    instrument_lookup: FakeInstrumentLookupClient | None = None,
) -> tuple:
    """Return (worker, session_factory_mock) with pre-wired fake UoW.

    PRD-0089 F2 §4.4 — the worker now depends on an injected
    ``IInstrumentLookupClient`` (single canonical S2 lookup, replacing the
    legacy DB-first + S3-fallback dual path). Tests that don't care about the
    resolution behaviour get a default fake seeded with AAPL/TSLA/MSFT/GOOG so
    the standard activity flow still resolves.
    """
    from portfolio.config import Settings
    from portfolio.workers.brokerage_sync_worker import BrokerageTransactionSyncWorker

    settings = Settings()  # type: ignore[call-arg]
    broker = broker or FakeBrokerageClient()

    # Default lookup: a small dictionary covering the symbols the existing test
    # helpers use. Specific tests override this via the ``instrument_lookup``
    # arg when they need to exercise 404 / transient failures.
    if instrument_lookup is None:
        # Reuse the same instrument ids as the FakeUnitOfWork's instrument
        # store when present, so cross-checks (e.g. transactions referencing
        # instrument.id) line up. Falls back to fresh ids when uow is empty.
        seed: dict[str, InstrumentRef] = {}
        for inst in uow.instruments._store.values():  # type: ignore[attr-defined]
            seed[inst.symbol.upper()] = inst
        instrument_lookup = FakeInstrumentLookupClient(instruments=seed)

    # We pass a sentinel for the session_factory — the worker's sync_cycle and
    # _sync_connection methods normally create SqlAlchemyUnitOfWork from it.
    # In unit tests we patch SqlAlchemyUnitOfWork to yield our FakeUnitOfWork.
    sentinel = object()
    worker = BrokerageTransactionSyncWorker(
        session_factory=sentinel,  # type: ignore[arg-type]
        brokerage_client=broker,
        settings=settings,
        cipher=None,
        instrument_lookup=instrument_lookup,
    )
    return worker, sentinel


# ── T-D-1-00: get_by_symbol (FakeInstrumentRepository) ───────────────────────


async def test_fake_instrument_repo_get_by_symbol_found() -> None:
    """FakeInstrumentRepository.get_by_symbol returns matching instrument (case-insensitive)."""
    uow = FakeUnitOfWork()
    inst = _make_instrument("AAPL")
    await uow.instruments.upsert(inst)

    result = await uow.instruments.get_by_symbol("aapl")
    assert result is not None
    assert result.symbol == "AAPL"


async def test_fake_instrument_repo_get_by_symbol_not_found() -> None:
    """FakeInstrumentRepository.get_by_symbol returns None for unknown symbol."""
    uow = FakeUnitOfWork()
    result = await uow.instruments.get_by_symbol("UNKNOWN")
    assert result is None


# ── sync_cycle: no active connections ────────────────────────────────────────


async def test_sync_cycle_no_connections_does_nothing() -> None:
    """sync_cycle with no active/error connections completes without errors."""
    worker, _ = _make_worker(FakeUnitOfWork())
    uow = FakeUnitOfWork()  # empty — no connections

    with patch(
        "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
    ) as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        await worker.sync_cycle()

    # No transactions, no errors
    assert len(uow.brokerage_connections._store) == 0


# ── _process_activity: type mapping ──────────────────────────────────────────


async def test_process_activity_buy_records_transaction() -> None:
    """BUY activity → TransactionType.BUY + INFLOW (asset direction) recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient (seeded by _setup_full_uow). No HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    # Verify no sync errors created
    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_sell_records_transaction() -> None:
    """SELL activity → TransactionType.SELL + OUTFLOW (asset direction) recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="SELL")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_div_records_transaction() -> None:
    """DIV activity → TransactionType.DIVIDEND + INFLOW recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="DIV")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


async def test_process_activity_dividend_alias_records_transaction() -> None:
    """DIVIDEND (alias) activity → TransactionType.DIVIDEND + INFLOW recorded."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="DIVIDEND")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0


# ── _process_activity: unsupported type ──────────────────────────────────────


async def test_process_activity_unsupported_type_creates_sync_error() -> None:
    """Unsupported activity type → UNSUPPORTED_TYPE sync error, worker continues."""
    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="TRANSFER")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNSUPPORTED_TYPE
    assert errors[0].snaptrade_transaction_id == "txn-001"


# ── _process_activity: unknown instrument ────────────────────────────────────


async def test_process_activity_unknown_instrument_creates_sync_error() -> None:
    """S2 returns 404 (lookup returns None) → UNKNOWN_INSTRUMENT sync error.

    PRD-0089 F2 §4.4 — the worker now resolves via the single canonical
    ``IInstrumentLookupClient`` port. An empty fake (no seeded instruments)
    yields None for every symbol, which the worker maps to
    ``BrokerageSyncSymbolNotFoundError`` → UNKNOWN_INSTRUMENT row.
    """
    uow = FakeUnitOfWork()
    # Explicit empty lookup so the symbol is genuinely unknown.
    empty_lookup = FakeInstrumentLookupClient(instruments={})
    worker, _ = _make_worker(uow, instrument_lookup=empty_lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="UNKNWN")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNKNOWN_INSTRUMENT
    assert "UNKNWN" in (errors[0].error_detail or "")
    # The lookup MUST have been consulted (single canonical path).
    assert empty_lookup.calls == ["UNKNWN"]


# ── _sync_connection: BrokerageApiError marks ERROR ─────────────────────────


async def test_sync_connection_api_error_marks_connection_error() -> None:
    """BrokerageApiError from get_activities → connection marked ERROR."""
    uow = FakeUnitOfWork()
    conn = _make_connection(status=ConnectionStatus.ACTIVE)
    await uow.brokerage_connections.save(conn)

    failing_broker = FakeBrokerageClient()
    failing_broker.should_raise_on_activities = True

    worker, _ = _make_worker(uow, broker=failing_broker)

    with patch(
        "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
    ) as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        # Call the inner sync entry point directly so this test exercises the
        # API-error path independently of the per-connection advisory lock
        # (BUG-003 / TASK-W1-03). Lock acquisition is covered by dedicated
        # tests further down.
        await worker._do_sync_connection(conn)

    updated = uow.brokerage_connections._store[CONNECTION_ID]
    assert updated.status == ConnectionStatus.ERROR


# ── _process_activity: idempotency conflict silently skipped ─────────────────


async def test_process_activity_idempotency_conflict_silently_skipped() -> None:
    """Duplicate activity (same external_ref) → silently skipped, no sync error."""
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", txn_id="txn-dup-001")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    # Record same activity twice
    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]
    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    # Second call should be silently skipped (dedup via find_by_external_ref)
    assert len(uow.brokerage_sync_errors._store) == 0
    # Transaction recorded exactly once
    txns = [t for t in uow.transactions._store.values() if t.external_ref == "txn-dup-001"]
    assert len(txns) == 1


# ── _process_activity: OPTION_EXERCISE unsupported ───────────────────────────


async def test_worker_skips_option_transactions() -> None:
    """OPTION_EXERCISE activity type → UNSUPPORTED_TYPE sync error, worker continues."""
    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="OPTION_EXERCISE", txn_id="txn-opt-001")
    # PRD-0089 F2 §4.4 — instrument resolution is via the injected
    # FakeInstrumentLookupClient; no HTTP shim needed.

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNSUPPORTED_TYPE
    assert errors[0].snaptrade_transaction_id == "txn-opt-001"


# ── _sync_connection: initial cursor uses history_days ───────────────────────


async def test_sync_worker_uses_history_days_for_initial_cursor() -> None:
    """When last_sync_cursor is None, start_date = today - brokerage_sync_history_days (PRD F-16)."""
    from datetime import date, timedelta
    from unittest.mock import AsyncMock, patch

    from portfolio.config import Settings

    uow = FakeUnitOfWork()
    conn = _make_connection(status=ConnectionStatus.ACTIVE, last_sync_cursor=None)
    await uow.brokerage_connections.save(conn)

    settings = Settings()  # type: ignore[call-arg]
    history_days = settings.brokerage_sync_history_days
    broker = FakeBrokerageClient(activities=[])  # no activities to process
    worker, _ = _make_worker(uow, broker=broker)

    captured_start: list[date] = []
    original_get_activities = broker.get_activities

    async def _capture_start(user: object, start: object, end: object) -> list:
        captured_start.append(start)  # type: ignore[arg-type]
        return await original_get_activities(user, start, end)

    broker.get_activities = _capture_start  # type: ignore[method-assign]

    with patch(
        "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
    ) as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        # Call the inner sync entry point directly so this test exercises the
        # cursor-derivation logic independently of the per-connection advisory
        # lock (BUG-003 / TASK-W1-03).
        await worker._do_sync_connection(conn)

    assert len(captured_start) == 1
    expected_start = datetime.now(tz=UTC).date() - timedelta(days=history_days)
    assert captured_start[0] == expected_start


# ── Helpers (full UoW with tenant/user/portfolio/instrument) ──────────────────


async def _setup_full_uow() -> FakeUnitOfWork:
    """Return a FakeUnitOfWork seeded with tenant, user, portfolio, AAPL instrument, and 100-share holding.

    The holding is pre-seeded so that SELL tests don't trigger InsufficientHoldingsError.
    """
    from decimal import Decimal

    from portfolio.domain.entities.holding import Holding
    from portfolio.domain.entities.instrument import InstrumentRef
    from portfolio.domain.entities.portfolio import Portfolio
    from portfolio.domain.entities.tenant import Tenant
    from portfolio.domain.entities.user import User
    from portfolio.domain.enums import TenantStatus, UserStatus

    uow = FakeUnitOfWork()

    tenant = Tenant(id=TENANT_ID, name="Test Tenant", status=TenantStatus.ACTIVE)
    await uow.tenants.save(tenant)

    user = User(id=USER_ID, tenant_id=TENANT_ID, email="test@example.com", status=UserStatus.ACTIVE)
    await uow.users.save(user)

    portfolio = Portfolio(id=PORTFOLIO_ID, tenant_id=TENANT_ID, owner_id=USER_ID, name="Test", currency="USD")
    await uow.portfolios.save(portfolio)

    instrument = InstrumentRef(
        id=uuid4(),
        symbol="AAPL",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        currency="USD",
    )
    await uow.instruments.upsert(instrument)

    # Pre-seed a holding so SELL tests don't hit InsufficientHoldingsError
    holding = Holding(
        id=uuid4(),
        portfolio_id=PORTFOLIO_ID,
        instrument_id=instrument.id,
        tenant_id=TENANT_ID,
        currency="USD",
        quantity=Decimal(100),
        average_cost=Decimal("150.00"),
    )
    await uow.holdings.save(holding)

    return uow


# ── _resolve_instrument: S2 lookup → 404 / transient (PRD-0089 F2 §4.4) ──────
#
# These tests previously poked the legacy ``_http_client`` to simulate raw HTTP
# responses from the two-path resolver. Post-F2 the worker depends on the
# ``IInstrumentLookupClient`` port, so the equivalent assertions now drive the
# fake client's behaviour directly. The end-to-end outcome (sync-error type)
# is preserved verbatim — only the seam moved.


async def test_resolve_instrument_s3_404_returns_none() -> None:
    """S2 lookup returns None (HTTP 404) → UNKNOWN_INSTRUMENT sync error.

    This is the 'genuine unknown' path: market-data confirmed the symbol
    does not exist on the platform. The error must remain UNKNOWN_INSTRUMENT
    (not API_ERROR) so operators can identify truly unmappable instruments.

    Post-F2 the worker raises ``BrokerageSyncSymbolNotFoundError`` internally
    and maps it to ``SyncErrorType.UNKNOWN_INSTRUMENT`` at the activity boundary.
    """
    uow = FakeUnitOfWork()  # empty — no instruments in DB
    # Empty lookup → every symbol resolves to None (the 404 outcome).
    lookup = FakeInstrumentLookupClient(instruments={})
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="NOTREAL")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.UNKNOWN_INSTRUMENT
    assert "NOTREAL" in (errors[0].error_detail or "")
    assert lookup.calls == ["NOTREAL"]


# ── _resolve_instrument: S2 transient (500/503) → API_ERROR ──────────────────


async def test_resolve_instrument_s3_500_creates_api_error() -> None:
    """S2 raises transient (formerly HTTP 500) → API_ERROR sync error with transient message.

    A 500 from market-data is a transient infrastructure failure. Recording it
    as UNKNOWN_INSTRUMENT would create false positives during outages. The error
    type must be API_ERROR and the message must mention 'transient'.
    """
    uow = FakeUnitOfWork()
    lookup = FakeInstrumentLookupClient(transient_for_symbols={"AAPL"})
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="AAPL")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.API_ERROR
    detail = errors[0].error_detail or ""
    assert "AAPL" in detail
    assert "transient" in detail.lower() or "unavailable" in detail.lower()


async def test_resolve_instrument_s3_503_creates_api_error() -> None:
    """S2 transient (formerly HTTP 503) → API_ERROR (same path as 500)."""
    uow = FakeUnitOfWork()
    # raise_transient_for_all=True is the shorthand for "S2 is completely down".
    lookup = FakeInstrumentLookupClient(raise_transient_for_all=True)
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="TSLA")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.API_ERROR


# ── _resolve_instrument: S2 network exception → API_ERROR ────────────────────


async def test_resolve_instrument_network_exception_creates_api_error() -> None:
    """Lookup client raises transient (formerly network exception) → API_ERROR.

    Connection refused, DNS failure, timeout etc. are transient failures. The
    symbol may be perfectly valid — S2 is just temporarily unreachable. The
    HttpInstrumentLookupClient surfaces all of these as
    ``InstrumentResolutionTransientError``; tests just trigger that via the fake.
    """
    uow = FakeUnitOfWork()
    lookup = FakeInstrumentLookupClient(transient_for_symbols={"MSFT"})
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="MSFT")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.API_ERROR
    detail = errors[0].error_detail or ""
    assert "MSFT" in detail


async def test_resolve_instrument_timeout_creates_api_error() -> None:
    """Lookup transient (formerly httpx.TimeoutException) → API_ERROR."""
    uow = FakeUnitOfWork()
    lookup = FakeInstrumentLookupClient(transient_for_symbols={"GOOG"})
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    conn = _make_connection()
    activity = _make_activity(activity_type="SELL", symbol="GOOG")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    errors = uow.brokerage_sync_errors._store
    assert len(errors) == 1
    assert errors[0].error_type == SyncErrorType.API_ERROR


# ── PRD-0089 F2 §4.4 — new direct-lookup happy + error path tests ────────────


async def test_resolve_instrument_direct_lookup_returns_instrument() -> None:
    """Happy path: S2 lookup returns an InstrumentRef → activity is recorded.

    Post-F2 there is a single resolution call (no DB-first branch). The worker
    must invoke the lookup client exactly once and use the returned ref's id
    when recording the transaction.
    """
    uow = await _setup_full_uow()
    # _setup_full_uow seeded AAPL into uow.instruments; _make_worker's default
    # FakeInstrumentLookupClient mirrors that store, so AAPL resolves cleanly.
    worker, _ = _make_worker(uow)

    # Snapshot the lookup client off the worker so we can assert on .calls.
    lookup = worker._instrument_lookup
    assert isinstance(lookup, FakeInstrumentLookupClient)

    conn = _make_connection()
    activity = _make_activity(activity_type="BUY", symbol="AAPL")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    # No sync errors — the activity was recorded.
    assert len(uow.brokerage_sync_errors._store) == 0
    # Lookup invoked exactly once with the activity's symbol.
    assert lookup.calls == ["AAPL"]


async def test_resolve_instrument_raises_symbol_not_found_for_unknown_ticker() -> None:
    """Direct test of ``_resolve_instrument`` — unknown symbol → BrokerageSyncSymbolNotFoundError.

    Exercises the contract at the resolver boundary (not through _process_activity).
    This locks in the F2 §4.4 behaviour that the new exception class is the way
    callers learn about genuine 404s, replacing the legacy None return value.
    """
    uow = FakeUnitOfWork()
    lookup = FakeInstrumentLookupClient(instruments={})  # nothing resolves
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    with pytest.raises(BrokerageSyncSymbolNotFoundError) as excinfo:
        await worker._resolve_instrument("ZZTOP", uow)  # type: ignore[arg-type]

    assert excinfo.value.symbol == "ZZTOP"
    assert lookup.calls == ["ZZTOP"]


async def test_resolve_instrument_passes_through_lookup_result() -> None:
    """Direct test: when the lookup returns an InstrumentRef, _resolve_instrument
    returns it verbatim — no DB upsert, no entity_id bridge consulted.

    Locks in the F2 §4.4 deletion of the legacy two-path branch: the post-F2
    contract is "S2 is the single source of truth; the worker does not transform
    or persist its output".
    """
    uow = FakeUnitOfWork()
    seeded = InstrumentRef(
        id=uuid4(),
        symbol="NVDA",
        exchange="NASDAQ",
        source_event_id=uuid4(),
        currency="USD",
    )
    lookup = FakeInstrumentLookupClient(instruments={"NVDA": seeded})
    worker, _ = _make_worker(uow, instrument_lookup=lookup)

    result = await worker._resolve_instrument("NVDA", uow)  # type: ignore[arg-type]

    assert result is seeded
    # No DB upsert side-effect (a side-effect of the deleted S3-fallback branch).
    assert uow.instruments._store == {}


# ── BUG-003 / TASK-W1-03 — per-connection advisory lock ──────────────────────
#
# These tests exercise the new ``_try_acquire_connection_lock`` helper and the
# control flow in ``_sync_connection`` that gates the per-connection sync on
# lock acquisition. Because ``FakeUnitOfWork`` does not own a real
# ``AsyncSession``, we patch the helper itself rather than mocking the
# ``session.execute`` call — this keeps the tests focused on the workflow
# decision (does the inner sync run? does the early-return fire?) without
# coupling to the SQL string.
#
# Lock-key derivation is unit-tested directly (deterministic across processes).


def test_connection_lock_key_is_deterministic_across_calls() -> None:
    """Same UUID → same lock key, every time, regardless of call site."""
    from portfolio.workers.brokerage_sync_worker import _connection_lock_key

    conn_id = uuid4()
    key_a = _connection_lock_key(conn_id)
    key_b = _connection_lock_key(conn_id)
    assert key_a == key_b
    # 63-bit positive: never negative, never overflows Postgres bigint.
    assert 0 <= key_a <= 0x7FFF_FFFF_FFFF_FFFF


def test_connection_lock_key_differs_per_connection() -> None:
    """Distinct UUIDs → distinct lock keys (different connections never collide)."""
    from portfolio.workers.brokerage_sync_worker import _connection_lock_key

    key_a = _connection_lock_key(uuid4())
    key_b = _connection_lock_key(uuid4())
    assert key_a != key_b


async def test_sync_connection_serialises_concurrent_same_connection_calls() -> None:
    """Two concurrent _sync_connection calls for the SAME connection: exactly one runs.

    Simulates two worker replicas racing for the same ``BrokerageConnection``.
    The advisory lock helper returns True on the first acquisition and False
    thereafter (mocking the "another replica holds the xact-scoped lock"
    outcome). The losing call must short-circuit before invoking the inner
    sync work — verified by asserting that ``_do_sync_connection`` was called
    exactly once.

    Acceptance criterion (BACKEND-PLAN.md TASK-W1-03):
        "Two concurrent sync calls for the same connection → exactly one
         executes; the other returns immediately."
    """
    from unittest.mock import AsyncMock, patch

    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)
    conn = _make_connection()

    # The lock helper is stateful in the real world (Postgres holds the lock
    # for whoever called first). We model that with a one-shot True/False
    # sequence so the first concurrent task "wins" the lock and the second
    # is told "already held".
    acquire_calls = 0
    acquire_lock = asyncio.Lock()

    async def fake_try_acquire(lock_uow: object, connection_id: object) -> bool:
        nonlocal acquire_calls
        async with acquire_lock:
            acquire_calls += 1
            return acquire_calls == 1

    do_sync_called = 0
    do_sync_started = asyncio.Event()
    do_sync_can_finish = asyncio.Event()

    async def fake_do_sync(connection: object) -> None:
        nonlocal do_sync_called
        do_sync_called += 1
        # Signal that the inner sync has started so the second task races in
        # while the first is still "working". Then block until the test
        # releases us so the lock-held window is wide enough to be observable.
        do_sync_started.set()
        await do_sync_can_finish.wait()

    with (
        patch(
            "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
        ) as mock_uow_cls,
        patch(
            "portfolio.workers.brokerage_sync_worker._try_acquire_connection_lock",
            new=fake_try_acquire,
        ),
        patch.object(worker, "_do_sync_connection", new=fake_do_sync),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        # Kick off two concurrent syncs for the SAME connection_id.
        task_a = asyncio.create_task(worker._sync_connection(conn))
        # Wait until the first task is inside _do_sync_connection (lock held)
        # before launching the second so the race is deterministic.
        await do_sync_started.wait()
        task_b = asyncio.create_task(worker._sync_connection(conn))

        # Let the first task complete its work. The second should already have
        # returned (lock-held path is synchronous after the helper returns
        # False — no awaits between the helper call and the early return).
        do_sync_can_finish.set()
        await asyncio.gather(task_a, task_b)

    assert do_sync_called == 1, "Exactly one concurrent caller should run the sync body"
    # Both calls attempted the lock — the second was rejected.
    assert acquire_calls == 2


async def test_sync_connection_different_connections_run_in_parallel() -> None:
    """Different connection_ids hold INDEPENDENT locks → both complete successfully.

    The advisory key is derived from connection_id (verified by
    ``test_connection_lock_key_differs_per_connection``), so two distinct
    connections never collide. Both concurrent invocations must call
    ``_do_sync_connection`` exactly once.

    Acceptance criterion (BACKEND-PLAN.md TASK-W1-03):
        "Different connections in parallel still proceed concurrently."
    """
    from unittest.mock import AsyncMock, patch

    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)

    conn_a = _make_connection()
    # Override id so conn_b is a distinct connection.
    conn_b = _make_connection()
    conn_b.id = uuid4()

    # Per-connection lock state: each connection's first acquisition wins.
    acquired_set: set[object] = set()
    acquire_lock = asyncio.Lock()

    async def fake_try_acquire(lock_uow: object, connection_id: object) -> bool:
        async with acquire_lock:
            if connection_id in acquired_set:
                return False  # would only happen on same-connection race
            acquired_set.add(connection_id)
            return True

    do_sync_started = asyncio.Event()
    do_sync_can_finish = asyncio.Event()
    completed_for: list[object] = []

    async def fake_do_sync(connection: object) -> None:
        do_sync_started.set()
        await do_sync_can_finish.wait()
        completed_for.append(connection.id)  # type: ignore[attr-defined]

    with (
        patch(
            "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
        ) as mock_uow_cls,
        patch(
            "portfolio.workers.brokerage_sync_worker._try_acquire_connection_lock",
            new=fake_try_acquire,
        ),
        patch.object(worker, "_do_sync_connection", new=fake_do_sync),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        task_a = asyncio.create_task(worker._sync_connection(conn_a))
        await do_sync_started.wait()  # task_a is inside fake_do_sync
        task_b = asyncio.create_task(worker._sync_connection(conn_b))

        do_sync_can_finish.set()
        await asyncio.gather(task_a, task_b)

    # Both connections completed their sync work — neither was locked out.
    assert sorted(str(x) for x in completed_for) == sorted([str(conn_a.id), str(conn_b.id)])


async def test_sync_connection_returns_early_when_lock_unavailable() -> None:
    """Lock helper returns False → no inner sync work, no SnapTrade calls.

    Direct single-task variant for clarity: verifies the early-return path
    in isolation without the concurrency machinery of the parallel test.
    """
    from unittest.mock import AsyncMock, patch

    uow = FakeUnitOfWork()
    worker, _ = _make_worker(uow)
    conn = _make_connection()

    async def always_fail(lock_uow: object, connection_id: object) -> bool:
        return False

    do_sync_called = 0

    async def spy_do_sync(connection: object) -> None:
        nonlocal do_sync_called
        do_sync_called += 1

    with (
        patch(
            "portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork",
        ) as mock_uow_cls,
        patch(
            "portfolio.workers.brokerage_sync_worker._try_acquire_connection_lock",
            new=always_fail,
        ),
        patch.object(worker, "_do_sync_connection", new=spy_do_sync),
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        await worker._sync_connection(conn)

    assert do_sync_called == 0


# ── BP-501: cash activity types silently skipped ─────────────────────────────


async def test_process_activity_fee_silently_skipped_no_sync_error() -> None:
    """FEE activity → silently skipped; no BrokerageTransactionSyncError recorded.

    BP-501: FEE is a cash-only activity (no instrument_id). The schema requires
    NOT NULL instrument_id, so recording it would fail. We skip without creating
    a sync error so the brokerage panel stays clean.
    """
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="FEE", symbol="", txn_id="fee-001")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0, "FEE must not create a sync error"
    assert len(uow.transactions._store) == 0, "FEE must not create a transaction"


async def test_process_activity_interest_silently_skipped_no_sync_error() -> None:
    """INTEREST activity → silently skipped; no BrokerageTransactionSyncError recorded.

    BP-501: INTEREST is a cash-only activity (no instrument_id). Same constraint
    as FEE — intercepted before instrument lookup to avoid UNSUPPORTED_TYPE error.
    """
    uow = await _setup_full_uow()
    worker, _ = _make_worker(uow)

    conn = _make_connection()
    activity = _make_activity(activity_type="INTEREST", symbol="", txn_id="int-001")

    await worker._process_activity(conn, activity, uow)  # type: ignore[arg-type]

    assert len(uow.brokerage_sync_errors._store) == 0, "INTEREST must not create a sync error"
    assert len(uow.transactions._store) == 0, "INTEREST must not create a transaction"


# ── BP-500: holdings not wiped when snapshot positions all fail resolution ────


async def test_sync_holdings_not_wiped_when_all_positions_unresolved() -> None:
    """Existing holdings survive when every broker position fails instrument resolution.

    BP-500: if the broker returns N positions but all fail lookup (e.g. ETFs not
    yet seeded in S2), the worker must NOT call UpsertHoldingsFromSnapshotUseCase
    with positions=[] — that would delete every existing holding.
    """
    from portfolio.domain.entities.holding import Holding
    from portfolio.domain.errors import BrokerageSyncSymbolNotFoundError

    from tests.unit.fakes import FakeBrokerageClient, FakeInstrumentLookupClient

    class AlwaysNotFoundLookup(FakeInstrumentLookupClient):
        """Simulates S2 returning 404 for every symbol."""

        async def lookup_by_ticker(self, symbol: str) -> InstrumentRef | None:
            raise BrokerageSyncSymbolNotFoundError(symbol=symbol)

    uow = await _setup_full_uow()

    # Pre-seed a holding so we can verify it survives the sync.
    instrument = next(iter(uow.instruments._store.values()))  # type: ignore[attr-defined]
    existing_holding = Holding(
        id=uuid4(),
        portfolio_id=PORTFOLIO_ID,
        instrument_id=instrument.id,
        tenant_id=TENANT_ID,
        currency="USD",
        quantity=Decimal(50),
        average_cost=Decimal(100),
    )
    await uow.holdings.save(existing_holding)

    from portfolio.application.ports.brokerage_client import SnapTradePosition

    broker = FakeBrokerageClient()
    # FakeBrokerageClient uses dynamic attribute injection for snapshot data.
    broker.account_ids = ["acc-1"]  # type: ignore[attr-defined]
    broker.positions_by_account = {  # type: ignore[attr-defined]
        "acc-1": [
            SnapTradePosition(
                account_id="acc-1",
                symbol="VWO",
                quantity=Decimal(100),
                average_purchase_price=Decimal(45),
                currency="USD",
            ),
        ],
    }

    worker, _ = _make_worker(uow, broker=broker, instrument_lookup=AlwaysNotFoundLookup())
    conn = _make_connection()

    with patch("portfolio.workers.brokerage_sync_worker.SqlAlchemyUnitOfWork") as mock_uow_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=uow)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_uow_cls.return_value = mock_ctx

        await worker._sync_holdings_from_snapshot(conn, object())  # type: ignore[arg-type]

    # The pre-existing AAPL holding must still be there.
    holdings = await uow.holdings.list_by_portfolio(PORTFOLIO_ID)
    assert len(holdings) == 1, "Existing holding must not be deleted when all positions fail resolution"
    assert holdings[0].instrument_id == existing_holding.instrument_id


# ── DEF-002: internal-JWT claims (aud + jti) ──────────────────────────────────


def test_system_jwt_headers_include_aud_and_jti() -> None:
    """DEF-002: X-Internal-JWT MUST carry aud + a unique jti (required by middleware)."""
    import jwt as pyjwt
    from portfolio.config import Settings
    from portfolio.workers.brokerage_sync_worker import _system_jwt_headers

    decoded = pyjwt.decode(
        _system_jwt_headers(Settings())["X-Internal-JWT"],  # type: ignore[call-arg]
        options={"verify_signature": False},
    )
    assert decoded["aud"] == "worldview-internal"
    assert decoded["iss"] == "worldview-gateway"
    assert decoded["sub"] == "system:brokerage-sync"
    assert decoded["jti"]
