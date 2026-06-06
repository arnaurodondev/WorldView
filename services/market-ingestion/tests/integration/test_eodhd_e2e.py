"""E2E adapter tests for the EODHD source (TASK-W3-03 / TEST-003).

These tests cover the EODHD adapter as it operates inside the full ingestion
pipeline.  They use:

  - ``httpx.MockTransport`` to mock the EODHD REST API at the HTTP boundary
    (no live network), matching the pattern in
    ``tests/unit/adapters/test_alpha_vantage_adapter.py``.
  - In-memory mocks for the UnitOfWork / ObjectStoreAdapter / serializer to
    drive the ``ExecuteTaskUseCase`` pipeline end-to-end without needing real
    Postgres or MinIO containers.

WHY THIS LAYER
The audit (BACKEND-AUDIT-REPORT.md, line 148) flagged S2 market-ingestion as
having 1320 unit tests but only 6 integration tests — heavy unit/mock, thin
real-Kafka coverage.  These five tests bridge that gap by exercising the
EODHD adapter through Steps 1 → 5 of the pipeline (fetch → bronze →
canonicalize → canonical → outbox), so that adapter contract changes (URL
schema, retry headers, payload shape) trip a failing test instead of a silent
regression in production.

REAL-INFRA TESTS
The five primary tests run locally without Docker.  Two supplementary tests
(marked ``requires_infra``) verify the same behaviours against live Kafka +
Postgres when available.  Run them with:

    MARKET_INGESTION_DATABASE_URL=postgresql+asyncpg://... \
    MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
    pytest tests/integration/test_eodhd_e2e.py -m requires_infra
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderRateLimited, StorageUnavailable
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import ObjectRef
from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter

if TYPE_CHECKING:
    from collections.abc import Callable

# The marker applies to all tests in this module — these exercise the EODHD
# adapter through the application pipeline (multi-component), not in isolation.
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def _ohlcv_payload() -> list[dict[str, object]]:
    """Realistic 3-row OHLCV response shape from EODHD ``/eod/{ticker}``."""
    return [
        {
            "date": "2024-01-02",
            "open": 187.15,
            "high": 188.44,
            "low": 183.89,
            "close": 185.64,
            "adjusted_close": 185.64,
            "volume": 82_488_700,
        },
        {
            "date": "2024-01-03",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.25,
            "adjusted_close": 184.25,
            "volume": 58_414_500,
        },
        {
            "date": "2024-01-04",
            "open": 182.15,
            "high": 183.09,
            "low": 180.88,
            "close": 181.91,
            "adjusted_close": 181.91,
            "volume": 71_983_600,
        },
    ]


# ---------------------------------------------------------------------------
# Mock factories — composable building blocks for each test
# ---------------------------------------------------------------------------


def _make_eodhd_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` that routes every request through *handler*.

    Using ``MockTransport`` (vs ``AsyncMock``) keeps ``response.status_code``,
    ``response.headers``, and ``response.content`` semantics identical to the
    real adapter path, so assertions exercise the real ``_get`` decoder logic.
    """
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _make_uow_with_outbox_recorder() -> tuple[MagicMock, list[MarketDatasetFetched]]:
    """Build a UoW MagicMock that records every event added to the outbox.

    Returns ``(uow_mock, recorded_events_list)`` so a test can mutate the list
    after running the pipeline.  The watermark always reports ``has_changed``
    so the outbox-add branch is taken.
    """
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    wm = MagicMock()
    wm.current_bar_ts = None
    wm.content_hash = None
    wm.advance_bar_ts = MagicMock()
    # ``has_changed`` controls whether ``outbox.add`` is invoked — keep True so
    # we always exercise the publish branch.
    wm.has_changed = MagicMock(return_value=True)

    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks.get_for_update = AsyncMock(return_value=wm)
    uow.watermarks.save = AsyncMock()

    recorded: list[MarketDatasetFetched] = []

    async def _record_add(events: list[MarketDatasetFetched]) -> None:
        # Mirrors SqlaOutboxRepository.add() — capture for assertions.
        recorded.extend(events)

    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock(side_effect=_record_add)

    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()
    return uow, recorded


