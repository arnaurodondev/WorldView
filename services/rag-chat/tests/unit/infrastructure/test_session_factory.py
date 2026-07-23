"""Unit tests for create_rag_session_factory and _same_db_endpoint (F-017).

Covers the dual-session factory logic including BP-179 regression (empty
SecretStr) and F-014 regression (whitespace-only SecretStr).

All tests mock ``build_async_engine`` (the BP-732 shared engine factory in
``messaging.pg.engine_factory``, imported into this module as
``rag_chat.infrastructure.db.session.build_async_engine``) to avoid real DB
connections — these are pure unit tests that validate branching logic only.
Previously these tests mocked ``create_async_engine`` directly; that patch
target no longer exists in this module now that engine construction is
delegated to the shared factory (BP-732 Recurrence 2 fix).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from rag_chat.infrastructure.db.session import _same_db_endpoint, create_rag_session_factory

pytestmark = pytest.mark.unit

_WRITE_URL = "postgresql+asyncpg://user:pass@write-host:5432/ragdb"
_READ_URL = "postgresql+asyncpg://user:pass@read-host:5432/ragdb"


def _make_settings(**overrides: object) -> MagicMock:
    """Build a minimal Settings-like object for session factory tests."""
    defaults: dict[str, object] = {
        "database_url": SecretStr(_WRITE_URL),
        "database_url_read": None,
        "db_pool_size": 5,
        "db_max_overflow": 10,
        "db_pool_size_read": 5,
        "db_max_overflow_read": 10,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ── TC-1: database_url_read=None → read shares write engine ──────────────────


@patch("rag_chat.infrastructure.db.session.build_async_engine")
def test_read_none_shares_write_engine(mock_engine: MagicMock) -> None:
    """When database_url_read is None, the read engine IS the write engine."""
    write_sentinel = MagicMock(name="write-engine")
    mock_engine.return_value = write_sentinel

    settings = _make_settings(database_url_read=None)
    write_engine, read_engine, write_factory, read_factory = create_rag_session_factory(settings)

    assert read_engine is write_engine
    assert read_factory is write_factory
    # Only one engine should have been created.
    mock_engine.assert_called_once()


# ── TC-2: database_url_read=SecretStr("") → read shares write (BP-179) ──────


@patch("rag_chat.infrastructure.db.session.build_async_engine")
def test_empty_secret_str_shares_write_engine(mock_engine: MagicMock) -> None:
    """BP-179 regression: SecretStr('') from ``KEY=`` env var must fall back.

    pydantic-settings parses ``RAG_CHAT_DATABASE_URL_READ=`` (empty value) as
    ``SecretStr('')`` rather than ``None``. The old ``is not None`` guard was
    bypassed, causing an asyncpg connection error on an empty DSN.
    """
    write_sentinel = MagicMock(name="write-engine")
    mock_engine.return_value = write_sentinel

    settings = _make_settings(database_url_read=SecretStr(""))
    write_engine, read_engine, _, _ = create_rag_session_factory(settings)

    assert read_engine is write_engine
    mock_engine.assert_called_once()


# ── TC-3: database_url_read=SecretStr("  ") → whitespace-only (F-014) ───────


@patch("rag_chat.infrastructure.db.session.build_async_engine")
def test_whitespace_only_secret_str_shares_write_engine(mock_engine: MagicMock) -> None:
    """F-014 regression: whitespace-only read URL must fall back to write.

    A read URL containing only spaces is functionally empty and must not be
    passed to ``create_async_engine``.
    """
    write_sentinel = MagicMock(name="write-engine")
    mock_engine.return_value = write_sentinel

    settings = _make_settings(database_url_read=SecretStr("  "))
    write_engine, read_engine, _, _ = create_rag_session_factory(settings)

    assert read_engine is write_engine
    mock_engine.assert_called_once()


# ── TC-4: Same host/port/db → read shares write engine ──────────────────────


@patch("rag_chat.infrastructure.db.session.build_async_engine")
def test_same_endpoint_shares_write_engine(mock_engine: MagicMock) -> None:
    """When read URL resolves to the same host/port/db, share the write engine."""
    write_sentinel = MagicMock(name="write-engine")
    mock_engine.return_value = write_sentinel

    # Same host, port, and database — only credentials differ.
    settings = _make_settings(
        database_url=SecretStr("postgresql+asyncpg://admin:secret@db-host:5432/ragdb"),
        database_url_read=SecretStr("postgresql+asyncpg://reader:readonly@db-host:5432/ragdb"),
    )
    write_engine, read_engine, _, _ = create_rag_session_factory(settings)

    assert read_engine is write_engine
    mock_engine.assert_called_once()


# ── TC-5: Distinct host → separate read engine ──────────────────────────────


@patch("rag_chat.infrastructure.db.session.build_async_engine")
def test_distinct_host_creates_separate_read_engine(mock_engine: MagicMock) -> None:
    """When the read URL points to a different host, a separate engine is created."""
    write_sentinel = MagicMock(name="write-engine")
    read_sentinel = MagicMock(name="read-engine")
    mock_engine.side_effect = [write_sentinel, read_sentinel]

    settings = _make_settings(
        database_url=SecretStr(_WRITE_URL),
        database_url_read=SecretStr(_READ_URL),
    )
    write_engine, read_engine, write_factory, read_factory = create_rag_session_factory(settings)

    assert write_engine is write_sentinel
    assert read_engine is read_sentinel
    assert read_engine is not write_engine
    assert read_factory is not write_factory
    assert mock_engine.call_count == 2


# ── TC-6: _same_db_endpoint trailing slash normalisation ─────────────────────


def test_same_db_endpoint_trailing_slash() -> None:
    """_same_db_endpoint returns True for URLs differing only by trailing slash."""
    assert _same_db_endpoint(
        "postgresql+asyncpg://user:pass@host:5432/ragdb/",
        "postgresql+asyncpg://user:pass@host:5432/ragdb",
    )
