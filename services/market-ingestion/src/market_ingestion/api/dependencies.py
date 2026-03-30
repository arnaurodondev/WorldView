"""FastAPI dependency providers for market-ingestion service."""

from __future__ import annotations

import hmac
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends, Header, HTTPException, Request

from market_ingestion.config import Settings
from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import CanonicalSerializer, ObjectStoreAdapter


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton Settings instance (cached across requests)."""
    return Settings()  # type: ignore[call-arg]


async def get_uow(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncGenerator[SqlaUnitOfWork, None]:
    """Provide a fresh SqlaUnitOfWork for each request.

    The session is opened and committed/rolled-back on exit.
    """
    write_factory, read_factory = _build_factories(settings)
    uow = SqlaUnitOfWork(write_factory, read_factory)
    async with uow:
        yield uow


def get_object_store(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ObjectStoreAdapter:
    """Provide an S3-compatible object store adapter.

    Constructs a real MinIO/S3 storage using the service settings.
    In tests, override this dependency with a mock.
    """
    from market_ingestion.infrastructure.adapters.object_store import S3ObjectStoreAdapter
    from storage.s3_adapter import S3ObjectStorage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    storage_settings = StorageSettings(
        endpoint=settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
    )
    storage = S3ObjectStorage(storage_settings)
    return S3ObjectStoreAdapter(storage=storage, default_bucket=settings.storage_bucket)


def get_provider_registry(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderRegistry:
    """Provide the provider registry (EODHD + stubs)."""
    registry = ProviderRegistry()
    from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter

    client = httpx.AsyncClient()
    registry.register(
        EODHDProviderAdapter(api_key=settings.eodhd_api_key, client=client, base_url=settings.eodhd_base_url)
    )
    return registry


def get_canonical_serializer() -> CanonicalSerializer:
    """Provide the canonical NDJSON serializer."""
    from market_ingestion.infrastructure.adapters.canonical import DefaultCanonicalSerializer

    return DefaultCanonicalSerializer()


async def verify_internal_token(
    request: Request,
    x_internal_token: str | None = Header(None),
) -> None:
    """Validate X-Internal-Token against the configured service token (QA-018)."""
    expected = request.app.state.settings.internal_service_token
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing internal token")


InternalAuthDep = Annotated[None, Depends(verify_internal_token)]
