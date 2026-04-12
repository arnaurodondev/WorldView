"""Async Valkey/Redis client with connection pooling and JSON helpers.

Key taxonomy convention (document in ADR-0004):
    ``<scope>:<version>:<resource>:<id>[:<qualifier>]``

Examples:
    ``md:v1:quote:AAPL``
    ``gw:v1:session:abc123``
    ``nlp:v1:enrichment:article-42:sentiment``
"""

from __future__ import annotations

import dataclasses
import json
from contextlib import asynccontextmanager
from typing import Any

import structlog

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


@dataclasses.dataclass
class ValkeyConfig:
    """Connection configuration for a Valkey/Redis instance.

    Args:
        host: Server hostname.
        port: Server port.
        db: Database index.
        password: Optional authentication password.
        username: Optional ACL username (Valkey 7+ / Redis 6+).
        max_connections: Connection pool size.
        socket_timeout: Socket timeout in seconds.
        socket_connect_timeout: Connection timeout in seconds.
        decode_responses: Decode byte responses to str.
        ssl: Use TLS for the connection.
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    username: str = ""
    max_connections: int = 50
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 2.0
    decode_responses: bool = True
    ssl: bool = False

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> ValkeyConfig:
        """Parse a Redis-style URL into a :class:`ValkeyConfig`.

        Only the host/port/db components are extracted; extra keyword
        arguments override parsed values.

        Args:
            url: URL in the form ``redis[s]://[user:pass@]host:port/db``.
            **kwargs: Field overrides applied after parsing.

        Returns:
            Populated :class:`ValkeyConfig`.
        """
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        ssl = scheme in {"rediss", "valkeys"}
        host = parsed.hostname or "localhost"
        port = parsed.port or (6380 if ssl else 6379)
        db = int(parsed.path.lstrip("/") or 0)
        password = parsed.password or ""
        username = parsed.username or ""
        cfg = cls(host=host, port=port, db=db, password=password, username=username, ssl=ssl)
        for key, val in kwargs.items():
            object.__setattr__(cfg, key, val)
        return cfg

    @property
    def url(self) -> str:
        """Reconstruct Redis-style URL from config fields."""
        scheme = "rediss" if self.ssl else "redis"
        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        elif self.password:
            auth = f":{self.password}@"
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"


class ValkeyClient:
    """Async Valkey/Redis client wrapping ``redis.asyncio``.

    Provides a clean async API over the ``redis.asyncio`` library with
    helpers for JSON, batching, and hash operations.  Every key should
    follow the taxonomy defined in ADR-0004.

    Args:
        config: :class:`ValkeyConfig` instance.  If *None*, reads from
            ``VALKEY_*`` environment variables via a default config.
    """

    def __init__(self, config: ValkeyConfig | None = None, url: str | None = None) -> None:
        from redis.asyncio import ConnectionPool, Redis, SSLConnection  # type: ignore[import-untyped]

        if url is not None:
            self._config = ValkeyConfig.from_url(url)
        else:
            self._config = config or ValkeyConfig()

        connection_kwargs: dict[str, object] = {
            "host": self._config.host,
            "port": self._config.port,
            "db": self._config.db,
            "password": self._config.password or None,
            "username": self._config.username or None,
            "socket_timeout": self._config.socket_timeout,
            "socket_connect_timeout": self._config.socket_connect_timeout,
            "decode_responses": self._config.decode_responses,
        }
        pool_kwargs: dict[str, object] = {
            "max_connections": self._config.max_connections,
        }
        if self._config.ssl:
            pool_kwargs["connection_class"] = SSLConnection
        pool = ConnectionPool(**pool_kwargs, **connection_kwargs)  # type: ignore[arg-type]
        self._redis: Redis = Redis(connection_pool=pool)

    # ── Basic operations ──────────────────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """Return the string value stored at *key*, or ``None`` if missing."""
        return await self._redis.get(key)  # type: ignore[no-any-return]

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set *key* to *value*, optionally with a TTL in seconds."""
        await self._redis.set(key, value, ex=ttl)

    async def delete(self, key: str) -> int:
        """Delete *key* and return the number of keys removed."""
        return await self._redis.delete(key)  # type: ignore[no-any-return]

    async def getdel(self, key: str) -> str | None:
        """Atomically GET and DELETE *key* (Redis 6.2+ / Valkey).

        Returns the value that was stored, or ``None`` if the key did not exist.
        Unlike GET + DEL in a pipeline, this is a single atomic command.
        """
        return await self._redis.getdel(key)  # type: ignore[no-any-return]

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists."""
        return bool(await self._redis.exists(key))

    async def incr(self, key: str, amount: int = 1) -> int:
        """Atomically increment *key* by *amount*.  Returns the new value."""
        return await self._redis.incr(key, amount)  # type: ignore[no-any-return]

    async def expire(self, key: str, seconds: int) -> bool:
        """Set a TTL of *seconds* on *key*.  Returns ``True`` on success."""
        return bool(await self._redis.expire(key, seconds))

    async def ttl(self, key: str) -> int:
        """Return the remaining TTL of *key* in seconds (``-2`` if missing)."""
        return await self._redis.ttl(key)  # type: ignore[no-any-return]

    # ── JSON helpers ─────────────────────────────────────────────────────────

    async def get_json(self, key: str) -> Any | None:
        """Deserialise the JSON string stored at *key*, or ``None`` if missing."""
        raw = await self.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Serialise *value* as JSON and store it at *key* with an optional TTL."""
        await self.set(key, json.dumps(value, default=str), ttl=ttl)

    # ── Batch operations ──────────────────────────────────────────────────────

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Return values for all *keys* in order (``None`` for misses)."""
        return await self._redis.mget(*keys)  # type: ignore[no-any-return]

    async def mset(self, mapping: dict[str, str]) -> None:
        """Set multiple key-value pairs atomically."""
        await self._redis.mset(mapping)

    async def delete_many(self, keys: list[str]) -> int:
        """Delete multiple *keys* and return the count of removed keys."""
        if not keys:
            return 0
        return await self._redis.delete(*keys)  # type: ignore[no-any-return]

    # ── Hash operations ───────────────────────────────────────────────────────

    async def hget(self, key: str, field: str) -> str | None:
        """Return the value of *field* in the hash stored at *key*."""
        return await self._redis.hget(key, field)  # type: ignore[no-any-return, misc]

    async def hset(self, key: str, field: str, value: str) -> int:
        """Set *field* in the hash stored at *key* to *value*."""
        return await self._redis.hset(key, field, value)  # type: ignore[no-any-return, misc]

    async def hgetall(self, key: str) -> dict[str, str]:
        """Return all fields and values in the hash stored at *key*."""
        return await self._redis.hgetall(key)  # type: ignore[no-any-return, misc]

    async def hdel(self, key: str, *fields: str) -> int:
        """Delete *fields* from the hash stored at *key*."""
        return await self._redis.hdel(key, *fields)  # type: ignore[no-any-return, misc, arg-type]

    # ── List operations ───────────────────────────────────────────────────────

    async def lpush(self, key: str, *values: str) -> int:
        """Prepend *values* to the list stored at *key*."""
        return await self._redis.lpush(key, *values)  # type: ignore[no-any-return, misc]

    async def rpush(self, key: str, *values: str) -> int:
        """Append *values* to the list stored at *key*."""
        return await self._redis.rpush(key, *values)  # type: ignore[no-any-return, misc]

    async def lpop(self, key: str) -> str | None:
        """Remove and return the first element of the list at *key*."""
        return await self._redis.lpop(key)  # type: ignore[no-any-return, misc]

    async def rpop(self, key: str) -> str | None:
        """Remove and return the last element of the list at *key*."""
        return await self._redis.rpop(key)  # type: ignore[no-any-return, misc]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        """Return the elements in the list at *key* from *start* to *end*."""
        return await self._redis.lrange(key, start, end)  # type: ignore[no-any-return, misc]

    async def llen(self, key: str) -> int:
        """Return the length of the list stored at *key*."""
        return await self._redis.llen(key)  # type: ignore[no-any-return, misc]

    # ── Pub/sub operations ────────────────────────────────────────────────────

    async def publish(self, channel: str, message: str) -> int:
        """Publish *message* to *channel*.

        Returns the number of subscribers that received the message.

        Args:
            channel: Pub/sub channel name.
            message: Message payload (string; serialise before calling if needed).
        """
        return await self._redis.publish(channel, message)  # type: ignore[no-any-return]

    @asynccontextmanager  # type: ignore[misc]
    async def subscribe(self, *channels: str) -> Any:
        """Async context manager — subscribe to *channels* and yield the ``PubSub`` object.

        Unsubscribes and closes the ``PubSub`` connection on context exit.

        Args:
            *channels: One or more channel names to subscribe to.

        Yields:
            A ``PubSub`` object.  Iterate it with ``async for message in pubsub`` or
            call ``await pubsub.get_message(ignore_subscribe_messages=True, timeout=…)``.

        Example::

            async with client.subscribe("alert:user-123") as pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        handle(message["data"])
        """
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(*channels)
        try:
            yield pubsub
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()

    # ── Sorted-set / pipeline ─────────────────────────────────────────────────

    @asynccontextmanager  # type: ignore[misc]
    async def pipeline(self, *, transaction: bool = False) -> Any:
        """Async context manager that yields the underlying redis pipeline.

        Allows callers to use sorted-set commands (zadd, zremrangebyscore,
        zcard) and other pipelined operations not natively exposed by
        :class:`ValkeyClient`.

        Args:
            transaction: If ``True``, wrap commands in a MULTI/EXEC block.
                         Defaults to ``False`` (non-transactional pipeline).

        Yields:
            The ``redis.asyncio`` pipeline object.  Call ``await pipe.execute()``
            inside the context to flush the buffered commands.

        Example::

            async with client.pipeline(transaction=False) as pipe:
                pipe.zadd("myset", {"member": 1.0})
                pipe.expire("myset", 60)
                results = await pipe.execute()
        """
        async with self._redis.pipeline(transaction=transaction) as pipe:  # type: ignore[misc]
            yield pipe

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Set *key* to *value* with an expiry of *seconds*.

        Alias for ``set(key, value, ttl=seconds)`` provided for
        backward-compatibility with callers using the ``redis.asyncio``
        ``setex`` API.

        Args:
            key:     Valkey key.
            seconds: TTL in seconds.
            value:   String value to store.
        """
        await self._redis.set(key, value, ex=seconds)

    # ── Connection management ─────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Send a PING and return ``True`` if the server responds."""
        try:
            return await self._redis.ping()  # type: ignore[no-any-return]
        except Exception:
            logger.warning("valkey_ping_failed", url=self._config.url)
            return False

    async def close(self) -> None:
        """Close the connection pool."""
        await self._redis.close()  # type: ignore[misc]


def create_valkey_client(config: ValkeyConfig) -> ValkeyClient:
    """Factory — build a :class:`ValkeyClient` from a :class:`ValkeyConfig`.

    Args:
        config: Pre-built configuration.

    Returns:
        Ready-to-use :class:`ValkeyClient`.
    """
    return ValkeyClient(config=config)


def create_valkey_client_from_url(url: str) -> ValkeyClient:
    """Factory — build a :class:`ValkeyClient` from a Redis-style URL.

    Args:
        url: Redis-style connection URL (``redis://host:port/db``).

    Returns:
        Ready-to-use :class:`ValkeyClient`.
    """
    return ValkeyClient(url=url)