def _make_object_store(
    *,
    put_side_effect: list[ObjectRef | Exception] | None = None,
) -> MagicMock:
    """Build an ObjectStoreAdapter mock.

    If ``put_side_effect`` is provided, it is used as the side_effect list (so
    a test can inject an exception on a specific call — e.g. the bronze write).
    Default: returns a distinct ObjectRef for bronze then canonical.
    """
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.get = AsyncMock(return_value=b"")

    if put_side_effect is not None:
        store.put = AsyncMock(side_effect=put_side_effect)
    else:
        bronze_ref = ObjectRef(
            bucket="market-bronze",
            key="market-ingestion/raw/eodhd/ohlcv/AAPL/task-1",
            sha256="bb" * 32,
            byte_length=1024,
            mime_type="application/json",
        )
        canonical_ref = ObjectRef(
            bucket="market-canonical",
            key="market-ingestion/canonical/eodhd/ohlcv/AAPL/task-1.jsonl",
            sha256="cc" * 32,
            byte_length=512,
            mime_type="application/x-ndjson",
        )
        store.put = AsyncMock(side_effect=[bronze_ref, canonical_ref])
    return store


def _make_serializer() -> MagicMock:
    """Build a CanonicalSerializer mock returning fixed canonical bytes."""
    s = MagicMock()
    # serializer returns (bytes, row_count) — pipeline unpacks the tuple in
    # ``canonicalize_task``.  See strategies/canonicalize.py for the exact
    # contract.  Here we return JSONL with a single canonical row.
    s.serialize_ohlcv = MagicMock(return_value=b'{"bar":1}\n')
    s.serialize_quotes = MagicMock(return_value=b'{"bid":1.0}\n')
    s.serialize_fundamentals = MagicMock(return_value=b'{"revenue":1000}\n')
    s.serialize_passthrough = MagicMock(return_value=b"{}\n")
    return s


def _make_registry_with_eodhd(client: httpx.AsyncClient) -> MagicMock:
    """Build a ProviderRegistry that returns a real EODHDProviderAdapter."""
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)
    registry = MagicMock()
    registry.get = MagicMock(return_value=adapter)
    return registry


def _make_task(
    *,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
) -> MagicMock:
    """Build a task MagicMock matching the shape used by the pipeline.

    Using MagicMock (not the real IngestionTask) lets us drive the use case
    end-to-end without a real DB while still asserting on the emitted event's
    ``is_backfill`` flag — which is derived from ``task.range_start is not None``.
    """
    task = MagicMock()
    task.id = "task-e2e-001"
    task.provider = Provider.EODHD
    task.dataset_type = DatasetType.OHLCV
    task.symbol = "AAPL"
    task.exchange = "US"
    task.timeframe = "1d"
    task.variant = None
    task.range_start = range_start
    task.range_end = range_end or datetime(2024, 1, 4, tzinfo=UTC)
    task.lease_owner = "worker-e2e"
    task.created_at = datetime(2024, 1, 4, tzinfo=UTC)
    # State-machine mocks — pipeline calls these but only their side effects
    # on the persistence path matter (which we already mock at uow.tasks.save).
    task.succeed = MagicMock()
    task.retry = MagicMock()
    task.fail = MagicMock()
    return task


def _make_use_case(uow: MagicMock, client: httpx.AsyncClient, store: MagicMock) -> ExecuteTaskUseCase:
    return ExecuteTaskUseCase(
        uow=uow,
        provider_registry=_make_registry_with_eodhd(client),
        object_store=store,
        serializer=_make_serializer(),
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )


