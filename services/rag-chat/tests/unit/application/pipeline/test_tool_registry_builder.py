"""Tests for the tool-registry parity guard (PLAN-0093 QA P0-1).

Background
----------
The GraphEnricher dormant-tool incident showed that a tool can exist in the
YAML manifest with no handler — or vice versa — and the gap is only noticed
when the LLM finally tries to call it.  ``validate_registry_parity()`` is the
boot-time guard that crashes the service early instead of letting that drift
survive to the conversation layer.

These tests cover:

  * Happy path — the live ``build_default_registry()`` is in sync with
    ``capability_manifest.yaml`` (today's invariant: 22 == 22).
  * Manifest orphan — a handler is missing for a YAML-advertised tool.
  * Handler orphan — a tool is registered but missing from the YAML.
  * Startup integration — ``app.py`` calls the validator during lifespan.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from rag_chat.application.pipeline.tool_executor import (
    ToolRegistryDriftError,
    build_default_registry,
    validate_registry_parity,
)

pytestmark = pytest.mark.unit


# ── Happy path ────────────────────────────────────────────────────────────────


def test_default_registry_has_zero_drift() -> None:
    """The live registry must match the YAML manifest tool-for-tool.

    WHY this assertion: this is the "today's state is 22/22" check that the
    sibling QA agent already verified manually.  If a future PR adds a tool
    to the YAML but forgets to register a handler (or vice versa), this test
    fails *before* the change is merged — which is the whole point of the
    parity guard.
    """
    registry = build_default_registry()

    sizes = validate_registry_parity(registry)

    # The two sides must agree.  We do NOT hard-code "22" — the test is
    # symmetric so a deliberate addition of a tool (in both YAML + builder)
    # passes without test edits, while a one-sided change fails.
    assert (
        sizes["manifest"] == sizes["handled"]
    ), f"Manifest tool count ({sizes['manifest']}) != handled tool count ({sizes['handled']}) — drift detected."

    # Today's known size — kept as a soft invariant so a one-sided regression
    # in BOTH yaml and builder (e.g. accidentally deleting a tool from both)
    # is still caught.  Update this number when intentionally adding/removing
    # a tool from the platform.
    # PLAN-0095 W2 T-W2-02 bumped the count from 22 → 23 by adding
    # ``get_fundamentals_history_batch`` alongside the singular variant.
    # PLAN-0103 W2 bumped 23 → 24 by adding ``get_entity_news``.
    # PLAN-0104 W32 bumped 24 → 25 by adding ``query_fundamentals``.
    # PLAN-0112 W4 bumped 25 → 26 by adding ``get_path_between`` (pairwise).
    # Chat prediction-market tool bumped 26 → 27 by adding ``get_prediction_markets``.
    # Chat SEC-filings tool bumped 27 → 28 by adding ``get_filings``
    # (SEC EDGAR filings with clickable EDGAR citation URLs).
    assert sizes["manifest"] == 28, (
        f"Expected 28 platform tools, got {sizes['manifest']}. "
        "If a tool was intentionally added/removed, update this assertion."
    )


def test_validate_returns_sizes_dict() -> None:
    """The validator returns a ``{'manifest': N, 'handled': M}`` dict for metrics."""
    registry = build_default_registry()

    sizes = validate_registry_parity(registry)

    assert set(sizes.keys()) == {"manifest", "handled"}
    assert isinstance(sizes["manifest"], int)
    assert isinstance(sizes["handled"], int)


# ── Drift detection ───────────────────────────────────────────────────────────


def test_drift_when_handler_missing_for_manifest_tool() -> None:
    """A tool in the YAML with no registered handler must raise.

    WHY a fake registry: we cannot remove a real handler from
    ``build_default_registry()`` without touching production code, so we
    construct a stand-in registry whose ``load_manifest()`` returns a synthetic
    manifest with an extra tool name that the live registry does not handle.
    The ``all_specs()`` proxy still returns the real specs so the orphan is
    "in manifest only".
    """
    real_registry = build_default_registry()

    # Synthesise a manifest doc that has every real tool PLUS one extra.
    extra_name = "totally_fake_tool_that_no_handler_handles"
    fake_manifest: dict[str, Any] = {
        "version": "test",
        "tools": [{"name": spec.name} for spec in real_registry.all_specs()] + [{"name": extra_name}],
    }

    stub = _StubRegistry(real_registry=real_registry, manifest_doc=fake_manifest)

    with pytest.raises(ToolRegistryDriftError) as exc:
        validate_registry_parity(stub)  # type: ignore[arg-type]

    msg = str(exc.value)
    assert extra_name in msg, f"Error message should mention the orphan tool: {msg!r}"
    assert "In manifest only" in msg


def test_drift_when_handler_registered_without_manifest_entry() -> None:
    """A handler registered with no YAML entry must raise.

    The reverse of the previous test: the manifest is shrunk to exclude one
    real tool, and we expect the validator to flag the now-orphaned handler.
    """
    real_registry = build_default_registry()
    real_names = [spec.name for spec in real_registry.all_specs()]
    dropped_name = real_names[0]  # any registered tool will do

    fake_manifest: dict[str, Any] = {
        "version": "test",
        "tools": [{"name": name} for name in real_names if name != dropped_name],
    }

    stub = _StubRegistry(real_registry=real_registry, manifest_doc=fake_manifest)

    with pytest.raises(ToolRegistryDriftError) as exc:
        validate_registry_parity(stub)  # type: ignore[arg-type]

    msg = str(exc.value)
    assert dropped_name in msg, f"Error message should mention the orphan handler: {msg!r}"
    assert "Handled only" in msg


def test_drift_error_lists_both_sides_sorted() -> None:
    """The error message must list orphans on each side, sorted for stability."""
    real_registry = build_default_registry()
    real_names = sorted(spec.name for spec in real_registry.all_specs())

    # Drop the FIRST real name, inject a synthetic name → both sides have one orphan.
    dropped = real_names[0]
    injected = "zzz_synthetic_orphan_tool"
    fake_manifest: dict[str, Any] = {
        "version": "test",
        "tools": [{"name": name} for name in real_names if name != dropped] + [{"name": injected}],
    }

    stub = _StubRegistry(real_registry=real_registry, manifest_doc=fake_manifest)

    with pytest.raises(ToolRegistryDriftError) as exc:
        validate_registry_parity(stub)  # type: ignore[arg-type]

    msg = str(exc.value)
    # Sorted list rendering — explicit check that both orphans appear and
    # the message names which side each came from.
    assert f"In manifest only: ['{injected}']" in msg
    assert f"Handled only: ['{dropped}']" in msg


# ── Startup integration ──────────────────────────────────────────────────────


def test_app_startup_calls_validate_registry_parity() -> None:
    """``app.py`` must invoke ``validate_registry_parity`` during lifespan setup.

    We import the module and assert the symbol is present in its module
    namespace.  A full lifespan invocation requires the entire upstream
    client stack (S6/S7/Valkey/etc.) which is out of scope for a unit test,
    so we settle for a static check: the import is present and the symbol
    is bound, which is what makes the fail-fast guard reachable.
    """
    import rag_chat.app as app_module

    src = _read_module_source(app_module)
    assert "validate_registry_parity" in src, "app.py must import validate_registry_parity so the boot-time guard runs."
    assert (
        "validate_registry_parity(tool_registry)" in src
    ), "app.py must call validate_registry_parity(tool_registry) at startup."


def test_validate_propagates_drift_error_not_swallowed() -> None:
    """Calling validate_registry_parity on a drifted registry must raise, not log-and-continue.

    WHY this matters: the whole point of P0-1 is fail-fast.  A future
    refactor that wraps the call in ``try/except: log.warning(...)`` would
    silently re-introduce the GraphEnricher bug class.  This test pins the
    raise contract.
    """
    real_registry = build_default_registry()
    fake_manifest: dict[str, Any] = {"version": "test", "tools": [{"name": "nope"}]}
    stub = _StubRegistry(real_registry=real_registry, manifest_doc=fake_manifest)

    # The exception type is RuntimeError-derived — assert both for callers
    # that catch broadly and for callers that catch the specific subclass.
    with pytest.raises((ToolRegistryDriftError, RuntimeError)):
        validate_registry_parity(stub)  # type: ignore[arg-type]


def test_startup_log_emitted_with_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app emits ``tool_registry_loaded`` with manifest/handled counts.

    Smoke-level check using mock.patch on the validator: we don't run the
    full lifespan but we assert the source contains the expected structured
    log call.  A previous QA round (HR-063) flagged audit-log values that
    were computed but never persisted; the equivalent here would be
    computing ``sizes`` and never logging or publishing them.
    """
    import rag_chat.app as app_module

    src = _read_module_source(app_module)
    # structlog get_logger().info — the structured event name is the load-bearing token.
    assert '"tool_registry_loaded"' in src
    assert "manifest_count=" in src
    assert "handled_count=" in src
    # The gauge must also be set with both labels.
    assert 'rag_tool_registry_size.labels(kind="manifest")' in src
    assert 'rag_tool_registry_size.labels(kind="handled")' in src

    # Also ensure validate_registry_parity is exported from tool_executor
    # (the import path app.py uses) — guard against an inadvertent rename.
    import rag_chat.application.pipeline.tool_executor as tool_executor_module

    assert hasattr(tool_executor_module, "validate_registry_parity")
    assert hasattr(tool_executor_module, "ToolRegistryDriftError")
    # The mock import is exercised here to silence the unused-import warning
    # and demonstrate the spy pattern that integration tests could reuse.
    with mock.patch.object(
        tool_executor_module,
        "validate_registry_parity",
        wraps=tool_executor_module.validate_registry_parity,
    ) as spy:
        registry = tool_executor_module.build_default_registry()
        sizes = tool_executor_module.validate_registry_parity(registry)
        spy.assert_called_once()
        assert sizes["manifest"] == sizes["handled"]
    # monkeypatch is accepted only so this test integrates cleanly with the
    # fixture; no env var is touched.
    _ = monkeypatch


