"""ID generation utilities."""

from __future__ import annotations

import uuid
from typing import cast

import uuid6 as _uuid6  # type: ignore[import-not-found]  # imported at module level with alias to avoid shadowing stdlib uuid
from ulid import ULID


def new_uuid() -> uuid.UUID:
    """Generate a new random UUID v4."""
    return uuid.uuid4()


def new_uuid_str() -> str:
    """Generate a new random UUID v4 as a string."""
    return str(uuid.uuid4())


def new_ulid() -> str:
    """Generate a new time-sortable ULID as a string."""
    return str(ULID())


def new_uuid7() -> uuid.UUID:
    """Generate a new time-sortable UUIDv7 (RFC 9562).

    Use for all new entity primary keys in the ingestion pipeline
    (documents, entities, relations, alerts, sections, chunks, etc.).
    UUIDv7 is monotonically increasing within a millisecond, making it
    safe for time-based ordering without a separate ``created_at`` index scan.

    Do NOT use for Kafka event IDs — use ``new_ulid()`` for those.
    Do NOT use in existing services (portfolio, market-ingestion) that already
    have UUIDv4 primary keys in production — changing would break existing rows.
    """
    return cast("uuid.UUID", _uuid6.uuid7())


def new_uuid7_str() -> str:
    """Generate a new time-sortable UUIDv7 as a hyphenated string.

    Convenience wrapper for contexts that require a str (e.g., Avro payloads,
    HTTP response bodies). Equivalent to ``str(new_uuid7())``.
    """
    return str(new_uuid7())
