"""Regression tests for the Theme F false write-action guard.

2026-06-12 root-cause audit (``docs/audits/2026-06-12-post-fix-failure-rootcause.md``
Theme F): ``tc_create_alert_nvda_below`` ("Set an alert to notify me when NVDA
drops below $400.") was human-ruled FAIL because the agent answered with a PROSE
confirmation request ("I'd be happy to set that alert for you. Before I proceed,
I need your explicit confirmation … Could you please confirm that you'd like me
to create this alert?") WITHOUT ever calling the confirmation-gated
``create_alert`` tool — so no ``pending_action`` SSE event fired and no alert was
registered.

The fix has three layers; these tests pin the two deterministic ones:
  1. The ``create_alert`` tool description now instructs the model to CALL the
     tool (not free-text a confirmation) — pinned by
     ``test_create_alert_description_directs_to_call_tool``.
  2. The orchestrator's deterministic guard repairs a misrouted reply when the
     question is an alert imperative, the answer asserts/offers an alert action
     in prose, and NO write-action tool / ``pending_action`` fired this turn —
     pinned by the ``_is_alert_imperative`` / ``_claims_or_offers_uninvoked_alert``
     helper tests below.

The verbatim failing scenario (question + answer) is asserted end-to-end at the
helper level: alert imperative + uninvoked-alert prose → the guard predicate is
True (so the orchestrator repairs to the honest "not created" offer), AND the
honest repair text itself does NOT trip the false-completion claim regex.
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.tool_registry_builder import build_default_registry
from rag_chat.application.use_cases.chat_orchestrator import (
    _ALERT_COMPLETION_CLAIM_RE,
    _ALERT_NOT_CREATED_REPAIR,
    _WRITE_ACTION_TOOLS,
    _claims_or_offers_uninvoked_alert,
    _is_alert_imperative,
)

pytestmark = pytest.mark.unit


# ── The verbatim failing artifact (run_20260612T183758Z) ────────────────────
_BENCHMARK_QUESTION = "Set an alert to notify me when NVDA drops below $400."
_BENCHMARK_ANSWER = (
    "I'd be happy to set that alert for you. Before I proceed, I need your "
    "explicit confirmation:\n\n"
    "**You asked me to create an alert:** Notify you when **NVDA (Nvidia)** "
    "drops below **$400**.\n\n"
    "Could you please confirm that you'd like me to create this alert?"
)
# A worse shape: the agent flatly claims it set the alert (never happened).
_FALSE_COMPLETION_ANSWER = "Done! I've set an alert for NVDA below $400. You'll be notified."


class TestVerbatimBenchmarkScenario:
    """The exact ``tc_create_alert_nvda_below`` failure must be caught + repaired."""

    def test_imperative_detected_for_benchmark_question(self) -> None:
        assert _is_alert_imperative(_BENCHMARK_QUESTION) is True

    def test_prose_offer_answer_flagged_as_uninvoked_alert(self) -> None:
        # The observed FAIL answer (prose confirmation request, no tool call).
        assert _claims_or_offers_uninvoked_alert(_BENCHMARK_ANSWER) is True

    def test_false_completion_answer_flagged(self) -> None:
        # The most severe shape — flatly asserting a completed write-action.
        assert _claims_or_offers_uninvoked_alert(_FALSE_COMPLETION_ANSWER) is True

    def test_guard_predicate_fires_for_benchmark(self) -> None:
        """The full orchestrator predicate (imperative + prose claim) is True.

        This is the deterministic condition under which the orchestrator
        rewrites ``full_text`` to ``_ALERT_NOT_CREATED_REPAIR`` when no
        write-action tool ran and no ``pending_action`` fired this turn.
        """
        question_is_imperative = _is_alert_imperative(_BENCHMARK_QUESTION)
        answer_claims_action = _claims_or_offers_uninvoked_alert(_BENCHMARK_ANSWER)
        assert question_is_imperative and answer_claims_action

    def test_honest_repair_text_does_not_claim_completion(self) -> None:
        """The repair text must NEVER assert a completed write-action.

        The whole point of the fix: replace a misrouted reply with an honest
        offer that explicitly says the alert was NOT created.
        """
        assert "have not created" in _ALERT_NOT_CREATED_REPAIR
        # Must not match the false-completion claim regex (no "I've set an alert").
        assert _ALERT_COMPLETION_CLAIM_RE.search(_ALERT_NOT_CREATED_REPAIR) is None


class TestAlertImperativeDetection:
    """`_is_alert_imperative` matches genuine alert intents, ignores the rest."""

    @pytest.mark.parametrize(
        "question",
        [
            "Set an alert to notify me when NVDA drops below $400.",
            "Alert me when AAPL drops below $200",
            "notify me if TSLA spikes 5%",
            "Create a price alert for MSFT above $500",
            "add an alert for AMZN",
            "Let me know when GOOGL hits $150",
            "set up an alert on META",
        ],
    )
    def test_matches_alert_imperatives(self, question: str) -> None:
        assert _is_alert_imperative(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "What is NVDA's current price?",
            "How did the market react to the latest CPI alert in the news?",
            "Compare AAPL and MSFT revenue",
            "What are Tesla's main risks?",
            "",
        ],
    )
    def test_ignores_non_imperatives(self, question: str) -> None:
        # Note: "CPI alert in the news" mentions the word alert but is NOT an
        # imperative to set one — the regex anchors on set/create/notify intent.
        assert _is_alert_imperative(question) is False


class TestUninvokedAlertClaimDetection:
    """`_claims_or_offers_uninvoked_alert` catches both completion + offer shapes."""

    @pytest.mark.parametrize(
        "answer",
        [
            "I've set an alert for NVDA below $400.",
            "I have created an alert for you.",
            "Done! I've set an alert for AAPL below $200.",
            "Your alert has been set.",
            "The price alert is now active.",
            "I'd be happy to set that alert for you.",
            "I can set up an alert for NVDA below $400.",
            "Before I proceed, I need your explicit confirmation.",
        ],
    )
    def test_flags_uninvoked_alert_prose(self, answer: str) -> None:
        assert _claims_or_offers_uninvoked_alert(answer) is True

    @pytest.mark.parametrize(
        "answer",
        [
            "NVDA is currently trading at $420.",
            "Tesla's main competitors are Rivian and Lucid.",
            "I could not find data for that ticker.",
            _ALERT_NOT_CREATED_REPAIR,  # the honest repair must NOT self-trip
            "",
        ],
    )
    def test_ignores_non_claims(self, answer: str) -> None:
        assert _claims_or_offers_uninvoked_alert(answer) is False


class TestCreateAlertToolDescription:
    """The tool description must direct the model to CALL the tool, not narrate."""

    def _create_alert_description(self) -> str:
        registry = build_default_registry()
        spec = registry.get_spec("create_alert")
        assert spec is not None
        return spec.description

    def test_create_alert_is_a_registered_write_action_tool(self) -> None:
        assert "create_alert" in _WRITE_ACTION_TOOLS

    def test_description_directs_to_call_tool(self) -> None:
        desc = self._create_alert_description().lower()
        # Must instruct the model to CALL the tool (not free-text a confirmation).
        assert "must call this tool" in desc or "you must call" in desc

    def test_description_forbids_prose_confirmation(self) -> None:
        desc = self._create_alert_description().lower()
        # Must explicitly forbid free-texting a confirmation / fake "alert set".
        assert "do not ask the user to confirm" in desc
        assert "confirmation step happens automatically" in desc

    def test_description_explains_gate_is_system_handled(self) -> None:
        desc = self._create_alert_description().lower()
        # The confirmation gate is a SYSTEM mechanism (pending action card),
        # not something the LLM should pre-empt in prose.
        assert "pending action" in desc