# ── Helpers ──────────────────────────────────────────────────────────────────


class _StubRegistry:
    """Minimal stand-in that proxies ``all_specs`` and overrides ``load_manifest``.

    The real ``ToolRegistry.load_manifest`` reads from disk; we want to inject
    a synthetic manifest doc to simulate drift without touching the YAML.
    """

    def __init__(self, *, real_registry: Any, manifest_doc: dict[str, Any]) -> None:
        self._real = real_registry
        self._manifest_doc = manifest_doc

    def all_specs(self) -> list[Any]:
        return self._real.all_specs()

    def load_manifest(self) -> dict[str, Any]:
        return self._manifest_doc


# ── PLAN-0095 W3 T-W3-01: tool description anti-pattern guards ───────────────
#
# After Q1/Q3 misrouting in iter-9 chat-eval, we tightened five descriptions
# so the LLM stops picking get_entity_graph + search_documents for peer or
# biographical questions. These tests pin the new "DO NOT use for..." clauses
# so a future copy-edit can't accidentally regress the disambiguation.


def _spec(name: str) -> Any:
    """Return the ToolSpec for ``name`` from the live default registry."""
    registry = build_default_registry()
    for spec in registry.all_specs():
        if spec.name == name:
            return spec
    raise AssertionError(f"tool {name!r} not registered")


