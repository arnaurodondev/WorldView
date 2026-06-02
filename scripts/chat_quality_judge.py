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
from typing import Any, Protocol

# Default judge model — Llama 3.1 8B Instruct is cheap, fast, and good enough
# at structured-JSON grading. We pin a specific revision via env var when
# stronger judgement is required (e.g. for thesis evaluation runs).
_DEFAULT_JUDGE_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
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


_SYSTEM_PROMPT = """You are a strict quality grader for a financial-research chat agent.

Grade ONE answer on FOUR dimensions, each 0-25, based ONLY on the inputs supplied.
Be calibrated: shallow questions deserve concise answers; deep questions deserve
multi-section answers; refusals can be PERFECT scores when the data is genuinely
missing AND the question's rubric marks `appropriate_refusal_ok=true`.

DIMENSIONS (each 0-25):

1. tool_use            How well did the agent route the question to the right
                       tools?

                       SCORING RULE (any-of semantics — read carefully):
                         * `rubric.expected_tools` is an EQUIVALENCE SET. Any
                           single tool from the list is sufficient for FULL
                           MARKS. Award 25 if AT LEAST ONE tool from
                           `expected_tools` was called.
                         * Do NOT deduct points for failing to call the OTHER
                           tools in the equivalence set — they are alternatives,
                           not a checklist. Example: expected_tools=[A, B, C]
                           and the agent called only A → 25 (not "missed B and
                           C, score 8").
                         * Award lower scores only when ZERO tools from
                           `expected_tools` were called.
                         * Deduct meaningfully only when the tool that WAS
                           called is clearly wrong for the question (e.g. user
                           asked about price history but the agent only called
                           `search_documents`).
                         * WORKED EXAMPLE — DO NOT DEVIATE: if
                           expected_tools = ["get_fundamentals_history",
                           "get_fundamentals_snapshot", "query_fundamentals"]
                           and the trace shows ONE call to
                           `query_fundamentals(...)`, then tool_use = 25.
                           A reason like "did not call any of the expected
                           tools" is FACTUALLY WRONG in this case — the
                           agent called one of them. You MUST score 25 and
                           write a reason consistent with that fact.
                         * Appropriate-refusal exemption: when
                           `rubric.appropriate_refusal_ok=true` AND the
                           tool_results show empty/missing data AND the answer
                           is a refusal, do NOT penalise tool_use for the
                           refusal itself — refusing instead of fabricating is
                           the correct behaviour. The tool_use score should
                           reflect routing quality (was the right tool tried?),
                           not whether the agent ultimately answered.

2. grounding           Are quantitative claims (numbers, dates, names) traceable
                       to tool_results? Penalise fabricated numbers, fabricated
                       periods (e.g. "Q4 FY2026" when no such period was returned),
                       or claims contradicted by tool output statuses.

                       SPECIAL CASES — DO NOT score grounding=0 for these:
                         * An answer ending with "⚠ Some numbers could not be
                           verified against retrieved data" is a TRANSPARENCY
                           feature, not fabrication. Judge the body claims, NOT
                           the banner. If the body claims are grounded, award
                           full marks; the banner is neutral.
                         * An answer marking specific numbers with [unverified]
                           tags is the LLM correctly flagging uncertainty. If
                           the OTHER numbers in the answer are grounded in
                           tool_results, award partial marks (15-22). Only
                           score 0 when the LLM invents specific values that
                           DO NOT appear anywhere in tool_results.
                         * A W36/synthesis-fallback answer beginning "I
                           retrieved data... the language model could not
                           produce a final summary right now" is a
                           degraded-mode fallback, NOT fabrication. Score
                           grounding by whether the highlights it does
                           include are correctly attributed; the absence of
                           analysis is a framing concern, not grounding.
                           Award 18-25 when highlights cite tool_results.
                         * An honest refusal stating data is unavailable
                           (when rubric.appropriate_refusal_ok=true) is NOT
                           fabrication; grounding should be 20-25 if the
                           refusal is supported by the tool's missing-coverage
                           flag (status=ok + items=0, or status=missing).

3. framing             Does the answer's depth match the question's depth?
                       - shallow + 1-3 sentence answer = PERFECT (25)
                       - shallow + bloated multi-section answer = WARN (~12)
                       - deep + multi-section structured answer = PERFECT (25)
                       - deep + one-line answer = FAIL (<10)
                       Length alone is NEVER the criterion — match to question.

4. refusal_judgment    If the answer is a refusal:
                         - rubric.appropriate_refusal_ok=true AND tool_results
                           show empty/missing data → 25 (correct refusal).
                         - rubric.appropriate_refusal_ok=false OR tool_results
                           contain the requested data → 0-5 (wrongful refusal).
                       If the answer is NOT a refusal: score 25 (N/A).

OUTPUT — strict JSON object, no markdown, with keys:
{
  "tool_use":        {"score": <0-25>, "reason": "<≤200 char>"},
  "grounding":       {"score": <0-25>, "reason": "<≤200 char>"},
  "framing":         {"score": <0-25>, "reason": "<≤200 char>"},
  "refusal_judgment":{"score": <0-25>, "reason": "<≤200 char>"},
  "notes":           "<≤400 char overall comment>"
}
"""


