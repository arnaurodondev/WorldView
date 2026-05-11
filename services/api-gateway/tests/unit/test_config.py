"""Unit tests for api-gateway Settings configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def _base_env(**overrides: str) -> dict[str, str]:
    """Minimal valid env vars for Settings."""
    base = {
        "API_GATEWAY_OIDC_ISSUER_URL": "https://example.zitadel.cloud",
        "API_GATEWAY_OIDC_CLIENT_ID": "client-id",
        "API_GATEWAY_OIDC_CLIENT_SECRET": "client-secret",
        "API_GATEWAY_OIDC_AUDIENCE": "client-id",
        "API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY": "test-private-key-placeholder",
        "API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY": "test-public-key-placeholder",
    }
    base.update(overrides)
    return base


def test_settings_fails_without_oidc_issuer_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing OIDC_ISSUER_URL must raise ValidationError."""
    from api_gateway.config import Settings

    env = _base_env()
    del env["API_GATEWAY_OIDC_ISSUER_URL"]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("API_GATEWAY_OIDC_ISSUER_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_fails_without_internal_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing INTERNAL_JWT_PRIVATE_KEY must raise ValidationError."""
    from api_gateway.config import Settings

    env = _base_env()
    del env["API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY"]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_jwt_secret_removed() -> None:
    """Settings must not expose a jwt_secret attribute (SEC-001)."""
    from api_gateway.config import Settings

    assert not hasattr(Settings.model_fields, "jwt_secret"), "jwt_secret field must not exist"
    assert not hasattr(Settings, "jwt_secret"), "jwt_secret must be completely removed"


def test_settings_oidc_client_secret_is_secret_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """oidc_client_secret must be SecretStr (never logged)."""
    from api_gateway.config import Settings
    from pydantic import SecretStr

    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)

    s = Settings()
    assert isinstance(s.oidc_client_secret, SecretStr)
    assert "client-secret" not in repr(s.oidc_client_secret)


def test_settings_internal_jwt_private_key_is_secret_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """internal_jwt_private_key must be SecretStr (never logged)."""
    from api_gateway.config import Settings
    from pydantic import SecretStr

    for k, v in _base_env().items():
        monkeypatch.setenv(k, v)

    s = Settings()
    assert isinstance(s.internal_jwt_private_key, SecretStr)
