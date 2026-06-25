"""Unit tests for intelligence_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _make_settings(*, read_url: str = "", statement_timeout_ms: int = 60_000) -> object:
    """Build a minimal Settings-like object for factory tests."""
    from types import SimpleNamespace

    return SimpleNamespace(
        database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"),
        database_url_read=SecretStr(read_url),
        db_pool_size=10,
        db_max_overflow=20,
        db_pool_size_read=20,
        db_max_overflow_read=30,
        statement_timeout_ms=statement_timeout_ms,
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


class TestStatementTimeoutBackstop:
    """The universal statement_timeout backstop (4.5 h promoter incident, 2026-06-21)."""

    def test_connect_args_includes_statement_timeout_when_positive(self) -> None:
        """A positive timeout becomes a string-valued server_settings entry (asyncpg requirement)."""
        from knowledge_graph.infrastructure.intelligence_db.session import _build_connect_args

        args = _build_connect_args(60_000)
        ss = args["server_settings"]
        assert ss["statement_timeout"] == "60000"  # type: ignore[index]
        assert ss["application_name"] == "knowledge-graph"  # type: ignore[index]

    def test_connect_args_omits_statement_timeout_when_zero(self) -> None:
        """Zero (or negative) disables the bound — no statement_timeout key at all (unbounded)."""
        from knowledge_graph.infrastructure.intelligence_db.session import _build_connect_args

        args = _build_connect_args(0)
        ss = args["server_settings"]
        assert "statement_timeout" not in ss  # type: ignore[operator]
        assert ss["application_name"] == "knowledge-graph"  # type: ignore[index]

    def test_build_factories_propagates_timeout_to_connect_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_build_factories must thread settings.statement_timeout_ms into the engine's connect_args.

        We spy on ``create_async_engine`` (the SQLAlchemy factory) to capture the
        exact ``connect_args`` it is invoked with — robust across SQLAlchemy
        versions, unlike poking at private pool internals.
        """
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from knowledge_graph.infrastructure.intelligence_db import session as session_mod

        captured: list[dict[str, object]] = []
        real_factory = session_mod.create_async_engine

        def _spy(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("connect_args", {}))  # type: ignore[arg-type]
            return real_factory(url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(session_mod, "create_async_engine", _spy)

        settings = _make_settings(statement_timeout_ms=12_345)
        session_mod._build_factories(settings)  # type: ignore[arg-type]

        assert captured, "create_async_engine was never called"
        server_settings = captured[0]["server_settings"]  # type: ignore[index]
        assert server_settings["statement_timeout"] == "12345"  # type: ignore[index]

    def test_env_fallback_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The raw-URL wrappers fall back to the 60 s default when the env var is unset."""
        monkeypatch.delenv("KNOWLEDGE_GRAPH_STATEMENT_TIMEOUT_MS", raising=False)
        from knowledge_graph.infrastructure.intelligence_db.session import (
            _DEFAULT_STATEMENT_TIMEOUT_MS,
            _statement_timeout_from_env,
        )

        assert _statement_timeout_from_env() == _DEFAULT_STATEMENT_TIMEOUT_MS

    def test_env_fallback_honours_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A valid env override is parsed as an int."""
        monkeypatch.setenv("KNOWLEDGE_GRAPH_STATEMENT_TIMEOUT_MS", "90000")
        from knowledge_graph.infrastructure.intelligence_db.session import _statement_timeout_from_env

        assert _statement_timeout_from_env() == 90_000

    def test_env_fallback_safe_on_garbage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed env value must NOT disable the backstop — falls back to default."""
        monkeypatch.setenv("KNOWLEDGE_GRAPH_STATEMENT_TIMEOUT_MS", "not-a-number")
        from knowledge_graph.infrastructure.intelligence_db.session import (
            _DEFAULT_STATEMENT_TIMEOUT_MS,
            _statement_timeout_from_env,
        )

        assert _statement_timeout_from_env() == _DEFAULT_STATEMENT_TIMEOUT_MS
