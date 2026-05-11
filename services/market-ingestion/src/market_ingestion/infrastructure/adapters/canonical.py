"""DefaultCanonicalSerializer — converts raw provider dicts to canonical JSONL.

Uses ``libs/contracts`` canonical models for type validation before serialization.
"""

from __future__ import annotations

import json
from typing import Any

from contracts.canonical.fundamentals import CanonicalFundamentals  # type: ignore[import-untyped]
from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from contracts.canonical.quotes import CanonicalQuote  # type: ignore[import-untyped]
from market_ingestion.application.ports.adapters import CanonicalSerializer
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class DefaultCanonicalSerializer(CanonicalSerializer):
    """Serialize provider data to newline-delimited JSON using contracts models.

    Each record is validated by its canonical model before serialization,
    guaranteeing schema compliance. The output is UTF-8 NDJSON.
    """

    def serialize_ohlcv(self, data: list[dict[str, Any]]) -> bytes:
        """Validate and serialize OHLCV bars to NDJSON bytes.

        Args:
        ----
            data: List of raw bar dicts from the provider adapter.

        Returns:
        -------
            UTF-8 NDJSON — one JSON line per bar, newline-terminated.

        """
        lines: list[str] = []
        for row in data:
            bar = CanonicalOHLCVBar.from_dict(row)
            lines.append(json.dumps(bar.to_dict()))
        result = "\n".join(lines)
        if result:
            result += "\n"
        return result.encode("utf-8")

    def serialize_quotes(self, data: list[dict[str, Any]]) -> bytes:
        """Validate and serialize quote snapshots to NDJSON bytes.

        Args:
        ----
            data: List of raw quote dicts from the provider adapter.

        Returns:
        -------
            UTF-8 NDJSON — one JSON line per quote, newline-terminated.

        """
        lines: list[str] = []
        for row in data:
            quote = CanonicalQuote.from_dict(row)
            lines.append(json.dumps(quote.to_dict()))
        result = "\n".join(lines)
        if result:
            result += "\n"
        return result.encode("utf-8")

    def serialize_fundamentals(
        self,
        data: dict[str, Any],
        variant: str | None = None,
    ) -> bytes:
        """Validate and serialize a fundamentals dict to a single NDJSON line.

        Args:
        ----
            data: Raw fundamentals dict from the provider adapter.
            variant: ``"annual"`` or ``"quarterly"`` (informational only).

        Returns:
        -------
            UTF-8 NDJSON — one JSON line, newline-terminated.

        """
        fund = CanonicalFundamentals.from_dict(data)
        return (json.dumps(fund.to_dict()) + "\n").encode("utf-8")

    def serialize_passthrough(
        self,
        raw_data: Any,
        dataset_type: str,
        symbol: str,
        source: str,
    ) -> bytes:
        """Wrap raw provider data in a canonical envelope for passthrough dataset types.

        Used for dataset types that have no domain-specific canonical model
        (economic_events, macro_indicator, insider_transactions,
        earnings_calendar, news_sentiment, yield_curve, market_cap). The
        envelope is self-describing so downstream consumers can identify and
        parse it without additional context.

        Args:
        ----
            raw_data: The parsed JSON payload from the provider (dict or list).
            dataset_type: String value of the DatasetType enum (e.g. "economic_events").
            symbol: The task symbol (e.g. "EVENTS.USA", "AAPL").
            source: String value of the Provider enum (e.g. "eodhd").

        Returns:
        -------
            UTF-8 NDJSON — one envelope line, newline-terminated.

        """
        from common.time import utc_now  # type: ignore[import-untyped]

        envelope = {
            "dataset_type": dataset_type,
            "symbol": symbol,
            "source": source,
            "payload": raw_data,
            "fetched_at": utc_now().isoformat(),
        }
        return (json.dumps(envelope) + "\n").encode("utf-8")
