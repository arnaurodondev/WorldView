#!/usr/bin/env python3
"""Quality-based LLM-judge for the chat-quality benchmark (PLAN-0104 W33).

Replaces the word-count-driven `derive_pass_fail` heuristics with a structured
rubric scored by an LLM. The judge consumes:

* the **prompt** (what the user asked),
* a per-question **rubric** declared in ``questions.yaml``
  (``expected_tools``, ``required_facts``, ``expected_depth``,
  ``appropriate_refusal_ok``),
* the captured **answer_text**,
* the captured **tool_call + tool_result** sequence,

and returns a structured verdict on four dimensions (each 0-25):

* **tool_use**       — were the right tools called for the question's intent?
* **grounding**      — are quantitative claims traceable to tool outputs?
                       any fabrication?
* **framing**        — does answer depth match the question's depth?
                       (shallow Qs get a short answer; deep Qs get structure)
* **refusal_judgment** — when the answer is a refusal, is it appropriate
                       given tool outputs? (refusing when data is present →
                       bad; refusing when data is genuinely missing → good)

Final ``score = sum(dimensions)``; verdict mapping:

* ``score >= 85``  → ``PASS``
* ``score 60-84``  → ``WARN``
* ``score <  60``  → ``FAIL``

Design notes
------------
* The judge is **additive** — the existing word-count heuristics still run for
  backward compatibility; the judge result goes into a separate
  ``_judge_summary.json`` and ``judge`` block in each ``q_<id>.json``.
* The runner exposes ``--judge-only --runs-dir <path>`` for **offline
  re-grading** of an existing run directory: we read the stored
  ``q_<id>.json`` files and call the judge using their captured artefacts.
  This lets us iterate on the rubric without burning chat-API calls.
* The judge call uses DeepInfra's OpenAI-compatible endpoint with
  ``response_format=json_object`` + ``temperature=0`` for determinism. The
  HTTP client is a thin ``httpx.Client`` to avoid pulling the async
  ``ml_clients`` stack into a sync script.
* All LLM calls are gated by ``DEEPINFRA_API_KEY``; if unset, the judge
  returns a ``SKIPPED`` verdict so the script still produces artefacts
  in offline / CI environments.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

# Import the canonical judge prompt from libs/prompts. The prompt has no
# parameters; we use .render() (not .template) because the source escapes
# literal JSON braces in the OUTPUT example block as ``{{`` / ``}}`` for the
# brace guard (MN-5). .render() with no kwargs collapses them back to single
# braces. v2.0 (2026-06-08) BREAKING: per-dim key ``reason``→``feedback`` and
# top-level ``notes``→``reviewer_summary``; this script reads BOTH for one
# release of back-compat.
from prompts.evaluation import CHAT_QUALITY_JUDGE

# Default judge model — Llama 3.1 8B Instruct is cheap, fast, and good enough
# at structured-JSON grading. We pin a specific revision via env var when
# stronger judgement is required (e.g. for thesis evaluation runs).
_DEFAULT_JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
_DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"

# Dimension keys and the max score each one carries. The runner stores
# individual scores so we can compute per-dimension averages in the summary.
DIMENSION_KEYS: tuple[str, ...] = (
    "tool_use",
    "grounding",
    "framing",
    "refusal_judgment",
)
_MAX_PER_DIMENSION = 25
_MAX_TOTAL = _MAX_PER_DIMENSION * len(DIMENSION_KEYS)  # 100

# Verdict thresholds — applied to the **summed** score (0-100). The bands
# match the heuristic buckets used by the legacy `derive_pass_fail` so the
# two reports remain comparable.
_PASS_THRESHOLD = 85
_WARN_THRESHOLD = 60

# PLAN-0110 W3 (FR-4 / FR-12): the tiered verdict SCHEMA version. Distinct from
# the judge PROMPT version (``CHAT_QUALITY_JUDGE.version``) — this bumps only
# when the Python scoring schema changes shape (e.g. a new InvariantCode, a
# banding change), so a longitudinal trend store (W4) can detect a
# discontinuity in the verdict objects independently of a prompt re-word. W1
# introduced the tiered schema (1.0); W3 added the populated numeric
# cross-check + GROUNDING_CONTRADICTED wiring → bump to 1.1.
VERDICT_MODEL_VERSION = "1.1"

# ── Hardening constants (audit 2026-06-11 F1/F3/F4) ───────────────────────
# The benchmark's original verdict was a pure ``sum(4 dims)`` with PASS>=85.
# That let a catastrophic single-dimension failure (e.g. grounding=10 =
# "fabricated") still PASS, and let degenerate / non-answers score 100. The
# three guards below run in the Python SCORING LAYER (not the LLM prompt) so
# they are deterministic, longitudinally stable, and cannot be argued away by
# a miscalibrated judge model.

# F1 — GROUNDING VETO. A financial-research agent's worst outcome is a
# fabricated number. If the judge scores grounding below this floor, the
# answer is FAIL regardless of how the other three dimensions sum. 12 is one
# notch below the prompt's own "presumed grounded → 20-25" band and above the
# "honest partial (15-22)" band, so it fires only on genuine fabrication
# signals (the prompt awards <12 only for cases (a)/(b)/(c) in its grounding
# rubric — claims against missing/out-of-scope tool data).
GROUNDING_VETO_FLOOR = 12

# F3 — control tokens that must NEVER appear in a user-facing answer. Their
# presence means the chat layer leaked the model's internal tool-call / think
# scaffolding into the rendered answer (E3 in the audit). We match BOTH the
# OPENING and CLOSING forms of every tag — the strict-validation pass found a
# leaked ``</think>`` that the opening-only ``<think`` substring missed (gap
# A). The regex is anchored on ``<`` + optional ``/`` so ``<think>`` and
# ``</think>`` (and the closing forms of function/invoke/parameter/
# function_calls/function_results) all match. These are never valid prose in
# any real financial answer.
_CONTROL_TOKEN_NAMES: tuple[str, ...] = (
    "function_calls",
    "function_results",
    "function",
    "invoke",
    "parameter",
    "think",
)
# Match ``<name`` or ``</name`` for each control-tag name. ``function`` is a
# prefix of ``function_calls`` / ``function_results`` so listing it last in
# the alternation is harmless — any of the three matches the leak. We do not
# require the closing ``>`` so partial / truncated leaks (``<invoke name=``)
# still trip.
_LEAKED_CONTROL_TOKEN_RE = re.compile(
    r"</?(?:" + "|".join(re.escape(n) for n in _CONTROL_TOKEN_NAMES) + r")\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Tiered verdict taxonomy (PLAN-0110 W1 / PRD-0091 §6.5, AD-1)
# --------------------------------------------------------------------------
#
# AD-1 is the lexicographic verdict model. The OLD model summed four soft 0-25
# LLM dimensions and called >=85 a PASS — which let a fabricated answer (one
# bad dim) still PASS, and let leaked control tokens / truncation slip through
# because the LLM judge mis-scores exactly those catastrophic cases (F3 audit).
#
# The NEW model is a GATE-then-BAND pipeline:
#   1. Deterministic, LLM-free INVARIANT GATES run FIRST. Any violated gate is
#      an unconditional FAIL — the soft score can never "buy back" a hard
#      failure (a 95/100 answer that leaks ``<function`` is still FAIL).
#   2. ONLY answers that clear every gate are BANDED by the additive
#      ``quality_score`` (== the old sum, FR-4 continuity) into
#      STRONG/PASS/WEAK/FAIL.
#
# The four objects below are the principled vocabulary for that pipeline. They
# REPLACE the ad-hoc ``veto`` dict at the structured-field level, but we keep
# emitting the legacy keys alongside them for one release (back-compat for the
# runner + artefact readers — W5 migrates those).


class Verdict(str, Enum):
    """The composed, tiered verdict an answer receives (PRD-0091 §6.5).

    ``str`` mix-in so a ``Verdict`` serialises to its plain string value in JSON
    artefacts (``json.dumps(Verdict.PASS) == '"PASS"'``) and compares equal to
    the bare string — important because legacy artefact readers compare against
    ``"PASS"``/``"FAIL"`` literals.

    Ordering (STRONG > PASS > WEAK > FAIL) is defined by ``_RANK`` below rather
    than enum declaration order so it is explicit and testable.
    """

    STRONG = "STRONG"  # gates pass + quality_score >= 90 — top band
    PASS = "PASS"  # noqa: S105 — enum value, not a secret. gates pass + quality_score >= 75 (acceptance)
    WEAK = "WEAK"  # gates pass + quality_score 60-74 — needs work, not a hard fail
    FAIL = "FAIL"  # any hard invariant violated, OR quality_score < 60

    @property
    def rank(self) -> int:
        """Severity-ordered rank: STRONG (best, 3) .. FAIL (worst, 0)."""
        return _VERDICT_RANK[self]


# Best-to-worst rank. Used by the report (W5) + tests to assert the ordering
# STRONG > PASS > WEAK > FAIL without relying on enum declaration order.
_VERDICT_RANK: dict[Verdict, int] = {
    Verdict.STRONG: 3,
    Verdict.PASS: 2,
    Verdict.WEAK: 1,
    Verdict.FAIL: 0,
}

# Band thresholds applied to ``quality_score`` (0-100) ONLY when no gate fired
# (PRD-0091 §6.5 table). These are intentionally DISTINCT from the legacy
# ``_PASS_THRESHOLD``/``_WARN_THRESHOLD`` (85/60) above: the tiered model adds a
# STRONG top band and renames WARN→WEAK with a 75 acceptance line. The legacy
# 85/60 bands still drive the back-compat ``verdict`` string for one release.
_BAND_STRONG = 90
_BAND_PASS = 75
_BAND_WEAK = 60  # below this (and gates clear) → FAIL


class InvariantCode(str, Enum):
    """Deterministic hard-FAIL invariant gates (PRD-0091 §6.5, FR-3).

    Each code is one catastrophic, deterministically-detectable failure class.
    A gate "fires" when the invariant is VIOLATED → the verdict is FAIL with
    this code as ``fail_reason``. ``str`` mix-in for JSON-friendly serialisation
    + dict keys that round-trip through ``json.dumps``.
    """

    CONTROL_TOKEN_LEAK = "CONTROL_TOKEN_LEAK"  # noqa: S105 — enum value: <function/<invoke/<think or fenced-JSON stub
    TRUNCATED = "TRUNCATED"  # mid-token/table/call cut-off (digit-drop, unbalanced markdown)
    EMPTY_AFTER_TOOLS = "EMPTY_AFTER_TOOLS"  # tool ok+items>=1 but no substantive synthesis
    INFRA_NON_ANSWER = "INFRA_NON_ANSWER"  # all relevant tools transport_error/5xx + apology
    GROUNDING_CONTRADICTED = "GROUNDING_CONTRADICTED"  # numeric claim contradicted by a sample (W3)
    GROUNDING_FLOOR = "GROUNDING_FLOOR"  # judge grounding sub-dim < GROUNDING_VETO_FLOOR


# Priority order for choosing the SINGLE ``fail_reason`` when several gates fire
# at once (PRD-0091 §6.7 / plan T-W1-03). Most-severe / most-diagnostic first:
# a contradicted number is the worst outcome, then leaked scaffolding, then a
# truncated/garbled body, then an infra non-answer, then empty-after-tools,
# then the soft grounding floor. Order matters: an answer that both leaks a
# token AND sits below the grounding floor is reported as CONTROL_TOKEN_LEAK.
_INVARIANT_PRIORITY: tuple[InvariantCode, ...] = (
    InvariantCode.GROUNDING_CONTRADICTED,
    InvariantCode.CONTROL_TOKEN_LEAK,
    InvariantCode.TRUNCATED,
    InvariantCode.INFRA_NON_ANSWER,
    InvariantCode.EMPTY_AFTER_TOOLS,
    InvariantCode.GROUNDING_FLOOR,
)

# Map the existing string reasons emitted by ``detect_degenerate_answer`` to
# the InvariantCode they represent. This is the REFACTOR seam (T-W1-02): the
# proven detection logic is untouched; we only re-label its output. Keeping the
# map explicit (rather than burying it in the gate) makes the routing auditable
# and means a new detector reason fails loudly here rather than silently.
_DEGENERATE_REASON_TO_CODE: dict[str, InvariantCode] = {
    "leaked_control_tokens": InvariantCode.CONTROL_TOKEN_LEAK,
    "tool_call_stub": InvariantCode.CONTROL_TOKEN_LEAK,
    "digit_drop_corruption": InvariantCode.TRUNCATED,
    "empty_after_tool": InvariantCode.EMPTY_AFTER_TOOLS,
    # A plain empty answer with no successful tool is still an "empty answer"
    # gate violation; EMPTY_AFTER_TOOLS is the closest principled code.
    "empty_answer": InvariantCode.EMPTY_AFTER_TOOLS,
}


@dataclass(frozen=True)
class GroundingCheck:
    """Outcome of the programmatic numeric claim↔sample cross-check (FR-6).

    POPULATED IN W3 (numeric cross-check). In W1 we always construct a zeroed
    ``presumed`` instance — no grounding samples exist yet, so nothing can be
    matched or contradicted. ``contradicted`` is the field the
    ``GROUNDING_CONTRADICTED`` gate reads; until W3 it is always 0, so that gate
    never fires in W1.
    """

    matched: int = 0  # numeric claims that matched a sampled value within tolerance
    unmatched: int = 0  # claims with no corresponding sample (no evidence either way)
    contradicted: int = 0  # claims a sample disproves → trips GROUNDING_CONTRADICTED
    examples: list[dict[str, Any]] = field(default_factory=list)  # {claim, nearest_sample, delta}
    evidence_mode: str = "presumed"  # "verified" (samples present) | "presumed" (legacy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "unmatched": self.unmatched,
            "contradicted": self.contradicted,
            "examples": list(self.examples),
            "evidence_mode": self.evidence_mode,
        }


@dataclass(frozen=True)
class VerdictDecision:
    """The composed, tiered verdict (PRD-0091 §6.5) — the W1 output object.

    Invariants (asserted by tests):
      * ``verdict == Verdict.FAIL`` IFF (``fail_reason is not None``) OR
        (``quality_score < _BAND_WEAK``). I.e. a FAIL always has either a fired
        gate or a sub-60 soft score, and any answer with a fired gate / sub-60
        score is a FAIL.
      * ``quality_score == sum(dimensions.values())`` (FR-4 continuity — equals
        the old additive sum exactly; no rescaling).
    """

    verdict: Verdict
    quality_score: int  # 0-100, additive soft score (== sum of dimensions)
    fail_reason: InvariantCode | None  # which gate fired (None unless a gate forced FAIL)
    gate_results: dict[InvariantCode, bool]  # per-invariant PASS (True) / VIOLATED (False)
    grounding_check: GroundingCheck
    dimensions: dict[str, int]  # raw judge sub-scores (4 keys, each 0-25)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form for the artefact + trend store (W4).

        ``feedback_audit_returned_value_persistence``: ``gate_results`` and
        ``fail_reason`` MUST reach the artefact, not just a counter — so they
        are emitted here in full.
        """
        return {
            "verdict": self.verdict.value,
            "quality_score": self.quality_score,
            "fail_reason": self.fail_reason.value if self.fail_reason is not None else None,
            # gate_results keys are InvariantCode (str enum) → use ``.value`` so
            # the JSON keys are plain strings, not ``"InvariantCode.X"`` reprs.
            "gate_results": {code.value: passed for code, passed in self.gate_results.items()},
            "grounding_check": self.grounding_check.to_dict(),
            "dimensions": dict(self.dimensions),
        }


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rubric:
    """Per-question grading rubric (loaded from `questions.yaml`).

    All fields are optional so the judge can still grade questions that have
    no rubric block — in that case it falls back to a generic prompt that
    asks the LLM to assess plausibility only.
    """

    expected_tools: list[str] = field(default_factory=list)
    # F7 (audit 2026-06-11): ``required_facts`` / ``forbidden_facts`` are
    # carried for back-compat with the YAML catalogue + the schema-lint test,
    # but they are DELIBERATELY NOT wired into the judge prompt or the scoring
    # layer. The catalogue values are SYMBOLIC placeholder identifiers
    # (e.g. ``pe_ratio_value``, ``fabricated_period``), NOT literal answer
    # substrings, so a deterministic must-mention / must-not-say check against
    # them would be meaningless (and an LLM semantic check would require
    # bumping the longitudinally-frozen judge prompt + rewriting every smoke
    # question to use concrete checkable strings — out of scope here). We keep
    # the fields inert rather than implying coverage that does not exist.
    # TODO(PRD-scoring-redesign): if/when the catalogue is migrated to
    # concrete checkable strings, wire required/forbidden facts into the judge
    # as explicit must-mention / must-not-say semantic checks here.
    required_facts: list[str] = field(default_factory=list)
    forbidden_facts: list[str] = field(default_factory=list)
    expected_depth: str = "medium"  # shallow | medium | deep
    appropriate_refusal_ok: bool = False

    @classmethod
    def from_question(cls, q: dict[str, Any]) -> Rubric:
        """Build from a `questions.yaml` entry; tolerates missing `rubric:`."""
        raw = q.get("rubric") or {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            expected_tools=list(raw.get("expected_tools") or []),
            required_facts=list(raw.get("required_facts") or []),
            forbidden_facts=list(raw.get("forbidden_facts") or []),
            expected_depth=str(raw.get("expected_depth") or "medium"),
            appropriate_refusal_ok=bool(raw.get("appropriate_refusal_ok", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_tools": list(self.expected_tools),
            "required_facts": list(self.required_facts),
            "forbidden_facts": list(self.forbidden_facts),
            "expected_depth": self.expected_depth,
            "appropriate_refusal_ok": self.appropriate_refusal_ok,
        }


@dataclass(frozen=True)
class JudgeInput:
    """Concise carrier of everything the LLM judge needs to grade one Q."""

    prompt: str
    rubric: Rubric
    answer_text: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]


# --------------------------------------------------------------------------
# Optional LLM client (httpx + DeepInfra) wrapped behind a Protocol so unit
# tests can inject a mock without monkeypatching the network layer.
# --------------------------------------------------------------------------


class JudgeLLM(Protocol):
    """Callable LLM judge. Receives `(system, user)` strings, returns raw JSON."""

    def __call__(self, *, system: str, user: str) -> str: ...


def _build_default_llm(*, api_key: str | None, model: str, base_url: str) -> JudgeLLM | None:
    """Build the default DeepInfra-backed judge LLM, or None if no API key."""
    if not api_key:
        return None

    try:
        import httpx  # local import — keeps the module importable without httpx
    except ImportError:
        return None

    def _call(*, system: str, user: str) -> str:
        # We use a one-shot client so the script doesn't have to manage a
        # persistent connection pool (judge calls are infrequent and serial).
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    # response_format forces the model to emit a valid JSON
                    # object server-side — no markdown fences, no preamble.
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            return str(body["choices"][0]["message"]["content"] or "")

    return _call


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------


# Use the canonical PromptTemplate from libs/prompts. The source escapes the
# literal JSON braces in the OUTPUT example as ``{{`` / ``}}`` so we go
# through .render() — str.format_map collapses them back to single braces.
# The PromptTemplate wrapper gives us version + content_hash + identifier()
# for artefact persistence (judge_prompt_id in q_<id>.json + _judge_summary).
_SYSTEM_PROMPT = CHAT_QUALITY_JUDGE.render()


def _build_user_prompt(inp: JudgeInput) -> str:
    """Compose the per-call user message — concise so token cost stays low."""
    # We pre-summarise the tool sequence so the judge sees a flat trace rather
    # than the raw SSE event log. tool_results often carry only status +
    # item_count from the current SSE schema, which is intentionally compact
    # — the judge uses these as evidence of "data was/was-not available".
    tool_trace_lines: list[str] = []
    # F8 (audit 2026-06-11): pair each call to its result by TOOL NAME / call
    # id, NOT by positional index. The SSE stream does not guarantee that
    # ``tool_results[i]`` belongs to ``tool_calls[i]`` — multiple calls,
    # interleaved or dropped result events, and retries all break the
    # positional assumption and mislabel the evidence the judge reasons over.
    # We consume each result at most once (a name can be called twice) so a
    # repeated tool still aligns left-to-right within that name's results.
    remaining_results = list(inp.tool_results)

    def _pop_result_for(call: dict[str, Any]) -> dict[str, Any] | None:
        """Return + consume the first unmatched result for this call.

        Match priority: explicit call id (``call_id`` / ``id`` on both sides)
        first, then tool name. Falls back to None when nothing matches (the
        judge then sees ``(no result event)`` rather than a wrong result).
        """
        call_id = call.get("call_id") or call.get("id")
        name = call.get("name")
        # 1) id-based pairing (most precise when the SSE schema carries ids).
        if call_id is not None:
            for idx, res in enumerate(remaining_results):
                if (res.get("call_id") or res.get("id")) == call_id:
                    return remaining_results.pop(idx)
        # 2) name-based pairing — first unconsumed result for this tool name.
        for idx, res in enumerate(remaining_results):
            if res.get("tool") == name or res.get("name") == name:
                return remaining_results.pop(idx)
        return None

    # Build a per-call/result line: "call N: <tool>(args) -> status item_count=K"
    for i, tc in enumerate(inp.tool_calls):
        name = tc.get("name", "?")
        args = tc.get("arguments") or {}
        # Keep arg formatting compact; we only care about which keys + scalar
        # values were passed, not nested JSON.
        args_repr = ", ".join(f"{k}={_short_repr(v)}" for k, v in args.items())
        matching = _pop_result_for(tc)
        if matching:
            status = matching.get("status", "?")
            item_count = matching.get("item_count", "?")
            tool_trace_lines.append(f"  call {i + 1}: {name}({args_repr}) -> status={status} items={item_count}")
        else:
            tool_trace_lines.append(f"  call {i + 1}: {name}({args_repr}) -> (no result event)")

    # Any results that never matched a call (e.g. interleaved / orphaned
    # events) are still surfaced so the judge sees the full evidence set.
    for res in remaining_results:
        rname = res.get("tool") or res.get("name") or "?"
        status = res.get("status", "?")
        item_count = res.get("item_count", "?")
        tool_trace_lines.append(f"  (unpaired result): {rname} -> status={status} items={item_count}")

    tool_trace = "\n".join(tool_trace_lines) if tool_trace_lines else "  (no tool calls)"

    # PLAN-0110 W3 (T-W3-03 / FR-7): render the captured GROUNDING SAMPLE values
    # so the judge can reason over the SAME evidence the deterministic
    # cross-check uses (feedback_prompt_input_mismatch — one source of truth).
    # The block is omitted entirely when no tool_result carried a sample, which
    # keeps the v2.x trace-only prompt byte-identical for sample-free runs and
    # signals the judge's "presumed band" path.
    grounding_block = _build_grounding_sample_block(inp.tool_results)

    return (
        f"QUESTION:\n{inp.prompt}\n\n"
        f"RUBRIC:\n{json.dumps(inp.rubric.to_dict(), indent=2)}\n\n"
        f"TOOL TRACE:\n{tool_trace}\n\n"
        f"{grounding_block}"
        f"ANSWER:\n{inp.answer_text or '<empty>'}\n"
    )


def _build_grounding_sample_block(tool_results: list[dict[str, Any]] | None) -> str:
    """Render the captured ``grounding_sample`` field values for the judge prompt.

    Returns ``"GROUNDING SAMPLE:\\n  <tool>.<field> = <value>\\n...\\n\\n"`` when
    at least one tool_result carried a W2 ``grounding_sample`` with fields, else
    an EMPTY string (the block is omitted → the v2.x trace-only prompt is
    byte-identical for sample-free runs, and the judge takes its "presumed band"
    path). The values shown here are the SAME ones the deterministic
    ``cross_check_grounding`` reads, so the prompt and the cross-check never
    diverge (feedback_prompt_input_mismatch).
    """
    lines: list[str] = []
    for tr in tool_results or []:
        sample = tr.get("grounding_sample")
        if not isinstance(sample, dict):
            continue
        fields = sample.get("fields")
        if not isinstance(fields, dict) or not fields:
            continue
        tool_name = str(tr.get("tool") or "?")
        for fname, fval in fields.items():
            lines.append(f"  {tool_name}.{fname} = {fval}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        "GROUNDING SAMPLE (actual values the tools returned — use as evidence; "
        "a contradicted number is hard-failed deterministically):\n"
        f"{body}\n\n"
    )


def _short_repr(v: Any) -> str:
    """Compact repr of a tool-arg value, capped at 60 chars."""
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= 60 else s[:57] + "..."


# --------------------------------------------------------------------------
# Deterministic pre-checks (run BEFORE the LLM judge)
# --------------------------------------------------------------------------
#
# The LLM judge is calibrated to grade QUALITY of a coherent answer. It is the
# wrong tool to detect that the "answer" is not a real answer at all — a
# leaked tool-call stub, a truncated mid-call fragment, an empty string after
# a successful tool, or an infra-failure non-answer. Those are deterministic
# string/state checks; running them here lets us HARD-FAIL such cases before
# (and independent of) the LLM, with a precise, model-agnostic reason. This
# directly closes the F3 ("degenerate answers score full marks") and F4
# ("tool failures reported as perfect quality") findings in the 2026-06-11
# audit.

# A "tool-call stub" is an answer whose ENTIRE body is essentially a fenced
# JSON object or a tool-invocation directive with no prose answer for the
# user. We detect the digit-drop corruption pattern (E6) conservatively to
# avoid false positives on legitimate prose.
#
# Leading-digit-drop signatures (E6): the streaming layer occasionally drops
# the first character of a token, producing artefacts a human never writes:
#   * ``**,095 BTC**``  — a bolded number that starts with a comma (the
#     leading digits were deleted).
#   * ``approximately **,`` — "approximately" immediately followed by a
#     comma-led number.
# We require the comma to be bound to surrounding markdown/number context so
# ordinary clause commas ("Apple, Inc.") never trip the check.
_DIGIT_DROP_PATTERNS: tuple[re.Pattern[str], ...] = (
    # ``**,095`` — bold marker then a comma then digits (dropped leading int).
    re.compile(r"\*\*,\d{2,}"),
    # a standalone token that is just ``,DDD`` preceded by whitespace and a
    # currency/word boundary, e.g. " **,095 BTC" or " ,095 BTC" — but NOT a
    # normal thousands group like "1,095" (which has a digit before the comma).
    re.compile(r"(?:^|[\s*$£€])[,]\d{3}\b"),
    # Gap D (strict-validation): "last  quarters" — a DOUBLE space immediately
    # before a unit noun is the space-where-a-digit-was form of the digit drop
    # ("last 8 quarters" → "last  quarters"). Restricted to a small set of
    # unit nouns so ordinary double spaces in prose never trip it. This form is
    # UNAMBIGUOUS — verified absent from every good (negative) fixture — so it
    # is safe to fire standalone.
    re.compile(r"\b\w+\s{2}(?:quarter|hop|year|month|week|day|period)s?\b", re.IGNORECASE),
)

# Gap D — the AMBIGUOUS space-where-a-digit-was forms. ``( quarters)`` /
# ``( hop)`` (open-paren + space + word) and ``Path :`` / ``**Step :**`` (word
# + space-colon) ALSO appear in GENUINELY-GOOD answers (the OpenAI↔MSFT path
# answers legitimately write "Path  — Direct Partnership ( hop)" with their own
# digit drops while still DELIVERING data). So these forms must NOT fire on
# their own — they are only corroborating evidence inside the "describes calls
# but delivers no data" stub check (gap B). Keeping them here (not in the
# standalone tuple above) is the whole point of the strict-validation fix.
_DIGIT_DROP_WEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\(\s(?:quarter|hop|year|month|week|day|period|row)s?\b", re.IGNORECASE),
    re.compile(r"(?:\*\*Step|Path|Step)\s+:", re.IGNORECASE),
)

# Gap B — signatures of an answer whose deliverable is just DESCRIBING tool
# invocations rather than presenting their results. Each is a phrase a model
# emits when it narrates "I will call X" instead of answering.
_TOOL_CALL_DESCRIPTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\*\*Tool calls?:\*\*", re.IGNORECASE),  # "**Tool calls:**"
    re.compile(r"\bCalling\s+`[a-z_]+`", re.IGNORECASE),  # "Calling `get_x`"
    re.compile(r"\*\*Calling\s+`[a-z_]+`", re.IGNORECASE),  # "**Calling `get_x`"
    re.compile(r"\*\*Step\b[^*]*:\s*", re.IGNORECASE),  # "**Step : ...**" / "**Step 2: ...**"
    # enumerated "1. `get_*`/`search_*`/`query_*` for <X>" call list lines.
    re.compile(r"^\s*\d+\.\s*`(?:get|search|query|screen|traverse)_[a-z_]+`", re.IGNORECASE | re.MULTILINE),
)

# Gap C — INVALID fenced-JSON signatures: a JSON object with a dropped value
# (``"periods": ,`` / ``": ]`` / ``": }``) is a tool-arg echo, not an answer.
_INVALID_JSON_VALUE_DROP_RE = re.compile(r":\s*(?:,|\]|\})")

# Markers that an answer actually DELIVERS substantive content (citations,
# real magnitudes, confidence/row references). Used as the discriminator that
# protects the good (negative) fixtures from the stub / weak-digit-drop checks:
# the good answers MENTION tools but DELIVER data; the stubs only describe
# calls. A single delivery marker is enough to spare an answer from gap B/weak-D.
_DELIVERY_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[(?:\d+|[a-z_]+,?\s*row\s*\d+)\]", re.IGNORECASE),  # [3] / [traverse_graph, row 0]
    re.compile(r"\bconfidence[:\s]+\*?\*?\d", re.IGNORECASE),  # "confidence: 1.0"
    re.compile(r"[$£€]\s?\d"),  # "$38 billion"
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:billion|million|trillion|%)", re.IGNORECASE),
)


