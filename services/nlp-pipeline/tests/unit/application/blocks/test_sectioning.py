"""Unit tests for Block 3 — Sectioning (T-C-2-05)."""

from __future__ import annotations

import uuid

import pytest
from nlp_pipeline.application.blocks.sectioning import (
    FinnhubTranscriptSectioner,
    NewsParagraphSectioner,
    SECEdgarSectioner,
    SyntheticSectioner,
    section_document,
)

pytestmark = pytest.mark.unit


def _doc_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.unit
class TestNewsParagraphSectioner:
    def test_splits_on_double_newline(self) -> None:
        text = (
            "Apple reported record breaking earnings this quarter.\n\n"
            "Revenues grew 15% year-over-year beating analyst estimates.\n\n"
            "Analysts were uniformly surprised by the strong margin expansion."
        )
        sections = NewsParagraphSectioner().section(_doc_id(), text)
        assert len(sections) == 3

    def test_skips_short_paragraphs(self) -> None:
        text = "Short.\n\nThis is a longer paragraph with more than 30 characters total."
        sections = NewsParagraphSectioner().section(_doc_id(), text)
        # "Short." (6 chars) is below threshold
        assert len(sections) == 1

    def test_section_type_is_body(self) -> None:
        text = "This paragraph has enough content to pass the 30-char threshold check here."
        sections = NewsParagraphSectioner().section(_doc_id(), text)
        assert all(s.section_type == "body" for s in sections)

    def test_empty_text_returns_empty(self) -> None:
        sections = NewsParagraphSectioner().section(_doc_id(), "")
        assert sections == []

    def test_section_indices_are_sequential(self) -> None:
        text = (
            "First long paragraph with more than 30 characters certainly.\n\n"
            "Second long paragraph with more than 30 characters certainly.\n\n"
            "Third long paragraph with more than 30 characters certainly."
        )
        sections = NewsParagraphSectioner().section(_doc_id(), text)
        indices = [s.section_index for s in sections]
        assert indices == list(range(len(sections)))


@pytest.mark.unit
class TestSECEdgarSectioner:
    def test_splits_on_item_headers(self) -> None:
        text = (
            "Item 1. Business\n\nApple Inc. designs and markets consumer electronics.\n\n"
            "Item 1A. Risk Factors\n\nThere are risks associated with operating in Asia.\n\n"
            "Item 2. Properties\n\nThe company leases offices worldwide."
        )
        sections = SECEdgarSectioner().section(_doc_id(), text)
        assert len(sections) == 3

    def test_section_type_is_heading(self) -> None:
        text = "Item 1. Business\n\nContent here.\nItem 2. Risk\n\nMore content here."
        sections = SECEdgarSectioner().section(_doc_id(), text)
        assert all(s.section_type == "heading" for s in sections)

    def test_no_items_returns_empty(self) -> None:
        text = "This filing has no item headers at all."
        sections = SECEdgarSectioner().section(_doc_id(), text)
        assert sections == []

    def test_title_captured(self) -> None:
        text = "Item 1A. Risk Factors\n\nVarious risks exist."
        sections = SECEdgarSectioner().section(_doc_id(), text)
        assert len(sections) == 1
        assert sections[0].title is not None
        assert "Risk Factors" in sections[0].title


@pytest.mark.unit
class TestFinnhubTranscriptSectioner:
    def test_splits_on_speaker_turns(self) -> None:
        text = (
            "Tim Cook: Good morning everyone. We had a strong quarter.\n"
            "Luca Maestri: Thank you Tim. Revenue was up significantly this quarter.\n"
            "Analyst Jones: Can you provide more color on services revenue?\n"
        )
        sections = FinnhubTranscriptSectioner().section(_doc_id(), text)
        assert len(sections) >= 2

    def test_speaker_field_populated(self) -> None:
        text = (
            "Tim Cook: Good morning everyone. We had a strong quarter with great results.\n"
            "Luca Maestri: Thank you Tim. Revenue was up significantly this quarter.\n"
        )
        sections = FinnhubTranscriptSectioner().section(_doc_id(), text)
        speakers = {s.speaker for s in sections if s.speaker}
        assert "Tim Cook" in speakers or len(speakers) >= 1

    def test_section_type_is_speaker_turn(self) -> None:
        text = (
            "Tim Cook: Welcome to the earnings call with quarterly results available.\n"
            "Luca Maestri: Financial highlights include revenue growth this quarter.\n"
        )
        sections = FinnhubTranscriptSectioner().section(_doc_id(), text)
        for s in sections:
            assert s.section_type == "speaker_turn"


@pytest.mark.unit
class TestSyntheticSectioner:
    def test_returns_single_section(self) -> None:
        text = "Some content that cannot be sectioned by any specific sectioner."
        sections = SyntheticSectioner().section(_doc_id(), text)
        assert len(sections) == 1
        assert sections[0].section_index == 0
        assert sections[0].section_type == "body"

    def test_covers_full_text(self) -> None:
        text = "Full document content here."
        sections = SyntheticSectioner().section(_doc_id(), text)
        assert sections[0].text == text.strip()
        assert sections[0].char_start == 0
        assert sections[0].char_end == len(text)

    def test_empty_text_returns_empty(self) -> None:
        sections = SyntheticSectioner().section(_doc_id(), "   ")
        assert sections == []


@pytest.mark.unit
class TestSectionDocumentFactory:
    def test_sec_type_uses_sec_sectioner(self) -> None:
        text = "Item 1. Business\n\nContent.\nItem 2. Risk\n\nRisk content here."
        sections = section_document(_doc_id(), text, "sec_10k")
        assert len(sections) >= 1

    def test_news_type_uses_paragraph_sectioner(self) -> None:
        text = (
            "Breaking: Apple reports record earnings this quarter.\n\n"
            "The technology giant surpassed analyst expectations for the third consecutive quarter."
        )
        sections = section_document(_doc_id(), text, "eodhd_news")
        assert len(sections) >= 1

    def test_unknown_type_uses_synthetic(self) -> None:
        text = "Some unknown source type document content that needs a fallback sectioner."
        sections = section_document(_doc_id(), text, "unknown_source_xyz")
        assert len(sections) == 1
        assert sections[0].section_type == "body"

    def test_always_returns_at_least_one_section(self) -> None:
        """Fallback guarantee: even if sectioner returns nothing, we get ≥1 section."""
        # Text that SEC sectioner won't match
        text = "No item headers here, just plain text for a filing source type."
        sections = section_document(_doc_id(), text, "sec_10k")
        assert len(sections) >= 1

    def test_earnings_call_dispatched_correctly(self) -> None:
        text = (
            "Tim Cook: Thank you for joining our quarterly earnings call today.\n"
            "Analyst: What were the highlights this quarter for Apple?\n"
        )
        sections = section_document(_doc_id(), text, "earnings_call")
        assert len(sections) >= 1
