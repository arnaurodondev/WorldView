"""API Gateway route package — re-exports the main router."""

from api_gateway.routes.proxy import router

__all__ = ["router"]
