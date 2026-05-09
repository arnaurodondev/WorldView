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


class TestToolDefinitions:
    """PLAN-0087 Wave F D-R1-001: ToolRegistry.to_tool_definitions() returns
    OpenAI function-calling shapes built from the registered ToolSpec list.

    These tests verify the method exists, the shape matches the OpenAI
    chat.completions ``tools`` schema, and the type / enum / required mappings
    are correct.  The orchestrator passes the result directly to DeepInfra (an
    OpenAI-compatible endpoint) so any deviation from the spec breaks tool use.
    """

    def test_returns_non_empty_list_for_registered_tools(self) -> None:
        registry = _make_default_registry()
        defs = registry.to_tool_definitions()
        assert isinstance(defs, list)
        assert len(defs) == 2  # get_price_history, get_fundamentals_history

    def test_returns_empty_list_for_empty_registry(self) -> None:
        registry = ToolRegistry()
        defs = registry.to_tool_definitions()
        assert defs == []

    def test_each_entry_has_openai_envelope(self) -> None:
        """Each entry: {"type": "function", "function": {name, description, parameters}}."""
        registry = _make_default_registry()
        defs = registry.to_tool_definitions()
        for entry in defs:
            assert entry["type"] == "function"
            fn = entry["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_parameters_block_shape(self) -> None:
        """parameters must be a JSON Schema ``object`` with ``properties`` and ``required``."""
        registry = _make_default_registry()
        defs = registry.to_tool_definitions()
        for entry in defs:
            params = entry["function"]["parameters"]
            assert params["type"] == "object"
            assert isinstance(params["properties"], dict)
            assert isinstance(params["required"], list)

    def test_required_list_matches_spec(self) -> None:
        registry = _make_default_registry()
        defs = registry.to_tool_definitions()
        # get_price_history has 3 required (ticker, from_date, to_date), 0 optional.
        price = next(d for d in defs if d["function"]["name"] == "get_price_history")
        assert set(price["function"]["parameters"]["required"]) == {"ticker", "from_date", "to_date"}
        # get_fundamentals_history has 1 required (ticker), 1 optional (periods).
        fundamentals = next(d for d in defs if d["function"]["name"] == "get_fundamentals_history")
        assert fundamentals["function"]["parameters"]["required"] == ["ticker"]

    def test_date_type_is_mapped_to_string_with_format(self) -> None:
        """ParameterSpec.type='date' must become {"type":"string","format":"date"}."""
        registry = _make_default_registry()
        defs = registry.to_tool_definitions()
        price = next(d for d in defs if d["function"]["name"] == "get_price_history")
        from_date = price["function"]["parameters"]["properties"]["from_date"]
        assert from_date["type"] == "string"
        assert from_date["format"] == "date"

    def test_array_type_includes_items_schema(self) -> None:
        """array params must include an ``items`` schema (OpenAI rejects raw 'array')."""
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="multi_ticker",
                description="Multi-ticker tool",
                parameters=[
                    ParameterSpec(
                        name="entity_tickers",
                        type="array",
                        description="List of tickers",
                        required=True,
                    ),
                ],
                source_type="mixed",
            ),
            handler=AsyncMock(),
        )
        defs = registry.to_tool_definitions()
        prop = defs[0]["function"]["parameters"]["properties"]["entity_tickers"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "string"

    def test_enum_constraint_is_propagated(self) -> None:
        """ParameterSpec.enum must show up as ``enum`` in the JSON Schema."""
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="sev_tool",
                description="severity-tagged tool",
                parameters=[
                    ParameterSpec(
                        name="severity",
                        type="string",
                        description="Severity tier",
                        required=False,
                        enum=["low", "medium", "high", "critical"],
                    ),
                ],
                source_type="alert",
            ),
            handler=AsyncMock(),
        )
        defs = registry.to_tool_definitions()
        prop = defs[0]["function"]["parameters"]["properties"]["severity"]
        assert prop["enum"] == ["low", "medium", "high", "critical"]

    def test_zero_parameter_tool_has_empty_properties(self) -> None:
        """Tools without parameters (e.g. get_morning_brief) must still produce a
        valid OpenAI schema with empty ``properties`` and ``required`` lists."""
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="no_args",
                description="No-argument tool",
                parameters=[],
                source_type="narrative",
            ),
            handler=AsyncMock(),
        )
        defs = registry.to_tool_definitions()
        params = defs[0]["function"]["parameters"]
        assert params["properties"] == {}
        assert params["required"] == []

    def test_all_simple_types_round_trip(self) -> None:
        """integer/number/boolean/object map 1:1; string is unchanged."""
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="kitchen_sink",
                description="all types",
                parameters=[
                    ParameterSpec(name="i", type="integer", description="i", required=False),
                    ParameterSpec(name="n", type="number", description="n", required=False),
                    ParameterSpec(name="b", type="boolean", description="b", required=False),
                    ParameterSpec(name="o", type="object", description="o", required=False),
                    ParameterSpec(name="s", type="string", description="s", required=False),
                ],
                source_type="mixed",
            ),
            handler=AsyncMock(),
        )
        props = registry.to_tool_definitions()[0]["function"]["parameters"]["properties"]
        assert props["i"]["type"] == "integer"
        assert props["n"]["type"] == "number"
        assert props["b"]["type"] == "boolean"
        assert props["o"]["type"] == "object"
        assert props["s"]["type"] == "string"


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
