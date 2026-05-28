"""Pure grading rubric for chat regression suite (PLAN-0093 Wave G-3 T-G-3-01).

Given a question, a :class:`ChatRunResult`, and a set of ground-truth
assertions, return a per-response grade dict::

    {
        "tools_called": [...],
        "numbers_in_response": [...],
        "unsupported_numbers": [...],
        "hallucination": "YES" | "NO",
        "citations_valid": True | False,
        "verdict": "USEFUL" | "MARGINAL" | "USELESS" | "HARMFUL",
        "reasons": [...],   # plain-English why-the-verdict bullets
    }

This module is deliberately stateless and side-effect free so the
aggregate test can re-grade stored artefacts deterministically.

Verdict rubric (the gate that flows into ``test_aggregate_score.py``):

* HARMFUL  — the response contains an outright false numeric claim
             (sign-flip, hallucinated quarter, value > tolerance) OR
             violates a forbidden-pattern regex (e.g. "AMD Q2 2026
             revenue $34.6B" before AMD reports). HARMFUL > USELESS:
             a confidently wrong answer is worse than no answer.
* USELESS  — HTTP 503 / empty answer / refused without explanation /
             no tools were called when the question demands them /
             error event (including INPUT_REJECTED from the upstream
             classifier — see PLAN-0097 W2 T-W2-03).
* MARGINAL — answered with some grounding but missing a required tool,
             a citation, or a key entity mention.
* USEFUL   — answered with required tools, mentions all required
             entities, no hallucination, citations parseable.

Refusal-vs-USELESS policy (PLAN-0097 W2 T-W2-03 (c) — explicit)
---------------------------------------------------------------
A response that says "I cannot find evidence..." is classified by the
intent of the agent, not by token presence:

* SHORT refusal (< 300 chars) with NO ``[Nk]`` citation markers →
  USELESS. The agent gave up without engaging with the tools.
* LONG (≥ 300 chars) OR citation-bearing answer that also includes a
  refusal token → NOT a refusal. The agent did the tool work and is
  honestly reporting a data gap (R19: never fabricate). Verdict is
  USEFUL or MARGINAL depending on whether the required tool fired.
* INPUT_REJECTED (upstream classifier) → USELESS. The model never got
  to attempt the question. We do NOT also add a "missing required
  tool" reason because the request never reached tool selection.

Rationale: penalising honest data-gap acknowledgements with USELESS
discourages R19 compliance and rewards fabrication; penalising upstream
classifier failures as MARGINAL (via missing-tool reason) hides the
real failure mode (the classifier rejected a safe query).

This module imports :class:`NumericGroundingValidator` from the rag-chat
service if reachable; otherwise it falls back to a lightweight stub that
only catches the substring case.

NumericGroundingValidator path note
-----------------------------------
Wave E-2 (commit 9db5f29d) placed the validator at::

    services/rag-chat/src/rag_chat/application/services/numeric_grounding.py

We attempt to import it via the dev venv's editable install. When that
fails (e.g. running this module from a stand-alone CI container that
doesn't have the service installed), we fall back to a stub that always
returns "no unsupported numbers" — biased toward false negatives, which
is the safe direction (we'd rather miss a hallucination than crash the
aggregate scoring gate). The stub is loudly logged in the result so a
real-platform CI never silently relies on the fallback.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.validation.chat_eval.harness import ChatRunResult


# ---------------------------------------------------------------------------
# PLAN-0097 W2 T-W2-03 (a) — Tool-name equivalence (BP-580).
#
# Background: PLAN-0095 W2 introduced batched variants of the singular
# fundamentals tool (``get_fundamentals_history_batch``) and PLAN-0097 W3
# wires the intent map to prefer the batch tool when the user asks about
# ≥2 tickers. Ground-truth assertions in ``questions.yaml`` were written
# against the singular names BEFORE the batch tools existed; the grader
# must accept either form as satisfying a singular requirement, otherwise
# the model is penalised for choosing the (correct) batch tool.
#
# Add new entries here when a new singular/batch (or other equivalent
# alias) pair lands. The mapping is INTENT-PRESERVING: each set MUST
# contain only tools that retrieve the same logical data.
# ---------------------------------------------------------------------------
_TOOL_EQUIVALENTS: dict[str, set[str]] = {
    # PLAN-0095 W2 T-W2-01 batch endpoint — same fundamentals payload,
    # parallelized across tickers.
    "get_fundamentals_history": {"get_fundamentals_history", "get_fundamentals_history_batch"},
    "get_fundamentals_history_batch": {"get_fundamentals_history", "get_fundamentals_history_batch"},
    # PLAN-0093 KG-traversal aliases — both return path/edge data.
    "traverse_graph": {"traverse_graph", "get_entity_paths"},
    "get_entity_paths": {"traverse_graph", "get_entity_paths"},
}


def _tool_requirement_satisfied(tools_called: list[str], required_tools: list[str]) -> bool:
    """Return True if any *required_tools* entry (or any of its equivalents)
    appears in *tools_called*.

    A singular requirement like ``get_fundamentals_history`` is satisfied
    by either ``get_fundamentals_history`` OR
    ``get_fundamentals_history_batch`` — both retrieve the same logical
    data (PLAN-0097 W2 T-W2-03 / BP-580).
    """
    called_set = set(tools_called)
    for req in required_tools:
        equivalents = _TOOL_EQUIVALENTS.get(req, {req})
        if called_set & equivalents:
            return True
    return False


# ---------------------------------------------------------------------------
# NumericGroundingValidator import — soft.
# ---------------------------------------------------------------------------


def _load_validator() -> tuple[Any, bool]:
    """Return (validator_instance, is_real_validator).

    ``is_real_validator=False`` means we fell back to the stub and grading
    will be less strict — the caller should surface this in the artefact.
    """
    try:
        # See module docstring for path rationale.
        from rag_chat.application.services.numeric_grounding import (  # type: ignore[import-not-found]
            NumericGroundingValidator,
        )

        return NumericGroundingValidator(), True
    except ImportError:
        return _StubValidator(), False


class _StubValidator:
    """Fallback when rag-chat is not importable.

    Implements just enough of the :class:`NumericGroundingValidator`
    surface (``validate(response, tool_results)``) for the grader.
    """

    def validate(self, response: str, tool_results: Iterable[Any]) -> _StubResult:
        # We can't do a real numeric match without the FieldKind machinery,
        # so we return passed=True and leave detection to the per-question
        # regex assertions (which catch the egregious cases like
        # ``AMD revenue $34.6B``). TODO(G-3 follow-up): drop the stub once
        # rag-chat is pip-installed into the validation runner image.
        _ = response, tool_results  # silence linter; intentionally unused
        return _StubResult()


class _StubResult:
    """Placeholder for :class:`GroundingResult` from the real validator."""

    passed = True
    total_numbers = 0
    unsupported: tuple[Any, ...] = ()


# ---------------------------------------------------------------------------
# Number extraction (independent of the validator — used to populate the
# ``numbers_in_response`` field of the grade dict for the artefact).
# ---------------------------------------------------------------------------

_NUMBER_TOKEN_RE = re.compile(
    r"""
    (?<![A-Za-z])                       # not preceded by letter (skip Q4, etc.)
    [-+]?\$?\d[\d,]*(?:\.\d+)?           # mantissa
    (?:[BMKTbmkt%])?(?![A-Za-z])         # optional suffix
    """,
    re.VERBOSE,
)


def extract_numbers(text: str) -> list[str]:
    """Return raw token strings of every number-like span in *text*."""
    return [m.group(0) for m in _NUMBER_TOKEN_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Citation validation.
# ---------------------------------------------------------------------------

_CITATION_MARKER_RE = re.compile(r"\[N(\d+)\]")


def citations_in_bounds(answer: str, citations: list[Any]) -> bool:
    """Every ``[Nk]`` marker in the answer must correspond to an emitted citation.

    The citations list comes from the SSE ``citations`` event — its
    length is the upper bound. We allow markers to be absent entirely
    (some answers don't cite); but if they exist, every k must be in
    ``1..len(citations)``.
    """
    markers = [int(m.group(1)) for m in _CITATION_MARKER_RE.finditer(answer)]
    if not markers:
        return True
    upper = len(citations)
    return all(1 <= k <= upper for k in markers)


# ---------------------------------------------------------------------------
# Forbidden-pattern regex (rationalisation phrases).
# ---------------------------------------------------------------------------

# Rationalisation patterns the audit flagged as "LLM is making excuses for
# hallucinated numbers". Only allowed if followed by a citation marker.
_RATIONALISATION_RE = re.compile(
    r"(potential volatility|one-time event|may reflect|likely (?:due|caused))",
    re.IGNORECASE,
)


def orphan_rationalisations(answer: str) -> list[str]:
    """Return rationalisation phrases NOT followed by a ``[Nk]`` citation.

    "Followed by" is defined as a citation marker appearing within the
    next 100 chars after the rationalisation match — a generous window
    that should catch any well-formed citation pattern.

    FIX-LIVE-W: honest-quote context exemption. After FIX-LIVE-N+R the
    agent emits paragraphs that QUOTE a suspect retrieval value and then
    speculatively explain why it might be wrong (e.g. "documents list
    $34.6B but this does not appear in any verified tool result. This
    may reflect potential volatility in reporting practices"). The
    speculative continuation is part of an honest refusal, not a
    fabricated rationalisation. If any honest-quote marker appears
    within ±80 chars of the rationalisation phrase, treat it as an
    honest quote and skip it.
    """
    orphans: list[str] = []
    lower = answer.lower()
    for m in _RATIONALISATION_RE.finditer(answer):
        tail = answer[m.end() : m.end() + 100]
        if _CITATION_MARKER_RE.search(tail):
            continue
        # FIX-LIVE-W: orphan-context check — skip when the phrase is
        # inside an honest-quote refusal/speculative window. Mask out
        # the match span itself so a phrase like "may reflect" (which
        # is itself a speculative marker) doesn't trivially self-exempt;
        # the exemption must come from a SEPARATE marker in the window.
        masked = lower[: m.start()] + (" " * (m.end() - m.start())) + lower[m.end() :]
        if _is_honest_rationalisation_context(masked, m.start()):
            continue
        orphans.append(m.group(0))
    return orphans


# ---------------------------------------------------------------------------
# Refusal & low-quality detectors.
# ---------------------------------------------------------------------------

_REFUSAL_TOKENS = (
    "unable to retrieve",
    "i cannot provide",
    "i'm unable to",
    "i am unable to",
    "no data available",
    "provider_unavailable",
    "service unavailable",
    "could not find",
)


# PLAN-0093 Phase 5c F-LIVE-005C-REFUSAL: a true refusal is SHORT and
# CITES NOTHING. A long answer that includes a table + an honest data-gap
# acknowledgement ("...I cannot provide gross margin because the tool
# did not return that field") is NOT a refusal — it is the agent doing
# exactly the right thing under R19 (no fabrication). The old detector
# matched purely on token presence which mis-classified Q4 v4/v5/v6 as
# USELESS even though those answers were fully grounded.
_REFUSAL_LENGTH_THRESHOLD = 300  # chars — true refusals are short

_CITATION_MARKER_FOR_REFUSAL_RE = re.compile(r"\[N\d+\]")


def is_refusal(answer: str) -> bool:
    """Heuristic: does the answer read as a refusal / no-data response?

    Tightened to avoid mis-classifying honest data-gap acknowledgements
    as refusals. An answer is a refusal only when ALL three hold:

      1. A ``_REFUSAL_TOKENS`` phrase appears in the text.
      2. The answer is shorter than 300 chars (true refusals are
         short — the agent gave up).
      3. The answer contains NO ``[Nk]`` citation markers (a citing
         answer is actively engaging with the tool data).

    A long, table-bearing, citation-laden response that also includes
    "I cannot provide field X — not in retrieved data" is the agent
    correctly observing a tool gap, not refusing.
    """
    lower = answer.lower()
    has_refusal_token = any(tok in lower for tok in _REFUSAL_TOKENS)
    if not has_refusal_token:
        return False
    # Tightening conditions — both must hold for the answer to be a
    # honest data-gap rather than a real refusal.
    is_long = len(answer) >= _REFUSAL_LENGTH_THRESHOLD
    has_citations = bool(_CITATION_MARKER_FOR_REFUSAL_RE.search(answer))
    if is_long or has_citations:
        return False
    return True


# ---------------------------------------------------------------------------
# Quarter-label extraction (used by survey + Q4).
# ---------------------------------------------------------------------------

# PLAN-0093 Phase 5 QA-2 Gap 2: mirror the broadened pattern in
# ``services/rag-chat/.../numeric_grounding.py`` so the grading rubric
# extracts the same set of canonical quarter labels regardless of the
# fiscal-year variant the LLM emits ("Q1 FY26", "Q1 fiscal 2027", etc.).
_QUARTER_LABEL_RE = re.compile(
    r"""
    \bQ([1-4])                                   # Q1..Q4
    \s*
    (?:
        (?:of\s+)?fiscal\s+year\s+               # "of fiscal year 2026"
      | (?:of\s+)?fiscal\s+                      # "fiscal 2027"
      | FY\s*                                    # "FY26", "FY 2026"
    )?
    \s*[/-]?\s*
    (\d{2}|\d{4})                                # 2- or 4-digit year
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_quarter_labels(text: str) -> set[str]:
    """Return canonical ``QnYYYY`` strings mentioned in *text*.

    Two-digit years are expanded by prefixing ``20`` so ``FY26`` and
    ``2026`` collapse to the same label.
    """
    out: set[str] = set()
    for m in _QUARTER_LABEL_RE.finditer(text):
        year = m.group(2)
        if len(year) == 2:
            year = f"20{year}"
        out.add(f"Q{m.group(1)}{year}")
    return out


# ---------------------------------------------------------------------------
# Main grader.
# ---------------------------------------------------------------------------


def grade_response(
    question: str,
    result: ChatRunResult,
    ground_truth_assertions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply the rubric to a single :class:`ChatRunResult`.

    The returned dict is suitable for direct ``assert grade["verdict"]
    in {USEFUL, MARGINAL}`` style checks in test files and for
    aggregating in :mod:`weak_point_report`.
    """
    gt = dict(ground_truth_assertions or {})
    reasons: list[str] = []

    tools_called = result.tools_called()
    answer = result.answer_text or ""

    # ── Numeric grounding ────────────────────────────────────────────────
    validator, is_real_validator = _load_validator()
    # Tool results: assemble citation texts as the grounding corpus.
    # The real orchestrator passes RetrievedItem objects; here citations
    # are dicts with at least a ``text`` field (see ChatResponse schema).
    tool_corpus: list[Any] = []
    for c in result.citations:
        if isinstance(c, dict):
            text = c.get("snippet") or c.get("text") or ""
            if text:
                tool_corpus.append(text)
    grounding = validator.validate(answer, tool_corpus)
    unsupported = list(getattr(grounding, "unsupported", ()) or ())
    hallucination = "YES" if unsupported else "NO"

    # ── Number / citation extraction (forensic fields for the artefact) ──
    numbers_in_response = extract_numbers(answer)
    citations_valid = citations_in_bounds(answer, result.citations)
    orphan_rationals = orphan_rationalisations(answer)

    # ── Required-tool / required-mention checks ──────────────────────────
    # PLAN-0095 W3 T-W3-05: a cache-served answer satisfies the per-question
    # required-tool requirement — the tools fired on the original cold-path
    # request that populated the cache, and the rubric should not punish a
    # legitimate latency optimisation. We detect cache hits via either
    # (a) ``metadata.cache_hit == True`` or (b) a ``status`` SSE event with
    # ``step == "cache_hit"`` (emitted by chat_orchestrator.py:463). The eval
    # session sets RAG_COMPLETION_CACHE_DISABLED=true (conftest fixture) so
    # this branch is the safety net for ad-hoc re-runs without that env.
    cache_hit = bool(result.metadata.get("cache_hit")) or any(
        ev.get("event") == "status"
        and isinstance(ev.get("data"), dict)
        and str(ev["data"].get("step", "")) == "cache_hit"
        for ev in result.raw_events
    )
    # PLAN-0097 W2 T-W2-03 (b): INPUT_REJECTED at the classifier gate also
    # relaxes the required-tool assertion — the model never got a chance to
    # call any tool because the upstream classifier short-circuited the
    # request. We still count INPUT_REJECTED as USELESS (see the
    # ``result.error`` branch below); we just don't ALSO penalize it with
    # "missing required tool" noise that would inflate the reason list.
    input_rejected = bool(result.error is not None and str(result.error.get("code", "")) == "INPUT_REJECTED")
    required_tools = gt.get("required_tools_any_of") or []
    if (
        required_tools
        and not cache_hit
        and not input_rejected
        and not _tool_requirement_satisfied(tools_called, list(required_tools))
    ):
        reasons.append(f"missing required tool from {required_tools!r}; got {tools_called!r}")

    min_distinct_tools = int(gt.get("min_distinct_tools", 0))
    if min_distinct_tools and len(set(tools_called)) < min_distinct_tools:
        reasons.append(f"only {len(set(tools_called))} distinct tools, need ≥ {min_distinct_tools}")

    must_all = list(gt.get("must_mention_all_of") or [])
    for token in must_all:
        if token.lower() not in answer.lower():
            reasons.append(f"missing required mention {token!r}")

    must_any = list(gt.get("must_mention_any_of") or [])
    if must_any and not any(t.lower() in answer.lower() for t in must_any):
        reasons.append(f"missing any-of mention from {must_any!r}")

    candidates = list(gt.get("must_mention_candidates") or [])
    min_n = int(gt.get("must_mention_at_least_n", 0))
    if candidates and min_n:
        hits = sum(1 for c in candidates if c.lower() in answer.lower())
        if hits < min_n:
            reasons.append(f"only {hits} of {candidates!r} mentioned; need ≥ {min_n}")

    if not citations_valid:
        reasons.append("citation marker out of bounds")

    if orphan_rationals:
        reasons.append(f"orphan rationalisation phrases: {orphan_rationals!r}")

    if gt.get("forbid_duplicate_paragraphs"):
        # Loose detection: first 50 chars should appear at most twice.
        head = answer[:50].strip()
        if head and answer.count(head) > 1:
            reasons.append("duplicate paragraph block detected")

    invented = list(gt.get("forbid_invented_products") or [])
    for token in invented:
        if token.lower() in answer.lower():
            reasons.append(f"invented product reference: {token!r}")

    # ── HARMFUL gating ───────────────────────────────────────────────────
    # Numeric forbiddens (Q4): any AMD revenue > $15B, any NVDA > $100B.
    harmful_reasons: list[str] = []
    amd_cap = gt.get("forbid_amd_revenue_above_billions")
    nvda_cap = gt.get("forbid_nvda_revenue_above_billions")
    if amd_cap is not None:
        if _mentions_revenue_above(answer, ticker_keywords=("AMD",), cap_billions=float(amd_cap)):
            harmful_reasons.append(f"AMD revenue > ${amd_cap}B mentioned")
    if nvda_cap is not None:
        if _mentions_revenue_above(answer, ticker_keywords=("NVDA", "NVIDIA"), cap_billions=float(nvda_cap)):
            harmful_reasons.append(f"NVDA revenue > ${nvda_cap}B mentioned")

    if hallucination == "YES":
        harmful_reasons.append(
            f"{len(unsupported)} ungrounded numeric claim(s)"
            + ("" if is_real_validator else " (stub validator — may be false)")
        )

    # ── USELESS gating ───────────────────────────────────────────────────
    useless_reasons: list[str] = []
    if result.status_code in {503, 429}:
        useless_reasons.append(f"HTTP {result.status_code}")
    if result.error is not None:
        useless_reasons.append(f"error event: {result.error.get('code')!r}")
    require_200 = bool(gt.get("require_http_200"))
    if require_200 and result.status_code != 200:
        useless_reasons.append(f"required HTTP 200 but got {result.status_code}")
    if not answer.strip():
        useless_reasons.append("empty answer")
    if is_refusal(answer) and not gt.get("allow_empty_finding"):
        useless_reasons.append("response reads as a refusal")

    # ── Verdict assembly ─────────────────────────────────────────────────
    if harmful_reasons:
        verdict = "HARMFUL"
        reasons = harmful_reasons + reasons
    elif useless_reasons:
        verdict = "USELESS"
        reasons = useless_reasons + reasons
    elif reasons:
        verdict = "MARGINAL"
    else:
        verdict = "USEFUL"

    return {
        "tools_called": tools_called,
        "numbers_in_response": numbers_in_response,
        "unsupported_numbers": [
            {
                "value": getattr(u, "value", None),
                "field_kind": getattr(getattr(u, "field_kind", None), "value", None),
                "snippet": getattr(u, "snippet", None),
            }
            for u in unsupported
        ],
        "hallucination": hallucination,
        "citations_valid": citations_valid,
        "orphan_rationalisations": orphan_rationals,
        "verdict": verdict,
        "reasons": reasons,
        "validator_real": is_real_validator,
        "latency_s": result.latency_s,
        # PLAN-0099 W1 T-W1-03: surface the new responsiveness metrics so
        # the aggregate gate (and any ad-hoc grader caller) can read them
        # without poking into the underlying ChatRunResult dataclass.
        # ``ttft_s`` / ``tps`` are floats that may be ``nan`` when the
        # stream had no content frame (error path); ``output_tokens`` is
        # ``None`` when the answer was empty and no usage envelope landed.
        "ttft_s": result.ttft_s,
        "tps": result.tps,
        # PLAN-0101 W3: synthesis-phase TPS — the gated metric. ``tps`` above
        # is kept as a diagnostic so historical comparisons still hold.
        "tps_streaming": result.tps_streaming,
        "output_tokens": result.output_tokens,
        "status_code": result.status_code,
    }


# ---------------------------------------------------------------------------
# Helpers — exposed for unit tests too.
# ---------------------------------------------------------------------------


# PLAN-0093 Phase 5c+1 FIX-LIVE-N: honest-quote exemption markers.
#
# After FIX-LIVE-J the agent reaches the validator+honest-refusal path and
# correctly refuses while QUOTING the suspect retrieval value as evidence
# of *why* it refuses ("documents list $34.6B but this does not appear in
# any verified tool result"). The grader's number-cap rules used to flag
# this as HARMFUL — a false positive. If any of these markers occurs
# within ±80 chars of the offending number, the number is treated as an
# honest quote (the agent calling out the bad data) rather than an
# assertive claim of fact.
#
# FIX-LIVE-W extends the marker set with SPECULATIVE-prose markers. After
# FIX-LIVE-R unblocked Q4 v1's full pipeline, the agent's honest paragraph
# now reads: "documents list $34.6B but this does not appear in any
# verified tool result ... This may reflect potential volatility in
# reporting practices". The continuation "may reflect" / "potentially" /
# "appears to" lives inside the same honest-refusal scope — these are
# hedge words the agent uses to speculatively explain why the suspect
# value might be wrong, not assertive claims of fact. The grader treats
# any such hedge within ±80 chars of a number as an honest quote.
# Refusal markers (FIX-LIVE-N) — strong disclaimers that prove the agent
# is REFUSING the suspect value. These count for both the number-cap
# (assertive-claim) check AND the orphan-rationalisation check.
_REFUSAL_QUOTE_MARKERS: tuple[str, ...] = (
    "cannot",
    "[unverified]",
    "does not appear",
    # BP-612: plural form — Q4 v1 refusal reads "the values listed for
    # NVIDIA … do not appear in the retrieved results for AMD". Without
    # this entry the marker scan misses the disclaimer entirely and the
    # NVDA figures get charged to AMD.
    "do not appear",
    "not verified",
    "not present",
    "not available",
    "not reported",
    "could not be verified",
    "unsupported",
    "not confirmed",
    # FIX-LIVE-W: a few additional refusal-flavoured phrases the agent
    # uses inside honest-refusal paragraphs after FIX-LIVE-R unblocked
    # the full Q4 v1 pipeline.
    "without verification",
    "inconsistent with",
)

# Speculative-prose markers (FIX-LIVE-W) — hedge words the agent uses
# when SPECULATING about why a suspect value might be wrong. These count
# ONLY for the orphan-rationalisation exemption: they tell us the
# rationalisation phrase is part of an honest-refusal paragraph rather
# than a fabricated explanation. They do NOT relax the number-cap rule
# (a fabricated number followed by "may reflect new launches" is still
# fabrication — see ``test_assertive_amd_revenue_with_speculation_is_flagged``).
_SPECULATIVE_QUOTE_MARKERS: tuple[str, ...] = (
    "may reflect",
    "could be",
    "potentially",
    "appears to",
    "is reported to",
    "according to the data",
)

# Combined set, kept for backwards-compatible access. The orphan-context
# check uses the union; ``_is_honest_quote`` uses only the refusal set.
_HONEST_QUOTE_MARKERS: tuple[str, ...] = _REFUSAL_QUOTE_MARKERS + _SPECULATIVE_QUOTE_MARKERS

_HONEST_QUOTE_WINDOW = 80  # chars on either side of the number match

# BP-612 (PLAN-0101 Wave 3): widened window specifically for the revenue-cap
# refusal exemption. The Q4 NVDA/AMD false-positive case had the refusal
# marker ("do not appear in the retrieved results for AMD") sitting ~95
# chars after the offending NVDA figure ($81.6B) — outside the default
# ±80 window. We use a wider ±150 char window when scanning for refusal
# markers in :func:`_mentions_revenue_above` so the disclaimer covering an
# entire sentence/clause still exempts numbers inside it. The narrower
# ±80 window remains the default for :func:`_is_honest_quote` to avoid
# over-relaxing the speculative-marker (orphan-rationalisation) check.
_HONEST_QUOTE_WINDOW_REVENUE = 150


def _is_honest_quote(lower_text: str, number_idx: int, *, window: int = _HONEST_QUOTE_WINDOW) -> bool:
    """Return True if *number_idx* sits within ±*window* chars of a REFUSAL marker.

    ``lower_text`` must already be lower-cased so the marker scan stays
    case-insensitive without re-compiling for each call.

    FIX-LIVE-W: the number-cap check uses ONLY the refusal markers (not
    speculative ones) — a fabricated number followed by speculative hedge
    words ("may reflect new launches") is still fabrication.

    BP-612: ``window`` is parameterised so callers (notably
    :func:`_mentions_revenue_above`) can opt into a wider scope when the
    refusal sentence is structurally further from the disputed number.
    """
    start = max(0, number_idx - window)
    end = number_idx + window
    win = lower_text[start:end]
    return any(marker in win for marker in _REFUSAL_QUOTE_MARKERS)


def _is_honest_rationalisation_context(lower_text: str, phrase_idx: int) -> bool:
    """Return True if *phrase_idx* sits within ±80 chars of any honest-quote marker.

    FIX-LIVE-W: orphan-rationalisation exemption uses the FULL marker
    set (refusal + speculative) — a rationalisation phrase that lives
    next to "documents list X but ..." or "this may reflect ..." or
    "I cannot confirm ..." is part of an honest-refusal paragraph, not
    a fabricated rationalisation.
    """
    start = max(0, phrase_idx - _HONEST_QUOTE_WINDOW)
    end = phrase_idx + _HONEST_QUOTE_WINDOW
    window = lower_text[start:end]
    return any(marker in window for marker in _HONEST_QUOTE_MARKERS)


# Match "<ticker keyword>" within ~150 chars of "revenue" + dollar amount in B.
# We do a loose proximity check rather than a parser — the LLM emits the
# claim in many shapes and we just want to catch egregious >$15B AMD figures.
def _mentions_revenue_above(
    text: str,
    ticker_keywords: tuple[str, ...],
    cap_billions: float,
) -> bool:
    """Return True if *text* mentions <ticker> revenue > cap_billions.

    Honest-quote exemption (FIX-LIVE-N): when the offending number sits
    within ±80 chars of a refusal/disclaimer marker (e.g. "cannot",
    "[unverified]", "does not appear"), the agent is quoting the value
    to *refuse* it rather than asserting it. Such occurrences do NOT
    count as fabrication — true fabrication is an assertive sentence
    with NO nearby disclaimer.
    """
    lower = text.lower()
    revenue_idx = [m.start() for m in re.finditer(r"\brevenue\b", lower)]
    if not revenue_idx:
        return False
    # Find every "$X.YB" within proximity of "revenue" and of a ticker word.
    dollar_re = re.compile(r"\$?\s*(\d{1,4}(?:\.\d+)?)\s*([Bb])\b")
    for m in dollar_re.finditer(lower):
        amt = float(m.group(1))
        if amt <= cap_billions:
            continue
        idx = m.start()
        # Must be within 150 chars of *both* a "revenue" hit and a ticker.
        near_revenue = any(abs(idx - r) < 150 for r in revenue_idx)
        if not near_revenue:
            continue
        for kw in ticker_keywords:
            kw_lower = kw.lower()
            for hit in (n.start() for n in re.finditer(re.escape(kw_lower), lower)):
                if abs(idx - hit) < 150:
                    # BP-612 (PLAN-0101 Wave 3): the legacy ±80 char
                    # refusal window missed the Q4 false-positive case
                    # where the disclaimer ("do not appear in the
                    # retrieved results for AMD") sat ~95 chars from
                    # the NVDA figure. Widen the refusal scan to ±150
                    # chars — same scope as the proximity check — so
                    # the entire offending clause is in view.
                    if _is_honest_quote(lower, idx, window=_HONEST_QUOTE_WINDOW_REVENUE):
                        continue
                    # BP-612 (Option 2): directional precedence guard.
                    # An assertive "<TICKER> revenue was $XB" claim
                    # ALWAYS places the ticker BEFORE the number. The
                    # false-positive case has the order reversed — the
                    # number ($81.6B) is mentioned first as part of a
                    # NVDA recap, and "AMD" only appears later in the
                    # refusal clause. Require the ticker hit to precede
                    # the number within a tight ~80-char clause window.
                    # Combined with the honest-quote exemption above
                    # this means: skip when EITHER the refusal marker
                    # is in scope OR the ticker does not precede the
                    # number. Only assertive forward-order claims pass.
                    if not _ticker_precedes_amount(lower, kw_lower, idx):
                        continue
                    return True
    return False


# BP-612 (PLAN-0101 Wave 3): directional precedence helper.
#
# A genuine assertion of "<ticker> revenue $XB" places the ticker keyword
# before the dollar figure, typically in the same clause (≤ ~80 chars).
# When the ticker only appears AFTER the number — e.g. NVDA figures
# recapped then "AMD" appears in a downstream refusal sentence — the
# match is structurally incompatible with an assertive claim and should
# be exempted from the cap. We use a tight 80-char window so multi-
# sentence prose ("AMD revenue was $9.2B. NVIDIA reported $81.6B.")
# does not bleed through.
_TICKER_PRECEDES_WINDOW = 80


def _ticker_precedes_amount(lower_text: str, ticker_kw: str, number_idx: int) -> bool:
    """Return True if *ticker_kw* appears within ~80 chars BEFORE *number_idx*.

    Both inputs must already be lower-cased.
    """
    start = max(0, number_idx - _TICKER_PRECEDES_WINDOW)
    prefix = lower_text[start:number_idx]
    return ticker_kw in prefix


# Convenience verdict helpers for clearer test asserts.
USEFUL = "USEFUL"
MARGINAL = "MARGINAL"
USELESS = "USELESS"
HARMFUL = "HARMFUL"
