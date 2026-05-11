"""Internal briefing route — POST /internal/v1/briefings (T-B-2-05, PRD-0016 §6.2).

Called exclusively by S10 email scheduler to generate portfolio risk narratives.
Auth: InternalJWTMiddleware (PRD-0025) — RS256 internal JWT validated at middleware level.

R25: This route imports only from the application layer.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request

from rag_chat.api.schemas import BriefingRequest, BriefingResponse
from rag_chat.domain.errors import ProviderUnavailableError, RateLimitExceededError

router = APIRouter(prefix="/internal/v1", tags=["internal"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


def _get_briefing_uc(request: Request) -> Any:
    return request.app.state.briefing_uc


@router.post("/briefings", status_code=200)
async def generate_briefing(
    body: BriefingRequest,
    request: Request,
) -> BriefingResponse:
    """Generate an AI portfolio risk narrative for email delivery.

    - 401: Missing or invalid X-Internal-JWT (enforced by InternalJWTMiddleware)
    - 422: Request body validation failure (FastAPI automatic)
    - 429: Daily rate limit exceeded (100/day per user_id)
    - 503: All LLM providers unavailable
    """
    uc = _get_briefing_uc(request)

    try:
        result = await uc.execute(
            user_id=body.user_id,
            tenant_id=body.tenant_id,
            portfolio_context=body.portfolio_context,
            market_snapshots=body.market_snapshots,
            active_signals=body.active_signals,
            lookback_days=body.lookback_days,
        )
    except RateLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return BriefingResponse(
        narrative=result["narrative"],
        risk_summary=result["risk_summary"],
        citations=result["citations"],
        generated_at=result["generated_at"],
    )