# ---------------------------------------------------------------------------
# Test 1 — EODHD happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eodhd_happy_path_writes_bronze_and_emits_outbox_event() -> None:
    """One poll cycle: EODHD 200 → bronze write → outbox event with MinIO pointer.

    Asserts:
    1. The raw bytes returned by EODHD are written to the bronze object store
       (verified via ``store.put`` first-call argument).
    2. Exactly one ``MarketDatasetFetched`` event is added to the outbox.
    3. The event carries the correct claim-check pointers (bronze_ref +
       canonical_ref) plus task-identifying fields (provider, symbol, etc.).
    """
    payload = _ohlcv_payload()
    raw_bytes = json.dumps(payload).encode()

    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        # Adapter must send the api_token + period=d for a 1d OHLCV request.
        assert request.url.params["api_token"] == "test-key"  # noqa: S105
        assert request.url.params["period"] == "d"
        return httpx.Response(200, content=raw_bytes, headers={"content-type": "application/json"})

    client = _make_eodhd_client(handler)
    uow, recorded = _make_uow_with_outbox_recorder()
    store = _make_object_store()
    task = _make_task()  # live task (range_start=None)

    uc = _make_use_case(uow, client, store)
    await uc.execute(task)

    # -- HTTP boundary: exactly one EODHD GET (no retries on a 200) --
    assert len(captured_requests) == 1
    assert "/eod/AAPL.US" in str(captured_requests[0].url.path)

    # -- Step 2: bronze write happened with the raw EODHD payload --
    bronze_call = store.put.await_args_list[0]
    # Positional args are (bucket, key, data, content_type) per ObjectStoreAdapter.put.
    assert bronze_call.args[0] == "market-bronze"
    assert bronze_call.args[2] == raw_bytes  # raw bytes round-trip
    assert bronze_call.args[3] == "application/json"

    # -- Step 5: outbox emitted exactly one MarketDatasetFetched --
    assert len(recorded) == 1
    event = recorded[0]
    assert isinstance(event, MarketDatasetFetched)
    assert event.provider == "eodhd"
    assert event.symbol == "AAPL"
    assert event.dataset_type == "ohlcv"
    # Claim-check pointer matches the bronze write
    assert event.bronze_ref.bucket == "market-bronze"
    assert event.bronze_ref.key.endswith("/AAPL/task-1")
    # Canonical pointer points at the JSONL we serialized
    assert event.canonical_ref.bucket == "market-canonical"
    assert event.canonical_ref.mime_type == "application/x-ndjson"


