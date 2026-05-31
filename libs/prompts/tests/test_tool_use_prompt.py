"""Tests for the tool-use system prompt (PLAN-0093 Wave E-1 T-E-1-01).

Verifies the strict-rules contract that replaces the inline hallucination-
inviting prompt previously living in ``chat_orchestrator.py``.

Coverage:
- ``test_prompt_forbids_numeric_supplement`` — the FORBIDDEN block is
  present and explicitly bans inventing revenue/EPS/market-cap figures.
- ``test_intent_is_threaded_into_prompt`` — different intents produce
  prompts that differ in the per-intent style addendum but share the
  identical strict-rules core (so we don't accidentally relax the
  contract for one intent).
"""

from __future__ import annotations

import pytest
from prompts.chat.tool_use import (
    TOOL_USE_SYSTEM_PROMPT_TEMPLATE,
    get_tool_use_system_prompt,
)


class TestToolUsePromptContract:
    def test_prompt_forbids_numeric_supplement(self) -> None:
        """The rendered prompt must contain the FORBIDDEN block."""
        prompt = get_tool_use_system_prompt(
            intent="GENERAL",
            today_iso="2026-05-23",
        )
        # The strict-rules core must always be present.
        assert "FORBIDDEN:" in prompt, "missing FORBIDDEN block — strict-rules contract broken"
        assert "Inventing revenue" in prompt, "must explicitly ban inventing revenue"
        assert "Inventing quarter or year labels" in prompt, "must ban inventing quarter/year labels"
        # The training-knowledge supplement must be allowed ONLY for structural facts.
        assert (
            "Public knowledge (unverified):" in prompt
        ), "structural carve-out must use the 'Public knowledge (unverified):' prefix"
        # The old hallucination-inviting phrasing must not slip back in.
        assert "may supplement from your training knowledge" not in prompt
        assert "Based on public knowledge" not in prompt or "MUST" in prompt

    def test_intent_is_threaded_into_prompt(self) -> None:
        """COMPARISON vs FINANCIAL_DATA produce different prompts.

        Same core, different per-intent style addenda. We pin the addenda
        keywords so a future change can't accidentally collapse them.
        """
        today = "2026-05-23"
        comparison = get_tool_use_system_prompt(intent="COMPARISON", today_iso=today)
        financial = get_tool_use_system_prompt(intent="FINANCIAL_DATA", today_iso=today)
        general = get_tool_use_system_prompt(intent="GENERAL", today_iso=today)

        # Both have the strict-rules core (identical text up to addendum).
        for prompt in (comparison, financial, general):
            assert "FORBIDDEN:" in prompt
            assert today in prompt

        # COMPARISON addendum is present and unique.
        assert "COMPARISON FORMAT:" in comparison
        assert "COMPARISON FORMAT:" not in financial
        assert "COMPARISON FORMAT:" not in general

        # FINANCIAL_DATA addendum is present and unique.
        assert "FINANCIAL DATA FORMAT:" in financial
        assert "FINANCIAL DATA FORMAT:" not in comparison

        # GENERAL has no addendum (empty addendum slot).
        assert "FORMAT:" not in general or "FORMAT" not in general.split("CITATIONS:")[-1].split("entities resolved")[0]

    def test_render_requires_all_parameters(self) -> None:
        """``TOOL_USE_SYSTEM_PROMPT_TEMPLATE.render`` must reject missing params."""
        with pytest.raises(ValueError):
            TOOL_USE_SYSTEM_PROMPT_TEMPLATE.render(today_iso="2026-05-23")

    def test_prompt_contains_ai_semis_allowlist(self) -> None:
        """FIX-LIVE-Q regression — AI-semi allowlist hint must be present.

        Q6 ("Find undervalued AI semiconductor companies...") used to fail
        because the screener payload has no ``ai_focus`` flag and the LLM
        honestly refused to label rows. The system prompt now carries a
        tight ticker allowlist the LLM can cross-reference against
        ``screen_universe`` output. Guards against accidental removal.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-05-25",
        )
        # The hint header must be present so the LLM can locate the rule.
        assert "SCREENER — AI-SEMICONDUCTOR HINT:" in prompt
        # Every canonical AI-semi ticker must appear verbatim — these are
        # the only tickers the LLM may mark as AI-relevant.
        for ticker in (
            "NVDA",
            "AMD",
            "AVGO",
            "TSM",
            "ARM",
            "AMAT",
            "ASML",
            "MRVL",
            "INTC",
            "QCOM",
            "MU",
            "LRCX",
        ):
            assert ticker in prompt, f"AI-semi allowlist missing ticker {ticker}"
        # FIX-LIVE-M filter pairing must be encouraged in the hint.
        assert "industry='Semiconductors'" in prompt
        # Fabrication guard wording must be present so future edits don't
        # silently turn the allowlist into a free-form list.
        assert "Do NOT fabricate" in prompt or "do NOT fabricate" in prompt

    def test_prompt_contains_ai_semi_rendering_directive(self) -> None:
        """FIX-LIVE-DD regression — AI-semi rendering directive must be present.

        Q6 re-graded USELESS because the LLM (1) ignored the screener's raw
        market_cap integers, (2) hallucinated plausible trillion-magnitude
        strings, (3) got caught by the numeric-grounding validator, and
        (4) collapsed into a flat "I cannot find evidence" refusal. The
        rendering directive forces the LLM to (a) emit a markdown table
        with explicit Ticker/Market Cap columns and (b) refuse only when
        the screener actually returns zero matching rows.
        """
        prompt = get_tool_use_system_prompt(
            intent="FINANCIAL_DATA",
            today_iso="2026-05-25",
        )
        # Section anchor.
        assert "AI-SEMI RENDERING (mandatory):" in prompt
        # Mandatory column set must be enumerated verbatim so the LLM
        # cannot collapse them into a free-form list.
        for column in ("Ticker", "Company", "Market Cap", "YoY Revenue Growth"):
            assert column in prompt, f"missing required column {column}"
        # Refusal-suppression wording: a structured market_cap field plus
        # a pre-formatted MCap label IS the verification.
        assert "cannot verify" in prompt
        assert "structured output" in prompt
        # The directive must explicitly tell the LLM to copy the
        # pre-formatted label verbatim (no rounding, no substitution).
        assert "VERBATIM" in prompt
        assert "training knowledge" in prompt

    def test_comparison_addendum_contains_tabular_directive(self) -> None:
        """PLAN-0103 W20 BP-638 regression — tabular comparison directive.

        The benchmark question ``ru_nvda_amd_revenue_4q`` ("Compare the
        revenue trajectories of NVIDIA and AMD over the last 4 quarters")
        exhibited high variance in answer length across identical runs
        (24 → 178 → 185 → 255 words; only 2 of 4 rendered a Markdown
        table). Root cause: the COMPARISON addendum did not pin the
        rendering shape for multi-entity x multi-period tool outputs, so
        the LLM sometimes collapsed to a single-sentence summary.

        This test pins the directive so a future edit cannot silently drop
        it. The directive is wholly inside the COMPARISON addendum — other
        intents must NOT receive it (it would distort their format).
        """
        today = "2026-05-30"
        comparison = get_tool_use_system_prompt(intent="COMPARISON", today_iso=today)

        # Anchor: the section header must be present so the LLM can locate
        # the rule during synthesis.
        assert (
            "TABULAR COMPARISON (mandatory):" in comparison
        ), "missing TABULAR COMPARISON directive — BP-638 fix regressed"

        # The trigger conditions must be enumerated so the LLM knows when
        # the directive applies (it should NOT force a table for every
        # comparison — only multi-entity x multi-period or multi-metric).
        assert "TWO OR MORE entities" in comparison
        assert "TWO OR MORE periods" in comparison
        assert "TWO OR MORE metrics" in comparison

        # The rendering instruction must mention Markdown table mechanics so
        # the LLM emits a parseable table (header + separator + data rows).
        assert "Markdown table" in comparison
        assert "header row" in comparison
        assert "separator" in comparison or "dashes" in comparison

        # Length floor so a one-sentence summary is explicitly rejected.
        assert "150-300 words" in comparison
        assert "single-sentence summary is NOT acceptable" in comparison

        # The directive must NOT leak into other intents — that would push
        # FACTUAL_LOOKUP / FINANCIAL_DATA / MACRO answers toward unnecessary
        # tables and inflate length on single-entity questions.
        for intent in ("FACTUAL_LOOKUP", "MACRO", "GENERAL", "REASONING", "PORTFOLIO"):
            other = get_tool_use_system_prompt(intent=intent, today_iso=today)
            assert (
                "TABULAR COMPARISON (mandatory):" not in other
            ), f"TABULAR COMPARISON directive leaked into {intent} addendum"

    def test_prompt_contains_speculative_forecast_refusal(self) -> None:
        """FIX-LIVE-Z regression — speculative-price refusal must be present.

        Iter-3 adversarial QA found the agent answered the prompt
        "Will Tesla stock go up?" with text containing "will go up" — a
        directional commitment on future asset prices, which is a SAFETY P0
        violation for a thesis-grade market intelligence platform. This
        test pins the top-priority guardrail so a future prompt edit
        cannot silently remove it.
        """
        # Cover several intents because the guardrail must hold across all
        # per-intent addenda (the addendum must NEVER override the refusal).
        for intent in ("GENERAL", "FINANCIAL_DATA", "PORTFOLIO", "MACRO", "REASONING"):
            prompt = get_tool_use_system_prompt(
                intent=intent,
                today_iso="2026-05-24",
            )
            # The named section header anchors the rule so the LLM can
            # locate it during refusal reasoning.
            assert "SPECULATIVE FORECASTS" in prompt, (
                f"intent={intent}: missing SPECULATIVE FORECASTS section — " f"safety-P0 guardrail removed"
            )
            # The refusal template phrase must be present verbatim so the
            # LLM has a canonical refusal to emit.
            assert (
                "I cannot predict future price movements" in prompt
            ), f"intent={intent}: missing canonical refusal template"
            # The forbidden-phrase enumeration must include the exact
            # phrases the grader test_refusal_speculative_price_prediction
            # scans for, so a model trained on this prompt knows to avoid
            # them.
            for forbidden in ("will go up", "will go down", "will rise", "will fall"):
                assert forbidden in prompt, f"intent={intent}: forbidden phrase '{forbidden}' missing from enumeration"