def detect_degenerate_answer(
    answer_text: str,
    tool_results: list[dict[str, Any]] | None = None,
) -> str | None:
    """Deterministically flag a NON-answer; return a reason or ``None``.

    Returns a short machine-stable reason string when the answer is
    degenerate (and must HARD-FAIL the verdict before the LLM judge), or
    ``None`` when the answer is a plausibly-real answer the LLM should grade.

    Detected failure classes (all from the 2026-06-11 audit example run):
      * ``leaked_control_tokens`` — ``<function``/``<invoke``/``<parameter``/
        ``<think`` scaffolding (OPENING or CLOSING form) rendered as the
        user-facing answer (E3 + strict-validation gap A).
      * ``tool_call_stub`` — the answer's deliverable is just a fenced-JSON /
        tool-call directive, OR a markdown DESCRIPTION of tool calls / steps
        with no data body (E3 + gaps B/C).
      * ``empty_after_tool`` — empty/whitespace answer after >=1 successful
        tool call (data was fetched, nothing was said).
      * ``empty_answer`` — empty/whitespace with no successful tool either.
      * ``digit_drop_corruption`` — the leading-digit-drop rendering bug
        (E6 + gap D space-where-a-digit-was forms).

    Conservative by design: ambiguous-but-prose answers return ``None`` so the
    LLM judge still grades them. Discriminator vs genuinely-good answers: good
    answers MENTION tools / write structured paths but DELIVER data (citations,
    magnitudes, confidence/row refs); stubs only DESCRIBE the calls. The
    ``_answer_delivers_data`` check protects the good answers from the stub and
    weak-digit-drop heuristics.
    """
    raw = answer_text or ""
    # Strip the transparency banner the chat layer appends — it is appended to
    # BOTH good and degenerate answers and must not mask a stub underneath.
    body = raw
    _BANNER = "⚠ Some numbers could not be verified against retrieved data"
    if _BANNER in body:
        body = body.replace(_BANNER, "")
    stripped = body.strip()

    results = tool_results or []
    had_ok_tool = any(
        (r.get("status") == "ok") and isinstance(r.get("item_count"), int) and r.get("item_count", 0) >= 1
        for r in results
    )

    # 1) Empty answer (distinguish "empty after a real tool fetch" — worse).
    if not stripped:
        return "empty_after_tool" if had_ok_tool else "empty_answer"

    # 2) Leaked control tokens (gap A) — any occurrence (opening OR closing
    #    tag) is fatal. Never valid prose; the tool-call / think scaffolding
    #    leaked into the answer.
    if _LEAKED_CONTROL_TOKEN_RE.search(stripped):
        return "leaked_control_tokens"

    # Does the answer actually DELIVER substantive content? This is the
    # discriminator that protects the GOOD answers (which mention tools but
    # present real data) from the stub + weak-digit-drop heuristics below.
    delivers = _answer_delivers_data(stripped)

    # 3a) Whole-answer fenced-JSON / bare-JSON stub (existing E3 check).
    fence_blocks = re.findall(r"```.*?```", stripped, flags=re.DOTALL)
    if fence_blocks:
        non_ws = len(re.sub(r"\s", "", stripped))
        fence_non_ws = len(re.sub(r"\s", "", "".join(fence_blocks)))
        if non_ws > 0 and fence_non_ws / non_ws >= 0.8:
            return "tool_call_stub"
        # 3b) Gap C — intro prose + fenced ```json whose contents are
        #     STRUCTURALLY INVALID with dropped values (``"periods": ,``).
        #     A valid JSON answer is fine; a broken tool-arg echo is a stub.
        for fb in fence_blocks:
            inner = re.sub(r"^```(?:json)?|```$", "", fb.strip()).strip()
            if _INVALID_JSON_VALUE_DROP_RE.search(inner) and not delivers:
                return "tool_call_stub"
    # A bare JSON object as the entire answer (no fence) is also a stub.
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            json.loads(stripped)
            return "tool_call_stub"
        except json.JSONDecodeError:
            pass

    # 3c) Gap B — markdown tool-call / step DESCRIPTION stub. The answer's
    #     body just narrates which tools/steps it would call and presents no
    #     results. We require (i) >=1 call-description signature AND (ii) NO
    #     substantive delivery. The "no delivery" half is what spares the good
    #     OpenAI↔MSFT path answers (they mention tools but deliver cited data).
    #     We also strengthen with the SSE signal: if expected tools returned
    #     data (ok/items>=1) yet the answer presents none, it is a stub.
    if not delivers:
        desc_hits = sum(1 for p in _TOOL_CALL_DESCRIPTION_PATTERNS if p.search(stripped))
        if desc_hits:
            return "tool_call_stub"

    # 4) Leading-digit-drop corruption (E6 + gap D).
    #    4a) UNAMBIGUOUS forms fire standalone (verified absent from all good
    #        fixtures).
    for pat in _DIGIT_DROP_PATTERNS:
        if pat.search(stripped):
            return "digit_drop_corruption"
    #    4b) WEAK / AMBIGUOUS forms (``( hop)`` / ``Path :``) ONLY fire when the
    #        answer also fails to deliver data — these forms legitimately occur
    #        in good path answers, so they must be corroborated.
    if not delivers:
        for pat in _DIGIT_DROP_WEAK_PATTERNS:
            if pat.search(stripped):
                return "digit_drop_corruption"

    return None


