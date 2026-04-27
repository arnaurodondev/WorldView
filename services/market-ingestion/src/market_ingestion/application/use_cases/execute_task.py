"""ExecuteTaskUseCase — 5-step ingestion pipeline.

Pipeline order (critical — do NOT reorder):
  0. Quota check — block if monthly EODHD limit is exhausted (optional).
  1. Fetch raw data from provider (outside DB transaction).
  2. Store raw bytes as bronze object in object storage (outside transaction).
  3. Canonicalize raw data (outside transaction).
  4. Store canonical JSONL bytes in object storage (outside transaction).
  5. Short DB transaction: advance watermark + add outbox event + task.succeed() + commit.

Error classification:
  Retryable  → ProviderRateLimited, ProviderUnavailable, StorageUnavailable, TaskLeaseLost,
               WatermarkViolation (concurrent worker race — re-queued via task.retry())
  Fatal      → ProviderAuthError, ProviderDataError, InvalidStateTransition
"""

from __future__ import annotations

import hashlib
from datetime import UTC
from typing import TYPE_CHECKING, Any, cast

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    InvalidStateTransition,
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
    StorageUnavailable,
    TaskLeaseLost,
    WatermarkViolation,
)
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.freshness import EODHD_CREDIT_COST, EODHD_INTRADAY_COST, INTRADAY_TIMEFRAMES
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


