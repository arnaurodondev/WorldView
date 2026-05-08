"""GenerateBriefingUseCase — internal briefing endpoint logic (T-B-2-04, PRD-0016 §6.2).

Called by S10 email scheduler to generate a portfolio risk narrative for digest emails.
Also provides execute_public_morning() and execute_public_instrument() for the frontend
briefing API routes (public_briefings.py).

Auth:       Enforced by InternalJWTMiddleware (PRD-0025) at the API layer — no
            additional token check is required here.
Rate limit: 100 requests/day per user_id (Valkey counter with midnight-aligned key).
LLM:        EMAIL_DEEP_BRIEF_PROMPT via LLMProviderChain (collects full stream).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from rag_chat.application.pipeline.prompts.intent_prompts import EMAIL_DEEP_BRIEF_PROMPT
from rag_chat.application.ports.brief_archive import BriefArchivePort, NullBriefArchive, UserBriefRecord
from rag_chat.domain.brief import BriefBullet, BriefCitation, BriefSection
from rag_chat.domain.errors import RateLimitExceededError

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from rag_chat.application.use_cases.briefing_context import BriefingContextGatherer
    from rag_chat.infrastructure.llm.provider_chain import LLMProviderChain

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_DAILY_RATE_LIMIT = 100
_BRIEFING_RL_PREFIX = "rag:v1:briefing:rl"
_BRIEFING_RL_TTL = 90_000  # 25 hours — covers DST edge cases

# Regex to strip <think>...</think> reasoning blocks emitted by some DeepSeek models.
# These blocks appear before the actual content and must be removed before returning
# the briefing to the frontend.
_REASONING_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Matches both [N] (literal letter N used by LLM as a citation placeholder) and
# [1], [2], [3] etc. (digit-indexed citations the LLM emits when items are present).
# WHY keep this regex: used by _strip_reasoning for the legacy email brief path.
_ORPHAN_CITATION_RE = re.compile(r"\s*\[(?:\d+|N)\]")

# Some LLMs wrap their output in a ```markdown ... ``` code fence even when not asked.
# Strip leading/trailing fence markers so the frontend receives raw markdown.
_CODE_FENCE_RE = re.compile(r"^\s*```(?:markdown)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)

# Matches [cN] citation markers emitted by the v3.0 prompt (e.g. [c1], [c2], [c12]).
# WHY separate from _ORPHAN_CITATION_RE: we KEEP these markers for the citation
# resolver (they index into context_citations). _ORPHAN_CITATION_RE is only used
# to strip LEGACY [N] / [1] markers in the email brief path where citations are
# not supported.
_CN_CITATION_RE = re.compile(r"\[c(\d+)\]")


def _strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks, markdown code fences, and orphaned [N] markers.

    DeepSeek R1 models prepend chain-of-thought within <think> tags before the
    final answer.  Some LLMs also wrap the answer in ```markdown ... ``` fences.
    Both are stripped before returning the briefing to the frontend.
    """
    text = _REASONING_RE.sub("", text).strip()
    # Strip outer ```markdown ... ``` or ``` ... ``` code fences the LLM may emit.
    m = _CODE_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # Strip [N] citation markers — briefings never have a citations array so any
    # [N] the LLM emits are orphaned and confusing to the end user.
    text = _ORPHAN_CITATION_RE.sub("", text)
    return text


# ── Two-tier brief splitter (PLAN-0048 Wave A, prompt v2.2) ─────────────────
#
# The v2.2 MORNING_BRIEFING prompt forces the LLM to emit:
#
#     ## SUMMARY
#     <1-2 sentences>
#
#     ---
#
#     ## DETAILS
#     ### Market Overview
#     ...
#
# We split on the FIRST line that is exactly ``---`` (after trim) so:
#   - The summary half feeds the collapsed card view (replaces line-clamp-3).
#   - The details half feeds the expanded card view.
#
# WHY a strict line-mode split (not ``str.split("---", 1)``):
# Markdown content can legitimately contain ``---`` mid-paragraph (e.g. an
# em-dash range). Requiring the divider to be on its own line eliminates
# false-positive splits.
def _split_summary_and_details(content: str) -> tuple[str | None, str]:
    """Split a v2.2 morning brief into ``(summary, narrative)``.

    The LLM is instructed to emit a ``## SUMMARY`` block, a literal ``---``
    divider line, then a ``## DETAILS`` block. Older prompts and instrument
    briefs emit a single block with no divider — those return ``(None, full_text)``
    so the frontend can degrade gracefully.

    Both returned strings have their leading ``## SUMMARY`` / ``## DETAILS``
    headers stripped — the card chrome already labels the two views, so the
    duplicate headers would just steal vertical space.
    """
    if not content:
        return None, content

    lines = content.splitlines()
    divider_idx: int | None = None
    # Walk the first ~50 lines looking for a bare "---" line. We cap the search
    # because a divider after that point almost certainly belongs to a markdown
    # rule inside the body, not to our two-tier separator.
    for i, line in enumerate(lines[:50]):
        if line.strip() == "---":
            divider_idx = i
            break

    if divider_idx is None:
        # No divider found — assume legacy single-block output. Return the full
        # content as the narrative and leave summary unset.
        return None, content

    summary_block = "\n".join(lines[:divider_idx]).strip()
    details_block = "\n".join(lines[divider_idx + 1 :]).strip()

    # Strip the redundant block headers ("## SUMMARY" / "## DETAILS") — the
    # frontend chrome already labels these regions, so the headers would
    # double-decorate the rendered output.
    summary_block = _strip_block_header(summary_block, "summary")
    # v3.0 LLM output uses "## LEAD" (not "## SUMMARY") for the first block.
    # Strip it here so the collapsed card view shows clean prose, not an H2 heading.
    summary_block = _strip_block_header(summary_block, "lead")
    details_block = _strip_block_header(details_block, "details")

    # Strip [cN] citation markers from the summary — they're produced by the v3.0
    # prompt for inline citation tracking but are meaningless to end-users in the
    # collapsed card view (the resolved source chips appear in the expanded view).
    summary_block = _CN_CITATION_RE.sub("", summary_block).strip()

    # Defensive: if the summary block is empty after stripping, fall back to
    # treating the full content as narrative. An empty summary would render as
    # a blank line in the collapsed view which is worse than a clamp-3 fallback.
    if not summary_block:
        return None, content

    return summary_block, details_block or content


