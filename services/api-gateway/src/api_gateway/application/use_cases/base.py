"""Base class for gateway use cases.

api-gateway has NO database — use cases make HTTP calls only via httpx.AsyncClient.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from api_gateway.config import Settings


class GatewayUseCase(ABC):
    """Abstract base for all gateway use cases.

    Dependencies: httpx.AsyncClient (for downstream HTTP calls) + Settings (for URLs).
    No database, no UnitOfWork — api-gateway is stateless.
    """

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = http_client
        self._settings = settings

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any: ...
