"""FundamentalsRefreshWorker — PLAN-0099 W2-T02.

WHY THIS WORKER EXISTS
======================
The 2026-05-27 chat-eval data-integrity investigation surfaced a recurring
"recent quarter missing" pattern: EODHD's most-recent FY2026 quarter for
tickers like AMD had not been ingested at eval time because **no recurring
worker existed** that re-enqueues fundamentals ingestion. The short-term
mitigation was ``scripts/refresh_fundamentals.py`` (PLAN-0097 W1-T04 — a
manual one-shot ops script). This worker is the proper recurring solution
called for in PLAN-0099 §A4 / T-W2-02.

Design rationale (audit decision):
- The audit hypothesised the worker should live in ``content-ingestion``
  because EODHD adapters live there. In reality, the EODHD **fundamentals**
  adapter and the ``TriggerIngestionUseCase`` that the manual script calls
  both live in ``services/market-ingestion``. The ``content-ingestion``
  service handles news / Polymarket / RSS — none of those exercise the
  fundamentals path. Mirroring the manual script's proven contract means
  the worker belongs in **market-ingestion**.
- The script POSTs to ``/api/v1/ingest/trigger``. To avoid an unnecessary
  HTTP hop and JWT plumbing inside our own process, the worker calls
  ``TriggerIngestionUseCase`` **directly** via the existing UoW factory.
- The worker is **ON by default** since 2026-05-28 (PLAN-0100 W4-T03;
  rationale in ``docs/audits/2026-05-28-plan-0100-amd-freshness-diagnostics.md``).
  Operators retain a per-deploy opt-out by setting
  ``FUNDAMENTALS_REFRESH_ENABLED=false`` explicitly. The scheduler process
  imports the worker and the loop spawns whenever the flag is truthy.

Exponential backoff on rate limits
----------------------------------
EODHD returns HTTP 429 under burst load and surfaces it as
``ProviderRateLimited`` in our adapter chain. The original BP-114 pattern
(EODHD demo rate limit silently returning ``[]``) is the precedent for
treating any rate-limit signal as a retryable error. We back off
**exponentially with jitter** (base 5 s, factor 2, max 60 s, ±20% jitter)
and respect the ``retry_after`` hint when the provider supplies one.

Metrics
-------
- ``fundamentals_refresh_attempts_total{symbol, status}`` — status in
  ``ok``, ``rate_limited``, ``error``, ``skipped``. Wired into the existing
  ``prometheus_client`` default REGISTRY exposed by the service's
  ``add_prometheus_middleware`` (no separate exporter needed when the worker
  runs in-process with the scheduler — Prometheus already scrapes
  market-ingestion-scheduler:9108 via the providers module pattern).
"""

from __future__ import annotations

import asyncio
import random
from contextlib import suppress
from typing import TYPE_CHECKING

import httpx
import prometheus_client as prom

from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
from market_ingestion.domain.enums import DatasetType, FundamentalsVariant, Provider
from market_ingestion.domain.errors import ProviderRateLimited
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.internal_jwt import mint_internal_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from market_ingestion.config import Settings

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prometheus metric (PLAN-0099 W2-T02 / T2)
# ---------------------------------------------------------------------------
# WHY a module-level singleton: prometheus_client REGISTRY rejects duplicate
# metric registration on re-import (collectors are process-wide). Pytest
# parallel collection (-n auto) plus multiple worker tests instantiating
# this module would otherwise raise ValueError at import time.
fundamentals_refresh_attempts_total: prom.Counter = prom.Counter(
    "fundamentals_refresh_attempts_total",
    "Total FundamentalsRefreshWorker attempts per symbol per outcome.",
    labelnames=["symbol", "status"],
)


# ---------------------------------------------------------------------------
# Default symbol universe — FALLBACK ONLY (PLAN-0100 T-W5-03).
#
# Used in two scenarios:
#   1. ``MARKET_INGESTION_FUNDAMENTALS_REFRESH_USE_INTERNAL_ENDPOINT=false``
#      — operator opts out of the live top-N endpoint.
#   2. The internal endpoint call fails (HTTP 5xx / network error). The
#      worker logs a WARNING and falls back to this curated list so the
#      refresh loop never stalls completely.
#
# Operators may still override via ``FUNDAMENTALS_REFRESH_SYMBOLS`` (CSV);
# the override takes precedence over BOTH the endpoint and this default.
#
# PLAN-0099 W2-T02 originally shipped this as the only source (cross-service
# DB read violated R9). PLAN-0100 W5 added the REST path; this list now
# exists purely as the safety net.
# ---------------------------------------------------------------------------
_DEFAULT_SYMBOL_UNIVERSE: tuple[str, ...] = (
    # US mega-caps — the practical "top-N by market cap" for our eval universe.
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "GOOG",
    "AMZN",
    "META",
    "TSLA",
    "AVGO",
    "BRK-B",
    "AMD",
    "JPM",
    "LLY",
    "V",
    "MA",
    "UNH",
    "XOM",
    "WMT",
    "PG",
    "JNJ",
    "ORCL",
    "HD",
    "COST",
    "BAC",
    "ABBV",
    "NFLX",
    "CRM",
    "ADBE",
    "MRK",
    "KO",
)


