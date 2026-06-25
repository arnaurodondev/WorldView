"""Storage configuration via environment variables."""

from __future__ import annotations

from pydantic import computed_field
from pydantic_settings import BaseSettings


class StorageSettings(BaseSettings):
    """S3/MinIO connection settings.

    All fields are read from environment with the ``STORAGE_`` prefix.

    Example ``.env``::

        STORAGE_ENDPOINT=http://localhost:7480
        STORAGE_ACCESS_KEY=minioadmin
        STORAGE_SECRET_KEY=minioadmin
        STORAGE_REGION=us-east-1
        STORAGE_USE_SSL=false
        STORAGE_DEFAULT_BUCKET=worldview
    """

    model_config = {"env_prefix": "STORAGE_"}

    endpoint: str = "http://localhost:7480"
    """S3-compatible endpoint URL.  Leave empty to use AWS S3's default endpoint."""

    access_key: str
    """AWS access key ID / MinIO access key. Required — set STORAGE_ACCESS_KEY env var."""

    secret_key: str
    """AWS secret access key / MinIO secret key. Required — set STORAGE_SECRET_KEY env var."""

    region: str = "us-east-1"
    """AWS region or MinIO region identifier."""

    use_ssl: bool = False
    """Whether to use HTTPS for the endpoint connection."""

    default_bucket: str = "worldview"
    """Default bucket name used by the factory and health check."""

    max_pool_connections: int = 50
    """Max size of the underlying urllib3 connection pool (botocore ``max_pool_connections``).

    The botocore/urllib3 default is 10, which is too small for consumers that
    issue many concurrent object fetches (e.g. the market-data ohlcv-consumer
    under dataset replay). When the pool is exhausted, urllib3 logs
    ``Connection pool is full, discarding connection`` and re-creates the
    connection, wasting time under load. Raise via ``STORAGE_MAX_POOL_CONNECTIONS``
    to match the consumer's concurrency.
    """

    @computed_field  # type: ignore[misc]
    @property
    def endpoint_url(self) -> str | None:
        """Return the endpoint URL for boto3.

        Returns ``None`` when *endpoint* is empty so that boto3 uses AWS S3's
        default endpoint resolution.
        """
        return self.endpoint.strip() or None

    @computed_field  # type: ignore[misc]
    @property
    def is_aws(self) -> bool:
        """Return ``True`` when no custom endpoint is set (i.e. using AWS S3)."""
        return not bool(self.endpoint.strip())
