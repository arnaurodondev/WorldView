"""Unit tests for ``scripts/chat_quality_judge.judge_answer`` (PLAN-0099-W4 / MN-4).

Three contracts the production runner depends on:
  1) SKIPPED path — no API key + no injected LLM → verdict=SKIPPED, and
     the result still carries a stable ``judge_prompt_id`` so the artefact
     can be matched to the rubric body that would have graded it.
  2) ERROR path — an injected LLM that raises any exception → verdict=ERROR,
     ``judge_prompt_id`` still present (same reason: traceability).
  3) Success path — an injected LLM returning valid JSON with all four
     dimensions → verdict in {PASS, WARN, FAIL}, score = sum of dims,
     ``judge_prompt_id`` still present.

All three paths MUST emit a ``judge_prompt_id`` starting with
``"chat_quality_judge@"`` — the runner persists this into
``q_<id>.json["judge"]["judge_prompt_id"]`` so a year-old artefact can be
linked back to the exact rubric body that produced it.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# scripts/ is not a package and not on sys.path during pytest; insert the
# parent directory so ``import chat_quality_judge`` works regardless of where
# pytest is invoked from. We resolve at import time (not test time) so a
# collection error surfaces immediately rather than as a cryptic per-test
# import failure.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import (  # — sys.path mutation must precede the import
    DIMENSION_KEYS,
    JudgeInput,
    Rubric,
    judge_answer,
)

pytestmark = pytest.mark.unit


def _make_input() -> JudgeInput:
    """Build a minimal but realistic JudgeInput for all three sub-tests."""
    return JudgeInput(
        prompt="What is the P/E ratio of AAPL?",
        rubric=Rubric(expected_tools=["query_fundamentals"], expected_depth="shallow"),
        answer_text="AAPL P/E is 37.73x [query_fundamentals row 0].",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"symbol": "AAPL"}}],
        tool_results=[{"status": "ok", "item_count": 1}],
    )


def test_judge_answer_skipped_when_no_llm_and_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DEEPINFRA_API_KEY + no injected LLM → SKIPPED verdict + judge_prompt_id."""
    # Remove the env var so the default LLM builder returns None — this is
    # the CI / offline path we exercise frequently in dev.
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)

    out = judge_answer(_make_input())

    assert out["verdict"] == "SKIPPED"
    assert out["score"] is None
    # Every dimension key must be present, even if value=None — the runner
    # iterates DIMENSION_KEYS unconditionally when building the summary.
    for k in DIMENSION_KEYS:
        assert k in out["dimensions"]
        assert out["dimensions"][k] is None
    # judge_prompt_id is the load-bearing field — must be present + match
    # the canonical PromptTemplate identifier format.
    assert "judge_prompt_id" in out
    assert out["judge_prompt_id"].startswith("chat_quality_judge@")
    assert "#" in out["judge_prompt_id"]  # "name@version#hash" form


def test_judge_answer_error_when_injected_llm_raises() -> None:
    """An LLM that raises → verdict=ERROR; judge_prompt_id still present."""

    def _failing_llm(*, system: str, user: str) -> str:
        # Simulate a network 5xx / rate-limit — judge_answer must wrap any
        # exception (broad ``Exception`` catch) and emit ERROR, not propagate.
        raise RuntimeError("simulated rate-limit / 5xx")

    out = judge_answer(_make_input(), llm=_failing_llm)

    assert out["verdict"] == "ERROR"
    assert out["score"] is None
    # Notes field must include the exception repr so post-mortem debugging
    # of a failed grading run does not require log-diving.
    assert "simulated rate-limit" in out["notes"]
    # Traceability invariant — judge_prompt_id present on ERROR too.
    assert out["judge_prompt_id"].startswith("chat_quality_judge@")


def test_judge_answer_success_returns_score_and_judge_prompt_id() -> None:
    """A valid-JSON LLM response → PASS/WARN/FAIL verdict + dimensions + id."""

    # Build a fake LLM that returns a known-good JSON object scoring 22 on
    # each dimension (total = 88, which sits in the PASS band ≥85).
    fake_payload = {k: {"score": 22, "reason": f"deterministic test stub for {k}"} for k in DIMENSION_KEYS}
    fake_payload["notes"] = "stub notes"

    def _ok_llm(*, system: str, user: str) -> str:
        # The judge expects raw JSON (no markdown fences).
        return json.dumps(fake_payload)

    out = judge_answer(_make_input(), llm=_ok_llm)

    # 22 * 4 = 88 → PASS band (>=85).
    assert out["verdict"] == "PASS"
    assert out["score"] == 88
    for k in DIMENSION_KEYS:
        assert out["dimensions"][k]["score"] == 22
        assert "deterministic test stub" in out["dimensions"][k]["reason"]
    # Notes are preserved up to the 600-char cap.
    assert out["notes"] == "stub notes"
    # Traceability invariant — judge_prompt_id present on success too.
    assert out["judge_prompt_id"].startswith("chat_quality_judge@")