def _parse_sections_from_markdown(markdown: str) -> list[dict[str, Any]]:
    """Parse a markdown narrative into structured ``[{title, bullets[]}]`` sections.

    Recognised section headings: ``## Heading``, ``### Heading``, or bold-only lines
    (``**Heading**``). Bullets: lines starting with ``- ``, ``* `` or ``• ``.

    PLAN-0049 T-A-1-04: when the LLM honours the v2.2 prompt and emits a clean
    ``## DETAILS`` block split into ``### Drivers`` / ``### Implications`` /
    ``### Risks``, this parser produces a structured ``BriefSection[]`` payload
    that the frontend renders as polished cards. When parsing fails (no
    headings, no bullets, malformed markdown) we return ``[]`` and the
    frontend falls back to ``<MarkdownContent>`` over the raw narrative —
    no UI breakage either way.

    Hard caps: ≤8 bullets per section, ≤120 chars per section title — matches
    the ``BriefSection`` Pydantic constraints so callers can hand the result
    straight to ``BriefSection(**...)`` without further validation.
    """
    if not markdown or not markdown.strip():
        return []

    sections: list[dict[str, Any]] = []
    current_title: str | None = None
    current_bullets: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_bullets
        if current_title and current_bullets:
            # Cap bullets to 8 (matches Pydantic `max_length=8`); cap title to 120.
            sections.append(
                {
                    "title": current_title[:120],
                    "bullets": current_bullets[:8],
                }
            )
        current_title = None
        current_bullets = []

    heading_re = re.compile(r"^\s{0,3}(#{2,3})\s+(.+?)\s*$")
    bold_only_re = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
    bullet_re = re.compile(r"^\s*(?:[-*•])\s+(.+)$")

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m_h = heading_re.match(line)
        m_b = bold_only_re.match(line) if not m_h else None
        if m_h:
            flush()
            current_title = m_h.group(2).strip()
            continue
        if m_b:
            flush()
            current_title = m_b.group(1).strip()
            continue
        m_bullet = bullet_re.match(line)
        if m_bullet and current_title:
            bullet_text = m_bullet.group(1).strip()
            if bullet_text:
                current_bullets.append(bullet_text)
    flush()

    # Discard the result if it's a single section with one bullet — that means
    # we mis-parsed prose as a section. Frontend renders narrative instead.
    if len(sections) == 1 and len(sections[0]["bullets"]) <= 1:
        return []
    return sections


def _strip_block_header(block: str, expected: str) -> str:
    """Remove a leading ``## SUMMARY`` / ``## DETAILS`` header from ``block``.

    Case-insensitive; tolerates 1-3 leading ``#`` characters and an optional
    trailing colon. Returns the block unchanged if no matching header is found.
    """
    lines = block.splitlines()
    if not lines:
        return block
    first = lines[0].strip().lower().rstrip(":")
    # Match "# summary", "## summary", "### summary" — same for "details".
    if first in (f"# {expected}", f"## {expected}", f"### {expected}", expected):
        return "\n".join(lines[1:]).lstrip()
    return block


# ── PLAN-0062-W4 citation-aware parser and helpers ────────────────────────────


def _materialize_brief_citations(ctx: Any) -> list[BriefCitation]:
    """Build a flat ordered list of BriefCitation from gathered context (T-W4-B-03).

    WHY ordered list: the v3.0 prompt numbers context items as [c1], [c2], …
    in the order returned by _format_news / _format_events / _format_alerts.
    _parse_sections_with_citations resolves [cN] markers by 1-based index into
    this list, so the ORDER here must match the order those format functions use.

    ORDERING: news articles first (indexed 1…N), then events (N+1…), then alerts.
    This mirrors the order of sections in the prompt template.

    snippet construction:
      - article: title[:240] + " — " + summary[:160]
      - event:   event_type + ": " + event_text[:240]
      - alert:   "[SEVERITY] alert_type: message[:240]"

    Returns [] when ctx is None (graceful degradation — no context gatherer wired).
    """
    if ctx is None:
        return []

    citations: list[BriefCitation] = []

    # 1. News articles (up to 8, matches _format_news cap)
    for a in (ctx.news_articles or [])[:8]:
        title_part = (a.title or "")[:240]
        summary_part = (a.summary or "")[:160] if hasattr(a, "summary") and a.summary else ""
        snippet = (f"{title_part} — {summary_part}" if summary_part else title_part)[:400]
        # WHY [:400]: BriefCitation.snippet has max_length=400 (Pydantic constraint).
        citations.append(
            BriefCitation(
                document_id=str(a.article_id),
                snippet=snippet[:400],
                url=getattr(a, "url", None),
                source_type="article",
                title=a.title,
            )
        )

    # 2. Recent events (up to 6, matches _format_events cap)
    for ev in (ctx.recent_events or [])[:6]:
        event_text = getattr(ev, "event_text", "") or ""
        event_type = getattr(ev, "event_type", "") or ""
        snippet = f"{event_type}: {event_text[:240]}"[:400]
        citations.append(
            BriefCitation(
                document_id=str(ev.event_id),
                snippet=snippet,
                url=None,
                source_type="event",
                title=f"{event_type}: {event_text[:80]}",
            )
        )

    # 3. Active alerts (up to 5, matches _format_alerts cap) — morning brief only
    for alert in (getattr(ctx, "active_alerts", None) or [])[:5]:
        severity = getattr(alert, "severity", "").upper()
        alert_type = getattr(alert, "alert_type", "")
        message = (getattr(alert, "payload", None) or {}).get("message", "")
        snippet = f"[{severity}] {alert_type}: {message}"[:400]
        citations.append(
            BriefCitation(
                document_id=str(alert.alert_id),
                snippet=snippet,
                url=None,
                source_type="alert",
                title=f"[{severity}] {alert_type}",
            )
        )

    return citations


def _parse_sections_with_citations(
    markdown: str,
    context_citations: list[BriefCitation],
) -> tuple[str | None, list[BriefCitation], list[BriefSection]]:
    """Parse the v3.0 two-block brief into (lead, lead_citations, sections) (T-W4-B-02).

    The v3.0 MORNING_BRIEFING/INSTRUMENT_BRIEFING prompts emit:
        ## LEAD
        <1-2 sentences> [c1][c3]

        ---

        ## DETAILS
        ### Section Title
        - Bullet text [cN]
        ...

    Returns:
        lead:             lead text with [cN] markers KEPT (they reference citations
                          inline), truncated at sentence boundary ≤600 chars.
                          None when no valid lead or no valid lead citations.
        lead_citations:   citations referenced in the lead block (resolved from markers).
        sections:         list[BriefSection] with BriefBullet objects (citations attached,
                          [cN] markers stripped from bullet text). Empty list on parse fail.

    WHY [cN] markers kept in lead (stripped from bullets):
    - Lead is rendered as prose — the citation markers serve as inline footnotes.
    - Bullets are rendered as discrete items with separate CitationChip UI — markers
      are stripped from display text and attached as BriefBullet.citations instead.

    out-of-range [cN] → that specific citation is silently skipped (not the whole bullet).
    lead with no valid citations → lead=None (no lead to show without evidence).
    """
    if not markdown or not markdown.strip():
        return None, [], []

    # ── Split on first --- divider ─────────────────────────────────────────────
    # WHY line-mode split: see _split_summary_and_details() above for rationale —
    # the divider must be on its own line to avoid false splits on em-dash ranges.
    lines = markdown.splitlines()
    divider_idx: int | None = None
    for i, line in enumerate(lines[:50]):
        if line.strip() == "---":
            divider_idx = i
            break

    if divider_idx is None:
        # No divider — assume legacy single-block output; fall back to old parser.
        return None, [], []

    lead_block = "\n".join(lines[:divider_idx]).strip()
    details_block = "\n".join(lines[divider_idx + 1 :]).strip()

    # ── Parse lead block ───────────────────────────────────────────────────────
    lead_block = _strip_block_header(lead_block, "lead")
    # Also strip "## summary" (back-compat with v2.2 LLM responses that emit SUMMARY)
    lead_block = _strip_block_header(lead_block, "summary")
    lead_block = lead_block.strip()

    lead_citations: list[BriefCitation] = []
    lead_text: str | None = None

    if lead_block:
        # Resolve [cN] markers in lead — keep them in the text for inline display
        raw_indices = [int(m) - 1 for m in _CN_CITATION_RE.findall(lead_block)]
        lead_citations = [context_citations[idx] for idx in raw_indices if 0 <= idx < len(context_citations)]

        if lead_citations:
            # Truncate at sentence boundary ≤600 chars
            lead_text = _truncate_at_sentence(lead_block, max_chars=600)
        # else: no valid citations in lead → lead_text remains None

    # ── Parse details block ────────────────────────────────────────────────────
    details_block = _strip_block_header(details_block, "details")
    sections = _parse_detail_sections_with_citations(details_block, context_citations)

    return lead_text, lead_citations, sections


