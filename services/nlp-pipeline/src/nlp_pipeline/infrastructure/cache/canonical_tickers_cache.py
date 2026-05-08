"""Canonical tickers Valkey cache (PLAN-0063 W5-2 / FR-T1-2).

Holds the set of valid ticker symbols (``AAPL``, ``MSFT``, ``NVDA``, ...) so
the rare-token analyzer in W5-3 can disambiguate genuine tickers from noise
matches that share the ``\\b[A-Z]{2,5}\\b`` shape (``CEO``, ``USA``, ``IPO``,
``Q4`` ...).

Source of truth
---------------
S2 (market-data) is the canonical owner of ``instruments.symbol``. Per R7
(no cross-service DB) nlp-pipeline cannot read S2's database directly. We
therefore read the same data through ``intelligence_db.canonical_entities``,
which S6/S7 own jointly — every financial-instrument entity in there carries a
``ticker`` column populated from the S2 → S6 sync. This avoids adding a new
REST dependency while staying inside an already-permitted database boundary
(R7's cross-service exception for the shared intelligence_db is documented in
the auth foundation PRD-0025 and PLAN-0033).

Storage
-------
Backing store is a Valkey SET so that multiple replicas of the nlp-pipeline
share the cache and a refresh on any instance is immediately visible to all
others — same pattern as the entity ``watchlist_cache``. Default key:
``nlp:v1:canonical_tickers`` (overridable via
``Settings.valkey_canonical_tickers_key``).

Lifecycle
---------
* ``startup()`` runs ``refresh()`` once at process start so the SET is warm
  before the first message is processed, then launches ``_refresh_loop()``
  as a background asyncio task.
* ``refresh()`` re-reads the source of truth and atomically replaces the SET
  contents via a Lua script (DEL + SADD as a single server-side atomic op,
  C-2 / BP-422).
  Failure is logged and the existing (possibly stale) SET is left untouched
  — never wipe the cache on a transient source error.
* ``_refresh_loop()`` runs forever, sleeping ``_refresh_interval_s`` seconds
  between ticks; transient errors are swallowed (with a 60s back-off sleep)
  so a temporary Valkey blip cannot kill the background task.
* ``close()`` cancels and awaits the background task, then returns.
* ``is_known_ticker(symbol)`` is the read API used by the rare-token
  analyzer; case-insensitive (the SET is normalised to upper-case on write).

Staleness guarantee
-------------------
With the default ``canonical_tickers_refresh_interval_s = 600`` (10 minutes)
the SET will be at most 600 seconds stale after a source-of-truth change.
The interval is operator-tunable via
``NLP_PIPELINE_CANONICAL_TICKERS_REFRESH_INTERVAL_S`` (range 60-3600).

W5 scope
--------
This module ships the cache and the unit tests. Wiring into the rare-token
analyzer + app startup hook is W5-3 work. Background loop wiring is PLAN-0084
Wave C-1 work.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Protocol

from prometheus_client import Counter

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import redis.asyncio as redis

log = get_logger(__name__)  # type: ignore[no-any-return]

# Keep legacy alias so external callers that imported ``logger`` continue to work.
logger = log

_VALKEY_UNAVAILABLE_MSG = "valkey_unavailable"
_DEFAULT_KEY = "nlp:v1:canonical_tickers"

# Lua script for atomic DEL + SADD swap (C-2 / BP-422).
# MULTI/EXEC (pipeline transaction=True) is vulnerable to partial failure on
# network drops between DEL and SADD — a disconnect after DEL but before SADD
# permanently wipes the cache until the next successful refresh.  A Lua script
# runs atomically on the server side with no interleaving from other clients,
# which eliminates that window.  Returns SCARD (int) of the new SET.
_ATOMIC_TICKER_SWAP = """
redis.call('DEL', KEYS[1])
if #ARGV > 0 then
    redis.call('SADD', KEYS[1], unpack(ARGV))
