"""Unit tests for the ValkeyCircuitBreaker adapter and its ExecuteTaskUseCase integration.

Covers:
1. Fresh keys → CLOSED state (circuit starts closed)
2. N consecutive failures → OPEN state
3. OPEN circuit blocks task execution via ExecuteTaskUseCase
4. Cooldown elapsed transitions OPEN → HALF_OPEN
5. Successful probe in HALF_OPEN closes the circuit
6. Failed probe in HALF_OPEN re-opens the circuit
7. Failures on endpoint A don't affect endpoint B

All tests use a mock ValkeyClient — no real Valkey required.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.ports.circuit_breaker import CircuitState
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderRateLimited
from market_ingestion.infrastructure.adapters.circuit_breaker import ValkeyCircuitBreaker

# ---------------------------------------------------------------------------
# Helpers: mock Valkey client backed by an in-memory dict
# ---------------------------------------------------------------------------


def _make_valkey_mock() -> MagicMock:
    """Build an AsyncMock ValkeyClient backed by a simple in-memory dict.

    The store dict is returned alongside the mock so tests can pre-populate
    or inspect Valkey key state without touching real Valkey.
    """
    store: dict[str, str] = {}

    mock = MagicMock()

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _set(key: str, value: str, ttl: int | None = None, *, ex: int | None = None) -> None:
        store[key] = value

    async def _delete(key: str) -> int:
        existed = key in store
        store.pop(key, None)
        return 1 if existed else 0

    async def _incr(key: str, amount: int = 1) -> int:
        current = int(store.get(key, "0"))
        new_val = current + amount
        store[key] = str(new_val)
        return new_val

    mock.get = AsyncMock(side_effect=_get)
    mock.set = AsyncMock(side_effect=_set)
    mock.delete = AsyncMock(side_effect=_delete)
    mock.incr = AsyncMock(side_effect=_incr)

    # Attach store for test inspection
    mock._store = store

    return mock


# ---------------------------------------------------------------------------
# Helper: build a ValkeyCircuitBreaker with the mock client
# ---------------------------------------------------------------------------


def _make_breaker(failure_threshold: int = 5, open_duration_sec: int = 60) -> tuple[ValkeyCircuitBreaker, MagicMock]:
    """Return (circuit_breaker, mock_valkey)."""
    mock_valkey = _make_valkey_mock()
    breaker = ValkeyCircuitBreaker(
        valkey=mock_valkey,
        failure_threshold=failure_threshold,
        open_duration_sec=open_duration_sec,
        success_threshold=1,
    )
    return breaker, mock_valkey


# ---------------------------------------------------------------------------
# Helper: build ExecuteTaskUseCase with a circuit breaker
# ---------------------------------------------------------------------------


def _make_uow() -> MagicMock:
    """Build a minimal mock UnitOfWork."""
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()
    uow.commit = AsyncMock()
    uow.watermarks = MagicMock()
    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock()
    return uow


def _make_use_case_with_cb(circuit_breaker: ValkeyCircuitBreaker) -> tuple[ExecuteTaskUseCase, MagicMock]:
    """Build ExecuteTaskUseCase with the given circuit breaker wired in."""
    uow = _make_uow()

    # Provider that returns a successful fetch result
    provider = MagicMock()
    provider.fetch_quotes = AsyncMock(
        return_value=MagicMock(
            raw_data=b'{"bid":1.0,"ask":1.01}',
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=10,
        )
    )

    registry = MagicMock()
    registry.get = MagicMock(return_value=provider)

    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.put = AsyncMock(
        return_value=MagicMock(
            sha256="abc123",
            byte_length=20,
            mime_type="application/x-ndjson",
        )
    )

    serializer = MagicMock()
    serializer.serialize_quotes = MagicMock(return_value=b'{"symbol":"AAPL"}')

    use_case = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        quota_service=None,  # no quota check in these tests
        circuit_breaker=circuit_breaker,
    )
    return use_case, uow


def _make_quote_task() -> MagicMock:
    """Build a minimal mock IngestionTask for QUOTES on AAPL."""
    task = MagicMock()
    task.id = "task-01"
    task.provider = Provider.EODHD
    task.dataset_type = DatasetType.QUOTES
    task.symbol = "AAPL"
    task.exchange = "US"
    task.timeframe = None
    task.variant = None
    task.range_start = None
    task.range_end = datetime.now(tz=UTC)
    task.created_at = datetime.now(tz=UTC)
    task.status = MagicMock()
    task.succeed = MagicMock()
    task.retry = MagicMock()
    task.fail = MagicMock()
    return task


# ===========================================================================
# Test 1: Fresh state → CLOSED
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_starts_closed() -> None:
    """A freshly initialised circuit breaker returns CLOSED state.

    When no Valkey keys exist for an endpoint, the circuit has never been
    opened and should be treated as CLOSED (all calls pass through).
    """
    breaker, _ = _make_breaker()

    state = await breaker.get_state("quotes")
    assert state == CircuitState.CLOSED

    is_open = await breaker.is_open("quotes")
    assert is_open is False


# ===========================================================================
# Test 2: N consecutive failures → OPEN
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_opens_after_threshold_failures() -> None:
    """After failure_threshold consecutive failures the circuit transitions to OPEN."""
    breaker, mock_valkey = _make_breaker(failure_threshold=3)

    # Record 2 failures — circuit should remain CLOSED.
    await breaker.record_failure("quotes")
    await breaker.record_failure("quotes")
    state = await breaker.get_state("quotes")
    assert state == CircuitState.CLOSED

    # Third failure hits the threshold — circuit should now be OPEN.
    await breaker.record_failure("quotes")
    state = await breaker.get_state("quotes")
    assert state == CircuitState.OPEN

    # is_open must return True when circuit is OPEN.
    is_open = await breaker.is_open("quotes")
    assert is_open is True


# ===========================================================================
# Test 3: OPEN circuit blocks task execution
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_open_prevents_task_execution() -> None:
    """When the circuit is OPEN, execute() raises ProviderRateLimited and calls retry().

    The provider fetch must NOT be called — the breaker intercepts before Step 1.
    """
    # Pre-open the circuit by recording enough failures.
    breaker, _ = _make_breaker(failure_threshold=2)
    await breaker.record_failure("quotes")
    await breaker.record_failure("quotes")
    assert await breaker.is_open("quotes") is True

    use_case, uow = _make_use_case_with_cb(breaker)
    task = _make_quote_task()

    with pytest.raises(ProviderRateLimited, match="circuit breaker OPEN"):
        await use_case.execute(task)

    # Task must be retried (not permanently failed).
    task.retry.assert_called_once()
    task.fail.assert_not_called()


# ===========================================================================
# Test 4: Cooldown elapsed → HALF_OPEN
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_transitions_to_half_open_after_cooldown() -> None:
    """When OPEN and the cooldown window has passed, get_state returns HALF_OPEN."""
    breaker, mock_valkey = _make_breaker(failure_threshold=1, open_duration_sec=60)

    # Force the circuit OPEN.
    await breaker.record_failure("quotes")
    assert await breaker.get_state("quotes") == CircuitState.OPEN

    # Manually set open_until to the past so the cooldown appears elapsed.
    expired_ts = int(time.time()) - 10  # 10 seconds in the past
    mock_valkey._store[breaker._key_open_until("quotes")] = str(expired_ts)

    # get_state should now detect the expired cooldown and return HALF_OPEN.
    state = await breaker.get_state("quotes")
    assert state == CircuitState.HALF_OPEN

    # is_open should return False in HALF_OPEN (probe call is allowed).
    is_open = await breaker.is_open("quotes")
    assert is_open is False


# ===========================================================================
# Test 5: Successful probe in HALF_OPEN → CLOSED
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_closes_on_probe_success() -> None:
    """A successful probe in HALF_OPEN transitions the circuit back to CLOSED."""
    breaker, mock_valkey = _make_breaker(failure_threshold=1, open_duration_sec=60)

    # Open the circuit, then simulate cooldown expiry.
    await breaker.record_failure("quotes")
    expired_ts = int(time.time()) - 5
    mock_valkey._store[breaker._key_open_until("quotes")] = str(expired_ts)

    # Verify HALF_OPEN.
    assert await breaker.get_state("quotes") == CircuitState.HALF_OPEN

    # Record a successful probe.
    await breaker.record_success("quotes")

    # Circuit should be CLOSED again.
    state = await breaker.get_state("quotes")
    assert state == CircuitState.CLOSED

    # Failure counter should be reset.
    failures_raw = mock_valkey._store.get(breaker._key_failures("quotes"))
    assert failures_raw == "0"

    # open_until key should be deleted.
    assert breaker._key_open_until("quotes") not in mock_valkey._store


# ===========================================================================
# Test 6: Failed probe in HALF_OPEN → re-opened OPEN
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_reopens_on_probe_failure() -> None:
    """A failed probe in HALF_OPEN re-opens the circuit (resets the cooldown timer)."""
    breaker, mock_valkey = _make_breaker(failure_threshold=1, open_duration_sec=60)

    # Open the circuit, then simulate cooldown expiry.
    await breaker.record_failure("quotes")
    expired_ts = int(time.time()) - 5
    mock_valkey._store[breaker._key_open_until("quotes")] = str(expired_ts)

    # Verify HALF_OPEN before the probe.
    assert await breaker.get_state("quotes") == CircuitState.HALF_OPEN

    # Probe fails — record_failure in HALF_OPEN should re-open.
    await breaker.record_failure("quotes")

    # Circuit should be OPEN again.
    state_raw = mock_valkey._store.get(breaker._key_state("quotes"))
    assert state_raw == "open"

    # open_until should be a fresh future timestamp.
    open_until_raw = mock_valkey._store.get(breaker._key_open_until("quotes"))
    assert open_until_raw is not None
    open_until = int(open_until_raw)
    assert open_until > int(time.time())  # still in the future


# ===========================================================================
# Test 7: Failures on endpoint A don't affect endpoint B
# ===========================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_does_not_affect_other_endpoints() -> None:
    """Failures recorded for endpoint A have no effect on endpoint B's state."""
    breaker, _ = _make_breaker(failure_threshold=2)

    # Record enough failures to open endpoint "ohlcv".
    await breaker.record_failure("ohlcv")
    await breaker.record_failure("ohlcv")
    assert await breaker.is_open("ohlcv") is True

    # Endpoint "quotes" should still be CLOSED.
    state = await breaker.get_state("quotes")
    assert state == CircuitState.CLOSED

    is_open = await breaker.is_open("quotes")
    assert is_open is False
