"""Port interfaces for the intelligence-rollup upstream clients (R25).

The ``SyncIntelligenceRollupUseCase`` materialises 6 intelligence fields by
calling 4 upstream services (S6/S7/S8/S10).  Per R25 the application layer must
not depend on the concrete ``httpx`` clients in ``infrastructure/clients`` —
instead it depends on these abstract ports and the composition root (``app.py``)
injects the concrete implementations.

The concrete clients live in
``market_data.infrastructure.clients.intelligence_clients`` and subclass these
ports.  The response value objects (``S6NewsRollup`` etc.) live in the **domain**
layer (``market_data.domain.intelligence_rollup``) so both the port and the use
case can reference them without an application→infrastructure dependency.
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Domain value objects (application→domain dependency is allowed under R25).
    # Used only in return annotations, so a TYPE_CHECKING import suffices and
    # avoids a runtime import cycle.
    from market_data.domain.intelligence_rollup import (
        S6NewsRollup,
        S7IntelligenceRollup,
        S8BriefFlag,
        S10AlertFlag,
    )


class S6NewsRollupClientPort(abc.ABC):
    """Port: S6 (content-store / nlp-pipeline) 7-day news rollup."""

    @abc.abstractmethod
    async def get_news_rollup(self, instrument_id: str) -> S6NewsRollup | None:
        """Return the parsed news rollup, or ``None`` on failure."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close the underlying HTTP client."""


class S7IntelligenceClientPort(abc.ABC):
    """Port: S7 (knowledge-graph) 7-day intelligence rollup."""

    @abc.abstractmethod
    async def get_intelligence_rollup(self, instrument_id: str) -> S7IntelligenceRollup | None:
        """Return the parsed intelligence rollup, or ``None`` on failure."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close the underlying HTTP client."""


class S10AlertClientPort(abc.ABC):
    """Port: S10 (alert) active-alert flag."""

    @abc.abstractmethod
    async def get_active_alert_flag(self, instrument_id: str) -> S10AlertFlag | None:
        """Return the parsed active-alert flag, or ``None`` on failure."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close the underlying HTTP client."""


class S8BriefClientPort(abc.ABC):
    """Port: S8 (rag-chat) AI-brief flag."""

    @abc.abstractmethod
    async def get_ai_brief_flag(self, instrument_id: str) -> S8BriefFlag | None:
        """Return the parsed AI-brief flag, or ``None`` on failure."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