def _answer_delivers_data(text: str) -> bool:
    """True when the answer presents SUBSTANTIVE content, not just call narration.

    A single delivery marker (citation, magnitude, confidence/row reference) is
    enough. This is the discriminator that keeps genuinely-good answers — which
    mention tools and write structured paths but DELIVER cited data — from
    tripping the markdown-stub and weak-digit-drop heuristics.
    """
    return any(p.search(text) for p in _DELIVERY_MARKERS)


def detect_tool_failure_nonanswer(
    answer_text: str,
    rubric: Rubric,
    tool_results: list[dict[str, Any]] | None = None,
) -> str | None:
    """Flag an INFRA-FAILURE non-answer that must not be scored as PASS (F4).

    Returns a reason string or ``None``. Fires when ALL hold:
      * the rubric marks ``appropriate_refusal_ok=false`` (the question is
        answerable — a non-answer here is a failure, not correct behaviour);
      * an EXPECTED tool's result shows an error / empty status (the agent
        could not get the data — e.g. the screener ``transport_error`` /
        HTTP 500 case in the audit, E2); and
      * the answer reads as a non-answer (a refusal / "cannot reach" apology
        rather than a substantive analysis).

    This is deliberately conservative — it only fires on the intersection of
    "question is answerable", "expected tool failed", and "no substantive
    answer was produced", so a graceful, correct refusal (rubric permits) or a
    successful answer is never penalised here.
    """
    if rubric.appropriate_refusal_ok:
        return None

    results = tool_results or []
    expected = set(rubric.expected_tools)
    # Status values that mean "the tool did not deliver usable data".
    _BAD_STATUSES = {"error", "transport_error", "timeout", "missing", "failed"}

    def _result_is_failure(r: dict[str, Any]) -> bool:
        status = str(r.get("status") or "")
        if status in _BAD_STATUSES:
            return True
        # ``empty`` / ok-with-zero-items counts as a non-delivery for an
        # EXPECTED tool on an answerable question.
        if status in {"empty", "ok"} and (r.get("item_count") or 0) == 0:
            return True
        return False

    # Did an expected tool fail to deliver? (If no expected tools are declared,
    # fall back to: did the ONLY tool called fail?)
    relevant = [r for r in results if (not expected) or (r.get("tool") in expected) or (r.get("name") in expected)]
    if not relevant:
        return None
    if not any(_result_is_failure(r) for r in relevant):
        return None

    # Is the answer a non-answer? Reuse the refusal-phrase shape plus the
    # "cannot reach / try again" infra-apology shape the audit flagged (E2).
    lowered = (answer_text or "").lower()
    _NONANSWER_MARKERS = (
        "cannot reach",
        "could not reach",
        "returned a 500",
        "500 error",
        "try again",
        "please retry",
        "i cannot find",
        "i am unable to",
        "i'm unable to",
        "data is not available",
        "no data was returned",
        "no results were returned",
    )
    if not any(m in lowered for m in _NONANSWER_MARKERS):
        return None

    return "tool_failure_nonanswer"


