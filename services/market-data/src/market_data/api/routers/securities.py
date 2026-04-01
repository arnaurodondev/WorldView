"""Securities API router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from market_data.api.dependencies import get_list_securities_uc, get_security_uc
from market_data.api.schemas.securities import SecurityListResponse, SecurityResponse
from market_data.application.use_cases.query_securities import GetSecurityUseCase, ListSecuritiesUseCase
from market_data.domain.entities import Security

router = APIRouter(tags=["securities"])


def _to_response(security: Security) -> SecurityResponse:
    return SecurityResponse(
        id=security.id,
        figi=security.figi,
        isin=security.isin,
        name=security.name,
        sector=security.sector,
        industry=security.industry,
        country=security.country,
        currency=security.currency,
        created_at=security.created_at,
        updated_at=security.updated_at,
    )


@router.get("/securities/{security_id}", response_model=SecurityResponse)
async def get_security(
    security_id: str,
    uc: Annotated[GetSecurityUseCase, Depends(get_security_uc)] = ...,  # type: ignore[assignment]
) -> SecurityResponse:
    """Return a security by FIGI or ISIN."""
    security = await uc.execute(security_id)
    if security is None:
        raise HTTPException(status_code=404, detail=f"Security not found: {security_id}")
    return _to_response(security)


@router.get("/securities", response_model=SecurityListResponse)
async def list_securities(
    figi: Annotated[str | None, Query(description="Filter by FIGI")] = None,
    isin: Annotated[str | None, Query(description="Filter by ISIN")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Page offset")] = 0,
    uc: Annotated[ListSecuritiesUseCase, Depends(get_list_securities_uc)] = ...,  # type: ignore[assignment]
) -> SecurityListResponse:
    """List securities, optionally filtered by FIGI or ISIN."""
    securities, total = await uc.execute(figi=figi, isin=isin, limit=limit, offset=offset)
    return SecurityListResponse(
        items=[_to_response(s) for s in securities],
        total=total,
    )