class FundamentalsRefreshWorker:
    """Long-running worker that periodically re-enqueues fundamentals fetches.

    Args:
        settings: Service configuration. The worker reads:
            - ``fundamentals_refresh_enabled`` (bool, default True since 2026-05-28 / PLAN-0100 W4-T03) — kill switch.
            - ``fundamentals_refresh_interval_hours`` (float, default 6.0).
            - ``fundamentals_refresh_top_n`` (int, default 500) — caps the list.
            - ``fundamentals_refresh_symbols`` (CSV string, optional override).
            - ``fundamentals_refresh_provider`` (str, default ``"eodhd"``).
            - ``fundamentals_refresh_variant`` (str, default ``"quarterly"``).
        sleep_fn: Override for ``asyncio.sleep`` — present so unit tests can
            avoid wall-clock waits in backoff paths.
    """

    # Backoff parameters — keep here (not in settings) so they are part of the
    # worker contract rather than per-deploy noise. The values target EODHD's
    # demo + paid rate-limit profiles (typical Retry-After range 1-30 s).
    _BACKOFF_BASE_SECONDS: float = 5.0
    _BACKOFF_FACTOR: float = 2.0
    _BACKOFF_MAX_SECONDS: float = 60.0
    _BACKOFF_MAX_ATTEMPTS: int = 4
    _BACKOFF_JITTER_FRAC: float = 0.2

    def __init__(
        self,
        settings: Settings,
        *,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._stop_event = asyncio.Event()
        # Built lazily in run() — keeps construction side-effect-free so
        # disabled-flag tests don't need a working DB factory.
        self._write_factory: async_sessionmaker[AsyncSession] | None = None
        self._read_factory: async_sessionmaker[AsyncSession] | None = None
        # Test seam — defaults to ``asyncio.sleep`` so production paths run
        # real backoff timing while unit tests can pass a fake.
        self._sleep: Callable[[float], Awaitable[None]] = sleep_fn or asyncio.sleep

    @property
    def enabled(self) -> bool:
        """True if this worker should run on startup."""
        return bool(getattr(self._settings, "fundamentals_refresh_enabled", False))

    def stop(self) -> None:
        """Signal the worker loop to exit after the current iteration."""
        self._stop_event.set()

    # ------------------------------------------------------------------ loop

    async def run(self) -> None:
        """Run the refresh loop until ``stop()`` is fired.

        No-op when the kill switch is off. Returns immediately in that case
        so the scheduler process can keep going. This is the contract the
        ``scheduler.py`` startup path relies on (mirrors the
        ``_spawn_startup_backfill`` pattern).
        """
        if not self.enabled:
            logger.info(
                "fundamentals_refresh_worker_disabled",
                hint="default is now ON; set FUNDAMENTALS_REFRESH_ENABLED=false only to explicitly opt out",
            )
            return

        interval_hours = float(getattr(self._settings, "fundamentals_refresh_interval_hours", 6.0))
        interval_seconds = max(60.0, interval_hours * 3600.0)
        logger.info(
            "fundamentals_refresh_worker_starting",
            interval_hours=interval_hours,
            top_n=self._top_n(),
        )

        # Build infra now — disabled-flag callers above this line never reach here.
        self._write_factory, self._read_factory = _build_factories(self._settings)

        while not self._stop_event.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # — loop must survive any per-tick failure
                logger.exception("fundamentals_refresh_tick_error")

            # Sleep until the next tick OR until stop(). The shield+wait_for
            # idiom mirrors SchedulerProcess.run() so SIGTERM is honoured
            # promptly even mid-sleep.
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=interval_seconds,
                )

        logger.info("fundamentals_refresh_worker_stopped")

    # ---------------------------------------------------------------- tick

    async def _tick(self) -> None:
        """Issue one refresh round for the configured symbol universe.

        Symbol resolution order (PLAN-0100 T-W5-02):
          1. CSV override (``FUNDAMENTALS_REFRESH_SYMBOLS``) — operator
             pin, wins if set.
          2. ``GET /internal/v1/instruments/top-by-market-cap`` on
             market-data (when ``FUNDAMENTALS_REFRESH_USE_INTERNAL_ENDPOINT``
             is true, the default).
          3. The curated mega-cap CSV constant (``_DEFAULT_SYMBOL_UNIVERSE``)
             as the last-resort fallback so the worker never stops.
        """
        symbols = await self._resolve_symbol_universe()
        provider_str = getattr(self._settings, "fundamentals_refresh_provider", "eodhd")
        variant_str = getattr(self._settings, "fundamentals_refresh_variant", "quarterly")

        try:
            provider = Provider(provider_str)
        except ValueError:
            logger.error(
                "fundamentals_refresh_invalid_provider",
                provider=provider_str,
            )
            return

        try:
            # Validate early — TriggerIngestionUseCase accepts a free-form
            # ``str | None`` for variant, but we want a hard fail-fast on
            # config typos rather than silently falling back at fetch time.
            FundamentalsVariant(variant_str)
        except ValueError:
            logger.error(
                "fundamentals_refresh_invalid_variant",
                variant=variant_str,
            )
            return

        logger.info(
            "fundamentals_refresh_tick_start",
            provider=provider.value,
            variant=variant_str,
            symbol_count=len(symbols),
        )

        for symbol in symbols:
            if self._stop_event.is_set():
                break
            await self._refresh_one(provider, variant_str, symbol)

    async def _refresh_one(
        self,
        provider: Provider,
        variant: str,
        symbol: str,
    ) -> None:
        """Fire one trigger for ``symbol`` with exponential backoff on 429."""
        attempt = 0
        # The factories are populated by run() before this method is reached
        # in production; tests that exercise _refresh_one directly stub them
        # via the public init or via setattr.
        assert self._write_factory is not None
        assert self._read_factory is not None

        while attempt < self._BACKOFF_MAX_ATTEMPTS:
            attempt += 1
            uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
            use_case = TriggerIngestionUseCase(uow=uow)
            try:
                await use_case.execute(
                    provider=provider,
                    dataset_type=DatasetType.FUNDAMENTALS,
                    symbols=[symbol],
                    variant=variant,
                )
                fundamentals_refresh_attempts_total.labels(symbol=symbol, status="ok").inc()
                logger.debug(
                    "fundamentals_refresh_ok",
                    symbol=symbol,
                    attempt=attempt,
                )
                return

            except ProviderRateLimited as exc:
                fundamentals_refresh_attempts_total.labels(symbol=symbol, status="rate_limited").inc()
                # Respect provider hint when present (EODHD often sets
                # ``Retry-After``). Otherwise back off exponentially with
                # jitter — mirrors the BP-114 pattern.
                hinted = getattr(exc, "retry_after", None)
                delay = self._compute_backoff_delay(attempt, hint_seconds=hinted)
                logger.warning(
                    "fundamentals_refresh_rate_limited",
                    symbol=symbol,
                    attempt=attempt,
                    retry_after_seconds=delay,
                )
                if attempt >= self._BACKOFF_MAX_ATTEMPTS:
                    return
                await self._sleep(delay)
                continue

            except Exception:
                fundamentals_refresh_attempts_total.labels(symbol=symbol, status="error").inc()
                logger.exception(
                    "fundamentals_refresh_error",
                    symbol=symbol,
                    attempt=attempt,
                )
                return

    # ------------------------------------------------------------- helpers

    def _top_n(self) -> int:
        # Hardcode-clamped to [1, 5000] so a typo'd env var doesn't fan out
        # into a 100k-ticker request storm against EODHD.
        raw = int(getattr(self._settings, "fundamentals_refresh_top_n", 500))
        return max(1, min(5000, raw))

    def _resolve_symbols(self) -> list[str]:
        """Return the (capped) symbol list from CSV override or built-in default.

        Synchronous CSV/default-list resolver. Used directly by
        ``_resolve_symbol_universe`` as the last-resort fallback and kept
        as a public helper for backwards-compat with existing unit tests.
        """
        override = getattr(self._settings, "fundamentals_refresh_symbols", "")
        if override:
            parsed = [s.strip().upper() for s in str(override).split(",") if s.strip()]
        else:
            parsed = list(_DEFAULT_SYMBOL_UNIVERSE)
        # Cap to top-N — the input ordering is already "by market cap" because
        # operators curate the env var that way (or the default list is
        # mega-cap-first). We do NOT re-sort here; preserving input order is
        # part of the contract so backfill ops can prioritise.
        return parsed[: self._top_n()]

    # ------------------------------------------------------------- W5 (PLAN-0100)

    async def _resolve_symbol_universe(self) -> list[str]:
        """Resolve symbols for the current tick (CSV → endpoint → default).

        Priority order:
          1. ``FUNDAMENTALS_REFRESH_SYMBOLS`` CSV override — operator
             kill-switch to pin a specific list during incidents.
          2. ``GET /internal/v1/instruments/top-by-market-cap`` on
             market-data (when ``FUNDAMENTALS_REFRESH_USE_INTERNAL_ENDPOINT``
             is true, the default).
          3. The curated ``_DEFAULT_SYMBOL_UNIVERSE`` mega-cap list so the
             worker never stops producing work even when market-data is
             down.
        """
        # 1. CSV override pin — same precedence as before W5.
        override = getattr(self._settings, "fundamentals_refresh_symbols", "")
        if override:
            return self._resolve_symbols()

        # 2. Live top-N from market-data (off only via explicit env flip).
        if bool(getattr(self._settings, "fundamentals_refresh_use_internal_endpoint", True)):
            symbols = await self._fetch_top_n_symbols(self._top_n())
            if symbols:
                return symbols
            # Empty list from _fetch_top_n_symbols means either the endpoint
            # genuinely returned zero rows OR the call failed; either way
            # we fall back to the curated list below.
            logger.warning(
                "fundamentals_refresh_endpoint_fallback",
                message="market-data top-N endpoint returned no symbols; " "falling back to _DEFAULT_SYMBOL_UNIVERSE",
            )

        # 3. Fallback — curated mega-cap CSV.
        return self._resolve_symbols()

    async def _fetch_top_n_symbols(self, n: int) -> list[str]:
        """Call market-data's ``GET /internal/v1/instruments/top-by-market-cap``.

        Returns the symbol list on success, or an empty list on ANY failure
        (network error, non-2xx, malformed JSON, empty response). The
        empty-on-failure contract is what triggers the curated fallback in
        ``_resolve_symbol_universe``.

        Auth: signs a short-lived RS256 internal JWT using the same
        private key S9 issues — mirrors knowledge-graph's
        ``build_market_data_signer``. Falls back to an HS256 dev token
        when the private key is empty (dev/test only; production
        market-data enforces RS256 unless
        ``MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true``).

        BP-235 guard: explicit ``httpx.Timeout`` is set per request — never
        rely on the httpx 5 s default for a cross-service hop.
        """
        base_url = str(getattr(self._settings, "market_data_url", "http://market-data:8003")).rstrip("/")
        url = f"{base_url}/internal/v1/instruments/top-by-market-cap"

        try:
            token = self._sign_internal_jwt()
        except Exception:
            logger.exception("fundamentals_refresh_jwt_sign_failed")
            return []

        headers: dict[str, str] = {}
        if token:
            headers["X-Internal-JWT"] = token

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url, params={"n": n, "offset": 0}, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "fundamentals_refresh_endpoint_non_2xx",
                    status_code=resp.status_code,
                    url=url,
                )
                return []
            payload = resp.json()
            results = payload.get("results") or []
            symbols = [str(row["symbol"]).strip().upper() for row in results if row.get("symbol")]
            return symbols
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.exception("fundamentals_refresh_endpoint_error", url=url)
            return []

    def _sign_internal_jwt(self) -> str:
        """Sign a short-lived internal JWT for the market-data call.

        DEF-002: delegates to the shared ``mint_internal_jwt`` helper so the
        token always includes ``aud="worldview-internal"`` + a unique ``jti``
        (required by ``InternalJWTMiddleware``).  Returns an HS256 dev token
        when no RS256 private key is configured; production deployments must
        inject the same key S9 uses so market-data accepts the request.
        """
        # SecretStr-or-str compatibility — settings may expose either.
        raw_key = getattr(self._settings, "internal_jwt_private_key", "")
        if hasattr(raw_key, "get_secret_value"):
            raw_key = raw_key.get_secret_value()
        return str(
            mint_internal_jwt(
                sub="system:fundamentals-refresh-worker",
                ttl_seconds=300,
                private_key_pem=raw_key or "",
                dev_hs256_secret="dev-skip-verification-key-for-kg-structured-enrichment",  # noqa: S106 — documented dev-only skip_verification key, not a real secret
            )
        )

    def _compute_backoff_delay(
        self,
        attempt: int,
        *,
        hint_seconds: float | None,
    ) -> float:
        """Exponential backoff with jitter, clamped to ``_BACKOFF_MAX_SECONDS``.

        When the provider supplies a ``retry_after`` hint we honour it as the
        floor (we never sleep less than the provider asked) and still cap at
        ``_BACKOFF_MAX_SECONDS`` to bound worst-case stall.
        """
        # Classic exponential: base * factor**(attempt-1)
        base = self._BACKOFF_BASE_SECONDS * (self._BACKOFF_FACTOR ** (attempt - 1))
        if hint_seconds is not None and hint_seconds > base:
            base = float(hint_seconds)
        # ±20% jitter — multiplied symmetrically around base. Spreads many
        # workers' retries so they don't synchronise into a thundering herd.
        jitter = base * self._BACKOFF_JITTER_FRAC
        delay = base + random.uniform(-jitter, jitter)  # noqa: S311 — jitter, not crypto
        return max(0.0, min(self._BACKOFF_MAX_SECONDS, delay))