# --------------------------------------------------------------------------
# Deterministic invariant gate (PLAN-0110 W1 / T-W1-02)
# --------------------------------------------------------------------------
#
# ``evaluate_invariants`` is the SINGLE entry point that consolidates the three
# ad-hoc detectors above (degenerate-answer, tool-failure non-answer, grounding
# floor) into one toggleable gate that emits ``InvariantCode`` results. It does
# NOT re-implement any detection — it CALLS the existing functions and re-labels
# their output. The functions stay callable on their own (back-compat), so the
# existing degenerate/tool-failure unit tests keep passing unchanged (R19).
#
# Convention: a value of ``True`` in the returned dict means the invariant is
# SATISFIED (the gate PASSED); ``False`` means the invariant is VIOLATED (the
# gate FIRED → hard FAIL). Every one of the six codes is always present so the
# report (FR-3) can show each gate's individual pass/fail.

# The complete set of gates, in the canonical iteration order. Used to seed a
# fully-passing baseline so a disabled gate is reported as "passed" rather than
# missing from the dict.
_ALL_INVARIANTS: tuple[InvariantCode, ...] = (
    InvariantCode.CONTROL_TOKEN_LEAK,
    InvariantCode.TRUNCATED,
    InvariantCode.EMPTY_AFTER_TOOLS,
    InvariantCode.INFRA_NON_ANSWER,
    InvariantCode.GROUNDING_CONTRADICTED,
    InvariantCode.GROUNDING_FLOOR,
)


def evaluate_invariants(
    answer_text: str,
    tool_results: list[dict[str, Any]] | None,
    rubric: Rubric,
    grounding_check: GroundingCheck,
    *,
    grounding_score: int | None = None,
    enabled: set[InvariantCode] | None = None,
) -> dict[InvariantCode, bool]:
    """Run every deterministic invariant gate; return per-code pass/fail.

    ``True`` = invariant satisfied (gate passed). ``False`` = violated (FAIL).

    Parameters
    ----------
    answer_text, tool_results, rubric
        The same inputs the legacy detectors consume.
    grounding_check
        The numeric cross-check result (W3). ``contradicted > 0`` trips
        ``GROUNDING_CONTRADICTED``. In W1 this is always a zeroed ``presumed``
        instance, so that gate never fires here.
    grounding_score
        The judge's ``grounding`` sub-dimension (0-25). When below
        ``GROUNDING_VETO_FLOOR`` the ``GROUNDING_FLOOR`` gate fires. ``None``
        (judge skipped / no sub-score) → the floor gate cannot fire (we cannot
        know the grounding score, so we do not invent a failure).
    enabled
        The subset of ``InvariantCode`` that are active. ``None`` → all gates
        enabled (the default). A DISABLED gate is reported as ``True`` (passed)
        and never fires (FR-3 toggleability).

    This is LLM-free and runs even when ``DEEPINFRA_API_KEY`` is unset, so the
    verdict is meaningful in offline / CI mode (F-4).
    """
    active = _ALL_INVARIANTS if enabled is None else tuple(c for c in _ALL_INVARIANTS if c in enabled)

    # Seed every gate to PASS (True). Disabled gates stay True and are skipped
    # below, so they are reported as "passed" rather than absent.
    results: dict[InvariantCode, bool] = {code: True for code in _ALL_INVARIANTS}

    # 1) Degenerate-answer family → CONTROL_TOKEN_LEAK / TRUNCATED /
    #    EMPTY_AFTER_TOOLS. We call the EXISTING detector and re-label its
    #    single reason string to the matching code. Because the detector returns
    #    at most one reason, at most one of these three gates can fire from it.
    degenerate_reason = detect_degenerate_answer(answer_text, tool_results)
    if degenerate_reason is not None:
        code = _DEGENERATE_REASON_TO_CODE.get(degenerate_reason)
        # Only flip the gate if it maps to a code AND that gate is enabled.
        if code is not None and code in active:
            results[code] = False

    # 2) Infra non-answer → INFRA_NON_ANSWER, via the existing detector.
    if InvariantCode.INFRA_NON_ANSWER in active:
        if detect_tool_failure_nonanswer(answer_text, rubric, tool_results) is not None:
            results[InvariantCode.INFRA_NON_ANSWER] = False

    # 3) Grounding contradiction → GROUNDING_CONTRADICTED (W3-populated).
    if InvariantCode.GROUNDING_CONTRADICTED in active:
        if grounding_check.contradicted > 0:
            results[InvariantCode.GROUNDING_CONTRADICTED] = False

    # 4) Grounding floor → GROUNDING_FLOOR. Reuses the existing veto floor
    #    constant. Fires only when we HAVE a sub-score and it is below the floor
    #    (strict ``<`` — score == floor does NOT fire, matching the legacy veto).
    if InvariantCode.GROUNDING_FLOOR in active:
        if grounding_score is not None and grounding_score < GROUNDING_VETO_FLOOR:
            results[InvariantCode.GROUNDING_FLOOR] = False

    return results