class ExecuteTaskUseCase:
    """Execute a single claimed ingestion task through the 5-step pipeline.

    Optional dependencies (passed as constructor arguments when available):

    ``quota_service``
        When provided, the monthly EODHD credit quota is checked *before* any
        provider call.  Tasks that would exceed the hard limit are retried at the
        next scheduler tick rather than failing permanently, and the worker logs
        a ``quota_hard_limit_exceeded`` event.  When ``None``, quota enforcement
        is bypassed (useful in tests or non-EODHD provider contexts).
    """

    def __init__(
        self,
        uow: UnitOfWork,
        provider_registry: ProviderRegistry,
        object_store: ObjectStoreAdapter,
        serializer: CanonicalSerializer,
        bronze_bucket: str = "market-bronze",
        canonical_bucket: str = "market-canonical",
        quota_service: EodhdQuotaService | None = None,
        service_name: str = "market-ingestion",
        circuit_breaker: CircuitBreakerPort | None = None,
        zero_bar_tracker: ZeroBarTrackerPort | None = None,
        routing_cache: ProviderRoutingCache | None = None,
    ) -> None:
        self._uow = uow
        self._registry = provider_registry
        self._store = object_store
        self._serializer = serializer
        self._bronze_bucket = bronze_bucket
        self._canonical_bucket = canonical_bucket
        # Optional shared monthly quota enforcer (Valkey-backed, multi-replica safe).
        self._quota_service = quota_service
        self._service_name = service_name
        # Optional cross-replica circuit breaker (Valkey-backed).
        # When provided, blocks fetch calls when EODHD is degraded and records
        # success/failure outcomes to coordinate state across replicas.
        self._circuit_breaker = circuit_breaker
        # Optional zero-bar streak tracker (Valkey-backed).
        # When provided, tracks consecutive zero-bar responses per provider/symbol
        # and triggers failover to the next provider after FAILOVER_THRESHOLD misses.
        self._zero_bar_tracker = zero_bar_tracker
        # Optional config-backed routing cache (PRD-0032).
        # When provided, provider selection uses cache.primary_for() instead of the
        # static _preferred_provider() heuristic.  When None, falls back to static logic.
        self._routing_cache = routing_cache

    async def execute_with_prefetched_result(self, task: IngestionTask, fetch_result: ProviderFetchResult) -> None:
        """Run Steps 2-5 of the pipeline using an already-fetched result.

        Called by the worker batch execution path when the provider adapter
        supports multi-symbol batching (e.g. Alpaca ``fetch_ohlcv_batch``).
        The batch call is performed once for N symbols and each symbol's
        ``ProviderFetchResult`` is then fed into this method for storage,
        canonicalization, and the DB transaction.

        Skips: Step 0 (quota), Step 0.5 (circuit breaker), Step 1 (fetch),
        and zero-bar failover — these are either inapplicable (batch providers
        are free-tier) or handled by the caller.
        """
        log = logger.bind(
            task_id=task.id,
            provider=str(task.provider),
            symbol=task.symbol,
            dataset_type=str(task.dataset_type),
        )

        # Record which provider actually fetched the data (T-A-4-03).
        task.fetched_by_provider = fetch_result.provider.value

        # ── Step 2: Store bronze ─────────────────────────────────────────────
        try:
            bronze_ref = await self._store_bronze(task, fetch_result)
        except StorageUnavailable as exc:
            log.warning("bronze_store_retryable", error=str(exc))
            await self._persist_retry(task, exc)
            raise

        # ── Step 3: Canonicalize ─────────────────────────────────────────────
        try:
            canonical_bytes, row_count = self._canonicalize(task, fetch_result)
        except (ProviderDataError, ValueError, KeyError, TypeError) as exc:
            log.error("canonicalize_fatal", error=str(exc))
            await self._persist_fail(task, ProviderDataError(str(exc)))
            raise ProviderDataError(str(exc)) from exc

        # ── Step 4: Store canonical ──────────────────────────────────────────
        try:
            canonical_ref = await self._store_canonical(task, canonical_bytes)
        except StorageUnavailable as exc:
            log.warning("canonical_store_retryable", error=str(exc))
            await self._persist_retry(task, exc)
            raise

        # ── Step 5: Short transaction ────────────────────────────────────────
        new_sha256 = canonical_ref.sha256

        try:
            async with self._uow:
                watermark = await self._uow.watermarks.get_or_create(
                    provider=str(task.provider),
                    dataset_type=str(task.dataset_type),
                    symbol=task.symbol,
                    exchange=task.exchange,
                    timeframe=task.timeframe,
                    variant=task.variant,
                )
                locked = await self._uow.watermarks.get_for_update(
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

                new_ts = task.range_end if task.range_end is not None else task.created_at
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
                    event = MarketDatasetFetched(
                        provider=str(task.provider),
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
                    )
                    await self._uow.outbox.add(events=[event])
                else:
                    log.debug(
                        "skip_outbox_unchanged_sha256",
                        sha256_prefix=new_sha256[:8] if new_sha256 else "",
                    )

                await self._uow.watermarks.save(watermark)
                # Capture lease owner before succeed() clears it (BP-NEW-task-save-lease).
                original_lease_owner = task.lease_owner
                task.succeed(canonical_ref)
                await self._uow.tasks.save(task, original_lease_owner=original_lease_owner)
                await self._uow.commit()

        except WatermarkViolation as exc:
            log.warning("watermark_violation_retry", error=str(exc), task_id=task.id)
            await self._persist_retry(task, exc)
            raise
        except InvalidStateTransition as exc:
            log.error("invalid_state_transition", error=str(exc))
            await self._persist_fail(task, exc)
            raise

        log.info("task_succeeded", row_count=row_count)

    async def execute(self, task: IngestionTask) -> None:
        """Run the pipeline for *task*.

        Raises
        ------
            ProviderRateLimited / ProviderUnavailable / StorageUnavailable /
            WatermarkViolation:
                Retryable errors — task.retry() called before re-raise.
                WatermarkViolation indicates a concurrent worker race; the task is
                re-queued via retry() so the worker loop picks it up again.
            ProviderAuthError / ProviderDataError / InvalidStateTransition:
                Fatal errors — task.fail() called before re-raise.

        """
        log = logger.bind(
            task_id=task.id,
            provider=str(task.provider),
            symbol=task.symbol,
            dataset_type=str(task.dataset_type),
        )

        # ── Provider routing ──────────────────────────────────────────────────
        # Select the best registered provider for this dataset/timeframe.
        # When a ProviderRoutingCache is wired in (PRD-0032), use it as the
        # primary path.  When absent or when the cache returns an unknown/
        # unregistered provider, fall back to the static _preferred_provider()
        # heuristic for backward compatibility.
        #
        # The task.provider stored in DB reflects what was *requested*; the
        # actual adapter used for this execution may differ (e.g. Alpaca for
        # intraday OHLCV, Yahoo for EOD).
        if self._routing_cache is not None:
            # Dynamic config-backed routing (PRD-0032 primary path).
            primary_provider_str = self._routing_cache.primary_for(str(task.dataset_type), task.timeframe)
            try:
                preferred = Provider(primary_provider_str)
                adapter = self._registry.get(preferred)
            except (ValueError, ProviderUnavailable):
                # Unknown or unregistered provider from cache — fall back to static routing.
                preferred = _preferred_provider(task.dataset_type, task.timeframe, self._registry)
                adapter = self._registry.get(preferred)
        else:
            # Static routing fallback (PLAN-0038 A-4 path — backward compatible).
            preferred = _preferred_provider(task.dataset_type, task.timeframe, self._registry)
            adapter = self._registry.get(preferred)

        if preferred != task.provider:
            log.info(
                "provider_routing_cache_selected",
                requested=str(task.provider),
                selected=preferred.value,
                dataset_type=str(task.dataset_type),
                timeframe=task.timeframe or "",
            )

        # ── Step 0: Monthly quota check ──────────────────────────────────────
        # Only enforced when a shared EodhdQuotaService is wired in AND the
        # selected provider is EODHD (free providers have no quota).
        if self._quota_service is not None and preferred == Provider.EODHD:
            cost = _task_credit_cost(task)
            from messaging.eodhd_quota.quota_service import QuotaCheckResult

            quota_result = await self._quota_service.try_consume(
                cost=cost,
                service=self._service_name,
                symbol=task.symbol,
            )
            if quota_result == QuotaCheckResult.HARD_LIMIT_EXCEEDED:
                log.warning(
                    "quota_hard_limit_exceeded",
                    cost=cost,
                    monthly_quota_limit=self._quota_service._hard_limit,
                )
                # Treat quota exhaustion as a retryable error so the task is
                # re-queued for the next month rather than permanently failed.
                exc = ProviderRateLimited("Monthly EODHD quota exhausted — task deferred")
                await self._persist_retry(task, exc)
                # NOTE: metric increment intentionally lives here rather than in an
                # infrastructure callback to keep the quota-block -> persist-retry ->
                # increment -> raise sequence atomic.  Accepted layer violation (F-010).
                from market_ingestion.infrastructure.metrics.eodhd import (
                    eodhd_quota_blocked_total,
                )

                eodhd_quota_blocked_total.labels(dataset_type=str(task.dataset_type)).inc()
                raise exc
            elif quota_result == QuotaCheckResult.SOFT_LIMIT_EXCEEDED:
                log.warning(
                    "quota_soft_limit_exceeded",
                    cost=cost,
                )
                # Soft limit: log and proceed — do not block the call.

        # ── Step 0.5: Circuit breaker check ─────────────────────────────────
        # If the EODHD circuit is OPEN, block the fetch and retry the task.
        # HALF_OPEN allows one probe call through (is_open returns False) so
        # the circuit can self-heal after the cooldown period.
        # Only applies to EODHD — free providers have their own rate-limit
        # handling and the CB is EODHD-specific infrastructure.
        # F-004: Valkey errors are caught so a Valkey outage does not crash
        # the task — we assume CLOSED (let the fetch proceed) on failure.
        if self._circuit_breaker is not None and preferred == Provider.EODHD:
            endpoint = str(task.dataset_type)
            try:
                cb_open = await self._circuit_breaker.is_open(endpoint)
            except Exception as cb_exc:
                log.warning("circuit_breaker_unavailable", error=str(cb_exc))
                cb_open = False
            if cb_open:
                log.warning("circuit_breaker_open", endpoint=endpoint)
                exc = ProviderRateLimited("EODHD circuit breaker OPEN — task deferred")
                await self._persist_retry(task, exc)
                raise exc

        # ── Step 1: Fetch ────────────────────────────────────────────────────
        try:
            fetch_result = await self._fetch(adapter, task)
            # Record success after a clean fetch so the circuit can close after
            # a HALF_OPEN probe or reset the failure counter in CLOSED state.
            if self._circuit_breaker is not None:
                try:
                    await self._circuit_breaker.record_success(str(task.dataset_type))
                except Exception as cb_exc:
                    log.warning("circuit_breaker_unavailable", error=str(cb_exc))
        except (ProviderRateLimited, ProviderUnavailable, TaskLeaseLost) as exc:
            log.warning("fetch_retryable_error", error=str(exc))
            # Count rate-limit and unavailability errors toward the circuit
            # breaker threshold.  TaskLeaseLost is a local scheduling issue
            # (not a provider error) so we skip it.
            if self._circuit_breaker is not None and not isinstance(exc, TaskLeaseLost):
                try:
                    await self._circuit_breaker.record_failure(str(task.dataset_type))
                except Exception as cb_exc:
                    log.warning("circuit_breaker_unavailable", error=str(cb_exc))
            await self._persist_retry(task, exc)
            raise
        except (ProviderAuthError, ProviderDataError) as exc:
            log.error("fetch_fatal_error", error=str(exc))
            await self._persist_fail(task, exc)
            raise

        # ── Zero-bar failover check ──────────────────────────────────────────
        # Tracks consecutive zero-bar responses per (provider, symbol, timeframe,
        # dataset). After FAILOVER_THRESHOLD (default 5) consecutive misses,
        # re-route to the next provider in the priority chain.
        # Dataset gate: only list-type datasets can have meaningful zero-bar
        # counts; FUNDAMENTALS/MACRO always return bars_returned=1.
        # F-004: Valkey errors in the zero-bar tracker are caught so a Valkey
        # outage does not crash the task.  On record_zero failure we default
        # streak=0 (skip failover); on reset failure we log and continue.
        if self._zero_bar_tracker is not None and task.dataset_type in _ZERO_BAR_DATASET_TYPES:
            if fetch_result.bars_returned == 0:
                try:
                    streak = await self._zero_bar_tracker.record_zero(
                        provider=preferred.value,
                        symbol=task.symbol,
                        timeframe=task.timeframe or "",
                        dataset_type=str(task.dataset_type),
                    )
                except Exception as zbt_exc:
                    log.warning("zero_bar_tracker_unavailable", error=str(zbt_exc))
                    streak = 0  # cannot determine streak — skip failover
                log.debug("zero_bar_streak_recorded", streak=streak, provider=preferred.value)
                if self._zero_bar_tracker.should_failover(streak):
                    fallback = _fallback_provider(
                        task.dataset_type, task.timeframe, preferred, self._registry, self._routing_cache
                    )
                    if fallback is not None:
                        fallback_adapter = self._registry.get(fallback)
                        log.warning(
                            "provider_zero_bar_failover",
                            streak=streak,
                            primary_provider=preferred.value,
                            fallback_provider=fallback.value,
                            symbol=task.symbol,
                            timeframe=task.timeframe or "",
                        )
                        try:
                            fetch_result = await self._fetch(fallback_adapter, task)
                        except (ProviderRateLimited, ProviderUnavailable, TaskLeaseLost) as exc:
                            log.warning("fallback_fetch_retryable_error", error=str(exc))
                            await self._persist_retry(task, exc)
                            raise
                        except (ProviderAuthError, ProviderDataError) as exc:
                            log.error("fallback_fetch_fatal_error", error=str(exc))
                            await self._persist_fail(task, exc)
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
                    await self._zero_bar_tracker.reset(
                        provider=preferred.value,
                        symbol=task.symbol,
                        timeframe=task.timeframe or "",
                        dataset_type=str(task.dataset_type),
                    )
                except Exception as zbt_exc:
                    log.warning("zero_bar_tracker_unavailable", error=str(zbt_exc))

        # Record which provider actually fetched the data (T-A-4-03).
        # This is set before the DB transaction so it is included in the SUCCEEDED
        # row written in Step 5.  fetch_result.provider reflects the actual adapter
        # used — may differ from task.provider when routing cache overrides.
        task.fetched_by_provider = fetch_result.provider.value

        # ── Step 2: Store bronze ─────────────────────────────────────────────
        try:
            bronze_ref = await self._store_bronze(task, fetch_result)
        except StorageUnavailable as exc:
            log.warning("bronze_store_retryable", error=str(exc))
            await self._persist_retry(task, exc)
            raise

        # ── Step 3: Canonicalize ─────────────────────────────────────────────
        try:
            canonical_bytes, row_count = self._canonicalize(task, fetch_result)
        except (ProviderDataError, ValueError, KeyError, TypeError) as exc:
            log.error("canonicalize_fatal", error=str(exc))
            await self._persist_fail(task, ProviderDataError(str(exc)))
            raise ProviderDataError(str(exc)) from exc

        # ── Step 4: Store canonical ──────────────────────────────────────────
        try:
            canonical_ref = await self._store_canonical(task, canonical_bytes)
        except StorageUnavailable as exc:
            log.warning("canonical_store_retryable", error=str(exc))
            await self._persist_retry(task, exc)
            raise

        # ── Step 5: Short transaction ────────────────────────────────────────
        new_sha256 = canonical_ref.sha256

        try:
            async with self._uow:
                # Ensure watermark row exists (upsert on first task execution)
                watermark = await self._uow.watermarks.get_or_create(
                    provider=str(task.provider),
                    dataset_type=str(task.dataset_type),
                    symbol=task.symbol,
                    exchange=task.exchange,
                    timeframe=task.timeframe,
                    variant=task.variant,
                )
                # Re-read with SELECT FOR UPDATE to lock the row against concurrent
                # workers advancing the same watermark simultaneously.
                locked = await self._uow.watermarks.get_for_update(
                    provider=str(task.provider),
                    dataset_type=str(task.dataset_type),
                    symbol=task.symbol,
                    exchange=task.exchange,
                    timeframe=task.timeframe,
                    variant=task.variant,
                )
                if locked is not None:
                    watermark = locked

                # SHA-256 dedup: check BEFORE advancing so has_changed compares
                # new_sha256 against the previously-stored hash, not itself.
                data_changed = watermark.has_changed(new_sha256)

                # Advance watermark when this task is newer than current state.
                # Older/equal task windows can arrive due to retries or overlap; treat
                # them as idempotent stale updates instead of failing the task.
                # Use task.created_at (not utc_now()) when range_end is absent: two
                # concurrent tasks without range_end always produce a deterministic
                # ordering via their stable creation timestamps (M-029).
                new_ts = task.range_end if task.range_end is not None else task.created_at
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
                    event = MarketDatasetFetched(
                        provider=str(task.provider),
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
                    )
                    await self._uow.outbox.add(events=[event])
                else:
                    log.debug("skip_outbox_unchanged_sha256", sha256_prefix=new_sha256[:8] if new_sha256 else "")

                await self._uow.watermarks.save(watermark)
                # Capture lease owner before succeed() clears it (BP-NEW-task-save-lease).
                original_lease_owner = task.lease_owner
                task.succeed(canonical_ref)
                await self._uow.tasks.save(task, original_lease_owner=original_lease_owner)
                await self._uow.commit()

        except WatermarkViolation as exc:
            log.warning(
                "watermark_violation_retry",
                error=str(exc),
                task_id=task.id,
            )
            # Concurrent worker race: the loser gets WatermarkViolation.
            # Re-queue via retry() so the task is attempted again on the next cycle
            # rather than being permanently failed (it is not broken, just lost a race).
            await self._persist_retry(task, exc)
            raise
        except InvalidStateTransition as exc:
            log.error("invalid_state_transition", error=str(exc))
            # F-DS-005: persist task failure before re-raising so the task does not
            # remain stuck in RUNNING state. _persist_fail opens a new UoW context
            # (the outer one was rolled back when this exception escaped the async with).
            await self._persist_fail(task, exc)
            raise

        log.info("task_succeeded", row_count=row_count)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch(self, adapter: ProviderAdapter, task: IngestionTask) -> ProviderFetchResult:
        if task.dataset_type == DatasetType.OHLCV:
            # EXT-01: intraday vs EOD dispatch based on timeframe.
            # Intraday timeframes include 15m, 30m, 4h in addition to 1m, 5m, 1h —
            # extended to match PLAN-0040 A-2 / PRD-0032 intraday set.
            if task.timeframe in {"1m", "5m", "15m", "30m", "1h", "4h"}:
                ext_adapter = cast("Any", adapter)
                return cast(
                    "ProviderFetchResult",
                    await ext_adapter.fetch_intraday(
                        symbol=task.symbol,
                        interval=task.timeframe,
                        exchange=task.exchange,
                    ),
                )
            return await adapter.fetch_ohlcv(
                symbol=task.symbol,
                timeframe=task.timeframe or "1d",
                start=task.range_start,
                end=task.range_end,
                exchange=task.exchange,
            )
        if task.dataset_type == DatasetType.QUOTES:
            return await adapter.fetch_quotes(
                symbol=task.symbol,
                exchange=task.exchange,
            )
        if task.dataset_type == DatasetType.EARNINGS_CALENDAR:
            from datetime import timedelta

            today = utc_now().date()
            ext_adapter = cast("Any", adapter)
            return cast(
                "ProviderFetchResult",
                await ext_adapter.fetch_earnings_calendar(
                    from_date=(today - timedelta(days=14)).isoformat(),
                    to_date=(today + timedelta(days=14)).isoformat(),
                ),
            )
        if task.dataset_type == DatasetType.ECONOMIC_EVENTS:
            from datetime import timedelta

            today = utc_now().date()
            # symbol encodes country: "EVENTS.USA" → "USA"
            country = task.symbol.split(".")[-1] if "." in task.symbol else "USA"
            ext_adapter = cast("Any", adapter)
            return cast(
                "ProviderFetchResult",
                await ext_adapter.fetch_economic_events(
                    from_date=(today - timedelta(days=14)).isoformat(),
                    to_date=(today + timedelta(days=14)).isoformat(),
                    country=country,
                ),
            )
        if task.dataset_type == DatasetType.MACRO_INDICATOR:
            ext_adapter = cast("Any", adapter)
            return cast("ProviderFetchResult", await ext_adapter.fetch_macro_indicator(symbol=task.symbol))
        if task.dataset_type == DatasetType.NEWS_SENTIMENT:
            from datetime import timedelta

            today = utc_now().date()
            ext_adapter = cast("Any", adapter)
            return cast(
                "ProviderFetchResult",
                await ext_adapter.fetch_news_sentiment(
                    symbol=task.symbol,
                    from_date=(today - timedelta(days=7)).isoformat(),
                    to_date=today.isoformat(),
                ),
            )
        if task.dataset_type == DatasetType.INSIDER_TRANSACTIONS:
            ext_adapter = cast("Any", adapter)
            return cast("ProviderFetchResult", await ext_adapter.fetch_insider_transactions(ticker=task.symbol))
        if task.dataset_type == DatasetType.YIELD_CURVE:
            ext_adapter = cast("Any", adapter)
            return cast("ProviderFetchResult", await ext_adapter.fetch_yield_curve(series_symbol=task.symbol))
        if task.dataset_type == DatasetType.MARKET_CAP:
            ext_adapter = cast("Any", adapter)
            return cast("ProviderFetchResult", await ext_adapter.fetch_historical_market_cap(ticker=task.symbol))
        # FUNDAMENTALS (default)
        return await adapter.fetch_fundamentals(
            symbol=task.symbol,
            variant=task.variant or "annual",
            exchange=task.exchange,
        )

    async def _store_bronze(
        self,
        task: IngestionTask,
        fetch_result: ProviderFetchResult,
    ) -> ObjectRef:
        key = f"market-ingestion/raw/{task.provider}/{task.dataset_type}/{task.symbol}/{task.id}"
        # D-008: On retry, the object may already exist — skip the upload and
        # reconstruct the ObjectRef using a locally-computed SHA-256.
        if await self._store.exists(self._bronze_bucket, key):
            sha256 = hashlib.sha256(fetch_result.raw_data).hexdigest()
            return ObjectRef(
                bucket=self._bronze_bucket,
                key=key,
                sha256=sha256,
                byte_length=len(fetch_result.raw_data),
                mime_type=fetch_result.content_type,
            )
        return await self._store.put(
            self._bronze_bucket,
            key,
            fetch_result.raw_data,
            fetch_result.content_type,
        )

    def _canonicalize(
        self,
        task: IngestionTask,
        fetch_result: ProviderFetchResult,
    ) -> tuple[bytes, int]:
        import json

        raw_data = json.loads(fetch_result.raw_data.decode())

        if task.dataset_type == DatasetType.OHLCV:
            # EODHD (and most providers) return a JSON array at the top level.
            bars = raw_data if isinstance(raw_data, list) else raw_data.get("data", [raw_data])
            enriched = [
                {**bar, "symbol": task.symbol, "exchange": task.exchange or "", "source": str(task.provider)}
                for bar in bars
            ]
            canon = self._serializer.serialize_ohlcv(enriched)
            lines = [line for line in canon.split(b"\n") if line.strip()]
            return canon, len(lines)

        if task.dataset_type == DatasetType.QUOTES:
            # EODHD real-time endpoint returns a single JSON object (not a list).
            # Normalise to a list and remap provider-specific field names to canonical
            # names so CanonicalQuote.from_dict() can parse the result.
            raw_quotes = raw_data if isinstance(raw_data, list) else [raw_data]
            enriched_quotes = [
                _remap_quote(q, task.symbol, task.exchange or "", str(task.provider)) for q in raw_quotes
            ]
            canon = self._serializer.serialize_quotes(enriched_quotes)
            lines = [line for line in canon.split(b"\n") if line.strip()]
            return canon, len(lines)

        # Passthrough dataset types — no domain-specific canonical model exists.
        # Wrap raw JSON in a self-describing envelope so downstream consumers
        # (e.g. S7 knowledge-graph) can identify and parse the payload without
        # needing provider-specific parsing logic.  Returns row_count=1 because
        # each task produces exactly one envelope record regardless of payload size.
        if task.dataset_type in {
            DatasetType.ECONOMIC_EVENTS,
            DatasetType.MACRO_INDICATOR,
            DatasetType.INSIDER_TRANSACTIONS,
            DatasetType.EARNINGS_CALENDAR,
            DatasetType.NEWS_SENTIMENT,
            DatasetType.YIELD_CURVE,
            DatasetType.MARKET_CAP,
        }:
            canon = self._serializer.serialize_passthrough(
                raw_data=raw_data,
                dataset_type=str(task.dataset_type),
                symbol=task.symbol,
                source=str(task.provider),
            )
            return canon, 1

        # FUNDAMENTALS
        # Map raw provider response to the section-keyed canonical format expected
        # by the FundamentalsConsumer in market-data.
        raw_dict = raw_data if isinstance(raw_data, dict) else {}
        sections = _map_fundamentals_sections(
            raw_dict,
            symbol=task.symbol,
            source=str(task.provider),
        )
        # Enrich with task-level metadata (exchange, period/variant, report_date)
        from datetime import datetime

        sections["exchange"] = task.exchange or ""
        sections["period"] = task.variant or "annual"
        if "report_date" not in sections or not sections["report_date"]:
            sections["report_date"] = raw_dict.get("report_date") or datetime.now(tz=UTC).date().isoformat()
        canon = self._serializer.serialize_fundamentals(sections, variant=task.variant)
        return canon, 1

    async def _store_canonical(
        self,
        task: IngestionTask,
        canonical_bytes: bytes,
    ) -> ObjectRef:
        key = f"market-ingestion/canonical/{task.provider}/{task.dataset_type}/{task.symbol}/{task.id}.jsonl"
        # D-008: On retry, the object may already exist — skip the upload and
        # reconstruct the ObjectRef using a locally-computed SHA-256.
        if await self._store.exists(self._canonical_bucket, key):
            sha256 = hashlib.sha256(canonical_bytes).hexdigest()
            return ObjectRef(
                bucket=self._canonical_bucket,
                key=key,
                sha256=sha256,
                byte_length=len(canonical_bytes),
                mime_type="application/x-ndjson",
            )
        return await self._store.put(
            self._canonical_bucket,
            key,
            canonical_bytes,
            "application/x-ndjson",
        )

    async def _persist_retry(self, task: IngestionTask, exc: Exception) -> None:
        # Capture the lease owner BEFORE retry() clears it so the repository
        # WHERE clause can still match the DB row (BP-NEW-task-save-lease).
        original_lease_owner = task.lease_owner
        task.retry(exc)
        async with self._uow:
            await self._uow.tasks.save(task, original_lease_owner=original_lease_owner)
            await self._uow.commit()

    async def _persist_fail(self, task: IngestionTask, exc: Exception) -> None:
        # Capture the lease owner BEFORE fail() clears it so the repository
        # WHERE clause can still match the DB row (BP-NEW-task-save-lease).
        original_lease_owner = task.lease_owner
        task.fail(exc)
        async with self._uow:
            await self._uow.tasks.save(task, original_lease_owner=original_lease_owner)
            await self._uow.commit()


# ---------------------------------------------------------------------------
# Module-level helpers (no I/O — pure data transformation)
# ---------------------------------------------------------------------------


def _remap_quote(raw: dict, symbol: str, exchange: str, source: str) -> dict:
    """Normalise a provider quote dict to CanonicalQuote field names.

    EODHD real-time response uses ``close`` for the last price and carries a
    Unix epoch ``timestamp``.  CanonicalQuote requires ``last`` and an ISO-8601
    ``timestamp`` string, plus ``bid`` / ``ask`` which EODHD does not supply
    (we fall back to ``close``).
    """
    from datetime import datetime

    # Resolve last price: prefer explicit "last", fall back to "close"
    last = raw.get("last") or raw.get("close", 0.0)

    if not last:
        # FIX-Q1: Log — do not raise; data may be legitimately halted
        logger.warning(
            "quote_zero_or_missing_price",
            symbol=symbol,
            exchange=exchange,
            raw_keys=list(raw.keys()),
        )
        last = 0.0

    # Convert Unix epoch timestamp to ISO-8601 if necessary
    ts_raw = raw.get("timestamp")
    if isinstance(ts_raw, int | float):
        timestamp = datetime.fromtimestamp(ts_raw, tz=UTC).isoformat()
    else:
        timestamp = str(ts_raw) if ts_raw is not None else datetime.now(tz=UTC).isoformat()

    return {
        "symbol": symbol,
        "exchange": exchange,
        "source": source,
        "bid": raw.get("bid") or last,
        "ask": raw.get("ask") or last,
        "last": last,
        "volume": raw.get("volume", 0),
        "timestamp": timestamp,
        "bid_size": raw.get("bid_size"),
        "ask_size": raw.get("ask_size"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "open": raw.get("open"),
        "prev_close": raw.get("prev_close") or raw.get("previousClose"),
    }


def _map_fundamentals_sections(raw: dict, symbol: str, source: str) -> dict:
    """Map a full EODHD fundamentals response to the section-keyed canonical format.

    Keys in the returned dict correspond to the ``_SECTION_HANDLERS`` mapping in
    the market-data ``FundamentalsConsumer``.  Missing sections are omitted so
    the consumer skips them cleanly.
    """
    financials = raw.get("Financials") or {}
    earnings = raw.get("Earnings") or {}
    splits_divs = raw.get("SplitsDividends") or {}

    sections: dict = {
        "symbol": symbol,
        "source": source,
    }

    def _add(key: str, value: object) -> None:
        if value:
            sections[key] = value

    _add("income_statement", financials.get("Income_Statement"))
    _add("balance_sheet", financials.get("Balance_Sheet"))
    _add("cash_flow", financials.get("Cash_Flow"))
    _add("highlights", raw.get("Highlights"))  # FIX-F10: separated from valuation_ratios
    _add("valuation_ratios", raw.get("Valuation"))  # FIX-F10: Valuation only
    _add("technicals_snapshot", raw.get("Technicals"))
    _add("share_statistics", raw.get("SharesStats"))
    _add("splits_dividends", raw.get("SplitsDividends"))
    _add("analyst_consensus", raw.get("AnalystRatings"))
    _add("earnings_history", earnings.get("History"))
    _add("earnings_trend", earnings.get("Trend"))
    _add("earnings_annual_trend", earnings.get("Annual"))
    _add("dividend_history", splits_divs.get("NumberDividendsByYear"))  # FIX-F5: was "Dividends"
    _add("outstanding_shares", raw.get("outstandingShares"))
    _add("company_profile", raw.get("General"))  # FIX-F4
    _add("institutional_holders", (raw.get("Holders") or {}).get("Institutions"))  # FIX-F6
    _add("fund_holders", (raw.get("Holders") or {}).get("Funds"))  # FIX-F6
    _add("insider_transactions_snapshot", raw.get("InsiderTransactions"))  # FIX-F7

    return sections


# ---------------------------------------------------------------------------
# Provider routing — selects the cheapest registered provider per dataset
# ---------------------------------------------------------------------------

_YAHOO_TIMEFRAMES: frozenset[str] = frozenset({"1d", "1w", "1mo", "1M"})
_FINNHUB_TYPES: frozenset[DatasetType] = frozenset(
    {
        DatasetType.NEWS_SENTIMENT,
        DatasetType.EARNINGS_CALENDAR,
        DatasetType.INSIDER_TRANSACTIONS,
    }
)
_ZERO_BAR_DATASET_TYPES: frozenset[DatasetType] = frozenset(
    {
        DatasetType.OHLCV,
        DatasetType.NEWS_SENTIMENT,
        DatasetType.EARNINGS_CALENDAR,
        DatasetType.INSIDER_TRANSACTIONS,
    }
)


def _preferred_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    registry: ProviderRegistry,
) -> Provider:
    """Return the cheapest registered provider for this dataset/timeframe.

    Priority order:
      OHLCV + (1d | 1w | 1mo | 1M) → Yahoo Finance if registered (0 credits)
      NEWS_SENTIMENT | EARNINGS_CALENDAR | INSIDER_TRANSACTIONS → Finnhub if registered (free)
      All other combinations → EODHD (default, always registered)
    """
    if dataset_type == DatasetType.OHLCV and timeframe in _YAHOO_TIMEFRAMES:
        try:
            registry.get(Provider.YAHOO_FINANCE)
            return Provider.YAHOO_FINANCE
        except ProviderUnavailable:
            pass
    if dataset_type in _FINNHUB_TYPES:
        try:
            registry.get(Provider.FINNHUB)
            return Provider.FINNHUB
        except ProviderUnavailable:
            pass
    return Provider.EODHD


def _fallback_provider(
    dataset_type: DatasetType,
    timeframe: str | None,
    current_provider: Provider,
    registry: ProviderRegistry,
    routing_cache: ProviderRoutingCache | None = None,
) -> Provider | None:
    """Return the next provider in the priority chain after zero-bar failover.

    When a ``routing_cache`` is provided, walks the cache's ordered provider
    list to find the next registered provider after ``current_provider``.
    This handles Alpaca → Polygon → EODHD chains for intraday OHLCV.

    Falls back to static chain when cache is None:
      OHLCV daily/weekly/monthly: Yahoo Finance → EODHD → None
      NEWS_SENTIMENT / EARNINGS_CALENDAR / INSIDER_TRANSACTIONS: Finnhub → EODHD → None
      OHLCV intraday / all others: EODHD → None

    Returns None when no fallback is registered or dataset has no alternative.
    """
    if routing_cache is not None:
        # Dynamic routing chain: find the next provider after current_provider.
        providers = routing_cache.get_providers_for(str(dataset_type), timeframe)
        current_val = current_provider.value
        # Walk the list looking for the position after current_provider.
        found_current = False
        for prov_val in providers:
            if found_current:
                # Try to resolve this provider and verify it's registered.
                try:
                    prov = Provider(prov_val)
                    registry.get(prov)  # raises ProviderUnavailable if not registered
                    return prov
                except (ValueError, ProviderUnavailable):
                    continue  # skip unknown/unregistered providers
            if prov_val == current_val:
                found_current = True
        # Always allow EODHD as final fallback if it's registered and not current.
        if current_provider != Provider.EODHD:
            try:
                registry.get(Provider.EODHD)
                return Provider.EODHD
            except ProviderUnavailable:
                pass
        return None

    # Static routing fallback (backward-compatible with PLAN-0038 A-4).
    if (
        dataset_type == DatasetType.OHLCV
        and timeframe in _YAHOO_TIMEFRAMES
        and current_provider == Provider.YAHOO_FINANCE
    ):
        return Provider.EODHD
    if dataset_type in _FINNHUB_TYPES and current_provider == Provider.FINNHUB:
        return Provider.EODHD
    return None


def _task_credit_cost(task: IngestionTask) -> int:
    """Return the EODHD credit cost for *task*.

    Uses the canonical EODHD_CREDIT_COST table from the domain freshness module.
    Intraday timeframes (1m/5m/1h) hit the /intraday endpoint which costs 5 credits.
    """
    if task.dataset_type == DatasetType.OHLCV and task.timeframe in INTRADAY_TIMEFRAMES:
        return EODHD_INTRADAY_COST
    return EODHD_CREDIT_COST.get(str(task.dataset_type), 1)
