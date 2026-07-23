"""Unit tests for nlp_db + intelligence_db session factory 4-tuple return (BP-097 fix)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.unit


def _make_nlp_settings(
    *,
    read_url: str = "",
    statement_timeout_ms: int = 60_000,
    command_timeout_s: float = 600.0,
) -> object:
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
        command_timeout_s=command_timeout_s,
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


class TestCommandTimeoutBackstop:
    """Client-side asyncpg command_timeout backstop (2.4 h dead-connection hang, 2026-07-21).

    ``statement_timeout`` is enforced by the Postgres SERVER and does nothing once
    the server is dead; ``command_timeout`` is enforced by the asyncpg CLIENT, so a
    query on a half-open (dead-but-not-RST) connection RAISES instead of hanging.
    It must be a TOP-LEVEL asyncpg connect kwarg (not nested under server_settings)
    for asyncpg.connect to honour it.
    """

    def test_connect_args_includes_command_timeout_when_positive(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        args = build_connect_args(60_000, command_timeout_s=90.0)
        # Top-level float — this is exactly how asyncpg.connect() expects it.
        assert args["command_timeout"] == 90.0
        assert isinstance(args["command_timeout"], float)
        # Must NOT be smuggled into server_settings (asyncpg would reject a
        # non-string server_settings value and never enforce it as a deadline).
        assert "command_timeout" not in args["server_settings"]  # type: ignore[operator]

    def test_connect_args_omits_command_timeout_when_zero(self) -> None:
        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        args = build_connect_args(60_000, command_timeout_s=0)
        assert "command_timeout" not in args

    def test_connect_args_defaults_command_timeout(self) -> None:
        """A caller that omits command_timeout_s still gets the dead-connection backstop."""
        from nlp_pipeline.infrastructure.nlp_db.session import _DEFAULT_COMMAND_TIMEOUT_S, build_connect_args

        args = build_connect_args(60_000)
        assert args["command_timeout"] == _DEFAULT_COMMAND_TIMEOUT_S

    def test_command_timeout_above_statement_and_embedding_ceilings(self) -> None:
        """The default client deadline must never preempt legitimate slow-but-live work.

        server statement_timeout (60 s) and the startup embedding-expiry batch
        SET LOCAL ceiling (300 s) run on the SAME engine; the client deadline must
        sit ABOVE both, and BELOW Kafka max.poll.interval.ms (30 min) so a wedged
        op raises and the article redelivers before the consumer is evicted.
        """
        from nlp_pipeline.infrastructure.nlp_db.session import _DEFAULT_COMMAND_TIMEOUT_S

        assert _DEFAULT_COMMAND_TIMEOUT_S > 60  # above server statement_timeout
        assert _DEFAULT_COMMAND_TIMEOUT_S > 300  # above embedding-expiry batch ceiling
        assert _DEFAULT_COMMAND_TIMEOUT_S < 30 * 60  # below Kafka max.poll.interval.ms

    def test_nlp_factory_propagates_command_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nlp_pipeline.infrastructure.nlp_db import session as session_mod

        captured: list[dict[str, object]] = []
        real_factory = session_mod.create_async_engine

        def _spy(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("connect_args", {}))  # type: ignore[arg-type]
            return real_factory(url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(session_mod, "create_async_engine", _spy)
        session_mod._build_nlp_factories(_make_nlp_settings(command_timeout_s=77.0))  # type: ignore[arg-type]

        assert captured, "create_async_engine was never called"
        assert captured[0]["command_timeout"] == 77.0

    def test_intelligence_factory_propagates_command_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALEMBIC_ENABLED", "false")
        from nlp_pipeline.infrastructure.intelligence_db import session as session_mod

        captured: list[dict[str, object]] = []
        real_factory = session_mod.create_async_engine

        def _spy(url: str, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.append(kwargs.get("connect_args", {}))  # type: ignore[arg-type]
            return real_factory(url, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(session_mod, "create_async_engine", _spy)
        session_mod._build_intelligence_factories(_make_nlp_settings(command_timeout_s=88.0))  # type: ignore[arg-type]

        assert captured, "create_async_engine was never called"
        assert captured[0]["command_timeout"] == 88.0

    def test_command_timeout_env_fallback_safe_on_garbage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed env value must NOT disable the dead-connection backstop."""
        monkeypatch.setenv("NLP_PIPELINE_COMMAND_TIMEOUT_S", "garbage")
        from nlp_pipeline.infrastructure.nlp_db.session import (
            _DEFAULT_COMMAND_TIMEOUT_S,
            command_timeout_from_env,
        )

        assert command_timeout_from_env() == _DEFAULT_COMMAND_TIMEOUT_S

    def test_command_timeout_env_reads_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NLP_PIPELINE_COMMAND_TIMEOUT_S", "42.5")
        from nlp_pipeline.infrastructure.nlp_db.session import command_timeout_from_env

        assert command_timeout_from_env() == 42.5


