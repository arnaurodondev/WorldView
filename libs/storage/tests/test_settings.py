"""Tests for storage.settings (StorageSettings)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from storage.settings import StorageSettings

if TYPE_CHECKING:
    import pytest


class TestStorageSettingsDefaults:
    def test_default_endpoint(self) -> None:
        s = StorageSettings()
        assert s.endpoint == "http://localhost:7480"

    def test_default_access_key(self) -> None:
        s = StorageSettings()
        assert s.access_key == "minioadmin"

    def test_default_secret_key(self) -> None:
        s = StorageSettings()
        assert s.secret_key == "minioadmin"  # noqa: S105

    def test_default_region(self) -> None:
        s = StorageSettings()
        assert s.region == "us-east-1"

    def test_default_use_ssl(self) -> None:
        s = StorageSettings()
        assert s.use_ssl is False

    def test_default_bucket(self) -> None:
        s = StorageSettings()
        assert s.default_bucket == "worldview"


class TestStorageSettingsComputedFields:
    def test_endpoint_url_returns_endpoint_when_set(self) -> None:
        s = StorageSettings(endpoint="http://minio:9000")
        assert s.endpoint_url == "http://minio:9000"

    def test_endpoint_url_returns_none_when_empty(self) -> None:
        s = StorageSettings(endpoint="")
        assert s.endpoint_url is None

    def test_endpoint_url_returns_none_when_whitespace(self) -> None:
        s = StorageSettings(endpoint="   ")
        assert s.endpoint_url is None

    def test_is_aws_false_when_endpoint_set(self) -> None:
        s = StorageSettings(endpoint="http://localhost:7480")
        assert s.is_aws is False

    def test_is_aws_true_when_endpoint_empty(self) -> None:
        s = StorageSettings(endpoint="")
        assert s.is_aws is True

    def test_is_aws_true_when_endpoint_whitespace(self) -> None:
        s = StorageSettings(endpoint="  ")
        assert s.is_aws is True


class TestStorageSettingsFromEnv:
    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STORAGE_ENDPOINT", "http://custom:9000")
        monkeypatch.setenv("STORAGE_DEFAULT_BUCKET", "my-bucket")
        s = StorageSettings()
        assert s.endpoint == "http://custom:9000"
        assert s.default_bucket == "my-bucket"

    def test_boolean_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STORAGE_USE_SSL", "true")
        s = StorageSettings()
        assert s.use_ssl is True