def first_fired_invariant(gate_results: dict[InvariantCode, bool]) -> InvariantCode | None:
    """Return the highest-priority VIOLATED gate, or ``None`` if all passed.

    Priority order is ``_INVARIANT_PRIORITY`` (most-severe first). This is the
    single ``fail_reason`` reported when several gates fire at once.
    """
    for code in _INVARIANT_PRIORITY:
        if gate_results.get(code) is False:
            return code
    return None


# --------------------------------------------------------------------------
# Programmatic numeric grounding cross-check (PLAN-0110 W3 / T-W3-01, FR-6)
# --------------------------------------------------------------------------
#
# THE PROBLEM. The LLM judge alone cannot *verify* a number — it only sees a
# compact tool trace (``status=ok items=K``), not the raw payload. So a
# fabricated "$5.4B revenue" reads as plausibly-grounded to the judge. W2 fixed
# the EVIDENCE side: the backend now optionally streams a bounded, redacted
# ``grounding_sample`` ({fields:{field:str_value}, sampled_rows, total_rows,
# truncated}) on each ``tool_result`` frame, captured into the artefact.
#
# THIS MODULE is the DETERMINISTIC, LLM-free cross-check that consumes those
# samples. It extracts quantitative claims from the answer, associates each to a
# sampled field BY NAME, and classifies it:
#   * matched      — claim value ≈ the sampled value for that field (tolerance).
#   * contradicted — claim is associated to a field whose sampled value it
#                    DISPROVES (outside tolerance). This is the only class that
#                    HARD-FAILs (trips GROUNDING_CONTRADICTED). "Absent" never
#                    fails — we only fail on a value the tool actually returned.
#   * unmatched    — a number with no associated sampled field (no evidence
#                    either way; neutral).
#
# EVIDENCE MODE. When at least one sample is present we set
# ``evidence_mode="verified"`` (the check had real values to bite on). With NO
# samples we fall back to ``evidence_mode="presumed"`` (today's legacy
# behaviour) and NEVER fail — absence is not contradiction.
#
# FALSE-POSITIVE GUARDS (F-2, mandatory):
#   * numbers inside ``` fenced code / inline-code blocks are ignored (they are
#     usually tool-arg echoes / identifiers, not prose claims);
#   * a claim must be associated to the SAME field (the field name or a known
#     alias must appear near the number) — we never compare a revenue claim to
#     an EPS sample;
#   * equality is tolerance-based (relative + absolute) so rounding ("$46.7B" vs
#     46_742_000_000) and unit scaling (B/M/K) never trip a contradiction;
#   * 4-digit bare integers that look like calendar years (1900-2099) and values
#     that are part of a citation marker (``[... row 3]``) are not treated as
#     magnitude claims.

# Field-name aliases: the human-readable words an answer uses for a sampled
# field. The cross-check associates a number to a field when the field name OR
# one of its aliases appears within ``_CLAIM_FIELD_WINDOW`` chars of the number.
# Forward-compatible: unknown fields still match on their own name (snake_case
# split into words), so a brand-new sampled field needs no code change to be
# checkable — aliases only ADD natural-language synonyms.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "total revenue", "net revenue"),
    "eps": ("eps", "earnings per share"),
    "gross_profit": ("gross profit", "gross_profit"),
    "net_income": ("net income", "net_income", "earnings", "profit"),
    "pe_ratio": ("p/e", "pe ratio", "pe_ratio", "price-to-earnings", "price to earnings"),
    "forward_pe": ("forward p/e", "forward pe", "forward_pe"),
    "market_cap": ("market cap", "market capitalization", "market_cap"),
    "ebitda": ("ebitda",),
    "operating_income": ("operating income", "operating_income"),
    "free_cash_flow": ("free cash flow", "free_cash_flow", "fcf"),
    "dividend_yield": ("dividend yield", "dividend_yield"),
    "price": ("price", "share price", "trading at", "quote"),
}

# How far (chars) on EITHER side of a number we look for a field-name / alias to
# associate the claim with a sampled field. A short window keeps "revenue is X …
# eps is Y" from cross-associating.
_CLAIM_FIELD_WINDOW = 60

# Tolerance for declaring two magnitudes EQUAL (and therefore NOT contradicted).
# A claim within EITHER bound of a sample counts as matched. Generous on
# purpose: the answer rounds ("$46.7B" for 46_742_000_000) and the sample may be
# truncated — we only want to fire on a genuine, large discrepancy.
_GROUNDING_REL_TOL = 0.05  # 5% relative
_GROUNDING_ABS_TOL = 1e-6  # absolute floor so tiny values (0.0) compare sanely

# Scale suffixes the answer uses (case-insensitive). ``%`` is handled
# separately (a percentage claim is compared as a plain number, not scaled).
_SCALE_SUFFIX: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
}

# A numeric claim in PROSE: an optional ``$``, a mantissa with optional thousands
# separators + decimal, and an optional scale word/suffix. We deliberately do
# NOT match bare 4-digit years here (filtered in ``_is_yearlike``) or numbers
# embedded in identifiers (the fenced/inline-code strip removes those first).
#
# The suffix alternation is anchored so a scale LETTER is only consumed when it
# is a standalone token — ``(?![A-Za-z])`` after the short ``[kmbt]…`` form stops
# "2026 the" from being read as "2026 t(rillion)" (the ``t`` is the start of
# "the", not a suffix). ``%`` and the spelled-out words are unambiguous.
_CLAIM_NUMBER_RE = re.compile(
    r"\$?\s?(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?"
    r"(?P<suffix>%|trillion|billion|million|(?:bn|mn|tn|[kmbt]b?n?)(?![A-Za-z]))?",
    re.IGNORECASE,
)


def _strip_code_spans(text: str) -> str:
    """Blank out fenced + inline code so numbers inside them are not claims (F-2).

    We REPLACE the code spans with equal-length whitespace rather than deleting
    them so the character offsets of the surviving prose are unchanged — the
    field-association window logic relies on stable offsets.
    """
    out = text
    # Fenced ``` ... ``` blocks (DOTALL) first, then inline `...` spans.
    for pat in (re.compile(r"```.*?```", re.DOTALL), re.compile(r"`[^`]*`")):

        def _blank(m: re.Match[str]) -> str:
            return " " * len(m.group(0))

        out = pat.sub(_blank, out)
    return out


def _is_yearlike(raw: str, suffix: str) -> bool:
    """True when a bare 4-digit integer looks like a calendar year (1900-2099)."""
    if suffix:
        return False
    if "," in raw or "." in raw:
        return False
    try:
        v = int(raw)
    except ValueError:
        return False
    return 1900 <= v <= 2099 and len(raw) == 4


def _coerce_number(raw: str, suffix: str) -> float | None:
    """Parse a claim token (mantissa + optional scale suffix) to a float.

    ``"46.7", "B"`` → 46_700_000_000.0 ; ``"37.73", ""`` → 37.73 ;
    ``"5", "%"`` → 5.0 (percent is compared as a plain number).
    Returns ``None`` when the mantissa is not parseable.
    """
    cleaned = raw.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    sfx = (suffix or "").lower()
    if sfx and sfx != "%":
        value *= _SCALE_SUFFIX.get(sfx, 1.0)
    return value


def _sample_value_to_float(raw: Any) -> float | None:
    """Coerce a SAMPLED field value (a capped str from W2) to a float.

    Samples are strings (``str(value)[:32]``). They may carry their own scale
    suffix / ``$`` / ``%`` / commas (e.g. ``"46.7B"``, ``"$46,742,000,000"``,
    ``"37.73"``). We reuse the same claim regex so sample + claim are scaled
    identically (feedback_prompt_input_mismatch: one parser, one source).
    """
    s = str(raw).strip()
    if not s:
        return None
    m = _CLAIM_NUMBER_RE.fullmatch(s.strip())
    if m is None:
        # Fall back to a loose search (e.g. trailing units like "46.7B USD").
        m = _CLAIM_NUMBER_RE.search(s)
    if m is None:
        return None
    return _coerce_number(m.group("num"), m.group("suffix") or "")


def _values_within_tolerance(claim: float, sample: float) -> bool:
    """True when two magnitudes are equal within rel OR abs tolerance."""
    if claim == sample:
        return True
    diff = abs(claim - sample)
    if diff <= _GROUNDING_ABS_TOL:
        return True
    denom = max(abs(claim), abs(sample))
    return denom > 0 and (diff / denom) <= _GROUNDING_REL_TOL


def _collect_grounding_fields(tool_results: list[dict[str, Any]] | None) -> dict[str, list[float]]:
    """Gather ``{field: [sampled_float, ...]}`` from every captured grounding_sample.

    Reads the W2 ``grounding_sample.fields`` map off each tool_result entry. A
    field may appear in several tool results / sampled rows, so we keep a LIST of
    candidate values per field. Non-numeric / unparseable sample values are
    dropped (they cannot contradict a number).
    """
    fields: dict[str, list[float]] = {}
    for tr in tool_results or []:
        sample = tr.get("grounding_sample")
        if not isinstance(sample, dict):
            continue
        raw_fields = sample.get("fields")
        if not isinstance(raw_fields, dict):
            continue
        for fname, fval in raw_fields.items():
            num = _sample_value_to_float(fval)
            if num is None:
                continue
            fields.setdefault(str(fname), []).append(num)
    return fields


def _field_candidates(field: str) -> set[str]:
    """The lowercased name-forms (snake, spaced, aliases) that name ``field``."""
    candidates = {field.lower(), field.replace("_", " ").lower()}
    candidates.update(a.lower() for a in _FIELD_ALIASES.get(field, ()))
    return {c for c in candidates if c}


