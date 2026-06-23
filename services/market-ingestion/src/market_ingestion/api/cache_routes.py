"""Internal cache admin API — manual invalidation endpoint.

Endpoints:
  DELETE /internal/v1/cache/{dataset_type}/{symbol}
      Force-delete every cached payload for the given (dataset_type, symbol)
      pair. Useful when an out-of-cycle event (8-K filing, restatement) makes
      cached fundamentals stale before the natural 24h TTL expires.

Auth: protected by InternalJWTMiddleware via the ``/internal/`` prefix — the
middleware already rejects requests without a valid X-Internal-JWT header.
No additional role check is layered on top because (a) every internal JWT in
this platform is service-issued (no end-user tokens reach backends), and
(b) the existing internal routes (routing reload, providers reload) follow the
same pattern. If a future requirement is added for ``role=admin`` it should be
applied uniformly across every ``/internal/`` route, not bolted onto this one.

PLAN-0108 Wave E.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from market_ingestion.application.use_cases.invalidate_cache import InvalidateCacheUseCase
from market_ingestion.domain.enums import CacheDatasetType as DatasetType
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from market_ingestion.infrastructure.cache.market_data_cache import MarketDataCache

logger = get_logger(__name__)

cache_router = APIRouter(prefix="/internal/v1/cache", tags=["cache"])


def get_invalidate_cache_use_case(request: Request) -> InvalidateCacheUseCase:
    """FastAPI dependency that builds the use case from app.state.

    The MarketDataCache is expected to be wired onto ``app.state.market_data_cache``
    at lifespan startup (same pattern as ``app.state.routing_cache``). When
    absent, a 503 is raised so the operator gets a clear "cache backend not
    available" signal instead of an opaque AttributeError.
    """
    cache: MarketDataCache | None = getattr(request.app.state, "market_data_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="market_data_cache_not_configured",
        )
    return InvalidateCacheUseCase(cache=cache)


@cache_router.delete("/{dataset_type}/{symbol}")
async def invalidate_cache(
    dataset_type: str,
    symbol: str,
    use_case: InvalidateCacheUseCase = Depends(get_invalidate_cache_use_case),
) -> dict[str, object]:
    """Delete every cached payload for ``(dataset_type, symbol)``.

    Returns a JSON body with the canonical dataset_type, the symbol, and the
    count of Valkey keys actually removed. ``keys_deleted == 0`` is a legal
    response (cache was already empty for this coordinate).

    Raises:
        400: ``dataset_type`` is not a known :class:`DatasetType` member.
    """
    try:
        ds = DatasetType(dataset_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown dataset_type: {dataset_type!r}",
        ) from exc

    result = await use_case.execute(ds, symbol)
    logger.info(
        "market_data_cache_invalidate",
        dataset_type=result["dataset_type"],
        symbol=result["symbol"],
        keys_deleted=result["keys_deleted"],
    )
    return result