def _parse_detail_sections_with_citations(
    markdown: str,
    context_citations: list[BriefCitation],
) -> list[BriefSection]:
    """Parse the ## DETAILS block into list[BriefSection] with BriefBullet objects.

    WHY separate from _parse_sections_with_citations: keeps the top-level function
    focused on the LEAD/DETAILS split; this function handles section/bullet parsing.

    Recognised section headings: ## Heading, ### Heading, **Bold**.
    Bullets: lines starting with - , * , or •.
    [cN] markers are extracted from each bullet's text (resolved to BriefCitation
    objects), then stripped from the display text.

    out-of-range [cN]: silently skip that specific citation reference.
    Bullets with no valid citations: collected into a list; the backfill pass
    (_backfill_uncited_bullets) will attach fallback citations or drop them.

    Hard caps: ≤4 sections, ≤4 bullets per section, ≤120 chars per section title —
    matches the BriefSection Pydantic constraints.
    """
    if not markdown or not markdown.strip():
        return []

    sections: list[BriefSection] = []
    current_title: str | None = None
    # WHY list[tuple]: store (display_text, citations) so we can build BriefBullet
    # objects at flush time (after all bullets for the section are collected).
    current_bullets: list[tuple[str, list[BriefCitation]]] = []

    heading_re = re.compile(r"^\s{0,3}(#{2,3})\s+(.+?)\s*$")
    bold_only_re = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
    bullet_re = re.compile(r"^\s*(?:[-*•])\s+(.+)$")

    def flush() -> None:
        """Flush current section into sections list."""
        nonlocal current_title, current_bullets
        if current_title and current_bullets:
            # Cap bullets at 4 (v3.0 prompt targets ≤4); cap title at 120.
            # WHY 4 instead of 8: v3.0 tightened to <=4 x <=4.
            bullet_pairs = current_bullets[:4]
            # Construct BriefBullet objects only for bullets that have citations.
            # Bullets without citations are dropped HERE — BriefBullet.citations
            # has min_length=1 so we cannot construct one with an empty list.
            # The backfill pass will handle adding fallback citations later.
            built_bullets = [
                BriefBullet(text=text[:400], citations=cites)
                for text, cites in bullet_pairs
                if cites  # only include bullets that already have valid citations
            ]
            # WHY include section even with 0 bullets: backfill will populate
            # them or drop the section. An empty BriefSection is valid (min=0).
            if current_title[:120] and len(sections) < 4:  # cap at 4 sections
                sections.append(BriefSection(title=current_title[:120], bullets=built_bullets))
        current_title = None
        current_bullets = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        m_h = heading_re.match(line)
        m_b = bold_only_re.match(line) if not m_h else None
        if m_h:
            flush()
            current_title = m_h.group(2).strip()
            continue
        if m_b:
            flush()
            current_title = m_b.group(1).strip()
            continue
        m_bullet = bullet_re.match(line)
        if m_bullet and current_title:
            raw_text = m_bullet.group(1).strip()
            if not raw_text:
                continue
            # Extract [cN] markers and resolve to BriefCitation objects
            raw_indices = [int(m) - 1 for m in _CN_CITATION_RE.findall(raw_text)]
            bullet_citations = [context_citations[idx] for idx in raw_indices if 0 <= idx < len(context_citations)]
            # Strip [cN] markers from the display text
            display_text = _CN_CITATION_RE.sub("", raw_text).strip()
            if display_text:
                current_bullets.append((display_text, bullet_citations))
    flush()

    # Discard single-section / single-bullet results (mis-parsed prose guard)
    if len(sections) == 1 and len(sections[0].bullets) <= 1:
        return []
    return sections


