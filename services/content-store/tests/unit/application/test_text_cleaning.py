"""Unit tests for text cleaning pipeline."""

from __future__ import annotations

import json

import pytest
from content_store.application.text_cleaning.cleaner import (
    clean,
    extract,
    normalize,
    sanitize,
)

pytestmark = pytest.mark.unit


# ── extract() — HTML ─────────────────────────────────────────────────────────


class TestExtractHTML:
    def test_extracts_text_from_simple_html(self) -> None:
        html = b"<html><body><p>Hello world</p></body></html>"
        result = extract(html, "html")
        assert "Hello world" in result

    def test_strips_tags(self) -> None:
        html = b"<html><body><div><b>Bold</b> <i>italic</i></div></body></html>"
        result = extract(html, "html")
        assert "<b>" not in result
        assert "Bold" in result

    def test_handles_malformed_html(self) -> None:
        html = b"<p>Unclosed paragraph <b>with bold"
        result = extract(html, "html")
        assert "Unclosed paragraph" in result


# ── extract() — XML ──────────────────────────────────────────────────────────


class TestExtractXML:
    def test_strips_xml_tags(self) -> None:
        xml = b"<root><item>First</item><item>Second</item></root>"
        result = extract(xml, "xml")
        assert "First" in result
        assert "Second" in result
        assert "<item>" not in result

    def test_handles_nested_xml(self) -> None:
        xml = b"<doc><section><title>Title</title><body>Content</body></section></doc>"
        result = extract(xml, "xml")
        assert "Title" in result
        assert "Content" in result


# ── extract() — JSON ─────────────────────────────────────────────────────────


class TestExtractJSON:
    def test_extracts_string_values(self) -> None:
        data = {"title": "Test Article", "body": "Article content here"}
        raw = json.dumps(data).encode()
        result = extract(raw, "json")
        assert "Test Article" in result
        assert "Article content here" in result

    def test_recursive_extraction(self) -> None:
        data = {"nested": {"deep": {"value": "Found it"}}, "list": ["a", "b"]}
        raw = json.dumps(data).encode()
        result = extract(raw, "json")
        assert "Found it" in result
        assert "a" in result
        assert "b" in result

    def test_skips_non_string_values(self) -> None:
        data = {"count": 42, "active": True, "text": "Hello"}
        raw = json.dumps(data).encode()
        result = extract(raw, "json")
        assert "Hello" in result

    def test_skips_empty_strings(self) -> None:
        data = {"a": "", "b": "  ", "c": "Valid"}
        raw = json.dumps(data).encode()
        result = extract(raw, "json")
        assert "Valid" in result


# ── extract() — plain text ───────────────────────────────────────────────────


class TestExtractText:
    def test_decodes_utf8(self) -> None:
        text = "Hello UTF-8 café"
        result = extract(text.encode("utf-8"), "text")
        assert result == text

    def test_handles_plain_content_type(self) -> None:
        result = extract(b"Simple text", "plain")
        assert result == "Simple text"

    def test_handles_text_plain_content_type(self) -> None:
        result = extract(b"Simple text", "text/plain")
        assert result == "Simple text"

    def test_replaces_invalid_bytes(self) -> None:
        result = extract(b"Hello \xff\xfe world", "text")
        assert "Hello" in result
        assert "world" in result


# ── extract() — unsupported type ─────────────────────────────────────────────


class TestExtractUnsupported:
    def test_raises_on_unknown_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported content_type"):
            extract(b"data", "binary")


# ── sanitize() ───────────────────────────────────────────────────────────────


class TestSanitize:
    def test_keeps_safe_tags(self) -> None:
        html = "<p>Paragraph</p><b>Bold</b>"
        result = sanitize(html)
        assert "<p>" in result
        assert "<b>" in result

    def test_strips_script_tags(self) -> None:
        html = "<p>Safe</p><script>alert('xss')</script>"
        result = sanitize(html)
        assert "<script>" not in result
        assert "Safe" in result

    def test_strips_iframe_tags(self) -> None:
        html = '<iframe src="evil.com"></iframe><p>Safe</p>'
        result = sanitize(html)
        assert "<iframe>" not in result
        assert "Safe" in result


# ── normalize() ──────────────────────────────────────────────────────────────


class TestNormalize:
    def test_nfc_normalization(self) -> None:
        # é as combining sequence → NFC form
        combining = "e\u0301"  # e + combining accent
        result = normalize(combining)
        assert result == "\u00e9"  # NFC é

    def test_strips_zero_width_chars(self) -> None:
        text = "Hello\u200bWorld\u200c!\ufeff"
        result = normalize(text)
        assert result == "HelloWorld!"

    def test_collapses_whitespace(self) -> None:
        text = "  Hello   World  \n\t  Test  "
        result = normalize(text)
        assert result == "Hello World Test"

    def test_empty_string(self) -> None:
        assert normalize("") == ""

    def test_single_space(self) -> None:
        assert normalize("   ") == ""


# ── clean() — full pipeline ──────────────────────────────────────────────────


class TestCleanPipeline:
    def test_html_full_pipeline(self) -> None:
        html = "<html><body><p>  Hello   \u200b World  </p></body></html>".encode()
        result = clean(html, "html")
        # Should be extracted and normalized
        assert "Hello" in result
        assert "\u200b" not in result

    def test_json_full_pipeline(self) -> None:
        data = {"text": "  Multiple   spaces  here  "}
        raw = json.dumps(data).encode()
        result = clean(raw, "json")
        assert result == "Multiple spaces here"
