#!/usr/bin/env python3
"""Trajectory / tool-chain quality judge (Multi-Level Eval Framework — W2).

Where ``chat_quality_judge.judge_answer`` grades the FINAL ANSWER, this module
grades the agent's PROCESS — the ordered sequence of tool calls it made to reach
that answer. It is a SEPARATE, ADDITIVE layer: it never changes the answer's
PASS/FAIL verdict; the runner attaches its output as a ``trajectory`` block.

Public surface
--------------
* ``judge_trajectory(inp, *, llm=None) -> TrajectoryJudgement``
    Mirrors ``judge_answer``. It REUSES ``chat_quality_judge._build_user_prompt``
    to render the SAME flat ordered trace the answer judge sees
    (``call N: tool(args) -> status items=K``) — it does NOT re-derive a trace
    from raw SSE events, so the two judges always reason over identical evidence
    (one source of truth — feedback_prompt_input_mismatch).
* ``summarise_trajectory_records(records) -> dict``
    Roll-up for the ``_judge_summary.json`` ``trajectory`` block + report.

Two-tier evaluation
-------------------
1. **Deterministic, LLM-free pre-signals** (always computed, even offline):
     * ``redundant_call_pairs`` — count of identical ``(name, args)`` calls that
       repeat (a re-issued call with the same arguments adds no information).
     * ``unrecovered_failures`` — count of failed/empty calls (status != ok,
       items == 0, or no result event) that have NO later SUCCESSFUL call for
       the same tool name (the agent gave up / looped without recovering).
   These are model-agnostic and stable; they are the trajectory layer's MUST-2
   pre-signals and are the only output when no judge LLM is configured.
2. **LLM sub-scores** (when an ``llm`` is configured / injected): four 0-25
   trajectory dimensions (routing / ordering / recovery / efficiency) graded by
   ``CHAT_TRAJECTORY_JUDGE``. ``trajectory_score = sum(4)`` (0-100). With no LLM
   the score is ``None`` (verdict ``SKIPPED``) but the pre-signals still populate.

Like the answer judge, all LLM calls are gated by ``DEEPINFRA_API_KEY``; if
unset (and no LLM injected), ``judge_trajectory`` returns ``trajectory_score=None``
so the harness still produces artefacts in offline / CI environments.
"""

from __future__ import annotations

import json
import os
from typing import Any

# Reuse the answer judge's plumbing verbatim — JudgeInput / JudgeLLM (the
# Protocol), the default-LLM builder, the SHARED trace renderer
# ``_build_user_prompt`` (do NOT re-derive the trace), the defensive JSON parser,
# and the compact arg repr. Importing them keeps the two judges byte-identical in
# how they present the trace to their respective prompts.
from chat_quality_judge import (
    _DEFAULT_BASE_URL,
    _DEFAULT_JUDGE_MODEL,
    JudgeInput,
    JudgeLLM,
    _build_default_llm,
    _build_user_prompt,
    _parse_judge_response,
    _short_repr,
)
from prompts.evaluation import CHAT_TRAJECTORY_JUDGE

# The four trajectory sub-dimensions, each scored 0-25 by the LLM. Order is
# stable so the report + roll-up render columns deterministically.
TRAJECTORY_DIMENSION_KEYS: tuple[str, ...] = (
    "routing",
    "ordering",
    "recovery",
    "efficiency",
)
_MAX_PER_DIMENSION = 25
_MAX_TOTAL = _MAX_PER_DIMENSION * len(TRAJECTORY_DIMENSION_KEYS)  # 100

# Rendered once at import — the trajectory judge prompt is parameter-free; the
# per-call QUESTION / INTENT / TOOL TRACE go in the user message we build below.
_SYSTEM_PROMPT = CHAT_TRAJECTORY_JUDGE.render()


# --------------------------------------------------------------------------
# Deterministic, LLM-free pre-signals (always computed)
# --------------------------------------------------------------------------


