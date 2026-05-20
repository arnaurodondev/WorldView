"""ExecuteTaskUseCase -- 5-step ingestion pipeline dispatcher.

Steps: 0=quota, 1=fetch, 2=bronze, 3=canonicalize, 4=canonical, 5=DB-commit.
Implementation split across strategies/ subpackage (routing, fetch, canonicalize, pipeline).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Re-export module-level helpers that tests import directly from this module.
from market_ingestion.application.use_cases.strategies.canonicalize import (  # noqa: F401
    _map_fundamentals_sections,
    _remap_quote,
)
from market_ingestion.application.use_cases.strategies.pipeline import (
    fetch_with_guards,
    pre_fetch_checks,
    run_steps_2_to_5,
    zero_bar_failover,
)
from market_ingestion.application.use_cases.strategies.routing import (  # noqa: F401
    _fallback_provider,
    _preferred_provider,
    _task_credit_cost,
)
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.errors import ProviderUnavailable
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
    """Execute a single claimed ingestion task through the 5-step pipeline."""

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
        self._quota_service = quota_service
        self._service_name = service_name
        self._circuit_breaker = circuit_breaker
        self._zero_bar_tracker = zero_bar_tracker
        self._routing_cache = routing_cache

    def _select_provider(self, task: IngestionTask) -> tuple[Provider, ProviderAdapter]:
        """Resolve preferred provider + adapter. Dynamic cache (PRD-0032) takes priority."""
        if self._routing_cache is not None:
            primary = self._routing_cache.primary_for(str(task.dataset_type), task.timeframe)
            try:
                preferred = Provider(primary)
                return preferred, self._registry.get(preferred)  # type: ignore[return-value]
            except (ValueError, ProviderUnavailable):
                pass  # fall through to static routing
        preferred = _preferred_provider(task.dataset_type, task.timeframe, self._registry)
        return preferred, self._registry.get(preferred)  # type: ignore[return-value]

    async def execute_with_prefetched_result(self, task: IngestionTask, fetch_result: ProviderFetchResult) -> None:
        """Run Steps 2-5 using an already-fetched result (batch path). Skips quota/CB/zero-bar."""
        log: Any = logger.bind(
            task_id=task.id, provider=str(task.provider), symbol=task.symbol, dataset_type=str(task.dataset_type)
        )
        task.fetched_by_provider = fetch_result.provider.value
        await run_steps_2_to_5(
            task,
            fetch_result,
            self._store,
            self._bronze_bucket,
            self._serializer,
            self._canonical_bucket,
            self._uow,
            log,
        )

    async def execute(self, task: IngestionTask) -> None:
        """Run the full 5-step pipeline for *task*. Raises retryable/fatal on error."""
        log: Any = logger.bind(
            task_id=task.id, provider=str(task.provider), symbol=task.symbol, dataset_type=str(task.dataset_type)
        )

        # -- Provider routing --------------------------------------------------
        preferred, adapter = self._select_provider(task)
        if preferred != task.provider:
            log.info(
                "provider_routing_cache_selected",
                requested=str(task.provider),
                selected=preferred.value,
                dataset_type=str(task.dataset_type),
                timeframe=task.timeframe or "",
            )

        # -- Steps 0+0.5: quota + circuit breaker ------------------------------
        await pre_fetch_checks(
            task, preferred, self._quota_service, self._service_name, self._circuit_breaker, self._uow, log
        )

        # -- Step 1: fetch -----------------------------------------------------
        fetch_result = await fetch_with_guards(adapter, task, self._circuit_breaker, self._uow, log)

        # -- Zero-bar failover -------------------------------------------------
        if self._zero_bar_tracker is not None:
            fetch_result = await zero_bar_failover(
                task,
                fetch_result,
                preferred,
                self._zero_bar_tracker,
                self._registry,
                self._routing_cache,
                self._uow,
                log,
            )

        # Record which provider actually fetched the data (T-A-4-03).
        task.fetched_by_provider = fetch_result.provider.value

        # -- Steps 2-5 ---------------------------------------------------------
        await run_steps_2_to_5(
            task,
            fetch_result,
            self._store,
            self._bronze_bucket,
            self._serializer,
            self._canonical_bucket,
            self._uow,
            log,
        )