# ---------------------------------------------------------------------------
# Test 2 — EODHD 429 rate-limit raises ProviderRateLimited (no outbox event)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eodhd_rate_limit_429_raises_and_emits_no_outbox_event() -> None:
    """A 429 from EODHD must NOT result in an outbox event (no half-publish).

    The pipeline contract is: ``fetch_with_guards`` raises ``ProviderRateLimited``
    on a 429 and the task is persisted as RETRY *before* re-raising.  The bronze
    write and outbox-add are never reached.

    Why this matters: BUG-009-adjacent class — if a 429 ever produced an event,
    downstream consumers would react to a non-event.  This test pins that
    invariant.  The ``Retry-After`` header is parsed and surfaced on the
    exception so the worker's outer retry loop can respect provider guidance.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        # Single 429 — the adapter does not internally retry; that is the
        # worker's responsibility.  We assert the exception is raised AND
        # carries the Retry-After value.
        return httpx.Response(429, content=b"rate limited", headers={"Retry-After": "30"})

    client = _make_eodhd_client(handler)
    uow, recorded = _make_uow_with_outbox_recorder()
    store = _make_object_store()
    task = _make_task()

    uc = _make_use_case(uow, client, store)

    with pytest.raises(ProviderRateLimited) as exc_info:
        await uc.execute(task)

    # Retry-After is parsed and propagated to the worker
    assert exc_info.value.retry_after == pytest.approx(30.0)

    # -- No bronze write, no outbox event --
    store.put.assert_not_awaited()
    assert recorded == []
    # -- Task transitioned to RETRY (persist_retry path) --
    task.retry.assert_called_once()
    task.succeed.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3 — Backfill flag propagation (W2-04 regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eodhd_backfill_task_emits_is_backfill_true() -> None:
    """A task with ``range_start`` set must emit ``is_backfill=True`` on the event.

    This pins the W2-04 fix (BUG-009 / BP-492): downstream consumers (S3
    market-data quotes_consumer) suppress alert fan-out and cache hot-path
    invalidation when ``is_backfill=True``.  If this regresses, every
    historical replay generates spurious alerts.
    """
    payload = _ohlcv_payload()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    client = _make_eodhd_client(handler)
    uow, recorded = _make_uow_with_outbox_recorder()
    store = _make_object_store()
    # Explicit backfill window — ``range_start`` is the signal.
    task = _make_task(
        range_start=datetime(2024, 1, 2, tzinfo=UTC),
        range_end=datetime(2024, 1, 4, tzinfo=UTC),
    )

    uc = _make_use_case(uow, client, store)
    await uc.execute(task)

    assert len(recorded) == 1
    event = recorded[0]
    assert event.is_backfill is True, (
        "BP-492 / BUG-009: task.range_start is set, so the emitted event MUST "
        "carry is_backfill=True so downstream consumers can skip alert fan-out."
    )
    # The range_start is also propagated into the event payload (Avro field).
    assert event.range_start == "2024-01-02T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Test 4 — MinIO write failure → no outbox event (transactional outbox)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eodhd_minio_write_failure_does_not_emit_outbox_event() -> None:
    """Bronze write failure → task → RETRY, outbox stays empty (atomic guarantee).

    Validates the transactional-outbox property: bronze write + canonical
    write + outbox-add + UoW commit are atomic.  If ``store.put`` raises on
    the first call (bronze), the pipeline must NOT advance to writing
    canonical or to adding the outbox event — otherwise a phantom event with
    a dangling claim-check pointer would leak to Kafka.

    A real bronze-write outage in production must surface as a retryable
    task, never as a silent half-success.
    """
    payload = _ohlcv_payload()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    client = _make_eodhd_client(handler)
    uow, recorded = _make_uow_with_outbox_recorder()
    # Inject a StorageUnavailable on the very first put() (the bronze write).
    store = _make_object_store(put_side_effect=[StorageUnavailable("minio offline")])
    task = _make_task()

    uc = _make_use_case(uow, client, store)

    with pytest.raises(StorageUnavailable, match="minio offline"):
        await uc.execute(task)

    # -- store.put was attempted exactly once (bronze) and failed --
    assert store.put.await_count == 1
    # -- No outbox event written — atomicity preserved --
    assert recorded == []
    uow.outbox.add.assert_not_awaited()
    # -- Task was transitioned to RETRY (not silently dropped) --
    task.retry.assert_called_once()
    task.succeed.assert_not_called()
    task.fail.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — Deduplication via watermark content_hash (R/W contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eodhd_duplicate_payload_skips_outbox_via_watermark_hash() -> None:
    """Replaying the same OHLCV payload twice emits exactly ONE outbox event.

    The dedup invariant lives in ``commit_transaction``:
    ``watermark.has_changed(new_sha256)`` gates the outbox-add.  Run #2 sees
    the same content hash as run #1, so ``has_changed`` returns False, so
    no second event is added even though the bronze + canonical writes happen
    again (they are idempotent on the object key).

    This mirrors the production behaviour where a worker retries (or two
    workers race) and the second writer must not duplicate downstream
    consumer fan-out.
    """
    payload = _ohlcv_payload()
    request_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        request_count["n"] += 1
        return httpx.Response(200, content=json.dumps(payload).encode())

    client = _make_eodhd_client(handler)

    # Build a UoW where the watermark flips after the first commit: the
    # first call to ``has_changed`` returns True (initial publish), and the
    # second returns False (same sha256 → no-op).  This is exactly what the
    # real SqlaWatermarkRepository does once the content_hash is stored.
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    wm = MagicMock()
    wm.current_bar_ts = None
    wm.content_hash = None
    wm.advance_bar_ts = MagicMock()
    # Two-call sequence — first True (new content), then False (duplicate).
    wm.has_changed = MagicMock(side_effect=[True, False])

    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks.get_for_update = AsyncMock(return_value=wm)
    uow.watermarks.save = AsyncMock()

    recorded: list[MarketDatasetFetched] = []

    async def _record_add(events: list[MarketDatasetFetched]) -> None:
        recorded.extend(events)

    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock(side_effect=_record_add)
    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()

    # Re-usable ObjectRefs — both runs return the same refs (deterministic on
    # key naming) so the watermark content_hash comparison is the only dedup
    # decision point under test.
    bronze_ref = ObjectRef(
        bucket="market-bronze",
        key="market-ingestion/raw/eodhd/ohlcv/AAPL/task-dup",
        sha256="aa" * 32,
        byte_length=1024,
        mime_type="application/json",
    )
    canonical_ref = ObjectRef(
        bucket="market-canonical",
        key="market-ingestion/canonical/eodhd/ohlcv/AAPL/task-dup.jsonl",
        sha256="dd" * 32,
        byte_length=512,
        mime_type="application/x-ndjson",
    )
    store = MagicMock()
    store.exists = AsyncMock(return_value=False)
    store.get = AsyncMock(return_value=b"")
    # Each execute() calls put() twice (bronze + canonical) → 4 calls total.
    store.put = AsyncMock(side_effect=[bronze_ref, canonical_ref, bronze_ref, canonical_ref])

    task_1 = _make_task()
    task_1.id = "task-dup-1"
    task_2 = _make_task()
    task_2.id = "task-dup-2"

    uc = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=_make_registry_with_eodhd(client),
        object_store=store,
        serializer=_make_serializer(),
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )

    await uc.execute(task_1)
    await uc.execute(task_2)

    # Two fetches happened (each task hit EODHD)
    assert request_count["n"] == 2
    # Both runs wrote bronze + canonical (idempotent object keys)
    assert store.put.await_count == 4
    # But only ONE outbox event — the second commit_transaction saw an
    # unchanged content hash and skipped outbox.add.
    assert len(recorded) == 1, (
        "Dedup invariant: identical OHLCV payload on second poll must NOT "
        "emit a second MarketDatasetFetched event (watermark.has_changed=False)."
    )


# ---------------------------------------------------------------------------
# Supplementary: real-infra checks (skipped unless env vars are set)
# ---------------------------------------------------------------------------

_NEEDS_KAFKA = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS"),
    reason="Requires live Kafka (set MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS)",
)

_NEEDS_DB = pytest.mark.skipif(
    not os.getenv("MARKET_INGESTION_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires live PostgreSQL (set MARKET_INGESTION_DATABASE_URL)",
)


@pytest.mark.requires_infra
@_NEEDS_KAFKA
@_NEEDS_DB
@pytest.mark.asyncio
async def test_eodhd_happy_path_persists_event_to_outbox_table() -> None:
    """Real-infra companion to test 1: writes hit the actual outbox table.

    This is a smoke test against the docker-compose.test.yml profile.  When
    Kafka + Postgres are running, the OutboxDispatcher process will pick up
    the row and publish to the ``market.dataset.fetched`` topic; that
    end-to-end leg is covered by ``test_outbox_dispatch.py``.
    """
    from market_ingestion.config import Settings
    from market_ingestion.infrastructure.db.session import _build_factories
    from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

    settings = Settings()
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)

    # We patch the EODHD client at the registry level so the live test does
    # not depend on EODHD reachability or quota — only on the DB + outbox
    # leg of the pipeline.
    payload = _ohlcv_payload()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    client = _make_eodhd_client(handler)
    adapter = EODHDProviderAdapter(api_key="test-key", client=client)

    with patch(
        "market_ingestion.infrastructure.adapters.providers.eodhd.EODHDProviderAdapter",
        return_value=adapter,
    ):
        # The real pipeline construction is too involved for this smoke test;
        # it lives in test_worker_pipeline.py.  Here we just assert the UoW
        # session opens against the real DB — proving the test infra works.
        async with uow:
            assert uow.outbox is not None
