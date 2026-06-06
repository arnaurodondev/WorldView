"""Reusable pagination request/response models.

Designed to be adopted opt-in by services that currently roll their own
limit/offset schemas. Existing per-service pagination continues to work
unchanged.

Pattern:
  - PaginationParams: query-param input (limit, offset) with sensible
    defaults and bounds.
  - PaginatedResponse[T]: wraps a list of T plus total count + has_more
    flag.

Rationale:
  Across the worldview backend, several services (portfolio, market-data,
  knowledge-graph, content-store, …) each define their own pagination
  schemas with subtly different defaults (limit=20/50/100, offset/page,
  caps of 100/200/500). This module provides a single canonical shape
  so services can converge over time without a forced migration.

Defaults:
  ``limit=20`` matches the most common worldview pattern (portfolio
  transactions, news feeds, holdings). ``limit`` is capped at 200 to
  prevent unbounded queries that could exhaust a connection or memory
  budget. Services with legitimate higher caps should keep their own
  schema rather than relax this default.

Cursor variant:
  REF-003 / TASK-W4-07 explicitly calls for limit/offset only. A
  cursor-based variant is out of scope for this task and will be added
  later if needed (e.g. for very large keyset-paginated screener results).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

# Generic item type for PaginatedResponse. Bound to ``object`` rather than
# a more specific protocol so that primitives (int, str), dicts, and
# pydantic models can all flow through transparently.
T = TypeVar("T")


class PaginationParams(BaseModel):
    """Standard pagination query parameters.

    Defaults match the most common worldview pattern (limit=20, offset=0).
    ``limit`` is capped at 200 to prevent unbounded queries.

    Usage::

        from contracts import PaginationParams

        @router.get("/items")
        async def list_items(p: PaginationParams = Depends()) -> ...:
            rows = await repo.list(limit=p.limit, offset=p.offset)
    """

    limit: int = Field(default=20, ge=1, le=200, description="Max rows to return (1-200)")
    offset: int = Field(default=0, ge=0, description="Number of rows to skip")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response wrapper.

    ``has_more`` is computed by the service from ``total`` vs
    ``offset + limit`` — this model does not derive it automatically
    because some endpoints stream from sources where ``total`` is
    expensive or unknown (in which case callers may set ``has_more``
    from a "did we get a full page back?" check instead).

    Usage::

        return PaginatedResponse[TransactionOut](
            items=rows,
            total=total,
            limit=p.limit,
            offset=p.offset,
            has_more=(p.offset + len(rows)) < total,
        )
    """

    items: list[T] = Field(default_factory=list)
    total: int = Field(default=0, ge=0, description="Total matching rows in the underlying source")
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    has_more: bool = Field(default=False)
