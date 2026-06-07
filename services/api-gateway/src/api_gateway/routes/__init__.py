"""API Gateway route package — combines 7 domain routers into main_router.

PLAN-0089 B-3: proxy.py (4319 lines) was split into 7 focused domain modules.
The combined ``router`` is imported by app.py as ``main_router``.
"""

from fastapi import APIRouter

from api_gateway.routes.alerts import router as alerts_router
from api_gateway.routes.auth import router as auth_router
from api_gateway.routes.chat import router as chat_router
from api_gateway.routes.content import router as content_router
from api_gateway.routes.dashboard import router as dashboard_router
from api_gateway.routes.instruments import router as instruments_router
from api_gateway.routes.intelligence import router as intelligence_router
from api_gateway.routes.market import router as market_router
from api_gateway.routes.portfolio import router as portfolio_router

# Combined router — all domain routers merged in registration order.
# WHY order matters: FastAPI evaluates routes in registration order.
# Routes with literal path segments (e.g. /entities/similar) must be
# registered BEFORE parameterised routes (e.g. /entities/{entity_id}).
# content_router: /entities/similar + /entities/{id}/articles registered
#   before intelligence_router: /entities/{id}/graph etc.
# instruments_router: /instruments/lookup + /search/instruments registered
#   before market_router: /fundamentals/{id}/* etc.
router = APIRouter()
router.include_router(alerts_router)
router.include_router(chat_router)
# F-2: dashboard bundle endpoint — registered BEFORE portfolio_router (which
# owns /v1/dashboard/snapshot) so route resolution is purely by path; no
# ordering conflict (different paths) but keeping dashboard.* together helps
# discovery.
router.include_router(dashboard_router)
router.include_router(content_router)
router.include_router(instruments_router)
router.include_router(intelligence_router)
router.include_router(market_router)
router.include_router(portfolio_router)

__all__ = ["auth_router", "router"]

# internal_router is imported directly in app.py to avoid circular imports
