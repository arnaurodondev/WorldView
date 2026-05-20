"""Base class for tool handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ToolHandler(ABC):
    """Handles execution of a group of related tools.

    WHY ABC: enforces a uniform can_handle / execute contract across all domain
    handler classes. The ToolExecutor dispatcher iterates the handler list and
    delegates to the first handler that claims the tool name.
    """

    @abstractmethod
    def can_handle(self, tool_name: str) -> bool:
        """Return True if this handler handles the named tool."""
        ...

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Execute the tool and return the result.

        Returns:
            RetrievedItem, list[RetrievedItem], or None depending on the tool.
            Returns [] (empty list) on graceful degradation (missing port, no data).
            Returns None on hard-fail (missing auth, rate limit, invalid input).
        """
        ...
