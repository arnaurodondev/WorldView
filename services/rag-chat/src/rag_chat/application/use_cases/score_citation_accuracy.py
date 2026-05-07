"""Citation-accuracy use case — PLAN-0063 W5-5 T-W5-5-02, hardened PLAN-0084 A-1.

Samples 50 recent assistant messages, extracts [cN]-annotated claim spans,
and uses an LLM judge to score each claim-snippet pair on a 0-3 rubric.
The normalised mean is emitted as the `rag_citation_accuracy` gauge.

PLAN-0084 A-1 changes:
- T-A-1-03: `_sanitise` helper fences inputs against prompt injection (F-S01).
- T-A-1-04: Per-call ``LLMJudgeTimeoutError`` catch + skip; wall-clock budget
  via ``asyncio.timeout``; failure counter ``rag_citation_accuracy_call_failures_total``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

import structlog

from rag_chat.application.metrics.prometheus import (
    rag_citation_accuracy,
    rag_citation_accuracy_call_failures_total,
)
from rag_chat.domain.errors import LLMJudgeTimeoutError

if TYPE_CHECKING:
    from rag_chat.application.ports.message_repository import MessageRepository
    from rag_chat.domain.entities.conversation import Message

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Minimum samples required to emit a meaningful gauge value.
_MIN_SAMPLES = 10

# Regex matching [c1], [c2], … markers used in brief-style messages.
_CLAIM_MARKER_RE = re.compile(r"\[c(\d+)\]")

# Sentence boundary pattern (simple heuristic — adequate for MVP).
_SENTENCE_SEP_RE = re.compile(r"(?<=[.!?])\s+")

# F-S01: Maximum character lengths for claim and snippet before LLM judge call.
# Truncation prevents token-budget exhaustion and reduces attack surface for
# injection payloads embedded in long articles.
_MAX_CLAIM_CHARS = 1024
_MAX_SNIPPET_CHARS = 1024

# F-S01: Tokens that could break the rubric delimiters or override instructions.
# If found the token is replaced with [REDACTED] and a warning is logged.
_INJECTION_TOKENS = ("<<<CLAIM ", "<<<SNIPPET ", ">>>", "Respond with ONLY")


def _sanitise(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars* and redact known injection delimiters.

    Used by ``ScoreCitationAccuracyUseCase.execute`` on both claim and snippet
    before they are interpolated into the LLM-judge prompt (F-S01).
    """
    truncated = text[:max_chars]
    for token in _INJECTION_TOKENS:
        if token in truncated:
            log.warning(  # type: ignore[no-any-return]
                "citation_judge_input_contains_delimiter",
                token=token,
            )
            truncated = truncated.replace(token, "[REDACTED]")
    return truncated


# Prompt injection defence: explicit delimiters fence the {claim} and {snippet}
# substitution slots so the judge model cannot be overridden by adversarial content.
# The <<<CLAIM …>>> / <<<SNIPPET …>>> frame is chosen because it is visually
# distinct from prose and is included in _INJECTION_TOKENS so any attempt to
# embed the same frame inside the inputs is redacted by _sanitise() before
# formatting (F-S01: belt-and-braces approach).
_CITATION_RUBRIC = """\
You are evaluating whether a snippet supports a chat assistant's claim.
The claim may be a direct quote OR a synthesis/paraphrase of multiple sources.

<<<CLAIM START>>>
{claim}
<<<CLAIM END>>>

<<<SNIPPET START>>>
{snippet}
<<<SNIPPET END>>>

Score the snippet's support of the claim on this 0-3 scale:
- 0: Snippet is irrelevant to the claim
- 1: Snippet is tangentially related but does not support the specific claim
- 2: Snippet supports the claim — EITHER directly OR by supporting a paraphrase
     or synthesis of which this claim is a faithful summary.
- 3: Snippet directly answers/contains the claim verbatim or near-verbatim.

Respond with ONLY a single digit 0, 1, 2, or 3."""


class LLMJudgePort(Protocol):
    """Minimal interface for the LLM judge used by ScoreCitationAccuracyUseCase."""

    async def score_citation(self, *, claim: str, snippet: str) -> str:
        """Return a single-digit string '0', '1', '2', or '3'."""
        ...


def iter_cited_claims(msg: Message) -> Iterator[tuple[str, str]]:
    """Yield (claim_text, citation_id_str) for each [cN] marker in a message.

    For messages that contain inline [cN] markers (brief-style), claim_text is
    the sentence containing the marker.  For plain chat messages without any
    [cN] markers, falls back to the full content paired with each stored
    citation (legacy behaviour, scored once per citation).

    citation_id_str is the string form of the marker, e.g. "c1", "c3".
    """
    markers_in_content = _CLAIM_MARKER_RE.findall(msg.content)
    if not markers_in_content:
        # Plain chat message — pair full content with each citation.
        for cite in msg.citations:
            yield msg.content, f"c{cite.ref}"
        return

    # Brief-style message — split into sentences and yield per marker.
    sentences = _SENTENCE_SEP_RE.split(msg.content)
    for sentence in sentences:
        found = _CLAIM_MARKER_RE.findall(sentence)
        for marker_num in found:
            yield sentence, f"c{marker_num}"


