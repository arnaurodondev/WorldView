"""Unit tests for alert_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


class TestBuildFactories:
    """_build_factories() must return a 4-tuple including the read engine."""

    def _make_settings(self, *, read_url: str = "") -> object:
        """Build a minimal Settings-like object for factory tests."""
        from types import SimpleNamespace

        return SimpleNamespace(
            database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db"),
            database_url_read=read_url,
            db_pool_size=5,
            db_max_overflow=10,
            db_pool_size_read=10,
            db_max_overflow_read=20,
        )

    def test_build_factories_returns_4_tuple(self) -> None:
        from alert.infrastructure.db.session import _build_factories

        settings = self._make_settings()
        result = _build_factories(settings)  # type: ignore[arg-type]
        assert len(result) == 4, f"Expected 4-tuple, got {len(result)}-tuple"

    def test_fallback_engines_are_same_object(self) -> None:
        """When database_url_read is empty, read_engine must be the same object as write_engine."""
        from alert.infrastructure.db.session import _build_factories

        settings = self._make_settings(read_url="")
        write_engine, read_engine, _write_factory, _read_factory = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine, "Expected read_engine is write_engine when no read replica configured"

    def test_separate_read_replica_creates_distinct_engine(self) -> None:
        """When database_url_read points to a different host, a distinct read engine is created."""
        from alert.infrastructure.db.session import _build_factories

        settings = self._make_settings(read_url="postgresql+asyncpg://postgres:postgres@replica:5432/alert_db")
        write_engine, read_engine, _write_factory, _read_factory = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is not write_engine, "Expected distinct engines for different read-replica URL"

    def test_same_url_fallback_uses_same_engine(self) -> None:
        """Explicit same URL as database_url should still use write_engine (no leak)."""
        from alert.infrastructure.db.session import _build_factories

        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/alert_db"
        settings = self._make_settings(read_url=db_url)
        write_engine, read_engine, _write_factory, _read_factory = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine
