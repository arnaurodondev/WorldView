"""ExecuteTaskUseCase — 5-step ingestion pipeline.

Pipeline order (critical — do NOT reorder):
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
from market_ingestion.domain.enums import DatasetType
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
from market_ingestion.domain.value_objects import ObjectRef
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import (
        CanonicalSerializer,
        ObjectStoreAdapter,
        ProviderAdapter,
        ProviderFetchResult,
    )
    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.domain.entities.ingestion_task import IngestionTask
    from market_ingestion.infrastructure.adapters.providers import ProviderRegistry

logger = get_logger(__name__)


class ExecuteTaskUseCase:
    """Execute a single claimed ingestion task through the 5-step pipeline."""

    def __init__(
        self,
        uow: UnitOfWork,
        provider_registry: ProviderRegistry,
        object_store: ObjectStoreAdapter,
        serializer: CanonicalSerializer,
        bronze_bucket: str = "market-bronze",
        canonical_bucket: str = "market-canonical",
    ) -> None:
        self._uow = uow
        self._registry = provider_registry
        self._store = object_store
        self._serializer = serializer
        self._bronze_bucket = bronze_bucket
        self._canonical_bucket = canonical_bucket

    async def execute(self, task: IngestionTask) -> None:
        """Run the pipeline for *task*.

        Raises:
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
        )

        adapter = self._registry.get(task.provider)

        # ── Step 1: Fetch ────────────────────────────────────────────────────
        try:
            fetch_result = await self._fetch(adapter, task)
        except (ProviderRateLimited, ProviderUnavailable, TaskLeaseLost) as exc:
            log.warning("fetch_retryable_error", error=str(exc))
            await self._persist_retry(task, exc)
            raise
        except (ProviderAuthError, ProviderDataError) as exc:
            log.error("fetch_fatal_error", error=str(exc))
            await self._persist_fail(task, exc)
            raise

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
                task.succeed(canonical_ref)
                await self._uow.tasks.save(task)
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
            # EXT-01: intraday vs EOD dispatch based on timeframe
            if task.timeframe in {"1m", "5m", "1h"}:
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
        task.retry(exc)
        async with self._uow:
            await self._uow.tasks.save(task)
            await self._uow.commit()

    async def _persist_fail(self, task: IngestionTask, exc: Exception) -> None:
        task.fail(exc)
        async with self._uow:
            await self._uow.tasks.save(task)
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