def _backfill_uncited_bullets(
    sections: list[BriefSection],
    context_citations: list[BriefCitation],
) -> list[BriefSection]:
    """Attach fallback citations to uncited bullets and drop empties (T-W4-B-03).

    Called AFTER _parse_sections_with_citations. Any BriefBullet that already
    has citations passes through unchanged. Sections that were constructed with
    0 bullets (because all bullets lacked citations) get the first available
    context citation attached to each bullet… but wait — the parser only creates
    BriefBullet for cited bullets. Sections that had ONLY uncited bullets will
    have 0 BriefBullets but some un-constructed (dropped) bullets.

    WHY this function: the parser drops uncited bullets at construction time
    (BriefBullet.citations min_length=1 prevents empty-citation objects).
    This function's job is to drop empty sections that result from all their
    bullets being uncited, and to verify the invariant that no BriefBullet
    with empty citations reaches the output.

    In the current implementation, uncited bullet TEXT is lost at parser time
    (not stored separately), so we cannot retroactively attach citations to them.
    The backfill therefore:
    1. Removes sections with 0 BriefBullets (all their bullets were uncited).
    2. Passes all other sections through unchanged (their bullets already have cites).

    IMPORTANT: DO NOT construct BriefBullet(citations=[]) here — that violates
    the min_length=1 gate and would defeat the entire citation guarantee.
    MUST use list comprehensions (not in-place mutation) because BriefSection
    is a Pydantic BaseModel (not frozen, but immutable-by-convention).
    """
    if not context_citations:
        # No citations at all — drop all sections (can't guarantee citation coverage)
        return []

    # Drop sections that ended up with 0 bullets (all were uncited).
    # Sections with ≥1 bullet already have valid citations (enforced by parser).
    result = [sec for sec in sections if len(sec.bullets) > 0]
    return result


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate text at the nearest sentence boundary at or before max_chars.

    WHY sentence boundary (not hard cut): cutting mid-sentence produces
    grammatically broken lead text. We prefer a shorter but complete sentence.

    If no sentence boundary is found within max_chars, we hard-cut at max_chars.
    The returned string is ALWAYS ≤ max_chars characters (including any suffix).
    """
    if len(text) <= max_chars:
        return text
    # Look for sentence-ending punctuation before the cut point
    truncated = text[:max_chars]
    # Find the last sentence-ending punctuation (position of the '.' or '!' char)
    last_end = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
        truncated.rfind(".\n"),
        truncated.rfind("!\n"),
        truncated.rfind("?\n"),
    )
    # WHY > 0 (not > max_chars//2): any sentence boundary is better than a hard cut.
    # The previous > max_chars//2 guard was too aggressive — it rejected boundaries
    # near the start of the text (e.g. "First sentence." at index 15 in 600-char text).
    if last_end > 0:
        # Include the punctuation char itself (last_end is the index of the '.', etc.)
        return truncated[: last_end + 1].strip()
    # No clean boundary — hard cut; append ellipsis only if room allows
    # WHY -1: reserve 1 char for the ellipsis so total stays ≤ max_chars.
    clipped = truncated[: max_chars - 1].rstrip().rstrip(".,;:")
    return clipped + "…"


def _compute_confidence(
    sections: list[BriefSection],
    lead: str | None,
    lead_citations: list[BriefCitation],
) -> float:
    """Compute the composite citation confidence score (T-W4-B-04).

    Formula:
        total_bullets   = count of BriefBullet objects across all sections
        cited_bullets   = bullets where citations is non-empty (always true after backfill,
                          but computed defensively)
        bullet_density  = cited_bullets / total_bullets  (0.0 when no bullets)
        lead_density    = 1.0 if lead is non-None AND lead_citations is non-empty
        composite       = 0.4 * lead_density + 0.6 * bullet_density
        total_citations = all bullet citations + lead citations
        coverage_factor = min(1.0, total_citations / 8.0)
        confidence      = round(min(1.0, composite * coverage_factor), 4)

    WHY weighted average (not product): a brief with a great bullet section but
    no lead should score ~0.6, not ~0 (as a product would give). The weighted
    average reflects "mostly cited" gracefully.

    WHY coverage_factor / 8: with <8 total citations the score is scaled down
    proportionally — forces the LLM to use ALL available context sources.
    """
    total_bullets = sum(len(s.bullets) for s in sections)
    cited_bullets = sum(1 for s in sections for b in s.bullets if b.citations)
    bullet_density = (cited_bullets / total_bullets) if total_bullets else 0.0

    lead_density = 1.0 if (lead and lead_citations) else 0.0

    composite_density = (0.4 * lead_density) + (0.6 * bullet_density)

    total_citations = sum(len(b.citations) for s in sections for b in s.bullets) + len(lead_citations)
    coverage_factor = min(1.0, total_citations / 8.0)

    confidence = round(min(1.0, composite_density * coverage_factor), 4)
    return confidence


class GenerateBriefingUseCase:
    """Generate an AI-narrative portfolio risk brief for email delivery or frontend.

    Args:
        llm_chain:        LLM provider chain (DeepInfra → OpenRouter → Ollama).
        valkey:           Valkey client for daily rate-limit counters.
        context_gatherer: Optional BriefingContextGatherer for gathering upstream
                          context in execute_public_morning() / execute_public_instrument().
                          When None, public methods degrade gracefully.

    Note:
        Authentication is handled by InternalJWTMiddleware (PRD-0025) at the
        API layer before this use case is invoked.
    """

    def __init__(
        self,
        llm_chain: LLMProviderChain,
        valkey: ValkeyClient,  # type: ignore[name-defined]
        context_gatherer: BriefingContextGatherer | None = None,  # optional — degrades gracefully
        brief_archive: BriefArchivePort | None = None,  # PLAN-0066 Wave B — optional persistence
    ) -> None:
        self._llm_chain = llm_chain
        self._valkey = valkey
        self._context_gatherer = context_gatherer  # None when wired without context gathering
        # WHY NullBriefArchive default: callers that do not wire a real archive
        # (e.g. unit tests, email briefing path) continue to work without any
        # code change. Production wires BriefArchiveRepository via DI.
        self._brief_archive: BriefArchivePort = brief_archive if brief_archive is not None else NullBriefArchive()

    async def execute(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
    ) -> dict[str, Any]:
        """Run the briefing pipeline.

        Returns a dict with keys: narrative, risk_summary, citations, generated_at.

        Raises:
            RateLimitExceededError: User has exceeded 100 briefings today.
            ProviderUnavailableError: All LLM providers failed.
        """
        # ── 0. Anti-hallucination guard (BP-184) ─────────────────────────────
        # When portfolio_context is empty or contains no meaningful holdings/
        # positions, the LLM fabricates realistic-looking but false portfolio data.
        # Instead of letting that happen, return an empty narrative immediately so
        # the email template can render a "no data available" message rather than
        # fictional risk analysis.
        # WHY check market_snapshots type: the API schema validates it as
        # list[dict] with min_length=1 but we guard defensively here.
        _context_has_data = any(
            [
                portfolio_context.get("holdings"),
                portfolio_context.get("positions"),
                # Exclude the sentinel "morning_overview" type which carries no
                # real per-holding data — only real position snapshots count.
                bool(market_snapshots)
                and any(isinstance(s, dict) and s.get("type") != "morning_overview" for s in market_snapshots),
            ]
        )
        if not _context_has_data:
            log.warning(  # type: ignore[no-any-return]
                "briefing_empty_context_guard",
                user_id=str(user_id),
                detail="All context empty — returning placeholder narrative to prevent hallucination",
            )
            return {
                "narrative": "",
                "risk_summary": {},
                "citations": [],
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }

        # ── 1. Daily rate limit (100/day per user_id) ─────────────────────────
        await self._check_daily_rate_limit(user_id)

        # ── 3. Build prompt ───────────────────────────────────────────────────
        prompt = self._build_prompt(
            user_id=user_id,
            tenant_id=tenant_id,
            portfolio_context=portfolio_context,
            market_snapshots=market_snapshots,
            active_signals=active_signals,
            lookback_days=lookback_days,
        )

        # ── 4. LLM completion (collect streaming tokens) ─────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(
            prompt,
            max_tokens=6000,
            temperature=0.1,
        ):
            chunks.append(chunk)
        narrative = "".join(chunks)

        # ── 5. Derive risk_summary from input signals ─────────────────────────
        risk_summary = self._build_risk_summary(
            portfolio_context=portfolio_context,
            active_signals=active_signals,
        )

        generated_at = datetime.now(tz=UTC).isoformat()

        log.info(  # type: ignore[no-any-return]
            "briefing_generated",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            narrative_chars=len(narrative),
        )

        return {
            "narrative": narrative,
            "risk_summary": risk_summary,
            "citations": [],
            "generated_at": generated_at,
        }

    async def _check_daily_rate_limit(self, user_id: UUID) -> None:
        """Increment the daily briefing counter and raise if over limit.

        Key format: ``rag:v1:briefing:rl:{user_id}:{YYYY-MM-DD}`` (UTC date).
        TTL is 25 hours to cover DST transitions.
        """
        today = datetime.now(tz=UTC).date().isoformat()
        key = f"{_BRIEFING_RL_PREFIX}:{user_id}:{today}"

        count = await self._valkey.incr(key)
        if count == 1:
            # First request today — set expiry
            await self._valkey.expire(key, _BRIEFING_RL_TTL)

        if count > _DAILY_RATE_LIMIT:
            raise RateLimitExceededError(
                f"Briefing rate limit exceeded: {count} requests today (limit: {_DAILY_RATE_LIMIT})",
            )

    def _build_prompt(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]],
        lookback_days: int,
    ) -> str:
        """Assemble the EMAIL_DEEP_BRIEF prompt with XML-wrapped context."""
        context_block = (
            f"<portfolio_context>\n{json.dumps(portfolio_context, indent=2)}\n</portfolio_context>\n\n"
            f"<market_snapshots lookback_days='{lookback_days}'>\n"
            f"{json.dumps(market_snapshots, indent=2)}\n</market_snapshots>\n\n"
        )
        if active_signals:
            context_block += f"<active_signals>\n{json.dumps(active_signals, indent=2)}\n</active_signals>\n\n"

        return (
            f"{EMAIL_DEEP_BRIEF_PROMPT}\n\n"
            f"<context>\n{context_block}</context>\n\n"
            f"Generate the portfolio risk brief for user {user_id} (tenant {tenant_id})."
        )

    def _build_risk_summary(
        self,
        *,
        portfolio_context: dict[str, Any],
        active_signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Derive a structured risk summary from input data (no extra LLM call).

        Computes a simple concentration score from portfolio positions if available.
        """
        positions: list[dict[str, Any]] = portfolio_context.get("positions", [])

        # Concentration score: 1.0 = fully concentrated in one position
        concentration_score: float = 0.0
        sector_breakdown: dict[str, float] = {}
        if positions:
            total_value = sum(float(p.get("value", 0)) for p in positions)
            if total_value > 0:
                weights = [float(p.get("value", 0)) / total_value for p in positions]
                # Herfindahl-Hirschman Index normalised to [0, 1]
                concentration_score = round(sum(w * w for w in weights), 4)

            for pos in positions:
                sector = str(pos.get("sector", "unknown"))
                value = float(pos.get("value", 0))
                sector_breakdown[sector] = round(
                    sector_breakdown.get(sector, 0.0) + (value / total_value if total_value > 0 else 0.0),
                    4,
                )

        top_risk_signals = [
            {"signal_id": str(s.get("id", "")), "description": str(s.get("description", ""))}
            for s in active_signals[:5]  # cap at 5 top signals
        ]

        return {
            "concentration_score": concentration_score,
            "top_risk_signals": top_risk_signals,
            "sector_breakdown": sector_breakdown,
        }

    # ── Public briefing methods (frontend-facing) ────────────────────────────

    async def execute_public_morning(
        self,
        user_id: str,
        tenant_id: str,
        internal_jwt: str | None = None,
    ) -> dict[str, Any]:
        """Generate a morning portfolio briefing for an authenticated frontend user.

        Called by GET /api/v1/briefings/morning (public_briefings.py route).
        Uses BriefingContextGatherer to assemble context from S1/S3/S5/S6/S7,
        then renders MORNING_BRIEFING prompt and streams LLM completion.

        Rate-limited: 100 requests/day per user_id (same counter as execute()).

        Returns dict with keys: content, risk_summary, entity_mentions, citations, generated_at

        Raises:
            RateLimitExceededError: User has exceeded 100 briefings today.
            ProviderUnavailableError: All LLM providers failed.
        """
        from prompts._safety import SAFETY_FOOTER  # type: ignore[import-untyped]
        from prompts.briefing.morning import MORNING_BRIEFING  # type: ignore[import-untyped]

        # ── 1. Daily rate limit (shared counter with execute()) ───────────────
        # WHY convert to UUID: _check_daily_rate_limit builds a Valkey key with
        # str(user_id) — a UUID string is stable and avoids ambiguous formats.
        try:
            uid_for_rl = UUID(user_id)
        except (ValueError, AttributeError):
            uid_for_rl = UUID("00000000-0000-0000-0000-000000000000")
        await self._check_daily_rate_limit(uid_for_rl)

        # ── 2. Gather context via BriefingContextGatherer ─────────────────────
        ctx = None
        if self._context_gatherer is not None:
            try:
                ctx = await self._context_gatherer.gather_morning_context(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    internal_jwt=internal_jwt,
                )
            except Exception as exc:
                # R9 safe degradation: log warning, proceed without context
                log.warning("morning_context_gathering_failed", error=str(exc))  # type: ignore[no-any-return]
                ctx = None

        # ── 3. Build prompt sections from context ─────────────────────────────
        # WHY: datetime.now(tz=UTC).date() is the UTC-aware equivalent of date.today()
        # and avoids DTZ011 (date.today() is timezone-naive).
        today = datetime.now(tz=UTC).date().isoformat()
        portfolio_text = _format_portfolio_morning(ctx)
        # WHY compute citation offsets here: news is [c1..cN], events are [c(N+1)..],
        # alerts are [c(N+events+1)..]. Offsets must match _materialize_brief_citations
        # ordering so [cN] markers in the LLM output resolve to the correct documents.
        news_count = len((ctx.news_articles or [])[:8]) if ctx else 0
        events_count = len((ctx.recent_events or [])[:6]) if ctx else 0
        news_text = _format_news(ctx, citation_offset=0)
        events_text = _format_events(ctx, citation_offset=news_count)
        alerts_text = _format_alerts(ctx, citation_offset=news_count + events_count)
        market_text = _format_market_overview(ctx)

        # ── 3b. Empty context guard ───────────────────────────────────────────
        # WHY: When all upstream services are unavailable or return empty data,
        # the LLM receives a completely empty prompt and degrades to a retail-grade
        # disclaimer ("Please ensure all relevant context sections are populated").
        # This is unacceptable for institutional users. Return a professional
        # placeholder so the UI renders something useful instead of LLM confusion.
        all_sections_empty = not any([portfolio_text, news_text, alerts_text, market_text, events_text])
        if all_sections_empty:
            log.warning("morning_briefing_empty_context", user_id=user_id)  # type: ignore[no-any-return]
            generated_at = datetime.now(tz=UTC).isoformat()
            return {
                "content": (
                    "Portfolio data is being synchronized with upstream services. "
                    "Your morning briefing will be available shortly — "
                    "please refresh in a few minutes."
                ),
                "risk_summary": _build_morning_risk_summary(ctx),
                "entity_mentions": [],
                "citations": [],
                "generated_at": generated_at,
            }

        prompt = MORNING_BRIEFING.render(
            safety=SAFETY_FOOTER,
            current_date=today,
            portfolio_context=portfolio_text,
            news_context=news_text,
            alerts_context=alerts_text,
            market_overview=market_text,
            events_context=events_text,
        )

        # ── 4. LLM completion (collect streaming tokens) ──────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(prompt, max_tokens=2000, temperature=0.1):
            chunks.append(chunk)
        content = _strip_reasoning("".join(chunks))

        # ── 4b. PLAN-0062-W4: citation-aware parse pipeline ───────────────────
        # Build the citation index (ordered list matching [c1], [c2], … in prompt).
        context_citations = _materialize_brief_citations(ctx)

        # Parse the v3.0 two-block output (LEAD + DETAILS) with [cN] resolution.
        # Falls back to (None, [], []) for legacy single-block output (no --- divider).
        lead, lead_citations, sections = _parse_sections_with_citations(content, context_citations)

        # Backfill: drop sections with 0 cited bullets (can't guarantee citation coverage).
        sections = _backfill_uncited_bullets(sections, context_citations)

        # ── 4c. Legacy two-tier fallback (PLAN-0048 Wave A back-compat) ───────
        # When v3.0 parse fails (old cached LLM output), try the v2.2 SUMMARY/DETAILS
        # split so the summary field still populates for existing cached briefs.
        # WHY both: during rollout, cached responses may still use the v2.2 format.
        summary, narrative = _split_summary_and_details(content)

        # ── 5. Derive risk_summary from portfolio holdings (HHI concentration) ─
        risk_summary = _build_morning_risk_summary(ctx)

        # ── 6. Build citations and entity mentions from gathered context ───────
        citations = _build_citations(ctx)
        entity_mentions = _extract_entity_mentions(ctx)

        # ── 7. Compute confidence score ────────────────────────────────────────
        confidence = _compute_confidence(sections, lead, lead_citations)

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "morning_briefing_generated",
            user_id=user_id,
            chars=len(narrative),
            has_lead=lead is not None,
            sections_count=len(sections),
            confidence=confidence,
        )

        # PLAN-0049 T-A-1-04: also parse narrative into legacy dict-based sections
        # for the legacy structured render path (sections with string bullets).
        # WHY keep: cached briefs and fallback render paths still use this.
        # PLAN-0062-W4: sections (BriefBullet) takes precedence; legacy_sections
        # is only used when the new parser returned no sections.
        legacy_sections = _parse_sections_from_markdown(narrative) if not sections else []

        # ── 8. PLAN-0066 Wave B: fire-and-forget brief persistence ───────────
        # WHY asyncio.shield: DB failures must NEVER propagate back to the caller
        # (this is a cache/analytics write, not the primary response path). The
        # shield ensures that even if the event loop cancels the task, the DB
        # write attempt is not interrupted mid-flight.
        # WHY ensure_future (not create_task): ensure_future is available in
        # Python 3.12 without requiring an explicit running loop reference.
        # WHY skip persistence on cached returns: the cache-hit path returns
        # early (before this code), so we only persist genuinely fresh generations.
        try:
            _uid = UUID(user_id)
        except (ValueError, AttributeError):
            _uid = UUID("00000000-0000-0000-0000-000000000000")
        try:
            _tid = UUID(tenant_id)
        except (ValueError, AttributeError):
            _tid = UUID("00000000-0000-0000-0000-000000000000")

        # Build sections_json: coerce BriefSection dataclasses → plain dicts.
        # citations_json: BriefCitation dataclasses → plain dicts using to_dict().
        # WHY cast to Any: sections is list[BriefSection] and legacy_sections is
        # list[dict]; mypy cannot unify the types in the conditional. We explicitly
        # cast to Any and then normalise each entry to dict in the comprehension.
        _raw_sections: Any = sections if sections else legacy_sections
        _sections_json: list[dict] = [
            s.to_dict() if hasattr(s, "to_dict") else (s if isinstance(s, dict) else {}) for s in _raw_sections
        ]
        _citations_json: list[dict] = [
            c.to_dict() if hasattr(c, "to_dict") else (c if isinstance(c, dict) else {}) for c in citations
        ]

        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        _record = UserBriefRecord(
            id=new_uuid7(),
            user_id=_uid,
            tenant_id=_tid,
            brief_type="morning",
            entity_id=None,
            generated_at=utc_now(),
            headline=(lead or narrative or "")[:500],  # WHY [:500]: headline col is Text, but keep it concise
            lead=lead,
            sections_json=_sections_json,
            citations_json=_citations_json,
            confidence=confidence,
            source_version="v2",
        )

        _archive = self._brief_archive

        async def _persist_brief(record: UserBriefRecord) -> None:
            """Fire-and-forget DB write — exceptions are logged, never raised."""
            try:
                await _archive.save(record)
            except Exception as exc:
                # WHY warn (not error): persistence failure is non-critical for
                # the user experience. The brief is already generated; the archive
                # is best-effort analytics storage.
                log.warning("brief_persist_failed", error=str(exc))  # type: ignore[no-any-return]

        # asyncio.shield prevents cancellation from interrupting the DB write.
        # WHY store _task reference: RUF006 — storing the future prevents it from
        # being garbage-collected before the event loop runs it (Python GC can
        # collect unreferenced tasks mid-execution on CPython implementations).
        _task = asyncio.ensure_future(asyncio.shield(_persist_brief(_record)))
        # Attach a no-op done callback so the task reference is kept alive until
        # the event loop finalises it — avoids "Task destroyed but it is pending"
        # warnings in tests and concurrent request scenarios.
        _task.add_done_callback(lambda _: None)

        return {
            # ``content`` keeps the field name expected by the route layer (which
            # maps result["content"] → response.narrative). The narrative half of
            # the split goes here so the expanded card view shows the structured
            # ## DETAILS sections without the redundant ## SUMMARY heading.
            "content": narrative,
            # ``summary`` is the v2.2 fallback — None when the LLM didn't emit
            # the v2.2 two-tier format. Preserved for back-compat.
            "summary": summary,
            # PLAN-0062-W4: return v3.0 BriefSection list when available; otherwise
            # use legacy string-bullet sections for backward compatibility.
            "sections": sections if sections else legacy_sections,
            "risk_summary": risk_summary,
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
            # PLAN-0062-W4 new fields
            "lead": lead,
            "confidence": confidence,
        }

    async def execute_public_instrument(
        self,
        entity_id: str,
    ) -> dict[str, Any]:
        """Generate an instrument-specific briefing.

        Called by GET /api/v1/briefings/instrument/{entity_id}.
        Uses BriefingContextGatherer to fetch entity graph + fundamentals + news.

        Returns dict with keys: content, risk_summary (None), entity_mentions, citations, generated_at

        Raises:
            EntityNotFoundError: entity_id not found in knowledge graph.
            ProviderUnavailableError: All LLM providers failed.
        """
        from prompts._safety import SAFETY_FOOTER  # type: ignore[import-untyped]
        from prompts.briefing.instrument import INSTRUMENT_BRIEFING  # type: ignore[import-untyped]

        if self._context_gatherer is None:
            # No context gatherer wired — degrade gracefully rather than crashing
            log.warning("instrument_brief_no_context_gatherer", entity_id=entity_id)  # type: ignore[no-any-return]
            return {
                "content": "Instrument briefing context gatherer not configured.",
                "risk_summary": None,
                "entity_mentions": [],
                "citations": [],
                "generated_at": datetime.now(tz=UTC).isoformat(),
            }

        # gather_instrument_context raises EntityNotFoundError if entity not in KG
        # — let the exception propagate to the route handler for a 404 response
        ctx = await self._context_gatherer.gather_instrument_context(entity_id=entity_id)

        # ── Build prompt sections ─────────────────────────────────────────────
        entity_text = _format_entity_context(ctx)
        fundamentals_text = _format_fundamentals(ctx)
        # WHY citation offsets: instrument brief uses news + events only (no alerts).
        # news = [c1..cN], events = [c(N+1)..].
        news_count_inst = len((ctx.news_articles or [])[:8]) if ctx else 0
        news_text = _format_news(ctx, citation_offset=0)
        events_text = _format_events(ctx, citation_offset=news_count_inst)
        relationships_text = _format_relationships(ctx)

        prompt = INSTRUMENT_BRIEFING.render(
            safety=SAFETY_FOOTER,
            entity_context=entity_text,
            fundamentals_context=fundamentals_text,
            news_context=news_text,
            events_context=events_text,
            relationships_context=relationships_text,
        )

        # ── LLM completion ────────────────────────────────────────────────────
        chunks: list[str] = []
        async for chunk in self._llm_chain.stream(prompt, max_tokens=1500, temperature=0.1):
            chunks.append(chunk)
        content = _strip_reasoning("".join(chunks))

        # ── Build citations and entity mentions ───────────────────────────────
        citations = _build_citations(ctx)
        entity_mentions = _extract_entity_mentions(ctx)

        # ── PLAN-0062-W4: citation-aware parse pipeline ────────────────────────
        context_citations = _materialize_brief_citations(ctx)
        lead, lead_citations, sections = _parse_sections_with_citations(content, context_citations)
        sections = _backfill_uncited_bullets(sections, context_citations)
        confidence = _compute_confidence(sections, lead, lead_citations)

        # Legacy fallback when v3.0 parse returned no sections
        if not sections:
            sections = _parse_sections_from_markdown(content)  # type: ignore[assignment]
            # WHY type: ignore: _parse_sections_from_markdown returns list[dict]
            # (legacy format with string bullets) which the route layer handles.

        generated_at = datetime.now(tz=UTC).isoformat()
        log.info(  # type: ignore[no-any-return]
            "instrument_briefing_generated",
            entity_id=entity_id,
            chars=len(content),
            has_lead=lead is not None,
            sections_count=len(sections),
            confidence=confidence,
        )

        return {
            "content": content,
            "risk_summary": None,  # instrument brief has no portfolio — risk_summary is None
            "entity_mentions": entity_mentions,
            "citations": citations,
            "generated_at": generated_at,
            "sections": sections,
            # PLAN-0062-W4 new fields
            "lead": lead,
            "confidence": confidence,
        }


