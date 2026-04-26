"""Unit tests for alert service Settings (F-007)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def test_skip_verification_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True MUST raise in production."""
    # Remove any ALERT_* env vars that might conflict
    for key in list(os.environ):
        if key.startswith("ALERT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    from alert.config import Settings

    with pytest.raises(ValidationError, match="MUST NOT be enabled in production"):
        Settings(
            internal_jwt_skip_verification=True,
            s8_internal_jwt="test",
            s1_internal_token="test",
            _env_file=None,
        )


def test_skip_verification_allowed_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True is allowed in non-production."""
    for key in list(os.environ):
        if key.startswith("ALERT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    from alert.config import Settings

    settings = Settings(
        internal_jwt_skip_verification=True,
        s8_internal_jwt="test",
        s1_internal_token="test",
        _env_file=None,
    )
    assert settings.internal_jwt_skip_verification is True
