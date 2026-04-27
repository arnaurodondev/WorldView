"""Adapter port interfaces for external services.

These ABCs define how the application layer interacts with external systems
(providers, object storage, canonical serialization) without depending on
specific implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from market_ingestion.domain.enums import DatasetType, Provider
    from market_ingestion.domain.value_objects import ObjectRef

# ---------------------------------------------------------------------------
# Shared result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderFetchResult:
    """Result from a provider fetch operation."""

    provider: Provider
    dataset_type: DatasetType
    symbol: str
    raw_data: bytes
    content_type: str
    fetched_at: datetime
    duration_ms: int
    range_start: datetime | None = None
    range_end: datetime | None = None
    provider_metadata: dict[str, Any] | None = None
    bars_returned: int = 0


# ---------------------------------------------------------------------------
# Port ABCs
# ---------------------------------------------------------------------------


class ProviderAdapter(ABC):
    """Port for market data provider adapters.

    Each provider (EODHD, Polygon, etc.) implements this interface.
    The application layer is agnostic to provider-specific APIs.
    """

    @property
    @abstractmethod
    def provider(self) -> Provider:
        """Return the provider this adapter handles."""

    @abstractmethod
    async def fetch_quotes(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch real-time quotes for a symbol.

        Raises
        ------
            ProviderRateLimited: HTTP 429.
            ProviderUnavailable: HTTP 5xx or connection timeout.
            ProviderAuthError: HTTP 401/403.
            ProviderDataError: Malformed response.

        """

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch OHLCV (candlestick) data for a date range."""

    @abstractmethod
    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch fundamental data for a symbol."""

    @property
    def supports_batch(self) -> bool:
        """True if this adapter supports multi-symbol batch fetching.

        When True, the worker layer may call ``fetch_ohlcv_batch(symbols, ...)``
        to batch multiple tasks into a single HTTP request instead of making one
        call per symbol.  Defaults to False — only adapters with a native
        multi-symbol endpoint (e.g. Alpaca) should override this.
        """
        return False

    async def health_check(self) -> bool:
        """Check if the provider is reachable. Returns True if healthy."""
        return True


class ObjectStoreAdapter(ABC):
    """Port for object storage (MinIO/S3) operations.

    Aligns with the ``libs/storage.ObjectStorage`` ABC signatures.
    """

    @abstractmethod
    async def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        """Store an object and return its reference.

        Raises
        ------
            StorageUnavailable: If storage is unreachable.

        """

    @abstractmethod
    async def get(
        self,
        bucket: str,
        key: str,
    ) -> bytes:
        """Retrieve an object's raw bytes."""

    @abstractmethod
    async def exists(
        self,
        bucket: str,
        key: str,
    ) -> bool:
        """Return True if the object exists."""

    @abstractmethod
    async def ensure_bucket(self, bucket: str) -> None:
        """Ensure a bucket exists, creating it if necessary."""


class CanonicalSerializer(ABC):
    """Port for canonical data serialization.

    Transforms raw provider data dicts into normalized JSONL bytes using
    ``libs/contracts`` canonical models. MIME type is always
    ``application/x-ndjson``.
    """

    MIME_TYPE: str = "application/x-ndjson"

    @abstractmethod
    def serialize_quotes(self, data: list[dict[str, Any]]) -> bytes:
        """Serialize a list of quote dicts to JSONL bytes.

        Each dict must contain fields required by ``CanonicalQuote``.
        Returns UTF-8-encoded JSONL; one line per record.
        """

    @abstractmethod
    def serialize_ohlcv(self, data: list[dict[str, Any]]) -> bytes:
        """Serialize a list of OHLCV bar dicts to JSONL bytes.

        Each dict must contain fields required by ``CanonicalOHLCVBar``.
        Returns UTF-8-encoded JSONL; one line per bar.
        """

    @abstractmethod
    def serialize_fundamentals(
        self,
        data: dict[str, Any],
        variant: str | None = None,
    ) -> bytes:
        """Serialize a fundamentals dict to a single JSONL line.

        ``data`` must contain fields required by ``CanonicalFundamentals``.
        Returns UTF-8-encoded JSONL with a single record.
        """

    @abstractmethod
    def serialize_passthrough(
        self,
        raw_data: Any,
        dataset_type: str,
        symbol: str,
        source: str,
    ) -> bytes:
        """Wrap raw provider data in a self-describing canonical envelope.

        Used for dataset types that have no domain-specific canonical model
        (economic_events, macro_indicator, insider_transactions,
        earnings_calendar, news_sentiment, yield_curve, market_cap).
        The envelope is self-describing so downstream consumers (e.g. S7)
        can identify and parse it without additional context.

        Args:
        ----
            raw_data: The parsed JSON payload from the provider (dict or list).
            dataset_type: String value of the DatasetType enum (e.g. "economic_events").
            symbol: The task symbol (e.g. "EVENTS.USA", "AAPL").
            source: String value of the Provider enum (e.g. "eodhd").

        Returns:
        -------
            UTF-8-encoded NDJSON with a single envelope record, newline-terminated.

        """