# ── Module-level context-formatting helpers ──────────────────────────────────
# These functions accept a BriefingContext (or None) and return formatted strings
# for use in prompt templates. They are module-level (not methods) so they can
# be used by both execute_public_morning() and execute_public_instrument().


def _format_portfolio_morning(ctx: Any) -> str:
    """Format portfolio holdings + watchlist for the morning brief prompt."""
    if ctx is None or ctx.portfolio is None:
        return ""
    p = ctx.portfolio
    lines: list[str] = []
    if p.holdings:
        lines.append(f"Holdings ({p.total_positions} positions):")
        for h in p.holdings:
            name = h.canonical_name or h.ticker or "Unknown"
            weight = f"{h.current_weight:.1%}" if h.current_weight else "N/A"
            lines.append(f"  - {name}: {h.quantity} units, weight {weight}")
    if p.watchlist:
        lines.append("Watchlist:")
        for w in p.watchlist:
            name = w.canonical_name or w.ticker or "Unknown"
            lines.append(f"  - {name}")
    return "\n".join(lines)


def _format_news(ctx: Any, citation_offset: int = 0) -> str:
    """Format news articles from context into a readable list with [cN] prefixes.

    WHY [cN] prefixes: the v3.0 prompt requires stable citation indices so the LLM
    can embed [c1], [c2], … markers in its bullets. The offset parameter allows the
    caller to continue numbering from where a previous section left off (news is
    always first so offset=0).

    NOTE: citation_offset is unused here (news is always first), but the parameter
    is included for symmetry with _format_events and _format_alerts so callers can
    use the same pattern.
    """
    if ctx is None or not ctx.news_articles:
        return ""
    lines: list[str] = []
    for i, a in enumerate(ctx.news_articles[:8]):
        cn = f"[c{citation_offset + i + 1}]"
        date_str = a.published_at.strftime("%Y-%m-%d") if a.published_at else "unknown date"
        score = f" (relevance: {a.display_relevance_score:.0%})" if a.display_relevance_score else ""
        lines.append(f"{cn} [{date_str}] {a.title}{score}")
        if a.url:
            lines.append(f"  Source: {a.url}")
    return "\n".join(lines)


