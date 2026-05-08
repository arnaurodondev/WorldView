"""ToolRegistry — maps tool names to ToolSpec + handler callables (PLAN-0066 Wave H).

The registry is the central lookup used by:
- ToolExecutor (dispatch to the correct handler)
- ChatOrchestratorUseCase (inject manifest section into system prompt)
- Architecture tests (verify capability_manifest.yaml is in sync with registrations)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from tools.tool_spec import ToolSpec  # noqa: TCH001

# Path to the canonical tool manifest, co-located with this module
_MANIFEST_PATH = Path(__file__).parent / "capability_manifest.yaml"


class ToolRegistry:
    """Registry of LLM-callable tools.

    Tools are registered at application startup via register().
    The registry is stateless after construction — safe for concurrent use.
    """

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, spec: ToolSpec, handler: Callable[..., Any]) -> None:
        """Register a tool spec and its handler callable.

        Args:
            spec: The ToolSpec describing name, parameters, and source_type.
            handler: An async callable that accepts the tool's input kwargs
                     and returns a value (typically ``RetrievedItem | None``).
        """
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def get_spec(self, name: str) -> ToolSpec | None:
        """Return the ToolSpec for a registered tool, or None if unknown."""
        return self._specs.get(name)

    def get_handler(self, name: str) -> Callable[..., Any] | None:
        """Return the handler callable for a registered tool, or None if unknown."""
        return self._handlers.get(name)

    def all_specs(self) -> list[ToolSpec]:
        """Return all registered ToolSpecs in registration order."""
        return list(self._specs.values())

    def to_system_prompt_section(self) -> str:
        """Render the manifest as a fenced YAML block for LLM system prompts.

        WHY fenced YAML: the LLM is instructed to emit JSON ``tool_use`` blocks
        when it decides a tool is appropriate. The manifest section gives the LLM
        the name + parameter schema it needs to construct a valid block. YAML is
        more compact than JSON for this purpose and the LLM handles it well.
        """
        lines = ["Available tools (call by emitting a tool_use JSON block):\n```yaml"]
        for spec in self._specs.values():
            lines.append(f"- name: {spec.name}")
            lines.append(f"  description: {spec.description[:200]}")
            if spec.parameters:
                lines.append("  parameters:")
                for p in spec.parameters:
                    lines.append(f"    - name: {p.name}")
                    lines.append(f"      type: {p.type}")
                    lines.append(f"      required: {str(p.required).lower()}")
        lines.append("```")
        return "\n".join(lines)

    def load_manifest(self) -> dict[str, Any]:
        """Load and return the raw capability_manifest.yaml for architecture tests.

        Architecture tests use this to assert that every registered tool has a
        corresponding YAML entry (R29: manifest must stay in sync with code).
        """
        with open(_MANIFEST_PATH) as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]
