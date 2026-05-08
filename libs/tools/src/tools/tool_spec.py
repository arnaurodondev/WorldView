"""Tool specification dataclasses for the LLM tool-use manifest (PLAN-0066 Wave H).

ParameterSpec describes a single parameter accepted by a tool.
ToolSpec describes a complete tool that the LLM can invoke via tool_use blocks.

NOTE (R29): per-tool trust_weight is NOT stored here.  TrustScorer computes it
at retrieval time from SOURCE_AUTHORITY * recency_decay * corroboration *
extraction_confidence. ToolSpec carries source_type so TrustScorer can look up
authority. ToolExecutor handlers set trust_weight at result construction time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, kw_only=True)
class ParameterSpec:
    """Schema for a single parameter in a tool's input signature."""

    name: str
    type: str  # "string" | "date" | "integer"
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    """Full specification for a single LLM-callable tool.

    The LLM sees name + description + parameters in the system prompt section
    rendered by ToolRegistry.to_system_prompt_section().

    source_type is used by TrustScorer to determine trust_weight at retrieval
    time — it is NOT a trust_weight field itself (R29).
    """

    name: str
    description: str
    parameters: list[ParameterSpec]
    # Used by TrustScorer to compute authority weight at query time (R29)
    source_type: str
    # Optional few-shot examples shown to the LLM in the manifest
    example_queries: list[str] = field(default_factory=list)
