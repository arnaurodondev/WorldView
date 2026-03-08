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

    access_key: str = "minioadmin"
    """AWS access key ID / MinIO access key."""

    secret_key: str = "minioadmin"  # noqa: S105
    """AWS secret access key / MinIO secret key."""

    region: str = "us-east-1"
    """AWS region or MinIO region identifier."""

    use_ssl: bool = False
    """Whether to use HTTPS for the endpoint connection."""

    default_bucket: str = "worldview"
    """Default bucket name used by the factory and health check."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endpoint_url(self) -> str | None:
        """Return the endpoint URL for boto3.

        Returns ``None`` when *endpoint* is empty so that boto3 uses AWS S3's
        default endpoint resolution.
        """
        return self.endpoint.strip() or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_aws(self) -> bool:
        """Return ``True`` when no custom endpoint is set (i.e. using AWS S3)."""
        return not bool(self.endpoint.strip())