end
return redis.call('SCARD', KEYS[1])
"""

_REFRESH_FAILURE_COUNTER: Counter = Counter(
    "canonical_tickers_refresh_failures_total",
    "Total number of canonical tickers cache refresh failures",
)


class CanonicalTickerSource(Protocol):
    """Pluggable source-of-truth port — implemented by an intelligence_db
    adapter in production and by a fake in unit tests."""

    async def fetch_all_tickers(self) -> list[str]:
        """Return every known ticker symbol as a list of strings.

        Implementations MAY raise; the cache treats any exception as a
        transient error and keeps the previously cached SET untouched.
        """
        ...


class CanonicalTickersCache:
    """Valkey-backed SET of canonical ticker symbols with background refresh.

    All read APIs are best-effort: when Valkey is unreachable they return a
    safe default (``False`` for ``is_known_ticker``) and log a warning, so
    the rare-token analyzer keeps making progress on a degraded signal
    rather than failing the whole pipeline.

    The atomic swap in ``refresh()`` uses a server-side Lua script so
    concurrent ``is_known_ticker`` callers never observe an empty SET
    between the DEL and the SADD (C-2 / BP-422).
    """

    def __init__(
        self,
        client: redis.Redis,  # type: ignore[type-arg]
        source: CanonicalTickerSource,
        key: str = _DEFAULT_KEY,
        refresh_interval_s: int = 600,
    ) -> None:
        self._client = client
        self._source = source
        self._key = key
        # Interval in seconds between background refresh ticks (default 600s = 10 min).
        # Clamp is a safety net; Settings validation enforces ge=60/le=3600.
        self._refresh_interval_s = max(60, refresh_interval_s)
        # Background asyncio.Task created by startup(); cancelled by close().
        self._refresh_task: asyncio.Task[None] | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Cold-start hook — warm the SET from the source of truth, then start
        the background refresh loop.

        Never raises. A failed startup leaves the cache empty and the
        rare-token analyzer falls back to "all uppercase tokens are
        suspicious" — the W5-3 wave is responsible for the fallback path.
        """
        try:
            await self.refresh()
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "canonical_tickers_cache.startup_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        # Launch background loop regardless of whether the initial refresh
        # succeeded — the loop will retry after ``_refresh_interval_s`` seconds.
        self._refresh_task = asyncio.create_task(self._refresh_loop())

        # D-018 fix: add a done-callback so a crash *outside* the inner
        # try/except (e.g. a bug in the loop scaffolding itself) is surfaced
        # to the log rather than silently swallowed — mirrors the BP-268
        # pattern used in services/rag-chat/src/rag_chat/app.py.
        def _on_task_done(task: asyncio.Task[None]) -> None:  # type: ignore[type-arg]
            if task.cancelled():
                # Normal shutdown via close() — not an error.
                return
            exc = task.exception()
            if exc is not None:
                log.critical(  # type: ignore[no-any-return]
                    "canonical_tickers_refresh_task_crashed",
                    exc_info=exc,
                )

        self._refresh_task.add_done_callback(_on_task_done)

    async def close(self) -> None:
        """Cancel and await the background refresh loop.

        Safe to call even if ``startup()`` was never called (no-op).
        """
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

    async def _refresh_loop(self) -> None:
        """Background loop: sleep then call ``refresh()``, forever.

        Design notes
        ------------
        * ``asyncio.CancelledError`` is re-raised immediately so the task can
          be cancelled cleanly by ``close()``.
        * All other exceptions are swallowed after logging a warning; the loop
          then applies exponential back-off (C-3 / BP-423): ``min(2^n * 60, 300)``
          seconds where *n* is the number of consecutive failures.  This reduces
          log spam during sustained Valkey outages while still recovering quickly
          after the first failure (60 s) and capping at 5 minutes.
        * ``_REFRESH_FAILURE_COUNTER`` is incremented on every failure so ops
          dashboards can alert on sustained outages.
        * The sleep comes FIRST so the initial warm-up from ``startup()``
          is not redundantly repeated on the first tick.
        """
        consecutive_failures = 0
        while True:
            try:
                await asyncio.sleep(self._refresh_interval_s)
                count = await self.refresh()
                consecutive_failures = 0
                log.info(  # type: ignore[no-any-return]
                    "canonical_tickers.refresh_loop_tick",
                    count=count,
                )
            except asyncio.CancelledError:
                raise  # propagate so the task terminates cleanly
            except Exception:
                consecutive_failures += 1
                _REFRESH_FAILURE_COUNTER.inc()
                backoff = min(2**consecutive_failures * 60, 300)
                log.warning(  # type: ignore[no-any-return]
                    "canonical_tickers.refresh_loop_error",
                    exc_info=True,
                    consecutive_failures=consecutive_failures,
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)

    def start_loop(self) -> asyncio.Task[None]:
        """Create and return the background refresh task.

        Prefer ``startup()`` in application code — this method exists for
        callers that need a handle to the task for introspection or testing.
        Idempotent: if a task already exists and is not done, returns it.
        """
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._refresh_loop())
        return self._refresh_task

    async def refresh(self) -> int:
        """Re-read the source of truth and atomically replace the SET.

        Uses a server-side Lua script (``_ATOMIC_TICKER_SWAP``) so the DEL
        and SADD execute as a single atomic unit — concurrent
        ``is_known_ticker`` callers cannot observe an empty SET between the
        two operations.  This replaces the previous MULTI/EXEC pipeline
        approach (C-2 / BP-422): a MULTI/EXEC was vulnerable to permanent
        cache wipe if the connection dropped between DEL and SADD.

        Returns the SCARD of the new SET (as reported by the Lua script). A
        source-side error is logged and the existing SET is left untouched;
        the caller can detect this by observing that the returned count is 0
        AND a warning was logged (the zero-source case is also legal — see
        the ``test_startup_does_not_raise_on_empty_source`` unit test).
        """
        try:
            tickers = await self._source.fetch_all_tickers()
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                "canonical_tickers_cache.source_failed",
                operation="fetch_all_tickers",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0

        # Normalise to upper-case + dedupe before going to Valkey so the SET
        # comparison in ``is_known_ticker`` is unambiguous.
        normalised = {t.strip().upper() for t in tickers if t and t.strip()}

        # D-017 fix: if the source returned 0 tickers (not an exception —
        # just a genuinely empty result set), skip the wipe rather than
        # issuing DEL with no SADD.  That would permanently erase the cache
        # and leave every ticker lookup returning False until the next
        # successful refresh — a silent data-loss regression caused by a
        # transient DB query issue (e.g. cold start before entities are
        # synced, or a brief lock contention window).
        if not normalised:
            log.warning(  # type: ignore[no-any-return]
                "canonical_tickers_cache.empty_source_skipping_wipe",
                reason="DB returned 0 tickers — may indicate transient query issue",
            )
            return 0

        try:
            # Atomic swap via Lua script (C-2 / BP-422).  A MULTI/EXEC pipeline
            # is vulnerable to partial failure: if the connection drops after
            # DEL but before SADD the cache is permanently empty until the next
            # successful refresh.  The Lua script runs atomically on the server
            # so concurrent ``is_known_ticker`` callers never observe an empty
            # SET between the DEL and the SADD.
            count = int(
                await self._client.eval(  # type: ignore[misc]
                    _ATOMIC_TICKER_SWAP,
                    1,  # number of KEYS
                    self._key,
                    *normalised,
                )
            )
        except Exception as exc:
            log.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="refresh",
                error=str(exc),
            )
            return 0

        log.info(  # type: ignore[no-any-return]
            "canonical_tickers_cache.refreshed",
            count=count,
        )
        return count

    # ── Read API ─────────────────────────────────────────────────────────────

    async def is_known_ticker(self, symbol: str) -> bool:
        """Return True iff ``symbol`` (case-insensitive) is in the SET.

        Returns False on Valkey unavailability — a missed lookup is a softer
        failure than a raise (the rare-token analyzer's job is to filter
        false positives; "don't know" defaults to "treat as suspicious",
        which the analyzer must already cope with).
        """
        if not symbol or not symbol.strip():
            return False
        try:
            return bool(
                await self._client.sismember(self._key, symbol.strip().upper())  # type: ignore[misc]
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="sismember",
                symbol=symbol,
                error=str(exc),
            )
            return False

    # ── Write API (used by tests / future Kafka consumer) ────────────────────

    async def add(self, symbol: str) -> None:
        """SADD a single ticker — convenience for tests + future event-driven
        updates. Idempotent on the Valkey side."""
        if not symbol or not symbol.strip():
            return
        try:
            await self._client.sadd(self._key, symbol.strip().upper())  # type: ignore[misc]
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="sadd",
                symbol=symbol,
                error=str(exc),
            )