def _format_alerts(ctx: Any, citation_offset: int = 0) -> str:
    """Format active alerts from context with [cN] prefixes.

    WHY citation_offset: alerts come after news + events in the citation index.
    The caller computes offset = len(news) + len(events) so alert items get
    contiguous [cN] indices.
    """
    if ctx is None or not ctx.active_alerts:
        return ""
    lines: list[str] = []
    for i, alert in enumerate(ctx.active_alerts[:5]):
        cn = f"[c{citation_offset + i + 1}]"
        lines.append(
            f"{cn} [{alert.severity.upper()}] {alert.alert_type}: {alert.payload.get('message', '')}",
        )
    return "\n".join(lines)


def _format_market_overview(ctx: Any) -> str:
    """Format market overview snapshot."""
    if ctx is None or ctx.market_overview is None:
        return ""
    mo = ctx.market_overview
    lines: list[str] = []
    if mo.sector_performance:
        lines.append("Sector performance:")
        for sector, pct in sorted(mo.sector_performance.items(), key=lambda x: -abs(x[1]))[:5]:
            lines.append(f"  - {sector}: {pct:+.1%}")
    return "\n".join(lines)


def _format_events(ctx: Any, citation_offset: int = 0) -> str:
    """Format structured events from context with [cN] prefixes.

    WHY citation_offset: events come after news items in the citation index.
    The caller sets offset = len(news_articles) so events are numbered
    [c(N+1)], [c(N+2)], … continuing from where news left off.
    """
    if ctx is None or not ctx.recent_events:
        return ""
    lines: list[str] = []
    for i, ev in enumerate(ctx.recent_events[:6]):
        cn = f"[c{citation_offset + i + 1}]"
        date_str = ev.event_date.strftime("%Y-%m-%d") if ev.event_date else "unknown date"
        lines.append(f"{cn} [{date_str}] {ev.event_type}: {ev.event_text[:200]}")
    return "\n".join(lines)


