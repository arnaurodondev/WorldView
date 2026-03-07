"""ID generation utilities."""

from __future__ import annotations

import uuid

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
