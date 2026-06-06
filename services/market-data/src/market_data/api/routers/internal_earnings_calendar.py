"""Internal earnings-calendar API router.

PLAN-0102 Wave 3 T-W3-02.

Exposes:
  GET /internal/v1/calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD

WHY THIS ENDPOINT EXISTS
------------------------
The morning brief (rag-chat) needs a forward-looking earnings calendar so
the "Macro Today" section can name upcoming earnings ("Earnings this week:
NVDA Tue AMC, CRM Wed AMC"). The existing S9 ``/v1/fundamentals/earnings-
calendar`` route queries the S7 ``temporal_events`` table — useful for the
public dashboard but the brief specifically wants the row-level EODHD
``earnings_calendar`` table on market-data (consensus EPS, before/after
market session, fiscal date) without going through the gateway.

DATA SOURCE
-----------
Reads ``earnings_calendar`` directly. This table exists since alembic
migration 001 and is populated by the EODHD ``/calendar/earnings`` sync
worker (PLAN-0089 L-5b). When the worker has not run for a date range
the response will be an empty ``events: []`` list — that is by design
(not a 500).

RESPONSE SHAPE
--------------
Wire shape per PRD::

    {
      "from": "2026-05-29",
      "to":   "2026-06-05",
      "events": [
        {
          "symbol":           "NVDA",
          "entity_id":        null,   // not modelled on instruments
          "report_date":      "2026-05-30",
          "when":             "AMC",  // AMC | BMO | DMH | null
          "period":           null,    // not derivable without fundamentals join
          "consensus_eps":    0.83,
          "consensus_rev_usd": null   // EODHD does not provide on calendar
        }
      ]
    }

Fields that we cannot populate from ``earnings_calendar`` alone are
serialised as ``null`` rather than omitted — keeps the schema stable for
callers and makes it explicit that we don't have the data, vs. a missing
key implying schema drift.

AUTH + CACHE
------------
  * Auth: ``X-Internal-JWT`` via ``require_internal_jwt``.
  * Cache: 300 s Valkey keyed by ``earn-cal:v1:{from}:{to}``. Earnings dates
    don't shift intra-day except for very rare reschedules — a 5 min TTL is
    a safe latency/freshness trade-off for brief generation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from market_data.api.dependencies import require_internal_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["internal-earnings-calendar"])

_CACHE_TTL_SECONDS = 300

# Hard caps to bound query cost and protect the DB from misconfigured
# callers. 90 days covers a full quarter of forward earnings — anything
# larger is almost certainly a bug in the caller.
_MAX_RANGE_DAYS = 90


# ── Response schema ─────────────────────────────────────────────────────────


class EarningsEventResponse(BaseModel):
    """One earnings event row in the response.

    Nullable fields encode "we don't have it" — never silently omitted.
    """

    symbol: str
    entity_id: str | None
    report_date: date
    when: str | None  # "AMC" | "BMO" | "DMH" | None
    period: str | None  # e.g. "Q4 FY26" — None until fundamentals join is added
    consensus_eps: float | None
    consensus_rev_usd: float | None


class EarningsCalendarResponse(BaseModel):
    """Top-level earnings calendar response shape.

    Internally the lower-bound is stored as ``from_`` because ``from`` is
    a Python keyword. The wire JSON uses plain ``"from"`` via Field alias
    + ``ser_json_by_alias`` so the contract matches the PRD example.
    """

    from_: date = Field(alias="from")
    to: date
    events: list[EarningsEventResponse]

    # ``ser_json_by_alias`` makes ``model_dump_json()`` emit ``"from"`` not
    # ``"from_"``; mypy's ConfigDict TypedDict doesn't know about this key
    # in our pinned pydantic version so we silence the unknown-key warning.
    model_config = {"populate_by_name": True, "ser_json_by_alias": True}  # type: ignore[typeddict-unknown-key]


# ── Helper — translate EODHD ``before_after`` to compact tag ────────────────


def _when_tag(before_after: str | None) -> str | None:
    """Translate EODHD ``before_after`` string to the BMO/AMC/DMH tag.

    EODHD uses ``BeforeMarket`` / ``AfterMarket`` / ``DuringMarket`` strings;
    we surface the standard ``BMO``/``AMC``/``DMH`` shorthand the brief
    formatter expects.
    """
    if before_after is None:
        return None
    mapping = {
        "BeforeMarket": "BMO",
        "AfterMarket": "AMC",
        "DuringMarket": "DMH",
    }
    return mapping.get(before_after, before_after)


# ── Endpoint ────────────────────────────────────────────────────────────────


@router.get(
    "/calendar/earnings",
    response_model=EarningsCalendarResponse,
    # ``response_model_by_alias=True`` honours the ``from_`` → ``"from"``
    # alias on the response wire shape. Without it FastAPI emits the
    # Python attribute name and breaks the PRD contract.
    response_model_by_alias=True,
)
async def get_earnings_calendar(
    request: Request,
    # WHY ``alias="from"`` on the query param: ``from`` is a Python keyword
    # so we accept it via alias on the Annotated[Query()] but bind to a
    # safe attribute name internally.
    from_: Annotated[
        date,
        Query(alias="from", description="Inclusive lower bound on report_date (YYYY-MM-DD)."),
    ],
    to: Annotated[
        date,
        Query(description="Inclusive upper bound on report_date (YYYY-MM-DD)."),
    ],
    _: Annotated[None, Depends(require_internal_jwt)] = None,
) -> EarningsCalendarResponse:
    """Return earnings calendar rows for a date range."""
    if to < from_:
        raise HTTPException(status_code=422, detail="to must be >= from")
    if (to - from_) > timedelta(days=_MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=422,
            detail=f"date range cannot exceed {_MAX_RANGE_DAYS} days",
        )

    # ── Cache read (fail-open) ──────────────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    cache_key = f"earn-cal:v1:{from_.isoformat()}:{to.isoformat()}"
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return EarningsCalendarResponse.model_validate_json(raw)
        except Exception as exc:
            logger.warning("earnings_calendar_cache_read_failed", error=str(exc))

    # ── DB read ─────────────────────────────────────────────────────────────
    # Defensive import keeps router import-time light and matches the pattern
    # used elsewhere in this codebase (internal_market_tape).
    from sqlalchemy import select

    from market_data.infrastructure.db.models.earnings_calendar import EarningsCalendarModel
    from market_data.infrastructure.db.models.instruments import InstrumentModel

    read_factory = request.app.state.read_session_factory
    events: list[EarningsEventResponse] = []
    try:
        async with read_factory() as session:
            stmt = (
                select(
                    InstrumentModel.symbol,
                    EarningsCalendarModel.report_date,
                    EarningsCalendarModel.before_after,
                    EarningsCalendarModel.eps_estimate,
                )
                .join(InstrumentModel, InstrumentModel.id == EarningsCalendarModel.instrument_id)
                .where(
                    EarningsCalendarModel.report_date >= from_,
                    EarningsCalendarModel.report_date <= to,
                )
                .order_by(EarningsCalendarModel.report_date.asc(), InstrumentModel.symbol.asc())
            )
            rows = (await session.execute(stmt)).all()
            for row in rows:
                events.append(
                    EarningsEventResponse(
                        symbol=row[0],
                        entity_id=None,  # not modelled on instruments
                        report_date=row[1],
                        when=_when_tag(row[2]),
                        period=None,  # would require fundamentals_history join — out of scope for W3
                        consensus_eps=(float(row[3]) if row[3] is not None else None),
                        consensus_rev_usd=None,  # EODHD does not surface this on /calendar/earnings
                    )
                )
    except Exception as exc:
        # Fail-open: empty calendar is better than a 500 in the brief
        # generation pipeline (we'd rather omit the section than break it).
        logger.warning("earnings_calendar_query_failed", error=str(exc), from_=str(from_), to=str(to))
        events = []

    # WHY model_validate(dict) over kwargs: mypy can't see Pydantic's
    # populate_by_name=True alias-binding, so passing ``from_=`` kwarg raises
    # call-arg. Going through model_validate avoids the false positive.
    resp = EarningsCalendarResponse.model_validate(
        {"from_": from_, "to": to, "events": events},
    )

    # ── Cache write (fail-open) ─────────────────────────────────────────────
    if valkey is not None:
        try:
            await valkey.set(cache_key, resp.model_dump_json(), ex=_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("earnings_calendar_cache_write_failed", error=str(exc))

    return resp


__all__ = ["EarningsCalendarResponse", "EarningsEventResponse", "router"]
