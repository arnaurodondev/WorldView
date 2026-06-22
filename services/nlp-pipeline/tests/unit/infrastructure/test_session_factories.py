"""Unit tests for nlp_db + intelligence_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _make_nlp_settings(*, read_url: str = "", statement_timeout_ms: int = 60_000) -> object:
    """Build a minimal Settings-like object for nlp_db factory tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db"),
        database_url_read=SecretStr(read_url),
        db_pool_size=5,
        db_max_overflow=10,
        db_pool_size_read=10,
        db_max_overflow_read=20,
        statement_timeout_ms=statement_timeout_ms,
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


class TestStatementTimeoutBackstop:
    """The universal statement_timeout backstop (FTS / 4.5 h incidents, 2026-06-21).

    Applies to BOTH nlp_db (FTS ts_rank_cd / ts_headline) and intelligence_db.
    """

    def test_connect_args_includes_statement_timeout_when_positive(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        args = build_connect_args(60_000)
        ss = args["server_settings"]
        assert ss["statement_timeout"] == "60000"  # type: ignore[index]
        assert ss["application_name"] == "nlp-pipeline"  # type: ignore[index]

    def test_connect_args_omits_statement_timeout_when_zero(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        args = build_connect_args(0)
        assert "statement_timeout" not in args["server_settings"]  # type: ignore[operator]

    def test_nlp_factory_propagates_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spy on create_async_engine to capture the connect_args nlp_db is built with."""
        from nlp_pipeline.infrastructure.nlp_db import session as session_mod

        captured: list[dict[str, object]] = []
        real_factory = session_mod.create_async_engine

        def _spy(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("connect_args", {}))  # type: ignore[arg-type]
            return real_factory(url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(session_mod, "create_async_engine", _spy)
        session_mod._build_nlp_factories(_make_nlp_settings(statement_timeout_ms=22_222))  # type: ignore[arg-type]

        assert captured, "create_async_engine was never called"
        assert captured[0]["server_settings"]["statement_timeout"] == "22222"  # type: ignore[index]

    def test_intelligence_factory_propagates_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from nlp_pipeline.infrastructure.intelligence_db import session as session_mod

        captured: list[dict[str, object]] = []
        real_factory = session_mod.create_async_engine

        def _spy(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("connect_args", {}))  # type: ignore[arg-type]
            return real_factory(url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(session_mod, "create_async_engine", _spy)
        session_mod._build_intelligence_factories(_make_nlp_settings(statement_timeout_ms=33_333))  # type: ignore[arg-type]

        assert captured, "create_async_engine was never called"
        assert captured[0]["server_settings"]["statement_timeout"] == "33333"  # type: ignore[index]

    def test_env_fallback_safe_on_garbage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed env value must NOT disable the backstop — falls back to default."""
        monkeypatch.setenv("NLP_PIPELINE_STATEMENT_TIMEOUT_MS", "garbage")
        from nlp_pipeline.infrastructure.nlp_db.session import (
            _DEFAULT_STATEMENT_TIMEOUT_MS,
            statement_timeout_from_env,
        )

        assert statement_timeout_from_env() == _DEFAULT_STATEMENT_TIMEOUT_MS
