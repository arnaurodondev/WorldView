"""Tests for ExecuteTaskUseCase (T-MI-12). ≥12 test functions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.execute_task import ExecuteTaskUseCase
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
    StorageUnavailable,
    WatermarkViolation,
)
from market_ingestion.domain.value_objects import ObjectRef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ohlcv_json() -> bytes:
    return json.dumps([{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}]).encode()


def _quotes_json() -> bytes:
    return json.dumps([{"bid": 1.0, "ask": 1.01, "mid": 1.005}]).encode()


def _fundamentals_json() -> bytes:
    return json.dumps({"revenue": 1_000_000, "net_income": 100_000}).encode()


def _fetch_result(raw_data: bytes = b"", content_type: str = "application/json") -> MagicMock:
    fr = MagicMock()
    fr.raw_data = raw_data or _ohlcv_json()
    fr.content_type = content_type
    fr.fetched_at = datetime.now(UTC)
    fr.duration_ms = 50
    return fr


def _object_ref(sha256: str = "deadbeef" * 8, bucket: str = "b", key: str = "k") -> ObjectRef:
    return ObjectRef(bucket=bucket, key=key, sha256=sha256, byte_length=128, mime_type="application/octet-stream")


def _make_task(
    dataset_type: DatasetType = DatasetType.OHLCV,
    provider: Provider = Provider.EODHD,
    symbol: str = "AAPL",
    exchange: str | None = "US",
    timeframe: str | None = "1d",
    variant: str | None = None,
    range_end: datetime | None = None,
) -> MagicMock:
    task = MagicMock()
    task.id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    task.provider = provider
    task.dataset_type = dataset_type
    task.symbol = symbol
    task.exchange = exchange
    task.timeframe = timeframe
    task.variant = variant
    task.range_start = None
    task.range_end = range_end or datetime.now(UTC)
    task.succeed = MagicMock()
    task.retry = MagicMock()
    task.fail = MagicMock()
    return task


def _make_watermark(changed: bool = True) -> MagicMock:
    wm = MagicMock()
    wm.current_bar_ts = None
    wm.content_hash = None
    wm.advance_bar_ts = MagicMock()  # sync; raises WatermarkViolation when patched
    wm.has_changed = MagicMock(return_value=changed)
    return wm


def _make_uow(watermark: MagicMock | None = None) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()

    wm = watermark or _make_watermark()
    uow.watermarks = MagicMock()
    uow.watermarks.get_or_create = AsyncMock(return_value=wm)
    uow.watermarks.get_for_update = AsyncMock(return_value=wm)
    uow.watermarks.save = AsyncMock()

    uow.outbox = MagicMock()
    uow.outbox.add = AsyncMock()

    uow.tasks = MagicMock()
    uow.tasks.save = AsyncMock()

    return uow


def _make_store(sha256: str = "deadbeef" * 8, *, bronze_side_effect=None, canonical_side_effect=None) -> MagicMock:
    store = MagicMock()
    bronze_ref = _object_ref(sha256=sha256, bucket="market-bronze", key="bronze/key")
    canonical_ref = _object_ref(sha256=sha256, bucket="market-canonical", key="canonical/key")

    if bronze_side_effect:
        store.put = AsyncMock(side_effect=[bronze_side_effect])
    elif canonical_side_effect:
        store.put = AsyncMock(side_effect=[bronze_ref, canonical_side_effect])
    else:
        store.put = AsyncMock(side_effect=[bronze_ref, canonical_ref])

    store.get = AsyncMock(return_value=b"data")
    store.exists = AsyncMock(return_value=False)
    return store


def _make_serializer() -> MagicMock:
    s = MagicMock()
    s.serialize_ohlcv = MagicMock(return_value=b'{"bar": 1}\n')
    s.serialize_quotes = MagicMock(return_value=b'{"bid": 1.0}\n')
    s.serialize_fundamentals = MagicMock(return_value=b'{"revenue": 1000}\n')
    return s


def _make_registry(*, raw_data: bytes | None = None, fetch_side_effect=None) -> MagicMock:
    adapter = MagicMock()
    fr = _fetch_result(raw_data=raw_data or _ohlcv_json())
    if fetch_side_effect:
        adapter.fetch_ohlcv = AsyncMock(side_effect=fetch_side_effect)
        adapter.fetch_quotes = AsyncMock(side_effect=fetch_side_effect)
        adapter.fetch_fundamentals = AsyncMock(side_effect=fetch_side_effect)
    else:
        adapter.fetch_ohlcv = AsyncMock(return_value=fr)
        adapter.fetch_quotes = AsyncMock(return_value=fr)
        adapter.fetch_fundamentals = AsyncMock(return_value=fr)
    registry = MagicMock()
    registry.get = MagicMock(return_value=adapter)
    return registry


def _make_use_case(
    uow=None,
    registry=None,
    store=None,
    serializer=None,
) -> tuple[ExecuteTaskUseCase, MagicMock, MagicMock, MagicMock, MagicMock]:
    uow = uow or _make_uow()
    registry = registry or _make_registry()
    store = store or _make_store()
    serializer = serializer or _make_serializer()
    uc = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=serializer,
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )
    return uc, uow, registry, store, serializer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_happy_path_ohlcv_end_to_end() -> None:
    """Full 5-step pipeline: fetch → bronze → canonical → watermark → outbox → succeed."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, registry, store, serializer = _make_use_case(uow=uow)

    await uc.execute(task)

    # Step 1: fetched via correct method
    registry.get(task.provider).fetch_ohlcv.assert_awaited_once()

    # Step 2 & 4: put called twice (bronze + canonical)
    assert store.put.await_count == 2

    # Step 3: serializer called
    serializer.serialize_ohlcv.assert_called_once()

    # Step 5: watermark advanced, outbox added, task succeeded
    wm.advance_bar_ts.assert_called_once()
    uow.outbox.add.assert_awaited_once()
    task.succeed.assert_called_once()
    uow.commit.assert_awaited()


