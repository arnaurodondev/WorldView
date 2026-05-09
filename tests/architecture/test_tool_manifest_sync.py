"""Architecture test: capability_manifest.yaml must stay in sync with build_default_registry() (R29).

WHY: If a tool is registered in the YAML but not in build_default_registry(), the LLM can never
invoke it (the system-prompt section is built from the Python registry, not YAML — see
ToolRegistry.to_system_prompt_section()). And vice versa: a handler with no YAML entry is
invisible to the LLM. This test enforces bidirectional sync.

See BP-435: architecture tests cited in plans but never created → rule silently unenforced.

PYTHONPATH setup: rag_chat and tools are not on the default arch-test path (which targets
the repo root only). We add the service src and tools lib src paths here so this test can
import both without requiring a full service install — the same approach used by the service's
own unit tests (which activate the service venv). This is intentional: arch tests must be
able to import the module under test without spinning up infrastructure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── Path setup — add rag_chat + tools lib to sys.path ────────────────────────
# WHY: Architecture tests run from the repo root testpath where service src is not
# on sys.path. We add both the rag-chat src directory and the tools lib src directory
# so that `from rag_chat...` and `from tools...` resolve without a full install.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RAG_CHAT_SRC = _REPO_ROOT / "services" / "rag-chat" / "src"
_TOOLS_LIB_SRC = _REPO_ROOT / "libs" / "tools" / "src"

for _path in [str(_RAG_CHAT_SRC), str(_TOOLS_LIB_SRC)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

pytestmark = pytest.mark.unit


def test_manifest_yaml_tools_registered_in_build_default_registry() -> None:
    """Every tool name in capability_manifest.yaml must appear in build_default_registry()."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

    registry = build_default_registry()
    registered_names = {spec.name for spec in registry.all_specs()}

    tool_registry = ToolRegistry()
    manifest = tool_registry.load_manifest()
    yaml_names = {tool["name"] for tool in manifest.get("tools", [])}

    missing_from_registry = yaml_names - registered_names
    assert not missing_from_registry, (
        f"Tools in capability_manifest.yaml but NOT in build_default_registry(): "
        f"{missing_from_registry}. "
        f"Add them to build_default_registry() or the LLM can never invoke them."
    )


def test_build_default_registry_tools_in_manifest_yaml() -> None:
    """Every tool registered in build_default_registry() must appear in capability_manifest.yaml."""
    from rag_chat.application.pipeline.tool_executor import build_default_registry
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

    registry = build_default_registry()
    registered_names = {spec.name for spec in registry.all_specs()}

    tool_registry = ToolRegistry()
    manifest = tool_registry.load_manifest()
    yaml_names = {tool["name"] for tool in manifest.get("tools", [])}

    missing_from_yaml = registered_names - yaml_names
    assert not missing_from_yaml, (
        f"Tools registered in build_default_registry() but NOT in capability_manifest.yaml: "
        f"{missing_from_yaml}. "
        f"Add them to the YAML or remove the registration."
    )


def test_manifest_version_is_string() -> None:
    """capability_manifest.yaml top-level version must be a string (not an int)."""
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

    tool_registry = ToolRegistry()
    manifest = tool_registry.load_manifest()
    assert isinstance(manifest.get("version"), str), (
        "capability_manifest.yaml 'version' field must be a string (e.g. '2'), not an int. "
        "YAML without quotes parses integers as int, not str."
    )


def test_each_tool_has_required_fields() -> None:
    """Each tool entry in capability_manifest.yaml must have name, description, since, and example_queries."""
    from tools.tool_registry import ToolRegistry  # type: ignore[import-untyped]

    tool_registry = ToolRegistry()
    manifest = tool_registry.load_manifest()
    required_fields = {"name", "description", "since", "example_queries"}

    for tool in manifest.get("tools", []):
        tool_name = tool.get("name", "<unnamed>")
        missing = required_fields - set(tool.keys())
        assert not missing, f"Tool '{tool_name}' in capability_manifest.yaml is missing required fields: {missing}"
        assert (
            len(tool.get("example_queries", [])) >= 2
        ), f"Tool '{tool_name}' must have at least 2 example_queries (R29)"
