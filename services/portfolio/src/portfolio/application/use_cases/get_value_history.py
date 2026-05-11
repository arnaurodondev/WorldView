"""Read portfolio_value_snapshots over a date range with optional resampling.

PLAN-0046 Wave 5 / T-46-5-01.

Powers the equity-curve chart on the portfolio page. The use case reads
already-computed daily snapshots written by ``PortfolioSnapshotWorker``
(Wave 4) — it does NOT recompute values on the fly. That keeps the read
path cheap (one indexed range scan) and ensures the equity curve is
consistent with the headline KPI which also derives from the same
snapshot row.

Granularity:

* ``"1d"`` (default) — every snapshot in the range, oldest-first.
* ``"1w"`` — last snapshot in each ISO calendar week. We pick *last*
  rather than *first* because the most recent point in the bucket is
  the one a portfolio manager would compare with today's value
  (Friday close > Monday open for week-over-week analysis).
* ``"1m"`` — last snapshot in each calendar month, by the same
  reasoning as weekly.

The resampling is intentionally implemented in Python rather than SQL
``DATE_TRUNC`` so the use case can be unit-tested with a fake
repository (FakeUnitOfWork has no SQL engine). For the snapshot
volumes we expect (252 trading days * 1 portfolio) the in-memory pass
is O(N) and trivially fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.domain.entities.portfolio_value_snapshot import PortfolioValueSnapshot


# Public granularity literals exposed as strings (no enum import needed in the
# API layer — the FastAPI route validates the value via Pydantic Literal).
VALID_GRANULARITIES = ("1d", "1w", "1m")


@dataclass(frozen=True)
class GetValueHistoryQuery:
    """Inputs for the value-history read.

    ``from_date`` / ``to_date`` are the inclusive range bounds. The
    API layer is responsible for defaulting them — the use case treats
    whatever it receives as the authoritative range so tests can
    exercise edge cases (single-day, future ranges, etc.).
    """

    portfolio_id: UUID
    owner_id: UUID
    tenant_id: UUID
    from_date: date
    to_date: date
    granularity: str = "1d"


def _bucket_key_weekly(d: date) -> tuple[int, int]:
    """ISO year + ISO week — stable bucket key across year boundaries."""
    iso = d.isocalendar()
    return (iso.year, iso.week)


def _bucket_key_monthly(d: date) -> tuple[int, int]:
    """Calendar (year, month) bucket key."""
    return (d.year, d.month)


def _resample_last_per_bucket(
    snapshots: list[PortfolioValueSnapshot],
    granularity: str,
) -> list[PortfolioValueSnapshot]:
    """Keep the last snapshot in each bucket (assumes input is ascending).

    For ``"1d"`` this is an identity transform. For ``"1w"`` / ``"1m"``
    we walk the input once and overwrite the bucket entry on each row;
    because input is ascending, the last write wins — exactly what we
    want for "last snapshot in each week/month".
    """
    if granularity == "1d":
        return list(snapshots)

    key_fn = _bucket_key_weekly if granularity == "1w" else _bucket_key_monthly
    # Use a dict keyed by the bucket — Python preserves insertion order, so
    # iterating values() returns buckets in the same order they first
    # appeared (oldest-first), which is the contract we expose.
    bucket: dict[tuple[int, int], PortfolioValueSnapshot] = {}
    for snap in snapshots:
        bucket[key_fn(snap.snapshot_date)] = snap
    return list(bucket.values())


class GetValueHistoryUseCase:
    """Return resampled value-history points for a portfolio.

    R27 read-only path: depends on ``ReadOnlyUnitOfWork`` so the API
    route can wire it to the read replica.

    Authorisation:

    * ``PortfolioNotFoundError`` (mapped to 404 by the API layer) if the
      portfolio does not exist OR is not owned by ``owner_id``. We
      collapse "not found" and "not owned" into the same outward
      response so we don't leak the existence of other tenants'
      portfolios via a different status code.
    * ``AuthorizationError`` is also raised if the tenant guard fires;
      the API layer maps both to 404 to match the privacy posture.
    """

    async def execute(
        self,
        query: GetValueHistoryQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> list[PortfolioValueSnapshot]:
        if query.granularity not in VALID_GRANULARITIES:
            # Defensive guard — the API layer already validates via
            # Pydantic Literal, but the use case shouldn't trust its caller.
            raise ValueError(f"Unsupported granularity: {query.granularity!r}")

        portfolio = await uow.portfolios.get(query.portfolio_id, query.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {query.portfolio_id} not found")
        if portfolio.owner_id != query.owner_id:
            # Same outward shape as not-found — see class docstring.
            raise AuthorizationError("Not authorized to view this portfolio's value history")

        rows = await uow.portfolio_value_snapshots.list_range(
            query.portfolio_id,
            query.from_date,
            query.to_date,
        )
        # ``list_range`` is contractually ascending — see repository docstring.
        return _resample_last_per_bucket(rows, query.granularity)
