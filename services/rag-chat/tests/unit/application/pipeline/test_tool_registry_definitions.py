"""Tests for ``build_default_registry()`` x ``ToolRegistry.to_tool_definitions()``.

PLAN-0087 Wave F D-R1-001 / D-R1-002:

  D-R1-001 — ``ToolRegistry.to_tool_definitions()`` is the new method that emits
  OpenAI function-calling shapes from the registered ``ToolSpec`` list.  The
  orchestrator passes the result directly to DeepInfra (an OpenAI-compatible
  endpoint) so any deviation from the OpenAI ``chat.completions.tools`` shape
  breaks tool use end-to-end.

  D-R1-002 — Before this fix, 18 of the 22 tools registered by
  ``build_default_registry()`` carried ``parameters=[]`` placeholders, so the
  OpenAI tool definitions emitted by D-R1-001 would have been empty even with
  the new method in place.  These tests assert that the live ParameterSpec
  lists match the canonical ``capability_manifest.yaml`` for every tool.

Why these tests live in services/rag-chat (not libs/tools): the registry
content (the tool list and per-tool ParameterSpec rows) is owned by the
service.  The libs/tools side owns the ``to_tool_definitions()`` method shape
itself (covered in libs/tools/tests/test_tool_registry.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from rag_chat.application.pipeline.tool_executor import build_default_registry

pytestmark = pytest.mark.unit


# Path to the canonical YAML manifest in libs/tools.  We load it directly
# rather than via ``ToolRegistry.load_manifest()`` so the test does not depend
# on the registry's loader behaviour — the YAML is the source of truth.
_MANIFEST_PATH = Path(__file__).resolve().parents[6] / "libs/tools/src/tools/capability_manifest.yaml"

# Tools that intentionally carry zero parameters in both YAML and registration.
# WHY this list: ``test_every_tool_has_at_least_yaml_parameter_count`` would
# otherwise fire ``assert >= 1`` for these intentionally empty tools.
_ZERO_PARAM_TOOLS = frozenset({"get_portfolio_context", "get_morning_brief", "get_alerts"})

# Tools the audit (D-R1-002) explicitly called out as "had parameters=[]
# placeholder" before the fix.  We assert each one is now non-empty (or zero
# when intentionally so per _ZERO_PARAM_TOOLS).
_AUDIT_PLACEHOLDER_TOOLS = frozenset(
    {
        "search_documents",
        "get_entity_graph",
        "traverse_graph",
        "search_entity_relations",
        "search_claims",
        "search_events",
        "get_contradictions",
        "get_portfolio_context",
        "get_entity_narrative",
        "get_entity_paths",
        "get_entity_health",
        "get_entity_intelligence",
        "get_morning_brief",
        "compare_entities",
        "screen_universe",
        "get_market_movers",
        "get_economic_calendar",
        "get_earnings_calendar",
        "get_alerts",
        "create_alert",
    }
)


def _load_manifest_tools() -> dict[str, dict]:
    """Return YAML manifest tools indexed by name."""
    with open(_MANIFEST_PATH) as f:
        manifest = yaml.safe_load(f)
    return {t["name"]: t for t in manifest["tools"]}


# ── D-R1-002: ParameterSpec lists mirror capability_manifest.yaml ─────────────


class TestRegistryParameterCoverage:
    """For every tool the registration must carry at least the param NAMES from YAML.

    We do not assert on description/required equality (those are subtly normalised
    in the Python registration — e.g. quote style differs).  The critical
    invariant is: the LLM that consumes ``to_tool_definitions()`` sees the same
    set of parameter names per tool as the source-of-truth YAML.
    """

    def test_registry_has_all_22_tools(self) -> None:
        # PLAN-0095 W2 T-W2-02 bumped the count to 23 (added
        # ``get_fundamentals_history_batch``). PLAN-0103 W2 added
        # ``get_entity_news`` → 24. PLAN-0104 W32 added ``query_fundamentals``
        # → 25. Method name kept for grep parity.
        registry = build_default_registry()
        names = {s.name for s in registry.all_specs()}
        # PLAN-0112 W4 bumped 25 → 26 by adding ``get_path_between`` (pairwise).
        # Chat prediction-market tool bumped 26 → 27 by adding ``get_prediction_markets``.
        assert len(names) == 27, f"Expected 27 tools, got {len(names)}: {sorted(names)}"

    def test_every_audit_placeholder_tool_now_carries_params_or_is_zero_param(self) -> None:
        """D-R1-002: 18 placeholder tools were filled in; 3 intentionally zero-arg."""
        registry = build_default_registry()
        specs = {s.name: s for s in registry.all_specs()}
        for tool_name in _AUDIT_PLACEHOLDER_TOOLS:
            assert tool_name in specs, f"{tool_name} not registered"
            spec = specs[tool_name]
            if tool_name in _ZERO_PARAM_TOOLS:
                assert (
                    spec.parameters == []
                ), f"{tool_name} expected to be zero-arg but has params {[p.name for p in spec.parameters]}"
            else:
                assert spec.parameters, (
                    f"{tool_name} still has empty parameters — D-R1-002 regression. "
                    "build_default_registry() must mirror capability_manifest.yaml."
                )

    @pytest.mark.parametrize(
        "tool_name",
        ["get_morning_brief", "get_entity_narrative", "compare_entities", "get_market_movers", "screen_universe"],
    )
    def test_representative_tool_param_names_match_yaml(self, tool_name: str) -> None:
        """Representative-sample tools' param NAMES must equal YAML param names."""
        manifest = _load_manifest_tools()
        registry = build_default_registry()
        spec = registry.get_spec(tool_name)
        assert spec is not None
        yaml_param_names = {p["name"] for p in (manifest[tool_name].get("parameters") or [])}
        registered_param_names = {p.name for p in spec.parameters}
        assert (
            registered_param_names == yaml_param_names
        ), f"{tool_name}: YAML params {yaml_param_names} != registered {registered_param_names}"

    def test_create_alert_and_get_price_history_required_flags_match_yaml(self) -> None:
        """Required-flag invariants for the two action / data tools that the
        chat surface relies on most heavily (create_alert + get_price_history)."""
        manifest = _load_manifest_tools()
        registry = build_default_registry()
        for tool_name in ("create_alert", "get_price_history"):
            spec = registry.get_spec(tool_name)
            assert spec is not None
            yaml_required = {p["name"] for p in manifest[tool_name]["parameters"] if p.get("required")}
            reg_required = {p.name for p in spec.parameters if p.required}
            assert reg_required == yaml_required, f"{tool_name} required mismatch"