class ScoreCitationAccuracyUseCase:
    """Sample recent assistant messages and judge each cited claim via LLM.

    Emits the `rag_citation_accuracy` Gauge with the mean normalised score.
    Uses `citation.title` as the snippet proxy — adequate for MVP; a richer
    snippet field (full chunk text) can be added in a later wave.

    PLAN-0084 A-1 T-A-1-04 additions:
    - ``LLMJudgeTimeoutError`` and provider exceptions are caught per-pair and
      counted via ``rag_citation_accuracy_call_failures_total``.  The loop
      continues for remaining pairs rather than crashing.
    - ``min_samples`` overrides the module-level ``_MIN_SAMPLES`` default so the
      cron task can pass the config value from Settings.
    - Outer wall-clock budget enforced via ``asyncio.timeout(run_budget_s)``
      (Python 3.11+).  When the budget expires the loop is truncated gracefully.
    """

    def __init__(
        self,
        message_repo: MessageRepository,
        llm_judge: LLMJudgePort,
        *,
        min_samples: int = _MIN_SAMPLES,
        run_budget_s: float = 600.0,
    ) -> None:
        self._repo = message_repo
        self._judge = llm_judge
        self._min_samples = min_samples
        self._run_budget_s = run_budget_s

    async def execute(self) -> float:
        """Score citations and return the mean accuracy (0-1). Returns 0.0 on failure."""
        samples = await self._repo.sample_recent_with_citations(n=50)
        if len(samples) < self._min_samples:
            log.warning(  # type: ignore[no-any-return]
                "citation_accuracy_insufficient_samples",
                n=len(samples),
                min_required=self._min_samples,
            )
            return 0.0

        scores: list[float] = []

        async def _score_all() -> None:
            for msg in samples:
                for claim_text, citation_id in iter_cited_claims(msg):
                    ref_num_str = citation_id[1:]  # "c3" → "3"
                    try:
                        ref_num = int(ref_num_str)
                    except ValueError:
                        continue
                    cite = next((c for c in msg.citations if c.ref == ref_num), None)
                    if cite is None:
                        continue
                    snippet = cite.title or ""

                    # T-A-1-03: sanitise both inputs before building the prompt.
                    safe_claim = _sanitise(claim_text, _MAX_CLAIM_CHARS)
                    safe_snippet = _sanitise(snippet, _MAX_SNIPPET_CHARS)
                    # Build the full fenced prompt here so CitationJudgeAdapter
                    # receives a ready-to-send string (transport only, no logic).
                    prompt = _CITATION_RUBRIC.format(claim=safe_claim, snippet=safe_snippet)

                    try:
                        raw_response = await self._judge.score_citation(
                            claim=prompt,
                            snippet=safe_snippet,  # kept for protocol compliance
                        )
                    except LLMJudgeTimeoutError:
                        rag_citation_accuracy_call_failures_total.labels(reason="timeout").inc()
                        log.warning("citation_judge_pair_skipped", reason="timeout")  # type: ignore[no-any-return]
                        continue
                    except Exception as exc:
                        rag_citation_accuracy_call_failures_total.labels(reason="provider_error").inc()
                        log.warning("citation_judge_pair_skipped", reason="provider_error", error=str(exc))  # type: ignore[no-any-return]
                        continue

                    try:
                        judge_int = int(raw_response.strip())
                        if judge_int not in (0, 1, 2, 3):
                            raise ValueError(f"out-of-range: {judge_int}")
                        scores.append(judge_int / 3.0)
                    except (ValueError, TypeError):
                        # Invalid response — skip this pair, do not crash.
                        rag_citation_accuracy_call_failures_total.labels(reason="invalid_response").inc()
                        log.debug(  # type: ignore[no-any-return]
                            "citation_judge_invalid_response",
                            raw=raw_response[:20],
                        )

        # T-A-1-04: outer wall-clock budget — truncates the loop cleanly when
        # the total run exceeds citation_run_budget_s (default 600s).
        try:
            async with asyncio.timeout(self._run_budget_s):
                await _score_all()
        except TimeoutError:
            log.warning(  # type: ignore[no-any-return]
                "citation_accuracy_run_budget_exceeded",
                budget_s=self._run_budget_s,
                scored_so_far=len(scores),
            )

        mean = sum(scores) / len(scores) if scores else 0.0
        rag_citation_accuracy.set(mean)
        log.info(  # type: ignore[no-any-return]
            "citation_accuracy_scored",
            n_samples=len(samples),
            n_claims=len(scores),
            mean=round(mean, 4),
        )
        return mean
