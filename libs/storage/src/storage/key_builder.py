"""Canonical object key builder with validation."""

from __future__ import annotations

import re

# Pattern: {service}/{domain}/{resource_id}/{artifact}/{version}.{ext}
_KEY_PATTERN = re.compile(
    r"^[a-z][a-z0-9\-]+/"          # service
    r"[a-z][a-z0-9\-]+/"            # domain
    r"[A-Za-z0-9._/\-]+/"           # resource_id (flexible)
    r"[a-z][a-z0-9\-]+/"            # artifact
    r"v\d+\.[a-z]+$"                # version.ext
)


class InvalidObjectKeyError(ValueError):
    """Raised when an object key violates the naming convention."""


class KeyBuilder:
    """Builds and validates canonical object storage keys.

    Format: ``{service}/{domain}/{resource_id}/{artifact}/{version}.{extension}``

    Example: ``market-ingestion/ohlcv/AAPL.US/2024-01-01_2024-12-31/canonical/v2.parquet``
    """

    @staticmethod
    def build(
        service: str,
        domain: str,
        resource_id: str,
        artifact: str,
        version: str = "v1",
        extension: str = "parquet",
    ) -> str:
        key = f"{service}/{domain}/{resource_id}/{artifact}/{version}.{extension}"
        return key

    @staticmethod
    def validate(key: str) -> None:
        """Validate a key against the naming convention.

        Raises ``InvalidObjectKeyError`` if the key is malformed.
        """
        if not _KEY_PATTERN.match(key):
            raise InvalidObjectKeyError(
                f"Key does not match expected pattern: {key!r}"
            )