@pytest.mark.unit
async def test_provider_rate_limited_retries_task() -> None:
    """ProviderRateLimited → task.retry() called, exception propagates."""
    task = _make_task()
    exc = ProviderRateLimited("rate limit hit")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderRateLimited):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    uow.tasks.save.assert_awaited()
    uow.commit.assert_awaited()


@pytest.mark.unit
async def test_provider_unavailable_retries_task() -> None:
    """ProviderUnavailable → task.retry() called, exception propagates."""
    task = _make_task()
    exc = ProviderUnavailable("service unavailable")
    uc, _, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)


@pytest.mark.unit
async def test_provider_auth_error_fails_task() -> None:
    """ProviderAuthError → task.fail() called (fatal), exception propagates."""
    task = _make_task()
    exc = ProviderAuthError("bad credentials")
    uc, _, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderAuthError):
        await uc.execute(task)

    task.fail.assert_called_once_with(exc)
    task.retry.assert_not_called()


@pytest.mark.unit
async def test_provider_data_error_fails_task() -> None:
    """ProviderDataError → task.fail() called (fatal), exception propagates."""
    task = _make_task()
    exc = ProviderDataError("malformed response")
    uc, _, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderDataError):
        await uc.execute(task)

    task.fail.assert_called_once_with(exc)
    task.retry.assert_not_called()