# ── D-R1-001: to_tool_definitions() over the production registry ──────────────


class TestProductionRegistryToolDefinitions:
    """Exercise ``to_tool_definitions()`` against the LIVE ``build_default_registry()``.

    These tests would have failed (returned ``[]`` or ``AttributeError``) before
    PLAN-0087 Wave F when the method existed only as a test mock.
    """

    def test_returns_22_definitions(self) -> None:
        # PLAN-0095 W2 T-W2-02: 23 after adding get_fundamentals_history_batch.
        # PLAN-0103 W2: 24 after adding get_entity_news.
        # PLAN-0104 W32: 25 after adding query_fundamentals.
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        # PLAN-0112 W4: 26 after adding get_path_between.
        # Chat prediction-market tool: 27 after adding get_prediction_markets.
        assert len(defs) == 27

    def test_every_definition_has_openai_envelope(self) -> None:
        registry = build_default_registry()
        for entry in registry.to_tool_definitions():
            assert entry["type"] == "function"
            fn = entry["function"]
            assert isinstance(fn["name"], str) and fn["name"]
            assert isinstance(fn["description"], str) and fn["description"]
            assert fn["parameters"]["type"] == "object"
            assert isinstance(fn["parameters"]["properties"], dict)
            assert isinstance(fn["parameters"]["required"], list)

    def test_all_22_tool_names_present(self) -> None:
        """Audit §1 lists all 22 tools — every one must be in the OpenAI definitions."""
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        names = {entry["function"]["name"] for entry in defs}
        expected = {
            "get_price_history",
            "get_fundamentals_history",
            "search_documents",
            "get_entity_graph",
            "traverse_graph",
            "search_entity_relations",
            "search_claims",
            "search_events",
            "get_contradictions",
            "get_portfolio_context",
            "get_entity_narrative",
            "get_entity_paths",
            "get_entity_health",
            "get_entity_intelligence",
            "get_morning_brief",
            "compare_entities",
            "screen_universe",
            "get_market_movers",
            "get_economic_calendar",
            "get_earnings_calendar",
            "get_alerts",
            "create_alert",
            # PLAN-0095 W2 T-W2-02
            "get_fundamentals_history_batch",
            # PLAN-0103 W2
            "get_entity_news",
            # PLAN-0104 W32
            "query_fundamentals",
            # PLAN-0112 W4
            "get_path_between",
            # Chat prediction-market tool
            "get_prediction_markets",
        }
        assert names == expected, f"Missing: {expected - names}; Extra: {names - expected}"

    def test_create_alert_enums_propagate_to_openai_schema(self) -> None:
        """The PLAN-0082 allowlists are encoded as ``enum`` in JSON Schema."""
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        create_alert = next(d for d in defs if d["function"]["name"] == "create_alert")
        props = create_alert["function"]["parameters"]["properties"]
        assert set(props["condition"]["enum"]) == {
            "price_below",
            "price_above",
            "volume_spike",
            "percent_change",
        }
        assert set(props["severity"]["enum"]) == {"low", "medium", "high", "critical"}

    def test_search_documents_array_param_has_items_schema(self) -> None:
        """Array params must include ``items`` (OpenAI rejects raw 'array')."""
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        sd = next(d for d in defs if d["function"]["name"] == "search_documents")
        prop = sd["function"]["parameters"]["properties"]["entity_tickers"]
        assert prop["type"] == "array"
        assert prop["items"]["type"] == "string"

    def test_zero_arg_tools_emit_valid_empty_object_schema(self) -> None:
        """get_morning_brief / get_alerts / get_portfolio_context have empty
        ``properties`` and ``required`` but a valid ``object`` schema."""
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        for name in _ZERO_PARAM_TOOLS:
            entry = next(d for d in defs if d["function"]["name"] == name)
            params = entry["function"]["parameters"]
            assert params["type"] == "object"
            assert params["properties"] == {}
            assert params["required"] == []

    def test_get_price_history_interval_enum_excludes_week_and_month(self) -> None:
        """Chat-eval #5 root cause A: backend /ohlcv/bars has no week/month grain.

        Advertising them made the LLM pick week/month for "YTD high/low" and
        "P/E vs history" questions and burn iterations retrying on error. The
        enum the LLM sees must only carry supported grains.
        """
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        gph = next(d for d in defs if d["function"]["name"] == "get_price_history")
        interval_enum = gph["function"]["parameters"]["properties"]["interval"]["enum"]
        assert set(interval_enum) == {"1m", "hour", "day"}
        assert "week" not in interval_enum
        assert "month" not in interval_enum

    def test_get_price_history_date_params_have_format_date(self) -> None:
        """The orchestrator relies on the LLM emitting YYYY-MM-DD; format=date hints that."""
        registry = build_default_registry()
        defs = registry.to_tool_definitions()
        gph = next(d for d in defs if d["function"]["name"] == "get_price_history")
        from_date = gph["function"]["parameters"]["properties"]["from_date"]
        to_date = gph["function"]["parameters"]["properties"]["to_date"]
        assert from_date["type"] == "string" and from_date["format"] == "date"
        assert to_date["type"] == "string" and to_date["format"] == "date"
