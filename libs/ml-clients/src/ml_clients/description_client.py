"""EntityDescriptionClient — Protocol + NullDescriptionAdapter (PRD-0017 §6.5)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EntityDescriptionClient(Protocol):
    """Protocol for generating entity descriptions using world-knowledge LLMs."""

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
        news_context: list[str] | None = None,
    ) -> str | None:
        """Generate a world-knowledge description for a non-company entity.

        Args:
            entity_id:      UUID string of the entity (for logging).
            canonical_name: Canonical entity name (e.g. "Jerome Powell").
            entity_type:    Entity type string (e.g. "person", "country").
            context_hints:  Additional hints such as {"role": "Fed Chair", "country": "US"}.
            news_context:   Optional recent-news snippets used to ground the
                            description. When None/empty the adapter injects a
                            no-news guard so the model stays at the category level.

        Returns:
            Description string, or None if the API is unavailable or cost cap exceeded.
        """
        ...


class CostTrackerProtocol(Protocol):
    """Minimal Valkey/Redis protocol for cost tracking (structural typing)."""

    async def incrbyfloat(self, name: str, amount: float) -> float: ...

    async def get(self, name: str) -> bytes | str | None: ...


class NullDescriptionAdapter:
    """Always returns None — used in test/dev environments (no external calls)."""

    async def generate_description(
        self,
        entity_id: str,
        canonical_name: str,
        entity_type: str,
        context_hints: dict[str, str],
        news_context: list[str] | None = None,
    ) -> str | None:
        return None
