"""PromptTemplate — frozen, versioned, parameter-validated prompt container."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class PromptTemplate:
    """Typed prompt template with parameter validation."""

    name: str
    version: str
    description: str
    template: str
    parameters: frozenset[str]

    def render(self, **kwargs: str) -> str:
        """Substitute parameters into template.

        Raises ValueError if required parameters are missing.
        Extra kwargs beyond self.parameters are silently ignored.
        """
        missing = self.parameters - set(kwargs.keys())
        if missing:
            msg = f"Missing required parameters: {', '.join(sorted(missing))}"
            raise ValueError(msg)
        return self.template.format_map(kwargs)