def _format_entity_context(ctx: Any) -> str:
    """Format the center entity's basic info for an instrument brief."""
    if ctx is None or ctx.entity_graph is None:
        return ""
    eg = ctx.entity_graph
    lines = [
        f"Entity: {eg.canonical_name}",
        f"Type: {eg.entity_type}",
    ]
    if eg.ticker:
        lines.append(f"Ticker: {eg.ticker}")
    return "\n".join(lines)


def _fmt_usd_billions(value: Any) -> str:
    """Format a raw integer dollar value (e.g. 2_800_000_000_000) as '$X.XXB'.

    EODHD returns MarketCapitalization and RevenueTTM as raw integers (full USD).
    The LLM must receive a pre-formatted human string — otherwise it picks random
    unit conventions (sometimes billions, sometimes trillions, sometimes raw bytes).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v >= 1e12:
        return f"${v / 1e12:.2f}T"
    if v >= 1e9:
        return f"${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _fmt_percent(value: Any) -> str:
    """Format a decimal ratio (e.g. 0.2543) as 'XX.X%'.

    EODHD returns margin/growth fields as raw floats in [0, 1] (or negative).
    """
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_fundamentals(ctx: Any) -> str:
    """Format fundamental data highlights for an instrument brief.

    Reports a curated set of financial metrics when present in the data dict.
    Missing metrics are silently omitted (no 'N/A' placeholders — prompt template
    instructs the LLM to write 'Not in retrieved context' for absent metrics).

    All raw EODHD values are pre-formatted into human-readable strings before
    being passed to the LLM to prevent unit-convention hallucinations (BP-F-002).
    """
    if ctx is None or ctx.fundamentals is None:
        return ""
    data = ctx.fundamentals.data

    # Fields that arrive as raw integer USD values and must be scaled to B/T.
    # NOTE: MarketCapitalizationMln is intentionally excluded — it conflicts with
    # MarketCapitalization and causes the LLM to present the same metric twice in
    # different units. Use only the raw-integer canonical field.
    large_usd_fields: dict[str, str] = {
        "MarketCapitalization": "Market Cap",
        "RevenueTTM": "Revenue TTM",
    }

    # Fields that arrive as decimal ratios in [-1, 1] and must be shown as %.
    percent_fields: dict[str, str] = {
        "ProfitMargin": "Net Profit Margin",
        "OperatingMarginTTM": "Operating Margin TTM",
        "QuarterlyRevenueGrowthYOY": "Revenue Growth YoY",
        "QuarterlyEarningsGrowthYOY": "Earnings Growth YoY",
    }

    # Fields rendered verbatim (already in correct unit or not financial amounts).
    verbatim_fields: dict[str, str] = {
        "PERatio": "P/E TTM",
        "DilutedEpsTTM": "EPS TTM (USD)",
        "EPSEstimateNextYear": "EPS Est. Next FY (USD)",
        "WallStreetTargetPrice": "Consensus Target (USD)",
        "MostRecentQuarter": "Most Recent Quarter",
    }

    lines: list[str] = []
    for key, label in large_usd_fields.items():
        if key in data:
            lines.append(f"- **{label}**: {_fmt_usd_billions(data[key])}")
    for key, label in percent_fields.items():
        if key in data:
            lines.append(f"- **{label}**: {_fmt_percent(data[key])}")
    for key, label in verbatim_fields.items():
        if key in data:
            lines.append(f"- **{label}**: {data[key]}")
    return "\n".join(lines) if lines else ""


def _format_relationships(ctx: Any) -> str:
    """Format entity relationships from the knowledge graph as a markdown table."""
    if ctx is None or ctx.entity_graph is None or not ctx.entity_graph.relationships:
        return ""
    lines = ["| Entity | Relation | Confidence |", "|--------|----------|------------|"]
    for rel in ctx.entity_graph.relationships[:10]:
        target = rel.get("target_name", rel.get("target_entity_id", "Unknown"))
        rel_type = rel.get("relation_type", "RELATED_TO")
        confidence = float(rel.get("confidence", 0.0))
        lines.append(f"| {target} | {rel_type} | {confidence:.0%} |")
    return "\n".join(lines)


def _build_morning_risk_summary(ctx: Any) -> dict[str, Any]:
    """Compute HHI concentration score from portfolio holdings.

    Mirrors the logic in GenerateBriefingUseCase._build_risk_summary() but
    operates on BriefingContext.portfolio rather than a raw dict.
    Returns 0.0 concentration when context or portfolio is unavailable.
    """
    concentration_score: float = 0.0
    sector_breakdown: dict[str, float] = {}

    if ctx is not None and ctx.portfolio is not None and ctx.portfolio.holdings:
        holdings = ctx.portfolio.holdings
        total_weight = sum(float(h.current_weight or 0.0) for h in holdings)
        if total_weight > 0:
            weights = [float(h.current_weight or 0.0) / total_weight for h in holdings]
            # Herfindahl-Hirschman Index normalised to [0, 1]
            concentration_score = round(sum(w * w for w in weights), 4)

    return {
        "concentration_score": concentration_score,
        "sector_breakdown": sector_breakdown,
    }


def _build_citations(ctx: Any) -> list[dict[str, Any]]:
    """Build a structured citation list from articles, events, and alerts in context.

    Each citation includes BOTH 'source_id' (legacy) and 'document_id' (PLAN-0062-W4)
    so older clients that read 'source_id' continue to work, and new clients can
    use 'document_id' (the canonical field on BriefCitation).

    PLAN-0062-W4 (T-W4-C-02): added 'document_id' and 'snippet' fields so the
    top-level citations list can be used by the frontend to display citation
    chips, while the per-bullet citations in BriefSection.bullets are the
    primary citation mechanism.

    WHY separate from _materialize_brief_citations: _build_citations returns the
    top-level 'citations' list (legacy compatibility for old frontend code).
    _materialize_brief_citations returns the ordered list used by the parser to
    resolve [cN] markers into per-bullet BriefCitation objects.
    """
    if ctx is None:
        return []
    citations: list[dict[str, Any]] = []

    # Articles
    for a in ctx.news_articles or []:
        title_part = (a.title or "")[:240]
        summary_part = (getattr(a, "summary", None) or "")[:160]
        snippet = (f"{title_part} — {summary_part}" if summary_part else title_part)[:400]
        citations.append(
            {
                "source_type": "article",
                # WHY both: back-compat (source_id) + new canonical (document_id)
                "source_id": str(a.article_id),
                "document_id": str(a.article_id),
                "title": a.title,
                "url": a.url,
                "snippet": snippet[:400],
            }
        )

    # Structured events
    for ev in ctx.recent_events or []:
        event_text = getattr(ev, "event_text", "") or ""
        event_type = getattr(ev, "event_type", "") or ""
        snippet = f"{event_type}: {event_text[:200]}"[:400]
        citations.append(
            {
                "source_type": "event",
                "source_id": str(ev.event_id),
                "document_id": str(ev.event_id),
                "title": f"{event_type}: {event_text[:80]}",
                "url": None,
                "snippet": snippet,
            }
        )

    # Alerts (morning brief only — instrument context has no alerts)
    for alert in ctx.active_alerts or []:
        severity = getattr(alert, "severity", "").upper()
        alert_type = getattr(alert, "alert_type", "")
        message = (getattr(alert, "payload", None) or {}).get("message", "")
        snippet = f"[{severity}] {alert_type}: {message}"[:400]
        citations.append(
            {
                "source_type": "alert",
                "source_id": str(alert.alert_id),
                "document_id": str(alert.alert_id),
                "title": f"[{severity}] {alert_type}",
                "url": None,
                "snippet": snippet,
            }
        )

    return citations


def _extract_entity_mentions(ctx: Any) -> list[dict[str, Any]]:
    """Extract entity mentions from BriefingContext for the response payload.

    For morning briefs: extracts holdings + watchlist entities.
    For instrument briefs: extracts the center entity + relationship targets.

    Returns list of dicts with keys: entity_id, name, ticker.
    Deduplicates by entity_id (first occurrence wins).
    """
    if ctx is None:
        return []
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Morning: portfolio holdings and watchlist
    if ctx.portfolio is not None:
        for h in ctx.portfolio.holdings:
            eid = str(h.entity_id) if h.entity_id else None
            if eid and eid not in seen and (h.canonical_name or h.ticker):
                seen.add(eid)
                mentions.append(
                    {
                        "entity_id": eid,
                        "name": h.canonical_name or h.ticker or "",
                        "ticker": h.ticker,
                    }
                )
        for w in ctx.portfolio.watchlist:
            eid = str(w.entity_id) if w.entity_id else None
            if eid and eid not in seen and (w.canonical_name or w.ticker):
                seen.add(eid)
                mentions.append(
                    {
                        "entity_id": eid,
                        "name": w.canonical_name or w.ticker or "",
                        "ticker": w.ticker,
                    }
                )

    # Instrument: center entity from entity_graph
    if ctx.entity_graph is not None:
        eid = ctx.entity_graph.entity_id
        if eid and eid not in seen and ctx.entity_graph.canonical_name:
            seen.add(eid)
            mentions.append(
                {
                    "entity_id": eid,
                    "name": ctx.entity_graph.canonical_name,
                    "ticker": ctx.entity_graph.ticker,
                }
            )
        # Relationship targets also become entity mentions
        for rel in ctx.entity_graph.relationships or []:
            target_id = rel.get("target_entity_id", "")
            target_name = rel.get("target_name", "")
            if target_id and target_id not in seen and target_name:
                seen.add(target_id)
                mentions.append(
                    {
                        "entity_id": target_id,
                        "name": target_name,
                        "ticker": None,
                    }
                )

    return mentions
