"""Citation-accuracy use case — PLAN-0063 W5-5 T-W5-5-02.

Samples 50 recent assistant messages, extracts [cN]-annotated claim spans,
and uses an LLM judge to score each claim-snippet pair on a 0-3 rubric.
The normalised mean is emitted as the `rag_citation_accuracy` gauge.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Protocol

import structlog

from rag_chat.application.metrics.prometheus import rag_citation_accuracy

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

# Prompt injection defence: wrap snippet in explicit delimiters so the judge
# model cannot be instructed by adversarial content inside the snippet.
_CITATION_RUBRIC = """\
You are evaluating whether a snippet supports a chat assistant's claim.
The claim may be a direct quote OR a synthesis/paraphrase of multiple sources.

CLAIM: {claim}
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
    """

    def __init__(
        self,
        message_repo: MessageRepository,
        llm_judge: LLMJudgePort,
    ) -> None:
        self._repo = message_repo
        self._judge = llm_judge

    async def execute(self) -> float:
        """Score citations and return the mean accuracy (0-1). Returns 0.0 on failure."""
        samples = await self._repo.sample_recent_with_citations(n=50)
        if len(samples) < _MIN_SAMPLES:
            log.warning(  # type: ignore[no-any-return]
                "citation_accuracy_insufficient_samples",
                n=len(samples),
                min_required=_MIN_SAMPLES,
            )
            return 0.0

        scores: list[float] = []
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
                raw_response = await self._judge.score_citation(
                    claim=claim_text,
                    snippet=snippet,
                )
                try:
                    judge_int = int(raw_response.strip())
                    if judge_int not in (0, 1, 2, 3):
                        raise ValueError(f"out-of-range: {judge_int}")
                    scores.append(judge_int / 3.0)
                except (ValueError, TypeError):
                    # Invalid response — skip this pair, do not crash.
                    log.debug(  # type: ignore[no-any-return]
                        "citation_judge_invalid_response",
                        raw=raw_response[:20],
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
