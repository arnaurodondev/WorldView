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
  before the first message is processed.
* ``refresh()`` re-reads the source of truth and atomically replaces the SET
  contents. Failure is logged and the existing (possibly stale) SET is left
  untouched — never wipe the cache on a transient source error.
* ``is_known_ticker(symbol)`` is the read API used by the rare-token
  analyzer; case-insensitive (the SET is normalised to upper-case on write).

W5 scope
--------
This module ships the cache and the unit tests. Wiring into the rare-token
analyzer + app startup hook is W5-3 work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = get_logger(__name__)  # type: ignore[no-any-return]

_VALKEY_UNAVAILABLE_MSG = "valkey_unavailable"
_DEFAULT_KEY = "nlp:v1:canonical_tickers"


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
    """Valkey-backed SET of canonical ticker symbols.

    All read APIs are best-effort: when Valkey is unreachable they return a
    safe default (``False`` for ``is_known_ticker``) and log a warning, so
    the rare-token analyzer keeps making progress on a degraded signal
    rather than failing the whole pipeline.
    """

    def __init__(
        self,
        client: redis.Redis,  # type: ignore[type-arg]
        source: CanonicalTickerSource,
        key: str = _DEFAULT_KEY,
    ) -> None:
        self._client = client
        self._source = source
        self._key = key

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Cold-start hook — warm the SET from the source of truth.

        Never raises. A failed startup leaves the cache empty and the
        rare-token analyzer falls back to "all uppercase tokens are
        suspicious" — the W5-3 wave is responsible for the fallback path.
        """
        try:
            await self.refresh()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "canonical_tickers_cache.startup_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def refresh(self) -> int:
        """Re-read the source of truth and atomically replace the SET.

        Returns the size of the new SET. A source-side error is logged and
        the existing SET is left untouched; the caller can detect this by
        observing that the returned count is 0 AND a warning was logged
        (the zero-source case is also legal — see the
        ``test_startup_does_not_raise_on_empty_source`` unit test).
        """
        try:
            tickers = await self._source.fetch_all_tickers()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "canonical_tickers_cache.source_failed",
                operation="fetch_all_tickers",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0

        # Normalise to upper-case + dedupe before going to Valkey so the SET
        # comparison in ``is_known_ticker`` is unambiguous.
        normalised = {t.strip().upper() for t in tickers if t and t.strip()}

        try:
            # Atomic-ish swap: pipeline DEL + SADD so the empty window is at
            # most one round-trip wide. ``redis.asyncio`` returns a coroutine.
            pipe = self._client.pipeline()
            pipe.delete(self._key)
            if normalised:
                pipe.sadd(self._key, *normalised)
            await pipe.execute()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                _VALKEY_UNAVAILABLE_MSG,
                operation="refresh",
                error=str(exc),
            )
            return 0

        logger.info(  # type: ignore[no-any-return]
            "canonical_tickers_cache.refreshed",
            count=len(normalised),
        )
        return len(normalised)

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