def _nearest_field(answer_lower: str, span: tuple[int, int], sampled_fields: list[str]) -> str | None:
    """Return the SINGLE SAMPLED field nearest the claim, or None.

    SAME-FIELD guard (F-2). We compute the closest field-name mention to the
    number across the FULL universe of known field names (``_FIELD_ALIASES`` +
    the sampled field names themselves), then:
      * if the nearest mention belongs to a SAMPLED field → return it;
      * if the nearest mention belongs to a known-but-NOT-sampled field (e.g.
        "EPS" when only ``revenue`` was sampled) → return None. The number is
        about a different metric we have no sample for; comparing it to a
        farther-away sampled field would be a false contradiction.
      * if no field name sits within the window → None (unmatched, neutral).

    This stops "Revenue was $46.7B; EPS came in at $5.40" from contradicting the
    revenue sample with the EPS number: "eps" is nearer the $5.40 than "revenue".
    """
    start, end = span
    lo = max(0, start - _CLAIM_FIELD_WINDOW)
    hi = min(len(answer_lower), end + _CLAIM_FIELD_WINDOW)

    # The universe of field names we recognise: every alias key + every sampled
    # field name. Map each name-form back to its canonical field key.
    universe: dict[str, str] = {}
    for canonical in set(sampled_fields) | set(_FIELD_ALIASES):
        for name in _field_candidates(canonical):
            # Prefer a sampled field's claim on a shared name-form so a sampled
            # field is never shadowed by an unsampled alias of the same word.
            if name not in universe or canonical in sampled_fields:
                universe[name] = canonical

    # Financial prose names the metric BEFORE the number ("revenue was X",
    # "EPS came in at Y"). So we prefer the nearest field name that PRECEDES the
    # claim; only if none precedes within the window do we fall back to the
    # nearest following name. Tracked separately so a closer FOLLOWING mention of
    # another metric never steals a number that its own preceding label owns.
    best_pre: tuple[int, str] | None = None  # (distance, canonical)
    best_post: tuple[int, str] | None = None
    for name, canonical in universe.items():
        search_from = lo
        while True:
            pos = answer_lower.find(name, search_from, hi)
            if pos == -1:
                break
            name_end = pos + len(name)
            search_from = pos + 1
            if name_end <= start:  # name PRECEDES the claim
                dist = start - name_end
                if best_pre is None or dist < best_pre[0]:
                    best_pre = (dist, canonical)
            elif pos >= end:  # name FOLLOWS the claim
                dist = pos - end
                if best_post is None or dist < best_post[0]:
                    best_post = (dist, canonical)
            else:  # overlapping (rare) → treat as a zero-distance preceding match
                if best_pre is None or 0 < best_pre[0]:
                    best_pre = (0, canonical)

    chosen = best_pre or best_post
    if chosen is not None and chosen[1] in sampled_fields:
        return chosen[1]
    return None


def cross_check_grounding(
    answer_text: str,
    tool_results: list[dict[str, Any]] | None,
) -> GroundingCheck:
    """Deterministically cross-check numeric claims against captured samples (FR-6).

    Returns a populated :class:`GroundingCheck`. ``contradicted > 0`` is what
    trips the ``GROUNDING_CONTRADICTED`` invariant (hard FAIL) in
    :func:`evaluate_invariants`.

    Algorithm (LLM-free, deterministic):
      1. Collect ``{field: [sample_floats]}`` from every captured
         ``grounding_sample`` (W2). No samples → return a zeroed ``presumed``
         GroundingCheck (legacy fallback — NEVER fails for absence).
      2. Strip fenced/inline code so identifier numbers aren't treated as claims.
      3. For every numeric claim in the prose, find the sampled fields ASSOCIATED
         with it by name/alias within a window. For each associated field:
           * within tolerance of ANY sampled value → ``matched``;
           * outside tolerance of EVERY sampled value → ``contradicted`` (record
             the nearest sample + delta as an example).
         A claim associated to NO sampled field is ``unmatched`` (neutral).
    """
    grounding_fields = _collect_grounding_fields(tool_results)
    # No evidence at all → legacy "presumed" mode. We do NOT scan the answer:
    # with nothing to compare against, every number would be ``unmatched`` noise.
    if not grounding_fields:
        return GroundingCheck(evidence_mode="presumed")

    cleaned = _strip_code_spans(answer_text or "")
    cleaned_lower = cleaned.lower()
    field_names = list(grounding_fields)
    matched = 0
    unmatched = 0
    contradicted = 0
    examples: list[dict[str, Any]] = []

    for m in _CLAIM_NUMBER_RE.finditer(cleaned):
        raw_num = m.group("num")
        suffix = m.group("suffix") or ""
        if _is_yearlike(raw_num, suffix):
            continue
        claim_val = _coerce_number(raw_num, suffix)
        if claim_val is None:
            continue
        span = m.span()

        # Which SINGLE sampled field does the prose associate with this number?
        field_name = _nearest_field(cleaned_lower, span, field_names)
        if field_name is None:
            unmatched += 1
            continue

        samples = grounding_fields[field_name]
        if any(_values_within_tolerance(claim_val, s) for s in samples):
            matched += 1
            continue

        # Outside tolerance of EVERY sample for this field → contradiction.
        nearest_sample = min(samples, key=lambda s: abs(claim_val - s))
        contradicted += 1
        examples.append(
            {
                "field": field_name,
                "claim": claim_val,
                "claim_text": m.group(0).strip(),
                "nearest_sample": nearest_sample,
                "delta": abs(claim_val - nearest_sample),
            }
        )

    return GroundingCheck(
        matched=matched,
        unmatched=unmatched,
        contradicted=contradicted,
        examples=examples,
        evidence_mode="verified",
    )


# --------------------------------------------------------------------------
# Public judge entry point
# --------------------------------------------------------------------------


# Human-readable explanations for each deterministic FAIL reason — surfaced in
# the per-Q artifact ``reviewer_summary`` and in the report.
_DEGENERATE_REASON_TEXT: dict[str, str] = {
    "leaked_control_tokens": (
        "DEGENERATE ANSWER: tool-call control tokens (<function/<invoke/"
        "<parameter/<think) leaked into the user-facing answer — the chat "
        "layer rendered internal scaffolding as the response."
    ),
    "tool_call_stub": (
        "DEGENERATE ANSWER: the answer is a fenced-JSON / tool-call stub (or "
        "a mid-call truncation), not a prose answer the user can read."
    ),
    "empty_after_tool": (
        "DEGENERATE ANSWER: empty answer after >=1 successful tool call — "
        "data was fetched but nothing was said to the user."
    ),
    "empty_answer": "DEGENERATE ANSWER: empty / whitespace-only answer.",
    "digit_drop_corruption": (
        "DEGENERATE ANSWER: leading-digit-drop rendering corruption detected "
        "(e.g. a number rendered as '**,095') — the answer is unreliable."
    ),
    "tool_failure_nonanswer": (
        "TOOL-FAILURE NON-ANSWER: an expected tool failed (error/empty) and "
        "the agent produced an infra-apology / refusal on an answerable "
        "question (appropriate_refusal_ok=false). An outage non-answer is "
        "NOT a PASS."
    ),
}


def _degenerate_fail_result(reason: str, *, judge_prompt_id: str) -> dict[str, Any]:
    """Build a hard-FAIL verdict for a deterministic pre-check hit.

    The LLM judge is NOT consulted. Score is 0 and the ``veto`` field records
    the precise machine reason so the report can list it distinctly from
    LLM-graded FAILs. Dimensions are emitted as 0 (with the reason as
    feedback) so every downstream consumer that iterates DIMENSION_KEYS keeps
    working.

    PLAN-0110 W1: this path is itself an invariant-gate hit, so we also build a
    full ``VerdictDecision`` (verdict=FAIL, fail_reason=the matching
    InvariantCode) and attach it as ``verdict_decision`` — the deterministic
    gate produces a meaningful tiered verdict even when the LLM judge never
    runs (T-W1-04 / F-4).
    """
    text = _DEGENERATE_REASON_TEXT.get(reason, f"DEGENERATE ANSWER: {reason}")
    # tool_failure_nonanswer is a distinct class (infra failure, not a broken
    # answer string) — tag the veto type accordingly so the report can split
    # the two lists.
    veto_type = "tool_failure" if reason == "tool_failure_nonanswer" else "degenerate"

    # Map the deterministic reason to its InvariantCode and build the gate map:
    # exactly the matched gate is VIOLATED (False); all others passed (True).
    if reason == "tool_failure_nonanswer":
        fired_code: InvariantCode | None = InvariantCode.INFRA_NON_ANSWER
    else:
        fired_code = _DEGENERATE_REASON_TO_CODE.get(reason)
    gate_results: dict[InvariantCode, bool] = {code: True for code in _ALL_INVARIANTS}
    if fired_code is not None:
        gate_results[fired_code] = False
    decision = VerdictDecision(
        verdict=Verdict.FAIL,
        quality_score=0,
        fail_reason=fired_code,
        gate_results=gate_results,
        grounding_check=GroundingCheck(),
        dimensions={k: 0 for k in DIMENSION_KEYS},
    )

    return {
        "verdict": "FAIL",
        "score": 0,
        "dimensions": {k: {"score": 0, "feedback": text, "reason": text} for k in DIMENSION_KEYS},
        "reviewer_summary": text,
        "notes": text,  # back-compat mirror
        "raw_response": None,
        "judge_prompt_id": judge_prompt_id,
        # ``veto`` is the load-bearing field the report + summary pivot on.
        "veto": {"type": veto_type, "reason": reason, "detail": text},
        "verdict_decision": decision.to_dict(),
    }


def _grounding_contradicted_fail_result(
    grounding_check: GroundingCheck,
    *,
    judge_prompt_id: str,
) -> dict[str, Any]:
    """Build a hard-FAIL verdict for a deterministic numeric CONTRADICTION (W3).

    Mirror of ``_degenerate_fail_result`` for the GROUNDING_CONTRADICTED gate.
    The LLM judge is NOT consulted: a claimed value the tool's own sampled value
    disproves is fabrication-with-evidence, the most severe class — so we hard-
    FAIL deterministically (works offline, F-4). The populated ``GroundingCheck``
    (with examples) is carried on the VerdictDecision + the legacy ``veto`` so the
    report (W5) can render the claim-vs-sample mismatch.
    """
    ex = grounding_check.examples[0] if grounding_check.examples else {}
    text = (
        f"GROUNDING CONTRADICTED: {grounding_check.contradicted} numeric claim(s) "
        f"disproved by a sampled tool value (e.g. claim "
        f"{ex.get('claim_text', ex.get('claim'))!r} for field {ex.get('field')!r} "
        f"vs sample {ex.get('nearest_sample')}). The agent stated a number the "
        f"tool's own payload contradicts — fabrication."
    )
    gate_results: dict[InvariantCode, bool] = {code: True for code in _ALL_INVARIANTS}
    gate_results[InvariantCode.GROUNDING_CONTRADICTED] = False
    decision = VerdictDecision(
        verdict=Verdict.FAIL,
        quality_score=0,
        fail_reason=InvariantCode.GROUNDING_CONTRADICTED,
        gate_results=gate_results,
        grounding_check=grounding_check,
        dimensions={k: 0 for k in DIMENSION_KEYS},
    )
    return {
        "verdict": "FAIL",
        "score": 0,
        "dimensions": {k: {"score": 0, "feedback": text, "reason": text} for k in DIMENSION_KEYS},
        "reviewer_summary": text,
        "notes": text,  # back-compat mirror
        "raw_response": None,
        "judge_prompt_id": judge_prompt_id,
        "veto": {
            "type": "grounding_contradicted",
            "reason": "numeric_claim_contradicted",
            "contradicted": grounding_check.contradicted,
            "examples": list(grounding_check.examples),
            "detail": text,
        },
        "verdict_decision": decision.to_dict(),
    }