class TestCommandTimeoutBehaviour:
    """Prove the SEMANTICS: a DB op on a stalled connection raises within the
    command_timeout instead of hanging, while a healthy op is unaffected.

    We model asyncpg's client-side command_timeout the way asyncpg implements it
    internally — an ``asyncio.timeout`` around the protocol wait — driving it with
    the exact ``command_timeout`` value ``build_connect_args`` hands to
    ``asyncpg.connect``.  The point is to prove that the value we propagate turns a
    never-returning command into a bounded, catchable failure (not a 2.4 h hang).
    """

    @pytest.mark.asyncio
    async def test_stalled_connection_raises_within_timeout(self) -> None:
        import asyncio
        import time

        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        # Tiny finite deadline for a fast test; identical mechanism to the 600 s prod value.
        connect_args = build_connect_args(60_000, command_timeout_s=0.05)
        command_timeout = connect_args["command_timeout"]

        class _DeadConnection:
            """A half-open connection whose execute() never returns (dead-but-not-RST)."""

            async def execute(self, _sql: str) -> object:
                await asyncio.Event().wait()  # never set → would hang forever
                raise AssertionError("unreachable")  # pragma: no cover

        conn = _DeadConnection()
        started = time.monotonic()
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            # asyncio.timeout(...) is exactly how asyncpg bounds a command; the
            # dead connection's execute() would otherwise await forever.
            async with asyncio.timeout(command_timeout):  # type: ignore[arg-type]
                await conn.execute("SELECT COUNT(*) FROM provisional_entity_queue")
        elapsed = time.monotonic() - started
        # It RAISED (did not hang) and did so promptly, near the deadline.
        assert elapsed < 2.0, f"timeout fired too late ({elapsed:.2f}s) — would still wedge the pipeline"

    @pytest.mark.asyncio
    async def test_healthy_query_unaffected_by_timeout(self) -> None:
        import asyncio

        from nlp_pipeline.infrastructure.nlp_db.session import build_connect_args

        connect_args = build_connect_args(60_000, command_timeout_s=5.0)
        command_timeout = connect_args["command_timeout"]

        class _LiveConnection:
            async def execute(self, _sql: str) -> int:
                await asyncio.sleep(0)  # returns immediately, like a healthy server
                return 7

        conn = _LiveConnection()
        async with asyncio.timeout(command_timeout):  # type: ignore[arg-type]
            result = await conn.execute("SELECT COUNT(*) FROM provisional_entity_queue")
        assert result == 7  # healthy query completes normally, timeout never fires

    def test_command_timeout_error_is_retryable_not_fatal(self) -> None:
        """A fired command_timeout raises asyncio.TimeoutError (== TimeoutError).

        The article consumer's ``_settle_message`` routes ``FatalError`` to the DLQ
        but treats every other ``Exception`` as a TRANSIENT failure (in-place retry
        → DLQ only on exhaustion), preserving at-least-once.  A TimeoutError must
        therefore NOT be a FatalError, and must be a catchable Exception — so the
        wedged article is retried/redelivered, never silently dropped.
        """
        import asyncio

        from messaging.kafka.consumer.errors import FatalError  # type: ignore[import-untyped]

        assert asyncio.TimeoutError is TimeoutError  # py3.11+ alias
        assert issubclass(TimeoutError, Exception)
        assert not issubclass(TimeoutError, FatalError)


class TestPoolDefaultsAreRightSized:
    """Regression guard for the 2026-07-23 shared-Postgres direct-backend OOM.

    nlp-pipeline runs ~11 pods on the shared single-node Postgres (API + 8 singleton
    workers + 2-replica article fleet). SQLAlchemy's QueuePool keeps ``pool_size``
    connections open persistently (the per-pod idle-backend FLOOR) and allows a burst
    up to ``pool_size + max_overflow`` (the CEILING). An accidental bump back toward
    the old 10/20 default would re-open the unbounded burst tail that OOM-killed
    Postgres, so pin the SERVICE-WIDE defaults tiny. The heavy article fleet gets its
    real concurrency via per-worker env override in gitops (not tested here).
    """

    def _settings(self) -> object:
        from nlp_pipeline.config import Settings

        return Settings(
            database_url=SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/nlp_db"),  # type: ignore[call-arg]
            intelligence_database_url=SecretStr(
                "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
            ),
        )

    def test_nlp_db_pool_floor_is_small(self) -> None:
        s = self._settings()
        assert s.db_pool_size <= 3  # type: ignore[attr-defined]
        assert s.db_pool_size + s.db_max_overflow <= 8  # type: ignore[attr-defined]
        assert s.db_pool_size_read <= 3  # type: ignore[attr-defined]
        assert s.db_pool_size_read + s.db_max_overflow_read <= 8  # type: ignore[attr-defined]

    def test_intelligence_db_pool_floor_is_small(self) -> None:
        s = self._settings()
        assert s.intelligence_db_pool_size <= 3  # type: ignore[attr-defined]
        assert s.intelligence_db_pool_size + s.intelligence_db_max_overflow <= 8  # type: ignore[attr-defined]
        assert s.intelligence_db_pool_size_read <= 3  # type: ignore[attr-defined]
        assert s.intelligence_db_pool_size_read + s.intelligence_db_max_overflow_read <= 8  # type: ignore[attr-defined]