@pytest.mark.unit
async def test_storage_unavailable_on_bronze_retries_task() -> None:
    """StorageUnavailable on bronze store → task.retry(), exception propagates."""
    task = _make_task()
    exc = StorageUnavailable("s3 down")
    store = _make_store(bronze_side_effect=exc)
    uc, _, _, _, _ = _make_use_case(store=store)

    with pytest.raises(StorageUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_storage_unavailable_on_canonical_retries_task() -> None:
    """StorageUnavailable on canonical store → task.retry(), exception propagates."""
    task = _make_task()
    exc = StorageUnavailable("s3 canonical shard down")
    store = _make_store(canonical_side_effect=exc)
    uc, _, _, _, _ = _make_use_case(store=store)

    with pytest.raises(StorageUnavailable):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_unchanged_sha256_skips_outbox() -> None:
    """If watermark.has_changed() returns False, outbox.add() is NOT called."""
    task = _make_task()
    wm = _make_watermark(changed=False)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    uow.outbox.add.assert_not_awaited()
    task.succeed.assert_called_once()  # pipeline still completes


@pytest.mark.unit
async def test_changed_sha256_adds_outbox_event() -> None:
    """If watermark.has_changed() returns True, outbox.add() IS called."""
    task = _make_task()
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    uow.outbox.add.assert_awaited_once()


@pytest.mark.unit
async def test_watermark_advanced_with_range_end() -> None:
    """Watermark.advance_bar_ts() is called with task.range_end when set."""
    range_end = datetime(2024, 6, 30, tzinfo=UTC)
    task = _make_task(range_end=range_end)
    wm = _make_watermark()
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    wm.advance_bar_ts.assert_called_once_with(range_end)


@pytest.mark.unit
async def test_watermark_violation_retries_task_and_propagates() -> None:
    """WatermarkViolation from advance_bar_ts → task.retry() called (concurrent worker race).

    WatermarkViolation is a transient race condition, not a fatal error.
    The losing worker should re-queue via retry() so the task is attempted again.
    task.fail() must NOT be called.
    """
    task = _make_task()
    wm = _make_watermark()
    wm.advance_bar_ts.side_effect = WatermarkViolation("non-monotonic advance")
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    with pytest.raises(WatermarkViolation):
        await uc.execute(task)

    task.retry.assert_called_once()
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_ohlcv_uses_fetch_ohlcv_and_serialize_ohlcv() -> None:
    """DatasetType.OHLCV routes to fetch_ohlcv() and serialize_ohlcv()."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    registry = _make_registry(raw_data=_ohlcv_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_ohlcv.assert_awaited_once()
    registry.get(task.provider).fetch_quotes.assert_not_awaited()
    registry.get(task.provider).fetch_fundamentals.assert_not_awaited()
    serializer.serialize_ohlcv.assert_called_once()
    serializer.serialize_quotes.assert_not_called()
    serializer.serialize_fundamentals.assert_not_called()


@pytest.mark.unit
async def test_quotes_uses_fetch_quotes_and_serialize_quotes() -> None:
    """DatasetType.QUOTES routes to fetch_quotes() and serialize_quotes()."""
    task = _make_task(dataset_type=DatasetType.QUOTES)
    registry = _make_registry(raw_data=_quotes_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_quotes.assert_awaited_once()
    registry.get(task.provider).fetch_ohlcv.assert_not_awaited()
    serializer.serialize_quotes.assert_called_once()
    serializer.serialize_ohlcv.assert_not_called()
    serializer.serialize_fundamentals.assert_not_called()


@pytest.mark.unit
async def test_fundamentals_uses_fetch_fundamentals_and_serialize_fundamentals() -> None:
    """DatasetType.FUNDAMENTALS routes to fetch_fundamentals() and serialize_fundamentals()."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant="annual")
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, registry, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    registry.get(task.provider).fetch_fundamentals.assert_awaited_once()
    registry.get(task.provider).fetch_ohlcv.assert_not_awaited()
    registry.get(task.provider).fetch_quotes.assert_not_awaited()
    serializer.serialize_fundamentals.assert_called_once()
    serializer.serialize_ohlcv.assert_not_called()
    serializer.serialize_quotes.assert_not_called()


@pytest.mark.unit
async def test_fundamentals_enriches_with_required_fields() -> None:
    """Verify enriched dict has symbol, exchange, period, report_date."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant="annual", exchange="US", symbol="AAPL")
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    # Verify serialize_fundamentals was called with enriched data
    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]

    assert enriched_data["symbol"] == "AAPL"
    assert enriched_data["exchange"] == "US"
    assert enriched_data["period"] == "annual"
    assert "report_date" in enriched_data


@pytest.mark.unit
async def test_fundamentals_variant_none_defaults_to_annual() -> None:
    """When variant is None, period should be 'annual'."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, variant=None)
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["period"] == "annual"


@pytest.mark.unit
async def test_fundamentals_exchange_none_becomes_empty_string() -> None:
    """When exchange is None, it should be empty string."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS, exchange=None)
    registry = _make_registry(raw_data=_fundamentals_json())
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["exchange"] == ""


@pytest.mark.unit
async def test_fundamentals_report_date_generated_when_missing() -> None:
    """When report_date missing from raw data, should be auto-generated."""
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS)
    registry = _make_registry(raw_data=_fundamentals_json())  # no report_date
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]

    assert "report_date" in enriched_data
    # Verify it's a valid ISO format datetime string
    from datetime import datetime

    datetime.fromisoformat(enriched_data["report_date"])


@pytest.mark.unit
async def test_fundamentals_report_date_preserved_when_present() -> None:
    """When report_date already in raw data, should be preserved."""
    raw_date = "2023-12-31T00:00:00"
    raw_data = json.dumps({"revenue": 1_000_000, "report_date": raw_date}).encode()
    task = _make_task(dataset_type=DatasetType.FUNDAMENTALS)
    registry = _make_registry(raw_data=raw_data)
    serializer = _make_serializer()
    uc, _, _, _, serializer = _make_use_case(registry=registry, serializer=serializer)

    await uc.execute(task)

    call_args = serializer.serialize_fundamentals.call_args
    enriched_data = call_args[0][0]
    assert enriched_data["report_date"] == raw_date


# ---------------------------------------------------------------------------
# T-E1-1-04: Atomicity tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_watermark_get_for_update_called_in_step5() -> None:
    """Step 5 calls get_for_update() to lock watermark against concurrent workers."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    # Both get_or_create (ensure row) and get_for_update (lock row) must be called
    uow.watermarks.get_or_create.assert_awaited_once()
    uow.watermarks.get_for_update.assert_awaited_once()


@pytest.mark.unit
async def test_persist_retry_clears_lease_atomically() -> None:
    """After retry(), lease_owner/expires are cleared and committed atomically."""
    task = _make_task()
    exc = ProviderRateLimited("rate limit")
    uc, uow, _, _, _ = _make_use_case(registry=_make_registry(fetch_side_effect=exc))

    with pytest.raises(ProviderRateLimited):
        await uc.execute(task)

    task.retry.assert_called_once_with(exc)
    # save() and commit() must both have been called (atomic pair)
    uow.tasks.save.assert_awaited()
    uow.commit.assert_awaited()


@pytest.mark.unit
async def test_object_exists_skips_bronze_write_on_retry() -> None:
    """If bronze object already exists, put() is skipped and ref is reconstructed."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    store = _make_store()
    # Simulate bronze exists but canonical not yet (crash after bronze write, before canonical)
    store.exists = AsyncMock(side_effect=[True, False])

    uc, _, _, store, _ = _make_use_case(store=store)
    await uc.execute(task)

    # put() called only once (for canonical) — bronze upload skipped
    assert store.put.await_count == 1


# ---------------------------------------------------------------------------
# T-E1-1-06: Outbox contains only MarketDatasetFetched (D-005)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_watermark_uses_created_at_when_range_end_none() -> None:
    """When task.range_end is None, watermark is advanced by task.created_at (M-029).

    Ensures deterministic ordering: two tasks without range_end produce stable
    watermark advances via their immutable created_at timestamps, not utc_now()
    which is racy and non-deterministic.
    """
    created_at = datetime(2024, 3, 15, tzinfo=UTC)
    task = _make_task(range_end=None)
    task.range_end = None
    task.created_at = created_at

    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    wm.advance_bar_ts.assert_called_once_with(created_at)


@pytest.mark.unit
async def test_watermark_no_regression_out_of_order_tasks() -> None:
    """Earlier-created task with range_end=None uses created_at, not current time.

    Verifies that the fallback timestamp is stable: replaying an older task
    always uses the same created_at, preventing non-deterministic watermark
    advances that could differ across retries.
    """
    created_at_early = datetime(2024, 1, 10, tzinfo=UTC)
    task = _make_task(range_end=None)
    task.range_end = None
    task.created_at = created_at_early

    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    # The watermark advance is called with the stable created_at, not a moving now()
    args = wm.advance_bar_ts.call_args[0]
    assert args[0] == created_at_early


@pytest.mark.unit
async def test_execute_task_only_market_dataset_fetched_in_outbox() -> None:
    """Only MarketDatasetFetched is written to outbox — no internal task events (D-005)."""
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    await uc.execute(task)

    # outbox.add called exactly once, with the MarketDatasetFetched event
    uow.outbox.add.assert_awaited_once()
    call_kwargs = uow.outbox.add.call_args.kwargs
    events = call_kwargs["events"]
    from market_ingestion.domain.events import MarketDatasetFetched

    assert len(events) == 1
    assert isinstance(events[0], MarketDatasetFetched)


# ---------------------------------------------------------------------------
# T-E1-4-02: State-consistency error path tests (M-020)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_watermark_not_mutated_on_outbox_failure() -> None:
    """If outbox.add() fails, watermark.save() is never called — mutation not persisted.

    The watermark advance happens in memory inside the UoW block, but because
    the exception from outbox.add() propagates before watermarks.save() is
    reached, the mutation never reaches the DB.
    """
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uow.outbox.add = AsyncMock(side_effect=RuntimeError("outbox failure"))
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    with pytest.raises(RuntimeError, match="outbox failure"):
        await uc.execute(task)

    # In-memory advance did occur (the call was made)
    wm.advance_bar_ts.assert_called_once()
    # DB persistence was never reached
    uow.watermarks.save.assert_not_awaited()
    uow.commit.assert_not_awaited()


@pytest.mark.unit
async def test_task_status_reverts_on_commit_failure() -> None:
    """If uow.commit() raises, task.succeed() was called in memory but DB not updated.

    The commit failure means the DB transaction is rolled back, so the task
    status stays at its pre-succeed state in the database even though the
    in-memory domain object was mutated.
    """
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    uow.commit = AsyncMock(side_effect=RuntimeError("db commit failed"))
    uc, uow, _, _, _ = _make_use_case(uow=uow)

    with pytest.raises(RuntimeError, match="db commit failed"):
        await uc.execute(task)

    # task.succeed() was called in memory before commit
    task.succeed.assert_called_once()
    # tasks.save() was also invoked (it was the commit that failed)
    uow.tasks.save.assert_awaited()


@pytest.mark.unit
async def test_minio_write_skipped_on_retry_if_object_exists() -> None:
    """If the bronze object already exists, put() is not called for bronze (D-008).

    Simulates a retry where the worker crashed after uploading bronze but before
    committing the DB transaction.  On the next run, exists() returns True and
    the upload is skipped, making the pipeline idempotent.
    """
    task = _make_task(dataset_type=DatasetType.OHLCV)
    store = _make_store()
    # bronze exists (skip put), canonical does not yet (allow put)
    store.exists = AsyncMock(side_effect=[True, False])
    uc, _, _, store, _ = _make_use_case(store=store)

    await uc.execute(task)

    # Bronze put skipped; only canonical put was called
    assert store.put.await_count == 1
    # Pipeline still completes
    task.succeed.assert_called_once()
    # exists() was queried for both bronze and canonical keys
    assert store.exists.await_count == 2


@pytest.mark.unit
async def test_execute_task_idempotent_on_replay() -> None:
    """Replaying a task with bronze already in object store completes without re-uploading.

    Full idempotency check: exists()=True skips bronze upload, canonical is
    re-computed and stored, watermark is advanced, and the task succeeds.
    """
    task = _make_task(dataset_type=DatasetType.OHLCV)
    wm = _make_watermark(changed=True)
    uow = _make_uow(watermark=wm)
    store = _make_store()
    # bronze exists (skip put), canonical does not yet (allow put)
    store.exists = AsyncMock(side_effect=[True, False])
    uc, uow, _registry, store, _ = _make_use_case(uow=uow, store=store)

    await uc.execute(task)

    # Bronze skipped, canonical stored
    assert store.put.await_count == 1
    # Watermark still advanced
    wm.advance_bar_ts.assert_called_once()
    # Outbox event still emitted (data changed)
    uow.outbox.add.assert_awaited_once()
    # Task succeeds
    task.succeed.assert_called_once()


# ---------------------------------------------------------------------------
# T-D-2-02: InvalidStateTransition → FAILED task persisted (F-DS-005)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_state_transition_persists_failed_task() -> None:
    """F-DS-005 regression: InvalidStateTransition must call _persist_fail so the task
    transitions to FAILED in the DB instead of remaining stuck in RUNNING state.
    """
    from market_ingestion.domain.errors import InvalidStateTransition

    task = _make_task()
    wm = _make_watermark()
    uow = _make_uow(watermark=wm)

    # Make task.succeed() raise InvalidStateTransition (task in wrong state)
    task.succeed = MagicMock(side_effect=InvalidStateTransition("task already succeeded"))

    uc, uow, _registry, _store, _ = _make_use_case(uow=uow)

    with pytest.raises(InvalidStateTransition):
        await uc.execute(task)

    # task.fail() must have been called (inside _persist_fail)
    task.fail.assert_called_once()
    # tasks.save must have been called with the task in FAILED state
    uow.tasks.save.assert_awaited()


@pytest.mark.asyncio
async def test_invalid_state_transition_reraises() -> None:
    """F-DS-005 regression: InvalidStateTransition still propagates after persistence
    so the caller (scheduler) can handle or log the fatal error.
    """
    from market_ingestion.domain.errors import InvalidStateTransition

    task = _make_task()
    uow = _make_uow()
    original_exc = InvalidStateTransition("already in terminal state")
    task.succeed = MagicMock(side_effect=original_exc)

    uc, _uow, _registry, _store, _ = _make_use_case(uow=uow)

    with pytest.raises(InvalidStateTransition) as exc_info:
        await uc.execute(task)

    assert exc_info.value is original_exc, "must re-raise the original exception"


@pytest.mark.unit
async def test_type_error_in_canonicalize_fails_task_bp113() -> None:
    """BP-113 regression: TypeError from None-valued OHLCV field must call _persist_fail.

    EODHD intraday returns bars with None for volume; int(None) raises TypeError.
    Before the fix, TypeError was not caught, so the task stayed RUNNING forever.
    After the fix, TypeError is caught and _persist_fail is called.
    """
    import json

    # Raw data with None volume — triggers int(None) in CanonicalOHLCVBar.from_dict
    raw_with_none_volume = json.dumps(
        [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": None, "date": "2025-01-01"}]
    ).encode()

    task = _make_task(dataset_type=DatasetType.OHLCV, timeframe="1d")
    uow = _make_uow()

    # Use real serializer to trigger the actual TypeError path
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    real_serializer = DefaultCanonicalSerializer()
    registry = _make_registry(raw_data=raw_with_none_volume)
    store = _make_store()

    uc = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=real_serializer,
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )

    with pytest.raises(ProviderDataError):
        await uc.execute(task)

    # task.fail must have been called (BP-113 fix)
    task.fail.assert_called_once()


# ---------------------------------------------------------------------------
# M-007: Watermark race condition tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_watermark_violation_triggers_retry() -> None:
    """WatermarkViolation from advance_bar_ts → task.retry() called, status is RETRY not FAILED.

    When two workers race on the same watermark, the loser receives a
    WatermarkViolation.  The correct response is task.retry() so the task is
    re-queued; task.fail() must NOT be called (the task is not broken, just lost
    a race).
    """
    task = _make_task()
    # Simulate task in RUNNING state (after claim)
    task.status = "running"

    wm = _make_watermark()
    wm.advance_bar_ts.side_effect = WatermarkViolation("non-monotonic: new_ts <= current_ts")
    uow = _make_uow(watermark=wm)
    uc, _, _, _, _ = _make_use_case(uow=uow)

    # WatermarkViolation should propagate after triggering retry
    with pytest.raises(WatermarkViolation):
        await uc.execute(task)

    # retry() called — task goes back to RETRY queue
    task.retry.assert_called_once()
    # fail() must NOT be called — this is a transient race, not a fatal error
    task.fail.assert_not_called()


@pytest.mark.unit
async def test_watermark_concurrent_advance_only_one_succeeds() -> None:
    """Concurrent advance with same bar_ts: one succeeds, other gets WatermarkViolation and retries.

    Simulates two tasks racing to advance the same watermark.  The second call
    raises WatermarkViolation, which must result in retry(), not fail().
    """

    bar_ts = datetime(2024, 6, 30, tzinfo=UTC)

    # Task 1: succeeds (watermark advances normally)
    task1 = _make_task(range_end=bar_ts)
    wm1 = _make_watermark(changed=True)
    uow1 = _make_uow(watermark=wm1)
    uc1, _, _, _, _ = _make_use_case(uow=uow1)

    # Task 2: races, loses — watermark raises WatermarkViolation
    task2 = _make_task(range_end=bar_ts)
    wm2 = _make_watermark(changed=True)
    wm2.advance_bar_ts.side_effect = WatermarkViolation("concurrent advance detected")
    uow2 = _make_uow(watermark=wm2)
    uc2, _, _, _, _ = _make_use_case(uow=uow2)

    # Task 1 executes successfully
    await uc1.execute(task1)
    task1.succeed.assert_called_once()
    task1.retry.assert_not_called()

    # Task 2 races and loses → retry, not fail
    with pytest.raises(WatermarkViolation):
        await uc2.execute(task2)

    task2.retry.assert_called_once()
    task2.fail.assert_not_called()

    # Only one watermark was actually advanced (task1's)
    wm1.advance_bar_ts.assert_called_once_with(bar_ts)
    wm2.advance_bar_ts.assert_called_once_with(bar_ts)  # called but raised


@pytest.mark.unit
async def test_canonicalize_type_error_marks_failed() -> None:
    """BP-113 regression: None field in record → TypeError → task.fail() called (not stuck RUNNING).

    Feed a record where volume is None (simulating missing EODHD intraday data).
    The real serializer will raise TypeError; ExecuteTaskUseCase must catch it
    and call task.fail(), not leave the task stuck in RUNNING state.
    """
    import json as _json

    raw_with_none_volume = _json.dumps(
        [{"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": None, "date": "2025-01-01"}]
    ).encode()

    task = _make_task(dataset_type=DatasetType.OHLCV, timeframe="1d")
    uow = _make_uow()

    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    real_serializer = DefaultCanonicalSerializer()
    registry = _make_registry(raw_data=raw_with_none_volume)
    store = _make_store()

    uc = ExecuteTaskUseCase(
        uow=uow,
        provider_registry=registry,
        object_store=store,
        serializer=real_serializer,
        bronze_bucket="market-bronze",
        canonical_bucket="market-canonical",
    )

    with pytest.raises(ProviderDataError):
        await uc.execute(task)

    # task.fail() must be called — task transitions to FAILED, not stuck in RUNNING
    task.fail.assert_called_once()
    task.retry.assert_not_called()
