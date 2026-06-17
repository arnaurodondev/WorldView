"""Shared pipeline steps — object storage, DB transaction, and pre-fetch guards.

Implements Steps 0-5 of the ingestion pipeline as standalone async functions,
called by ExecuteTaskUseCase for both the ``execute()`` and the
``execute_with_prefetched_result()`` batch paths.

Separation of concerns:
  pre_fetch_checks()     — Steps 0 and 0.5: quota + circuit breaker
  fetch_with_guards()    — Step 1: fetch + circuit breaker bookkeeping
  zero_bar_failover()    — Zero-bar failover re-fetch
  run_steps_2_to_5()     — Steps 2-5: bronze -> canonicalize -> canonical -> DB
  store_bronze()         — Step 2 only (also used by execute_with_prefetched_result)
  store_canonical()      — Step 4 only (also used by execute_with_prefetched_result)
  commit_transaction()   — Step 5 only (also used by execute_with_prefetched_result)
  persist_retry()        — task.retry() + DB save
  persist_fail()         — task.fail() + DB save
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import (
    InvalidStateTransition,
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
    ProviderUnsupportedSymbol,
    StorageUnavailable,
    TaskLeaseLost,
    WatermarkViolation,
)
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import ObjectRef
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import (
        CanonicalSerializer,
        ObjectStoreAdapter,
        ProviderAdapter,
        ProviderFetchResult,
    )
    from market_ingestion.application.ports.circuit_breaker import CircuitBreakerPort
    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.application.ports.zero_bar_tracker import ZeroBarTrackerPort
    from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.providers import ProviderRegistry
    from messaging.eodhd_quota.quota_service import EodhdQuotaService

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Steps 0 + 0.5 -- quota and circuit breaker pre-fetch guards
# ---------------------------------------------------------------------------


async def pre_fetch_checks(
    task: IngestionTask,
    preferred: Provider,
    quota_service: EodhdQuotaService | None,
    service_name: str,
    circuit_breaker: CircuitBreakerPort | None,
    uow: UnitOfWork,
    log: Any,
) -> None:
    """Run quota (Step 0) and circuit breaker (Step 0.5) guards before fetching.

    Raises ProviderRateLimited (after calling persist_retry) when limits are hit.
    """
    # -- Step 0: Monthly quota check -----------------------------------------
    if quota_service is not None and preferred == Provider.EODHD:
        from market_ingestion.application.use_cases.strategies.routing import _task_credit_cost
        from messaging.eodhd_quota.quota_service import QuotaCheckResult

        cost = _task_credit_cost(task)
        quota_result = await quota_service.try_consume(cost=cost, service=service_name, symbol=task.symbol)
        if quota_result == QuotaCheckResult.HARD_LIMIT_EXCEEDED:
            log.warning("quota_hard_limit_exceeded", cost=cost, monthly_quota_limit=quota_service._hard_limit)
            exc = ProviderRateLimited("Monthly EODHD quota exhausted -- task deferred")
            await persist_retry(task, exc, uow)
            from market_ingestion.application.metrics.eodhd import eodhd_quota_blocked_total

            eodhd_quota_blocked_total.labels(dataset_type=str(task.dataset_type)).inc()
            raise exc
        elif quota_result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED:
            log.warning("quota_soft_limit_exceeded", cost=cost)

    # -- Step 0.5: Circuit breaker check -------------------------------------
    if circuit_breaker is not None and preferred == Provider.EODHD:
        endpoint = str(task.dataset_type)
        try:
            cb_open = await circuit_breaker.is_open(endpoint)
        except Exception as cb_exc:
            log.warning("circuit_breaker_unavailable", error=str(cb_exc))
            cb_open = False
        if cb_open:
            log.warning("circuit_breaker_open", endpoint=endpoint)
            exc = ProviderRateLimited("EODHD circuit breaker OPEN -- task deferred")
            await persist_retry(task, exc, uow)
            raise exc


# ---------------------------------------------------------------------------
# Step 1 -- fetch with circuit breaker bookkeeping and error classification
# ---------------------------------------------------------------------------


async def fetch_with_guards(
    adapter: ProviderAdapter,
    task: IngestionTask,
    circuit_breaker: CircuitBreakerPort | None,
    uow: UnitOfWork,
    log: Any,
) -> ProviderFetchResult:
    """Step 1: fetch from provider, record CB outcome, classify errors.

    Calls persist_retry/persist_fail before re-raising any error.
    """
    from market_ingestion.application.use_cases.strategies.fetch import fetch_for_task

    try:
        result = await fetch_for_task(adapter, task)
        if circuit_breaker is not None:
            try:
                await circuit_breaker.record_success(str(task.dataset_type))
            except Exception as cb_exc:
                log.warning("circuit_breaker_unavailable", error=str(cb_exc))
        return result
    except (ProviderRateLimited, ProviderUnavailable, TaskLeaseLost) as exc:
        log.warning("fetch_retryable_error", error=str(exc))
        if circuit_breaker is not None and not isinstance(exc, TaskLeaseLost):
            try:
                await circuit_breaker.record_failure(str(task.dataset_type))
            except Exception as cb_exc:
                log.warning("circuit_breaker_unavailable", error=str(cb_exc))
        await persist_retry(task, exc, uow)
        raise
    except ProviderUnsupportedSymbol as exc:
        log.warning("provider_unsupported_symbol", error=str(exc))
        await persist_fail(task, exc, uow)
        raise
    except (ProviderAuthError, ProviderDataError) as exc:
        log.error("fetch_fatal_error", error=str(exc))
        await persist_fail(task, exc, uow)
        raise


# ---------------------------------------------------------------------------
# Zero-bar failover -- re-fetch from the next provider in the chain
# ---------------------------------------------------------------------------


async def zero_bar_failover(
    task: IngestionTask,
    fetch_result: ProviderFetchResult,
    preferred: Provider,
    zero_bar_tracker: ZeroBarTrackerPort,
    registry: ProviderRegistry,
    routing_cache: ProviderRoutingCache | None,
    uow: UnitOfWork,
    log: Any,
) -> ProviderFetchResult:
    """Apply zero-bar streak tracking and optional provider failover.

    Returns the (possibly updated) fetch_result. Dataset gate: only
    _ZERO_BAR_DATASET_TYPES are tracked; others are returned unchanged.
    """
    from market_ingestion.application.use_cases.strategies.routing import (
        _ZERO_BAR_DATASET_TYPES,
        _fallback_provider,
    )

    if task.dataset_type not in _ZERO_BAR_DATASET_TYPES:
        return fetch_result

    if fetch_result.bars_returned == 0:
        try:
            streak = await zero_bar_tracker.record_zero(
                provider=preferred.value,
                symbol=task.symbol,
                timeframe=task.timeframe or "",
                dataset_type=str(task.dataset_type),
            )
        except Exception as zbt_exc:
            log.warning("zero_bar_tracker_unavailable", error=str(zbt_exc))
            streak = 0
        log.debug("zero_bar_streak_recorded", streak=streak, provider=preferred.value)
        if zero_bar_tracker.should_failover(streak):
            fallback = _fallback_provider(task.dataset_type, task.timeframe, preferred, registry, routing_cache)
            if fallback is not None:
                from market_ingestion.application.use_cases.strategies.fetch import fetch_for_task

                fallback_adapter = registry.get(fallback)
                log.warning(
                    "provider_zero_bar_failover",
                    streak=streak,
                    primary_provider=preferred.value,
                    fallback_provider=fallback.value,
                    symbol=task.symbol,
                    timeframe=task.timeframe or "",
                )
                try:
                    fetch_result = await fetch_for_task(fallback_adapter, task)
                except (ProviderRateLimited, ProviderUnavailable, TaskLeaseLost) as exc:
                    log.warning("fallback_fetch_retryable_error", error=str(exc))
                    await persist_retry(task, exc, uow)
                    raise
                except (ProviderAuthError, ProviderDataError) as exc:
                    log.error("fallback_fetch_fatal_error", error=str(exc))
                    await persist_fail(task, exc, uow)
                    raise
            else:
                log.warning(
                    "provider_zero_bar_no_fallback",
                    streak=streak,
                    provider=preferred.value,
                    dataset_type=str(task.dataset_type),
                )
    else:
        try:
            await zero_bar_tracker.reset(
                provider=preferred.value,
                symbol=task.symbol,
                timeframe=task.timeframe or "",
                dataset_type=str(task.dataset_type),
            )
        except Exception as zbt_exc:
            log.warning("zero_bar_tracker_unavailable", error=str(zbt_exc))

    return fetch_result


# ---------------------------------------------------------------------------
# Steps 2-5 combined helper
# ---------------------------------------------------------------------------


async def run_steps_2_to_5(
    task: IngestionTask,
    fetch_result: ProviderFetchResult,
    store: ObjectStoreAdapter,
    bronze_bucket: str,
    serializer: CanonicalSerializer,
    canonical_bucket: str,
    uow: UnitOfWork,
    log: Any,
) -> None:
    """Run Steps 2-5 in sequence: bronze store -> canonicalize -> canonical store -> DB.

    All errors call persist_retry/persist_fail before re-raising.
    On success, logs task_succeeded.
    """
    from market_ingestion.application.use_cases.strategies.canonicalize import canonicalize_task

    try:
        bronze_ref = await store_bronze(task, fetch_result, store, bronze_bucket)
    except StorageUnavailable as exc:
        log.warning("bronze_store_retryable", error=str(exc))
        await persist_retry(task, exc, uow)
        raise

    try:
        canonical_bytes, row_count = canonicalize_task(task, fetch_result, serializer)
    except (ProviderDataError, ValueError, KeyError, TypeError) as exc:
        log.error("canonicalize_fatal", error=str(exc))
        await persist_fail(task, ProviderDataError(str(exc)), uow)
        raise ProviderDataError(str(exc)) from exc

    try:
        canonical_ref = await store_canonical(task, canonical_bytes, store, canonical_bucket)
    except StorageUnavailable as exc:
        log.warning("canonical_store_retryable", error=str(exc))
        await persist_retry(task, exc, uow)
        raise

    try:
        await commit_transaction(task, bronze_ref, canonical_ref, row_count, uow, log)
    except WatermarkViolation as exc:
        log.warning("watermark_violation_retry", error=str(exc), task_id=task.id)
        await persist_retry(task, exc, uow)
        raise
    except InvalidStateTransition as exc:
        log.error("invalid_state_transition", error=str(exc))
        await persist_fail(task, exc, uow)
        raise

    log.info("task_succeeded", row_count=row_count)


# ---------------------------------------------------------------------------
# Individual step helpers (also used directly by execute_with_prefetched_result)
# ---------------------------------------------------------------------------


async def store_bronze(
    task: IngestionTask,
    fetch_result: ProviderFetchResult,
    store: ObjectStoreAdapter,
    bronze_bucket: str,
) -> ObjectRef:
    """Step 2: Write raw provider bytes to the bronze object store.

    D-008: On retry the object may already exist -- skip the upload and
    reconstruct the ObjectRef using a locally-computed SHA-256.
    """
    key = f"market-ingestion/raw/{task.provider}/{task.dataset_type}/{task.symbol}/{task.id}"
    if await store.exists(bronze_bucket, key):
        sha256 = hashlib.sha256(fetch_result.raw_data).hexdigest()
        return ObjectRef(
            bucket=bronze_bucket,
            key=key,
            sha256=sha256,
            byte_length=len(fetch_result.raw_data),
            mime_type=fetch_result.content_type,
        )
    return await store.put(bronze_bucket, key, fetch_result.raw_data, fetch_result.content_type)


async def store_canonical(
    task: IngestionTask,
    canonical_bytes: bytes,
    store: ObjectStoreAdapter,
    canonical_bucket: str,
) -> ObjectRef:
    """Step 4: Write canonical JSONL bytes to the canonical object store (BP-357)."""
    key = f"market-ingestion/canonical/{task.provider}/{task.dataset_type}/{task.symbol}/{task.id}.jsonl"
    return await store.put(canonical_bucket, key, canonical_bytes, "application/x-ndjson")


async def commit_transaction(
    task: IngestionTask,
    bronze_ref: ObjectRef,
    canonical_ref: ObjectRef,
    row_count: int,
    uow: UnitOfWork,
    log: Any,
) -> None:
    """Step 5: Short DB transaction -- advance watermark + outbox event + task.succeed()."""
    new_sha256 = canonical_ref.sha256

    async with uow:
        watermark = await uow.watermarks.get_or_create(
            provider=str(task.provider),
            dataset_type=str(task.dataset_type),
            symbol=task.symbol,
            exchange=task.exchange,
            timeframe=task.timeframe,
            variant=task.variant,
        )
        locked = await uow.watermarks.get_for_update(
            provider=str(task.provider),
            dataset_type=str(task.dataset_type),
            symbol=task.symbol,
            exchange=task.exchange,
            timeframe=task.timeframe,
            variant=task.variant,
        )
        if locked is not None:
            watermark = locked

        data_changed = watermark.has_changed(new_sha256)
        # FIX-FUTURE-WM: clamp the watermark to wall-clock now.  Incremental
        # daily tasks carry range_end = tomorrow-midnight; advancing the
        # watermark into the FUTURE made every same-day follow-up look stale
        # (new_ts <= current_bar_ts), suppressing both the watermark advance
        # and the outbox event for the rest of the day.
        new_ts = min(task.range_end, utc_now()) if task.range_end is not None else task.created_at
        if watermark.current_bar_ts is None or new_ts > watermark.current_bar_ts:
            watermark.advance_bar_ts(new_ts)
        else:
            log.debug(
                "skip_stale_watermark_update",
                current_bar_ts=watermark.current_bar_ts.isoformat(),
                task_bar_ts=new_ts.isoformat(),
            )
            data_changed = False
        watermark.content_hash = new_sha256

        if data_changed:
            # SOURCE-PROVENANCE FIX: emit the provider that ACTUALLY fetched the
            # data, not the provider the task was originally scheduled for.
            # ``task.provider`` is the scheduled/policy provider (e.g. ``eodhd``
            # for the 554 enabled ``eodhd ohlcv 1d`` policies), but at execution
            # time ``ExecuteTaskUseCase`` re-routes EOD OHLCV to Yahoo Finance via
            # the routing cache (``routing_ohlcv_eod = yahoo_finance:100,eodhd:80``)
            # and records the real fetcher in ``task.fetched_by_provider``.  Before
            # this fix the outbox event always carried the scheduled provider, so
            # market-data (S3) labelled every Yahoo-fetched daily bar
            # ``source = eodhd`` — making Yahoo's contribution invisible (the
            # "Yahoo produces 0 bars" symptom) and over-stating EODHD daily volume.
            # Falls back to the scheduled provider when no re-route happened
            # (``fetched_by_provider`` is None on the non-routed / prefetched path).
            actual_provider = task.fetched_by_provider or str(task.provider)
            event = MarketDatasetFetched(
                provider=actual_provider,
                dataset_type=str(task.dataset_type),
                symbol=task.symbol,
                exchange=task.exchange,
                timeframe=task.timeframe,
                variant=task.variant,
                range_start=task.range_start.isoformat() if task.range_start else "",
                range_end=task.range_end.isoformat() if task.range_end else "",
                bronze_ref=bronze_ref,
                canonical_ref=canonical_ref,
                canonical_schema_version=1,
                row_count=row_count,
                task_id=task.id,
                # BUG-009 / BP-492: propagate backfill flag — tasks with an
                # explicit ``range_start`` are historical replays and downstream
                # consumers (S5 market-data) must distinguish them from live
                # ticks so they don't overwrite the live high-water mark.
                is_backfill=task.range_start is not None,
            )
            await uow.outbox.add(events=[event])
        else:
            log.debug("skip_outbox_unchanged_sha256", sha256_prefix=new_sha256[:8] if new_sha256 else "")

        await uow.watermarks.save(watermark)
        original_lease_owner = task.lease_owner
        task.succeed(canonical_ref)
        await uow.tasks.save(task, original_lease_owner=original_lease_owner)
        await uow.commit()


async def persist_retry(task: IngestionTask, exc: Exception, uow: UnitOfWork) -> None:
    """Transition task to RETRY state and persist to DB (BP-NEW-task-save-lease)."""
    original_lease_owner = task.lease_owner
    task.retry(exc)
    async with uow:
        await uow.tasks.save(task, original_lease_owner=original_lease_owner)
        await uow.commit()


async def persist_fail(task: IngestionTask, exc: Exception, uow: UnitOfWork) -> None:
    """Transition task to FAILED state and persist to DB (BP-NEW-task-save-lease)."""
    original_lease_owner = task.lease_owner
    task.fail(exc)
    async with uow:
        await uow.tasks.save(task, original_lease_owner=original_lease_owner)
        await uow.commit()
