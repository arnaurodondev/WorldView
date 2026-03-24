"""Unit tests for content-ingestion storage wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from content_ingestion.app import _normalize_endpoint

from storage.settings import StorageSettings

pytestmark = pytest.mark.unit


def test_normalize_endpoint_adds_http_scheme_when_missing() -> None:
    assert _normalize_endpoint("localhost:7480") == "http://localhost:7480"


def test_normalize_endpoint_keeps_existing_scheme() -> None:
    assert _normalize_endpoint("http://localhost:7480") == "http://localhost:7480"
    assert _normalize_endpoint("https://minio.internal:9000") == "https://minio.internal:9000"


def test_storage_settings_mapping_from_service_config_like_values() -> None:
    service_settings = MagicMock()
    service_settings.minio_endpoint = "localhost:7480"
    service_settings.minio_access_key = "minioadmin"
    service_settings.minio_secret_key = "minioadmin"  # noqa: S105
    service_settings.minio_secure = False
    service_settings.minio_bucket = "worldview-bronze"

    storage_settings = StorageSettings(
        endpoint=_normalize_endpoint(service_settings.minio_endpoint),
        access_key=service_settings.minio_access_key,
        secret_key=service_settings.minio_secret_key,
        use_ssl=service_settings.minio_secure,
        default_bucket=service_settings.minio_bucket,
    )

    assert storage_settings.endpoint == "http://localhost:7480"
    assert storage_settings.default_bucket == "worldview-bronze"
