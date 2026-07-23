"""Unit tests for portfolio session factory helpers (BP-097)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/portfolio_db"
_READ_URL = "postgresql+asyncpg://user:pass@replica:5432/portfolio_db"


class _FakeSettings:
    """Minimal settings stub for _build_factories / _same_db_endpoint tests."""

    def __init__(
        self,
        *,
        database_url: str = _BASE_URL,
        database_url_read: str = "",
        db_pool_size: int = 5,
        db_max_overflow: int = 10,
        db_pool_size_read: int = 5,
        db_max_overflow_read: int = 10,
    ) -> None:
        self.database_url = SecretStr(database_url)
        self.database_url_read = SecretStr(database_url_read)
        self.db_pool_size = db_pool_size
        self.db_max_overflow = db_max_overflow
        self.db_pool_size_read = db_pool_size_read
        self.db_max_overflow_read = db_max_overflow_read


# ---------------------------------------------------------------------------
# _same_db_endpoint
# ---------------------------------------------------------------------------


class TestSameDbEndpoint:
    def test_identical_urls(self) -> None:
        from portfolio.infrastructure.db.session import _same_db_endpoint

        assert _same_db_endpoint(_BASE_URL, _BASE_URL) is True

    def test_trailing_slash_ignored(self) -> None:
        from portfolio.infrastructure.db.session import _same_db_endpoint

        url_with = "postgresql+asyncpg://user:pass@localhost:5432/portfolio_db/"
        url_without = "postgresql+asyncpg://user:pass@localhost:5432/portfolio_db"
        assert _same_db_endpoint(url_with, url_without) is True

    def test_different_host_returns_false(self) -> None:
        from portfolio.infrastructure.db.session import _same_db_endpoint

        assert _same_db_endpoint(_BASE_URL, _READ_URL) is False

    def test_different_database_returns_false(self) -> None:
        from portfolio.infrastructure.db.session import _same_db_endpoint

        other = "postgresql+asyncpg://user:pass@localhost:5432/other_db"
        assert _same_db_endpoint(_BASE_URL, other) is False

    def test_credentials_do_not_matter(self) -> None:
        """Different credentials but same host/port/db → True."""
        from portfolio.infrastructure.db.session import _same_db_endpoint

        url_a = "postgresql+asyncpg://user_a:pass_a@localhost:5432/portfolio_db"
        url_b = "postgresql+asyncpg://user_b:pass_b@localhost:5432/portfolio_db"
        assert _same_db_endpoint(url_a, url_b) is True

    def test_different_port_returns_false(self) -> None:
        from portfolio.infrastructure.db.session import _same_db_endpoint

        url_alt = "postgresql+asyncpg://user:pass@localhost:5433/portfolio_db"
        assert _same_db_endpoint(_BASE_URL, url_alt) is False


# ---------------------------------------------------------------------------
# _build_factories
# ---------------------------------------------------------------------------


class TestBuildFactories:
    def test_returns_4_tuple(self) -> None:
        from portfolio.infrastructure.db.session import _build_factories

        result = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert len(result) == 4

    def test_fallback_engines_are_same_object(self) -> None:
        """No read URL → read_engine IS write_engine (no leak, no extra pool)."""
        from portfolio.infrastructure.db.session import _build_factories

        write_engine, read_engine, _wf, _rf = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert read_engine is write_engine

    def test_fallback_factories_are_same_object(self) -> None:
        """No read URL → read_factory IS write_factory."""
        from portfolio.infrastructure.db.session import _build_factories

        _we, _re, write_factory, read_factory = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert read_factory is write_factory

    def test_distinct_read_url_creates_separate_engine(self) -> None:
        """Distinct read URL → read_engine is a different object from write_engine."""
        from portfolio.infrastructure.db.session import _build_factories

        settings = _FakeSettings(database_url_read=_READ_URL)
        write_engine, read_engine, _wf, _rf = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is not write_engine

    def test_distinct_read_url_creates_separate_factory(self) -> None:
        """Distinct read URL → read_factory is a different object from write_factory."""
        from portfolio.infrastructure.db.session import _build_factories

        settings = _FakeSettings(database_url_read=_READ_URL)
        _we, _re, write_factory, read_factory = _build_factories(settings)  # type: ignore[arg-type]
        assert read_factory is not write_factory


# ---------------------------------------------------------------------------
# PgBouncer transaction-pooling safety (2026-07-23)
#
# Portfolio routes through pgbouncer.infra.svc:6432 (pool_mode=transaction) in
# prod. Under transaction pooling, asyncpg's server-side prepared statements do
# NOT survive across pooled backends, so the shared factory MUST be called with
# ``pooled=True`` (which disables both statement caches). These tests pin that
# contract at the ``_build_factories`` boundary — the single most important
# invariant of the cutover — by capturing the kwargs handed to the factory.
# ---------------------------------------------------------------------------


def _capture_engine_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Patch the factory imported into session.py and record each call's kwargs."""
    import portfolio.infrastructure.db.session as session_mod
    from sqlalchemy.ext.asyncio import create_async_engine

    calls: list[dict[str, object]] = []

    def _fake_build_async_engine(dsn: str, **kwargs: object) -> object:
        calls.append({"dsn": dsn, **kwargs})
        # Return a real (unconnected) engine so async_sessionmaker binding works.
        return create_async_engine("postgresql+asyncpg://u:p@localhost:5432/portfolio_db")

    monkeypatch.setattr(session_mod, "build_async_engine", _fake_build_async_engine)
    return calls


class TestPoolingSafety:
    def test_write_engine_is_pooled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Write engine MUST be built with pooled=True (statement caches disabled)."""
        from portfolio.infrastructure.db.session import _build_factories

        calls = _capture_engine_kwargs(monkeypatch)
        _build_factories(_FakeSettings())  # type: ignore[arg-type]

        assert calls, "build_async_engine was never called"
        assert calls[0]["pooled"] is True
        assert calls[0]["application_name"] == "portfolio"

    def test_statement_timeout_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """statement_timeout is disabled so long FIFO replay / export queries survive."""
        from portfolio.infrastructure.db.session import _build_factories

        calls = _capture_engine_kwargs(monkeypatch)
        _build_factories(_FakeSettings())  # type: ignore[arg-type]

        assert calls[0]["statement_timeout_ms"] == 0

    def test_read_engine_also_pooled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A distinct read replica engine MUST also be pooled=True."""
        from portfolio.infrastructure.db.session import _build_factories

        calls = _capture_engine_kwargs(monkeypatch)
        _build_factories(_FakeSettings(database_url_read=_READ_URL))  # type: ignore[arg-type]

        assert len(calls) == 2, "expected separate write + read engine builds"
        assert all(c["pooled"] is True for c in calls)
        assert all(c["statement_timeout_ms"] == 0 for c in calls)

    def test_create_session_factory_is_pooled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The thin e2e-test wrapper MUST also build a pooled engine."""
        from portfolio.infrastructure.db.session import create_session_factory

        calls = _capture_engine_kwargs(monkeypatch)
        create_session_factory(_BASE_URL)

        assert calls, "build_async_engine was never called"
        assert calls[0]["pooled"] is True
        assert calls[0]["statement_timeout_ms"] == 0
