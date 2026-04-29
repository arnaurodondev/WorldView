"""API route registry."""

from __future__ import annotations

from fastapi import APIRouter

from portfolio.api.routes.admin import router as admin_router
from portfolio.api.routes.alert_preferences import router as alert_preferences_router
from portfolio.api.routes.brokerage_connections import router as brokerage_connections_router
from portfolio.api.routes.feedback import router as feedback_router
from portfolio.api.routes.holding import router as holding_router
from portfolio.api.routes.instrument import router as instrument_router
from portfolio.api.routes.portfolio import router as portfolio_router
from portfolio.api.routes.tenant import router as tenant_router
from portfolio.api.routes.transaction import router as transaction_router
from portfolio.api.routes.user import router as user_router
from portfolio.api.routes.watchlist import router as watchlist_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(tenant_router)
api_router.include_router(user_router)
api_router.include_router(portfolio_router)
api_router.include_router(transaction_router)
api_router.include_router(holding_router)
api_router.include_router(instrument_router)
api_router.include_router(watchlist_router, prefix="/watchlists")
api_router.include_router(alert_preferences_router, prefix="/alert-preferences")
api_router.include_router(brokerage_connections_router)
# F-204 (QA iter-2): admin / operator routes — snapshot recompute, etc.
api_router.include_router(admin_router)
# PLAN-0052 Wave D — feedback subsystem (12 endpoints under /api/v1/feedback)
api_router.include_router(feedback_router, prefix="/feedback")