def _canonical_args(arguments: Any) -> str:
    """Stable, comparable repr of a call's arguments for redundancy matching.

    We sort keys so ``{a:1, b:2}`` and ``{b:2, a:1}`` are recognised as the SAME
    call. Non-dict / unserialisable args fall back to ``_short_repr`` so the
    function never raises on odd payloads.
    """
    if isinstance(arguments, dict):
        try:
            return json.dumps(arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return _short_repr(arguments)
    return _short_repr(arguments)


def _call_signature(call: dict[str, Any]) -> tuple[str, str]:
    """``(tool_name, canonical_args)`` identity tuple for a tool call."""
    name = str(call.get("name") or "?")
    args = call.get("arguments") or {}
    return (name, _canonical_args(args))


def count_redundant_call_pairs(tool_calls: list[dict[str, Any]] | None) -> int:
    """Count REDUNDANT repeats of an identical ``(name, args)`` call.

    The FIRST occurrence of a signature is free; every SUBSEQUENT identical call
    is one redundant pair (the agent re-issued a call that can only return the
    same data). E.g. signatures [A, A, A, B] → 2 redundant repeats (the 2nd and
    3rd A). This is a deterministic efficiency pre-signal — it needs no LLM and
    cannot be argued away by a miscalibrated judge.
    """
    seen: dict[tuple[str, str], int] = {}
    redundant = 0
    for call in tool_calls or []:
        sig = _call_signature(call)
        if sig in seen:
            redundant += 1
        seen[sig] = seen.get(sig, 0) + 1
    return redundant


def _result_is_failed_or_empty(result: dict[str, Any]) -> bool:
    """True when a tool_result carried no usable data.

    Failure/empty signals (any one is enough):
      * ``status`` present and not ``ok`` (e.g. error / missing / timeout);
      * ``item_count`` == 0 (the tool ran but returned zero rows).
    A result with ``status=ok`` and a non-zero / absent item_count is a success.
    """
    status = result.get("status")
    if status is not None and str(status).lower() != "ok":
        return True
    item_count = result.get("item_count")
    if isinstance(item_count, int) and item_count == 0:
        return True
    return False


def _result_is_success(result: dict[str, Any]) -> bool:
    """True when a tool_result delivered usable data (status=ok AND items != 0)."""
    status = result.get("status")
    if status is not None and str(status).lower() != "ok":
        return False
    item_count = result.get("item_count")
    if isinstance(item_count, int) and item_count == 0:
        return False
    return True


def _result_tool_name(result: dict[str, Any]) -> str:
    """Tool name a result belongs to (``tool`` or ``name`` key)."""
    return str(result.get("tool") or result.get("name") or "?")


def count_unrecovered_failures(
    tool_calls: list[dict[str, Any]] | None,
    tool_results: list[dict[str, Any]] | None,
) -> int:
    """Count failed/empty tool results NOT followed by a later success.

    A failed/empty result for tool ``T`` is "recovered" when a LATER result for
    the SAME tool name succeeded (the agent retried with corrected args, or the
    call eventually returned data). A failed/empty result with no later success
    for that tool name is an UNRECOVERED failure — the agent gave up or looped.

    This is order-aware: we walk the results in stream order and, for each
    failed/empty one, look ONLY at results AFTER it for a same-name success.
    A call that has no result event at all (``(no result event)``) is detected
    by the answer-judge trace, not here — this signal works off captured results.
    """
    results = list(tool_results or [])
    unrecovered = 0
    for i, res in enumerate(results):
        if not _result_is_failed_or_empty(res):
            continue
        name = _result_tool_name(res)
        # Was there a LATER success for the same tool name? (recovery)
        recovered = any(_result_tool_name(later) == name and _result_is_success(later) for later in results[i + 1 :])
        if not recovered:
            unrecovered += 1
    return unrecovered


def compute_pre_signals(inp: JudgeInput) -> dict[str, int]:
    """Compute the deterministic, LLM-free trajectory pre-signals.

    Returns ``{"redundant_call_pairs": int, "unrecovered_failures": int}``. These
    run REGARDLESS of whether an LLM is configured, so the trajectory layer always
    yields signal (the MUST-2 deterministic floor).
    """
    return {
        "redundant_call_pairs": count_redundant_call_pairs(inp.tool_calls),
        "unrecovered_failures": count_unrecovered_failures(inp.tool_calls, inp.tool_results),
    }


# --------------------------------------------------------------------------
# LLM sub-score parsing
# --------------------------------------------------------------------------


def _parse_sub_scores(parsed: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], int]:
    """Clamp the four trajectory sub-dims to [0, 25]; return (sub_scores, total).

    Mirrors ``chat_quality_judge._finalise_verdict``'s clamping: a missing /
    non-numeric dimension defaults to 0; each dim carries ``{score, feedback}``.
    """
    sub_scores: dict[str, dict[str, Any]] = {}
    total = 0
    for key in TRAJECTORY_DIMENSION_KEYS:
        entry = parsed.get(key)
        if isinstance(entry, dict):
            raw_score = entry.get("score")
            feedback = str(entry.get("feedback") or entry.get("reason", ""))[:300]
        else:
            raw_score = entry  # tolerate a bare number
            feedback = ""
        try:
            score = int(raw_score) if raw_score is not None else 0
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(_MAX_PER_DIMENSION, score))
        sub_scores[key] = {"score": score, "feedback": feedback}
        total += score
    return sub_scores, total


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def judge_trajectory(
    inp: JudgeInput,
    *,
    llm: JudgeLLM | None = None,
) -> dict[str, Any]:
    """Grade ONE answer's tool-chain TRAJECTORY (process).

    Returns a ``TrajectoryJudgement`` dict::

        {
          "trajectory_score": int | None,   # sum of 4 sub-dims (0-100); None=SKIPPED
          "verdict":          "GRADED" | "SKIPPED" | "ERROR",
          "sub_scores":       {routing/ordering/recovery/efficiency: {score, feedback}},
          "reviewer_summary": str,
          "judge_prompt_id":  str,           # CHAT_TRAJECTORY_JUDGE identifier
          "redundant_call_pairs":  int,      # deterministic pre-signal
          "unrecovered_failures":  int,      # deterministic pre-signal
        }

    The deterministic pre-signals are ALWAYS populated. When ``llm`` is None we
    try to build the default DeepInfra-backed judge from env
    (``DEEPINFRA_API_KEY`` / ``CHAT_JUDGE_MODEL`` / ``CHAT_JUDGE_BASE_URL``); if
    no key is configured the LLM sub-scores are skipped (``trajectory_score=None``,
    verdict ``SKIPPED``) but the pre-signals still come through. A judge call that
    raises returns verdict ``ERROR`` with the pre-signals intact.
    """
    if llm is None:
        llm = _build_default_llm(
            api_key=os.environ.get("DEEPINFRA_API_KEY"),
            model=os.environ.get("CHAT_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL),
            base_url=os.environ.get("CHAT_JUDGE_BASE_URL", _DEFAULT_BASE_URL),
        )

    # Stable identifier for the trajectory rubric that produced this verdict —
    # persisted on EVERY result (including SKIPPED/ERROR) so a year-old artefact
    # can be traced to the exact prompt body that graded it.
    judge_prompt_id = CHAT_TRAJECTORY_JUDGE.identifier()

    # Deterministic pre-signals first — these run even with no LLM.
    pre_signals = compute_pre_signals(inp)

    def _result(
        *, verdict: str, score: int | None, sub_scores: dict[str, dict[str, Any]], summary: str
    ) -> dict[str, Any]:
        return {
            "trajectory_score": score,
            "verdict": verdict,
            "sub_scores": sub_scores,
            "reviewer_summary": summary,
            "judge_prompt_id": judge_prompt_id,
            **pre_signals,
        }

    if llm is None:
        # No API key + no injected LLM → SKIPPED LLM scoring, pre-signals only.
        return _result(
            verdict="SKIPPED",
            score=None,
            sub_scores={k: {"score": None, "feedback": ""} for k in TRAJECTORY_DIMENSION_KEYS},
            summary="Trajectory judge LLM not configured (set DEEPINFRA_API_KEY); deterministic pre-signals only.",
        )

    # REUSE the answer judge's trace renderer so both judges see the SAME flat
    # ordered trace (one source of truth — we do NOT re-derive it from raw
    # events). The user prompt also carries the QUESTION + RUBRIC (the rubric's
    # expected_tools / depth are useful intent signal for routing/ordering); the
    # trajectory prompt simply reads the TOOL TRACE + QUESTION from it.
    user_prompt = _build_user_prompt(inp)
    try:
        raw = llm(system=_SYSTEM_PROMPT, user=user_prompt)
    except Exception as exc:  # network error, rate-limit, model 5xx
        return _result(
            verdict="ERROR",
            score=None,
            sub_scores={k: {"score": None, "feedback": ""} for k in TRAJECTORY_DIMENSION_KEYS},
            summary=f"Trajectory judge call failed: {exc!r}",
        )

    parsed = _parse_judge_response(raw)
    sub_scores, total = _parse_sub_scores(parsed)
    reviewer_summary = str(parsed.get("reviewer_summary") or parsed.get("notes", ""))[:800]
    return _result(
        verdict="GRADED",
        score=total,
        sub_scores=sub_scores,
        summary=reviewer_summary,
    )


# --------------------------------------------------------------------------
# Roll-up for _judge_summary.json + the report
# --------------------------------------------------------------------------


def summarise_trajectory_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-Q trajectory judgements for the ``trajectory`` summary block.

    ``records`` is a list of ``TrajectoryJudgement`` dicts. Returns::

        {
          "mean_score":         float | None,   # mean trajectory_score over GRADED
          "redundant_turns_n":  int,            # total redundant_call_pairs
          "unrecovered_turns_n":int,            # total unrecovered_failures
          "dimension_avg":      {dim: float | None},
          "n_records":          int,
          "n_graded":           int,
          "judge_prompt_id":    str,
        }

    SKIPPED / ERROR records are excluded from the score/dimension averages but
    their deterministic pre-signals (which are always present) STILL count toward
    the redundant/unrecovered totals — those signals are LLM-free.
    """
    scored: list[int] = []
    dim_totals: dict[str, list[int]] = {k: [] for k in TRAJECTORY_DIMENSION_KEYS}
    redundant_total = 0
    unrecovered_total = 0
    n_graded = 0
    for r in records:
        # Pre-signals are present on EVERY record regardless of verdict.
        rc = r.get("redundant_call_pairs")
        if isinstance(rc, int):
            redundant_total += rc
        uf = r.get("unrecovered_failures")
        if isinstance(uf, int):
            unrecovered_total += uf
        score = r.get("trajectory_score")
        if isinstance(score, int):
            scored.append(score)
            n_graded += 1
        sub = r.get("sub_scores") or {}
        for k in TRAJECTORY_DIMENSION_KEYS:
            entry = sub.get(k)
            if isinstance(entry, dict):
                s = entry.get("score")
                if isinstance(s, int):
                    dim_totals[k].append(s)

    def _avg(xs: list[int]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "mean_score": _avg(scored),
        "redundant_turns_n": redundant_total,
        "unrecovered_turns_n": unrecovered_total,
        "dimension_avg": {k: _avg(v) for k, v in dim_totals.items()},
        "n_records": len(records),
        "n_graded": n_graded,
        "judge_prompt_id": CHAT_TRAJECTORY_JUDGE.identifier(),
    }
