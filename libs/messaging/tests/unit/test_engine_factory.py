"""Unit tests for messaging.pg.engine_factory.build_async_engine.

BP-732: these tests pin the exact connect_args shape the factory must produce
so a future edit cannot silently drop one of the three independently-learned
hardening lessons (PgBouncer prepared-statement disabling, client-side
command_timeout, server-side statement_timeout) without failing a test.
"""

from __future__ import annotations

import pytest

from messaging.pg.engine_factory import (
    DEFAULT_COMMAND_TIMEOUT_S,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    build_async_engine,
)

pytestmark = pytest.mark.unit

# A syntactically valid asyncpg DSN. create_async_engine() never opens a
# connection at construction time, so this never touches real network I/O.
_DSN = "postgresql+asyncpg://user:pass@localhost:5432/testdb"


class TestBuildAsyncEngineConnectArgs:
    """Verify the exact connect_args dict passed to create_async_engine."""

    def test_pooled_true_disables_prepared_statement_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_create_async_engine(dsn: str, **kwargs: object) -> str:
            captured["dsn"] = dsn
            captured.update(kwargs)
            return "fake-engine"  # type: ignore[return-value]

        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            fake_create_async_engine,
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-a")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert connect_args["statement_cache_size"] == 0
        assert connect_args["prepared_statement_cache_size"] == 0

    def test_pooled_false_omits_prepared_statement_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_create_async_engine(dsn: str, **kwargs: object) -> str:
            captured.update(kwargs)
            return "fake-engine"  # type: ignore[return-value]

        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            fake_create_async_engine,
        )

        build_async_engine(_DSN, pooled=False, application_name="svc-b")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert "statement_cache_size" not in connect_args
        assert "prepared_statement_cache_size" not in connect_args

    def test_application_name_in_server_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="rag-chat")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        server_settings = connect_args["server_settings"]
        assert isinstance(server_settings, dict)
        assert server_settings["application_name"] == "rag-chat"

    def test_default_command_timeout_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-c")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert connect_args["command_timeout"] == pytest.approx(DEFAULT_COMMAND_TIMEOUT_S)

    def test_default_statement_timeout_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-d")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        server_settings = connect_args["server_settings"]
        assert isinstance(server_settings, dict)
        assert server_settings["statement_timeout"] == str(DEFAULT_STATEMENT_TIMEOUT_MS)

    def test_custom_timeouts_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(
            _DSN,
            pooled=False,
            application_name="svc-e",
            command_timeout_s=30.0,
            statement_timeout_ms=1_000,
        )

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert connect_args["command_timeout"] == pytest.approx(30.0)
        server_settings = connect_args["server_settings"]
        assert isinstance(server_settings, dict)
        assert server_settings["statement_timeout"] == "1000"

    def test_command_timeout_zero_disables_client_side_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A value <= 0 is an explicit operator opt-out — omit the kwarg entirely."""
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-f", command_timeout_s=0)

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert "command_timeout" not in connect_args

    def test_statement_timeout_zero_disables_server_side_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-g", statement_timeout_ms=0)

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        server_settings = connect_args["server_settings"]
        assert isinstance(server_settings, dict)
        assert "statement_timeout" not in server_settings

    def test_connect_timeout_s_forwarded_as_asyncpg_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """asyncpg's own connect-level ``timeout`` (DNS + TCP handshake) is a
        DIFFERENT knob from command_timeout (already-open-connection command
        wait) — alert's PLAN-0088 P0-4 DNS-hiccup hardening depends on this
        staying a distinct, independently-settable value.
        """
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-k", connect_timeout_s=10.0)

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert connect_args["timeout"] == pytest.approx(10.0)
        # command_timeout (the OTHER timeout) still applies its own default —
        # confirms the two knobs are independent, not aliases of each other.
        assert connect_args["command_timeout"] == pytest.approx(DEFAULT_COMMAND_TIMEOUT_S)

    def test_connect_timeout_s_omitted_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-l")

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        assert "timeout" not in connect_args

    def test_extra_connect_args_merged_and_can_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(
            _DSN,
            pooled=True,
            application_name="svc-m",
            command_timeout_s=100.0,
            extra_connect_args={"command_timeout": 42.0, "ssl": "require"},
        )

        connect_args = captured["connect_args"]
        assert isinstance(connect_args, dict)
        # extra_connect_args is applied last, so it wins on key collision.
        assert connect_args["command_timeout"] == pytest.approx(42.0)
        assert connect_args["ssl"] == "require"


class TestBuildAsyncEnginePoolKwargs:
    """Verify pool sizing / recycling / pre-ping kwargs reach create_async_engine."""

    def test_default_pool_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-h")

        assert captured["pool_size"] == 10
        assert captured["max_overflow"] == 20
        assert captured["pool_recycle"] == 300
        assert captured["pool_pre_ping"] is True
        assert captured["echo"] is False
        assert captured["future"] is True
        # pool_timeout is only forwarded when explicitly requested — omitting
        # it lets SQLAlchemy's own default (30s) apply, matching every
        # pre-existing per-service session.py that never set it.
        assert "pool_timeout" not in captured

    def test_custom_pool_kwargs_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured.update(kw) or "fake-engine",
        )

        build_async_engine(
            _DSN,
            pooled=True,
            application_name="svc-i",
            pool_size=20,
            max_overflow=30,
            pool_recycle=120,
            pool_pre_ping=False,
            pool_timeout=10.0,
            echo=True,
        )

        assert captured["pool_size"] == 20
        assert captured["max_overflow"] == 30
        assert captured["pool_recycle"] == 120
        assert captured["pool_pre_ping"] is False
        assert captured["pool_timeout"] == 10.0
        assert captured["echo"] is True

    def test_dsn_forwarded_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_dsn: list[str] = []
        monkeypatch.setattr(
            "messaging.pg.engine_factory.create_async_engine",
            lambda dsn, **kw: captured_dsn.append(dsn) or "fake-engine",
        )

        build_async_engine(_DSN, pooled=True, application_name="svc-j")

        assert captured_dsn == [_DSN]


class TestBuildAsyncEngineRealEngine:
    """Sanity check against the real create_async_engine (no connection opened)."""

    def test_returns_async_engine_instance(self) -> None:
        from sqlalchemy.ext.asyncio import AsyncEngine

        engine = build_async_engine(_DSN, pooled=True, application_name="svc-real")
        assert isinstance(engine, AsyncEngine)

    def test_pooled_and_unpooled_both_construct_without_error(self) -> None:
        """Kwarg-name typos would raise TypeError here even though the mocked
        tests above accept **kwargs unconditionally and couldn't catch that
        class of bug — this exercises the REAL create_async_engine signature.
        """
        pooled_engine = build_async_engine(_DSN, pooled=True, application_name="svc-real-pooled")
        unpooled_engine = build_async_engine(_DSN, pooled=False, application_name="svc-real-unpooled")
        assert pooled_engine is not None
        assert unpooled_engine is not None
