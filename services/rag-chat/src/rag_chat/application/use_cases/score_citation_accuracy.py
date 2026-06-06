"""Citation-accuracy use case — PLAN-0063 W5-5 T-W5-5-02, hardened PLAN-0084 A-1.

Samples 50 recent assistant messages, extracts [cN]-annotated claim spans,
and uses an LLM judge to score each claim-snippet pair on a 0-3 rubric.
The normalised mean is emitted as the `rag_citation_accuracy_24h` gauge
(PLAN-0107 canonical; the legacy `rag_citation_accuracy` alias was removed
after the PLAN-0099 W4 transition window since no consumer scraped it).

PLAN-0084 A-1 changes:
- T-A-1-03: `_sanitise` helper fences inputs against prompt injection (F-S01).
- T-A-1-04: Per-call ``LLMJudgeTimeoutError`` catch + skip; wall-clock budget
  via ``asyncio.timeout``; failure counter ``rag_citation_accuracy_call_failures_total``.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

# Use the canonical citation-judge rubric from libs/prompts so version +
# content_hash + identifier() are persisted alongside every Prometheus
# emission and structlog event for audit trace linkage.
from prompts.evaluation import CITATION_JUDGE

from common.time import utc_now  # type: ignore[import-untyped]
from rag_chat.application.metrics.prometheus import (
    rag_citation_accuracy_24h,
    rag_citation_accuracy_call_failures_total,
)
from rag_chat.domain.errors import LLMJudgeTimeoutError

if TYPE_CHECKING:
    from rag_chat.application.ports.llm_judge import LLMJudgePort
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
# 500 tokens ≈ 150-300 words ≈ 2500 chars upper bound for typical English prose.
# Raised from 1024 once chunk text (not just title) is fed to the judge — chunk
# snippets are full retrieval payloads, not headlines, and truncating at 1024
# would clip mid-sentence for every chunk over ~200 words.
_MAX_SNIPPET_CHARS = 2500

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


# Prompt injection defence: the {claim} and {snippet} substitution slots inside
# CITATION_JUDGE.template are fenced by explicit <<<CLAIM …>>> / <<<SNIPPET …>>>
# delimiters so the judge model cannot be overridden by adversarial content.
# The same delimiters are listed in _INJECTION_TOKENS above so any attempt to
# embed the framing inside the inputs is redacted by _sanitise() BEFORE
# CITATION_JUDGE.render(...) is called (F-S01: belt-and-braces approach).


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

    Emits the `rag_citation_accuracy_24h` Gauge with the mean normalised
    score (PLAN-0107 canonical; the legacy `rag_citation_accuracy` alias
    was removed in the follow-up cleanup — no consumers scraped it).
    Uses `citation.text` (chunk text persisted in JSONB, PLAN-0107) as the
    snippet, falling back to `citation.title` for legacy records.

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
        """Score citations and return the mean accuracy (0-1). Returns 0.0 on failure.

        Daily-cron addition (PLAN-0099 W4): sampling is restricted to the last
        24h via the ``since`` kwarg so the gauge tracks recent quality drift
        rather than a 7-day rolling average. The use case dedups
        ``(message_id, citation.id)`` pairs so the same chunk cited under
        different refs within ONE message scores once (realistic when agents
        do multi-step retrieval and the same source surfaces twice). The
        same chunk cited across TWO messages still scores twice — by design,
        because each message is an independent answer event.
        """
        # 24h window — the cron runs daily so this lines up with one cron tick
        # without overlap. The repo port keeps ``since=None`` as the legacy
        # "no window" behaviour for callers that haven't migrated yet.
        since = utc_now() - timedelta(hours=24)
        samples = await self._repo.sample_recent_with_citations(n=50, since=since)
        if len(samples) < self._min_samples:
            # Dedicated log key for the 24h-window case so operators can grep
            # for genuinely-quiet days vs misconfigured cron schedules.
            log.warning(  # type: ignore[no-any-return]
                "citation_accuracy_insufficient_samples_24h",
                n=len(samples),
                min_required=self._min_samples,
                window_hours=24,
                # cadence label so dashboards correlate quiet-day warnings with
                # the 24h cron schedule (PLAN-0099 W4 QA F-007).
                cadence="daily",
            )
            return 0.0

        scores: list[float] = []
        # Dedup set — (message_id, citation.id) tuples already scored.
        # Same chunk cited under different refs within one message scores once.
        # Same chunk across two messages still scores twice — by design.
        seen: set[tuple[UUID, str]] = set()

        async def _score_all() -> None:
            for msg in samples:
                for claim_text, citation_id in iter_cited_claims(msg):
                    ref_num_str = citation_id[1:]  # "c3" → "3"
                    try:
                        ref_num = int(ref_num_str)
                    except ValueError:
                        continue
                    # Resolve the actual Citation BEFORE building the dedup key
                    # so we can key on its stable `id` (chunk identity) rather
                    # than the ref number (which the LLM assigns per-message).
                    cite = next((c for c in msg.citations if c.ref == ref_num), None)
                    if cite is None:
                        continue
                    # Dedup AFTER ref-resolution so non-existent refs (typos in
                    # the LLM output) don't poison the seen-set. Key uses
                    # citation.id so two refs pointing to the same chunk within
                    # one message score once.
                    dedup_key = (msg.message_id, cite.id)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    # Prefer chunk text (full payload) over title (headline).
                    # Falls back to title for legacy citations persisted before
                    # the Citation.text field was added (BP-NEW PLAN-0099 W4).
                    snippet = cite.text or cite.title or ""

                    # T-A-1-03: sanitise both inputs before building the prompt.
                    safe_claim = _sanitise(claim_text, _MAX_CLAIM_CHARS)
                    safe_snippet = _sanitise(snippet, _MAX_SNIPPET_CHARS)
                    # Build the full fenced prompt from the libs/prompts template
                    # so version+content_hash propagate to the log line below.
                    prompt = CITATION_JUDGE.render(claim=safe_claim, snippet=safe_snippet)

                    try:
                        # A-002: snippet param removed from LLMJudgePort.score_citation —
                        # the full fenced prompt (rubric + claim + snippet) is already
                        # assembled above and passed as `claim`.  The adapter does not
                        # need the raw snippet text separately.
                        raw_response = await self._judge.score_citation(
                            claim=prompt,
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
        # PLAN-0107 follow-up: legacy ``rag_citation_accuracy`` gauge removed
        # (was dual-emitted during the W4 transition; no Grafana / external
        # consumer ever scraped it). ``rag_citation_accuracy_24h`` is now the
        # sole canonical gauge — see infra/grafana/dashboards/rag-chat.json
        # for the dashboard panel.
        rag_citation_accuracy_24h.set(mean)
        log.info(  # type: ignore[no-any-return]
            "citation_accuracy_scored",
            n_samples=len(samples),
            n_claims=len(scores),
            mean=round(mean, 4),
            # judge_prompt_id ties the gauge value to a specific rubric body.
            # When the rubric is bumped in libs/prompts the hash changes, which
            # lets log-correlation queries diff "before vs after" cleanly.
            judge_prompt_id=CITATION_JUDGE.identifier(),
        )
        return mean