class IntelligenceDBCanonicalTickerSource:
    """Source-of-truth adapter that reads ``canonical_entities`` from
    intelligence_db.

    Selects the ``ticker`` column for every row where ``entity_type =
    'financial_instrument'`` AND ticker IS NOT NULL. This is the same shape S2
    populates via the canonical-entity sync.

    Wiring into the app (creating the session, instantiating the cache,
    invoking ``startup()``) lives in W5-3 — this class is the seam.
    """

    def __init__(
        self,
        intelligence_session_factory: object,  # async_sessionmaker[AsyncSession]
    ) -> None:
        # Stored as ``object`` to avoid pulling sqlalchemy types into a hot
        # import path; the test-time fake source bypasses this adapter
        # entirely.
        self._sf = intelligence_session_factory

    async def fetch_all_tickers(self) -> list[str]:
        from sqlalchemy import text

        # mypy: the factory is typed loosely (object); the runtime contract
        # is "callable returning an async-context-manager session".
        sf: object = self._sf
        async with sf() as session:  # type: ignore[operator]
            result = await session.execute(  # type: ignore[attr-defined]
                text(
                    """
                    SELECT ticker
                    FROM canonical_entities
                    WHERE entity_type = 'financial_instrument'
                      AND ticker IS NOT NULL
                      AND length(trim(ticker)) > 0
                    """
                )
            )
            return [str(row.ticker) for row in result.all()]
