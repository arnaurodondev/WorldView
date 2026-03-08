"""Tests for ValkeyClient configuration and contract (T-034).

Unit tests only — no live Valkey instance required.
Integration tests (requiring a running Valkey container) are tagged
``integration`` and skipped in the unit-only CI pipeline.
"""

from __future__ import annotations

from messaging.valkey.client import ValkeyConfig, create_valkey_client, create_valkey_client_from_url


class TestValkeyConfig:
    def test_defaults(self) -> None:
        cfg = ValkeyConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 6379
        assert cfg.db == 0
        assert cfg.max_connections == 50
        assert cfg.decode_responses is True
        assert cfg.ssl is False

    def test_url_property_plain(self) -> None:
        cfg = ValkeyConfig(host="valkey-host", port=6380, db=1)
        url = cfg.url
        assert url.startswith("redis://")
        assert "valkey-host" in url
        assert "6380" in url
        assert url.endswith("/1")

    def test_url_property_with_password(self) -> None:
        cfg = ValkeyConfig(password="secret")
        url = cfg.url
        assert ":secret@" in url

    def test_url_property_with_username_password(self) -> None:
        cfg = ValkeyConfig(username="user", password="pass")
        url = cfg.url
        assert "user:pass@" in url

    def test_url_property_ssl(self) -> None:
        cfg = ValkeyConfig(ssl=True, port=6380)
        url = cfg.url
        assert url.startswith("rediss://")

    def test_from_url_plain(self) -> None:
        cfg = ValkeyConfig.from_url("redis://myhost:6381/2")
        assert cfg.host == "myhost"
        assert cfg.port == 6381
        assert cfg.db == 2
        assert cfg.ssl is False

    def test_from_url_with_credentials(self) -> None:
        cfg = ValkeyConfig.from_url("redis://admin:s3cret@myhost:6379/0")
        assert cfg.username == "admin"
        assert cfg.password == "s3cret"  # noqa: S105

    def test_from_url_ssl_scheme(self) -> None:
        cfg = ValkeyConfig.from_url("rediss://host:6380/0")
        assert cfg.ssl is True
        assert cfg.port == 6380

    def test_from_url_override_kwargs(self) -> None:
        cfg = ValkeyConfig.from_url("redis://host:6379/0", max_connections=10)
        assert cfg.max_connections == 10

    def test_from_url_default_port(self) -> None:
        cfg = ValkeyConfig.from_url("redis://host/0")
        assert cfg.port == 6379


class TestValkeyClientConstruction:
    """ValkeyClient construction without making real connections."""

    def test_construct_with_config(self) -> None:
        # Uses a fake URL to avoid real connections at construction time.
        cfg = ValkeyConfig(host="localhost", port=6379)
        client = create_valkey_client(cfg)
        assert client is not None

    def test_construct_from_url(self) -> None:
        client = create_valkey_client_from_url("redis://localhost:6379/0")
        assert client is not None

    def test_client_has_expected_methods(self) -> None:
        expected_methods = [
            "get",
            "set",
            "delete",
            "exists",
            "expire",
            "ttl",
            "get_json",
            "set_json",
            "mget",
            "mset",
            "delete_many",
            "hget",
            "hset",
            "hgetall",
            "hdel",
            "lpush",
            "rpush",
            "lpop",
            "rpop",
            "lrange",
            "llen",
            "ping",
            "close",
        ]
        client = create_valkey_client_from_url("redis://localhost:6379/0")
        for method in expected_methods:
            assert hasattr(client, method), f"Missing method: {method}"


class TestRootImport:
    def test_import_from_root(self) -> None:
        from messaging import (  # noqa: F401
            ValkeyClient,
            ValkeyConfig,
            create_valkey_client,
            create_valkey_client_from_url,
        )
