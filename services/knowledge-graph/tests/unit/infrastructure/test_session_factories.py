"""Unit tests for intelligence_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _make_settings(*, read_url: str = "") -> object:
    """Build a minimal Settings-like object for factory tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db",
        database_url_read=read_url,
        db_pool_size=10,
        db_max_overflow=20,
        db_pool_size_read=20,
        db_max_overflow_read=30,
    )


class TestBuildFactories:
    """_build_factories() must return a 4-tuple including the read engine."""

    def test_build_factories_returns_4_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

        settings = _make_settings()
        result = _build_factories(settings)  # type: ignore[arg-type]
        assert len(result) == 4, f"Expected 4-tuple, got {len(result)}-tuple"

    def test_fallback_engines_are_same_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When database_url_read is empty, read_engine must be the same object as write_engine."""
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

        settings = _make_settings(read_url="")
        write_engine, read_engine, _wf, _rf = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine, "Expected read_engine is write_engine when no read replica configured"

    def test_separate_read_replica_creates_distinct_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When database_url_read points to a different host, a distinct read engine is created."""
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

        settings = _make_settings(read_url="postgresql+asyncpg://postgres:postgres@replica:5432/intelligence_db")
        write_engine, read_engine, _wf, _rf = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is not write_engine

    def test_same_url_fallback_uses_same_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit same URL as database_url should still use write_engine (no leak)."""
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from knowledge_graph.infrastructure.intelligence_db.session import _build_factories

        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
        settings = _make_settings(read_url=db_url)
        write_engine, read_engine, _wf, _rf = _build_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine
