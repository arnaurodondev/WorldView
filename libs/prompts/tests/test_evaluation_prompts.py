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
        # v3.0 — BREAKING (PLAN-0110 W3): deleted "PRESUME GROUNDED"; numeric
        # grounding is now cross-checked deterministically. v2.0 schema keys
        # (reason→feedback, notes→reviewer_summary, length-agnostic framing) are
        # carried forward unchanged.
        ident = CHAT_QUALITY_JUDGE.identifier()
        assert ident.startswith("chat_quality_judge@3.0#")
        assert len(ident.split("#")[1]) == 12

    def test_v3_deletes_presume_grounded_instruction(self) -> None:
        # v3.0 (PLAN-0110 W3 / FR-7): the "PRESUME GROUNDED → award 20-25"
        # instruction is GONE — numeric grounding is verified deterministically
        # against the captured grounding_sample, not presumed by the LLM. A
        # re-introduction of the presume-and-award shortcut must trip this test.
        body = CHAT_QUALITY_JUDGE.render()
        assert "PRESUMED\n" not in body  # the old "is PRESUMED\n GROUNDED" award block
        assert "is\n                             PRESUMED" not in body
        # The exact award shortcut string must be absent.
        assert "PRESUMED\n                             GROUNDED. Award grounding 20-25" not in body
        # The new division-of-labour + presumed-band language must be present.
        assert "NUMERIC VALUE VERIFICATION IS NOT YOUR JOB" in body
        assert "GROUNDING SAMPLE" in body
        assert "presumed band" in body.lower()

    def test_content_hash_stable_across_import(self) -> None:
        first = CHAT_QUALITY_JUDGE.content_hash
        mod = importlib.import_module("prompts.evaluation.chat_quality_judge")
        importlib.reload(mod)
        assert mod.CHAT_QUALITY_JUDGE.content_hash == first

    def test_v2_output_schema_uses_feedback_not_reason(self) -> None:
        # v2.0 BREAKING: per-dim JSON key renamed reason→feedback. The OUTPUT
        # block must show the new key; the legacy ``reason`` key must NOT be
        # the documented contract any more (it's only in the parser as a
        # back-compat fallback).
        body = CHAT_QUALITY_JUDGE.render()
        # OUTPUT block (between "OUTPUT" header and the WRITE FEEDBACK note).
        output_block = body.split("OUTPUT", 1)[1].split("WRITE FEEDBACK", 1)[0]
        assert '"feedback"' in output_block
        # Spelled out so a careless re-introduction of {"score": .., "reason": ..}
        # in the JSON example trips this test.
        assert '"reason"' not in output_block

    def test_v2_output_schema_uses_reviewer_summary_not_notes(self) -> None:
        # v2.0 BREAKING: top-level paragraph renamed notes→reviewer_summary.
        body = CHAT_QUALITY_JUDGE.render()
        output_block = body.split("OUTPUT", 1)[1].split("WRITE FEEDBACK", 1)[0]
        assert '"reviewer_summary"' in output_block
        assert '"notes"' not in output_block

    def test_framing_is_length_agnostic(self) -> None:
        # The framing dimension MUST contain the LENGTH-AGNOSTIC declaration
        # and the explicit "word counts are irrelevant" injunction so the
        # judge stops marking down short factual answers.
        body = CHAT_QUALITY_JUDGE.render()
        assert "LENGTH-AGNOSTIC" in body
        assert "WORD COUNTS ARE IRRELEVANT" in body

    def test_framing_pins_aapl_pe_worked_example(self) -> None:
        # The worked example pins short factual answers at framing=25 — this
        # is the load-bearing calibration that prevents v1.x's false WARNs
        # on simple "what is X's P/E ratio?" answers.
        body = CHAT_QUALITY_JUDGE.render()
        assert "P/E ratio for AAPL is 37.73x" in body


class TestChatTrajectoryJudge:
    """CHAT_TRAJECTORY_JUDGE — 4-dim tool-chain trajectory grader (W2)."""

    def test_no_parameters(self) -> None:
        # Pure system prompt; the per-call QUESTION / INTENT / TOOL TRACE go in
        # the USER message built by scripts/chat_trajectory_judge.py.
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        assert CHAT_TRAJECTORY_JUDGE.parameters == frozenset()

    def test_template_contains_four_trajectory_dimensions(self) -> None:
        # All four trajectory dimensions must appear so the downstream parser
        # sees the expected JSON keys.
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        body = CHAT_TRAJECTORY_JUDGE.render()
        for dim in ("routing", "ordering", "recovery", "efficiency"):
            assert dim in body, f"Missing trajectory dimension {dim!r}"

    def test_output_schema_keys_present(self) -> None:
        # Strict-JSON output contract: the four sub-dims + reviewer_summary.
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        body = CHAT_TRAJECTORY_JUDGE.render()
        output_block = body.split("OUTPUT", 1)[1].split("WRITE FEEDBACK", 1)[0]
        for key in ('"routing"', '"ordering"', '"recovery"', '"efficiency"', '"reviewer_summary"'):
            assert key in output_block, f"Missing output key {key} in OUTPUT block"
        # Per-dim shape mirrors the answer judge: {score, feedback}.
        assert '"score"' in output_block
        assert '"feedback"' in output_block

    def test_semver_and_identifier_format(self) -> None:
        # NEW v1.0; identifier() = name@version#12charhash (BP-405: tag new names).
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        assert CHAT_TRAJECTORY_JUDGE.version == "1.0"
        ident = CHAT_TRAJECTORY_JUDGE.identifier()
        assert ident.startswith("chat_trajectory_judge@1.0#")
        assert len(ident.split("#")[1]) == 12

    def test_content_hash_recorded_value(self) -> None:
        # Pin the v1.0 content_hash — the value recorded in CHANGELOG.md and
        # .claude/evals/prompt_changes/. A body edit flips this and must be
        # accompanied by a new prompt-changes record (judge-prompt versioning).
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        assert CHAT_TRAJECTORY_JUDGE.content_hash == "eb78317b2115"

    def test_content_hash_stable_across_import(self) -> None:
        from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

        first = CHAT_TRAJECTORY_JUDGE.content_hash
        mod = importlib.import_module("prompts.evaluation.chat_trajectory_judge")
        importlib.reload(mod)
        assert mod.CHAT_TRAJECTORY_JUDGE.content_hash == first

    def test_answer_judge_content_hash_unchanged(self) -> None:
        # The trajectory layer MUST NOT perturb the answer grader — its v3.0
        # content_hash is pinned so the answer-quality longitudinal series is
        # unaffected by adding the trajectory judge.
        assert CHAT_QUALITY_JUDGE.version == "3.0"
        assert CHAT_QUALITY_JUDGE.content_hash == "dbbee7f7c6b5"
