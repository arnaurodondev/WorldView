"""Tests for the cache TTL policy table (PLAN-0107 A-1)."""

from __future__ import annotations

import pytest
from market_ingestion.infrastructure.cache.cache_policy import (
    CACHE_TTL_SECONDS,
    DatasetType,
)

pytestmark = pytest.mark.unit


def test_every_dataset_type_has_ttl() -> None:
    """Each :class:`DatasetType` member MUST appear in
    :data:`CACHE_TTL_SECONDS` with a positive integer TTL -- a missing entry
    would mean an indefinite cache write (no expiry) when that dataset hits
    the cache.
    """
    missing = [member for member in DatasetType if member not in CACHE_TTL_SECONDS]
    assert missing == [], f"DatasetType members without TTL: {missing}"
    for member, ttl in CACHE_TTL_SECONDS.items():
        assert isinstance(ttl, int), f"{member} TTL must be int, got {type(ttl).__name__}"
        assert ttl > 0, f"{member} TTL must be positive, got {ttl}"
