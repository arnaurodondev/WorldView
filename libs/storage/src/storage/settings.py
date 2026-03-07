"""Storage configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class StorageSettings(BaseSettings):
    """S3/MinIO connection settings.

    All fields are read from environment with the ``STORAGE_`` prefix.
    """

    model_config = {"env_prefix": "STORAGE_"}

    endpoint: str = "http://localhost:7480"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    region: str = "us-east-1"
    use_ssl: bool = False
