"""API Gateway route package — re-exports the main router."""

from api_gateway.routes.auth import router as auth_router
from api_gateway.routes.proxy import router

__all__ = ["auth_router", "router"]

# internal_router is imported directly in app.py to avoid circular imports
