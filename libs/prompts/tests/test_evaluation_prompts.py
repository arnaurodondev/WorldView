"""Tests for libs/prompts/evaluation — judge prompts shared across services.

Covers:
- CITATION_JUDGE renders with {claim, snippet}, fences are present, hash stable.
- CHAT_QUALITY_JUDGE is a parameter-free system prompt. As of v1.1 (MN-5),
  the OUTPUT JSON example uses doubled braces in the source so the brace
  guard accepts it; callers MUST go through .render() (with no kwargs) to
  get the LLM-ready text — .render() collapses ``{{`` back to ``{`` and is
  byte-identical to the v1.0 inlined _SYSTEM_PROMPT.
- identifier() format: ``name@version#hash`` is stable across module reloads.
"""

from __future__ import annotations

import importlib

import pytest
from prompts.evaluation import CHAT_QUALITY_JUDGE, CITATION_JUDGE


class TestCitationJudge:
    """CITATION_JUDGE — claim/snippet scorer used by rag-chat."""

    def test_renders_with_claim_and_snippet(self) -> None:
        # Render with realistic inputs; both substitution slots must appear.
        rendered = CITATION_JUDGE.render(
            claim="Apple's Q4 revenue exceeded $90B.",
            snippet="Apple reported Q4 revenue of $94.9 billion.",
        )
        assert "Apple's Q4 revenue exceeded $90B." in rendered
        assert "Apple reported Q4 revenue of $94.9 billion." in rendered

    def test_renders_with_fenced_delimiters(self) -> None:
        # The fenced delimiters are part of the prompt-injection defence
        # (paired with _INJECTION_TOKENS sanitisation in the use case).
        rendered = CITATION_JUDGE.render(claim="c", snippet="s")
        assert "<<<CLAIM START>>>" in rendered
        assert "<<<CLAIM END>>>" in rendered
        assert "<<<SNIPPET START>>>" in rendered
        assert "<<<SNIPPET END>>>" in rendered

    def test_render_missing_param_raises(self) -> None:
        # PromptTemplate.render must reject missing required params at the
        # call site (not silently emit "{snippet}" into the LLM prompt).
        with pytest.raises(ValueError, match="snippet"):
            CITATION_JUDGE.render(claim="c")

    def test_parameters_frozen_set(self) -> None:
        assert CITATION_JUDGE.parameters == frozenset({"claim", "snippet"})

    def test_identifier_format(self) -> None:
        # identifier() = name@version#12charhash; persisted into log lines so
        # an old gauge value can be traced to the exact rubric body that scored it.
        ident = CITATION_JUDGE.identifier()
        assert ident.startswith("citation_judge@1.0#")
        assert len(ident.split("#")[1]) == 12

    def test_content_hash_stable_across_import(self) -> None:
        # Re-import the module — content_hash must be deterministic.
        first = CITATION_JUDGE.content_hash
        mod = importlib.import_module("prompts.evaluation.citation_judge")
        importlib.reload(mod)
        assert mod.CITATION_JUDGE.content_hash == first


class TestChatQualityJudge:
    """CHAT_QUALITY_JUDGE — 4-dim grader used by scripts/chat_quality_judge.py."""

    def test_no_parameters(self) -> None:
        # Pure system prompt, not a templated user message.
        assert CHAT_QUALITY_JUDGE.parameters == frozenset()

    def test_template_contains_dimension_keys(self) -> None:
        # All 4 dimensions must appear so downstream parsers see expected JSON keys.
        # v1.1 — assert on .render() output rather than .template, because the
        # raw source now contains doubled braces that .render() collapses.
        body = CHAT_QUALITY_JUDGE.render()
        for dim in ("tool_use", "grounding", "framing", "refusal_judgment"):
            assert dim in body, f"Missing dimension {dim!r} in CHAT_QUALITY_JUDGE rendered output"

    def test_render_emits_single_braces_in_output_block(self) -> None:
        # v1.1 (MN-5): the source uses ``{{`` / ``}}`` so the brace guard
        # accepts the template; .render() MUST collapse them back to single
        # braces so the LLM sees a literal JSON example, not doubled braces.
        # This is the load-bearing round-trip that protects byte-equivalence
        # with the v1.0 inlined _SYSTEM_PROMPT.
        rendered = CHAT_QUALITY_JUDGE.render()
        assert '{\n  "tool_use"' in rendered
        # And the doubled-brace form must NOT survive into the rendered text.
        assert "{{" not in rendered
        assert "}}" not in rendered

    def test_identifier_format(self) -> None:
        # v1.1 — brace-escape edit bumped the version and changed content_hash.
        # Semantics (grading behaviour) are unchanged from v1.0.
        ident = CHAT_QUALITY_JUDGE.identifier()
        assert ident.startswith("chat_quality_judge@1.1#")
        assert len(ident.split("#")[1]) == 12

    def test_content_hash_stable_across_import(self) -> None:
        first = CHAT_QUALITY_JUDGE.content_hash
        mod = importlib.import_module("prompts.evaluation.chat_quality_judge")
        importlib.reload(mod)
        assert mod.CHAT_QUALITY_JUDGE.content_hash == first
