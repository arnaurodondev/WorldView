"""API route registry."""

from __future__ import annotations

from fastapi import APIRouter

from portfolio.api.routes.holding import router as holding_router
from portfolio.api.routes.instrument import router as instrument_router
from portfolio.api.routes.portfolio import router as portfolio_router
from portfolio.api.routes.tenant import router as tenant_router
from portfolio.api.routes.transaction import router as transaction_router
from portfolio.api.routes.user import router as user_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(tenant_router)
api_router.include_router(user_router)
api_router.include_router(portfolio_router)
api_router.include_router(transaction_router)
api_router.include_router(holding_router)
api_router.include_router(instrument_router)
