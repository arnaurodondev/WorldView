"""Unit tests for content-store session factory helpers (BP-097)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/content_store_db"
_READ_URL = "postgresql+asyncpg://user:pass@replica:5432/content_store_db"


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
        from content_store.infrastructure.db.session import _same_db_endpoint

        assert _same_db_endpoint(_BASE_URL, _BASE_URL) is True

    def test_trailing_slash_ignored(self) -> None:
        from content_store.infrastructure.db.session import _same_db_endpoint

        url_with = "postgresql+asyncpg://user:pass@localhost:5432/content_store_db/"
        url_without = "postgresql+asyncpg://user:pass@localhost:5432/content_store_db"
        assert _same_db_endpoint(url_with, url_without) is True

    def test_different_host_returns_false(self) -> None:
        from content_store.infrastructure.db.session import _same_db_endpoint

        assert _same_db_endpoint(_BASE_URL, _READ_URL) is False

    def test_different_database_returns_false(self) -> None:
        from content_store.infrastructure.db.session import _same_db_endpoint

        other = "postgresql+asyncpg://user:pass@localhost:5432/other_db"
        assert _same_db_endpoint(_BASE_URL, other) is False

    def test_credentials_do_not_matter(self) -> None:
        """Different credentials but same host/port/db → True."""
        from content_store.infrastructure.db.session import _same_db_endpoint

        url_a = "postgresql+asyncpg://user_a:pass_a@localhost:5432/content_store_db"
        url_b = "postgresql+asyncpg://user_b:pass_b@localhost:5432/content_store_db"
        assert _same_db_endpoint(url_a, url_b) is True

    def test_different_port_returns_false(self) -> None:
        from content_store.infrastructure.db.session import _same_db_endpoint

        url_alt = "postgresql+asyncpg://user:pass@localhost:5433/content_store_db"
        assert _same_db_endpoint(_BASE_URL, url_alt) is False


# ---------------------------------------------------------------------------
# _build_factories
# ---------------------------------------------------------------------------


class TestBuildFactories:
    def test_returns_4_tuple(self) -> None:
        from content_store.infrastructure.db.session import _build_factories

        result = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert len(result) == 4

    def test_fallback_engines_are_same_object(self) -> None:
        """No read URL → read_engine IS write_engine (no leak, no extra pool)."""
        from content_store.infrastructure.db.session import _build_factories

        write_engine, read_engine, _wf, _rf = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert read_engine is write_engine

    def test_fallback_factories_are_same_object(self) -> None:
        """No read URL → read_factory IS write_factory."""
        from content_store.infrastructure.db.session import _build_factories

        _we, _re, write_factory, read_factory = _build_factories(_FakeSettings())  # type: ignore[arg-type]
        assert read_factory is write_factory

    def test_distinct_read_url_creates_separate_engine(self) -> None:
        """Distinct read URL → read_engine is a different object from write_engine."""
        from content_store.infrastructure.db.session import _build_factories

        settings = _FakeSettings(database_url_read=_READ_URL)
        write_engine, read_engine, _wf, _rf = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is not write_engine

    def test_distinct_read_url_creates_separate_factory(self) -> None:
        """Distinct read URL → read_factory is a different object from write_factory."""
        from content_store.infrastructure.db.session import _build_factories

        settings = _FakeSettings(database_url_read=_READ_URL)
        _we, _re, write_factory, read_factory = _build_factories(settings)  # type: ignore[arg-type]
        assert read_factory is not write_factory
