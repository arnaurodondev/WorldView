"""Unit tests for nlp_db + intelligence_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _make_nlp_settings(*, read_url: str = "") -> object:
    """Build a minimal Settings-like object for nlp_db factory tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db"),
        database_url_read=SecretStr(read_url),
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_size_read=10,
        db_max_overflow_read=20,
        intelligence_database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"),
        intelligence_database_url_read=SecretStr(""),
        intelligence_db_pool_size=5,
        intelligence_db_max_overflow=10,
        intelligence_db_pool_size_read=10,
        intelligence_db_max_overflow_read=20,
    )


class TestBuildNlpFactories:
    """_build_nlp_factories() must return a 4-tuple including the read engine."""

    def test_build_nlp_factories_returns_4_tuple(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

        settings = _make_nlp_settings()
        result = _build_nlp_factories(settings)  # type: ignore[arg-type]
        assert len(result) == 4, f"Expected 4-tuple, got {len(result)}-tuple"

    def test_fallback_engines_are_same_object(self) -> None:
        """When database_url_read is empty, read_engine must be the same object as write_engine."""
        from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

        settings = _make_nlp_settings(read_url="")
        write_engine, read_engine, _wf, _rf = _build_nlp_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine

    def test_separate_read_replica_creates_distinct_engine(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

        settings = _make_nlp_settings(read_url="postgresql+asyncpg://postgres:postgres@replica:5432/nlp_db")
        write_engine, read_engine, _wf, _rf = _build_nlp_factories(settings)  # type: ignore[arg-type]
        assert read_engine is not write_engine

    def test_same_url_fallback_uses_same_engine(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories

        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db"
        settings = _make_nlp_settings(read_url=db_url)
        write_engine, read_engine, _wf, _rf = _build_nlp_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine


class TestBuildIntelligenceFactories:
    """_build_intelligence_factories() must return a 4-tuple including the read engine."""

    def test_build_intelligence_factories_returns_4_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from nlp_pipeline.infrastructure.intelligence_db.session import _build_intelligence_factories

        settings = _make_nlp_settings()
        result = _build_intelligence_factories(settings)  # type: ignore[arg-type]
        assert len(result) == 4, f"Expected 4-tuple, got {len(result)}-tuple"

    def test_fallback_engines_are_same_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from nlp_pipeline.infrastructure.intelligence_db.session import _build_intelligence_factories

        settings = _make_nlp_settings()
        write_engine, read_engine, _wf, _rf = _build_intelligence_factories(settings)  # type: ignore[arg-type]
        assert read_engine is write_engine
