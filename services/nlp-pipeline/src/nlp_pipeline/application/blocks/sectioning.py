"""Block 3 — Document Sectioning (PRD §6.7 Block 3).

Source-specific sectioners parse a document's clean text into structural
sections. A factory dispatches to the correct sectioner by source_type.
If no sections are produced, a synthetic fallback section covers the full text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.domain.models import Section

if TYPE_CHECKING:
    from uuid import UUID

# ── Sectioner implementations ─────────────────────────────────────────────────


class NewsParagraphSectioner:
    """Paragraph-based sectioner for news articles and press releases.

    Splits on double-newlines (≥30 chars). Used for: eodhd_news, finnhub_news,
    newsapi_news, press_release.
    """

    def section(self, doc_id: UUID, text: str) -> list[Section]:
        paragraphs = re.split(r"\n{2,}", text)
        sections: list[Section] = []
        offset = 0
        idx = 0
        for para in paragraphs:
            stripped = para.strip()
            # Find actual start position within original text
            start = text.find(para, offset)
            end = start + len(para)
            offset = end
            if len(stripped) < 30:
                continue
            sections.append(
                Section(
                    section_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    section_index=idx,
                    char_start=start,
                    char_end=end,
                    text=stripped,
                    section_type="body",
                )
            )
            idx += 1
        return sections


class SECEdgarSectioner:
    """Item-header sectioner for SEC EDGAR filings (10-K, 10-Q, 8-K, DEF14A).

    Splits on ``^Item N[A].`` patterns per SEC filing structure.
    """

    _ITEM_RE = re.compile(r"^(Item\s+\d+[A-Z]?\.\s+[^\n]+)", re.MULTILINE | re.IGNORECASE)

    def section(self, doc_id: UUID, text: str) -> list[Section]:
        matches = list(self._ITEM_RE.finditer(text))
        if not matches:
            return []
        sections: list[Section] = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            if not content:
                continue
            sections.append(
                Section(
                    section_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    section_index=i,
                    char_start=start,
                    char_end=end,
                    text=content,
                    section_type="heading",
                    title=match.group(1).strip(),
                )
            )
        return sections


class FinnhubTranscriptSectioner:
    """Speaker-turn sectioner for Finnhub earnings call transcripts.

    Each speaker-turn (``Name: text``) becomes one section.
    """

    _SPEAKER_RE = re.compile(r"^([A-Z][^:\n]{2,50}):\s*(.+?)(?=^[A-Z][^:\n]{2,50}:|\Z)", re.MULTILINE | re.DOTALL)

    def section(self, doc_id: UUID, text: str) -> list[Section]:
        matches = list(self._SPEAKER_RE.finditer(text))
        if not matches:
            return []
        sections: list[Section] = []
        for i, match in enumerate(matches):
            speaker_name = match.group(1).strip()
            content = match.group(2).strip()
            if not content:
                continue
            sections.append(
                Section(
                    section_id=common.ids.new_uuid7(),
                    doc_id=doc_id,
                    section_index=i,
                    char_start=match.start(),
                    char_end=match.end(),
                    text=content,
                    section_type="speaker_turn",
                    speaker=speaker_name,
                )
            )
        return sections


class SyntheticSectioner:
    """Fallback sectioner — wraps the entire text in a single body section.

    Used when: (a) source_type is unknown, or (b) a source-specific sectioner
    returns zero sections.
    """

    def section(self, doc_id: UUID, text: str) -> list[Section]:
        stripped = text.strip()
        if not stripped:
            return []
        return [
            Section(
                section_id=common.ids.new_uuid7(),
                doc_id=doc_id,
                section_index=0,
                char_start=0,
                char_end=len(text),
                text=stripped,
                section_type="body",
            )
        ]


# ── Source-type → sectioner mapping ──────────────────────────────────────────

_SEC_TYPES = frozenset({"sec_10k", "sec_10q", "sec_8k", "sec_def14a"})
_NEWS_TYPES = frozenset({"eodhd_news", "finnhub_news", "newsapi_news", "press_release", "manual"})

_news_sectioner = NewsParagraphSectioner()
_sec_sectioner = SECEdgarSectioner()
_transcript_sectioner = FinnhubTranscriptSectioner()
_synthetic_sectioner = SyntheticSectioner()


def section_document(doc_id: UUID, text: str, source_type: str) -> list[Section]:
    """Factory: dispatch to the correct sectioner by source_type.

    Always returns ≥1 section — falls back to SyntheticSectioner if the
    source-specific sectioner produces no results (PRD §6.7 Block 3 step 5).
    """
    # UTF-8 normalisation already done upstream (Block 3 step 1-2)
    if source_type in _SEC_TYPES:
        sectioner: NewsParagraphSectioner | SECEdgarSectioner | FinnhubTranscriptSectioner = _sec_sectioner
    elif source_type in _NEWS_TYPES:
        sectioner = _news_sectioner
    elif source_type == "earnings_call":
        sectioner = _transcript_sectioner
    else:
        # Unknown source — go straight to synthetic
        return _synthetic_sectioner.section(doc_id, text)

    sections = sectioner.section(doc_id, text)

    if not sections:
        # Fallback: zero sections → one synthetic section covering full text
        sections = _synthetic_sectioner.section(doc_id, text)

    return sections
