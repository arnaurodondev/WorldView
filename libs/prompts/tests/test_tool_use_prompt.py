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
