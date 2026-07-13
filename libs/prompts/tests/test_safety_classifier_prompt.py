"""Tests for the migrated injection safety classifier prompt (Phase 2B).

Mirrors the prompt-content guards in
``services/rag-chat/tests/unit/security/test_llm_injection_classifier*`` so a
regression to the template body is caught at the libs/prompts layer too.
"""

from __future__ import annotations

import pytest
from prompts.chat import INJECTION_SAFETY_CLASSIFIER
from prompts.chat.safety_classifier import (
    INJECTION_SAFETY_CLASSIFIER as DIRECT_IMPORT,
)


class TestInjectionSafetyClassifierPrompt:
    def test_re_export_matches_direct_import(self) -> None:
        # The chat-package __init__ must re-export the same singleton.
        assert INJECTION_SAFETY_CLASSIFIER is DIRECT_IMPORT

    def test_version_is_semver_4(self) -> None:
        # Lineage: vN string was "v4" → semver normalised to "4.0"; MINOR bumped
        # to 4.1 for the A6 account/portfolio/alert additive SAFE exemplar. MAJOR
        # stays 4 (no threat-category change) so the legacy "v4" cache key holds.
        assert INJECTION_SAFETY_CLASSIFIER.version == "4.1"

    def test_identifier_shape(self) -> None:
        ident = INJECTION_SAFETY_CLASSIFIER.identifier()
        assert ident.startswith("injection_safety_classifier@4.1#")
        # 12-char hex hash suffix.
        assert len(ident.split("#")[-1]) == 12

    def test_template_lists_four_unsafe_categories(self) -> None:
        body = INJECTION_SAFETY_CLASSIFIER.template
        for category in ("JAILBREAK", "PRIVILEGE ESCALATION", "PROMPT INJECTION", "DATA EXFILTRATION"):
            assert category in body, f"missing UNSAFE category: {category}"

    def test_template_includes_screener_safe_exemplar(self) -> None:
        body = INJECTION_SAFETY_CLASSIFIER.template
        # v4 lineage: screener SAFE exemplar must be present (BP-632 regression guard).
        assert "Financial screening" in body
        assert "market cap above $50B" in body

    def test_template_includes_account_alert_safe_exemplar(self) -> None:
        body = INJECTION_SAFETY_CLASSIFIER.template
        # 4.1 lineage: A6 account/portfolio/alert SAFE exemplar must be present
        # so a prompt revert re-introducing the INPUT_REJECTED false-positive on
        # "What alerts do I currently have set up?" trips this guard immediately.
        assert "First-person account / portfolio" in body
        assert "What alerts do I currently have set up?" in body

    def test_template_includes_relationship_safe_exemplar(self) -> None:
        body = INJECTION_SAFETY_CLASSIFIER.template
        # v3 lineage: relationship SAFE exemplar must be present (BP-579 guard).
        assert "Relationship / graph / connection" in body

    def test_template_includes_conditional_reasoning_exemplar(self) -> None:
        body = INJECTION_SAFETY_CLASSIFIER.template
        # v2 lineage: FIX-LIVE-CC conditional reasoning guard.
        assert "Conditional / if-then-else" in body

    def test_render_no_params(self) -> None:
        # No parameters expected — render() with no kwargs must succeed and
        # must collapse the doubled JSON braces in the example line into
        # single braces (valid JSON for the LLM).
        out = INJECTION_SAFETY_CLASSIFIER.render()
        assert '{"label": "SAFE"|"UNSAFE", "reason": "..."}' in out
        # The literal template (pre-render) keeps the {{ }} escaping.
        assert '{{"label"' in INJECTION_SAFETY_CLASSIFIER.template

    def test_render_rejects_unknown_params_silently(self) -> None:
        # PromptTemplate ignores extra kwargs by design.
        out = INJECTION_SAFETY_CLASSIFIER.render(unused="x")
        # Output is the rendered form (single braces).
        assert '{"label":' in out


class TestAgenticBriefPlanPrompt:
    def test_import_and_version(self) -> None:
        from prompts.briefing import AGENTIC_BRIEF_PLAN

        # 0.x is intentionally pre-1.0 (scaffold).
        assert AGENTIC_BRIEF_PLAN.version == "0.1"

    def test_identifier_shape(self) -> None:
        from prompts.briefing.agentic_plan import AGENTIC_BRIEF_PLAN

        ident = AGENTIC_BRIEF_PLAN.identifier()
        assert ident.startswith("agentic_brief_plan@0.1#")

    def test_template_mentions_analyst_role(self) -> None:
        from prompts.briefing import AGENTIC_BRIEF_PLAN

        body = AGENTIC_BRIEF_PLAN.template
        assert "institutional research analyst" in body
        assert "morning brief" in body
        # Citation contract used by the loop's downstream parser.
        assert "[c1]" in body


class TestIntentClassifierPromptV21:
    def test_version_is_2_1(self) -> None:
        from prompts.classification import INTENT_CLASSIFICATION

        assert INTENT_CLASSIFICATION.version == "2.1"

    def test_priority_rules_block_present(self) -> None:
        # Block was originally only in libs/prompts; consolidation must keep it.
        from prompts.classification import INTENT_CLASSIFICATION

        body = INTENT_CLASSIFICATION.template
        assert "CLASSIFICATION RULES" in body
        assert "Priority:" in body

    def test_w49_examples_present(self) -> None:
        # Examples migrated from the inline _CLASSIFICATION_PROMPT must survive.
        from prompts.classification import INTENT_CLASSIFICATION

        body = INTENT_CLASSIFICATION.template
        assert "AAPL's P/E ratio" in body
        assert "market capitalization" in body
        assert "YoY revenue growth" in body

    def test_render_still_works(self) -> None:
        from prompts.classification import INTENT_CLASSIFICATION

        out = INTENT_CLASSIFICATION.render(message="hello", history="[]", entities="[]")
        assert "hello" in out

    def test_render_missing_params_raises(self) -> None:
        from prompts.classification import INTENT_CLASSIFICATION

        with pytest.raises(ValueError, match="Missing required parameters"):
            INTENT_CLASSIFICATION.render(message="x")