def _build_user_prompt(inp: JudgeInput) -> str:
    """Compose the per-call user message — concise so token cost stays low."""
    # We pre-summarise the tool sequence so the judge sees a flat trace rather
    # than the raw SSE event log. tool_results often carry only status +
    # item_count from the current SSE schema, which is intentionally compact
    # — the judge uses these as evidence of "data was/was-not available".
    tool_trace_lines: list[str] = []
    # Build a per-call/result line: "call N: <tool>(args) -> status item_count=K"
    for i, tc in enumerate(inp.tool_calls):
        name = tc.get("name", "?")
        args = tc.get("arguments") or {}
        # Keep arg formatting compact; we only care about which keys + scalar
        # values were passed, not nested JSON.
        args_repr = ", ".join(f"{k}={_short_repr(v)}" for k, v in args.items())
        matching = inp.tool_results[i] if i < len(inp.tool_results) else None
        if matching:
            status = matching.get("status", "?")
            item_count = matching.get("item_count", "?")
            tool_trace_lines.append(f"  call {i + 1}: {name}({args_repr}) -> status={status} items={item_count}")
        else:
            tool_trace_lines.append(f"  call {i + 1}: {name}({args_repr}) -> (no result event)")

    tool_trace = "\n".join(tool_trace_lines) if tool_trace_lines else "  (no tool calls)"

    return (
        f"QUESTION:\n{inp.prompt}\n\n"
        f"RUBRIC:\n{json.dumps(inp.rubric.to_dict(), indent=2)}\n\n"
        f"TOOL TRACE:\n{tool_trace}\n\n"
        f"ANSWER:\n{inp.answer_text or '<empty>'}\n"
    )


def _short_repr(v: Any) -> str:
    """Compact repr of a tool-arg value, capped at 60 chars."""
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= 60 else s[:57] + "..."


# --------------------------------------------------------------------------
# Public judge entry point
# --------------------------------------------------------------------------


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

    if llm is None:
        # No API key + no injected LLM → return a sentinel so the report
        # can clearly show "judge was not run" rather than a fake 0.
        return {
            "verdict": "SKIPPED",
            "score": None,
            "dimensions": {k: None for k in DIMENSION_KEYS},
            "notes": "Judge LLM not configured (set DEEPINFRA_API_KEY).",
            "raw_response": None,
        }

    user_prompt = _build_user_prompt(inp)
    try:
        raw = llm(system=_SYSTEM_PROMPT, user=user_prompt)
    except Exception as exc:  # network error, rate-limit, model 5xx
        return {
            "verdict": "ERROR",
            "score": None,
            "dimensions": {k: None for k in DIMENSION_KEYS},
            "notes": f"Judge call failed: {exc!r}",
            "raw_response": None,
        }

    parsed = _parse_judge_response(raw)
    return _finalise_verdict(parsed, raw_response=raw)


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


def _finalise_verdict(parsed: dict[str, Any], *, raw_response: str) -> dict[str, Any]:
    """Compute verdict + total score from parsed dimensions.

    Score-clamping logic:
    * each dimension is clamped to [0, _MAX_PER_DIMENSION];
    * non-numeric / missing dimensions default to 0;
    * verdict maps the **sum** to PASS/WARN/FAIL via the band thresholds.
    """
    dimensions: dict[str, dict[str, Any]] = {}
    total = 0
    for key in DIMENSION_KEYS:
        entry = parsed.get(key)
        if isinstance(entry, dict):
            raw_score = entry.get("score")
            reason = str(entry.get("reason", ""))[:300]
        else:
            raw_score = entry  # tolerate a bare number
            reason = ""
        try:
            score = int(raw_score) if raw_score is not None else 0
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(_MAX_PER_DIMENSION, score))
        dimensions[key] = {"score": score, "reason": reason}
        total += score

    if total >= _PASS_THRESHOLD:
        verdict = "PASS"
    elif total >= _WARN_THRESHOLD:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "score": total,
        "dimensions": dimensions,
        "notes": str(parsed.get("notes", ""))[:600],
        "raw_response": raw_response,
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
    for r in records:
        v = str(r.get("verdict") or "ERROR")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
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
    }
