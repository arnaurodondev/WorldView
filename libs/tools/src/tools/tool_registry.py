"""ToolRegistry — maps tool names to ToolSpec + handler callables (PLAN-0066 Wave H).

The registry is the central lookup used by:
- ToolExecutor (dispatch to the correct handler)
- ChatOrchestratorUseCase (inject manifest section into system prompt)
- Architecture tests (verify capability_manifest.yaml is in sync with registrations)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from tools.tool_spec import ToolSpec

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

    def to_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format function-calling definitions for all registered tools.

        Each entry has the OpenAI ``chat.completions`` ``tools`` shape:
            {
              "type": "function",
              "function": {
                "name": <tool_name>,
                "description": <description>,
                "parameters": {
                  "type": "object",
                  "properties": { <param_name>: { "type": ..., "description": ..., ... } },
                  "required": [ <required_param_names> ]
                }
              }
            }

        WHY this method exists (D-R1-001 / PLAN-0087 Wave F): the chat orchestrator
        previously called ``hasattr(registry, "to_tool_definitions")`` which always
        returned False (the method was only mocked in tests, never defined in
        production). As a result ``tool_defs=None`` was passed to ``chat_with_tools``,
        the OpenAI ``tools`` and ``tool_choice`` keys were omitted, and the model
        could only mimic tool calls by emitting raw markdown ``tool_code`` blocks
        as user-visible answer text. Implementing this method makes native
        OpenAI function-calling work end-to-end.

        Type mapping (ParameterSpec.type → JSON Schema):
            string  → {"type": "string"}
            date    → {"type": "string", "format": "date"}  # YYYY-MM-DD
            integer → {"type": "integer"}
            number  → {"type": "number"}
            boolean → {"type": "boolean"}
            array   → {"type": "array", "items": {"type": "string"}}  # default item type
            object  → {"type": "object"}  # opaque payload — LLM emits arbitrary JSON
        """
        definitions: list[dict[str, Any]] = []
        for spec in self._specs.values():
            properties: dict[str, dict[str, Any]] = {}
            required: list[str] = []
            for p in spec.parameters:
                # Build the per-parameter JSON Schema fragment.
                # WHY a dedicated builder: we need to handle date (string + format),
                # array (items schema), and enum constraints uniformly.
                schema: dict[str, Any] = {}
                if p.type == "date":
                    # JSON Schema convention for ISO-8601 dates.
                    schema["type"] = "string"
                    schema["format"] = "date"
                elif p.type == "array":
                    # Default array item type is string — covers all current uses
                    # in capability_manifest.yaml (ticker lists, source-type lists,
                    # relation-type lists).  If a future tool needs typed items,
                    # extend ParameterSpec rather than guessing here.
                    schema["type"] = "array"
                    schema["items"] = {"type": "string"}
                else:
                    # string, integer, number, boolean, object — all map 1:1.
                    schema["type"] = p.type
                schema["description"] = p.description
                if p.enum:
                    # Constrain the LLM to a known allowlist (e.g. severity levels,
                    # interval grain).  Mirrors capability_manifest.yaml ``enum:`` keys.
                    schema["enum"] = list(p.enum)
                properties[p.name] = schema
                if p.required:
                    required.append(p.name)
            # Build the OpenAI function envelope.  ``parameters`` is always present
            # (even for zero-parameter tools like get_morning_brief / get_alerts /
            # get_portfolio_context) — OpenAI tolerates an empty properties object.
            function_def: dict[str, Any] = {
                "name": spec.name,
                "description": spec.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
            definitions.append({"type": "function", "function": function_def})
        return definitions

    def load_manifest(self) -> dict[str, Any]:
        """Load and return the raw capability_manifest.yaml for architecture tests.

        Architecture tests use this to assert that every registered tool has a
        corresponding YAML entry (R29: manifest must stay in sync with code).
        """
        with open(_MANIFEST_PATH) as f:
            return yaml.safe_load(f)  # type: ignore[no-any-return]
