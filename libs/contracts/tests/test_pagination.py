"""Tests for the opt-in pagination contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import PaginatedResponse, PaginationParams


def test_pagination_params_constructs_with_values() -> None:
    """Explicit limit/offset within bounds construct cleanly."""
    p = PaginationParams(limit=50, offset=100)
    assert p.limit == 50
    assert p.offset == 100


def test_pagination_params_rejects_limit_zero() -> None:
    """limit < 1 must fail (ge=1)."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=0)


def test_pagination_params_rejects_limit_above_cap() -> None:
    """limit > 200 must fail (le=200) to prevent unbounded queries."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=201)


def test_pagination_params_defaults() -> None:
    """No-arg construction yields the canonical worldview defaults."""
    p = PaginationParams()
    assert p.limit == 20
    assert p.offset == 0


def test_paginated_response_with_int_items() -> None:
    """Generic specialisation with primitives works; has_more defaults False."""
    resp = PaginatedResponse[int](items=[1, 2, 3], total=10, limit=3, offset=0)
    assert resp.items == [1, 2, 3]
    assert resp.total == 10
    assert resp.limit == 3
    assert resp.offset == 0
    # has_more is caller-computed; default is False
    assert resp.has_more is False


def test_paginated_response_with_dict_items() -> None:
    """Generic specialisation with dict items (covariance / heterogeneous shapes)."""
    resp = PaginatedResponse[dict](items=[{"a": 1}], total=5)
    assert resp.items == [{"a": 1}]
    assert resp.total == 5
    # Defaults preserved for limit/offset/has_more when caller omits them
    assert resp.limit == 20
    assert resp.offset == 0
    assert resp.has_more is False
