"""Unit tests for rag-chat service Settings (F-007 + F-014)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def test_skip_verification_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True MUST raise in production."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    from rag_chat.config import Settings

    with pytest.raises(ValidationError, match="MUST NOT be enabled in production"):
        Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
            s1_internal_token="test-token",
            internal_jwt_skip_verification=True,
            _env_file=None,
        )


def test_skip_verification_allowed_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-007: internal_jwt_skip_verification=True is allowed in non-production."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        internal_jwt_skip_verification=True,
        _env_file=None,
    )
    assert settings.internal_jwt_skip_verification is True


def test_empty_database_url_read_coerced_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: Empty/whitespace DATABASE_URL_READ is coerced to None."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        database_url_read="   ",  # whitespace-only
        _env_file=None,
    )
    assert settings.database_url_read is None


def test_whitespace_database_url_read_env_coerced_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: RAG_CHAT_DATABASE_URL_READ=' ' is coerced to None."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RAG_CHAT_DATABASE_URL_READ", "  ")

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        _env_file=None,
    )
    assert settings.database_url_read is None


def test_valid_database_url_read_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-014: Non-empty database_url_read is preserved."""
    for key in list(os.environ):
        if key.startswith("RAG_CHAT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    from rag_chat.config import Settings

    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        s1_internal_token="test-token",
        database_url_read="postgresql+asyncpg://reader:reader@localhost:5432/test_rag_db",
        _env_file=None,
    )
    assert settings.database_url_read is not None
    assert "reader" in settings.database_url_read.get_secret_value()