def judge_answer(
    inp: JudgeInput,
    *,
    llm: JudgeLLM | None = None,
) -> dict[str, Any]:
    """Grade one answer; returns a dict with verdict, score, dimensions, notes.

    When ``llm`` is None we attempt to build the default DeepInfra-backed
    judge from environment variables (``DEEPINFRA_API_KEY``,
    ``CHAT_JUDGE_MODEL``, ``CHAT_JUDGE_BASE_URL``). If no key is configured,
    we return a ``SKIPPED`` verdict so the runner still produces artefacts.
    """
    if llm is None:
        llm = _build_default_llm(
            api_key=os.environ.get("DEEPINFRA_API_KEY"),
            model=os.environ.get("CHAT_JUDGE_MODEL", _DEFAULT_JUDGE_MODEL),
            base_url=os.environ.get("CHAT_JUDGE_BASE_URL", _DEFAULT_BASE_URL),
        )

    # Stable identifier for the rubric that produced this verdict — persisted
    # alongside every result (including SKIPPED/ERROR) so a year-old artefact
    # can be traced to the exact prompt body that graded it.
    judge_prompt_id = CHAT_QUALITY_JUDGE.identifier()

    # ── Deterministic pre-checks (F3 + F4, audit 2026-06-11) ──────────────
    # Run BEFORE the LLM judge. If the "answer" is a machine artefact (leaked
    # stub / truncation / empty-after-tools / digit-drop) or an infra-failure
    # non-answer to an answerable question, hard-FAIL it here — the LLM judge
    # is not consulted and cannot inflate the score. This runs even when no
    # LLM is configured, so degenerate answers are caught in offline / CI mode
    # too. We still attach a stable judge_prompt_id for traceability.
    degenerate_reason = detect_degenerate_answer(inp.answer_text, inp.tool_results)
    if degenerate_reason is None:
        degenerate_reason = detect_tool_failure_nonanswer(inp.answer_text, inp.rubric, inp.tool_results)
    if degenerate_reason is not None:
        return _degenerate_fail_result(degenerate_reason, judge_prompt_id=judge_prompt_id)

    # ── Deterministic numeric grounding cross-check (PLAN-0110 W3 / FR-6) ──
    # A numeric CONTRADICTION (a claimed value a sampled tool value disproves) is
    # an LLM-free hard failure — so we run it BEFORE the SKIPPED short-circuit
    # below. This makes GROUNDING_CONTRADICTED meaningful in offline / CI mode
    # too (F-4): a fabricated number is caught even with no DEEPINFRA_API_KEY.
    # With no samples the check returns ``presumed`` (contradicted=0) and this is
    # a no-op — the answer flows on to the normal SKIPPED / LLM path.
    grounding_check = cross_check_grounding(inp.answer_text, inp.tool_results)
    if grounding_check.contradicted > 0:
        return _grounding_contradicted_fail_result(grounding_check, judge_prompt_id=judge_prompt_id)

    if llm is None:
        # No API key + no injected LLM → return a sentinel so the report
        # can clearly show "judge was not run" rather than a fake 0.
        _skipped_note = "Judge LLM not configured (set DEEPINFRA_API_KEY)."
        return {
            "verdict": "SKIPPED",
            "score": None,
            "dimensions": {k: None for k in DIMENSION_KEYS},
            "reviewer_summary": _skipped_note,
            "notes": _skipped_note,  # v1.x back-compat mirror
            "raw_response": None,
            "judge_prompt_id": judge_prompt_id,
            # No soft sub-scores exist when the judge is skipped, so there is no
            # quality_score to band. The answer DID clear every deterministic
            # gate (degenerate/tool-failure short-circuit earlier) — a fired gate
            # would already have returned a FAIL VerdictDecision above. With no
            # gate fired and no judge, there is genuinely no verdict to compose,
            # so we emit None rather than a misleading 0-score FAIL.
            "verdict_decision": None,
        }

    user_prompt = _build_user_prompt(inp)
    try:
        raw = llm(system=_SYSTEM_PROMPT, user=user_prompt)
    except Exception as exc:  # network error, rate-limit, model 5xx
        _err_note = f"Judge call failed: {exc!r}"
        return {
            "verdict": "ERROR",
            "score": None,
            "dimensions": {k: None for k in DIMENSION_KEYS},
            "reviewer_summary": _err_note,
            "notes": _err_note,  # v1.x back-compat mirror
            "raw_response": None,
            "judge_prompt_id": judge_prompt_id,
            # The judge errored → no sub-scores → no verdict to compose (see the
            # SKIPPED path above for the rationale).
            "verdict_decision": None,
        }

    parsed = _parse_judge_response(raw)
    # Pass ``inp`` so the deterministic invariant gate (answer-text + tool-result
    # checks) runs inside the tiered composition — the soft judge alone cannot
    # see leaked tokens / truncation / infra non-answers (PLAN-0110 W1).
    return _finalise_verdict(parsed, raw_response=raw, judge_prompt_id=judge_prompt_id, inp=inp)


def _parse_judge_response(raw: str) -> dict[str, Any]:
    """Defensive JSON parsing — strips markdown fences if present.

    Returns a dict containing whatever dimension keys could be recovered.
    Missing keys default to 0 in `_finalise_verdict`.
    """
    text = raw.strip()
    # Strip optional ```json ... ``` fences in case a future model variant
    # ignores `response_format=json_object`.
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _band_quality_score(quality_score: int) -> Verdict:
    """Band a gate-cleared ``quality_score`` (0-100) into a tiered ``Verdict``.

    Only called when EVERY invariant gate passed (PRD-0091 §6.5 table). A score
    below ``_BAND_WEAK`` is still a FAIL (a barely-coherent answer is a failure
    even with no hard-invariant violation).
    """
    if quality_score >= _BAND_STRONG:
        return Verdict.STRONG
    if quality_score >= _BAND_PASS:
        return Verdict.PASS
    if quality_score >= _BAND_WEAK:
        return Verdict.WEAK
    return Verdict.FAIL


def compose_verdict(
    dimensions_int: dict[str, int],
    gate_results: dict[InvariantCode, bool],
    grounding_check: GroundingCheck,
) -> VerdictDecision:
    """Lexicographically compose the tiered ``VerdictDecision`` (AD-1).

    The composition is GATE-then-BAND:
      1. If ANY invariant gate fired (a ``False`` in ``gate_results``) → the
         verdict is ``FAIL`` and ``fail_reason`` is the highest-priority fired
         gate. The soft ``quality_score`` is IRRELEVANT here — a hard failure
         can never be "bought back" by a high score (the core AD-1 property).
      2. Otherwise → band the additive ``quality_score`` (== sum of dimensions,
         FR-4 continuity) into STRONG/PASS/WEAK/FAIL.
    """
    quality_score = sum(dimensions_int.values())
    fail_reason = first_fired_invariant(gate_results)
    if fail_reason is not None:
        # A fired gate is an UNCONDITIONAL FAIL regardless of quality_score.
        verdict = Verdict.FAIL
    else:
        verdict = _band_quality_score(quality_score)
    return VerdictDecision(
        verdict=verdict,
        quality_score=quality_score,
        fail_reason=fail_reason,
        gate_results=gate_results,
        grounding_check=grounding_check,
        dimensions=dimensions_int,
    )


