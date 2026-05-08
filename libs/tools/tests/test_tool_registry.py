"""Unit tests for ToolRegistry and capability_manifest.yaml (PLAN-0066 Wave H T-W10-H-01).

Tests:
- test_registry_get_spec_returns_registered_tool
- test_registry_get_spec_unknown_returns_none
- test_registry_to_system_prompt_section_contains_tool_names
- test_manifest_yaml_has_entry_for_every_registered_tool
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from tools.tool_registry import ToolRegistry
from tools.tool_spec import ParameterSpec, ToolSpec

pytestmark = pytest.mark.unit


def _make_spec(name: str = "my_tool", source_type: str = "ohlcv") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"Test tool: {name}",
        parameters=[ParameterSpec(name="ticker", type="string", description="Ticker symbol", required=True)],
        source_type=source_type,
        example_queries=[f"Query for {name}"],
    )


def _make_default_registry() -> ToolRegistry:
    """Build a registry with both production tools registered."""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="get_price_history",
            description="Fetches OHLCV history for a ticker",
            parameters=[
                ParameterSpec(name="ticker", type="string", description="Ticker", required=True),
                ParameterSpec(name="from_date", type="date", description="Start date", required=True),
                ParameterSpec(name="to_date", type="date", description="End date", required=True),
            ],
            source_type="ohlcv",
        ),
        handler=AsyncMock(return_value=None),
    )
    registry.register(
        ToolSpec(
            name="get_fundamentals_history",
            description="Fetches quarterly fundamentals for a ticker",
            parameters=[
                ParameterSpec(name="ticker", type="string", description="Ticker", required=True),
                ParameterSpec(name="periods", type="integer", description="Number of quarters", required=False),
            ],
            source_type="fundamentals",
        ),
        handler=AsyncMock(return_value=None),
    )
    return registry


class TestToolRegistryGetSpec:
    def test_registry_get_spec_returns_registered_tool(self) -> None:
        """A tool spec registered by name should be retrievable by name."""
        registry = ToolRegistry()
        spec = _make_spec("alpha_tool")
        registry.register(spec, handler=AsyncMock())

        result = registry.get_spec("alpha_tool")

        assert result is not None
        assert result.name == "alpha_tool"
        assert result.source_type == "ohlcv"

    def test_registry_get_spec_unknown_returns_none(self) -> None:
        """Looking up an unregistered tool name should return None (no KeyError)."""
        registry = ToolRegistry()
        registry.register(_make_spec("real_tool"), handler=AsyncMock())

        result = registry.get_spec("nonexistent_tool")

        assert result is None

    def test_registry_all_specs_returns_all_registered(self) -> None:
        """all_specs() should return all registered tools in order."""
        registry = ToolRegistry()
        registry.register(_make_spec("tool_a"), handler=AsyncMock())
        registry.register(_make_spec("tool_b"), handler=AsyncMock())

        specs = registry.all_specs()

        assert len(specs) == 2
        assert {s.name for s in specs} == {"tool_a", "tool_b"}

    def test_registry_get_handler_returns_callable(self) -> None:
        """get_handler() should return the registered handler callable."""
        mock_handler = AsyncMock(return_value=None)
        registry = ToolRegistry()
        registry.register(_make_spec(), handler=mock_handler)

        result = registry.get_handler("my_tool")

        assert result is mock_handler


class TestSystemPromptSection:
    def test_registry_to_system_prompt_section_contains_tool_names(self) -> None:
        """to_system_prompt_section() must include both registered tool names."""
        registry = _make_default_registry()

        section = registry.to_system_prompt_section()

        assert "get_price_history" in section
        assert "get_fundamentals_history" in section

    def test_system_prompt_section_is_fenced_yaml(self) -> None:
        """to_system_prompt_section() must produce a fenced ```yaml block."""
        registry = _make_default_registry()

        section = registry.to_system_prompt_section()

        assert "```yaml" in section
        assert section.rstrip().endswith("```")

    def test_system_prompt_section_includes_tool_description_prefix(self) -> None:
        """Section should include at least the first 200 chars of each description."""
        registry = ToolRegistry()
        spec = ToolSpec(
            name="my_special_tool",
            description="A very specific and detailed tool description.",
            parameters=[],
            source_type="ohlcv",
        )
        registry.register(spec, handler=AsyncMock())

        section = registry.to_system_prompt_section()

        assert "A very specific and detailed tool description." in section


class TestManifestArchitecture:
    def test_manifest_yaml_has_entry_for_every_registered_tool(self) -> None:
        """Architecture invariant: capability_manifest.yaml must have an entry
        for every tool name in a default registry. This test prevents silent
        manifest drift when new tools are added to the registry without updating
        the YAML (R29).
        """
        registry = _make_default_registry()
        manifest = registry.load_manifest()

        manifest_tool_names = {t["name"] for t in manifest.get("tools", [])}
        registered_tool_names = {s.name for s in registry.all_specs()}

        # Every registered tool must appear in the YAML manifest
        missing = registered_tool_names - manifest_tool_names
        assert not missing, (
            f"Tools registered but missing from capability_manifest.yaml: {missing}. "
            "Update libs/tools/src/tools/capability_manifest.yaml (R29)."
        )

    def test_manifest_yaml_is_valid_and_has_version(self) -> None:
        """capability_manifest.yaml must parse as valid YAML with a version field."""
        registry = ToolRegistry()  # fresh empty registry — just need load_manifest()
        manifest = registry.load_manifest()

        assert "version" in manifest
        assert "tools" in manifest
        assert isinstance(manifest["tools"], list)
        assert len(manifest["tools"]) >= 2  # at least the two temporal tools

    def test_manifest_yaml_tools_have_required_fields(self) -> None:
        """Every YAML entry must have name, description, parameters, source_type."""
        registry = ToolRegistry()
        manifest = registry.load_manifest()

        for entry in manifest.get("tools", []):
            assert "name" in entry, f"Tool entry missing 'name': {entry}"
            assert "description" in entry, f"Tool {entry.get('name')} missing 'description'"
            assert "source_type" in entry, f"Tool {entry.get('name')} missing 'source_type'"
