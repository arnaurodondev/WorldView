"""Abstract base adapter for external content sources.

Every concrete adapter (EODHD, SEC EDGAR, Finnhub, NewsAPI) inherits from
:class:`SourceAdapter` and implements :meth:`fetch`.  The base class provides
shared helpers for retry, dedup-hash computation, and backoff.
"""

from __future__ import annotations

import asyncio
import hashlib
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.application.ports.source_adapter import SourceAdapterPort
from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import FetchResult, Source

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTORS = (1.0, 2.0, 4.0)


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry configuration for adapter HTTP calls."""

    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_factors: tuple[float, ...] = DEFAULT_BACKOFF_FACTORS


def _is_retryable(exc: Exception) -> bool:
    """Return False for exceptions that signal permanent client-side failures.

    F-104 fix (2026-04-30): the previous retry loop treated every Exception
    as transient and burned 3 attempts x backoff on permanent failures (e.g.
    Finnhub 403 "premium endpoint required"). We detect non-retryable
    exceptions via ``isinstance`` so the check is robust to renames and
    subclassing — the previous string-name match would silently break if
    ``PremiumEndpointError`` was renamed.
    """
    # Late import to avoid an import cycle: client.py imports from this module.
    try:
        from content_ingestion.infrastructure.adapters.finnhub.client import PremiumEndpointError
    except ImportError:
        return True
    return not isinstance(exc, PremiumEndpointError)


def url_hash(value: str) -> str:
    """Compute a SHA-256 hex digest used as dedup key."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SourceAdapter(SourceAdapterPort):
    """Abstract base class for external content source adapters.

    Inherits from :class:`SourceAdapterPort` (application-layer interface).

    Each adapter:
    - Fetches articles from one external API
    - Deduplicates by ``url_hash`` (checked via ``exists_fn``)
    - Retries transient failures with exponential backoff
    - Propagates ``is_backfill`` and ``published_at`` through results
    """

    @abstractmethod
    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch articles from the external source.

        Args:
            source: The configured polling source with API config.
            is_backfill: Whether this is a historical backfill run.
            from_date: Optional date override (YYYY-MM-DD) from watermarks.

        Returns:
            List of :class:`FetchResult` objects for new (non-duplicate) articles.
        """

    @staticmethod
    async def _retry_request(
        coro_factory: object,
        *,
        retry_config: RetryConfig | None = None,
        context: str = "",
    ) -> object:
        """Execute an async callable with retry + exponential backoff.

        Args:
            coro_factory: An async callable (no-arg) that performs the HTTP request.
            retry_config: Retry parameters.  Defaults to 3 retries with 1s/2s/4s backoff.
            context: Description for log messages.

        Returns:
            The result of the successful call.

        Raises:
            AdapterError: After all retries are exhausted.
        """
        cfg = retry_config or RetryConfig()
        last_exc: Exception | None = None

        # F-104 fix (2026-04-30): a permanent client-side failure (403, 401, 404)
        # must NOT be retried. The previous code caught Exception broadly and
        # re-tried every kind of error, which on a free Finnhub tier wasted
        # ~56 s/cycle hammering paid endpoints. Re-raise non-retryable
        # exceptions immediately so the caller can handle them once.
        for attempt in range(cfg.max_retries + 1):
            try:
                return await coro_factory()  # type: ignore[operator]
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                if attempt < cfg.max_retries:
                    delay = (
                        cfg.backoff_factors[attempt] if attempt < len(cfg.backoff_factors) else cfg.backoff_factors[-1]
                    )
                    logger.warning(
                        "adapter_retry",
                        context=context,
                        attempt=attempt + 1,
                        max_retries=cfg.max_retries,
                        delay_seconds=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)

        msg = f"All {cfg.max_retries} retries exhausted for {context}"
        raise AdapterError(msg) from last_exc
