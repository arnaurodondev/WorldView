"""Unit tests for silver-layer body/title recovery (BUG #34 + BUG #35).

BUG #34 — ``download_article`` must recover the article *prose* even when the
silver ``body`` holds a raw content-ingestion JSON envelope re-encoded as a
string (EODHD ``content``, NewsAPI ``content``/``description``, Yahoo/seed
``summary``).  Without this, the whole JSON string is handed to the sectioner
and chunk_index=0 becomes the envelope rather than the article body.

BUG #35 — ``extract_title_from_silver`` must recover a title from the silver
envelope (top-level, or the inner raw-news JSON inside ``body``) when the Kafka
event carries no ``title`` (sec_edgar / newsapi), so ``chunks.title_denorm`` is
populated and the learned router is no longer blind.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.blocks.storage import (
    download_article,
    extract_title_from_silver,
)

# A canonical content-store silver key (BUG #34 fixes only touch the payload, not
# the key; we still need a valid key so the S-006 guard does not reject it).
_KEY = "content-store/canonical/019eb4eb-5112-7b07-91ee-08b7fad1557f/body.json"
_BUCKET = "worldview-silver"


def _storage_returning(payload: bytes | str) -> Any:
    """Build a storage double whose ``get_bytes`` returns *payload*."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else payload
    storage = AsyncMock()
    storage.get_bytes = AsyncMock(return_value=raw)
    return storage


# ── BUG #34: download_article body recovery ───────────────────────────────────


@pytest.mark.asyncio
async def test_plain_prose_body_returned_unchanged() -> None:
    """A well-formed silver envelope with prose ``body`` is returned as-is."""
    envelope = {"doc_id": "x", "source_type": "eodhd", "body": "Revenue grew 12% YoY."}
    storage = _storage_returning(json.dumps(envelope))

    text = await download_article(storage, _BUCKET, _KEY)

    assert text == "Revenue grew 12% YoY."


@pytest.mark.asyncio
async def test_eodhd_doubly_encoded_body_recovers_inner_content() -> None:
    """BUG #34: ``body`` holds a stringified EODHD JSON → recover inner ``content``."""
    inner = {
        "date": "2026-06-10T17:23:00+00:00",
        "title": "Ford Q1 cash flow",
        "link": "https://example.com/ford",
        "symbols": ["F"],
        "tags": ["earnings"],
        "sentiment": {"polarity": 0.1},
        "content": "Ford Motor Company reported robust EBIT performance.",
    }
    envelope = {"source_type": "eodhd", "body": json.dumps(inner)}
    storage = _storage_returning(json.dumps(envelope))

    text = await download_article(storage, _BUCKET, _KEY)

    assert text == "Ford Motor Company reported robust EBIT performance."
    # The JSON envelope must NOT leak through as the document text.
    assert not text.lstrip().startswith("{")


@pytest.mark.asyncio
async def test_yahoo_seed_body_recovers_summary() -> None:
    """BUG #34: Yahoo/seed shape has no ``content`` — fall back to ``summary``."""
    inner = {
        "date": "2026-04-24T13:16:47+00:00",
        "title": "Tesla financial news",
        "url": "https://finance.yahoo.com/news/tesla",
        "source": "Yahoo Finance",
        "summary": "Financial news update for Tesla as of April 26, 2026.",
    }
    envelope = {"source_type": "eodhd", "body": json.dumps(inner)}
    storage = _storage_returning(json.dumps(envelope))

    text = await download_article(storage, _BUCKET, _KEY)

    assert text == "Financial news update for Tesla as of April 26, 2026."


@pytest.mark.asyncio
async def test_raw_json_without_top_level_body_is_unwrapped() -> None:
    """BUG #34: a payload with no top-level ``body`` (bare raw envelope) recovers."""
    raw_envelope = {
        "author": "Jane",
        "content": "SpaceX, OpenAI, Anthropic drive a mega IPO revival on Wall Street.",
        "description": "short desc",
        "title": "IPO revival",
    }
    storage = _storage_returning(json.dumps(raw_envelope))

    text = await download_article(storage, _BUCKET, _KEY)

    # ``body`` is absent, so the fall-through path runs _recover_prose on the
    # whole decoded JSON and pulls ``content`` (first prose field after body).
    assert text == "SpaceX, OpenAI, Anthropic drive a mega IPO revival on Wall Street."


@pytest.mark.asyncio
async def test_non_json_payload_returned_as_text() -> None:
    """A genuinely non-JSON silver payload is returned verbatim."""
    storage = _storage_returning("Just plain prose, no JSON here.")

    text = await download_article(storage, _BUCKET, _KEY)

    assert text == "Just plain prose, no JSON here."


@pytest.mark.asyncio
async def test_json_without_recognised_prose_field_falls_back_to_text() -> None:
    """An unrecognised JSON object is kept intact (never silently dropped)."""
    envelope = {"body": json.dumps({"foo": "bar", "symbols": ["X"]})}
    storage = _storage_returning(json.dumps(envelope))

    text = await download_article(storage, _BUCKET, _KEY)

    # No prose field in the inner dict → return the inner JSON string unchanged
    # rather than dropping content; the sectioner's synthetic fallback handles it.
    assert json.loads(text) == {"foo": "bar", "symbols": ["X"]}


# ── BUG #35: extract_title_from_silver ────────────────────────────────────────


@pytest.mark.asyncio
async def test_title_recovered_from_envelope_top_level() -> None:
    """Envelope-level ``title`` (typical eodhd) is returned directly."""
    envelope = {"title": "Apple beats estimates", "body": "prose"}
    storage = _storage_returning(json.dumps(envelope))

    title = await extract_title_from_silver(storage, _BUCKET, _KEY)

    assert title == "Apple beats estimates"


@pytest.mark.asyncio
async def test_title_recovered_from_inner_newsapi_body() -> None:
    """BUG #35: NewsAPI has no top-level title — recover it from inner ``body`` JSON."""
    inner = {
        "author": "Jane",
        "title": "SpaceX, OpenAI, Anthropic drive mega IPO revival",
        "content": "...",
        "description": "...",
    }
    envelope = {"title": None, "body": json.dumps(inner)}
    storage = _storage_returning(json.dumps(envelope))

    title = await extract_title_from_silver(storage, _BUCKET, _KEY)

    assert title == "SpaceX, OpenAI, Anthropic drive mega IPO revival"


@pytest.mark.asyncio
async def test_title_none_when_absent_everywhere() -> None:
    """BUG #35: genuine title-less sec_edgar filing → None (keeps C-8 fallback)."""
    envelope = {"title": None, "source_type": "sec_edgar", "body": "Item 1. Business ..."}
    storage = _storage_returning(json.dumps(envelope))

    title = await extract_title_from_silver(storage, _BUCKET, _KEY)

    assert title is None


@pytest.mark.asyncio
async def test_title_none_when_storage_missing() -> None:
    """No storage configured → None, never raise."""
    assert await extract_title_from_silver(None, _BUCKET, _KEY) is None
