"""BriefParser — parses raw LLM response into structured BriefSection list.

Extracted from generate_briefing.py (PLAN-0089 C-3) so that all LLM output
parsing logic lives in one dedicated class rather than being scattered as
module-level helpers. The class wraps the same helper functions that were
previously defined at module level; their behaviour is unchanged (pure refactor).

Functions / methods moved here:
  - _strip_reasoning          → BriefParser._strip_reasoning (static)
  - _split_summary_and_details → BriefParser.split_summary_and_details
  - _parse_sections_from_markdown → BriefParser.parse_sections_from_markdown
  - _strip_block_header       → BriefParser._strip_block_header (static)
  - _materialize_brief_citations → BriefParser.materialize_brief_citations
  - _parse_sections_with_citations → BriefParser.parse_sections_with_citations
  - _parse_detail_sections_with_citations → BriefParser._parse_detail_sections_with_citations
  - _backfill_uncited_bullets → BriefParser.backfill_uncited_bullets
  - _truncate_at_sentence     → BriefParser._truncate_at_sentence (static)
  - _compute_confidence       → BriefParser.compute_confidence
"""

from __future__ import annotations

import re
from typing import Any

from rag_chat.domain.brief import BriefBullet, BriefCitation, BriefSection

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

# D-R4-002 (PLAN-0087, 2026-05-09): the LLM occasionally echoes the prompt's
# Jinja variable names as bracketed tokens (e.g. ``[relationships_context]``,
# ``[entity_context]``, ``[fundamentals_context]``, ``[news_context]``,
# ``[events_context]``).  These leaked into bullet text and rendered visibly
# in MorningBriefCard / instrument News tab — see audit R4 for AAPL bullet
# evidence.  Strip them defensively before bullet text is exposed.
_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"\s*\[(?:relationships_context|entity_context|fundamentals_context|news_context"
    r"|events_context|portfolio_context|safety|context|input)\]"
)


class BriefParser:
    """Parses raw LLM response into structured BriefSection list.

    All methods are pure functions (no internal state), grouped here so that
    generate_briefing.py can delegate all parsing concerns to a single object
    and tests can exercise parsing logic in isolation.
    """

    # ── Preprocessing ─────────────────────────────────────────────────────────

    @staticmethod
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

    # ── v2.2 two-tier split ────────────────────────────────────────────────────

    @staticmethod
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

    def split_summary_and_details(self, content: str) -> tuple[str | None, str]:
        """Split a v2.2 morning brief into ``(summary, narrative)``.

        The LLM is instructed to emit a ``## SUMMARY`` block, a literal ``---``
        divider line, then a ``## DETAILS`` block. Older prompts and instrument
        briefs emit a single block with no divider — those return ``(None, full_text)``
        so the frontend can degrade gracefully.

        Both returned strings have their leading ``## SUMMARY`` / ``## DETAILS``
        headers stripped — the card chrome already labels the two views, so the
        duplicate headers would just steal vertical space.

        WHY a strict line-mode split (not ``str.split("---", 1)``):
        Markdown content can legitimately contain ``---`` mid-paragraph (e.g. an
        em-dash range). Requiring the divider to be on its own line eliminates
        false-positive splits.
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
        summary_block = self._strip_block_header(summary_block, "summary")
        # v3.0 LLM output uses "## LEAD" (not "## SUMMARY") for the first block.
        # Strip it here so the collapsed card view shows clean prose, not an H2 heading.
        summary_block = self._strip_block_header(summary_block, "lead")
        details_block = self._strip_block_header(details_block, "details")

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

    # ── Legacy markdown section parser (v2.2 fallback) ─────────────────────────

    def parse_sections_from_markdown(self, markdown: str) -> list[dict[str, Any]]:
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

    # ── v3.0 citation-aware parser ─────────────────────────────────────────────

    @staticmethod
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

    def materialize_brief_citations(self, ctx: Any) -> list[BriefCitation]:
        """Build a flat ordered list of BriefCitation from gathered context (T-W4-B-03).

        WHY ordered list: the v3.0 prompt numbers context items as [c1], [c2], …
        in the order returned by _format_news / _format_events / _format_alerts.
        parse_sections_with_citations resolves [cN] markers by 1-based index into
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

    def _parse_detail_sections_with_citations(
        self,
        markdown: str,
        context_citations: list[BriefCitation],
    ) -> list[BriefSection]:
        """Parse the ## DETAILS block into list[BriefSection] with BriefBullet objects.

        WHY separate from parse_sections_with_citations: keeps the top-level function
        focused on the LEAD/DETAILS split; this function handles section/bullet parsing.

        Recognised section headings: ## Heading, ### Heading, **Bold**.
        Bullets: lines starting with - , * , or •.
        [cN] markers are extracted from each bullet's text (resolved to BriefCitation
        objects), then stripped from the display text.

        out-of-range [cN]: silently skip that specific citation reference.
        Bullets with no valid citations: collected into a list; the backfill pass
        (backfill_uncited_bullets) will attach fallback citations or drop them.

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
                # D-R4-002: defensively strip bracketed prompt-template variable
                # names the LLM occasionally echoes back (e.g. [relationships_context]).
                display_text = _TEMPLATE_PLACEHOLDER_RE.sub("", display_text).strip()
                if display_text:
                    current_bullets.append((display_text, bullet_citations))
        flush()

        # Discard single-section / single-bullet results (mis-parsed prose guard)
        if len(sections) == 1 and len(sections[0].bullets) <= 1:
            return []
        return sections

    def parse_sections_with_citations(
        self,
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
        # WHY line-mode split: see split_summary_and_details() above for rationale —
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
        lead_block = self._strip_block_header(lead_block, "lead")
        # Also strip "## summary" (back-compat with v2.2 LLM responses that emit SUMMARY)
        lead_block = self._strip_block_header(lead_block, "summary")
        lead_block = lead_block.strip()
        # D-R4-002: strip echoed Jinja variable names from the lead too.
        lead_block = _TEMPLATE_PLACEHOLDER_RE.sub("", lead_block).strip()
        details_block = _TEMPLATE_PLACEHOLDER_RE.sub("", details_block)

        lead_citations: list[BriefCitation] = []
        lead_text: str | None = None

        if lead_block:
            # Resolve [cN] markers in lead — keep them in the text for inline display
            raw_indices = [int(m) - 1 for m in _CN_CITATION_RE.findall(lead_block)]
            lead_citations = [context_citations[idx] for idx in raw_indices if 0 <= idx < len(context_citations)]

            if lead_citations:
                # Truncate at sentence boundary ≤600 chars
                lead_text = self._truncate_at_sentence(lead_block, max_chars=600)
            # else: no valid citations in lead → lead_text remains None

        # ── Parse details block ────────────────────────────────────────────────────
        details_block = self._strip_block_header(details_block, "details")
        sections = self._parse_detail_sections_with_citations(details_block, context_citations)

        return lead_text, lead_citations, sections

    def backfill_uncited_bullets(
        self,
        sections: list[BriefSection],
        context_citations: list[BriefCitation],
    ) -> list[BriefSection]:
        """Attach fallback citations to uncited bullets and drop empties (T-W4-B-03).

        Called AFTER parse_sections_with_citations. Any BriefBullet that already
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

    def compute_confidence(
        self,
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

    # ── Convenience top-level method (delegates to _strip_reasoning) ───────────

    def strip_reasoning(self, text: str) -> str:
        """Public entry point for stripping <think> blocks and code fences."""
        return self._strip_reasoning(text)