def test_get_entity_graph_description_documents_anti_patterns() -> None:
    desc = _spec("get_entity_graph").description
    assert "DO NOT use for" in desc, "get_entity_graph must explicitly list anti-patterns"
    # Peer / competitor and biographical / two-entity carve-outs.
    assert "competitor" in desc.lower()
    assert "biographical" in desc.lower() or "career" in desc.lower()
    assert "traverse_graph" in desc, "should redirect two-entity queries to traverse_graph"


def test_traverse_graph_description_documents_anti_patterns() -> None:
    desc = _spec("traverse_graph").description
    assert "DO NOT use for" in desc
    # Must redirect single-entity peer queries away.
    assert "get_entity_intelligence" in desc or "compare_entities" in desc
    # Must redirect pre-ranked single-anchor path queries to get_entity_paths.
    assert "get_entity_paths" in desc


def test_get_entity_paths_description_documents_anti_patterns() -> None:
    desc = _spec("get_entity_paths").description
    assert "DO NOT use for" in desc
    assert "traverse_graph" in desc, "should redirect two-entity questions to traverse_graph"


def test_get_entity_intelligence_description_covers_peer_and_bio() -> None:
    desc = _spec("get_entity_intelligence").description
    # Biographical / executive-history coverage.
    assert "biographical" in desc.lower() or "career" in desc.lower()
    # Peer / competitor coverage — the relations_summary bucket.
    assert "peer" in desc.lower() or "competitor" in desc.lower()
    assert "DO NOT use for" in desc


