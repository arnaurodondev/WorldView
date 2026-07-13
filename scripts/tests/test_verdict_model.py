"""Unit tests for the PLAN-0110 W1 tiered/lexicographic verdict model.

These tests pin the NEW behaviour added in Wave W1 of PLAN-0110 (PRD-0091
§6.5 / AD-1):

  * the four new verdict objects (``Verdict``, ``InvariantCode``,
    ``GroundingCheck``, ``VerdictDecision``) and their invariants;
  * the single deterministic invariant gate (``evaluate_invariants``) that
    consolidates the three ad-hoc detectors, with per-gate toggling;
  * the lexicographic composition in ``_finalise_verdict`` /
    ``compose_verdict``: GATE-then-BAND — a fired gate is an unconditional FAIL
    that a high soft score can never buy back;
  * band thresholds (90/75/60) and ``quality_score == sum(dimensions)``
    continuity (FR-4);
  * the E1 regression: the ``ru_mstr_news`` run2 artefact (which scored PASS
    under the old additive model) now FAILs via the tiered gate.

The judge module lives under ``scripts/`` which is NOT a package on ``sys.path``
during pytest, so we insert it the same way the sibling judge test does.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from chat_quality_judge import (  # — sys.path mutation must precede the import
    DIMENSION_KEYS,
    GROUNDING_VETO_FLOOR,
    GroundingCheck,
    InvariantCode,
    JudgeInput,
    Rubric,
    Verdict,
    compose_verdict,
    evaluate_invariants,
    first_fired_invariant,
    judge_answer,
    summarise_judge_records,
)

pytestmark = pytest.mark.unit


# The verbatim ``ru_mstr_news`` run2 answer (leading-digit-drop corruption, E6) —
# identical to the fixture in the sibling judge test. Under the old additive
# model this artefact scored PASS; the tiered gate must FAIL it (E1 regression).
_DIGIT_DROP_ANSWER = (
    "MicroStrategy recently purchased an additional **,095 BTC** for approximately **$271.47 million**."
)

# A leaked-control-token stub — the worst-case "polish can't buy it back" case.
_LEAKED_INVOKE_STUB = (
    "I'll pull the latest news on MSTR for you.\n\n"
    '<function_calls>\n<invoke name="get_entity_news">\n'
    '<parameter name="ticker" string="true">MSTR</parameter>\n'
    "</invoke>\n</function_calls>"
)


def _ok_input() -> JudgeInput:
    """A clean, non-degenerate answer that clears every deterministic gate."""
    return JudgeInput(
        prompt="What is the P/E ratio of AAPL?",
        rubric=Rubric(expected_tools=["query_fundamentals"], expected_depth="shallow"),
        answer_text="AAPL P/E is 37.73x as of 2026-06-01 [query_fundamentals row 0].",
        tool_calls=[{"name": "query_fundamentals", "arguments": {"symbol": "AAPL"}}],
        tool_results=[{"tool": "query_fundamentals", "status": "ok", "item_count": 1}],
    )


def _llm_with_dims(**dims: int):
    """Build a mock judge LLM that returns the given per-dimension scores."""

    def _llm(*, system: str, user: str) -> str:
        payload: dict[str, object] = {k: {"score": dims.get(k, 25), "feedback": ""} for k in DIMENSION_KEYS}
        payload["reviewer_summary"] = ""
        return json.dumps(payload)

    return _llm


# ══════════════════════════════════════════════════════════════════════════
# T-W1-01 — verdict taxonomy
# ══════════════════════════════════════════════════════════════════════════


def test_verdict_enum_members() -> None:
    """All four members resolve and order STRONG > PASS > WEAK > FAIL."""
    assert {v.value for v in Verdict} == {"STRONG", "PASS", "WEAK", "FAIL"}
    # Severity ordering by rank (best=STRONG > … > worst=FAIL).
    assert Verdict.STRONG.rank > Verdict.PASS.rank > Verdict.WEAK.rank > Verdict.FAIL.rank
    # ``str`` mix-in: a Verdict compares + serialises as its plain string value.
    assert Verdict.PASS == "PASS"  # noqa: S105 — enum value comparison, not a secret
    assert json.dumps(Verdict.STRONG) == '"STRONG"'


def test_invariant_code_members() -> None:
    """All invariant codes are present (incl. PHANTOM_CITATION + W1 substantiation)."""
    assert {c.value for c in InvariantCode} == {
        "CONTROL_TOKEN_LEAK",
        "TRUNCATED",
        "EMPTY_AFTER_TOOLS",
        "INFRA_NON_ANSWER",
        "GROUNDING_CONTRADICTED",
        "SUBSTANTIATION_UNSUPPORTED",
        "PHANTOM_CITATION",
        "GROUNDING_FLOOR",
    }


def test_grounding_check_defaults_presumed_and_zeroed() -> None:
    """In W1 a default GroundingCheck is presumed with no matches/contradictions."""
    gc = GroundingCheck()
    assert gc.matched == 0 and gc.unmatched == 0 and gc.contradicted == 0
    assert gc.evidence_mode == "presumed"
    assert gc.examples == []
    assert gc.to_dict()["evidence_mode"] == "presumed"


def test_verdict_decision_invariants() -> None:
    """`FAIL ⟺ fail_reason set OR quality_score < 60`; `quality_score == sum(dims)`."""
    gates_all_pass = {c: True for c in InvariantCode}

    # (a) Clear gates + high score → STRONG, no fail_reason.
    d = compose_verdict(
        {"tool_use": 25, "grounding": 25, "framing": 25, "refusal_judgment": 25}, gates_all_pass, GroundingCheck()
    )
    assert d.verdict == Verdict.STRONG
    assert d.fail_reason is None
    assert d.quality_score == sum(d.dimensions.values()) == 100

    # (b) A fired gate → FAIL with a fail_reason (even though the score is 100).
    gates = dict(gates_all_pass)
    gates[InvariantCode.CONTROL_TOKEN_LEAK] = False
    d2 = compose_verdict({k: 25 for k in DIMENSION_KEYS}, gates, GroundingCheck())
    assert d2.verdict == Verdict.FAIL
    assert d2.fail_reason == InvariantCode.CONTROL_TOKEN_LEAK

    # (c) No gate fired but score < 60 → FAIL, fail_reason stays None.
    d3 = compose_verdict(
        {"tool_use": 10, "grounding": 10, "framing": 10, "refusal_judgment": 10}, gates_all_pass, GroundingCheck()
    )
    assert d3.verdict == Verdict.FAIL
    assert d3.fail_reason is None  # soft FAIL — no hard invariant violated
    assert d3.quality_score == 40


def test_verdict_decision_to_dict_roundtrips() -> None:
    """to_dict() is JSON-serialisable with plain-string keys (persistence)."""
    d = compose_verdict({k: 25 for k in DIMENSION_KEYS}, {c: True for c in InvariantCode}, GroundingCheck())
    blob = json.dumps(d.to_dict())  # must not raise
    parsed = json.loads(blob)
    assert parsed["verdict"] == "STRONG"
    assert parsed["fail_reason"] is None
    # gate_results keys are the plain enum VALUES, not "InvariantCode.X" reprs.
    assert set(parsed["gate_results"].keys()) == {c.value for c in InvariantCode}
    assert all(parsed["gate_results"].values())


# ══════════════════════════════════════════════════════════════════════════
# T-W1-02 — deterministic invariant gate
# ══════════════════════════════════════════════════════════════════════════


def test_invariant_control_token_leak() -> None:
    """A leaked <function>/<invoke> stub trips CONTROL_TOKEN_LEAK."""
    gates = evaluate_invariants(_LEAKED_INVOKE_STUB, [], Rubric(), GroundingCheck())
    assert gates[InvariantCode.CONTROL_TOKEN_LEAK] is False
    # Only that gate fired — the others stayed satisfied.
    assert gates[InvariantCode.TRUNCATED] is True
    assert gates[InvariantCode.INFRA_NON_ANSWER] is True


def test_invariant_truncation_digit_drop() -> None:
    """The leading-digit-drop corruption trips TRUNCATED."""
    gates = evaluate_invariants(_DIGIT_DROP_ANSWER, [], Rubric(), GroundingCheck())
    assert gates[InvariantCode.TRUNCATED] is False


def test_invariant_empty_after_tools() -> None:
    """Empty answer after a successful tool trips EMPTY_AFTER_TOOLS."""
    gates = evaluate_invariants("   ", [{"tool": "x", "status": "ok", "item_count": 3}], Rubric(), GroundingCheck())
    assert gates[InvariantCode.EMPTY_AFTER_TOOLS] is False


def test_invariant_infra_non_answer() -> None:
    """All-transport_error + apology on an answerable question trips INFRA_NON_ANSWER."""
    answer = (
        "I cannot reach the stock screener data source right now — it returned a 500 error. "
        "Please retry in a minute."
    )
    rubric = Rubric(expected_tools=["screen_universe"], appropriate_refusal_ok=False)
    results = [{"tool": "screen_universe", "status": "transport_error", "item_count": 0}]
    gates = evaluate_invariants(answer, results, rubric, GroundingCheck())
    assert gates[InvariantCode.INFRA_NON_ANSWER] is False


def test_invariant_floor_below_12() -> None:
    """A grounding sub-dim below the floor trips GROUNDING_FLOOR in VERIFIED mode.

    B3 (2026-07-06): the floor veto is only valid when real grounding samples exist
    (``evidence_mode == "verified"``) — a low GUESSED sub-score in ``presumed`` mode
    is not evidence of fabrication (see ``test_invariant_floor_suppressed_in_presumed``).
    """
    gates = evaluate_invariants(
        _ok_input().answer_text,
        _ok_input().tool_results,
        Rubric(),
        GroundingCheck(evidence_mode="verified"),
        grounding_score=10,
        tool_calls=_ok_input().tool_calls,
    )
    assert gates[InvariantCode.GROUNDING_FLOOR] is False


def test_invariant_floor_suppressed_in_presumed() -> None:
    """B3: a low grounding sub-score in PRESUMED mode must NOT trip GROUNDING_FLOOR.

    No grounding sample = no basis to claim fabrication, so the guessed sub-score
    cannot force a FAIL. This is the fix for the identical-answer PASS/FAIL/PASS flip.
    """
    gates = evaluate_invariants(
        _ok_input().answer_text,
        _ok_input().tool_results,
        Rubric(),
        GroundingCheck(evidence_mode="presumed"),
        grounding_score=10,
        tool_calls=_ok_input().tool_calls,
    )
    assert gates[InvariantCode.GROUNDING_FLOOR] is True


def test_invariant_floor_at_12_does_not_fire() -> None:
    """Boundary: grounding == floor must NOT fire (strict < comparison)."""
    gates = evaluate_invariants(
        _ok_input().answer_text,
        _ok_input().tool_results,
        Rubric(),
        GroundingCheck(evidence_mode="verified"),
        grounding_score=GROUNDING_VETO_FLOOR,
        tool_calls=_ok_input().tool_calls,
    )
    assert gates[InvariantCode.GROUNDING_FLOOR] is True


def test_invariant_floor_none_score_does_not_fire() -> None:
    """No grounding sub-score (judge skipped) → floor gate cannot fire."""
    gates = evaluate_invariants(
        _ok_input().answer_text,
        _ok_input().tool_results,
        Rubric(),
        GroundingCheck(),
        tool_calls=_ok_input().tool_calls,
    )
    assert gates[InvariantCode.GROUNDING_FLOOR] is True


def test_invariant_contradicted_trips_gate() -> None:
    """A GroundingCheck with contradicted>0 trips GROUNDING_CONTRADICTED (W3 wiring)."""
    gc = GroundingCheck(contradicted=1, evidence_mode="verified")
    gates = evaluate_invariants(
        _ok_input().answer_text,
        _ok_input().tool_results,
        Rubric(),
        gc,
        tool_calls=_ok_input().tool_calls,
    )
    assert gates[InvariantCode.GROUNDING_CONTRADICTED] is False


def test_invariant_toggle_disables_gate() -> None:
    """A disabled gate never fires even when the answer would violate it."""
    # Enable everything EXCEPT CONTROL_TOKEN_LEAK; a leaked stub must not trip it.
    enabled = set(InvariantCode) - {InvariantCode.CONTROL_TOKEN_LEAK}
    gates = evaluate_invariants(_LEAKED_INVOKE_STUB, [], Rubric(), GroundingCheck(), enabled=enabled)
    assert gates[InvariantCode.CONTROL_TOKEN_LEAK] is True  # disabled → reported passed


def test_invariant_clean_answer_passes_all_gates() -> None:
    """A genuinely good answer satisfies every gate."""
    inp = _ok_input()
    gates = evaluate_invariants(
        inp.answer_text,
        inp.tool_results,
        inp.rubric,
        GroundingCheck(),
        grounding_score=25,
        tool_calls=inp.tool_calls,
    )
    assert all(gates.values())
    assert first_fired_invariant(gates) is None


def test_first_fired_invariant_priority_order() -> None:
    """When several gates fire, the highest-priority code wins."""
    gates = {c: True for c in InvariantCode}
    gates[InvariantCode.GROUNDING_FLOOR] = False
    gates[InvariantCode.CONTROL_TOKEN_LEAK] = False
    # CONTROL_TOKEN_LEAK outranks GROUNDING_FLOOR.
    assert first_fired_invariant(gates) == InvariantCode.CONTROL_TOKEN_LEAK
    # Contradiction outranks everything.
    gates[InvariantCode.GROUNDING_CONTRADICTED] = False
    assert first_fired_invariant(gates) == InvariantCode.GROUNDING_CONTRADICTED


# ══════════════════════════════════════════════════════════════════════════
# T-W1-03 — lexicographic composition in _finalise_verdict / judge_answer
# ══════════════════════════════════════════════════════════════════════════


def test_verdict_banding() -> None:
    """quality_score 92→STRONG, 80→PASS, 65→WEAK, 50→FAIL (no gate fired)."""
    gates = {c: True for c in InvariantCode}
    # 92 → STRONG
    assert (
        compose_verdict(
            {"tool_use": 25, "grounding": 25, "framing": 25, "refusal_judgment": 17}, gates, GroundingCheck()
        ).verdict
        == Verdict.STRONG
    )
    # 80 → PASS
    assert (
        compose_verdict(
            {"tool_use": 20, "grounding": 20, "framing": 20, "refusal_judgment": 20}, gates, GroundingCheck()
        ).verdict
        == Verdict.PASS
    )
    # 65 → WEAK
    assert (
        compose_verdict(
            {"tool_use": 20, "grounding": 15, "framing": 15, "refusal_judgment": 15}, gates, GroundingCheck()
        ).verdict
        == Verdict.WEAK
    )
    # 50 → FAIL (soft, no gate)
    assert (
        compose_verdict(
            {"tool_use": 13, "grounding": 13, "framing": 12, "refusal_judgment": 12}, gates, GroundingCheck()
        ).verdict
        == Verdict.FAIL
    )


def test_band_boundaries_inclusive() -> None:
    """The band edges (90/75/60) are inclusive lower bounds."""
    gates = {c: True for c in InvariantCode}

    def _band(score: int) -> Verdict:
        # Split a score across four dims so the sum equals it exactly.
        per, rem = divmod(score, 4)
        dims = {k: per for k in DIMENSION_KEYS}
        dims["tool_use"] += rem
        # Each dim must be 0-25; for these boundary scores it always is.
        return compose_verdict(dims, gates, GroundingCheck()).verdict

    assert _band(90) == Verdict.STRONG
    assert _band(89) == Verdict.PASS
    assert _band(75) == Verdict.PASS
    assert _band(74) == Verdict.WEAK
    assert _band(60) == Verdict.WEAK
    assert _band(59) == Verdict.FAIL


def test_quality_score_continuity() -> None:
    """quality_score == sum(dims), and the legacy ``score`` key matches it (FR-4)."""
    out = judge_answer(_ok_input(), llm=_llm_with_dims(tool_use=22, grounding=22, framing=20, refusal_judgment=20))
    decision = out["verdict_decision"]
    assert decision["quality_score"] == 84
    # The legacy additive ``score`` is numerically identical to quality_score.
    assert out["score"] == decision["quality_score"]
    assert decision["quality_score"] == sum(decision["dimensions"].values())


def test_gate_overrides_high_quality() -> None:
    """dims sum 95 + CONTROL_TOKEN_LEAK → FAIL[CONTROL_TOKEN_LEAK].

    The whole point of AD-1: a near-perfect soft score cannot buy back a hard
    invariant violation. The leaked stub short-circuits in judge_answer, so its
    VerdictDecision must still be a FAIL with the right code.
    """
    # The leaked stub never reaches the LLM; its VerdictDecision is built by the
    # degenerate path. Confirm it FAILs with CONTROL_TOKEN_LEAK regardless.
    inp = JudgeInput(
        prompt="Show me MSTR news.",
        rubric=Rubric(expected_tools=["get_entity_news"]),
        answer_text=_LEAKED_INVOKE_STUB,
        tool_calls=[],
        tool_results=[],
    )

    def _high_score_llm(*, system: str, user: str) -> str:
        return json.dumps({k: {"score": 24, "feedback": ""} for k in DIMENSION_KEYS})

    out = judge_answer(inp, llm=_high_score_llm)
    decision = out["verdict_decision"]
    assert decision["verdict"] == "FAIL"
    assert decision["fail_reason"] == "CONTROL_TOKEN_LEAK"
    assert decision["gate_results"]["CONTROL_TOKEN_LEAK"] is False


def _ok_input_verified() -> JudgeInput:
    """``_ok_input`` plus a real grounding sample → the cross-check runs VERIFIED.

    The sampled ``pe_ratio`` matches the claimed ``37.73x`` so no numeric
    contradiction fires; the low soft grounding sub-score is what drives the floor
    veto, which is only valid in verified mode (B3).
    """
    base = _ok_input()
    return JudgeInput(
        prompt=base.prompt,
        rubric=base.rubric,
        answer_text=base.answer_text,
        tool_calls=base.tool_calls,
        tool_results=[
            {
                "tool": "query_fundamentals",
                "status": "ok",
                "item_count": 1,
                "grounding_sample": {"fields": {"pe_ratio": "37.73", "ticker": "AAPL"}},
            }
        ],
    )


def test_grounding_floor_gate_overrides_high_quality_via_judge() -> None:
    """dims sum 85 with grounding=10 → tiered FAIL[GROUNDING_FLOOR] in VERIFIED mode.

    This is the E1 fabrication case routed through the soft judge (not the
    degenerate pre-check): a fabricated number scores grounding=10, the other
    dims are perfect, the additive sum is 85 (old PASS) — with real samples present
    the floor gate must FAIL it. (B3, 2026-07-06: the floor is verified-mode only.)
    """
    out = judge_answer(
        _ok_input_verified(), llm=_llm_with_dims(tool_use=25, grounding=10, framing=25, refusal_judgment=25)
    )
    decision = out["verdict_decision"]
    assert decision["quality_score"] == 85  # unchanged additive sum
    assert decision["verdict"] == "FAIL"
    assert decision["fail_reason"] == "GROUNDING_FLOOR"
    # Legacy back-compat: the old ``veto`` block + ``verdict`` string still fire.
    assert out["verdict"] == "FAIL"
    assert out["veto"]["type"] == "grounding"


def test_grounding_floor_suppressed_in_presumed_via_judge() -> None:
    """B3: the SAME dims (grounding=10) in PRESUMED mode do NOT veto → PASS.

    ``_ok_input`` carries no grounding sample, so the guessed grounding sub-score
    cannot force a FAIL. sum=85 → the additive band decides → PASS (no veto).
    """
    out = judge_answer(_ok_input(), llm=_llm_with_dims(tool_use=25, grounding=10, framing=25, refusal_judgment=25))
    decision = out["verdict_decision"]
    assert decision["quality_score"] == 85
    assert decision["fail_reason"] is None
    assert decision["verdict"] != "FAIL"
    assert out["verdict"] == "PASS"
    assert out["veto"] is None


def test_additive_fabrication_now_fails_e1_regression() -> None:
    """E1 regression: the ru_mstr_news run2 (digit-drop) artefact → FAIL not PASS.

    Under the old additive model this answer scored PASS. The tiered gate now
    classifies the digit-drop corruption as TRUNCATED → unconditional FAIL,
    before the LLM judge is ever consulted.
    """
    inp = JudgeInput(
        prompt="What's the latest MSTR news?",
        rubric=Rubric(expected_tools=["get_entity_news"]),
        answer_text=_DIGIT_DROP_ANSWER,
        tool_calls=[],
        tool_results=[{"tool": "get_entity_news", "status": "ok", "item_count": 1}],
    )

    called = {"n": 0}

    def _spy_llm(*, system: str, user: str) -> str:
        called["n"] += 1  # must NOT be called — the gate fires first
        return json.dumps({k: {"score": 25, "feedback": ""} for k in DIMENSION_KEYS})

    out = judge_answer(inp, llm=_spy_llm)
    assert called["n"] == 0
    decision = out["verdict_decision"]
    assert decision["verdict"] == "FAIL"
    assert decision["fail_reason"] == "TRUNCATED"


def test_clean_answer_gets_strong_tiered_verdict() -> None:
    """A clean, well-grounded answer clears every gate and bands to STRONG."""
    out = judge_answer(_ok_input(), llm=_llm_with_dims(tool_use=25, grounding=25, framing=25, refusal_judgment=25))
    decision = out["verdict_decision"]
    assert decision["verdict"] == "STRONG"
    assert decision["fail_reason"] is None
    assert all(decision["gate_results"].values())
    # Legacy verdict still PASS (the back-compat 85/60 bands have no STRONG).
    assert out["verdict"] == "PASS"


# ══════════════════════════════════════════════════════════════════════════
# T-W1-04 — wiring: skipped/error paths + summary aggregation
# ══════════════════════════════════════════════════════════════════════════


def test_skipped_judge_has_null_verdict_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """A skipped judge (no API key, clean answer) → verdict_decision is None.

    No soft sub-scores exist, and no gate fired (a fired gate would have FAILed
    earlier), so there is genuinely no tiered verdict to compose.
    """
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    out = judge_answer(_ok_input())  # llm=None, no key
    assert out["verdict"] == "SKIPPED"
    assert out["verdict_decision"] is None


def test_degenerate_offline_produces_fail_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate-only verdict is produced even when the judge is skipped (F-4)."""
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    inp = JudgeInput(
        prompt="Show me MSTR news.",
        rubric=Rubric(expected_tools=["get_entity_news"]),
        answer_text=_LEAKED_INVOKE_STUB,
        tool_calls=[],
        tool_results=[],
    )
    out = judge_answer(inp)  # llm=None, no key — gate still runs
    decision = out["verdict_decision"]
    assert decision is not None
    assert decision["verdict"] == "FAIL"
    assert decision["fail_reason"] == "CONTROL_TOKEN_LEAK"


