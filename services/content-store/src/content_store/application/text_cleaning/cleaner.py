"""Text extraction, sanitization, and normalization pipeline.

Handles 4 content types: HTML, XML, JSON, plain text.
Produces clean, normalized text suitable for deduplication and downstream NLP.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

import bleach  # type: ignore[import-untyped]
import structlog

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Safe HTML tags kept during sanitization (for display, not for dedup)
_SAFE_TAGS = frozenset(
    {
        "p",
        "br",
        "b",
        "i",
        "em",
        "strong",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "blockquote",
        "pre",
        "code",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)


def extract(raw_bytes: bytes, content_type: str) -> str:
    """Extract readable text from raw bytes based on content type.

    Args:
        raw_bytes: Raw content bytes.
        content_type: One of 'html', 'xml', 'json', 'text'.

    Returns:
        Extracted text string.

    Raises:
        ValueError: If content_type is unsupported.
    """
    ct = content_type.lower().strip()

    if ct == "html":
        return _extract_html(raw_bytes)
    if ct == "xml":
        return _extract_xml(raw_bytes)
    if ct == "json":
        return _extract_json(raw_bytes)
    if ct in {"text", "plain", "text/plain"}:
        return _extract_text(raw_bytes)

    msg = f"Unsupported content_type: {content_type!r}"
    raise ValueError(msg)


def sanitize(html: str) -> str:
    """Strip unsafe HTML tags, keeping only safe structural tags.

    Args:
        html: Raw or partially cleaned HTML string.

    Returns:
        Sanitized HTML with only safe tags.
    """
    return bleach.clean(html, tags=_SAFE_TAGS, attributes={}, strip=True)  # type: ignore[no-any-return]


def normalize(text: str) -> str:
    """Normalize text for consistent comparison.

    - NFC Unicode normalization
    - Strip zero-width characters
    - Collapse whitespace
    - Strip leading/trailing whitespace

    Args:
        text: Input text.

    Returns:
        Normalized text.
    """
    # NFC normalization
    text = unicodedata.normalize("NFC", text)
    # Strip zero-width characters (U+200B, U+200C, U+200D, U+FEFF)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean(raw_bytes: bytes, content_type: str) -> str:
    """Full cleaning pipeline: extract -> normalize.

    Args:
        raw_bytes: Raw content bytes.
        content_type: Content type identifier.

    Returns:
        Clean, normalized text ready for dedup.
    """
    extracted = extract(raw_bytes, content_type)
    return normalize(extracted)


# ── Private extraction helpers ────────────────────────────────────────────────


def _extract_html(raw_bytes: bytes) -> str:
    """Extract readable text from HTML using readability-lxml."""
    from readability import Document  # type: ignore[import-untyped,import-not-found]

    html_str = raw_bytes.decode("utf-8", errors="replace")
    doc = Document(html_str)
    # Get the readable article content (still HTML)
    summary_html = doc.summary()
    # Strip all HTML tags to get plain text
    text: str = bleach.clean(summary_html, tags=set(), strip=True)
    return text


def _extract_xml(raw_bytes: bytes) -> str:
    """Extract text from XML by stripping all tags."""
    xml_str = raw_bytes.decode("utf-8", errors="replace")
    # Strip all XML/HTML tags
    text: str = bleach.clean(xml_str, tags=set(), strip=True)
    return text


def _extract_json(raw_bytes: bytes) -> str:
    """Extract text from JSON by recursively collecting string values."""
    json_str = raw_bytes.decode("utf-8", errors="replace")
    data = json.loads(json_str)
    parts: list[str] = []
    _collect_strings(data, parts)
    return " ".join(parts)


def _extract_text(raw_bytes: bytes) -> str:
    """Decode raw bytes as UTF-8 plain text."""
    return raw_bytes.decode("utf-8", errors="replace")


def _collect_strings(obj: Any, acc: list[str]) -> None:
    """Recursively collect string values from a JSON structure."""
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped:
            acc.append(stripped)
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_strings(value, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_strings(item, acc)
