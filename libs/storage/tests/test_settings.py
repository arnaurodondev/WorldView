"""Tests for storage.settings (StorageSettings)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from storage.settings import StorageSettings

if TYPE_CHECKING:
    import pytest

# Shared credentials for tests — access_key and secret_key are required fields
# (no default, per security hardening C-001) so all test instances must supply them.
_CREDS = {"access_key": "test-key", "secret_key": "test-secret"}


class TestStorageSettingsDefaults:
    def test_default_endpoint(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.endpoint == "http://localhost:7480"

    def test_credentials_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """access_key and secret_key have no defaults — startup fails if unset."""
        import pydantic

        monkeypatch.delenv("STORAGE_ACCESS_KEY", raising=False)
        monkeypatch.delenv("STORAGE_SECRET_KEY", raising=False)
        try:
            StorageSettings(_env_file=None)
            raise AssertionError("Expected ValidationError when credentials are absent")
        except pydantic.ValidationError:
            pass  # expected

    def test_access_key_set(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.access_key == "test-key"

    def test_secret_key_set(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.secret_key == "test-secret"  # noqa: S105

    def test_default_region(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.region == "us-east-1"

    def test_default_use_ssl(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.use_ssl is False

    def test_default_bucket(self) -> None:
        s = StorageSettings(**_CREDS)
        assert s.default_bucket == "worldview"


class TestStorageSettingsComputedFields:
    def test_endpoint_url_returns_endpoint_when_set(self) -> None:
        s = StorageSettings(endpoint="http://minio:9000", **_CREDS)
        assert s.endpoint_url == "http://minio:9000"

    def test_endpoint_url_returns_none_when_empty(self) -> None:
        s = StorageSettings(endpoint="", **_CREDS)
        assert s.endpoint_url is None

    def test_endpoint_url_returns_none_when_whitespace(self) -> None:
        s = StorageSettings(endpoint="   ", **_CREDS)
        assert s.endpoint_url is None

    def test_is_aws_false_when_endpoint_set(self) -> None:
        s = StorageSettings(endpoint="http://localhost:7480", **_CREDS)
        assert s.is_aws is False

    def test_is_aws_true_when_endpoint_empty(self) -> None:
        s = StorageSettings(endpoint="", **_CREDS)
        assert s.is_aws is True

    def test_is_aws_true_when_endpoint_whitespace(self) -> None:
        s = StorageSettings(endpoint="  ", **_CREDS)
        assert s.is_aws is True


class TestStorageSettingsFromEnv:
    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STORAGE_ENDPOINT", "http://custom:9000")
        monkeypatch.setenv("STORAGE_DEFAULT_BUCKET", "my-bucket")
        monkeypatch.setenv("STORAGE_ACCESS_KEY", "envkey")
        monkeypatch.setenv("STORAGE_SECRET_KEY", "envsecret")
        s = StorageSettings()
        assert s.endpoint == "http://custom:9000"
        assert s.default_bucket == "my-bucket"

    def test_boolean_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STORAGE_USE_SSL", "true")
        monkeypatch.setenv("STORAGE_ACCESS_KEY", "envkey")
        monkeypatch.setenv("STORAGE_SECRET_KEY", "envsecret")
        s = StorageSettings()
        assert s.use_ssl is True