def test_summarise_records_tiered_counts_and_fail_reasons() -> None:
    """The summary aggregates tiered band counts + a fail_reason histogram."""
    records = [
        {
            "verdict": "PASS",
            "score": 90,
            "dimensions": {k: {"score": 22} for k in DIMENSION_KEYS},
            "verdict_decision": {"verdict": "STRONG", "fail_reason": None},
        },
        {
            "verdict": "FAIL",
            "score": 0,
            "dimensions": {k: {"score": 0} for k in DIMENSION_KEYS},
            "verdict_decision": {"verdict": "FAIL", "fail_reason": "CONTROL_TOKEN_LEAK"},
        },
        {
            "verdict": "FAIL",
            "score": 85,
            "dimensions": {k: {"score": 21} for k in DIMENSION_KEYS},
            "verdict_decision": {"verdict": "FAIL", "fail_reason": "GROUNDING_FLOOR"},
        },
        # A skipped record (no decision) must not crash the aggregator.
        {
            "verdict": "SKIPPED",
            "score": None,
            "dimensions": {k: {"score": None} for k in DIMENSION_KEYS},
            "verdict_decision": None,
        },
    ]
    agg = summarise_judge_records(records)
    assert agg["tiered_verdict_counts"] == {"n_strong": 1, "n_pass": 0, "n_weak": 0, "n_fail": 2}
    assert agg["fail_reason_counts"] == {"CONTROL_TOKEN_LEAK": 1, "GROUNDING_FLOOR": 1}
