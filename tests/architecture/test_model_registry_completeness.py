"""Registry-completeness architecture test (closes the BP-715/BP-294/BP-272 gap).

``ml_clients.model_registry.PLATFORM_MODEL_REGISTRY`` is a hand-maintained tuple
that mirrors every service's ``config.py`` model-id defaults (see that module's
docstring: "Keeping this list in sync (drift guard)"). The existing CI gate,
``libs/ml-clients/tests/test_priceability_guardrail.py::test_all_configured_models_priceable``,
only iterates the pairs ALREADY in the registry — it can never notice a model
that is configured in a service's ``config.py`` but was never appended to the
registry. That is exactly the shape of BP-715/BP-294/BP-272 (LLM calls silently
logged at $0): a new model ships, nobody remembers to enroll it, and the
"is every configured model priceable?" question is answered against a stale
list instead of reality.

This test closes that gap from the OTHER direction: instead of trusting the
registry as the source of truth, it independently re-derives "every model-id
field configured across the platform" by walking each service's (and
libs/ml-clients') ``config.py`` Settings class via AST, and asserts:

  1. (REG-FIELD-MISSING) every model-shaped field found in config.py has a
     corresponding ``(service, field)`` entry in ``PLATFORM_MODEL_REGISTRY``
     — i.e. nothing configures a model without ever being enrolled.
  2. (REG-VALUE-STALE) for every field that IS enrolled, the registry's
     recorded ``model_id`` still matches the field's current default in
     config.py — i.e. the registry has not silently drifted out of sync with
     a model swap (a live example of this existed in rag-chat: ``completion_model``'s
     default moved from ``deepseek-ai/DeepSeek-V4-Flash-Thinking`` to
     ``openai/gpt-oss-120b`` per DEF-035, while the registry still recorded the
     old value).

Deliberately does NOT try to infer the *provider* from the field name (an
inherently fragile heuristic — e.g. ``extraction_fallback_model_id`` has no
"api"/"ollama" hint in its name yet is DeepInfra-served). Field-name presence
in the registry is what the failure mode actually needs: a human enrolling a
new field also records its provider, so cross-checking on ``(service, field)``
identity is both sufficient to catch the drift and immune to provider-guessing
false positives.

Known scope limitation (by design, not an oversight): this AST scan only
walks ``*Settings`` classes inside a service's top-level ``config.py``. Four
``PLATFORM_MODEL_REGISTRY`` entries do NOT correspond to a scannable
``config.py`` Settings attribute and are therefore never matched by either
assertion (they simply never appear in ``configured``/``configured_by_key`` —
neither test flags them, but neither test can catch drift in them either):
``("nlp-pipeline", "EntailmentCheckConfig.model_id", ...)`` (a nested
dataclass field in ``application/blocks/deep_extraction.py``, not a Settings
class), ``("api-gateway", "_NL_SCREENER_MODEL", ...)`` (a module-level
constant in ``routes/market.py``), ``("knowledge-graph",
"description_gemini (adapter default)", ...)`` and ``("rag-chat", "reranker
(Cohere adapter)", ...)`` (adapter-internal defaults, not Settings fields —
their field name is deliberately non-identifier-shaped as a signal of this).
Extending the scanner to also catch these would require walking arbitrary
non-Settings classes/module constants across the whole services tree, which
reintroduces the same fragile-heuristic problem this test avoids for
providers. Left as a documented gap rather than a false sense of coverage.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from ml_clients.model_registry import PLATFORM_MODEL_REGISTRY

from tests.architecture._utils import REPO_ROOT, discover_services

pytestmark = pytest.mark.unit

# Field-naming convention observed across every service's config.py: a model
# identifier field is named exactly "model"/"model_id" or ends with
# "_model"/"_model_id" (see model_registry.py's own docstring: "The ``field``
# column names the settings attribute so the source is greppable").
_MODEL_FIELD_RE = re.compile(r"(^model$|^model_id$|.*_model$|.*_model_id$)")

# libs/ml-clients has its own config.py (shared across services) but is not a
# `services/` package discoverable via discover_services() — handled explicitly.
_ML_CLIENTS_CONFIG = REPO_ROOT / "libs" / "ml-clients" / "src" / "ml_clients" / "config.py"


@dataclass(frozen=True)
class ConfiguredModelField:
    """One model-shaped ``Settings`` field discovered in a config.py by AST scan."""

    service: str
    field: str
    default_value: str
    file: str
    line: int


def _extract_string_default(value_node: ast.expr | None) -> str | None:
    """Return the literal string default of a Settings field, or None.

    Handles both a bare literal (``x: str = "foo"``) and the pydantic
    ``Field(default=...)`` form. Returns None when there is no default, the
    default is ``None``, the default is empty (``""`` — treated as "not
    configured", matching the ``extraction_fallback_model_id`` /
    ``grounding_rewrite_model`` "disabled" convention used across this repo),
    or the default is not a plain string literal (e.g. an expression) — such
    fields cannot be verified statically and are skipped rather than
    producing a false positive.
    """
    if value_node is None:
        return None

    # Field(default="...", ...) — walk keywords for `default=`.
    if isinstance(value_node, ast.Call):
        for kw in value_node.keywords:
            if kw.arg == "default":
                return _extract_string_default(kw.value)
        return None

    # Bare literal, including implicitly-concatenated / parenthesized strings
    # (ast folds these into a single Constant regardless of source formatting).
    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
        return value_node.value or None

    return None


class _SettingsModelFieldVisitor(ast.NodeVisitor):
    """Collect model-shaped fields from every ``*Settings`` class in a module."""

    def __init__(self) -> None:
        self.fields: dict[str, tuple[str, int]] = {}  # field_name -> (default, line)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if "Settings" in node.name:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    name = item.target.id
                    if not _MODEL_FIELD_RE.match(name):
                        continue
                    default = _extract_string_default(item.value)
                    if default is not None:
                        self.fields[name] = (default, item.lineno)
        self.generic_visit(node)


def _scan_config_for_model_fields(config_py: Path, service: str) -> list[ConfiguredModelField]:
    if not config_py.exists():
        return []
    try:
        source = config_py.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    visitor = _SettingsModelFieldVisitor()
    visitor.visit(tree)

    rel = str(config_py.relative_to(REPO_ROOT))
    return [
        ConfiguredModelField(service=service, field=name, default_value=default, file=rel, line=line)
        for name, (default, line) in visitor.fields.items()
    ]


def _discover_all_configured_model_fields() -> list[ConfiguredModelField]:
    """Walk every service's (+ libs/ml-clients') config.py for model-shaped fields."""
    found: list[ConfiguredModelField] = []
    for svc in discover_services():
        config_py = svc.pkg_dir / "config.py"
        found.extend(_scan_config_for_model_fields(config_py, svc.name))
    found.extend(_scan_config_for_model_fields(_ML_CLIENTS_CONFIG, "ml-clients"))
    return found


class TestModelRegistryFieldCompleteness:
    def test_every_configured_model_field_is_enrolled_in_registry(self) -> None:
        """REG-FIELD-MISSING: every model-shaped config.py field must be enrolled.

        A field matching the "*_model"/"*_model_id" naming convention with a
        non-empty string default IS a model the platform will emit calls
        against. If it has no matching ``(service, field)`` entry in
        ``PLATFORM_MODEL_REGISTRY``, it silently bypasses the FR-7 priceability
        CI gate (that test only ever iterates the registry, never config.py) —
        the exact BP-715/BP-294/BP-272 shape.
        """
        registry_keys = {(m.service, m.field) for m in PLATFORM_MODEL_REGISTRY}

        configured = _discover_all_configured_model_fields()
        missing = [cf for cf in configured if (cf.service, cf.field) not in registry_keys]

        assert not missing, (
            "\nModel field(s) configured in config.py but NOT enrolled in "
            "libs/ml-clients/src/ml_clients/model_registry.PLATFORM_MODEL_REGISTRY "
            "(would silently bypass the FR-7 priceability CI gate — BP-715/BP-294/BP-272):\n"
            + "\n".join(f"  - {cf.service}.{cf.field} = {cf.default_value!r}  ({cf.file}:{cf.line})" for cf in missing)
            + "\n\nFix: add a ConfiguredModel(...) entry for each to PLATFORM_MODEL_REGISTRY."
        )

    def test_registered_model_defaults_match_current_config(self) -> None:
        """REG-VALUE-STALE: an enrolled field's registry model_id must match config.py.

        Catches registry drift where a field is enrolled but its recorded
        ``model_id`` no longer matches the live config default (e.g. a model
        swap that updated config.py but not the registry) — a live example:
        rag-chat's ``completion_model`` default moved to ``openai/gpt-oss-120b``
        (DEF-035) while the registry still recorded the retired
        ``deepseek-ai/DeepSeek-V4-Flash-Thinking``. A stale registry entry
        means the *wrong* model_id is being priceability-checked, which can
        mask an actually-unpriceable live model behind a priceable stale one.
        """
        configured_by_key = {(cf.service, cf.field): cf for cf in _discover_all_configured_model_fields()}

        stale = []
        for m in PLATFORM_MODEL_REGISTRY:
            cf = configured_by_key.get((m.service, m.field))
            if cf is not None and cf.default_value != m.model_id:
                stale.append((m, cf))

        assert not stale, (
            "\nRegistry entries whose recorded model_id no longer matches config.py's "
            "current default (registry drift — the wrong model is being priceability-checked):\n"
            + "\n".join(
                f"  - {m.service}.{m.field}: registry says {m.model_id!r}, "
                f"config.py now defaults to {cf.default_value!r} ({cf.file}:{cf.line})"
                for m, cf in stale
            )
            + "\n\nFix: update the ConfiguredModel(...) entry's model_id to match config.py."
        )


class TestExtractStringDefaultUnit:
    """Isolated unit tests for ``_extract_string_default`` against synthetic
    ``ast`` nodes, independent of whatever shapes happen to exist in the live
    repo today. Reviewer A flagged that these edge cases (Field(default=...),
    implicit string concatenation, None/empty defaults) were previously only
    exercised incidentally by config.py's current contents — if a future edit
    removed the last example of one of these shapes from every scanned
    config.py, that code path would go silently untested. These tests pin the
    behavior directly.
    """

    @staticmethod
    def _parse_default(source: str) -> ast.expr | None:
        """Parse ``x: str = <source>`` and return the value node."""
        tree = ast.parse(f"x: str = {source}")
        assign = tree.body[0]
        assert isinstance(assign, ast.AnnAssign)
        return assign.value

    def test_bare_string_literal(self) -> None:
        assert _extract_string_default(self._parse_default('"deepseek-ai/DeepSeek-V4-Flash"')) == (
            "deepseek-ai/DeepSeek-V4-Flash"
        )

    def test_implicitly_concatenated_string_literal(self) -> None:
        # Mirrors the parenthesized-string style used e.g. by
        # deepinfra_stream_chat_fallback_model in rag-chat's config.py.
        assert self._parse_default('(\n    "deepseek-ai/DeepSeek-V4-Flash"\n)') is not None
        assert _extract_string_default(self._parse_default('(\n    "deepseek-ai/DeepSeek-V4-Flash"\n)')) == (
            "deepseek-ai/DeepSeek-V4-Flash"
        )

    def test_field_call_with_default_kwarg(self) -> None:
        node = self._parse_default('Field(default="Qwen/Qwen3-235B-A22B-Instruct-2507", ge=0)')
        assert _extract_string_default(node) == "Qwen/Qwen3-235B-A22B-Instruct-2507"

    def test_field_call_without_default_kwarg_returns_none(self) -> None:
        node = self._parse_default("Field(ge=0, le=10)")
        assert _extract_string_default(node) is None

    def test_none_default_returns_none(self) -> None:
        assert _extract_string_default(self._parse_default("None")) is None

    def test_empty_string_default_returns_none(self) -> None:
        # Empty string = "disabled" convention (extraction_fallback_model_id,
        # grounding_rewrite_model) — must not be treated as a configured model.
        assert _extract_string_default(self._parse_default('""')) is None

    def test_no_default_returns_none(self) -> None:
        assert _extract_string_default(None) is None

    def test_non_literal_expression_returns_none(self) -> None:
        # An expression (not a plain literal) can't be verified statically —
        # must be skipped rather than mis-extracted.
        node = self._parse_default("os.environ.get('SOME_MODEL', 'x')")
        assert _extract_string_default(node) is None


class TestSettingsModelFieldVisitorUnit:
    """Isolated unit test for the AST visitor + field-name regex against a
    synthetic module, independent of live config.py contents."""

    def test_visitor_finds_only_model_shaped_fields_with_defaults(self) -> None:
        source = """
class FooSettings:
    completion_model: str = "openai/gpt-oss-120b"
    extraction_fallback_model_id: str = ""
    grounding_rewrite_model: str | None = None
    log_level: str = "INFO"
    model_config = {"env_prefix": ""}
"""
        tree = ast.parse(source)
        visitor = _SettingsModelFieldVisitor()
        visitor.visit(tree)
        assert set(visitor.fields.keys()) == {"completion_model"}
        assert visitor.fields["completion_model"][0] == "openai/gpt-oss-120b"