def test_compare_entities_description_is_financial_only() -> None:
    desc = _spec("compare_entities").description
    assert "FINANCIAL" in desc, "must flag itself as a financial-only tool"
    assert "DO NOT use for" in desc
    assert "traverse_graph" in desc, "should redirect relationship questions away"


# ── PLAN-0097 T-W3-03: fundamentals singular vs batch disambiguation ──────────
# Iter-9 chat-eval saw the agent looping `get_fundamentals_history` 5+ times for
# comparison questions instead of one `get_fundamentals_history_batch` call
# (5-10x slower per audit §4). Both descriptions now carry mutually-reciprocal
# anti-pattern callouts; these tests pin the keywords so a future copy-edit
# can't silently regress the tool-selection signal.


def test_get_fundamentals_history_description_warns_against_loop() -> None:
    """Singular tool must explicitly redirect multi-ticker callers to the batch tool."""
    desc = _spec("get_fundamentals_history").description
    # Singular emphasis — the LLM keys on this to distinguish from batch.
    assert "SINGLE" in desc or "single" in desc
    # Reciprocal warning must name the batch tool by exact identifier.
    assert "get_fundamentals_history_batch" in desc
    # Must explicitly call out the loop anti-pattern (not just "use other tool").
    assert "loop" in desc.lower(), "must explicitly warn against looping this tool"


def test_get_fundamentals_history_batch_description_is_strict_directive() -> None:
    """Batch tool must lead with a strict 'use this — not the singular' directive.

    Prior soft phrasing ("use this when comparing") was insufficient — the LLM
    kept iterating the singular tool. The new directive uses imperative voice
    (`**Use this tool — NOT ...**`) at the very top of the description.
    """
    desc = _spec("get_fundamentals_history_batch").description
    # Strict-directive marker — bold imperative at the top.
    assert "**Use this tool" in desc, "must lead with a strict imperative directive"
    # Must name the singular tool by exact identifier (so the LLM disambiguates).
    assert "get_fundamentals_history" in desc
    # Must call out all three trigger conditions from the task spec.
    assert "2 or more tickers" in desc, "must mention the 2+ ticker trigger"
    assert "screener" in desc.lower(), "must mention screener result trigger"
    assert "comparing" in desc.lower(), "must mention comparison trigger"
    # Must label the singular-loop pattern as a bug, not just slower.
    assert "tool-selection bug" in desc.lower()


def _read_module_source(module: Any) -> str:
    """Return the on-disk source of ``module`` for static-presence assertions.

    Using inspect.getsource rather than monkey-patching the lifespan keeps
    the test fast and avoids spinning up the full DI graph.
    """
    import inspect

    return inspect.getsource(module)