def _finalise_verdict(
    parsed: dict[str, Any],
    *,
    raw_response: str,
    judge_prompt_id: str,
    inp: JudgeInput | None = None,
) -> dict[str, Any]:
    """Compute the tiered verdict + legacy fields from parsed dimensions.

    Pipeline (PLAN-0110 W1 / AD-1):
    * each dimension is clamped to [0, _MAX_PER_DIMENSION]; missing/non-numeric
      default to 0; ``quality_score = sum(dims)`` (FR-4 continuity).
    * deterministic invariant gates run via ``evaluate_invariants`` (LLM-free);
    * if any gate fired → FAIL[first-fired code]; else band the quality_score.
    * the returned dict carries BOTH the NEW ``verdict_decision`` structured
      field AND the LEGACY ``verdict``/``score``/``dimensions``/``veto`` keys so
      the runner + artefact readers keep working for one release (W5 migrates
      them).

    ``inp`` carries the answer/tool_results/rubric the deterministic gate needs.
    It is optional only so legacy callers that pass nothing still get the soft
    score (the answer-text gates then cannot run — but in the live flow
    ``judge_answer`` always passes ``inp``).
    """
    dimensions: dict[str, dict[str, Any]] = {}
    dimensions_int: dict[str, int] = {}  # key→score, for the VerdictDecision
    total = 0
    for key in DIMENSION_KEYS:
        entry = parsed.get(key)
        if isinstance(entry, dict):
            raw_score = entry.get("score")
            # v2.0 canonical key is ``feedback``; fall back to v1.x ``reason``
            # for one release of back-compat while in-flight judge calls
            # transition. We emit BOTH keys downstream so older readers keep
            # working too.
            feedback = str(entry.get("feedback") or entry.get("reason", ""))[:300]
        else:
            raw_score = entry  # tolerate a bare number
            feedback = ""
        try:
            score = int(raw_score) if raw_score is not None else 0
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(_MAX_PER_DIMENSION, score))
        # Emit both keys so downstream consumers (artefact readers, dashboards)
        # can migrate at their own pace. ``feedback`` is canonical; ``reason``
        # mirrors it for one release.
        dimensions[key] = {"score": score, "feedback": feedback, "reason": feedback}
        dimensions_int[key] = score
        total += score

    # v2.0: canonical top-level summary key is ``reviewer_summary`` (≤800
    # chars, written as a PR-review note). v1.x used ``notes`` (≤400 chars).
    # Dual-read + dual-emit for one release.
    reviewer_summary = str(parsed.get("reviewer_summary") or parsed.get("notes", ""))[:800]

    grounding_score = dimensions_int.get("grounding", _MAX_PER_DIMENSION)

    # ── NEW tiered composition (PLAN-0110 W1 / AD-1) ──────────────────────
    # Run every deterministic gate. In this path the answer already cleared the
    # degenerate + tool-failure pre-checks in ``judge_answer`` (it short-circuits
    # those before reaching here), so the only gate that can fire from the soft
    # judge is GROUNDING_FLOOR — but we run the FULL gate so the VerdictDecision
    # carries an accurate, complete ``gate_results`` map (FR-3), and so a future
    # caller invoking ``_finalise_verdict`` directly still gets correct gating.
    # PLAN-0110 W3 (T-W3-02): the numeric cross-check is now LIVE. We compute the
    # GroundingCheck from the answer + the W2-captured grounding samples on
    # ``inp.tool_results``; ``contradicted > 0`` trips GROUNDING_CONTRADICTED in
    # the gate. With no samples the cross-check returns a zeroed ``presumed``
    # check (legacy behaviour — never fails for absence).
    if inp is not None:
        grounding_check = cross_check_grounding(inp.answer_text, inp.tool_results)
        gate_results = evaluate_invariants(
            inp.answer_text,
            inp.tool_results,
            inp.rubric,
            grounding_check,
            grounding_score=grounding_score,
        )
    else:
        # No inputs → no answer/samples to cross-check, so the GroundingCheck is
        # the zeroed ``presumed`` default. We can only evaluate the grounding
        # floor (we still have the judge sub-score); other gates default to
        # "passed".
        grounding_check = GroundingCheck()
        gate_results = {code: True for code in _ALL_INVARIANTS}
        if grounding_score < GROUNDING_VETO_FLOOR:
            gate_results[InvariantCode.GROUNDING_FLOOR] = False

    decision = compose_verdict(dimensions_int, gate_results, grounding_check)

    # ── LEGACY band + grounding veto (back-compat, unchanged behaviour) ───
    # The legacy ``verdict`` string keeps the OLD 85/60 PASS/WARN/FAIL bands and
    # the OLD ``veto`` dict so the runner + report (which W5 will migrate) read
    # the same values as before. The grounding floor is the ONLY gate that can
    # reach this path, so we reproduce the legacy veto exactly when it fires.
    if total >= _PASS_THRESHOLD:
        verdict = "PASS"
    elif total >= _WARN_THRESHOLD:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    veto: dict[str, Any] | None = None
    # PLAN-0110 W3 (T-W3-02): a numeric CONTRADICTION is the most severe veto and
    # is checked FIRST (matching the gate's _INVARIANT_PRIORITY where
    # GROUNDING_CONTRADICTED outranks GROUNDING_FLOOR). A claim a sampled value
    # disproves is fabrication-with-evidence — strictly worse than a low soft
    # grounding sub-score. We mirror it into the legacy ``verdict``/``veto`` keys
    # so report readers on the back-compat path also see the FAIL + the
    # claim-vs-sample mismatch.
    if grounding_check.contradicted > 0:
        pre_veto_verdict = verdict
        verdict = "FAIL"
        ex = grounding_check.examples[0] if grounding_check.examples else {}
        veto_detail = (
            f"GROUNDING CONTRADICTED: {grounding_check.contradicted} numeric "
            f"claim(s) disproved by a sampled tool value (e.g. claim "
            f"{ex.get('claim_text', ex.get('claim'))!r} for field "
            f"{ex.get('field')!r} vs sample {ex.get('nearest_sample')}). Verdict "
            f"forced FAIL (sum={total} would otherwise have been {pre_veto_verdict})."
        )
        veto = {
            "type": "grounding_contradicted",
            "reason": "numeric_claim_contradicted",
            "contradicted": grounding_check.contradicted,
            "examples": list(grounding_check.examples),
            "detail": veto_detail,
            "pre_veto_verdict": pre_veto_verdict,
        }
        reviewer_summary = (f"{veto_detail} {reviewer_summary}").strip()[:800]
    elif grounding_score < GROUNDING_VETO_FLOOR:
        pre_veto_verdict = verdict
        verdict = "FAIL"
        veto_detail = (
            f"GROUNDING VETO: grounding={grounding_score} < floor "
            f"{GROUNDING_VETO_FLOOR} — likely fabrication. Verdict forced FAIL "
            f"(sum={total} would otherwise have been {pre_veto_verdict})."
        )
        veto = {
            "type": "grounding",
            "reason": "grounding_below_floor",
            "grounding": grounding_score,
            "floor": GROUNDING_VETO_FLOOR,
            "detail": veto_detail,
            "pre_veto_verdict": pre_veto_verdict,
        }
        # Prepend the veto to the reviewer summary so a human scanning the
        # artifact sees WHY this FAILed even though three dims may be high.
        reviewer_summary = (f"{veto_detail} {reviewer_summary}").strip()[:800]

    return {
        "verdict": verdict,
        "score": total,
        "dimensions": dimensions,
        "reviewer_summary": reviewer_summary,
        "notes": reviewer_summary,  # back-compat mirror — drop in next release
        "raw_response": raw_response,
        "judge_prompt_id": judge_prompt_id,
        "veto": veto,
        # ── NEW structured tiered verdict (PLAN-0110 W1) ──────────────────
        # ``verdict_decision`` is the authoritative tiered object; downstream
        # consumers (trend store W4, report W5) read it. It is emitted ALONGSIDE
        # the legacy keys, never instead of them, for the back-compat window.
        "verdict_decision": decision.to_dict(),
    }


# --------------------------------------------------------------------------
# Helpers consumed by the runner
# --------------------------------------------------------------------------


def build_input_from_artifact(
    q: dict[str, Any],
    result_dict: dict[str, Any],
) -> JudgeInput:
    """Construct a JudgeInput from a saved `q_<id>.json` payload.

    `result_dict` is the `result` block (as stored by ChatRunResult.to_json_dict).
    This is the offline-grading entry point — it lets us re-judge an existing
    run without rerunning the chat.
    """
    return JudgeInput(
        prompt=str(q.get("prompt") or ""),
        rubric=Rubric.from_question(q),
        answer_text=str(result_dict.get("answer_text") or ""),
        tool_calls=list(result_dict.get("tool_calls") or []),
        tool_results=list(result_dict.get("tool_results") or []),
    )


def summarise_judge_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate stats for the `_judge_summary.json` artefact.

    `records` is a list of {id, verdict, score, dimensions:{key:{score,reason}}}.
    Skipped/errored entries are excluded from averages but counted in `n_*`.
    """
    verdict_counts: dict[str, int] = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIPPED": 0, "ERROR": 0}
    dim_totals: dict[str, list[int]] = {k: [] for k in DIMENSION_KEYS}
    scored_totals: list[int] = []
    # Audit 2026-06-11 — failure-first aggregates. We tally the deterministic /
    # veto FAIL classes so the report can lead with them instead of an average.
    # PLAN-0110 W3: ``grounding_contradicted`` is the new W3 veto class (a numeric
    # claim disproved by a sampled tool value) — counted separately from the soft
    # ``grounding`` floor veto so the report can distinguish "fabrication proven
    # against evidence" from "low soft grounding sub-score".
    veto_counts: dict[str, int] = {"grounding": 0, "grounding_contradicted": 0, "degenerate": 0, "tool_failure": 0}
    # PLAN-0110 W1 — tiered-verdict aggregates. Counts of the NEW Verdict bands
    # and a histogram of which InvariantCode triggered each FAIL, both read from
    # the structured ``verdict_decision`` block (None when judge skipped/errored).
    tiered_counts: dict[str, int] = {"STRONG": 0, "PASS": 0, "WEAK": 0, "FAIL": 0}
    fail_reason_counts: dict[str, int] = {}
    for r in records:
        v = str(r.get("verdict") or "ERROR")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
        # Veto/degenerate FAILs carry a ``veto`` block — count by type even
        # though their score (0) is excluded from the dimension averages below.
        veto = r.get("veto")
        if isinstance(veto, dict):
            vt = str(veto.get("type") or "")
            if vt in veto_counts:
                veto_counts[vt] += 1
        # Tiered verdict roll-up (W1). Skipped/errored records have no decision.
        decision = r.get("verdict_decision")
        if isinstance(decision, dict):
            tv = str(decision.get("verdict") or "")
            if tv in tiered_counts:
                tiered_counts[tv] += 1
            fr = decision.get("fail_reason")
            if isinstance(fr, str):
                fail_reason_counts[fr] = fail_reason_counts.get(fr, 0) + 1
        if v in {"SKIPPED", "ERROR"}:
            continue
        score = r.get("score")
        if isinstance(score, int):
            scored_totals.append(score)
        dims = r.get("dimensions") or {}
        for k in DIMENSION_KEYS:
            entry = dims.get(k)
            if isinstance(entry, dict):
                s = entry.get("score")
                if isinstance(s, int):
                    dim_totals[k].append(s)

    def _avg(xs: list[int]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    return {
        "verdict_counts": verdict_counts,
        "score_avg": _avg(scored_totals),
        "score_max": max(scored_totals) if scored_totals else None,
        "score_min": min(scored_totals) if scored_totals else None,
        "dimension_avg": {k: _avg(v) for k, v in dim_totals.items()},
        "n_records": len(records),
        # Failure-first counters (audit F5). ``grounding`` = fabrication veto,
        # ``degenerate`` = broken-answer pre-check, ``tool_failure`` = infra
        # non-answer. The report leads with these.
        "veto_counts": veto_counts,
        "grounding_veto_floor": GROUNDING_VETO_FLOOR,
        # PLAN-0110 W1 — tiered verdict band counts (n_strong/n_pass/n_weak/
        # n_fail) and the fail-reason (InvariantCode) histogram. The W5 report
        # leads with these; they are the authoritative verdict aggregates.
        "tiered_verdict_counts": {
            "n_strong": tiered_counts["STRONG"],
            "n_pass": tiered_counts["PASS"],
            "n_weak": tiered_counts["WEAK"],
            "n_fail": tiered_counts["FAIL"],
        },
        "fail_reason_counts": fail_reason_counts,
        # The rubric identifier is the same for every record in a single run
        # (all records were graded by CHAT_QUALITY_JUDGE). We surface it once at
        # the summary level so dashboards/exports can pivot on judge version
        # without scanning per-question payloads.
        "judge_prompt_id": CHAT_QUALITY_JUDGE.identifier(),
    }
